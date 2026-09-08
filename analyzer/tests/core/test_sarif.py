"""SARIF 2.1.0 output (CI-ADOPT part c).

The document is validated against the **official** OASIS schema, vendored at
`tests/fixtures/sarif-schema-2.1.0.json` from
`docs.oasis-open.org/sarif/sarif/v2.1.0/errata01/os/schemas/`. It is a
draft-04 schema, so `Draft4Validator` is the right validator; the test skips
itself if `jsonschema` is not installed, exactly as the contract validator
does.

The four properties with teeth: no absolute path anywhere in the bytes, one
distinct fingerprint per finding, fingerprints that survive an edit above the
finding, and a `rules[]` covering the whole registry so every `helpUri`
resolves.
"""

from __future__ import annotations

import json
import os
import re
import shutil

import pytest

from core_support import FIXTURES, REPO_ROOT
from mlview import cli
from mlview.api import AnalyzeOptions, analyze_to_dict
from mlview.emit import sarif_out
from mlview.rules import all_rules

SAMPLE_DIR = os.path.join(REPO_ROOT, "samples", "vision_pipeline")
SARIF_SCHEMA = os.path.join(FIXTURES, "sarif-schema-2.1.0.json")

#: A drive letter, or a POSIX root that is not a workspace-relative path.
ABSOLUTE = re.compile(r'"(?:[A-Za-z]:/|/)[^"]*"')


@pytest.fixture(scope="module")
def sample_doc():
    return analyze_to_dict(AnalyzeOptions(paths=(SAMPLE_DIR,)))


@pytest.fixture(scope="module")
def sarif(sample_doc):
    return sarif_out.render_sarif(sample_doc)


def test_it_validates_against_the_official_sarif_schema(sarif):
    jsonschema = pytest.importorskip("jsonschema")
    with open(SARIF_SCHEMA, encoding="utf-8") as fh:
        schema = json.load(fh)
    validator = jsonschema.Draft4Validator(schema)
    errors = ["%s: %s" % (list(e.path), e.message)
              for e in validator.iter_errors(sarif)]
    assert errors == []


def test_the_envelope_is_2_1_0(sarif):
    assert sarif["version"] == "2.1.0"
    assert sarif["$schema"] == sarif_out.SARIF_SCHEMA_URI
    assert len(sarif["runs"]) == 1


def test_every_finding_becomes_one_result_with_a_distinct_fingerprint(sarif, sample_doc):
    results = sarif["runs"][0]["results"]
    assert len(results) == len(sample_doc["issues"]) == 15
    fingerprints = [r["partialFingerprints"]["mlviewIssueId"] for r in results]
    assert len(set(fingerprints)) == 15
    assert fingerprints == [i["id"] for i in sample_doc["issues"]]


def test_no_absolute_path_escapes(sarif):
    """GitHub rejects an absolute URI, and a CI log must not leak the runner's
    layout. `originalUriBaseIds` therefore declares the base with no `uri`."""
    text = json.dumps(sarif, ensure_ascii=False)
    for match in ABSOLUTE.findall(text):
        assert match.startswith('"https://'), match
    base = sarif["runs"][0]["originalUriBaseIds"]["%SRCROOT%"]
    assert "uri" not in base and base["description"]["text"]
    for result in sarif["runs"][0]["results"]:
        artifact = result["locations"][0]["physicalLocation"]["artifactLocation"]
        assert artifact["uriBaseId"] == "%SRCROOT%"
        assert not artifact["uri"].startswith("/") and ":" not in artifact["uri"]


def test_rules_cover_the_whole_registry_and_every_help_uri_resolves(sarif):
    rules = sarif["runs"][0]["tool"]["driver"]["rules"]
    registry = all_rules()
    assert [r["id"] for r in rules] == [s.code for s in registry]
    assert len(rules) >= 20
    for rule in rules:
        assert rule["helpUri"] == "docs/rules/%s.md" % rule["id"]
        assert rule["properties"]["helpUriBaseId"] == "%SRCROOT%"
        assert os.path.isfile(os.path.join(REPO_ROOT, rule["helpUri"])), rule["id"]


def test_rule_index_points_at_the_rule_it_names(sarif):
    rules = sarif["runs"][0]["tool"]["driver"]["rules"]
    for result in sarif["runs"][0]["results"]:
        assert rules[result["ruleIndex"]]["id"] == result["ruleId"]


def test_severity_maps_to_a_sarif_level(sarif, sample_doc):
    expected = {"high": "error", "medium": "warning", "low": "note"}
    for result, issue in zip(sarif["runs"][0]["results"], sample_doc["issues"]):
        assert result["level"] == expected[issue["severity"]]
    assert sarif_out.level_for("nonsense") == "warning"


def test_regions_are_one_based_and_carry_the_snippet(sarif, sample_doc):
    for result, issue in zip(sarif["runs"][0]["results"], sample_doc["issues"]):
        region = result["locations"][0]["physicalLocation"]["region"]
        assert region["startLine"] == issue["loc"]["line"]
        assert region["startColumn"] == issue["loc"]["col"] + 1
        assert region["snippet"]["text"] == issue["loc"]["snippet"]


def test_fingerprints_survive_twenty_inserted_blank_lines(tmp_path):
    """CONTRACTS section 0: ids are content-addressed, never line-derived."""
    root = tmp_path / "ws"
    shutil.copytree(SAMPLE_DIR, root)
    before = sarif_out.render_sarif(analyze_to_dict(AnalyzeOptions(paths=(str(root),))))
    path = root / "train.py"
    lines = path.read_text(encoding="utf-8").split("\n")
    path.write_text("\n".join(lines[:16] + [""] * 20 + lines[16:]), encoding="utf-8")
    after = sarif_out.render_sarif(analyze_to_dict(AnalyzeOptions(paths=(str(root),))))

    def prints(doc):
        return [r["partialFingerprints"]["mlviewIssueId"] for r in doc["runs"][0]["results"]]

    assert prints(before) == prints(after)
    moved = [r["locations"][0]["physicalLocation"]["region"]["startLine"]
             for r in after["runs"][0]["results"]]
    assert moved != [r["locations"][0]["physicalLocation"]["region"]["startLine"]
                     for r in before["runs"][0]["results"]], "the lines DID move"


def test_a_suppressed_finding_ships_as_a_suppressed_result(make_workspace):
    root = make_workspace({"t.py": (
        "import torch\nimport torch.nn as nn\nimport torch.optim as optim\n"
        "from torch.utils.data import DataLoader\n\n\n"
        "def train(ds):\n"
        "    model = nn.Linear(4, 2)\n"
        "    crit = nn.CrossEntropyLoss()\n"
        "    opt = optim.Adam(model.parameters())\n"
        "    loader = DataLoader(ds, batch_size=8)\n"
        "    for x, y in loader:  # mlview: ignore[MLV201]\n"
        "        loss = crit(model(x), y)\n"
        "        loss.backward()\n"
        "        opt.step()\n")})
    doc = analyze_to_dict(AnalyzeOptions(paths=(root,)))
    suppressed = [i for i in doc["issues"] if i["suppressed"]]
    assert suppressed, "the fixture must actually suppress something"
    sarif = sarif_out.render_sarif(doc)
    by_id = {r["partialFingerprints"]["mlviewIssueId"]: r for r in sarif["runs"][0]["results"]}
    for issue in suppressed:
        result = by_id[issue["id"]]
        assert result["suppressions"][0]["kind"] == "external"


def test_the_run_carries_what_the_analyzer_could_not_see(sarif, sample_doc):
    """The honesty column survives the CI boundary: diagnostics travel with
    the findings instead of being dropped at the SARIF edge."""
    properties = sarif["runs"][0]["properties"]
    assert properties["filesAnalyzed"] == sample_doc["workspace"]["filesAnalyzed"]
    assert [d["kind"] for d in properties["diagnostics"]] == \
        [d["kind"] for d in sample_doc["diagnostics"]]


# ------------------------------------------------------------------- the CLI
@pytest.fixture
def run(capsysbinary):
    def _run(*argv):
        code = cli.main(list(argv))
        captured = capsysbinary.readouterr()
        return code, captured.out, captured.err.decode("utf-8", "replace")

    return _run


def test_sarif_writes_a_file_and_leaves_stdout_to_the_format(run, tmp_path):
    target = str(tmp_path / "out.sarif")
    code, out, err = run("analyze", SAMPLE_DIR, "--sarif", target)
    assert code == 0 and out.startswith(b"MLView"), "the summary still prints"
    assert "wrote" in err
    with open(target, encoding="utf-8") as fh:
        assert len(json.load(fh)["runs"][0]["results"]) == 15


def test_sarif_dash_writes_to_stdout_and_nothing_else_does(run):
    code, out, _err = run("issues", SAMPLE_DIR, "--sarif", "-")
    assert code == 0
    doc = json.loads(out.decode("utf-8"))
    assert doc["version"] == "2.1.0"


def test_two_payloads_on_stdout_is_a_usage_error(run):
    code, out, err = run("analyze", SAMPLE_DIR, "--sarif", "-", "--json", "-")
    assert code == 1 and out == b""
    assert "both write to stdout" in err


def test_sarif_follows_changed_only(run, tmp_path):
    """The SARIF is a transform of what was emitted, not a second analysis."""
    root = tmp_path / "ws"
    shutil.copytree(SAMPLE_DIR, root)
    listing = tmp_path / "changed.txt"
    listing.write_text("data.py\n", encoding="utf-8")
    target = str(tmp_path / "o.sarif")
    code, _out, _err = run("issues", str(root), "--changed-paths", str(listing),
                           "--changed-only", "--sarif", target)
    assert code == 0
    with open(target, encoding="utf-8") as fh:
        results = json.load(fh)["runs"][0]["results"]
    assert {r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
            for r in results} == {"data.py"}
    assert all(r["baselineState"] == "unchanged" for r in results)


def test_sarif_on_issues_honours_code_but_not_limit_or_hiding(run, tmp_path):
    target = str(tmp_path / "one.sarif")
    code, _out, _err = run("issues", SAMPLE_DIR, "--code", "MLV201",
                           "--limit", "1", "--sarif", target)
    assert code == 0
    with open(target, encoding="utf-8") as fh:
        results = json.load(fh)["runs"][0]["results"]
    assert [r["ruleId"] for r in results] == ["MLV201"]
