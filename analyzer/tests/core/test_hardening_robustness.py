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
    """The per-file cache is a file on a disk, so anything can happen to it: a
    truncated write, a `git checkout` over it, an editor's autosave. Three
    corruptions, three correct analyses.

    C8 moved the directory out of the analyzed folder and into the user's cache
    root, so the location is asked of `core.cache.cache_dir_for` rather than
    spelled - the corruption this test performs is the point, not the path.
    """
    from mlview.core.cache import cache_dir_for

    root = tmp_path / "cache"
    root.mkdir()
    write_bytes(root, "train.py", TRAIN.encode("utf-8"))
    clean = analyze(root)                               # warms the cache
    cache_dir = cache_dir_for(str(root))
    assert os.path.isdir(cache_dir), "the cache was not written"
    assert not cache_dir.startswith(str(root).replace("\\", "/")), (
        "C8: the sidecar must never land inside the analyzed folder")

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


# ============================================================ hardening round 2
# Round 1's battery is above and every one of its guards still passes; ROB-01
# .. ROB-05, ROB-10, ROB-12 and ROB-13 were fixed and their tests are green
# without a marker. What follows is the coverage round 1 did not reach, in the
# same two halves.
#
# | id | what | fix belongs to |
# |---|---|---|
# | ROB-15 | one parallel assignment (`opt, crit = Adam(...), CrossEntropyLoss()`)
#            turns the training loop into an `eval_loop`, declares the `eval`
#            stage present on a file with no evaluation, drops the
#            zero_grad/backward/step op nodes and silences MLV201 | analyzer |
# | ROB-16 | `accelerator.prepare(...)` erases MODEL / OPTIMIZER / LOADER, so
#            five calls of the canonical `accelerate` training step draw no node
#            and MLV201 goes blind on the shape `accelerate` documents | analyzer |
# | ROB-17 | a `functools.partial`-built `DataLoader` makes the `data` stage read
#            as absent with an EMPTY diagnostics list | analyzer |
# | ROB-18 | `<!--` in one source line makes the standalone HTML report's
#            embedded JSON invalid, so the whole diagram fails to render | analyzer |
# | ROB-19 | a line magic continued across an open bracket costs the whole
#            notebook (the bracket twin of round 1's ROB-05) | analyzer |
# | ROB-20 | an IPython assignment magic (`files = !ls`, `PATH = %env PATH`)
#            costs the whole notebook | analyzer |
# | ROB-21 | `single_file_diagnostic` walks the PARENT of the analyzed root, and
#            names files outside it as "sibling module(s) in the same package" | analyzer |
# | ROB-22 | `mlview render --graph` prints a Python traceback and exits 3 on a
#            JSON document that is not a graph | analyzer |
# | ROB-23 | the `--max-nodes` rollup is all-or-nothing per file: a 608-node
#            single-module workspace draws ONE node at `--max-nodes 100` | analyzer |

BINDING = os.path.join(ROBUSTNESS, "binding")
REPORT_FIXTURES = os.path.join(ROBUSTNESS, "report")
PKGWALK = os.path.join(ROBUSTNESS, "pkgwalk", "workspace")

HEAD = ("import torch\n"
        "import torch.nn as nn\n"
        "from torch.utils.data import DataLoader\n\n\n")

#: One Python feature per program, each wrapped around the same ordinary
#: zero_grad / backward / step loop. Round 1's twenty fixtures under
#: `fixtures/robustness/syntax` cover `match`, walrus, PEP 695, async, ...;
#: these are the twenty-two shapes it did not reach. They all pass today and
#: are pinned so a later change cannot lose one quietly.
ROUND2_SHAPES = {
    "while_true": HEAD + '''def train(ds):
    model = nn.Linear(16, 3)
    opt = torch.optim.Adam(model.parameters())
    crit = nn.CrossEntropyLoss()
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    it = iter(loader)
    while True:
        try:
            xb, yb = next(it)
        except StopIteration:
            break
        opt.zero_grad()
        loss = crit(model(xb), yb)
        loss.backward()
        opt.step()
    return model
''',
    "async_for": HEAD + '''async def train(ds):
    model = nn.Linear(16, 3)
    opt = torch.optim.Adam(model.parameters())
    crit = nn.CrossEntropyLoss()
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    async for xb, yb in loader:
        opt.zero_grad()
        loss = crit(model(xb), yb)
        loss.backward()
        opt.step()
    return model
''',
    "generator_yield": HEAD + '''def train(ds):
    model = nn.Linear(16, 3)
    opt = torch.optim.Adam(model.parameters())
    crit = nn.CrossEntropyLoss()
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    for xb, yb in loader:
        opt.zero_grad()
        loss = crit(model(xb), yb)
        loss.backward()
        opt.step()
        yield float(loss)
''',
    "try_finally": HEAD + '''def train(ds):
    model = nn.Linear(16, 3)
    opt = torch.optim.Adam(model.parameters())
    crit = nn.CrossEntropyLoss()
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    try:
        for xb, yb in loader:
            opt.zero_grad()
            loss = crit(model(xb), yb)
            loss.backward()
            opt.step()
    finally:
        del loader
    return model
''',
    "with_two_managers": HEAD + '''import contextlib


def train(ds):
    model = nn.Linear(16, 3)
    opt = torch.optim.Adam(model.parameters())
    crit = nn.CrossEntropyLoss()
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    with contextlib.ExitStack() as stack, torch.autograd.set_detect_anomaly(True):
        stack.callback(lambda: None)
        for xb, yb in loader:
            opt.zero_grad()
            loss = crit(model(xb), yb)
            loss.backward()
            opt.step()
    return model
''',
    "closure": HEAD + '''def make_trainer(ds):
    model = nn.Linear(16, 3)
    opt = torch.optim.Adam(model.parameters())
    crit = nn.CrossEntropyLoss()
    loader = DataLoader(ds, batch_size=8, shuffle=True)

    def inner():
        for xb, yb in loader:
            opt.zero_grad()
            loss = crit(model(xb), yb)
            loss.backward()
            opt.step()
        return model

    return inner
''',
    "global_rebind": HEAD + '''MODEL = None


def train(ds):
    global MODEL
    MODEL = nn.Linear(16, 3)
    opt = torch.optim.Adam(MODEL.parameters())
    crit = nn.CrossEntropyLoss()
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    for xb, yb in loader:
        opt.zero_grad()
        loss = crit(MODEL(xb), yb)
        loss.backward()
        opt.step()
    return MODEL
''',
    "callable_class": HEAD + '''class Criterion:
    def __init__(self):
        self.inner = nn.CrossEntropyLoss()

    def __call__(self, logits, target):
        return self.inner(logits, target)


def train(ds):
    model = nn.Linear(16, 3)
    opt = torch.optim.Adam(model.parameters())
    crit = Criterion()
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    for xb, yb in loader:
        opt.zero_grad()
        loss = crit(model(xb), yb)
        loss.backward()
        opt.step()
    return model
''',
    "property_accessor": HEAD + '''class Bundle:
    def __init__(self, ds):
        self._ds = ds
        self._model = nn.Linear(16, 3)

    @property
    def model(self):
        return self._model

    @property
    def loader(self):
        return DataLoader(self._ds, batch_size=8, shuffle=True)


def train(b):
    opt = torch.optim.Adam(b.model.parameters())
    crit = nn.CrossEntropyLoss()
    for xb, yb in b.loader:
        opt.zero_grad()
        loss = crit(b.model(xb), yb)
        loss.backward()
        opt.step()
    return b.model
''',
    "type_checking_import": HEAD + '''from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from torch import Tensor


def train(ds) -> "Tensor":
    model = nn.Linear(16, 3)
    opt = torch.optim.Adam(model.parameters())
    crit = nn.CrossEntropyLoss()
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    for xb, yb in loader:
        opt.zero_grad()
        loss = crit(model(xb), yb)
        loss.backward()
        opt.step()
    return loss
''',
    "abstract_base": HEAD + '''import abc


class Engine(abc.ABC):
    @abc.abstractmethod
    def step(self, batch):
        ...


class TorchEngine(Engine):
    def __init__(self, ds):
        self.model = nn.Linear(16, 3)
        self.opt = torch.optim.Adam(self.model.parameters())
        self.crit = nn.CrossEntropyLoss()
        self.loader = DataLoader(ds, batch_size=8, shuffle=True)

    def step(self, batch):
        xb, yb = batch
        self.opt.zero_grad()
        loss = self.crit(self.model(xb), yb)
        loss.backward()
        self.opt.step()
        return loss

    def run(self):
        for batch in self.loader:
            self.step(batch)
        return self.model
''',
    "enum_dispatch": HEAD + '''import enum


class Mode(enum.Enum):
    TRAIN = "train"
    EVAL = "eval"


def train(ds, mode=Mode.TRAIN):
    model = nn.Linear(16, 3)
    opt = torch.optim.Adam(model.parameters())
    crit = nn.CrossEntropyLoss()
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    for xb, yb in loader:
        if mode is Mode.TRAIN:
            opt.zero_grad()
            loss = crit(model(xb), yb)
            loss.backward()
            opt.step()
    return model
''',
    "class_decorator": HEAD + '''def register(cls):
    cls.registered = True
    return cls


@register
class Net(nn.Module):
    def __init__(self):
        super().__init__()
        self.fc = nn.Linear(16, 3)

    def forward(self, x):
        return self.fc(x)


def train(ds):
    model = Net()
    opt = torch.optim.Adam(model.parameters())
    crit = nn.CrossEntropyLoss()
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    for xb, yb in loader:
        opt.zero_grad()
        loss = crit(model(xb), yb)
        loss.backward()
        opt.step()
    return model
''',
    "module_getattr": HEAD + '''def __getattr__(name):
    raise AttributeError(name)


def train(ds):
    model = nn.Linear(16, 3)
    opt = torch.optim.Adam(model.parameters())
    crit = nn.CrossEntropyLoss()
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    for xb, yb in loader:
        opt.zero_grad()
        loss = crit(model(xb), yb)
        loss.backward()
        opt.step()
    return model
''',
    "posonly_kwonly": HEAD + '''def train(ds, /, *, epochs: int = 1, lr: float = 1e-3):
    model = nn.Linear(16, 3)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    crit = nn.CrossEntropyLoss()
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    for _ in range(epochs):
        for xb, yb in loader:
            opt.zero_grad()
            loss = crit(model(xb), yb)
            loss.backward()
            opt.step()
    return model
''',
    "singledispatch": HEAD + '''import functools


@functools.singledispatch
def build(spec):
    return nn.Linear(16, 3)


@build.register(int)
def _(spec: int):
    return nn.Linear(spec, 3)


def train(ds):
    model = build(16)
    opt = torch.optim.Adam(model.parameters())
    crit = nn.CrossEntropyLoss()
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    for xb, yb in loader:
        opt.zero_grad()
        loss = crit(model(xb), yb)
        loss.backward()
        opt.step()
    return model
''',
    "contextmanager": HEAD + '''import contextlib


@contextlib.contextmanager
def timed(name):
    yield name


def train(ds):
    model = nn.Linear(16, 3)
    opt = torch.optim.Adam(model.parameters())
    crit = nn.CrossEntropyLoss()
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    with timed("epoch"):
        for xb, yb in loader:
            opt.zero_grad()
            loss = crit(model(xb), yb)
            loss.backward()
            opt.step()
    return model
''',
    "operator_overload": HEAD + '''def train(ds):
    model = nn.Linear(16, 3)
    opt = torch.optim.Adam(model.parameters())
    crit = nn.CrossEntropyLoss()
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    for xb, yb in loader:
        opt.zero_grad()
        loss = crit(model(xb), yb) * 0.5
        loss.backward()
        opt.step()
    return model
''',
    "nested_class": HEAD + '''class Outer:
    class Net(nn.Module):
        def __init__(self):
            super().__init__()
            self.fc = nn.Linear(16, 3)

        def forward(self, x):
            return self.fc(x)

    def train(self, ds):
        model = Outer.Net()
        opt = torch.optim.Adam(model.parameters())
        crit = nn.CrossEntropyLoss()
        loader = DataLoader(ds, batch_size=8, shuffle=True)
        for xb, yb in loader:
            opt.zero_grad()
            loss = crit(model(xb), yb)
            loss.backward()
            opt.step()
        return model
''',
    "try_except_importerror": '''try:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader
except ImportError:                     # pragma: no cover
    torch = nn = DataLoader = None


def train(ds):
    model = nn.Linear(16, 3)
    opt = torch.optim.Adam(model.parameters())
    crit = nn.CrossEntropyLoss()
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    for xb, yb in loader:
        opt.zero_grad()
        loss = crit(model(xb), yb)
        loss.backward()
        opt.step()
    return model
''',
    "tqdm_wrapped_loader": HEAD + '''from tqdm import tqdm


def train(ds):
    model = nn.Linear(16, 3)
    opt = torch.optim.Adam(model.parameters())
    crit = nn.CrossEntropyLoss()
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    for xb, yb in tqdm(loader, desc="train"):
        opt.zero_grad()
        loss = crit(model(xb), yb)
        loss.backward()
        opt.step()
    return model
''',
    "ddp_and_compile": HEAD + '''def train(ds):
    model = nn.Linear(16, 3)
    model = torch.compile(nn.parallel.DistributedDataParallel(model))
    opt = torch.optim.Adam(model.parameters())
    crit = nn.CrossEntropyLoss()
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    for xb, yb in loader:
        opt.zero_grad()
        loss = crit(model(xb), yb)
        loss.backward()
        opt.step()
    return model
''',
}


def write_program(tmp_path, name, source):
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    write_bytes(root, "prog.py", source.encode("utf-8"))
    return root


# ----------------------------------------------------- round 2, the guards
@pytest.mark.parametrize("name", sorted(ROUND2_SHAPES))
def test_round2_syntax_shapes_keep_their_training_loop(name, tmp_path):
    """Twenty-two more Python features, twenty-two surviving training loops.

    The bar is round 1's: `train` present, at least one `train_loop` node, a
    schema-valid document, nothing on stdout or stderr. Everything here passes
    today; the two shapes that did NOT are ROB-15 and ROB-17 below, and they
    are fixtures on disk rather than rows in this table.
    """
    root = write_program(tmp_path, name, ROUND2_SHAPES[name])
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        doc = analyze(root)
    assert out.getvalue() == "" and err.getvalue() == "", name
    assert validate(doc) == [], name
    assert doc["workspace"]["filesFailed"] == 0, name
    assert stage_present(doc, "train"), "%s lost its train stage" % name
    assert [n for n in doc["nodes"] if n["kind"] == "train_loop"], (
        "%s: no train_loop node survived" % name)


@pytest.mark.parametrize("name", sorted(ROUND2_SHAPES))
def test_round2_shapes_never_invent_an_evaluation_stage(name, tmp_path):
    """None of the twenty-two programs evaluates anything. A pipeline that is
    told it has an `eval` stage when it does not is the same misrepresentation
    as a stage wrongly declared absent, pointing the other way - and it is
    exactly what ROB-15 produces."""
    doc = analyze(write_program(tmp_path, name, ROUND2_SHAPES[name]))
    assert not stage_present(doc, "eval"), (
        "%s: eval declared present; eval-lane nodes = %s"
        % (name, [(n["kind"], n["loc"]["line"]) for n in doc["nodes"]
                  if n["stage"] == "eval"]))


def test_round2_hostile_encodings_and_file_shapes(tmp_path):
    """Fourteen byte-level and filesystem hostilities round 1 did not reach.

    CR-only line endings (classic Mac), a form feed, a PEP 263 line declaring
    `ascii` over UTF-8 bytes, a PEP 263 line naming a codec that does not
    exist, a BOM *followed* by a coding line, a lone-surrogate escape, U+2028 /
    U+2029 inside a string, a megabyte of leading whitespace, a file that is
    only a BOM, a file that is only a comment, a NUL inside a comment, an
    invalid UTF-8 continuation byte, a directory named exactly `.py`, and two
    hard links to one inode.
    """
    root = tmp_path / "bytes2"
    root.mkdir()
    write_bytes(root, "good.py", TRAIN.encode("utf-8"))
    write_bytes(root, "cr_only.py", TRAIN.replace("\n", "\r").encode("utf-8"))
    write_bytes(root, "formfeed.py",
                TRAIN.replace("\n\n\n", "\n\x0c\n\n").encode("utf-8"))
    write_bytes(root, "declared_ascii.py",
                b"# -*- coding: ascii -*-\nimport torch\nX = 'caf\xc3\xa9'\n")
    write_bytes(root, "unknown_codec.py",
                b"# -*- coding: not-a-real-codec -*-\nimport torch\nX = 1\n")
    write_bytes(root, "bom_then_coding.py",
                b"\xef\xbb\xbf# -*- coding: utf-8 -*-\n" + TRAIN.encode("utf-8"))
    write_bytes(root, "surrogate.py", b"import torch\nX = '\\ud800'\n")
    write_bytes(root, "linesep.py", "import torch\nX = '\u2028\u2029'\n".encode("utf-8"))
    write_bytes(root, "bigindent.py", (b" " * 1000000) + b"pass\n")
    write_bytes(root, "only_bom.py", b"\xef\xbb\xbf")
    write_bytes(root, "only_comment.py", b"# nothing at all\n")
    write_bytes(root, "nul_comment.py", b"# hi\x00there\nimport torch\n")
    write_bytes(root, "invalid_utf8.py", b"import torch\nX = 1\n\xc3\x28\n")
    os.makedirs(os.path.join(str(root), ".py"), exist_ok=True)
    write_bytes(root, os.path.join(".py", "inner.py"), TRAIN.encode("utf-8"))
    write_bytes(root, "twin_a.py", TRAIN.encode("utf-8"))
    try:
        os.link(os.path.join(str(root), "twin_a.py"),
                os.path.join(str(root), "twin_b.py"))
        hard_linked = True
    except OSError:
        hard_linked = False

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        doc = analyze(root)
    assert out.getvalue() == "" and err.getvalue() == ""
    assert validate(doc) == []
    failed = {d["file"] for d in diagnostics(doc, "parse_error")}
    # the three that genuinely cannot be read are named, and only those three
    assert failed == {"bigindent.py", "nul_comment.py", "invalid_utf8.py"}, failed
    assert doc["workspace"]["filesFailed"] == len(failed)
    assert stage_present(doc, "train"), "the healthy files were still analyzed"
    # a CR-only file still yields usable snippets
    assert all("\r" not in (n["loc"].get("snippet") or "") for n in doc["nodes"])
    if hard_linked:
        files = {n["loc"]["file"] for n in doc["nodes"]}
        assert {"twin_a.py", "twin_b.py"} <= files, (
            "two hard links to one inode collapsed into one module: %s" % sorted(files))


def test_round2_the_document_is_identical_under_four_hash_seeds(tmp_path):
    """Non-determinism is a finding in its own right: a document that depends
    on `PYTHONHASHSEED` means a set iteration order reached the output, and two
    CI runs of one commit would then disagree.

    Four seeds, the cache disabled so the second run cannot answer from the
    first, and the two fields the contract lets vary stripped.
    """
    root = tmp_path / "seeds"
    root.mkdir()
    write_bytes(root, "train.py", TRAIN.encode("utf-8"))
    write_bytes(root, "second.py",
                TRAIN.replace("        opt.zero_grad()\n", "").encode("utf-8"))
    payloads = set()
    for seed in ("0", "1", "7", "12345"):
        env = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1",
                   PYTHONHASHSEED=seed, MLVIEW_NO_CACHE="1")
        proc = subprocess.run(
            [sys.executable, "-m", "mlview", "analyze", str(root), "--json", "-"],
            capture_output=True, cwd=REPO_ROOT, env=env, timeout=300)
        assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[-300:]
        doc = json.loads(proc.stdout.decode("utf-8"))
        doc["generator"].pop("generatedAt", None)
        doc["stats"].pop("durationMs", None)
        payloads.add(json.dumps(doc, sort_keys=True))
    assert len(payloads) == 1, "the document depends on PYTHONHASHSEED"


PATHOLOGICAL = {
    "nested_dict_200": "import torch\nX = " + "{'a':" * 200 + "1" + "}" * 200 + "\n",
    "chain_attr_2000": "import torch\nx = torch" + ".a" * 2000 + "\n",
    "chain_call_400": "import torch\nx = torch" + ".f()" * 400 + "\n",
    "bool_3000": "import torch\nx = " + " and ".join(["True"] * 3000) + "\n",
    "self_import": "import prog\n" + TRAIN,
    "mutual_recursion": ("import torch\n\ndef a(x):\n    return b(x)\n\n"
                         "def b(x):\n    return a(x)\n\n" + TRAIN),
    "self_ref_attr": ("import torch.nn as nn\n\nclass C:\n"
                      "    def __init__(self):\n        self.me = self\n"
                      "        self.net = nn.Linear(2, 2)\n\n"
                      "    def go(self):\n        return self.me.me.me.net\n"),
    "params_3000": ("import torch\n\ndef f("
                    + ", ".join("a%d" % i for i in range(3000)) + "):\n    return 1\n"),
    "dict_20k": ("import torch\nCFG = {"
                 + ",".join("'k%d': %d" % (i, i) for i in range(20000)) + "}\n"),
    "decorators_300": ("import torch\n\ndef d(f):\n    return f\n\n"
                       + "@d\n" * 300 + "def g():\n    pass\n"),
    "imports_2000": ("\n".join("import os as o%d" % i for i in range(2000))
                     + "\nimport torch\n" + TRAIN),
}


@pytest.mark.parametrize("name", sorted(PATHOLOGICAL))
@pytest.mark.parametrize("mode", ["local", "ip"])
def test_round2_pathological_sources_never_crash_the_run(name, mode, tmp_path):
    """A generated or adversarial source file may cost itself. It may never
    cost the run, raise out of the API, or take longer than a wall-clock budget
    an accidental quadratic would blow through.

    ROB-01 fixed the RecursionError that used to come out of `ir.scopes`; these
    are the neighbouring shapes - a 2000-deep attribute chain, a 3000-term
    boolean, a module that imports itself, two mutually recursive functions, an
    object that holds itself, 3000 parameters, a 20 000-entry dict literal, 300
    stacked decorators and 2000 imports.
    """
    import time

    root = write_program(tmp_path, name, PATHOLOGICAL[name])
    started = time.perf_counter()
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        doc = analyze(root, dataflow=mode, relevance="all")
    elapsed = time.perf_counter() - started
    assert out.getvalue() == "" and err.getvalue() == "", name
    assert validate(doc) == [], name
    assert elapsed < 60.0, "%s took %.1fs" % (name, elapsed)
    assert not diagnostics(doc, "rule_error"), name


ROUND2_NOTEBOOKS = {
    # nbformat 3 kept its cells under `worksheets`
    "nbformat3": {"nbformat": 3, "nbformat_minor": 0, "metadata": {},
                  "worksheets": [{"cells": [{"cell_type": "code", "language": "python",
                                             "outputs": [], "input": None}]}]},
    "crlf_cells": None,
    "cr_only_cells": None,
    "raw_cell_first": None,
    "python_cell_magic": None,
    "run_line_magic": None,
    "bang_inside_a_string": None,
    "help_query": None,
    "double_help_query": None,
    "magic_then_code": None,
    "percent_inside_a_triple_quote": None,
    "autoreload": None,
    "wrapping_magic": None,
    "non_monotonic_execution": None,
    "null_execution_count": None,
    "bom_prefixed": None,
    "nbformat_as_a_string": None,
}


def _loop_cell_lines():
    return ["import torch\n", "import torch.nn as nn\n",
            "from torch.utils.data import DataLoader\n", "ds = None\n",
            "model = nn.Linear(16, 3)\n",
            "opt = torch.optim.Adam(model.parameters())\n",
            "crit = nn.CrossEntropyLoss()\n",
            "loader = DataLoader(ds, batch_size=8, shuffle=True)\n",
            "for xb, yb in loader:\n", "    opt.zero_grad()\n",
            "    loss = crit(model(xb), yb)\n", "    loss.backward()\n",
            "    opt.step()\n"]


def _code_cell(source, count=1):
    return {"cell_type": "code", "execution_count": count, "metadata": {},
            "outputs": [], "source": source}


def _notebook_payload(name):
    """The bytes for one round-2 notebook shape."""
    loop = _loop_cell_lines()
    if name == "nbformat3":
        return json.dumps({"nbformat": 3, "nbformat_minor": 0, "metadata": {},
                           "worksheets": [{"cells": [
                               {"cell_type": "code", "language": "python",
                                "outputs": [], "input": loop}]}]})
    prefix = {
        "crlf_cells": [[l.replace("\n", "\r\n") for l in loop]],
        "cr_only_cells": [["".join(loop).replace("\n", "\r")]],
        "raw_cell_first": None,
        "python_cell_magic": [["%%capture\n", "import torch\n"], loop],
        "run_line_magic": [["get_ipython().run_line_magic('matplotlib', 'inline')\n"], loop],
        "bang_inside_a_string": [["x = '!pip install torch'\n"], loop],
        "help_query": [["torch.nn?\n"], loop],
        "double_help_query": [["torch.nn??\n"], loop],
        "magic_then_code": [["%matplotlib inline\n", "import torch\n"], loop],
        "percent_inside_a_triple_quote": [["s = '''\n", "%cd /tmp\n", "'''\n"], loop],
        "autoreload": [["%load_ext autoreload\n", "%autoreload 2\n"], loop],
        "wrapping_magic": [["%time total = 1 + 1\n"], loop],
        "non_monotonic_execution": None,
        "null_execution_count": None,
        "bom_prefixed": None,
        "nbformat_as_a_string": None,
    }[name]
    if name == "raw_cell_first":
        cells = [{"cell_type": "raw", "metadata": {}, "source": ["not python\n"]},
                 _code_cell(loop)]
    elif name == "non_monotonic_execution":
        cells = [_code_cell(loop, 7), _code_cell(["x = 1\n"], 2)]
    elif name == "null_execution_count":
        cells = [_code_cell(loop, None)]
    elif name in ("bom_prefixed", "nbformat_as_a_string"):
        cells = [_code_cell(loop)]
    else:
        cells = [_code_cell(c, i + 1) for i, c in enumerate(prefix)]
    document = {"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
    if name == "nbformat_as_a_string":
        document["nbformat"] = "4"
    text = json.dumps(document)
    return ("\ufeff" + text) if name == "bom_prefixed" else text


@pytest.mark.parametrize("name", sorted(ROUND2_NOTEBOOKS))
def test_round2_notebook_shapes_keep_their_loop(name, tmp_path):
    """Seventeen notebook shapes round 1 did not reach - an nbformat-3 document
    whose cells live under `worksheets`, CRLF and CR-only cell sources, a raw
    cell, `%%capture`, `get_ipython().run_line_magic(...)`, a `!` inside a
    string literal, `x?` and `x??`, a magic above real code in one cell, a `%cd`
    inside a triple-quoted string, `%load_ext autoreload`, a wrapping `%time`,
    a non-monotonic `execution_count`, a null one, a BOM in front of the JSON,
    and `"nbformat": "4"` as a string.

    Every one of them must convert, and the training loop must survive. ROB-19
    and ROB-20 are the two shapes that do not, and they are fixtures on disk.
    """
    root = tmp_path / ("nb_" + name)
    root.mkdir()
    write_bytes(root, "n.ipynb", _notebook_payload(name).encode("utf-8"))
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        doc = analyze(root, include_notebooks=True)
    assert out.getvalue() == "" and err.getvalue() == "", name
    assert validate(doc) == [], name
    assert doc["workspace"]["notebooksSkipped"] == 0, [
        d["message"] for d in diagnostics(doc, "notebook_skipped")]
    assert stage_present(doc, "train"), "%s lost its training loop" % name


HOSTILE_ENV = [
    ("MLVIEW_CACHE_DIR", "@file"),          # points at a regular file
    ("MLVIEW_CACHE_DIR", "/dev/null"),
    ("MLVIEW_CACHE_DIR", ""),
    ("MLVIEW_CACHE_DIR", "/proc/nope/cache"),
    ("HOME", "/nonexistent-home-mlview"),
    ("HOME", "/dev/null"),
]


@pytest.mark.parametrize("key,value", HOSTILE_ENV,
                         ids=["%s=%s" % (k, v or "empty") for k, v in HOSTILE_ENV])
def test_round2_a_hostile_environment_never_costs_the_analysis(key, value, tmp_path):
    """The cache writes a sidecar under `MLVIEW_CACHE_DIR` and authenticates it
    with a secret in the user's home. Both are environment, so both are
    somebody else's decision in a container, a CI runner or a sandbox. None of
    these may cost the analysis or raise."""
    root = tmp_path / "env"
    root.mkdir()
    write_bytes(root, "train.py", TRAIN.encode("utf-8"))
    target = value
    if value == "@file":
        target = write_bytes(root, "not_a_dir", b"x")
    env = {key: target}
    proc = subprocess.run(
        [sys.executable, "-m", "mlview", "analyze", str(root), "--json", "-"],
        capture_output=True, cwd=REPO_ROOT, timeout=300,
        env=dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", **env))
    err = proc.stderr.decode("utf-8", "replace")
    assert "Traceback" not in err, err[-300:]
    assert proc.returncode == 0, err[-300:]
    doc = json.loads(proc.stdout.decode("utf-8"))
    assert validate(doc) == []
    assert stage_present(doc, "train")


def test_round2_a_mlview_directory_that_is_a_file_is_survivable(tmp_path):
    """`.mlview/` is where the cache and the generated notebook modules go. A
    user, a `.gitignore` trick or a previous tool can leave a *file* with that
    name, and `.mlview.toml` can be a directory."""
    root = tmp_path / "shapes"
    root.mkdir()
    write_bytes(root, "train.py", TRAIN.encode("utf-8"))
    write_bytes(root, ".mlview", b"not a directory")
    os.makedirs(os.path.join(str(root), ".mlview.toml"), exist_ok=True)
    for extra in ([], ["--include-notebooks"]):
        rc, out, err = run_cli("analyze", str(root), "--json", "-", *extra)
        assert "Traceback" not in err, err[-300:]
        assert rc == 0, err[-300:]
        doc = json.loads(out)
        assert validate(doc) == []
        assert stage_present(doc, "train")


# --------------------------------------------------------- round 2, ROB-15
ROB15_PROGRAMS = ["tuple_pair", "tuple_pair_method"]


@pytest.mark.parametrize("program", ROB15_PROGRAMS)
@pytest.mark.parametrize("mode", ["local", "ip"])
def test_rob15_a_parallel_assignment_keeps_the_training_loop(program, mode):
    """**Silent misrepresentation.** One statement, and a training loop is
    relabelled evaluation.

    `ir/bindings._bind_record` (line 460) handles a tuple target by asking
    `record.call` for per-slot tags. When the right-hand side is itself a tuple
    literal there IS no call, so `positions` and `base_tags` are both empty and
    every name in the target is bound with **no tags and no producer**::

        opt, crit = torch.optim.Adam(model.parameters()), nn.CrossEntropyLoss()

    `opt` then carries no OPTIMIZER tag, so `opt.zero_grad()` and `opt.step()`
    resolve to nothing and draw no node; `loss` is untyped, so `loss.backward()`
    draws none either. `core/views._runs_without_training` scans the loop for a
    call with a *training* role, finds none (the model still resolves, so the
    forward pass does), and concludes the loop is evaluation - even though the
    three `_TRAINING_METHODS` its own sibling `_runs_an_unresolved_model`
    checks syntactically are all right there in the body.

    Measured on `tuple_pair`, both dataflow modes::

        nodes                6      (9 when the two binds are written apart)
        loops                eval_loop
        stages[eval]         present: true      (there is no evaluation)
        MLV201 on a loop with no zero_grad()    silent (high, 0.95, when apart)

    `tuple_pair_method` is the same defect in the shape a project writes it:
    `self.opt, self.crit = ...` in a Trainer's `__init__`.
    """
    doc = analyze(os.path.join(BINDING, program), dataflow=mode)
    assert validate(doc) == []
    kinds = [(n["kind"], n["loc"]["line"]) for n in doc["nodes"] if "loop" in n["kind"]]
    assert not stage_present(doc, "eval"), (
        "eval declared present on a program with no evaluation; loops = %s" % kinds)
    assert [k for k, _l in kinds if k == "train_loop"], (
        "the training loop is not a train_loop: %s" % kinds)


def test_rob15_the_parallel_assignment_also_silences_mlv201(tmp_path):
    """The half that matters to a user: the misclassification hides a real,
    high-severity defect.

    Two programs, identical but for how `opt` and `crit` are bound, and both
    missing `optimizer.zero_grad()` - which is MLV201, high, confidence 0.95.
    """
    apart = ("    opt = torch.optim.Adam(model.parameters())\n"
             "    crit = nn.CrossEntropyLoss()\n")
    together = ("    opt, crit = torch.optim.Adam(model.parameters()), "
                "nn.CrossEntropyLoss()\n")
    body = (HEAD + "def train(ds):\n    model = nn.Linear(16, 3)\n%s"
            "    loader = DataLoader(ds, batch_size=8, shuffle=True)\n"
            "    for xb, yb in loader:\n"
            "        loss = crit(model(xb), yb)\n"
            "        loss.backward()\n        opt.step()\n    return model\n")
    control = analyze(write_program(tmp_path, "apart", body % apart))
    assert "MLV201" in {i["code"] for i in live_issues(control)}, (
        "the control no longer reports MLV201; this test is measuring nothing")
    subject = analyze(write_program(tmp_path, "together", body % together))
    assert validate(subject) == []
    assert "MLV201" in {i["code"] for i in live_issues(subject)}, (
        "MLV201 is silent on the same defect because `opt` and `crit` share one "
        "assignment; issues = %s"
        % sorted({(i["code"], i["severity"]) for i in subject["issues"]}))


# --------------------------------------------------------- round 2, ROB-16
ACCELERATE = os.path.join(BINDING, "accelerate_prepare")

#: The calls of the canonical accelerate step that carry a knowledge role of
#: their own. `model(features)` (51) and `criterion(...)` (52) are FORWARD,
#: which `core/build.py` lists in `TRANSPARENT_ROLES` and maps onto the model /
#: criterion node by design, so they are asserted as *attributed*, never as
#: nodes of their own.
ACCELERATE_STEP_LINES = (53, 54, 55, 56)


@pytest.mark.parametrize("mode", ["local", "ip"])
def test_rob16_the_accelerate_training_step_is_on_the_diagram(mode):
    """**A dropped call, five times over, on the loop `accelerate` documents.**

    `accelerator.prepare(model, optimizer, loader, scheduler)` is mandatory in
    every `accelerate` script - it is how the three are placed on the device -
    and it had no knowledge-table entry, so it returned untagged. Re-binding
    `model`, `optimizer` and `loader` to its result therefore **erased** the
    MODEL, OPTIMIZER and LOADER tags those names already carried, and every
    call that depends on one of them stopped resolving: the batch loop was
    emitted as an `eval_loop`, `stages[eval].present` was true on a file that
    never evaluates, and none of `accelerator.backward(loss)`,
    `optimizer.step()`, `lr_scheduler.step()` or `optimizer.zero_grad()` had a
    node.

    Two fixes carry it, and neither is an `accelerate` special case.
    `ir/bindings._self_wrapped` keeps what a name already carried when it is
    rebound from `f(..., x, ...)` whose callee resolves to nothing - the
    wrapper idiom, which also covers `fabric.setup`, `fabric.setup_module` and
    a plain workspace `def wrap(m, o): return m, o` (INFRA-R2-04) - and
    `accelerate.Accelerator.backward` carries the BACKWARD role, because it is
    the only way the scaled backward happens in an accelerate script.
    """
    doc = analyze(ACCELERATE, dataflow=mode)
    assert validate(doc) == []
    drawn = {n["loc"]["line"] for n in doc["nodes"]}
    missing = sorted(set(ACCELERATE_STEP_LINES) - drawn)
    assert not missing, (
        "no node for the training-step call(s) on line(s) %s; the train lane "
        "holds %s" % (missing, sorted((n["kind"], n["loc"]["line"])
                                      for n in doc["nodes"] if n["stage"] == "train")))
    assert not stage_present(doc, "eval"), (
        "the batch loop is still read as evaluation on a file that never evaluates")
    loops = [(n["kind"], n["loc"]["line"]) for n in doc["nodes"] if "loop" in n["kind"]]
    assert ("train_loop", 50) in loops, loops



def test_rob16_accelerate_does_not_hide_a_missing_zero_grad(tmp_path):
    """The measurement that turns ROB-16 from a picture defect into a blind
    spot: delete `optimizer.zero_grad()` from the canonical accelerate loop and
    MLView reports **nothing** - not a de-rated finding, not a suppressed one,
    not a ghost node - in either dataflow mode.

    The framework de-rate is not what is happening here: `--show-suppressed`
    shows an empty list too. The rule simply never sees an optimizer.
    """
    root = tmp_path / "accel_bad"
    shutil.copytree(ACCELERATE, str(root))
    path = os.path.join(str(root), "train.py")
    with open(path, encoding="utf-8") as fh:
        source = fh.read()
    assert "            optimizer.zero_grad()\n" in source
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(source.replace("            optimizer.zero_grad()\n", ""))
    for mode in ("local", "ip"):
        doc = analyze(root, dataflow=mode)
        assert validate(doc) == []
        assert "MLV201" in {i["code"] for i in doc["issues"]}, (
            "%s: a training loop with no zero_grad() produced %s"
            % (mode, sorted({(i["code"], i["severity"]) for i in doc["issues"]})))


# --------------------------------------------------------- round 2, ROB-17
@pytest.mark.parametrize("mode", ["local", "ip"])
def test_rob17_a_partial_built_loader_is_not_an_absent_data_stage(mode):
    """**A stage claimed absent, unqualified, on a file that builds a loader.**

    Observed::

        stages[data].present  false
        diagnostics           []                      <- nothing at all
        answers.dataEntry     "No data entry was detected: nothing in this
                               workspace builds a dataset or a loader ..."

    The comparison is what makes this a defect rather than a limit: a workspace
    helper (`def make_loader(d): return DataLoader(...)`) keeps the loader; a
    `lambda` keeps it and raises `unresolved_callee`; a dict lookup loses it but
    raises `unresolved_callee`. `functools.partial` alone loses it **and**
    raises nothing, so CONTRACTS 11.23's rule - no emitter may claim a stage is
    absent without qualification - is not met.

    Either outcome passes: recognise the partial, or declare the blind spot.
    """
    doc = analyze(os.path.join(BINDING, "partial_loader"), dataflow=mode)
    assert validate(doc) == []
    if stage_present(doc, "data"):
        return
    assert doc["diagnostics"], (
        "the data stage is declared absent on a workspace that builds a "
        "DataLoader, and `diagnostics` is empty; answer = %r"
        % doc["answers"]["dataEntry"]["sentence"])


# --------------------------------------------------------- round 2, ROB-18
GRAPH_BLOCK_OPEN = '<script id="mlview-graph" type="application/json">'


def embedded_graph_text(html_path):
    with open(html_path, encoding="utf-8") as fh:
        raw = fh.read()
    start = raw.index(GRAPH_BLOCK_OPEN) + len(GRAPH_BLOCK_OPEN)
    return raw[start:raw.index("</script>", start)]


def test_rob18_a_source_line_with_an_html_comment_still_renders(tmp_path):
    """**The report is a blank page.** `emit/html_out.py:57` is

        return text.replace("</", "<\\\\/").replace("<!--", "<\\\\!--")

    `<\\/` is right and is one of JSON's seven escapes. `\\!` is not an escape
    at all, and the block it lands in is `type="application/json"`, read back by
    the report's own bootstrap with

        JSON.parse(document.getElementById('mlview-graph').textContent)

    so the parse throws, `MLView.mount` never runs, and everything outside the
    two script blocks of an asset-carrying report is the `<h1>`: the reader gets
    a page saying `MLView - <root>` and nothing else, while the CLI prints
    `mlview: wrote report.html` and exits 0.

    Reproduce::

        python -m mlview analyze analyzer/tests/fixtures/robustness/report/html_comment \\
            --html /tmp/r.html
        cd webview && node test/render_report.mjs /tmp/r.html
        #  SyntaxError: Bad escaped character in JSON at position 1938

    Any line carrying `<!--` that becomes a node's `symbol` or `snippet` does
    it - an HTML template in a string, a Jinja fragment, a wandb
    `<!--- @wandbcode{...} -->` marker in a notebook cell.

    Python's `json.loads` rejects `\\!` for the same reason JavaScript's does,
    so this test needs no browser.
    """
    report = tmp_path / "report.html"
    rc, _out, err = run_cli("analyze", os.path.join(REPORT_FIXTURES, "html_comment"),
                            "--html", str(report))
    assert rc == 0, err[-300:]
    text = embedded_graph_text(str(report))
    json.loads(text)          # the report's own JSON.parse, in Python


def test_rob18_the_script_terminator_guard_is_still_correct(tmp_path):
    """The control ROB-18's fix must keep: a literal `</script>` in a source
    line is neutralised, and no raw `</script` survives inside the JSON block.
    Escaping this one is what the `<!--` arm was reaching for."""
    root = tmp_path / "closer"
    root.mkdir()
    write_bytes(root, "t.py",
                (b'import torch\nMARKER = "</script><img src=x onerror=alert(1)>"\n'
                 + TRAIN.encode("utf-8")))
    report = tmp_path / "closer.html"
    rc, _out, err = run_cli("analyze", str(root), "--html", str(report))
    assert rc == 0, err[-300:]
    text = embedded_graph_text(str(report))
    assert "</script" not in text.lower()
    assert "<\\/script" in text


# --------------------------------------------------------- round 2, ROB-19/20
@pytest.mark.xfail(reason="ROB-19: a line magic continued across an open "
                          "bracket leaves the continuation as Python, and one "
                          "IndentationError costs the whole notebook")
def test_rob19_a_bracket_continued_magic_keeps_the_notebook(tmp_path):
    """ROB-05's bracket twin, and it is on the board of every timing notebook::

        %timeit np.fromiter((xi + yi for xi, yi in zip(x, y)),
                            dtype=x.dtype, count=len(x))

    `ingest/notebook._rewrite` blanks the magic line and carries a backslash
    continuation with it (ROB-05's fix), but an *open bracket* continuation is
    left behind as Python, where it is `IndentationError: unexpected indent`.
    The notebook is one generated module, so that one cell costs every cell:
    the training loop below is never analyzed.

    Measured by converting the 876 notebooks in the pinned public clones with
    this build: **867 parse, 9 do not**, and this is one of them -
    `PythonDataScienceHandbook/notebooks/03.12-Performance-Eval-and-Query.ipynb`
    cell 1, copied verbatim into the fixture.
    """
    root = tmp_path / "nb19"
    root.mkdir()
    shutil.copy(os.path.join(NOTEBOOKS, "magic_bracket_continuation.ipynb"),
                str(root / "n.ipynb"))
    doc = analyze(root, include_notebooks=True)
    assert validate(doc) == []
    assert doc["workspace"]["notebooksSkipped"] == 0, [
        d["message"] for d in diagnostics(doc, "notebook_skipped")]
    assert stage_present(doc, "train")


@pytest.mark.xfail(reason="ROB-20: an IPython assignment magic (`x = !cmd`, "
                          "`x = %env VAR`) is not recognised as a magic, so it "
                          "costs the whole notebook")
def test_rob20_an_assignment_magic_keeps_the_notebook(tmp_path):
    """`ingest/notebook._is_magic` asks whether the **stripped line starts**
    with `%`, `!` or `?`. IPython also accepts a magic on the right of an
    assignment - `files = !ls data`, `PATH = %env PATH` - and those lines reach
    the generated module unchanged, where `!ls data` is a SyntaxError.

    Observed: `filesAnalyzed 0`, `notebooksSkipped 1`, no `train` stage. The
    notebook is declared skipped, so this is loud rather than silent - but the
    training loop two cells down is gone either way, and one unrecognised line
    costing every cell is the design ROB-05 already paid for once.

    `wandb-examples/colabs/tables/AlphaFold_with_W&B_Align,_Fold,_Log.ipynb`
    cell 59 is the `%env` half, verbatim.
    """
    root = tmp_path / "nb20"
    root.mkdir()
    shutil.copy(os.path.join(NOTEBOOKS, "assignment_magic.ipynb"),
                str(root / "n.ipynb"))
    doc = analyze(root, include_notebooks=True)
    assert validate(doc) == []
    assert doc["workspace"]["notebooksSkipped"] == 0, [
        d["message"] for d in diagnostics(doc, "notebook_skipped")]
    assert stage_present(doc, "train")


# --------------------------------------------------------- round 2, ROB-21
@pytest.mark.xfail(reason="ROB-21: single_file_diagnostic discovers the PARENT "
                          "of the analyzed root and names files outside it")
def test_rob21_the_analysis_stays_inside_the_analyzed_root():
    """**MLView reads, and reports on, directories the caller did not name.**

    `core/coverage._package_root()` climbs out of the analyzed directory for as
    long as each level holds an `__init__.py` - which every library package
    does - and `single_file_diagnostic` then runs a second
    `discover([package_root], max_files=1000)`. That root is above
    `workspace.root`.

    Observed on this fixture::

        workspace.root        .../pkgwalk/workspace/pkg
        single_file_analysis  "Only pkg/train.py was analyzed: 3 sibling
                               module(s) in the same package were not
                               (helper.py, pkg/__init__.py,
                               sibling_project/other.py) ..."

    Two of those three are not in this package and are not under
    `workspace.root`; the sentence says they are. On real trees the second
    discover walks the whole repository -
    `pytorch-image-models/timm/models` -> `pytorch-image-models`,
    `detectron2/detectron2/modeling` -> `detectron2`, `yolov5/utils` ->
    `yolov5`, each measured with `os.walk` instrumented.
    """
    doc = analyze(os.path.join(PKGWALK, "pkg"))
    assert validate(doc) == []
    root = doc["workspace"]["root"].replace("\\", "/")
    for diagnostic in doc["diagnostics"]:
        message = diagnostic.get("message") or ""
        assert "sibling_project/other.py" not in message, (
            "a file outside %s is named in a %s diagnostic: %s"
            % (root, diagnostic["kind"], message[:220]))


@pytest.mark.xfail(reason="ROB-21: the second discover() is rooted at the parent of the analyzed directory")
def test_rob21_no_directory_above_the_analyzed_root_is_walked():
    """The mechanism, measured rather than inferred: `os.walk` is instrumented
    for one analysis and every top it is handed is compared with the analyzed
    root.

    Cost, measured on a 200-module workspace whose parent directory is busy:
    **5.37 s with the root `__init__.py` present, 0.33 s with it removed** -
    94% of the run spent walking a tree the caller never named, for a
    diagnostic that was not even emitted. `max_files=1000` truncates the
    *result* of `discover`, never the walk, so nothing bounds the cost.
    """
    target = os.path.abspath(os.path.join(PKGWALK, "pkg"))
    real_walk = os.walk
    tops = []

    def spy(top, *args, **kwargs):
        tops.append(os.path.abspath(str(top)))
        return real_walk(top, *args, **kwargs)

    os.walk = spy
    try:
        analyze(target)
    finally:
        os.walk = real_walk
    repo = os.path.abspath(REPO_ROOT)
    outside = sorted({t for t in tops
                      if not t.startswith(target)
                      and not t.startswith(os.path.join(repo, "analyzer", "src"))})
    assert outside == [], (
        "analysing %s walked %s" % (target, outside))


# --------------------------------------------------------- round 2, ROB-22
#: Every one of these makes `render --graph` print a Python traceback. The
#: format matters for the last row only: `{"issues": [{"id": "x"}]}` reaches a
#: `KeyError: 'severity'` through the mermaid emitter and is survivable through
#: the text one, so it is listed against mermaid alone.
NON_GRAPH_DOCUMENTS = [(payload, fmt)
                       for payload in ("null", "[]", '"hi"', "5", '{"nodes": "x"}')
                       for fmt in ("mermaid", "text")]
NON_GRAPH_DOCUMENTS.append(('{"nodes": [], "edges": [], "issues": [{"id": "x"}]}',
                            "mermaid"))


@pytest.mark.parametrize("payload,fmt", NON_GRAPH_DOCUMENTS,
                         ids=["%s-%s" % (f, p[:14]) for p, f in NON_GRAPH_DOCUMENTS])
@pytest.mark.xfail(reason="ROB-22: `render --graph` tracebacks and exits 3 on "
                          "a JSON document that is not an MLView graph")
def test_rob22_render_of_a_non_graph_document_is_a_usage_error(payload, fmt, tmp_path):
    """`--graph` points at a file a previous run wrote, so a truncated write, a
    merge conflict or a hand edit is routine - and `mlview diff` already gets
    this right: README says "a `base` that is not an MLView graph is an error
    naming the file, never an empty comparison", and round 1 pinned it
    (`test_the_cli_never_tracebacks_on_a_bad_diff_base`). `render` shares
    neither the check nor the exit code.

    Observed::

        $ echo null > t.json && python -m mlview render --graph t.json --format mermaid
        AttributeError: 'NoneType' object has no attribute 'get'
        rc=3

    README's table: `1` is usage or I/O, `3` is *internal error*. A CI harness
    tells "MLView has a bug" from "your file is damaged" by reading that code.
    `{}` is the other half of the same hole - it renders an empty `flowchart LR`
    and exit 0 rather than saying the file is not a graph.
    """
    graph = tmp_path / "t.json"
    graph.write_text(payload, encoding="utf-8")
    rc, _out, err = run_cli("render", "--graph", str(graph), "--format", fmt)
    assert "Traceback" not in err, err[-300:]
    assert rc in (0, 1), "expected 0 or the usage exit code, got %d" % rc


def test_rob22_render_of_a_real_graph_still_works(tmp_path):
    """The control: the same command over a document MLView wrote."""
    graph = tmp_path / "good.json"
    rc, _out, err = run_cli("analyze", os.path.join(SYNTAX, "walrus"),
                            "--json", str(graph))
    assert rc == 0, err[-300:]
    rc, out, err = run_cli("render", "--graph", str(graph), "--format", "mermaid")
    assert rc == 0, err[-300:]
    assert "flowchart" in out


# --------------------------------------------------------- round 2, ROB-23
def _deep_unit_workspace(root):
    """One module, 200 `nn.Module` blocks and a training loop: 608 nodes whose
    every operation hangs off a unit, which is the shape a model zoo has."""
    out = ["import torch\n", "import torch.nn as nn\n",
           "from torch.utils.data import DataLoader\n\n\n"]
    for i in range(200):
        out.append("class Block%d(nn.Module):\n" % i)
        out.append("    def __init__(self):\n        super().__init__()\n"
                   "        self.fc = nn.Linear(8, 8)\n        self.act = nn.ReLU()\n\n")
        out.append("    def forward(self, x):\n        return self.act(self.fc(x))\n\n\n")
    out.append("def train(ds):\n    model = Block0()\n"
               "    opt = torch.optim.Adam(model.parameters())\n"
               "    crit = nn.CrossEntropyLoss()\n"
               "    loader = DataLoader(ds, batch_size=8, shuffle=True)\n"
               "    for xb, yb in loader:\n        opt.zero_grad()\n"
               "        loss = crit(model(xb), yb)\n        loss.backward()\n"
               "        opt.step()\n    return model\n")
    root.mkdir(parents=True, exist_ok=True)
    write_bytes(root, "blocks.py", "".join(out).encode("utf-8"))
    return root


@pytest.mark.parametrize("budget", [20, 45, 100])
@pytest.mark.xfail(reason="ROB-23: the rollup is all-or-nothing per file, so a "
                          "608-node single-module workspace draws ONE node at "
                          "every budget below the whole graph")
def test_rob23_the_node_budget_is_actually_spent(budget, tmp_path):
    """`--max-nodes N` is a request for a diagram of about N cards. On a
    workspace whose operations all hang off units, the rollup folds every unit
    into its file and then folds the file, and stops: **1 node**, at 20, at 45
    and at 100 alike, for a graph of 608. At 400 the same workspace draws 400.

    Measured the same way on the pinned public clones: `vit-pytorch` (3180
    nodes) draws 4 at `--max-nodes 20` *and* 4 at 45;
    `denoising-diffusion-pytorch` (984) draws 18 at both. Raising the budget by
    125% changes nothing, and the `train` lane holds no node at all, so the
    training loop is off the picture at any budget a large repository makes a
    user reach for.

    It is **declared** - the `truncated` diagnostic says "608 of 608 node(s)
    rolled up ... 1 node(s) kept" - and the issue list is invariant, which is
    why this is a `major` and not a misrepresentation. It is still a diagram
    with one card in it.
    """
    root = _deep_unit_workspace(tmp_path / "deepunits")
    doc = analyze(root, max_nodes=budget)
    assert validate(doc) == []
    assert len(doc["nodes"]) >= budget // 2, (
        "--max-nodes %d drew %d node(s) of a %d-node graph; lanes = %s"
        % (budget, len(doc["nodes"]),
           len(analyze(root, max_nodes=100000)["nodes"]),
           sorted({n["stage"] for n in doc["nodes"]})))


def test_rob23_the_rollup_never_changes_the_finding_list(tmp_path):
    """The guard under ROB-23 that already holds and must keep holding: however
    few nodes the budget draws, the issue-id set is the uncapped one and the
    truncation is declared."""
    root = _deep_unit_workspace(tmp_path / "deepunits_issues")
    full = analyze(root, max_nodes=100000)
    for budget in (20, 45, 100, 400):
        capped = analyze(root, max_nodes=budget)
        assert validate(capped) == []
        assert ({i["id"] for i in capped["issues"]}
                == {i["id"] for i in full["issues"]}), budget
        assert capped["stats"]["truncated"] is bool(diagnostics(capped, "truncated"))
