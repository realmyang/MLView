"""NB - `.ipynb` ingest (CONTRACTS 11.29).

Four things are under test here, in this order of importance:

1. **The default path is untouched.** Without `--include-notebooks` a notebook
   is counted and skipped, with the message it has always carried, and a
   workspace with no notebooks emits byte-identical bytes either way.
2. **The acceptance criteria from ROADMAP's NB entry**: the four-cell leak
   notebook exits 0, reports `filesAnalyzed 1` and fires MLV101 and MLV201
   with the right cell indices; `execution_count [1, 3, 2, 4]` emits the
   out-of-order diagnostic and its MLV101 confidence is *strictly* lower than
   the same code in a `.py`.
3. **Locations still re-open and slice** (R2.1) - the generated module is a
   real file on disk and `test_locations.check_document` is run against it.
4. **Line counts are 1:1** through every magic shape the converter claims to
   handle, because that is the single assumption every cell index rests on.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest

from core_support import FIXTURES, REPO_ROOT, validate, write_files
from mlview.api import AnalyzeOptions, analyze_to_dict
from mlview.ingest.notebook import (MAGIC_LINE, SHADOW_DIR, convert,
                                    shadow_relpath)
from mlview.rules.confidence import NOTEBOOK_ORDER_FACTOR, ORDER_SENSITIVE_CODES
from test_locations import check_document

NOTEBOOKS = os.path.join(FIXTURES, "notebooks")

#: Exactly the code of `fixtures/notebooks/leak.ipynb`, as one plain module.
#: The comparison the acceptance criterion asks for is "the same code in a
#: `.py`", so it has to really be the same code.
LEAK_AS_PY = """import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

raw = np.load("features.npz")
X = raw["features"]
y = raw["labels"]

scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)
X_train, X_test, y_train, y_test = train_test_split(
    X_scaled, y, test_size=0.2, random_state=0)

model = nn.Sequential(nn.Linear(10, 3))
criterion = nn.CrossEntropyLoss()
optimizer = optim.Adam(model.parameters(), lr=0.001)
ds = TensorDataset(torch.tensor(X_train), torch.tensor(y_train))
train_loader = DataLoader(ds, batch_size=32, shuffle=True)
for features, labels in train_loader:
    outputs = model(features)
    loss = criterion(outputs, labels)
    loss.backward()
    optimizer.step()
"""


@pytest.fixture
def notebook_ws(tmp_path):
    """Copy named notebook fixtures into a fresh workspace and return its root.

    Fixtures are copied rather than analyzed in place: analysis materialises a
    generated module under `<root>/.mlview/notebooks/`, and the repository is
    not a scratch directory.
    """
    counter = {"n": 0}

    def _make(*names, **extra):
        counter["n"] += 1
        root = tmp_path / ("nb%d" % counter["n"])
        root.mkdir(parents=True, exist_ok=True)
        for name in names:
            shutil.copyfile(os.path.join(NOTEBOOKS, name), str(root / name))
        if extra:
            write_files(str(root), extra)
        return str(root).replace("\\", "/")

    return _make


def _analyze(root, **kwargs):
    return analyze_to_dict(AnalyzeOptions(paths=(root,), **kwargs))


def _diagnostics(doc, kind):
    return [d for d in doc["diagnostics"] if d["kind"] == kind]


def _issue(doc, code):
    found = [i for i in doc["issues"] if i["code"] == code]
    assert found, "%s did not fire; codes were %s" % (
        code, sorted({i["code"] for i in doc["issues"]}))
    return found[0]


def _cell_of(doc, code):
    """`(cell, cellLine)` for the node an issue is anchored on."""
    issue = _issue(doc, code)
    nodes = {n["id"]: n for n in doc["nodes"]}
    node = nodes[issue["nodeIds"][0]]
    return int(node["attrs"]["cell"]), int(node["attrs"]["cellLine"])


# ------------------------------------------------------- the default path
def test_without_the_flag_a_notebook_is_still_counted_and_skipped(notebook_ws):
    root = notebook_ws("leak.ipynb", **{"train.py": "import torch\n"})
    doc = _analyze(root)
    assert doc["workspace"]["notebooksSkipped"] == 1
    assert doc["workspace"]["filesAnalyzed"] == 1
    skipped = _diagnostics(doc, "notebook_skipped")
    assert skipped and skipped[0]["count"] == 1
    assert skipped[0]["message"] == (
        "1 notebook(s) detected but not analyzed in this version.")
    assert not _diagnostics(doc, "notebook_analyzed")
    assert not os.path.isdir(os.path.join(root, SHADOW_DIR))
    assert validate(doc) == []


def test_the_flag_changes_nothing_at_all_without_a_notebook(analyze_ws, make_workspace):
    """The byte-identity claim, stated as an equality over the document."""
    files = {"train.py": LEAK_AS_PY}
    root = make_workspace(files)
    plain = _analyze(root)
    with_flag = _analyze(root, include_notebooks=True)
    for doc in (plain, with_flag):
        doc["workspace"].pop("root", None)
        # `generatedAt` is a field of `generator`, not of the document (see
        # `contracts/graph.sample.json`). Popping it at the top level popped
        # nothing, so this equality was really asserting that two consecutive
        # analyses land in the same WALL-CLOCK SECOND -- green on a fast machine
        # and red the moment CI straddles a second boundary, which is what
        # `e2e (ubuntu, sh)` caught. The claim under test is that the flag
        # changes nothing; the clock is not part of it.
        doc["generator"].pop("generatedAt", None)
        doc.pop("stats", None)
        for loc_owner in doc["nodes"] + doc["edges"] + doc["issues"]:
            loc_owner["loc"].pop("absFile", None)
    assert json.dumps(with_flag, sort_keys=True) == json.dumps(plain, sort_keys=True)


# --------------------------------------------------- ROADMAP NB acceptance
def test_the_four_cell_leak_notebook_is_analyzed(notebook_ws):
    root = notebook_ws("leak.ipynb")
    doc = _analyze(root, include_notebooks=True)

    assert doc["workspace"]["filesAnalyzed"] == 1
    assert doc["workspace"]["notebooksSkipped"] == 0
    assert validate(doc) == []

    # MLV101's `fit_transform` is cell 2 line 2; MLV201's batch loop is cell 3
    # line 6. Both indices count the markdown cells a notebook may carry, which
    # is what a host needs to address the cell.
    assert _cell_of(doc, "MLV101") == (2, 2)
    assert _cell_of(doc, "MLV201") == (3, 6)

    analyzed = _diagnostics(doc, "notebook_analyzed")
    assert len(analyzed) == 1
    assert analyzed[0]["file"] == "leak.ipynb"
    assert analyzed[0]["count"] == 4
    assert "is monotonic" in analyzed[0]["message"]
    assert "codes" not in analyzed[0]


def test_the_leak_notebook_exits_zero_through_the_cli(notebook_ws):
    root = notebook_ws("leak.ipynb")
    env = dict(os.environ, PYTHONPATH=os.path.join(REPO_ROOT, "analyzer", "src"),
               PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.run(
        [sys.executable, "-m", "mlview", "analyze", root, "--include-notebooks"],
        capture_output=True, text=True, env=env, cwd=REPO_ROOT)
    assert proc.returncode == 0, proc.stderr
    assert "1 files analyzed" in proc.stdout
    assert "0 notebooks skipped" in proc.stdout
    assert "MLV101" in proc.stdout and "MLV201" in proc.stdout


def test_an_out_of_order_notebook_says_so_and_de_rates_order_rules(notebook_ws,
                                                                   make_workspace):
    ordered = _analyze(notebook_ws("leak.ipynb"), include_notebooks=True)
    shuffled = _analyze(notebook_ws("leak_out_of_order.ipynb"),
                        include_notebooks=True)
    plain = _analyze(make_workspace({"leak.py": LEAK_AS_PY}))

    note = _diagnostics(shuffled, "notebook_analyzed")
    assert len(note) == 1
    assert "[1, 3, 2, 4]" in note[0]["message"]
    assert "NOT monotonic" in note[0]["message"]
    assert note[0]["codes"] == list(ORDER_SENSITIVE_CODES)
    # `codes` on a `notebook_analyzed` is a RuleCode array, so the document has
    # to stay schema-valid with it set - not only in the in-order case.
    assert validate(shuffled) == []

    py_confidence = _issue(plain, "MLV101")["confidence"]
    # An in-order notebook scores exactly what the same code in a `.py` does:
    # the provenance factor has weight 1.0, which is an identity in the product.
    assert _issue(ordered, "MLV101")["confidence"] == py_confidence
    # Out of order, strictly lower - and by the declared factor, not by luck.
    shuffled_confidence = _issue(shuffled, "MLV101")["confidence"]
    assert shuffled_confidence < py_confidence
    assert shuffled_confidence == pytest.approx(
        py_confidence * NOTEBOOK_ORDER_FACTOR, abs=0.002)

    # MLV201 is not order-sensitive, so it is untouched by the caveat.
    assert _issue(shuffled, "MLV201")["confidence"] == _issue(plain, "MLV201")["confidence"]


def test_the_de_rating_is_stated_in_the_evidence(notebook_ws):
    doc = _analyze(notebook_ws("leak_out_of_order.ipynb"), include_notebooks=True)
    evidence = _issue(doc, "MLV101")["evidence"]
    notes = [e for e in evidence if "leak_out_of_order.ipynb" in e["detail"]]
    assert len(notes) == 1, "exactly one notebook factor per finding"
    assert notes[0]["kind"] == "context_confirmed"
    assert notes[0]["weight"] == NOTEBOOK_ORDER_FACTOR
    assert "cell 2, line 2" in notes[0]["detail"]
    assert "de-rated" in notes[0]["detail"]


# ------------------------------------------------------------ R2.1 / locs
def test_notebook_locations_re_open_and_slice(notebook_ws):
    root = notebook_ws("leak.ipynb", "odd_cells.ipynb")
    doc = _analyze(root, include_notebooks=True)

    def read(relpath):
        with open(os.path.join(root, relpath), encoding="utf-8") as handle:
            return handle.read()

    check_document(doc, read)
    for node in doc["nodes"]:
        assert node["loc"]["file"].startswith(SHADOW_DIR + "/")
        assert node["loc"]["absFile"] == "%s/%s" % (doc["workspace"]["root"],
                                                    node["loc"]["file"])


def test_the_generated_module_is_materialised_where_it_says_it_is(notebook_ws):
    root = notebook_ws("leak.ipynb")
    doc = _analyze(root, include_notebooks=True)
    shadow = shadow_relpath("leak.ipynb")
    assert shadow == ".mlview/notebooks/leak.py"
    assert os.path.isfile(os.path.join(root, shadow))
    assert _diagnostics(doc, "notebook_analyzed")[0]["message"].count(shadow) == 1


def test_a_second_run_does_not_discover_the_generated_module_as_source(notebook_ws):
    root = notebook_ws("leak.ipynb")
    first = _analyze(root, include_notebooks=True)
    second = _analyze(root, include_notebooks=True)
    assert first["workspace"]["filesAnalyzed"] == 1
    assert second["workspace"]["filesAnalyzed"] == 1
    assert len(second["nodes"]) == len(first["nodes"])


# ------------------------------------------------------------- conversion
def _lines_of(source):
    return source.split("\n")


def test_every_cell_keeps_its_line_count_exactly():
    with open(os.path.join(NOTEBOOKS, "odd_cells.ipynb"), encoding="utf-8") as handle:
        raw = handle.read()
    source, nbmap, error = convert(raw, "odd_cells.ipynb")
    assert error is None
    cells = json.loads(raw)["cells"]
    lines = _lines_of(source)
    for cell in nbmap.cells:
        original = cells[cell.index]["source"]
        text = original if isinstance(original, str) else "".join(original)
        expected = text.split("\n")
        if expected and expected[-1] == "":
            expected.pop()
        assert cell.lineCount == len(expected), "cell %d" % cell.index
        for offset in range(cell.lineCount):
            assert lines[cell.startLine - 1 + offset] is not None


def test_a_non_python_cell_magic_blanks_the_whole_cell():
    source, nbmap, error = convert(json.dumps({"cells": [
        {"cell_type": "code", "execution_count": 1,
         "source": ["%%bash\n", "for f in *.csv; do\n", "  echo $f\n", "done\n"]},
    ]}), "shell.ipynb")
    assert error is None
    body = _lines_of(source)[nbmap.cells[0].startLine - 1:][:4]
    assert body == [MAGIC_LINE] * 4


def test_a_wrapping_line_magic_keeps_its_statement():
    source, nbmap, _ = convert(json.dumps({"cells": [
        {"cell_type": "code", "execution_count": 1,
         "source": ["%time model.fit(X, y)\n", "%timeit -n 100 f()\n",
                    "if True:\n", "    %time g()\n"]},
    ]}), "timed.ipynb")
    body = _lines_of(source)[nbmap.cells[0].startLine - 1:][:4]
    # The statement survives; only the column moves, and the line count does not.
    assert body[0] == "model.fit(X, y)"
    assert body[2:] == ["if True:", "    g()"]
    # `-n 100` is not Python, so guessing would cost the whole notebook.
    assert body[1] == MAGIC_LINE


def test_a_percent_inside_a_string_or_a_bracket_is_not_a_magic():
    source, nbmap, _ = convert(json.dumps({"cells": [
        {"cell_type": "code", "execution_count": 1,
         "source": ["Q = '''\n", "% not a magic\n", "'''\n",
                    "total = (10\n", "         % 3)\n"]},
    ]}), "strings.ipynb")
    body = _lines_of(source)[nbmap.cells[0].startLine - 1:][:5]
    assert MAGIC_LINE not in body
    assert nbmap.magicLines == 0


def test_source_may_be_a_string_and_cell_indices_count_markdown():
    source, nbmap, error = convert(json.dumps({"cells": [
        {"cell_type": "markdown", "source": "# Title\n"},
        {"cell_type": "code", "execution_count": 1, "source": "x = 1\ny = 2\n"},
    ]}), "stringy.ipynb")
    assert error is None
    assert [c.index for c in nbmap.cells] == [1]
    assert nbmap.cells[0].lineCount == 2
    assert nbmap.totalCells == 2
    assert _lines_of(source)[nbmap.cells[0].startLine - 1] == "x = 1"


@pytest.mark.parametrize("counts,ok", [
    ([1, 2, 3, 4], True),
    ([1, 3, 2, 4], False),
    ([None, None], True),
    ([1, None, 2], True),
    ([2, 1], False),
    ([1, 1], False),
])
def test_execution_order_verdict(counts, ok):
    cells = [{"cell_type": "code", "execution_count": c, "source": "pass\n"}
             for c in counts]
    _source, nbmap, _error = convert(json.dumps({"cells": cells}), "order.ipynb")
    assert nbmap.orderOk is ok


def test_a_notebook_with_no_cells_key_is_a_failure_not_a_silence(notebook_ws):
    root = notebook_ws("broken.ipynb")
    doc = _analyze(root, include_notebooks=True)
    assert doc["workspace"]["notebooksSkipped"] == 1
    errors = _diagnostics(doc, "parse_error")
    assert [e["file"] for e in errors] == ["broken.ipynb"]
    assert "invalid notebook JSON" in errors[0]["message"]
    skipped = _diagnostics(doc, "notebook_skipped")
    assert skipped and skipped[0]["count"] == 1
    assert "broken.ipynb" in skipped[0]["message"]
    assert validate(doc) == []


def test_notebooks_skipped_never_becomes_zero_because_the_flag_was_on(notebook_ws):
    root = notebook_ws("leak.ipynb", "broken.ipynb")
    doc = _analyze(root, include_notebooks=True)
    assert doc["workspace"]["notebooksSkipped"] == 1
    assert doc["workspace"]["filesAnalyzed"] == 1
    assert len(_diagnostics(doc, "notebook_analyzed")) == 1


# ------------------------------------------------------------------ config
# `.mlview.toml` needs a TOML parser, and tomllib is stdlib only from 3.11.
# Below that `rules/suppress.py` ignores the file and appends a `config_warning`,
# so on 3.10 the two tests under this mark would be asserting the behaviour of a
# parser that is not there: `[paths] notebooks` is never read, notebooks stay
# skipped, and the near-miss warning is never computed. The degradation itself is
# asserted by
# `analyzer/tests/rules/test_suppression.py::test_a_missing_tomllib_says_so_instead_of_pretending`.
# Same mark, same reason, as `tests/core/test_cleanup.py`,
# `tests/core/test_robustness.py` and `tests/rules/test_suppression.py`. The FLAG
# path — `--include-notebooks` and `AnalyzeOptions.include_notebooks` — needs no
# parser and is gated on every version in the matrix, so NB's acceptance is not
# what is being skipped here.
NEEDS_TOMLLIB = pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="tomllib is stdlib from 3.11; .mlview.toml is ignored with a config_warning below that",
)


@NEEDS_TOMLLIB
def test_the_toml_opt_in_turns_notebooks_on(notebook_ws):
    root = notebook_ws("leak.ipynb", **{
        ".mlview.toml": "[paths]\nnotebooks = true\n"})
    doc = _analyze(root)
    assert doc["workspace"]["filesAnalyzed"] == 1
    assert doc["workspace"]["notebooksSkipped"] == 0
    assert _diagnostics(doc, "notebook_analyzed")


@NEEDS_TOMLLIB
def test_a_non_boolean_toml_value_is_a_config_warning(notebook_ws):
    root = notebook_ws("leak.ipynb", **{
        ".mlview.toml": '[paths]\nnotebooks = "yes"\n'})
    doc = _analyze(root)
    assert doc["workspace"]["notebooksSkipped"] == 1
    warnings = [d["message"] for d in _diagnostics(doc, "config_warning")]
    assert any("notebooks must be true or false" in w for w in warnings)


def test_an_excluded_notebook_is_neither_counted_nor_analyzed(notebook_ws):
    """`--exclude` has always removed a notebook from the count as well as
    from the analysis, and the flag does not change that."""
    root = notebook_ws("leak.ipynb")
    doc = _analyze(root, include_notebooks=True, exclude=("**/leak.ipynb",))
    assert doc["workspace"]["notebooksSkipped"] == 0
    assert doc["workspace"]["filesAnalyzed"] == 0
    assert not _diagnostics(doc, "notebook_analyzed")


def test_an_include_filter_leaves_the_notebook_counted(notebook_ws):
    """`--include` narrows what is *analyzed*; it never narrowed the notebook
    count, so a notebook outside the filter stays a declared skip rather than
    disappearing."""
    root = notebook_ws("leak.ipynb")
    doc = _analyze(root, include_notebooks=True, include=("src/**",))
    assert doc["workspace"]["notebooksSkipped"] == 1
    assert not _diagnostics(doc, "notebook_analyzed")
    assert _diagnostics(doc, "notebook_skipped")[0]["count"] == 1
