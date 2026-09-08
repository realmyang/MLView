"""Hostile and degenerate input never crashes the analyzer (A7 robustness).

A syntax error, a non-UTF-8 byte, an empty file, a notebook, a `getattr`
factory, a broken rule and an unreadable config all become *diagnostics* -
the run still produces a schema-valid document and exit code 0.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

from core_support import validate
from mlview.api import AnalyzeOptions, analyze_to_dict
from mlview.rules import compute_confidence, cap_severity
from mlview.rules.confidence import DYNAMIC_FACTOR, WRAPPER_FACTOR
from mlview.rules.registry import RuleSpec, REGISTRY, run_all

TRAIN = ("import torch\n"
         "import torch.nn as nn\n"
         "import torch.optim as optim\n"
         "from torch.utils.data import DataLoader\n\n\n"
         "def train(ds):\n"
         "    model = nn.Linear(4, 2)\n"
         "    crit = nn.CrossEntropyLoss()\n"
         "    opt = optim.Adam(model.parameters())\n"
         "    loader = DataLoader(ds, batch_size=8)\n"
         "    for x, y in loader:\n"
         "        loss = crit(model(x), y)\n"
         "        loss.backward()\n"
         "        opt.step()\n")


def _diagnostics(doc, kind):
    return [d for d in doc["diagnostics"] if d["kind"] == kind]


# ------------------------------------------------------------- malformed input
def test_a_syntax_error_is_a_diagnostic_not_a_crash(analyze_ws):
    doc = analyze_ws({"good.py": TRAIN, "broken.py": "import torch\ndef nope(:\n"})
    assert doc["workspace"]["filesAnalyzed"] == 1
    assert doc["workspace"]["filesFailed"] == 1
    errors = _diagnostics(doc, "parse_error")
    assert len(errors) == 1
    assert errors[0]["file"] == "broken.py"
    assert errors[0]["line"] == 2
    assert "SyntaxError" in errors[0]["message"]
    assert doc["nodes"], "the healthy file was still analyzed"
    assert validate(doc) == []


def test_a_non_utf8_file_is_a_diagnostic(make_workspace):
    root = make_workspace({"good.py": TRAIN})
    with open(os.path.join(root, "latin1.py"), "wb") as fh:
        fh.write(b'import torch\n# caf\xe9\ndevice = torch.device("cpu")\n')
    doc = analyze_to_dict(AnalyzeOptions(paths=(root,)))
    errors = _diagnostics(doc, "parse_error")
    assert [e["file"] for e in errors] == ["latin1.py"]
    assert "UnicodeDecodeError" in errors[0]["message"]
    assert doc["workspace"]["filesFailed"] == 1
    assert validate(doc) == []


def test_an_empty_file_is_analyzed_without_incident(analyze_ws):
    doc = analyze_ws({"empty.py": "", "blank.py": "\n\n# just a comment\n"})
    assert doc["workspace"]["filesAnalyzed"] == 2
    assert doc["workspace"]["filesFailed"] == 0
    assert doc["nodes"] == []
    assert validate(doc) == []


def test_notebooks_are_counted_not_parsed(make_workspace):
    root = make_workspace({"train.py": TRAIN})
    for name in ("a.ipynb", "b.ipynb"):
        with open(os.path.join(root, name), "w", encoding="utf-8") as fh:
            json.dump({"cells": [], "metadata": {}}, fh)
    doc = analyze_to_dict(AnalyzeOptions(paths=(root,)))
    assert doc["workspace"]["notebooksSkipped"] == 2
    assert doc["workspace"]["filesAnalyzed"] == 1
    skipped = _diagnostics(doc, "notebook_skipped")
    assert skipped and skipped[0]["count"] == 2


def test_a_missing_path_is_a_config_warning(tmp_path):
    doc = analyze_to_dict(AnalyzeOptions(paths=(str(tmp_path / "nowhere"),)))
    warnings = _diagnostics(doc, "config_warning")
    assert warnings and "does not exist" in warnings[0]["message"]
    assert validate(doc) == []


def test_deeply_nested_and_oddly_named_files_still_resolve(analyze_ws):
    doc = analyze_ws({"a/b/c/d/e/train_2024-v1.py": TRAIN})
    assert doc["workspace"]["filesAnalyzed"] == 1
    assert all("\\" not in n["loc"]["file"] for n in doc["nodes"])
    assert all(n["loc"]["file"].startswith("a/b/c/d/e/") for n in doc["nodes"])


def test_crlf_source_keeps_correct_columns(make_workspace):
    root = make_workspace({})
    with open(os.path.join(root, "crlf.py"), "wb") as fh:
        fh.write(TRAIN.replace("\n", "\r\n").encode("utf-8"))
    doc = analyze_to_dict(AnalyzeOptions(paths=(root,)))
    assert doc["nodes"]
    for node in doc["nodes"]:
        loc = node["loc"]
        assert "\r" not in (loc.get("snippet") or "")
    assert validate(doc) == []


# ------------------------------------------------------------- dynamic scopes
def test_a_getattr_factory_degrades_instead_of_guessing(analyze_ws):
    doc = analyze_ws({"reg.py": ("import torch.nn as nn\n\n\n"
                                 "def build(name, **cfg):\n"
                                 "    factory = getattr(nn, name)\n"
                                 "    return factory(**cfg)\n")})
    scopes = _diagnostics(doc, "dynamic_scope")
    assert scopes, "the scope is reported, not silently trusted"
    assert scopes[0]["scope"] == "reg.build"
    assert "getattr" in scopes[0]["message"]
    assert any(n["dynamic"] for n in doc["nodes"])
    assert validate(doc) == []


def test_a_dynamic_scope_de_rates_confidence_exactly_once(analyze_ws):
    static = analyze_ws({"t.py": TRAIN})
    dynamic = analyze_ws({"t.py": TRAIN.replace(
        "def train(ds):\n",
        "def train(ds, name='ReLU'):\n    extra = getattr(nn, name)()\n")})
    issue = next(i for i in static["issues"] if i["code"] == "MLV201")
    derated = next(i for i in dynamic["issues"] if i["code"] == "MLV201")
    assert derated["confidence"] == pytest.approx(issue["confidence"] * DYNAMIC_FACTOR,
                                                  abs=0.002)
    assert derated["severity"] == "medium", "the absence cap bites in a dynamic scope"
    assert issue["severity"] == "high"
    assert "scope_static" not in {e["kind"] for e in derated["evidence"]}


# -------------------------------------------------------------- framework gate
LIT = ("import pytorch_lightning as pl\n"
       "import torch.nn as nn\n\n\n"
       "class Lit(pl.LightningModule):\n"
       "    def __init__(self):\n"
       "        super().__init__()\n"
       "        self.net = nn.Linear(4, 2)\n")


def test_a_lightning_wrapper_gates_the_absence_rules_in_its_own_module(analyze_ws):
    doc = analyze_ws({"t.py": LIT + "\n\n" + TRAIN})
    issue = next(i for i in doc["issues"] if i["code"] == "MLV201")
    assert issue["severity"] == "medium", "the cap forbids high when a wrapper exists"
    assert issue["confidence"] < 0.5
    gate = _diagnostics(doc, "framework_suppressed")
    assert gate, "the gate names itself so a user can tell why the score dropped"
    assert len(gate) == 1, "one diagnostic lists every de-rated code"
    assert "MLV201" in gate[0]["codes"]
    assert gate[0]["codes"] == sorted(gate[0]["codes"])
    assert "Lightning" in gate[0]["message"]


def test_the_gate_follows_a_workspace_import(analyze_ws):
    """A `train.py` that imports the LightningModule *is* covered by the gate."""
    doc = analyze_ws({"lit.py": LIT, "t.py": "from lit import Lit\n" + TRAIN})
    issue = next(i for i in doc["issues"] if i["code"] == "MLV201")
    assert issue["severity"] == "medium"
    assert _diagnostics(doc, "framework_suppressed")


def test_an_unrelated_wrapper_file_does_not_gate_a_handwritten_loop(analyze_ws):
    """One Trainer script must not silently de-rate the findings next door.

    `t.py` neither imports `lit.py` nor is imported by it, so its loop is
    hand-written and the finding keeps its full weight.
    """
    doc = analyze_ws({"lit.py": LIT, "t.py": TRAIN})
    issue = next(i for i in doc["issues"] if i["code"] == "MLV201")
    assert issue["severity"] == "high"
    assert issue["confidence"] >= 0.9
    assert not _diagnostics(doc, "framework_suppressed")


# ------------------------------------------------------------------ rule errors
def _install_broken_rule(monkeypatch):
    def explode(_ctx):
        raise ZeroDivisionError("rule bug")

    spec = RuleSpec(code="MLV000", severity="low", base_prior=0.5, frameworks=(),
                    rule_version=1, tags=(), absence=False, enabled=True,
                    title="broken", why="", fix_hint="", func=explode,
                    module="tests")
    monkeypatch.setitem(REGISTRY, "MLV000", spec)


def test_a_raising_rule_becomes_a_diagnostic(monkeypatch, analyze_ws):
    _install_broken_rule(monkeypatch)
    doc = analyze_ws({"t.py": TRAIN})
    errors = _diagnostics(doc, "rule_error")
    assert len(errors) == 1
    assert errors[0]["ruleCode"] == "MLV000"
    assert "ZeroDivisionError" in errors[0]["message"]
    assert any(i["code"] == "MLV201" for i in doc["issues"]), "other rules still ran"
    assert validate(doc) == []


def test_strict_re_raises_a_rule_error(monkeypatch, analyze_ws):
    _install_broken_rule(monkeypatch)
    with pytest.raises(ZeroDivisionError):
        analyze_ws({"t.py": TRAIN}, strict=True)


def test_a_disabled_rule_never_runs(monkeypatch, analyze_ws):
    _install_broken_rule(monkeypatch)
    monkeypatch.setitem(REGISTRY, "MLV000",
                        REGISTRY["MLV000"].__class__(**{
                            **REGISTRY["MLV000"].__dict__, "enabled": False}))
    doc = analyze_ws({"t.py": TRAIN})
    assert _diagnostics(doc, "rule_error") == []


# ------------------------------------------------------------------ suppression
def test_an_ignore_comment_marks_the_issue_without_removing_it(make_workspace):
    source = TRAIN.replace("    for x, y in loader:\n",
                           "    for x, y in loader:  # mlview: ignore[MLV201]\n")
    root = make_workspace({"t.py": source})
    doc = analyze_to_dict(AnalyzeOptions(paths=(root,)))
    issue = next(i for i in doc["issues"] if i["code"] == "MLV201")
    assert issue["suppressed"] is True
    assert doc["stats"]["suppressed"] == 1
    assert [n for n in doc["nodes"] if n["ghost"]], "the ghost stays for 'show suppressed'"
    assert validate(doc) == []


def test_an_ignore_comment_on_the_line_above_also_counts(make_workspace):
    source = TRAIN.replace("    for x, y in loader:\n",
                           "    # mlview: ignore[MLV201]\n    for x, y in loader:\n")
    doc = analyze_to_dict(AnalyzeOptions(paths=(make_workspace({"t.py": source}),)))
    assert next(i for i in doc["issues"] if i["code"] == "MLV201")["suppressed"] is True


def test_a_bare_ignore_covers_every_code(make_workspace):
    source = TRAIN.replace("    for x, y in loader:\n",
                           "    for x, y in loader:  # mlview: ignore\n")
    doc = analyze_to_dict(AnalyzeOptions(paths=(make_workspace({"t.py": source}),)))
    assert next(i for i in doc["issues"] if i["code"] == "MLV201")["suppressed"] is True


def test_a_different_code_is_not_suppressed(make_workspace):
    source = TRAIN.replace("    for x, y in loader:\n",
                           "    for x, y in loader:  # mlview: ignore[MLV999]\n")
    doc = analyze_to_dict(AnalyzeOptions(paths=(make_workspace({"t.py": source}),)))
    assert next(i for i in doc["issues"] if i["code"] == "MLV201")["suppressed"] is False


def test_ignore_file_in_the_header_covers_the_whole_file(make_workspace):
    doc = analyze_to_dict(AnalyzeOptions(paths=(make_workspace(
        {"t.py": "# mlview: ignore-file\n" + TRAIN}),)))
    assert all(i["suppressed"] for i in doc["issues"])


def test_ignore_file_below_the_header_does_nothing(make_workspace):
    source = TRAIN.replace("def train(ds):", "# mlview: ignore-file\ndef train(ds):")
    doc = analyze_to_dict(AnalyzeOptions(paths=(make_workspace({"t.py": source}),)))
    assert any(not i["suppressed"] for i in doc["issues"])


# ---------------------------------------------------------------- .mlview.toml
# `.mlview.toml` needs a TOML parser, and tomllib is stdlib only from 3.11.
# `rules/suppress.py:53-55` degrades on 3.10 by appending a `config_warning` and
# ignoring the file, so on 3.10 these tests would be asserting the behaviour of a
# parser that is not there. The degradation itself is asserted by
# `test_a_missing_tomllib_says_so_instead_of_pretending`
# (analyzer/tests/rules/test_suppression.py). CI-01 put 3.10 in the matrix and
# this is what it found.
NEEDS_TOMLLIB = pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="tomllib is stdlib from 3.11; .mlview.toml is ignored with a config_warning below that",
)


def _with_config(make_workspace, toml: str, files=None):
    root = make_workspace({**(files or {"t.py": TRAIN}), ".mlview.toml": toml})
    return analyze_to_dict(AnalyzeOptions(paths=(root,)))


@NEEDS_TOMLLIB
def test_config_disable_suppresses_but_still_emits(make_workspace):
    doc = _with_config(make_workspace, '[rules]\ndisable = ["MLV201"]\n')
    assert doc["workspace"]["configPath"].endswith(".mlview.toml")
    issue = next(i for i in doc["issues"] if i["code"] == "MLV201")
    assert issue["suppressed"] is True, "the schema requires it to stay in the document"
    assert doc["stats"]["suppressed"] >= 1


@NEEDS_TOMLLIB
def test_config_path_excludes_are_applied(make_workspace):
    doc = _with_config(make_workspace, '[paths]\nexclude = ["skipme/**"]\n',
                       files={"t.py": TRAIN, "skipme/other.py": TRAIN})
    assert doc["workspace"]["filesAnalyzed"] == 1
    assert all(not n["loc"]["file"].startswith("skipme/") for n in doc["nodes"])


@NEEDS_TOMLLIB
def test_an_unparseable_config_is_a_warning_not_a_crash(make_workspace):
    doc = _with_config(make_workspace, "[rules\ndisable = nope\n")
    warnings = _diagnostics(doc, "config_warning")
    assert warnings and "cannot parse" in warnings[0]["message"]
    assert doc["nodes"], "analysis continued"
    assert validate(doc) == []


@NEEDS_TOMLLIB
def test_an_explicit_config_path_is_honoured(make_workspace, tmp_path):
    root = make_workspace({"t.py": TRAIN})
    config = tmp_path / "custom.toml"
    config.write_text('[rules]\ndisable = ["MLV201"]\n', encoding="utf-8")
    doc = analyze_to_dict(AnalyzeOptions(paths=(root,), config_path=str(config)))
    assert doc["workspace"]["configPath"].endswith("custom.toml")
    assert next(i for i in doc["issues"] if i["code"] == "MLV201")["suppressed"] is True


# ------------------------------------------------------------- confidence model
def test_the_confidence_formula_is_the_documented_product():
    assert compute_confidence(0.9, []) == 0.9
    assert compute_confidence(0.9, [], dynamic=True) == pytest.approx(0.63)
    assert compute_confidence(0.9, [], wrapper_gate=True) == pytest.approx(0.36)
    assert compute_confidence(0.9, [], dynamic=True, wrapper_gate=True) == pytest.approx(
        0.9 * DYNAMIC_FACTOR * WRAPPER_FACTOR, abs=0.002)


def test_confidence_is_clamped_to_a_usable_band():
    assert compute_confidence(1.5, []) <= 1.0
    assert compute_confidence(0.0, []) >= 0.0
    assert 0.0 <= compute_confidence(0.01, [("x", "", 0.01)]) <= 1.0


def test_the_absence_severity_cap():
    # high survives only when the scope is static AND no wrapper was detected
    assert cap_severity("high", absence=True, static_scope=True, wrapper_present=False) == "high"
    assert cap_severity("high", absence=True, static_scope=False,
                        wrapper_present=False) == "medium"
    assert cap_severity("high", absence=True, static_scope=True,
                        wrapper_present=True) == "medium"
    # a presence rule is never capped, and medium/low never move
    assert cap_severity("high", absence=False, static_scope=False,
                        wrapper_present=True) == "high"
    assert cap_severity("medium", absence=True, static_scope=False,
                        wrapper_present=True) == "medium"


# --------------------------------------------------------------- precision
NON_ML = {
    "util.py": ("import os\n"
                "import re\n\n\n"
                "def split_path(path):\n"
                "    parts = path.split('/')\n"
                "    out = []\n"
                "    for i in range(1, len(parts)):\n"
                "        out.append('/'.join(parts[:i]))\n"
                "    return out\n\n\n"
                "def retry(fn, attempts=3):\n"
                "    for attempt in range(attempts):\n"
                "        try:\n"
                "            return fn()\n"
                "        except OSError:\n"
                "            continue\n"
                "    raise RuntimeError('gave up')\n"),
    "cache.py": ("import json\n\n\n"
                 "def load(path):\n"
                 "    with open(path) as fh:\n"
                 "        return json.load(fh)\n\n\n"
                 "def warm(paths):\n"
                 "    for i in range(10):\n"
                 "        load(paths[i])\n"),
}


def test_ordinary_python_produces_no_findings(analyze_ws):
    """A workspace with no ML framework has no ML problems to report."""
    doc = analyze_ws(NON_ML)
    assert doc["workspace"]["frameworks"] == []
    assert doc["issues"] == [], [i["code"] for i in doc["issues"]]
    assert validate(doc) == []


def test_index_and_retry_loops_are_not_training_loops(analyze_ws):
    """`range(1, len(parts))` and `range(attempts)` count nothing epoch-shaped.

    A *fully literal* `range(10)` is epoch-classified by contract (section 3 of
    the brief), so only the non-literal loops are asserted here.
    """
    doc = analyze_ws(NON_ML)
    lines = {(n["loc"]["file"], n["loc"]["line"])
             for n in doc["nodes"] if n.get("attrs", {}).get("loopKind")}
    assert ("util.py", 7) not in lines, "range(1, len(parts)) is index arithmetic"
    assert ("util.py", 13) not in lines, "range(attempts) is a retry budget"
