"""CFG-ONE (CONTRACTS 11.37): one configuration surface with a stated precedence.

The item's own wording is *"the requirement is a stated precedence with a test,
not more surface"*, so the precedence tests below are the point of this file and
everything else supports them:

* `disable` and `exclude` belong to the file - a host may add and never subtract;
* every `[analysis]` option is the other way round - a **flag wins over the file**;
* whichever file was applied is named in `workspace.configPath`, so no reader
  has to guess which of `.mlview.toml` and `pyproject.toml` decided anything;
* and no mistake in a configuration file may ever stop an analysis from
  happening - every one of them is a `config_warning` on the document.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

from core_support import FIXTURES, validate, write_files
from mlview import cli
from mlview.api import AnalyzeOptions, analyze_to_dict
from mlview.core import config as config_mod
from mlview.rules import RuleConfig, load_config

CONFIG_FIXTURES = os.path.join(FIXTURES, "config")
FULL_TOML = os.path.join(CONFIG_FIXTURES, "toml", "full.mlview.toml")
WARNINGS_TOML = os.path.join(CONFIG_FIXTURES, "toml", "warnings.mlview.toml")
PYPROJECT_WS = os.path.join(CONFIG_FIXTURES, "pyproject_ws")

#: A training loop with **no** `zero_grad`, so it carries an MLV201 (high) as
#: well as the workspace-wide MLV601 (low). Two findings at two severities is
#: what the `enable` / `min_confidence` / severity tests need to bite on.
TORCH_TRAIN = (
    "import torch\n"
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


@pytest.fixture
def run(capsysbinary):
    def _run(*argv):
        code = cli.main(list(argv))
        captured = capsysbinary.readouterr()
        return code, captured.out, captured.err.decode("utf-8", "replace")

    return _run


def _warnings(doc):
    return [d["message"] for d in doc["diagnostics"] if d["kind"] == "config_warning"]


# `.mlview.toml` and `[tool.mlview]` both need a TOML parser, and `tomllib` is
# stdlib only from 3.11. `core/config.py:191-193` degrades on 3.10 by appending a
# `config_warning` and ignoring the file, so on 3.10 every test below would be
# asserting the behaviour of a parser that is not there. The convention, the
# wording and the reason string are lifted from
# `analyzer/tests/rules/test_suppression.py`, which found the same thing when
# CI-01 put 3.10 in the matrix; the degradation itself is asserted here by
# `test_below_3_11_the_file_is_ignored_out_loud_and_the_analysis_still_runs`,
# which runs ONLY on 3.10 so the skip is never silence.
NEEDS_TOMLLIB = pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="tomllib is stdlib from 3.11; a config file is ignored with a config_warning below that",
)


# ------------------------------------------------------------- the surface
@NEEDS_TOMLLIB
def test_every_table_is_read_from_one_file():
    config = load_config(FULL_TOML)
    assert config.disabled == {"MLV601"}
    assert config.excludes == ("experiments/**",)
    assert config.includes == ("src/**",)
    assert config.notebooks is True
    assert config.min_confidence == pytest.approx(0.42)
    assert config.analysis == {"relevance": "all", "relevance_hops": 3,
                               "dataflow": "ip", "max_nodes": 77,
                               "include_notebooks": True}
    assert config.baseline_path.endswith("config/toml/ci/baseline.json")
    assert config.severity == {"MLV201": "low"}


def test_the_historical_rule_config_name_still_resolves():
    """`mlview.rules.RuleConfig` is what every caller in and out of this tree
    imports; CFG-ONE moved the implementation, not the import path."""
    assert RuleConfig is config_mod.MlviewConfig
    assert isinstance(RuleConfig(), config_mod.MlviewConfig)
    assert load_config(None, None).path is None


@NEEDS_TOMLLIB
def test_pyproject_is_read_when_there_is_no_mlview_toml():
    config = load_config(None, PYPROJECT_WS)
    assert config.source == "pyproject.toml"
    assert config.path.endswith("pyproject_ws/pyproject.toml")
    assert config.disabled == {"MLV601"}
    assert config.excludes == ("scratch/**",)
    assert config.analysis == {"max_nodes": 55}


@NEEDS_TOMLLIB
def test_mlview_toml_wins_outright_over_pyproject(tmp_path):
    """They are never merged. Two half-applied files is the confusion CFG-ONE
    exists to end, and `configPath` can only name one of them."""
    root = write_files(str(tmp_path), {
        "train.py": TORCH_TRAIN,
        ".mlview.toml": "[rules]\ndisable = [\"MLV601\"]\n",
        "pyproject.toml": "[tool.mlview.rules]\ndisable = [\"MLV201\"]\n"})
    config = load_config(None, root)
    assert config.path.endswith(".mlview.toml")
    assert config.disabled == {"MLV601"}


@NEEDS_TOMLLIB
def test_a_pyproject_with_no_tool_mlview_is_not_a_configuration_file(tmp_path):
    root = write_files(str(tmp_path), {
        "train.py": TORCH_TRAIN,
        "pyproject.toml": "[project]\nname = \"x\"\nversion = \"0\"\n"})
    config = load_config(None, root)
    assert config.path is None and config.source is None
    doc = analyze_to_dict(AnalyzeOptions(paths=(root,), cache=False))
    assert "configPath" not in doc["workspace"]


@NEEDS_TOMLLIB
def test_the_applied_file_is_named_in_workspace_config_path(tmp_path):
    root = write_files(str(tmp_path), {
        "train.py": TORCH_TRAIN,
        ".mlview.toml": "[rules]\ndisable = [\"MLV601\"]\n"})
    doc = analyze_to_dict(AnalyzeOptions(paths=(root,), cache=False))
    assert doc["workspace"]["configPath"].endswith("/.mlview.toml")
    assert validate(doc) == []


@NEEDS_TOMLLIB
def test_a_pyproject_config_is_named_too():
    doc = analyze_to_dict(AnalyzeOptions(paths=(PYPROJECT_WS,), cache=False))
    assert doc["workspace"]["configPath"].endswith("/pyproject.toml")


# ------------------------------------------------------------- precedence
@NEEDS_TOMLLIB
def test_the_file_wins_for_disable_and_exclude(tmp_path):
    """The lead's decision, asserted: `disable` and `exclude` are the file's.
    A caller may add to them - `--exclude` below still applies - and there is
    no flag, setting or host that can take one away."""
    root = write_files(str(tmp_path), {
        "train.py": TORCH_TRAIN,
        "other.py": TORCH_TRAIN,
        "third.py": TORCH_TRAIN,
        ".mlview.toml": "[paths]\nexclude = [\"other.py\"]\n"})
    doc = analyze_to_dict(AnalyzeOptions(paths=(root,), exclude=("third.py",),
                                         cache=False))
    files = {n["loc"]["file"] for n in doc["nodes"]}
    assert "other.py" not in files and "third.py" not in files
    assert "train.py" in files


@NEEDS_TOMLLIB
def test_a_flag_wins_over_the_file_for_an_analysis_option(tmp_path):
    root = write_files(str(tmp_path), {
        "train.py": TORCH_TRAIN,
        ".mlview.toml": "[analysis]\nmax_nodes = 3\nrelevance = \"ml\"\n"})
    from_file = analyze_to_dict(AnalyzeOptions(paths=(root,), cache=False))
    assert from_file["stats"]["truncated"] is True          # the file's 3 applied
    from_flag = analyze_to_dict(AnalyzeOptions(paths=(root,), max_nodes=200,
                                               relevance="all", cache=False))
    assert from_flag["stats"]["truncated"] is False, "the flag beat the file"
    assert not [d for d in from_flag["diagnostics"]
                if "Relevance prefilter" in d["message"]], "and so did --relevance all"


@NEEDS_TOMLLIB
def test_the_one_case_the_precedence_cannot_see(tmp_path):
    """Stated in `core/config.py` and asserted here rather than discovered:
    `AnalyzeOptions` carries values, not provenance, so a caller who *types* a
    flag at exactly its shipped default is indistinguishable from one who typed
    nothing, and the file wins that one case."""
    root = write_files(str(tmp_path), {
        "train.py": TORCH_TRAIN,
        ".mlview.toml": "[analysis]\nmax_nodes = 3\n"})
    typed_the_default = analyze_to_dict(
        AnalyzeOptions(paths=(root,), max_nodes=400, cache=False))
    assert typed_the_default["stats"]["truncated"] is True


@NEEDS_TOMLLIB
def test_include_is_additive_in_both_directions(tmp_path):
    root = write_files(str(tmp_path), {
        "src/train.py": TORCH_TRAIN,
        "extra/other.py": TORCH_TRAIN,
        "skip/third.py": TORCH_TRAIN,
        ".mlview.toml": "[paths]\ninclude = [\"src/**\"]\n"})
    doc = analyze_to_dict(AnalyzeOptions(paths=(root,), include=("extra/**",),
                                         cache=False))
    files = {n["loc"]["file"] for n in doc["nodes"]}
    assert files == {"src/train.py", "extra/other.py"}


@NEEDS_TOMLLIB
def test_min_confidence_from_the_file_filters_the_document(tmp_path):
    root = write_files(str(tmp_path), {
        "train.py": TORCH_TRAIN,
        ".mlview.toml": "[rules]\nmin_confidence = 0.99\n"})
    empty = str(tmp_path / "empty.toml")
    with open(empty, "w", encoding="utf-8") as handle:
        handle.write("")
    doc = analyze_to_dict(AnalyzeOptions(paths=(root,), cache=False))
    assert all(i["confidence"] >= 0.99 for i in doc["issues"])
    # `--config` naming an empty file is how a caller says "no configuration":
    # it wins the A1 order outright, so the `.mlview.toml` beside it is not read.
    wide = analyze_to_dict(AnalyzeOptions(paths=(root,), cache=False,
                                          config_path=empty))
    assert len(wide["issues"]) > len(doc["issues"])


@NEEDS_TOMLLIB
def test_enable_is_an_allow_list_and_disable_still_wins(tmp_path):
    root = write_files(str(tmp_path), {
        "train.py": TORCH_TRAIN,
        ".mlview.toml": ("[rules]\nenable = [\"MLV201\", \"MLV601\"]\n"
                         "disable = [\"MLV601\"]\n")})
    doc = analyze_to_dict(AnalyzeOptions(paths=(root,), cache=False))
    live = {i["code"] for i in doc["issues"] if not i["suppressed"]}
    assert live <= {"MLV201"}
    assert any("MLV601 is in both" in w for w in _warnings(doc))
    # A rule outside the allow-list is SUPPRESSED, never deleted: the schema
    # requires the finding to be emitted so a UI can offer "show suppressed".
    assert any(i["suppressed"] for i in doc["issues"])


# ----------------------------------------------------- mistakes are warnings
@NEEDS_TOMLLIB
def test_a_severity_override_is_a_warning_not_an_error():
    config = load_config(FULL_TOML)
    assert any("severities are fixed" in w and "MLV201" in w
               for w in config.warnings)
    assert config.severity == {"MLV201": "low"}


@NEEDS_TOMLLIB
def test_the_shipped_severity_is_what_the_document_carries(tmp_path):
    root = write_files(str(tmp_path), {
        "train.py": TORCH_TRAIN,
        ".mlview.toml": "[rules.severity]\nMLV201 = \"low\"\n"})
    doc = analyze_to_dict(AnalyzeOptions(paths=(root,), cache=False))
    hits = [i for i in doc["issues"] if i["code"] == "MLV201"]
    assert hits and all(i["severity"] == "high" for i in hits)
    assert any("severities are fixed" in w for w in _warnings(doc))


@NEEDS_TOMLLIB
def test_every_mistake_is_a_warning_and_none_is_fatal():
    config = load_config(WARNINGS_TOML)
    joined = "\n".join(config.warnings)
    for fragment in ("[paths] exclude must be a list",
                     "[paths] notebooks must be true or false",
                     "unknown key excludes in [paths]",
                     "unknown key dataflows in [analysis]",
                     "[analysis] relevance",
                     "[analysis] max_nodes",
                     "unknown key paths in [baseline]",
                     "unknown section [nonsense]",
                     "min_confidence must be between 0 and 1",
                     "unknown rule code MVL601",
                     "unknown rule code MLV999",
                     "severities are fixed"):
        assert fragment in joined, fragment
    # Nothing usable was thrown away with the mistakes.
    assert config.analysis == {} and config.min_confidence is None


@NEEDS_TOMLLIB
def test_a_broken_file_still_analyzes(tmp_path):
    root = write_files(str(tmp_path), {
        "train.py": TORCH_TRAIN,
        ".mlview.toml": "[rules\ndisable = ["})
    doc = analyze_to_dict(AnalyzeOptions(paths=(root,), cache=False))
    assert doc["nodes"], "a bad config must never stop an analysis"
    assert any("cannot parse" in w for w in _warnings(doc))
    assert validate(doc) == []


# ------------------------------------------------------------------ baseline
@NEEDS_TOMLLIB
def test_the_baseline_path_comes_from_the_file(tmp_path, run):
    """`[baseline] path` is the checked-in half of `--baseline`. It is applied
    in the CLI rather than in the pipeline because CI-ADOPT applies a baseline
    to the finished graph, never to the analysis."""
    root = write_files(str(tmp_path), {"train.py": TORCH_TRAIN})
    first = analyze_to_dict(AnalyzeOptions(paths=(root,), cache=False))
    assert first["issues"], "the fixture must have something to baseline"
    baseline = os.path.join(root, "ci", "base.json")
    code, _out, _err = run("baseline", "write", root, "--out", baseline)
    assert code == 0 and os.path.isfile(baseline)
    with open(os.path.join(root, ".mlview.toml"), "w", encoding="utf-8") as handle:
        handle.write("[baseline]\npath = \"ci/base.json\"\n")

    code, out, _err = run("issues", root, "--json")
    assert code == 0
    payload = json.loads(out.decode("utf-8"))
    assert payload.get("baselinedCount", 0) == len(first["issues"])


@NEEDS_TOMLLIB
def test_the_baseline_path_is_relative_to_the_file_that_named_it():
    config = load_config(FULL_TOML)
    assert os.path.isabs(config.baseline_path)
    assert config.baseline_path.startswith(
        os.path.dirname(FULL_TOML).replace("\\", "/"))


# -------------------------------------------------------------- mlview init
def test_init_lists_every_registered_rule_with_its_severity():
    from mlview.rules import all_rules

    text = config_mod.render_init()
    for spec in all_rules():
        assert ("#   %-6s  %-6s  %s" % (spec.code, spec.severity, spec.title)
                ) in text, spec.code
    assert "%d rules this build registers" % len(all_rules()) in text


@NEEDS_TOMLLIB
def test_init_writes_a_file_that_parses_and_changes_nothing(tmp_path, run):
    import tomllib

    root = write_files(str(tmp_path), {"train.py": TORCH_TRAIN})
    before = analyze_to_dict(AnalyzeOptions(paths=(root,), cache=False))
    code, out, err = run("init", root)
    assert code == 0 and out == b"", "the payload is the file; stdout stays empty"
    written = os.path.join(root, ".mlview.toml")
    assert os.path.isfile(written) and written.replace("\\", "/") in err
    with open(written, "rb") as handle:
        assert sorted(tomllib.load(handle)) == ["analysis", "baseline", "paths", "rules"]
    after = analyze_to_dict(AnalyzeOptions(paths=(root,), cache=False))
    assert [i["id"] for i in after["issues"]] == [i["id"] for i in before["issues"]]
    assert after["workspace"]["configPath"].endswith("/.mlview.toml")


def test_init_refuses_to_overwrite_without_force(tmp_path, run):
    root = write_files(str(tmp_path), {"train.py": TORCH_TRAIN})
    target = os.path.join(root, ".mlview.toml")
    with open(target, "w", encoding="utf-8") as handle:
        handle.write("[rules]\ndisable = [\"MLV601\"]\n")
    code, out, err = run("init", root)
    assert code == 1 and out == b"" and "--force" in err
    with open(target, encoding="utf-8") as handle:
        assert "MLV601" in handle.read(), "the human's file survived"
    code, _out, _err = run("init", root, "--force")
    assert code == 0
    with open(target, encoding="utf-8") as handle:
        assert "Generated by `mlview init`" in handle.read()


def test_init_to_stdout_is_the_payload(tmp_path, run):
    code, out, _err = run("init", str(tmp_path), "--out", "-")
    assert code == 0
    assert out.decode("utf-8").startswith("# .mlview.toml")
    assert not os.path.exists(os.path.join(str(tmp_path), ".mlview.toml"))


@pytest.mark.skipif(
    sys.version_info >= (3, 11),
    reason="tomllib is present from 3.11, so there is no degradation to observe",
)
def test_below_3_11_the_file_is_ignored_out_loud_and_the_analysis_still_runs(tmp_path):
    """The counterpart of `NEEDS_TOMLLIB`: on 3.10 CFG-ONE has no parser, and the
    one thing it must not do is pretend. `core/config.py` says so in a
    `config_warning` that names the file it ignored, and lets the analysis finish
    - a configuration file MLView cannot read must never be a configuration file
    that stops a run.

    CFG-CONFIG-WARNING-DROPPED re-pointed one assertion here. This used to
    require the ignored file to keep its `path` and `source`, which meant
    `workspace.configPath` named a file that had decided **nothing** - exactly
    the reading a user cannot tell apart from an applied one, and the failure
    §11.37 A3 exists to prevent. The warning is what survives now; the path is
    not, on 3.10 for the same reason as on 3.13."""
    config = load_config(FULL_TOML)
    assert config.path is None and config.source is None
    assert config.disabled == set() and config.analysis == {}
    assert any("tomllib is unavailable" in w for w in config.warnings), config.warnings
    assert FULL_TOML in "\n".join(config.warnings)

    root = write_files(str(tmp_path), {
        "train.py": TORCH_TRAIN,
        ".mlview.toml": '[rules]\ndisable = ["MLV201"]\n'})
    doc = analyze_to_dict(AnalyzeOptions(paths=(root,), cache=False))
    assert doc["nodes"], "an unreadable config must never stop an analysis"
    assert any("tomllib is unavailable" in w for w in _warnings(doc))
    # And the rule it could not disable is still reported, rather than silently
    # dropped as if the file had been honoured.
    assert any(i["code"] == "MLV201" and not i["suppressed"] for i in doc["issues"])
    assert validate(doc) == []
