"""ROB - hardening round 1, the robustness battery.

Everything here is an *input* the analyzer does not control: syntax it has
never seen, bytes that are not UTF-8, a directory it may not read, a file that
is not a file, a notebook a human never meant to be Python. The bar is the one
the product rests on: **degrade to a diagnostic, never to a traceback, a hang,
or a silent hole**.

The battery is in two halves.

*Regression guards* (the majority) pin behaviour that is already correct, so a
later change cannot quietly lose it. The most important of them is
`test_every_syntax_fixture_keeps_its_training_loop`: twenty programs, each
leaning on one Python feature (`match`, walrus, PEP 695 generics, async,
metaclasses, `exec`, circular imports, a module named `torch.py`, ...), and
every one of them must still show its training loop. A dropped loop is the
second-worst failure this product can have.

*Known defects*, each `xfail` with its finding id and each carrying the exact
input that produces it. **Remove the marker with the fix, not before.**

| id | what | fix belongs to |
|---|---|---|
| ROB-01 | a deep-but-legal AST (a 700-branch `elif`, a 1200-term expression) raises `RecursionError` out of `ir.scopes` and the whole run exits 3 with no document | analyzer |
| ROB-02 | discovery hands `ingest.parse.read_bytes` any path, so a FIFO named `*.py` blocks the process for ever and a `*.py` symlink to `/dev/zero` reads until memory runs out | analyzer |
| ROB-03 | two findings of one rule in one scope on one symbol get the same `Issue.id`; CONTRACTS section 0 says ids are globally unique | analyzer |
| ROB-04 | a directory `os.walk` cannot enter vanishes from the analysis with no diagnostic at all | analyzer |
| ROB-05 | a shell escape continued with a backslash costs the **whole** notebook | analyzer |
| ROB-06 | `--min-confidence 5` silently hides every finding and turns `--fail-on high` green | analyzer |
| ROB-07 | an unwritable `--json` / `--html` path exits 3 (internal error) where the CLI contract says 1 (I/O) | analyzer |
| ROB-08 | a `.mlview.toml` saved with a UTF-8 BOM is rejected whole | analyzer |
| ROB-09 | one `from x import *` inside the workspace makes the `objective` stage read as absent on code that builds a `CrossEntropyLoss` | analyzer |
"""

from __future__ import annotations

import collections
import json
import os
import shutil
import stat
import subprocess
import sys
import threading

import pytest

from core_support import FIXTURES, REPO_ROOT, validate
from mlview.api import AnalyzeOptions, analyze_to_dict

ROBUSTNESS = os.path.join(FIXTURES, "robustness")
SYNTAX = os.path.join(ROBUSTNESS, "syntax")
NOTEBOOKS = os.path.join(ROBUSTNESS, "notebooks")

#: Every syntax fixture builds a training loop except this one, which is a
#: workspace whose `torch` is a local module of the same name and therefore has
#: no framework in it at all.
NO_LOOP = {"shadowed_stdlib"}

TRAIN = (
    "import torch\n"
    "import torch.nn as nn\n"
    "from torch.utils.data import DataLoader\n"
    "\n"
    "\n"
    "def train(ds):\n"
    "    model = nn.Linear(16, 3)\n"
    "    opt = torch.optim.Adam(model.parameters())\n"
    "    crit = nn.CrossEntropyLoss()\n"
    "    loader = DataLoader(ds, batch_size=8, shuffle=True)\n"
    "    for xb, yb in loader:\n"
    "        opt.zero_grad()\n"
    "        loss = crit(model(xb), yb)\n"
    "        loss.backward()\n"
    "        opt.step()\n"
    "    return model\n"
)


# --------------------------------------------------------------- helpers
#: A fixture whose *source* needs a newer interpreter than the one running the
#: suite. MLView parses with the host's own `ast`, so on an older Python these
#: files are not analyzable at all - `pep695`'s `type Batch = ...` and
#: `class Runner[T]`, and `fstrings`' PEP 701 `f"{names["loss"]}"` (the same
#: quote reused inside the f-string), are each a SyntaxError before 3.12. Both
#: read green on a 3.13 laptop and red on the matrix, which is the argument for
#: the matrix. Analysing them there would
#: assert the wrong thing: `filesFailed == 0` is a claim about a file the host
#: can read. The general claim - a file the host cannot parse becomes a counted
#: `parse_error` and never a crash - is held by
#: `test_a_syntax_error_is_one_diagnostic_and_the_siblings_survive` and by the
#: ELOOP case below, on every version.
MIN_PYTHON = {"pep695": (3, 12), "fstrings": (3, 12)}


def syntax_programs():
    """Every fixture directory, each skipped on a host that cannot read it."""
    out = []
    for name in sorted(os.listdir(SYNTAX)):
        if not os.path.isdir(os.path.join(SYNTAX, name)):
            continue
        needs = MIN_PYTHON.get(name)
        marks = ()
        if needs is not None:
            marks = pytest.mark.skipif(
                sys.version_info < needs,
                reason="%s is %d.%d+ syntax; MLView parses with the host's ast"
                       % (name, needs[0], needs[1]))
        out.append(pytest.param(name, marks=marks, id=name))
    return out


def analyze(path, **kwargs):
    return analyze_to_dict(AnalyzeOptions(paths=(str(path),), **kwargs))


def diagnostics(doc, kind):
    return [d for d in doc["diagnostics"] if d["kind"] == kind]


def stage_present(doc, stage_id):
    return next(s for s in doc["stages"] if s["id"] == stage_id)["present"]


def run_cli(*argv, timeout=180, cwd=None):
    """Run the CLI in a child process. Returns (rc, stdout, stderr)."""
    env = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.run([sys.executable, "-m", "mlview"] + [str(a) for a in argv],
                          capture_output=True, cwd=cwd or REPO_ROOT, env=env,
                          timeout=timeout)
    return (proc.returncode,
            proc.stdout.decode("utf-8", "replace"),
            proc.stderr.decode("utf-8", "replace"))


def write_bytes(root, relpath, raw):
    target = os.path.join(str(root), relpath)
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(target, "wb") as fh:
        fh.write(raw)
    return target


def elif_chain(branches):
    """A model registry written as one long `elif` chain - the shape a code
    generator emits and a hand-written file never does."""
    out = ["import torch.nn as nn\n", "\n", "\n", "def build(name):\n",
           "    if name == 'a0':\n        return nn.Linear(1, 1)\n"]
    for i in range(branches):
        out.append("    elif name == 'a%d':\n        return nn.Linear(%d, 1)\n"
                   % (i + 1, i + 2))
    out.append("    return None\n")
    return "".join(out)


# ======================================================= regression guards
@pytest.mark.parametrize("program", syntax_programs())
def test_every_syntax_fixture_analyzes_without_incident(program):
    """Twenty Python features, twenty schema-valid documents, zero failures."""
    doc = analyze(os.path.join(SYNTAX, program))
    assert validate(doc) == [], program
    assert doc["workspace"]["filesFailed"] == 0, program
    assert doc["workspace"]["filesAnalyzed"] >= 1, program


@pytest.mark.parametrize("program",
                         [p for p in syntax_programs() if p.id not in NO_LOOP])
def test_every_syntax_fixture_keeps_its_training_loop(program):
    """The one claim a static analyzer must never get wrong quietly.

    Each of these programs writes an ordinary `zero_grad / backward / step`
    loop and wraps it in one syntax feature. The loop has to survive the
    feature: `train` present, and at least one node whose kind says so.
    """
    doc = analyze(os.path.join(SYNTAX, program))
    assert stage_present(doc, "train"), "%s lost its train stage" % program
    loops = [n for n in doc["nodes"] if n["kind"] == "train_loop"]
    assert loops, "%s: no train_loop node survived" % program


@pytest.mark.parametrize("program", syntax_programs())
def test_syntax_fixtures_are_identical_under_ip_dataflow(program):
    """`--dataflow ip` is additive: it may add findings, never lose a stage."""
    local = analyze(os.path.join(SYNTAX, program))
    ip = analyze(os.path.join(SYNTAX, program), dataflow="ip")
    assert validate(ip) == [], program
    local_stages = {s["id"] for s in local["stages"] if s["present"]}
    ip_stages = {s["id"] for s in ip["stages"] if s["present"]}
    assert local_stages <= ip_stages, (
        "%s: --dataflow ip dropped stage(s) %s"
        % (program, sorted(local_stages - ip_stages)))


@pytest.mark.parametrize("budget", [20, 45, 100, 400])
def test_node_budgets_never_lose_a_finding(budget):
    """PERF-04's rollup is a zoom, not a deletion: the issue list is invariant."""
    full = analyze(SYNTAX + "/deep_nesting")
    capped = analyze(SYNTAX + "/deep_nesting", max_nodes=budget)
    assert validate(capped) == []
    assert ({i["id"] for i in capped["issues"]}
            == {i["id"] for i in full["issues"]}), budget
    assert len(capped["nodes"]) <= max(budget, len(full["nodes"]))


def test_hostile_encodings_each_become_one_diagnostic(tmp_path):
    """Eight byte-level hostilities, one healthy file, one honest document."""
    root = tmp_path / "encodings"
    root.mkdir()
    write_bytes(root, "good.py", TRAIN.encode("utf-8"))
    write_bytes(root, "zero.py", b"")
    write_bytes(root, "bom.py", b"\xef\xbb\xbf" + TRAIN.encode("utf-8"))
    write_bytes(root, "crlf_tabs.py",
                TRAIN.replace("    ", "\t").replace("\n", "\r\n").encode("utf-8"))
    write_bytes(root, "declared_latin1.py",
                b'# -*- coding: latin-1 -*-\nMODEL = "caf\xe9"\nimport torch\n')
    write_bytes(root, "raw_latin1.py", b'MODEL = "caf\xe9"\nimport torch\n')
    write_bytes(root, "utf16.py", "import torch\nX = 1\n".encode("utf-16"))
    write_bytes(root, "nul.py", b"import torch\nx = 1\x00\ny = 2\n")
    write_bytes(root, "binary.py", bytes(range(256)) * 64)
    write_bytes(root, "tab_error.py", b"def f():\n    x = 1\n\ty = 2\n\treturn x\n")

    doc = analyze(root)
    assert validate(doc) == []
    failed = {d["file"] for d in diagnostics(doc, "parse_error")}
    assert failed == {"raw_latin1.py", "utf16.py", "nul.py", "binary.py",
                      "tab_error.py"}
    # the three that ARE decodable were decoded, not skipped
    analyzed_ok = doc["workspace"]["filesAnalyzed"]
    assert analyzed_ok >= 4, doc["workspace"]
    assert doc["workspace"]["filesFailed"] == len(failed)
    # a BOM + CRLF + tab file keeps a usable snippet: no stray carriage return
    assert all("\r" not in (n["loc"].get("snippet") or "") for n in doc["nodes"])
    # and the healthy file is still a whole pipeline
    assert stage_present(doc, "train")


def test_symlink_loops_and_dangling_links_terminate(tmp_path):
    """`os.walk` must not follow a symlink into itself, and a dead `*.py`
    symlink is a diagnostic rather than a crash."""
    root = tmp_path / "links"
    (root / "loop").mkdir(parents=True)
    write_bytes(root, "good.py", TRAIN.encode("utf-8"))
    write_bytes(root, "loop/mod.py", TRAIN.encode("utf-8"))
    try:
        os.symlink("..", str(root / "loop" / "up"))
        os.symlink(".", str(root / "self"))
        os.symlink("real", str(root / "alias"))
        os.symlink("nowhere_at_all.py", str(root / "gone.py"))
    except (OSError, NotImplementedError):   # Windows without developer mode
        pytest.skip("this platform will not create symlinks")

    doc = analyze(root)                      # must simply return
    assert validate(doc) == []
    assert doc["workspace"]["filesAnalyzed"] == 2
    dead = diagnostics(doc, "parse_error")
    assert [d["file"] for d in dead] == ["gone.py"]
    assert "cannot read file" in dead[0]["message"]


def test_odd_file_and_directory_names_survive_the_round_trip(tmp_path):
    """A newline, a quote, a semicolon, a leading dash, Cyrillic and CJK in
    paths - every `loc.file` still round-trips through JSON."""
    root = tmp_path / "odd"
    root.mkdir()
    names = ["-rf.py", " leading space.py", "semi;colon.py", "quote'.py",
             "new\nline.py", os.path.join("модели",
                                          "träin_模型.py")]
    written = []
    for name in names:
        try:
            write_bytes(root, name, TRAIN.encode("utf-8"))
            written.append(name.replace(os.sep, "/"))
        except OSError:                      # a filesystem that refuses one
            continue
    doc = analyze(root)
    assert validate(doc) == []
    assert doc["workspace"]["filesAnalyzed"] == len(written)
    reparsed = json.loads(json.dumps(doc))
    assert {n["loc"]["file"] for n in reparsed["nodes"]} <= set(written)
    assert all("\\" not in n["loc"]["file"] for n in doc["nodes"])


def test_a_directory_named_like_a_module_is_walked_not_parsed(tmp_path):
    root = tmp_path / "dirpy"
    (root / "package.py").mkdir(parents=True)
    write_bytes(root, "good.py", TRAIN.encode("utf-8"))
    write_bytes(root, os.path.join("package.py", "inner.py"), TRAIN.encode("utf-8"))
    doc = analyze(root)
    assert validate(doc) == []
    assert doc["workspace"]["filesAnalyzed"] == 2
    assert doc["workspace"]["filesFailed"] == 0


def test_an_unreadable_file_is_a_diagnostic(tmp_path):
    root = tmp_path / "perm"
    root.mkdir()
    write_bytes(root, "good.py", TRAIN.encode("utf-8"))
    secret = write_bytes(root, "secret.py", TRAIN.encode("utf-8"))
    os.chmod(secret, 0)
    try:
        if os.access(secret, os.R_OK):       # running as root
            pytest.skip("this process can read a mode-000 file")
        doc = analyze(root)
        assert validate(doc) == []
        errors = diagnostics(doc, "parse_error")
        assert [e["file"] for e in errors] == ["secret.py"]
        assert "Permission denied" in errors[0]["message"]
        assert doc["workspace"]["filesFailed"] == 1
    finally:
        os.chmod(secret, stat.S_IRUSR | stat.S_IWUSR)


def test_a_notebook_of_plain_magics_still_yields_its_loop(tmp_path):
    """The positive control for ROB-05: line magics, a shell escape, a help
    query and a `%%bash` cell all blank cleanly, and the training loop two
    cells later is still analyzed."""
    root = tmp_path / "nb_ok"
    root.mkdir()
    shutil.copy(os.path.join(NOTEBOOKS, "plain_magics.ipynb"),
                str(root / "plain_magics.ipynb"))
    doc = analyze(root, include_notebooks=True)
    assert validate(doc) == []
    assert doc["workspace"]["notebooksSkipped"] == 0
    assert stage_present(doc, "train")
    assert [d for d in doc["diagnostics"] if d["kind"] == "notebook_analyzed"]


def test_degenerate_notebooks_are_diagnostics_not_crashes(tmp_path):
    """Malformed JSON, a non-object document, a missing `cells`, a `cells`
    that is not a list, a string `source`, a `source` of the wrong type and a
    cell that is not a dict."""
    root = tmp_path / "nb_bad"
    root.mkdir()
    write_bytes(root, "truncated.ipynb", b'{"cells": [ {"cell_type": "code",')
    write_bytes(root, "notjson.ipynb", b"not json at all\n")
    write_bytes(root, "toplevel_list.ipynb", b"[]")
    write_bytes(root, "no_cells.ipynb", b'{"nbformat": 4}')
    write_bytes(root, "cells_object.ipynb",
                b'{"nbformat": 4, "cells": {"0": {"cell_type": "code"}}}')
    write_bytes(root, "bad_utf8.ipynb",
                b'{"cells": [], "nbformat": 4, "x": "caf\xe9"}')
    odd = {"cells": [{"cell_type": "code", "source": None},
                     {"cell_type": "code", "source": 123},
                     {"cell_type": "code", "source": {"a": 1}},
                     {"cell_type": "code"},
                     {"cell_type": "code", "source": ["import torch\n", None]},
                     "not-a-cell", None],
           "nbformat": 4}
    write_bytes(root, "odd_cells.ipynb", json.dumps(odd).encode("utf-8"))
    write_bytes(root, "good.py", TRAIN.encode("utf-8"))

    doc = analyze(root, include_notebooks=True)
    assert validate(doc) == []
    assert stage_present(doc, "train"), "the healthy sibling was still analyzed"
    skipped = diagnostics(doc, "notebook_skipped")
    assert skipped, "the unusable notebooks are declared"
    # every skipped notebook says why, by name
    assert "could not be analyzed" in skipped[0]["message"]


def test_a_string_source_notebook_is_read_the_same_as_a_list(tmp_path):
    """`source` is a list of lines in every notebook Jupyter writes and a bare
    string in plenty that other tools write."""
    cells = [["import torch\n", "import torch.nn as nn\n",
              "from torch.utils.data import DataLoader\n"],
             ["model = nn.Linear(16, 3)\n",
              "opt = torch.optim.Adam(model.parameters())\n",
              "crit = nn.CrossEntropyLoss()\n",
              "loader = DataLoader(ds, batch_size=8, shuffle=True)\n",
              "for xb, yb in loader:\n", "    opt.zero_grad()\n",
              "    loss = crit(model(xb), yb)\n", "    loss.backward()\n",
              "    opt.step()\n"]]

    def build(as_string):
        return {"cells": [{"cell_type": "code", "execution_count": i + 1,
                           "metadata": {}, "outputs": [],
                           "source": ("".join(c) if as_string else c)}
                          for i, c in enumerate(cells)],
                "metadata": {}, "nbformat": 4, "nbformat_minor": 5}

    docs = []
    for name, as_string in (("as_list", False), ("as_string", True)):
        root = tmp_path / name
        root.mkdir()
        write_bytes(root, "t.ipynb", json.dumps(build(as_string)).encode("utf-8"))
        docs.append(analyze(root, include_notebooks=True))
    for doc in docs:
        assert validate(doc) == []
        assert stage_present(doc, "train")
    assert ([n["kind"] for n in docs[0]["nodes"]]
            == [n["kind"] for n in docs[1]["nodes"]])


def test_a_huge_notebook_is_analyzed_whole(tmp_path):
    """3000 one-line cells plus a training loop: the loop is not lost in the
    offset table."""
    root = tmp_path / "huge_nb"
    root.mkdir()
    cells = [{"cell_type": "code", "execution_count": i + 1, "metadata": {},
              "outputs": [], "source": ["x%d = %d\n" % (i, i)]}
             for i in range(3000)]
    cells.append({"cell_type": "code", "execution_count": 3001, "metadata": {},
                  "outputs": [], "source": [
                      "import torch\n", "import torch.nn as nn\n",
                      "from torch.utils.data import DataLoader\n",
                      "model = nn.Linear(16, 3)\n",
                      "opt = torch.optim.Adam(model.parameters())\n",
                      "crit = nn.CrossEntropyLoss()\n",
                      "loader = DataLoader(ds, batch_size=8, shuffle=True)\n",
                      "for xb, yb in loader:\n", "    opt.zero_grad()\n",
                      "    loss = crit(model(xb), yb)\n",
                      "    loss.backward()\n", "    opt.step()\n"]})
    write_bytes(root, "huge.ipynb",
                json.dumps({"cells": cells, "metadata": {}, "nbformat": 4,
                            "nbformat_minor": 5}).encode("utf-8"))
    doc = analyze(root, include_notebooks=True)
    assert validate(doc) == []
    assert stage_present(doc, "train")
    loops = [n for n in doc["nodes"] if n["kind"] == "train_loop"]
    assert loops and loops[0]["loc"]["line"] > 3000


def test_the_same_workspace_analyzes_identically_cold_and_warm(tmp_path):
    """The fact cache may make a run faster; it may not make it different."""
    root = tmp_path / "cache_ws"
    root.mkdir()
    write_bytes(root, "train.py", TRAIN.encode("utf-8"))
    write_bytes(root, "second.py", TRAIN.replace("train", "train2").encode("utf-8"))
    shutil.rmtree(str(root / ".mlview"), ignore_errors=True)
    cold = analyze(root)
    warm = analyze(root)
    for doc in (cold, warm):
        doc["generator"].pop("generatedAt", None)
        doc["stats"].pop("durationMs", None)
    assert json.dumps(cold, sort_keys=True) == json.dumps(warm, sort_keys=True)


def test_a_read_only_mlview_directory_degrades_to_a_diagnostic(tmp_path):
    """CI checks out read-only trees. Nothing MLView writes is load-bearing."""
    root = tmp_path / "ro"
    root.mkdir()
    write_bytes(root, "train.py", TRAIN.encode("utf-8"))
    write_bytes(root, "nb.ipynb", json.dumps(
        {"cells": [{"cell_type": "code", "execution_count": 1, "metadata": {},
                    "outputs": [], "source": ["import torch\n"]}],
         "metadata": {}, "nbformat": 4, "nbformat_minor": 5}).encode("utf-8"))
    mlview_dir = root / ".mlview"
    mlview_dir.mkdir()
    os.chmod(str(mlview_dir), stat.S_IRUSR | stat.S_IXUSR)
    try:
        if os.access(str(mlview_dir), os.W_OK):
            pytest.skip("this process can write a read-only directory")
        doc = analyze(root, include_notebooks=True)
        assert validate(doc) == []
        assert stage_present(doc, "train"), "the Python half still ran"
        skipped = diagnostics(doc, "notebook_skipped")
        assert skipped and "cannot write" in skipped[0]["message"]
    finally:
        os.chmod(str(mlview_dir), stat.S_IRWXU)


def test_concurrent_runs_over_one_workspace_agree(tmp_path):
    """Eight processes, one cache directory, one answer."""
    root = tmp_path / "conc"
    root.mkdir()
    write_bytes(root, "train.py", TRAIN.encode("utf-8"))
    results = {}
    lock = threading.Lock()

    def one(i):
        rc, out, _err = run_cli("analyze", str(root), "--json", "-")
        doc = json.loads(out)
        doc["generator"].pop("generatedAt", None)
        doc["stats"].pop("durationMs", None)
        with lock:
            results[i] = (rc, json.dumps(doc, sort_keys=True))

    threads = [threading.Thread(target=one, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(300)
    assert len(results) == 8
    assert {rc for rc, _ in results.values()} == {0}
    assert len({payload for _, payload in results.values()}) == 1


def test_hostile_configuration_files_are_warnings_not_failures(tmp_path):
    """Garbage TOML, binary TOML, absurd values and an unknown rule code."""
    root = tmp_path / "cfg"
    root.mkdir()
    write_bytes(root, "train.py", TRAIN.encode("utf-8"))
    for raw in (b"this is not toml at all ][\n",
                b"\xff\xfe\x00binary",
                (b"[analysis]\nmax_nodes = 999999999999999999999\n"
                 b"max_files = -3\n[paths]\nexclude = 5\n"
                 b'[rules]\ndisable = ["NOPE999"]\n')):
        write_bytes(root, ".mlview.toml", raw)
        doc = analyze(root)
        assert validate(doc) == []
        assert stage_present(doc, "train"), raw[:20]
        assert diagnostics(doc, "config_warning"), raw[:20]


def test_a_deep_but_shallow_enough_expression_is_analyzed(tmp_path):
    """The control for ROB-01: 100 `elif` branches and a 300-term sum are
    ordinary code and must analyze."""
    root = tmp_path / "shallow"
    root.mkdir()
    write_bytes(root, "registry.py", elif_chain(100).encode("utf-8"))
    write_bytes(root, "sums.py",
                ("x = 1\ntotal = " + " + ".join(["x"] * 300) + "\n").encode("utf-8"))
    write_bytes(root, "train.py", TRAIN.encode("utf-8"))
    doc = analyze(root)
    assert validate(doc) == []
    assert doc["workspace"]["filesFailed"] == 0
    assert stage_present(doc, "train")


def test_the_cli_never_tracebacks_on_a_bad_diff_base(tmp_path):
    base = tmp_path / "base.json"
    base.write_text('{"not": "a graph"}', encoding="utf-8")
    head = tmp_path / "head.json"
    rc, _out, _err = run_cli("analyze", os.path.join(SYNTAX, "walrus"),
                             "--json", str(head))
    assert rc == 0
    for candidate in (str(base), str(tmp_path / "missing.json")):
        rc, out, err = run_cli("diff", candidate, str(head), "--json", "-")
        assert rc == 1, (candidate, rc, err)
        assert "Traceback" not in err
        assert out.strip() == "" or out.strip().startswith("{")


# =========================================================== known defects
def test_rob01_a_deep_elif_chain_does_not_kill_the_workspace(tmp_path):
    """A 700-branch `elif` is legal Python that CPython's own `ast.parse`
    handles without blinking; `mlview` exits 3 with no document, and takes
    every *other* file in the workspace down with it.

    Observed: rc=3, stdout `{"error": {"type": "RecursionError", ...}}`.
    Expected: the file becomes one `parse_error` diagnostic and the healthy
    sibling is still analyzed.
    """
    root = tmp_path / "deep"
    root.mkdir()
    write_bytes(root, "registry.py", elif_chain(700).encode("utf-8"))
    write_bytes(root, "train.py", TRAIN.encode("utf-8"))
    rc, out, err = run_cli("analyze", str(root), "--json", "-")
    assert "RecursionError" not in err
    assert rc == 0, err[-400:]
    doc = json.loads(out)
    assert stage_present(doc, "train"), "the healthy sibling survived"


def test_rob01_a_long_expression_does_not_kill_the_workspace(tmp_path):
    root = tmp_path / "wide_expr"
    root.mkdir()
    write_bytes(root, "prompt.py",
                ("import torch\n\nPROMPT = "
                 + " + ".join(['"chunk"'] * 1200) + "\n").encode("utf-8"))
    write_bytes(root, "train.py", TRAIN.encode("utf-8"))
    rc, out, err = run_cli("analyze", str(root), "--json", "-")
    assert "RecursionError" not in err
    assert rc == 0, err[-400:]
    assert stage_present(json.loads(out), "train")


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no mkfifo on this OS")
def test_rob02_a_fifo_named_py_does_not_hang_the_analyzer(tmp_path):
    """`mkfifo pipe.py` in a repository is enough to wedge MLView: `open()`
    on a FIFO with no writer blocks, and `read_bytes` has no regular-file
    check and no timeout. The same hole reads a `*.py` symlink to `/dev/zero`
    until the machine runs out of memory (measured: 1.23 GB in 1.1 s).

    Run in a child process with a hard timeout so the suite itself cannot hang.
    """
    root = tmp_path / "fifo"
    root.mkdir()
    write_bytes(root, "train.py", TRAIN.encode("utf-8"))
    os.mkfifo(str(root / "pipe.py"))
    try:
        rc, out, _err = run_cli("analyze", str(root), "--json", "-", timeout=20)
    except subprocess.TimeoutExpired:
        pytest.fail("ROB-02: the analyzer blocked for 20s on a FIFO named "
                    "pipe.py; expected one parse_error diagnostic")
    assert rc == 0
    assert stage_present(json.loads(out), "train")


@pytest.mark.parametrize("program", ["dup_issue_ids", "dup_issue_ids_two_phase"])
def test_rob03_issue_ids_are_globally_unique(program):
    """CONTRACTS section 0, invariant 1. Two findings that share an id are one
    finding to every host: the rail lists a duplicate row, `applyFix` (which
    sends only the id) cannot tell the two lines apart, and `mlview diff`
    compares issue-id *sets*, so the second occurrence can never be new.

    `contracts/validate_sample.validate_graph` already fails the document; two
    of the shipped corpus programs (`vision_detector_bad`, `vision_unet_seg_bad`)
    fail it today with no mutation at all.
    """
    doc = analyze(os.path.join(ROBUSTNESS, program))
    counts = collections.Counter(i["id"] for i in doc["issues"])
    dupes = sorted(k for k, v in counts.items() if v > 1)
    assert dupes == [], "duplicate Issue.id: %s" % dupes
    assert validate(doc) == []


def test_rob04_an_unreadable_directory_is_declared(tmp_path):
    """Observed: `filesAnalyzed 1, filesFailed 0, diagnostics []` - a whole
    package disappeared and the document says the analysis was clean.
    Expected: something in `diagnostics` names the directory."""
    root = tmp_path / "locked_dir"
    root.mkdir()
    write_bytes(root, "good.py", TRAIN.encode("utf-8"))
    locked = root / "locked"
    locked.mkdir()
    write_bytes(root, os.path.join("locked", "inner.py"), TRAIN.encode("utf-8"))
    os.chmod(str(locked), 0)
    try:
        if os.access(str(locked), os.R_OK):
            pytest.skip("this process can read a mode-000 directory")
        doc = analyze(root)
        assert validate(doc) == []
        messages = " ".join((d.get("message") or "") for d in doc["diagnostics"])
        assert "locked" in messages, (
            "the unreadable directory is not mentioned anywhere in %s"
            % [d["kind"] for d in doc["diagnostics"]])
    finally:
        os.chmod(str(locked), stat.S_IRWXU)


def test_rob05_a_continued_shell_escape_keeps_the_notebook(tmp_path):
    """`!pip install -q \\` + two indented continuation lines is the single
    commonest install cell in a public Colab notebook - 16 of the 23 real
    notebooks that failed conversion in a 655-notebook sweep failed on exactly
    this. The first line becomes `pass  # mlview: magic`; the continuations are
    left as Python and raise IndentationError, so the training loop three cells
    below is never seen.
    """
    root = tmp_path / "nb_cont"
    root.mkdir()
    shutil.copy(os.path.join(NOTEBOOKS, "magic_continuation.ipynb"),
                str(root / "magic_continuation.ipynb"))
    doc = analyze(root, include_notebooks=True)
    assert validate(doc) == []
    assert doc["workspace"]["notebooksSkipped"] == 0, [
        d["message"] for d in diagnostics(doc, "notebook_skipped")]
    assert stage_present(doc, "train")


@pytest.mark.xfail(reason="ROB-06: --min-confidence above 1.0 is accepted and "
                          "silently empties the finding list")
def test_rob06_an_impossible_min_confidence_is_refused(tmp_path):
    """The configuration file rejects `min_confidence = 5.0` with a
    `config_warning` and ignores it. The flag takes it, hides all fifteen
    findings of the demo, and `--fail-on high` then exits 0 - a CI gate that
    is green because of a typo is the one failure a gate must never have.
    """
    sample = os.path.join(REPO_ROOT, "samples", "vision_pipeline")
    rc, out, _err = run_cli("analyze", sample, "--min-confidence", "5", "--json", "-")
    doc = json.loads(out)
    warned = [d for d in doc["diagnostics"] if d["kind"] == "config_warning"
              and "confidence" in (d.get("message") or "")]
    assert warned or doc["issues"], (
        "every finding was hidden and nothing said so")
    rc, _out, _err = run_cli("analyze", sample, "--min-confidence", "5",
                             "--fail-on", "high")
    assert rc == 2, "--fail-on high went green under an impossible threshold"


@pytest.mark.xfail(reason="ROB-07: an I/O error on an output path exits 3 "
                          "(internal error) where the CLI contract says 1")
def test_rob07_an_unwritable_output_path_is_an_io_error(tmp_path):
    """README: `0 ok - 1 usage or I/O - 2 --fail-on - 3 internal error`.
    Pointing `--json` at a read-only directory is I/O, and a CI harness that
    tells "MLView has a bug" from "your output path is read-only" reads the
    exit code to do it. Observed: rc=3 plus a Python traceback on stderr.
    """
    out_dir = tmp_path / "ro_out"
    out_dir.mkdir()
    os.chmod(str(out_dir), stat.S_IRUSR | stat.S_IXUSR)
    try:
        if os.access(str(out_dir), os.W_OK):
            pytest.skip("this process can write a read-only directory")
        rc, _out, err = run_cli("analyze", os.path.join(SYNTAX, "walrus"),
                                "--json", str(out_dir / "graph.json"))
        assert "Traceback" not in err
        assert rc == 1, "expected the I/O exit code, got %d" % rc
    finally:
        os.chmod(str(out_dir), stat.S_IRWXU)


@pytest.mark.xfail(reason="ROB-08: tomllib rejects a UTF-8 BOM, so a config "
                          "saved by a Windows editor is ignored whole")
def test_rob08_a_config_with_a_bom_is_honoured(tmp_path):
    """`Out-File` and Notepad write a BOM by default, and this project's own
    quick start is a PowerShell line. `ingest.parse.decode_source` already
    decodes source with `utf-8-sig`; `core/config.py` hands the raw bytes to
    `tomllib.load`, which fails at line 1 column 1 - and every rule the file
    disabled stays on.
    """
    root = tmp_path / "bom_cfg"
    root.mkdir()
    # a loop with no `opt.zero_grad()`, so MLV201 has something to report
    write_bytes(root, "train.py",
                TRAIN.replace("        opt.zero_grad()\n", "").encode("utf-8"))
    write_bytes(root, ".mlview.toml",
                b'\xef\xbb\xbf[rules]\ndisable = ["MLV201"]\n')
    doc = analyze(root)
    live = [i for i in doc["issues"]
            if i["code"] == "MLV201" and not i.get("suppressed")]
    assert live == [], "the BOM'd config was ignored; MLV201 is still reported"


@pytest.mark.xfail(reason="ROB-09: a workspace-internal `from x import *` "
                          "leaves every imported call unresolved")
def test_rob09_a_star_import_does_not_erase_the_objective_stage():
    """`base.py` defines `CRIT = nn.CrossEntropyLoss` and lists it in
    `__all__`; `train.py` does `from base import *` and calls `CRIT()`. The
    objective stage is then reported **absent** on a program that plainly has
    one, and the loss, the optimizer and the dataloader all land in the graph
    as `kind: unknown` in the `config` lane.

    A `dynamic_scope` diagnostic does name the star import, so the blind spot
    is declared - but `stages[objective].present = false` is still a claim
    about the code, made next to a `CrossEntropyLoss` the workspace can see.
    """
    doc = analyze(os.path.join(SYNTAX, "star_import_chain"))
    assert validate(doc) == []
    assert stage_present(doc, "objective"), (
        "objective declared absent; nodes = %s"
        % sorted({(n["kind"], n["stage"]) for n in doc["nodes"]}))


# ================================================ round 1, second half
# ROB-10 .. ROB-12 and the guards that came with them. The table at the top of
# this module continues here:
#
# | ROB-10 | `MLV101` treats **any** estimator `.fit()` as a preprocessing fit,
#            so refitting a classifier on the full matrix next to a `KFold.split`
#            is reported high / 0.95 on correct code | analyzer |
# | ROB-11 | an ignore directive inside a **string literal** suppresses a real
#            high finding | analyzer |
# | ROB-12 | `# MLVIEW: ignore[MLV201]` is neither honoured nor reported | analyzer |

LEAKAGE = os.path.join(ROBUSTNESS, "leakage_estimator_fit")
SUPPRESS = os.path.join(ROBUSTNESS, "suppress")

#: The shipped corpus programs whose documents fail `validate_graph` today, and
#: the rule whose second firing mints the duplicate id. Measured by analysing
#: every one of the 91 corpus programs in both dataflow modes.
DUP_ID_CORPUS = [
    ("vision_detector_bad", "local"),
    ("vision_detector_bad", "ip"),
    ("vision_unet_seg_bad", "local"),
    ("vision_video3d_bad", "local"),
]

CORPUS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..",
                                      "accuracy", "corpus"))


def live_issues(doc):
    return [i for i in doc["issues"] if not i.get("suppressed")]


def codes_at(doc, severity):
    return sorted((i["code"], i["loc"]["line"], i["loc"].get("symbol"))
                  for i in live_issues(doc) if i["severity"] == severity)


# --------------------------------------------------------- ROB-03, at scale
@pytest.mark.parametrize("program,mode", DUP_ID_CORPUS,
                         ids=["%s-%s" % (p, m) for p, m in DUP_ID_CORPUS])
def test_rob03_the_shipped_corpus_is_schema_valid(program, mode):
    """The duplicate-id defect is not hypothetical and does not need a crafted
    fixture: `tools/accuracy.py`'s own corpus produces it.

    Reproduce without pytest::

        python -c "from mlview.api import *; import json; \
          d=analyze_to_dict(AnalyzeOptions(paths=('analyzer/tests/accuracy/corpus/vision_detector_bad',))); \
          import collections; \
          print([k for k,v in collections.Counter(i['id'] for i in d['issues']).items() if v>1])"
        ['i:d4aedbacb06c']

    Found by mutating corpus programs 500 times (random line deletion,
    block duplication, identifier renaming, dedent, truncation, statement
    injection) across both dataflow modes: **every one of the 8 failures was
    this defect**, and the three programs above fail with no mutation at all.
    Zero tracebacks and zero `rule_error` diagnostics in the same 500 runs.
    """
    path = os.path.join(CORPUS, program)
    if not os.path.isdir(path):
        pytest.skip("corpus program %s is not present" % program)
    doc = analyze(path, dataflow=mode)
    counts = collections.Counter(i["id"] for i in doc["issues"])
    dupes = sorted(k for k, v in counts.items() if v > 1)
    assert dupes == [], "duplicate Issue.id in %s (%s): %s" % (program, mode, dupes)
    assert validate(doc) == []


def test_two_thousand_findings_keep_two_thousand_distinct_ids(tmp_path):
    """The positive control for ROB-03: the id is unique whenever the *symbol*
    differs, so the defect really is confined to one rule firing twice in one
    scope on one symbol - and the document stays schema-valid at scale."""
    root = tmp_path / "many"
    root.mkdir()
    body = ["import torch.nn as nn\n", "\n"]
    for i in range(2000):
        body.append("class M%d(nn.Module):\n    def __init__(self):\n"
                    "        self.fc = nn.Linear(4, 4)\n\n" % i)
    write_bytes(root, "many.py", "".join(body).encode("utf-8"))
    doc = analyze(root)
    assert validate(doc) == []
    ids = [i["id"] for i in doc["issues"]]
    assert len(ids) == 2000, len(ids)
    assert len(set(ids)) == 2000
    assert {i["code"] for i in doc["issues"]} == {"MLV701"}


# ------------------------------------------------------------------- ROB-10
@pytest.mark.parametrize("program", ["final_refit", "search_then_check"])
@pytest.mark.parametrize("mode", ["local", "ip"])
def test_rob10_an_estimator_fit_is_not_a_preprocessing_fit(program, mode):
    """**The worst failure this product can have**: `high`, confidence 0.95,
    on code that is correct.

    `docs/ISSUE_RULES.md` section 3 scopes MLV101 to call sites "whose resolved
    FQN carries the knowledge-table role `FIT` or `FIT_TRANSFORM`
    (`sklearn.preprocessing.*`, `sklearn.decomposition.*`, `sklearn.impute.*`,
    `sklearn.feature_selection.*`, `sklearn.feature_extraction.*`)". The
    implementation keeps the roles and drops the namespaces, and
    `knowledge/sklearn_tbl.py:120` gives `sklearn.base.BaseEstimator.fit` the
    role `FIT` - so `RandomForestClassifier.fit`, `GridSearchCV.fit` and
    `Pipeline.fit` are all MLV101 candidates. The second half of the rule then
    accepts a cross-validator's `KFold.split` / `StratifiedKFold.split` as "the
    train/test split", which is what makes the pair fire.

    Observed on `final_refit`::

        high MLV101 final_refit.py:24 final.fit conf 0.95
        "final.fit() is fitted on X at final_refit.py:24, before split splits
         it at line 26, so the transformer sees the held-out rows."

    `final` is a `RandomForestClassifier`. It has no `transform`. Measured on
    the pinned public corpus this shape is **13 of the 13 high findings** on
    scikit-learn's own source tree (`model_selection/tests/test_search.py`,
    `linear_model/tests/test_ridge.py`, `ensemble/.../test_gradient_boosting.py`
    and three more).

    Expected: no high finding. `fold_local_fit` (nothing fitted outside the
    loop) and `scaler_before_split` (the genuine defect) pin both edges.
    """
    doc = analyze(os.path.join(LEAKAGE, program), dataflow=mode)
    assert validate(doc) == []
    assert codes_at(doc, "high") == [], "high finding on correct code"


@pytest.mark.parametrize("mode", ["local", "ip"])
def test_rob10_the_genuine_leak_and_the_clean_fold_are_unchanged(mode):
    """The two controls ROB-10's fix has to keep: a stateful
    `sklearn.preprocessing` transformer fitted before `train_test_split` still
    fires, and a fold-local fit still says nothing."""
    good = analyze(os.path.join(LEAKAGE, "fold_local_fit"), dataflow=mode)
    assert validate(good) == []
    assert codes_at(good, "high") == []
    assert codes_at(good, "medium") == []

    bad = analyze(os.path.join(LEAKAGE, "scaler_before_split"), dataflow=mode)
    assert validate(bad) == []
    assert [c for c, _l, _s in codes_at(bad, "high")] == ["MLV101"]


@pytest.mark.parametrize("name,source", [
    ("split_first", '''"""The textbook-correct order."""
from sklearn.datasets import make_classification
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler


def run():
    X, y = make_classification(n_samples=200, random_state=0)
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, random_state=0)
    sc = StandardScaler()
    X_tr = sc.fit_transform(X_tr)
    X_te = sc.transform(X_te)
    clf = LogisticRegression().fit(X_tr, y_tr)
    return clf.score(X_te, y_te)
'''),
    ("nested_cv", '''"""Nested cross-validation - the gold standard, zero leakage."""
from sklearn.datasets import make_classification
from sklearn.model_selection import GridSearchCV, KFold, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC


def run():
    X, y = make_classification(n_samples=200, random_state=0)
    inner = KFold(n_splits=3, shuffle=True, random_state=0)
    outer = KFold(n_splits=5, shuffle=True, random_state=0)
    pipe = Pipeline([("sc", StandardScaler()), ("svc", SVC())])
    search = GridSearchCV(pipe, {"svc__C": [0.1, 1.0]}, cv=inner)
    return cross_val_score(search, X, y, cv=outer)
'''),
    ("refit_on_dev", '''"""Select on a validation split, then refit on train+val."""
from sklearn.datasets import make_classification
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split


def run():
    X, y = make_classification(n_samples=300, random_state=0)
    X_dev, X_test, y_dev, y_test = train_test_split(X, y, random_state=0)
    X_tr, X_val, y_tr, y_val = train_test_split(X_dev, y_dev, random_state=1)
    best, best_score = None, -1.0
    for C in (0.1, 1.0, 10.0):
        m = LogisticRegression(C=C).fit(X_tr, y_tr)
        s = m.score(X_val, y_val)
        if s > best_score:
            best, best_score = C, s
    final = LogisticRegression(C=best).fit(X_dev, y_dev)
    return final.score(X_test, y_test)
'''),
    ("cv_then_refit", '''"""cross_val_score for the estimate, one fit for the artefact."""
from sklearn.datasets import make_classification
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


def run():
    X, y = make_classification(n_samples=200, random_state=0)
    pipe = Pipeline([("sc", StandardScaler()), ("lr", LogisticRegression())])
    scores = cross_val_score(pipe, X, y, cv=5)
    pipe.fit(X, y)
    return pipe, scores
'''),
    ("fit_inside_every_fold", '''"""Fit the scaler inside every fold - correct."""
from sklearn.datasets import make_classification
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import StandardScaler


def run():
    X, y = make_classification(n_samples=200, random_state=0)
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=0)
    out = []
    for tr, te in skf.split(X, y):
        sc = StandardScaler().fit(X[tr])
        m = LogisticRegression().fit(sc.transform(X[tr]), y[tr])
        out.append(m.score(sc.transform(X[te]), y[te]))
    return out
'''),
])
@pytest.mark.parametrize("mode", ["local", "ip"])
def test_five_correct_sklearn_workflows_stay_clean(name, source, mode, tmp_path):
    """The wider precision floor around ROB-10: five workflows straight out of
    the scikit-learn user guide, each with local data so every value is tagged,
    each analysed in both dataflow modes. None may produce a high or a medium
    finding. These pass today and are the reason ROB-10 is scoped narrowly
    rather than "MLV101 is broken"."""
    root = tmp_path / name
    root.mkdir()
    write_bytes(root, name + ".py", source.encode("utf-8"))
    doc = analyze(root, dataflow=mode)
    assert validate(doc) == []
    assert codes_at(doc, "high") == []
    assert codes_at(doc, "medium") == []


# ------------------------------------------------------------ ROB-11, ROB-12
@pytest.mark.xfail(reason="ROB-11: the ignore index is a line-text regex, so a "
                          "string literal suppresses a real high finding")
def test_rob11_a_string_literal_does_not_suppress():
    """`rules/suppress.py:60` runs `IGNORE_RE.search(text)` over raw source
    lines, never over tokens. The fixture's line 23 is

        hint = "write # mlview: ignore[MLV201] on the loop header to silence this"

    and MLView emits the MLV201 on line 24 with `suppressed: true`. Hosts never
    publish suppressed issues, so a high-severity finding disappears because of
    text inside a string - the file's own documentation silencing the file.
    """
    doc = analyze(os.path.join(SUPPRESS, "string_literal"))
    assert validate(doc) == []
    suppressed = [(i["code"], i["loc"]["line"]) for i in doc["issues"]
                  if i.get("suppressed")]
    assert suppressed == [], "suppressed by a string literal: %s" % suppressed


def test_rob12_a_capitalised_ignore_directive_is_honoured_or_reported():
    """`IGNORE_RE` carries `re.IGNORECASE`; the guard on the line above it,
    `if "mlview" not in text: continue` (`rules/suppress.py:58`), does not. So
    `# MLVIEW: IGNORE[MLV201]` never reaches the regex.

    Every neighbouring spelling is forgiving: `.mlview.toml` accepts
    `disable = ["mlv201"]`, the code list inside a comment is upper-cased
    before matching, whitespace is trimmed, and an ignore comment naming an
    unknown code raises a `config_warning`. This spelling alone is silently
    inert - the user sees the finding they asked to hide and no explanation.

    Either outcome passes this test: honour it, or say it was not understood.
    """
    doc = analyze(os.path.join(SUPPRESS, "upper_directive"))
    assert validate(doc) == []
    hidden = any(i.get("suppressed") and i["code"] == "MLV201"
                 for i in doc["issues"])
    explained = any(d["kind"] == "config_warning" and "MLVIEW" in
                    (d.get("message") or "").upper()
                    for d in doc["diagnostics"])
    assert hidden or explained, (
        "the directive did nothing and nothing was said; diagnostics = %s"
        % [d["kind"] for d in doc["diagnostics"]])


def test_the_documented_suppression_spellings_all_work():
    """The regression floor under ROB-11/ROB-12: everything the docstring of
    `rules/suppress.py` promises still works, and an unknown code still warns."""
    doc = analyze(os.path.join(SUPPRESS, "exact_line"))
    assert validate(doc) == []
    assert [i["code"] for i in doc["issues"] if i.get("suppressed")] == ["MLV201"]
    assert [i["code"] for i in live_issues(doc)] == ["MLV601"]


# ============================================== round 1, the standing guards
# Everything below passes today. Each one is a hole that was probed and found
# closed, pinned so a later change cannot open it quietly.

import contextlib                                            # noqa: E402
import io                                                    # noqa: E402
import random                                                # noqa: E402


def test_a_corrupt_parse_cache_is_ignored_not_trusted(tmp_path):
    """The per-file cache lives in the workspace, so anything can happen to it:
    a truncated write, a `git checkout` over it, an editor's autosave. Three
    corruptions, three correct analyses."""
    root = tmp_path / "cache"
    root.mkdir()
    write_bytes(root, "train.py", TRAIN.encode("utf-8"))
    clean = analyze(root)                               # warms the cache
    cache_dir = os.path.join(str(root), ".mlview", "cache")
    assert os.path.isdir(cache_dir), "the cache was not written"

    def entries():
        return [os.path.join(cache_dir, n) for n in os.listdir(cache_dir)
                if n.endswith(".json")]

    for payload in (b"\x00\x01 not json at all",
                    b'{"nodes": 5}',
                    b'{"schema": 99, "files": {"train.py": {"calls": "nope"}}}'):
        for path in entries():
            with open(path, "wb") as fh:
                fh.write(payload)
        doc = analyze(root)
        assert validate(doc) == []
        assert doc["workspace"]["filesAnalyzed"] == 1
        assert stage_present(doc, "train")
        assert ({i["code"] for i in doc["issues"]}
                == {i["code"] for i in clean["issues"]}), payload[:12]


def test_an_edit_that_preserves_size_and_mtime_is_still_seen(tmp_path):
    """`core/cache.py` keys on content, not on `st_mtime_ns`/`st_size`, and
    this is the input that tells the two apart: a same-length edit with the
    timestamp restored. A cache keyed on the stat tuple would answer from the
    stale entry and report a training loop that no longer exists - the quietest
    possible misrepresentation."""
    root = tmp_path / "stat"
    root.mkdir()
    path = write_bytes(root, "train.py", TRAIN.encode("utf-8"))
    before = analyze(root)
    assert "MLV201" not in {i["code"] for i in before["issues"]}

    stat_before = os.stat(path)
    old = "        opt.zero_grad()\n"
    new = "        " + "pass  # nograd".ljust(len(old) - 9) + "\n"
    assert len(new) == len(old)
    # `newline=""` on BOTH handles: without it, text mode translates on write,
    # so on Windows every "\n" becomes "\r\n" and the file grows by one byte a
    # line - 402 to 418 for this fixture. The premise of the test is that the
    # size did not move, so the platform default silently destroys it, and the
    # failure reads as an analyzer defect rather than as a file-mode one.
    with open(path, "r", encoding="utf-8", newline="") as fh:
        source = fh.read()
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(source.replace(old, new))
    os.utime(path, (stat_before.st_atime, stat_before.st_mtime))
    assert os.stat(path).st_size == stat_before.st_size, (
        "the edit must preserve the size on every platform, or this test is "
        "measuring newline translation instead of the cache key")

    after = analyze(root)
    assert "MLV201" in {i["code"] for i in after["issues"]}, (
        "the stale cache entry was served for an edited file")


def test_byte_identical_files_keep_their_own_locations(tmp_path):
    """Content-keyed caching must not make two identical modules one module:
    both files have to appear in `nodes[].loc.file` and both have to carry
    their own copy of the finding."""
    root = tmp_path / "twins"
    root.mkdir()
    body = TRAIN.replace("        opt.zero_grad()\n", "")
    write_bytes(root, "alpha.py", body.encode("utf-8"))
    write_bytes(root, "beta.py", body.encode("utf-8"))
    cold = analyze(root)
    warm = analyze(root)
    for doc in (cold, warm):
        assert validate(doc) == []
        assert {n["loc"]["file"] for n in doc["nodes"]} == {"alpha.py", "beta.py"}
        fired = sorted((i["code"], i["loc"]["file"]) for i in doc["issues"]
                       if i["code"] == "MLV201")
        assert fired == [("MLV201", "alpha.py"), ("MLV201", "beta.py")], fired


@pytest.mark.parametrize("program", syntax_programs())
def test_the_library_writes_nothing_to_stdout_or_stderr(program):
    """CONTRACTS: library code never prints. A stray `print` in a rule corrupts
    `--json -`, which is the only way a host gets a document."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        analyze(os.path.join(SYNTAX, program))
    assert out.getvalue() == "", (program, out.getvalue()[:200])
    assert err.getvalue() == "", (program, err.getvalue()[:200])


def test_a_long_symlink_chain_and_a_directory_symlink_are_diagnostics(tmp_path):
    """Forty chained `*.py` symlinks cross the kernel's `ELOOP` limit part of
    the way along, and a `*.py` symlink that points at a *directory* is not a
    file at all. Both must land in `diagnostics`, and the real module must
    still be analyzed."""
    root = tmp_path / "chain"
    root.mkdir()
    write_bytes(root, "real.py", TRAIN.encode("utf-8"))
    (root / "adir").mkdir()
    try:
        previous = "real.py"
        for i in range(40):
            os.symlink(previous, str(root / ("link%d.py" % i)))
            previous = "link%d.py" % i
        os.symlink("adir", str(root / "asdir.py"))
    except (OSError, NotImplementedError):
        pytest.skip("this platform will not create symlinks")

    doc = analyze(root)
    assert validate(doc) == []
    assert doc["workspace"]["filesAnalyzed"] >= 1
    assert stage_present(doc, "train")
    failed = diagnostics(doc, "parse_error")
    assert doc["workspace"]["filesFailed"] == len(failed)
    assert all(d.get("message") for d in failed)


def test_non_ascii_identifiers_keep_the_training_loop(tmp_path):
    """CJK identifiers are legal Python and common in Chinese-language
    tutorials. Every stage must resolve, and every label must survive the JSON
    round trip."""
    root = tmp_path / "unicode"
    root.mkdir()
    source = (
        "import torch\n"
        "import torch.nn as nn\n"
        "from torch.utils.data import DataLoader\n"
        "\n"
        "\n"
        "def 训练(数据集):\n"
        "    模型 = nn.Linear(16, 3)\n"
        "    优化器 = torch.optim.Adam(模型.parameters())\n"
        "    损失函数 = nn.CrossEntropyLoss()\n"
        "    加载器 = DataLoader(数据集, batch_size=8, shuffle=True)\n"
        "    for xb, yb in 加载器:\n"
        "        优化器.zero_grad()\n"
        "        loss = 损失函数(模型(xb), yb)\n"
        "        loss.backward()\n"
        "        优化器.step()\n"
        "    return 模型\n"
    )
    write_bytes(root, "uni.py", source.encode("utf-8"))
    doc = analyze(root)
    assert validate(doc) == []
    assert doc["workspace"]["filesFailed"] == 0
    for stage in ("data", "model", "objective", "train"):
        assert stage_present(doc, stage), stage
    reparsed = json.loads(json.dumps(doc))
    assert any("加载器" in (n.get("label") or "")
               for n in reparsed["nodes"])


def test_four_hundred_levels_of_directory_nesting(tmp_path):
    """A generated artefact tree, or a `node_modules`-shaped repository. Deep
    recursion in discovery would surface here as a `RecursionError`."""
    root = tmp_path / "nest"
    leaf = root
    for _ in range(400):
        leaf = leaf / "d"
    leaf.mkdir(parents=True)
    write_bytes(leaf, "train.py", TRAIN.encode("utf-8"))
    doc = analyze(root)
    assert validate(doc) == []
    assert doc["workspace"]["filesAnalyzed"] == 1
    assert stage_present(doc, "train")


HOSTILE_ARGS = [
    ["--include", "**/**/**"], ["--include", "["], ["--include", "!!"],
    ["--include", "../../*"], ["--include", "/*"], ["--include", "{a,b}"],
    ["--exclude", "["], ["--exclude", "**"],
    ["--max-nodes", "-1"], ["--max-nodes", "0"], ["--max-nodes", "99999999"],
    ["--max-files", "0"], ["--max-files", "-1"],
    ["--relevance-hops", "-5"], ["--relevance-hops", "0"],
    ["--relevance-hops", "100000"],
    ["--min-confidence", "-1"], ["--min-confidence", "nan"],
    ["--framework", "keras"], ["--framework", "hf"],
    ["--scope", "file:train.py"], ["--scope", ""],
]


@pytest.mark.parametrize("extra", HOSTILE_ARGS,
                         ids=[" ".join(a) or "empty" for a in HOSTILE_ARGS])
def test_hostile_flag_values_never_traceback(extra, tmp_path):
    """Every one of these is something a shell, a CI template or a typo
    produces. The contract is the exit code table in the README: 0, 1, 2 or 4,
    and never a Python traceback."""
    root = tmp_path / "flags"
    root.mkdir()
    write_bytes(root, "train.py", TRAIN.encode("utf-8"))
    rc, out, err = run_cli("analyze", str(root), *extra)
    assert "Traceback" not in err, err[-400:]
    assert rc in (0, 1, 2, 4), (rc, err[-200:])
    if rc == 0:
        assert out.strip() != ""


BAD_SELECTORS = ["nope", "file:", "file:../../../etc/passwd", "issue:xxx",
                 "node:", "stage:zzz", "@@@", "symbol:", "concern:zzz",
                 "pipeline:zzz"]


@pytest.mark.parametrize("selector", BAD_SELECTORS)
def test_a_bad_scope_selector_is_a_usage_error_with_candidates(selector, tmp_path):
    """`--scope` is the surface a human types by hand, so a wrong value has to
    come back as exit 1 with a list of what would have worked - never a
    traceback, never a silently empty graph."""
    root = tmp_path / "scope"
    root.mkdir()
    write_bytes(root, "train.py", TRAIN.encode("utf-8"))
    rc, _out, err = run_cli("analyze", str(root), "--scope", selector)
    assert "Traceback" not in err, err[-300:]
    assert rc == 1, (selector, rc)
    assert "try:" in err or "candidates" in err, err[-200:]


#: Mutations applied to a copy of a real corpus program. `inject` deliberately
#: produces invalid Python; roughly half of the 500 runs behind ROB-03 did not
#: parse, which is the point - a parse failure is a diagnostic, not an excuse.
_MUTATIONS = ("delete", "dup", "rename", "dedent", "truncate", "swap", "inject")
_IDENTS = ("model", "loader", "opt", "loss", "train", "X", "y", "scaler",
           "trainer", "ds", "batch", "logits", "cfg", "device", "net")
_INJECTIONS = ("import torch\n", "x = (\n", "def \n", "class C(:\n",
               "    return\n", "@\n", "loss.backward()\n", "for in:\n")


def _mutate(text, rng):
    kind = rng.choice(_MUTATIONS)
    lines = text.splitlines(True)
    if not lines:
        return text, kind
    if kind == "delete":
        start = rng.randrange(len(lines))
        del lines[start:start + rng.randint(1, 4)]
    elif kind == "dup":
        start = rng.randrange(len(lines))
        block = lines[start:start + rng.randint(1, 8)]
        lines[rng.randrange(len(lines)):0 + rng.randrange(len(lines))] = block
    elif kind == "rename":
        return text.replace(rng.choice(_IDENTS), rng.choice(_IDENTS)), kind
    elif kind == "dedent":
        index = rng.randrange(len(lines))
        lines[index] = lines[index].lstrip(" ")
    elif kind == "truncate":
        lines = lines[:rng.randrange(1, len(lines) + 1)]
    elif kind == "swap" and len(lines) > 2:
        i, j = rng.randrange(len(lines)), rng.randrange(len(lines))
        lines[i], lines[j] = lines[j], lines[i]
    elif kind == "inject":
        lines.insert(rng.randrange(len(lines)), rng.choice(_INJECTIONS))
    return "".join(lines), kind


def test_mutated_corpus_programs_never_traceback(tmp_path):
    """A bounded replay of the 500-run sweep that found ROB-03: copy a real
    corpus program, damage one module at random, analyse it in one of the two
    dataflow modes. No traceback, no `rule_error` diagnostic, and a document
    that is either schema-valid or fails *only* on the known duplicate-id
    defect.

    The full sweep (500 runs, seed 1234, `--dataflow local` and `ip`) produced
    8 failures, all of them ROB-03, and 0 tracebacks. This keeps 40 of them so
    the suite stays fast; raise `MLVIEW_MUTATION_RUNS` to replay more.
    """
    if not os.path.isdir(CORPUS):
        pytest.skip("the accuracy corpus is not present")
    programs = sorted(d for d in os.listdir(CORPUS)
                      if os.path.isdir(os.path.join(CORPUS, d)))
    if not programs:
        pytest.skip("the accuracy corpus is empty")
    runs = int(os.environ.get("MLVIEW_MUTATION_RUNS", "40"))
    rng = random.Random(1234)
    unexpected = []
    for index in range(runs):
        program = rng.choice(programs)
        work = str(tmp_path / ("run%03d" % index))
        shutil.copytree(os.path.join(CORPUS, program), work,
                        ignore=shutil.ignore_patterns(".mlview", "labels.json"))
        modules = []
        for dirpath, dirnames, filenames in os.walk(work):
            dirnames[:] = [d for d in dirnames if d != ".mlview"]
            modules += [os.path.join(dirpath, f) for f in filenames
                        if f.endswith(".py")]
        if not modules:
            continue
        target = rng.choice(modules)
        with open(target, "r", encoding="utf-8") as fh:
            original = fh.read()
        mutated, kind = _mutate(original, rng)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(mutated)
        mode = rng.choice(("local", "ip"))
        where = "%s/%s %s %s" % (program, os.path.basename(target), kind, mode)
        try:
            doc = analyze(work, dataflow=mode)
        except Exception as exc:                             # noqa: BLE001
            unexpected.append("%s raised %r" % (where, exc))
            continue
        raised = diagnostics(doc, "rule_error")
        if raised:
            unexpected.append("%s -> rule_error %s"
                              % (where, [d.get("message") for d in raised][:2]))
        errors = [e for e in validate(doc) if "duplicate issue ids" not in e
                  and "globally unique" not in e]
        if errors:
            unexpected.append("%s -> %s" % (where, errors[:2]))
        shutil.rmtree(work, ignore_errors=True)
    assert unexpected == [], unexpected[:5]


def test_a_selector_that_matches_nothing_is_an_empty_view_not_an_error(tmp_path):
    """`unit:` and `node:` resolve against the graph, so a *grammatically*
    valid selector can legitimately match nothing. That is exit 0 with an
    empty, honest view - `view.of` says what the whole graph held - and a line
    on stderr saying so. What it must never be is exit 0 with a full graph, or
    a document that does not admit it was scoped."""
    root = tmp_path / "empty_scope"
    root.mkdir()
    write_bytes(root, "train.py", TRAIN.encode("utf-8"))
    rc, out, err = run_cli("analyze", str(root), "--scope", "unit:no_such_symbol",
                           "--json", "-")
    assert rc == 0, err[-200:]
    assert "matched no nodes" in err
    doc = json.loads(out)
    assert validate(doc) == []
    assert doc["nodes"] == []
    assert doc["view"]["scope"] == "unit:no_such_symbol"
    assert doc["view"]["of"]["nodes"] > 0, "the view does not say what it hid"


def test_rob13_an_empty_scope_message_quotes_what_the_user_typed(tmp_path):
    """`core/selectors.py:207` folds the `symbol:` spelling into `unit:` -
    deliberately, because "symbol is the word everyone reaches for". The
    message in `emit/scope_out.py:87` is then rendered from the normalized
    selector, so::

        $ mlview analyze ws --scope symbol:zzz
        mlview: scope unit:zzz matched no nodes; ...

    The user is told about a flag value they did not write, on the one code
    path whose whole job is to help them find the right one.
    """
    root = tmp_path / "echo"
    root.mkdir()
    write_bytes(root, "train.py", TRAIN.encode("utf-8"))
    _rc, _out, err = run_cli("analyze", str(root), "--scope", "symbol:zzz")
    assert "symbol:zzz" in err, err[:300]


# ------------------------------------------------------------------- ROB-14
RELEVANCE = os.path.join(ROBUSTNESS, "relevance_hops")


def train_nodes(doc):
    return sorted(n.get("label") or "" for n in doc["nodes"]
                  if n["stage"] == "train")


def test_the_relevance_prefilter_names_every_file_it_sets_aside():
    """The half that works, and the reason ROB-14 is about prose rather than
    about the prefilter: the set-aside is declared, in full, by name."""
    doc = analyze(RELEVANCE)
    assert validate(doc) == []
    warnings = [d for d in doc["diagnostics"] if d["kind"] == "config_warning"
                and "set aside" in (d.get("message") or "")]
    assert warnings, [d["kind"] for d in doc["diagnostics"]]
    assert "run_training.py" in warnings[0]["message"]
    assert "--relevance all" in warnings[0]["message"]


def test_raising_the_hop_budget_restores_the_training_loop():
    """The control for ROB-14: nothing is wrong with the analysis, only with
    what the default says about it. Four hops, or `--relevance all`, and the
    loop is back."""
    wide = analyze(RELEVANCE, relevance="all")
    assert validate(wide) == []
    labels = train_nodes(wide)
    assert any("for xb, yb in loader" in l for l in labels), labels
    assert any(l.startswith("train(") for l in labels), labels
    assert "MLV601" in {i["code"] for i in wide["issues"]}

    hops = analyze(RELEVANCE, relevance_hops=4)
    assert train_nodes(hops) == labels


@pytest.mark.xfail(reason="ROB-14: the training loop is dropped from the "
                          "graph and the stage table, the answers and the "
                          "verdict do not say so")
def test_rob14_a_set_aside_training_loop_is_admitted_where_it_shows():
    """`project/scripts/run_training.py` holds the batch loop,
    `loss.backward()` and `opt.step()`. Three import hops from the only module
    that names `torch`, the default `--relevance ml --relevance-hops 2` sets it
    aside, so the `train` stage renders two nodes - `Adam()` and
    `make_optimizer()` - and the diagram shows a pipeline with no training loop.

    Observed on the default invocation::

        Stages
          train         2 nodes
        verdict:  No findings: no rule fired on this workspace. MLView also
                  reported 1 coverage gap(s) (untagged_dataflow), so this is
                  not a clean bill of health.

    A `config_warning` in `Notes` does name both files, so the omission is
    declared once - and contradicted by the stage table above it. The verdict
    already appends the `untagged_dataflow` gap; the fix is to append this one
    the same way, or to mark the stage.

    Expected: something in `answers` or `stages[train]` says the loop was set
    aside. Either would do.
    """
    doc = analyze(RELEVANCE)
    assert validate(doc) == []
    labels = train_nodes(doc)
    assert not any("for xb, yb in loader" in l for l in labels), (
        "the fixture no longer reproduces: the loop is in the graph")
    prose = json.dumps(doc.get("answers")) + json.dumps(doc["stages"])
    assert ("set aside" in prose or "relevance" in prose.lower()
            or "run_training" in prose), (
        "the train stage shows %s and nothing in answers or stages says the "
        "loop was set aside" % labels)


# ------------------------------------------------- ROB-07, the other writers
@pytest.mark.parametrize("flag", ["--json", "--sarif", "--html"])
@pytest.mark.xfail(reason="ROB-07: every output flag exits 3 with a traceback "
                          "when its directory is read-only")
def test_rob07_every_output_flag_reports_io_as_io(flag, tmp_path):
    """The original ROB-07 repro used `--json`. All three writers share the
    defect: `--sarif` and `--html` also exit 3 and print a Python traceback
    where the README's table says 1 (usage or I/O).

    Observed, on a mode-500 directory::

        --sarif rc=3 traceback=1
        --html  rc=3 traceback=1
        --json  rc=3 traceback=1
    """
    out_dir = tmp_path / "ro"
    out_dir.mkdir()
    os.chmod(str(out_dir), stat.S_IRUSR | stat.S_IXUSR)
    try:
        if os.access(str(out_dir), os.W_OK):
            pytest.skip("this process can write a read-only directory")
        rc, _out, err = run_cli("analyze", os.path.join(SYNTAX, "walrus"),
                                flag, str(out_dir / "out"))
        assert "Traceback" not in err, err[-300:]
        assert rc == 1, "expected the I/O exit code, got %d" % rc
    finally:
        os.chmod(str(out_dir), stat.S_IRWXU)


HOSTILE_SIDE_FILES = ["not json", "{}", "[]", "", '{"issues": "x"}',
                      '{"schemaVersion": "9.9"}']


@pytest.mark.parametrize("payload", HOSTILE_SIDE_FILES,
                         ids=["empty" if not p else p[:14] for p in HOSTILE_SIDE_FILES])
def test_a_damaged_baseline_is_ignored_out_loud(payload, tmp_path):
    """`--baseline` points at a file a previous run wrote, so a truncated write
    or a merge conflict is routine. The analysis must still happen, and the
    document must say the baseline was dropped - a `--baseline` that silently
    does nothing turns "no new findings" into a meaningless CI green."""
    root = tmp_path / "baseline"
    root.mkdir()
    write_bytes(root, "train.py", TRAIN.encode("utf-8"))
    base = tmp_path / "base.json"
    write_bytes(tmp_path, "base.json", payload.encode("utf-8"))
    rc, out, err = run_cli("analyze", str(root), "--baseline", str(base),
                           "--json", "-")
    assert "Traceback" not in err, err[-300:]
    assert rc == 0, err[-200:]
    doc = json.loads(out)
    assert validate(doc) == []
    assert stage_present(doc, "train")
    warned = [d for d in doc["diagnostics"] if d["kind"] == "config_warning"
              and "baseline" in (d.get("message") or "")]
    assert warned, [d["kind"] for d in doc["diagnostics"]]


def test_a_missing_baseline_and_a_missing_changed_paths_file_are_declared(tmp_path):
    """The same for the two paths that may simply not exist."""
    root = tmp_path / "missing"
    root.mkdir()
    write_bytes(root, "train.py", TRAIN.encode("utf-8"))
    for flag in ("--baseline", "--changed-paths"):
        rc, out, err = run_cli("analyze", str(root), flag,
                               str(tmp_path / "nothing_here"), "--json", "-")
        assert "Traceback" not in err, (flag, err[-300:])
        assert rc == 0, (flag, err[-200:])
        doc = json.loads(out)
        assert validate(doc) == []
        assert stage_present(doc, "train"), flag


HOSTILE_CONFIGS = [
    "not toml at all",
    "[rules]\n",
    "[rules]\ndisable = 5\n",
    "[paths]\nexclude = \"x\"\n",
    "[tool.mlview]\n",
    "[rules]\ndisable = [1, 2, 3]\n",
    "[rules]\ndisable = [\"MLV201\"]\n[rules]\ndisable = [\"MLV601\"]\n",
]


@pytest.mark.parametrize("body", HOSTILE_CONFIGS,
                         ids=[b.splitlines()[0][:18] for b in HOSTILE_CONFIGS])
def test_a_hostile_config_file_never_costs_the_analysis(body, tmp_path):
    """`.mlview.toml` is checked into the repository being analyzed, so it is
    attacker-adjacent input in the ordinary sense: somebody else wrote it. A
    wrong type, a duplicated table, a file that is not TOML at all - none may
    cost the analysis, and none may raise."""
    root = tmp_path / "cfg"
    root.mkdir()
    write_bytes(root, "train.py", TRAIN.encode("utf-8"))
    write_bytes(root, ".mlview.toml", body.encode("utf-8"))
    rc, out, err = run_cli("analyze", str(root), "--json", "-")
    assert "Traceback" not in err, err[-300:]
    assert rc == 0, err[-200:]
    doc = json.loads(out)
    assert validate(doc) == []
    assert stage_present(doc, "train")


def test_a_notebook_run_twice_is_the_same_run(tmp_path):
    """`--include-notebooks` writes a generated module under
    `<root>/.mlview/notebooks/`. Two things must hold: a second run must not
    see its own output as new source, and a *later* run without the flag must
    not pick the stale generated module up and report findings for a `.py`
    file the user does not have."""
    root = tmp_path / "nb_twice"
    root.mkdir()
    cells = [
        ["import torch\n", "import torch.nn as nn\n",
         "from torch.utils.data import DataLoader\n"],
        ["def train(ds):\n", "    model = nn.Linear(16, 3)\n",
         "    opt = torch.optim.Adam(model.parameters())\n",
         "    crit = nn.CrossEntropyLoss()\n",
         "    loader = DataLoader(ds, batch_size=8, shuffle=True)\n",
         "    for xb, yb in loader:\n", "        loss = crit(model(xb), yb)\n",
         "        loss.backward()\n", "        opt.step()\n",
         "    return model\n"],
    ]
    notebook = {"cells": [{"cell_type": "code", "execution_count": None,
                           "metadata": {}, "outputs": [], "source": s}
                          for s in cells],
                "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
    write_bytes(root, "work.ipynb", json.dumps(notebook).encode("utf-8"))

    first = analyze(root, include_notebooks=True)
    second = analyze(root, include_notebooks=True)
    for doc in (first, second):
        assert validate(doc) == []
        assert doc["workspace"]["filesAnalyzed"] == 1
        assert "MLV201" in {i["code"] for i in doc["issues"]}
    assert ({(i["code"], i["loc"]["line"]) for i in first["issues"]}
            == {(i["code"], i["loc"]["line"]) for i in second["issues"]})

    plain = analyze(root)                      # the flag is gone, the dir is not
    assert validate(plain) == []
    assert plain["workspace"]["filesAnalyzed"] == 0
    assert plain["issues"] == [], "the generated module was analyzed as source"
