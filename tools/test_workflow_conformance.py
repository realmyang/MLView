"""Schema and helper layers of the WorkflowDocument conformance corpus, plus the checks of whole documents.

The corpus lives in contracts/conformance (see its README). Every case is
materialised into a fresh temporary workspace by contracts/conformance/helper_bridge.py,
which this runner shares with the extension runner
(vscode-extension/test/conformance.test.js). This file asserts:

* the case format, and that no expectation is `unverified` and no divergence is `open`;
* `expect.schema` under the strict schema layer (Draft 2020-12, full-match `pattern`,
  stdlib RFC 3339 `date-time`);
* `expect.helper` exactly (codes, warnings, stale files and fingerprints);
* the helper half of the round trip: publish, then re-validate the published artifact;
* the parity invariant on the committed expectations (the extension runner checks it on
  actual results);
* whole documents: every sample diagram under samples/, the eight test documents of
  contracts/conformance/documents and the bundled skill example are schema-valid under the
  strict layer and pass the helper's structural checks; each test document validates fully and
  fresh against its workspace (tools/test_samples.py validates each sample diagram in full).
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE_PATH = ROOT / "contracts" / "conformance" / "helper_bridge.py"
_SPEC = importlib.util.spec_from_file_location("mlview_conformance_bridge", BRIDGE_PATH)
bridge = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader
_SPEC.loader.exec_module(bridge)
helper = bridge.load_helper()

CASES = bridge.case_paths()
EXAMPLE = "skills/mlview/references/workflow-example.json"
# The generated test documents (contracts/conformance/documents/README.md), listed by name.
TEST_WORKSPACE = "contracts/conformance/documents/workspace"
TEST_DOCUMENTS = (
    "d01-minimal", "d02-notebook", "d03-two-files", "d04-loop",
    "d05-groups", "d06-refinement", "d07-multi-file", "d08-dense",
)

# The cases this test requires by name.
REQUIRED_CASES = {
    "shape-001-node-parent-null", "shape-002-verification-null", "shape-003-inspected-directory-unverified",
    "encoding-001-lone-surrogate-title", "evidence-001-bom-line1-quote-both-forms", "evidence-002-owned-evidence",
    "fingerprint-001-latin1-inspected", "fingerprint-002-binary-pdf-inspected", "fingerprint-003-oversize-inspected",
    "fingerprint-004-owned-inspected-skill-dir", "fingerprint-005-owned-inspected-mlview-dir",
    "fingerprint-006-owned-inspected-draft-suffix", "fingerprint-007-owned-inspected-artifact-suffix",
    "fingerprint-008-owned-key-ignored", "fingerprint-009-out-of-scope-key-ignored", "fingerprint-010-stale-tracked-key",
    "path-001-drive-qualified-evidence", "path-002-entrypoint-nul",
    "freshness-001-crlf-source-raw-hash", "freshness-002-bom-source-fresh",
    "freshness-003-latin1-inspected-with-key-fresh", "freshness-004-owned-key-changed-not-stale",
    "freshness-005-missing-tracked-file-with-key", "freshness-006-missing-inspected-without-key-verified",
    # NaN/Infinity and duplicate keys in cited notebooks; the publishedAt profile.
    "notebook-009-nan-in-notebook", "notebook-010-duplicate-key-in-notebook", "shape-016-published-at-lowercase-z",
    "shape-017-published-at-leap-second", "shape-018-published-at-nine-digit-fraction",
    # Quote mismatches of the kinds the helper explains (a trailing line break, a range one line
    # short, a difference far into the quote), also when the same document has another error,
    # and one case per non-blocking hygiene warning.
    "evidence-007-quote-trailing-newline", "evidence-008-quote-end-line-off-by-one",
    "evidence-009-long-multiline-difference-past-200-characters", "notebook-011-stray-cell-quote-still-checked",
    "shape-019-duplicate-member-with-quote-mismatch-raw", "evidence-010-wide-evidence-warning",
    "evidence-011-sixty-line-evidence-no-warning", "evidence-012-unreferenced-evidence-warning",
    "shape-020-isolated-node-warning", "shape-021-self-edge-warning", "shape-022-self-edge-with-loop-kind-no-warning",
    "shape-023-evidence-overlap-warning", "path-007-duplicate-inspected-warning",
}
# Every helper warning code has at least one conformance case that expects it.
WARNING_CODES = {"excluded_inspected", "not_fingerprinted", "unreferenced_evidence", "isolated_node", "self_edge",
                 "wide_evidence", "evidence_overlap", "duplicate_inspected"}


def load(path: Path) -> dict:
    return bridge.load_case(path)


def sample_diagrams() -> list[str]:
    """Every sample diagram `samples/*.mlview.json`, as repository-relative paths."""
    return sorted(path.relative_to(ROOT).as_posix() for path in (ROOT / "samples").glob("*.mlview.json"))


def listed_documents() -> list[str]:
    """The sample diagrams and the eight test documents, as repository-relative paths."""
    return sample_diagrams() + [f"{TEST_WORKSPACE}/{name}.mlview.json" for name in TEST_DOCUMENTS]


class CorpusFormatTests(unittest.TestCase):
    def test_corpus_is_well_formed_and_complete(self):
        self.assertTrue(CASES, "contracts/conformance/cases is empty")
        numbers: dict[tuple[str, str], str] = {}
        for path in CASES:
            case = load(path)
            with self.subTest(case=path.name):
                self.assertEqual([], bridge.case_problems(path, case))
                area, number = case["id"].split("-")[:2]
                self.assertNotIn((area, number), numbers, f"{area}-{number} is also used by {numbers.get((area, number))}")
                numbers[(area, number)] = case["id"]
        self.assertLessEqual(REQUIRED_CASES, {path.stem for path in CASES})
        expected_warnings = {code for path in CASES for code in load(path)["expect"]["helper"]["warnings"]}
        self.assertEqual(WARNING_CODES, expected_warnings)

    def test_a_key_outside_the_case_format_is_reported(self):
        path = next(path for path in CASES if load(path)["divergence"] is not None)
        case = load(path)
        self.assertEqual([], bridge.case_problems(path, case))
        self.assertEqual(["unknown keys ['extra']"], bridge.case_problems(path, {**case, "extra": 1}))
        divergence = {**case["divergence"], "extra": 1}
        self.assertEqual(["divergence must be null or {layers, note, status}"],
                         bridge.case_problems(path, {**case, "divergence": divergence}))

    def test_accepted_divergences_belong_to_a_documented_class(self):
        readme = (ROOT / "contracts" / "conformance" / "README.md").read_text(encoding="utf-8")
        for path in CASES:
            divergence = load(path)["divergence"]
            if divergence is not None:
                with self.subTest(case=path.stem):
                    match = re.match(r"Accepted class ([12]):", divergence["note"])
                    self.assertIsNotNone(match, "an accepted divergence note starts with its README class")
                    self.assertIn(f"### Class {match.group(1)}:", readme)


class SchemaLayerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = bridge.strict_validator()
        if cls.validator is None:
            raise unittest.SkipTest("jsonschema is not installed (python -m pip install -r requirements-dev.txt)")

    def test_schema_patterns_are_anchored_so_full_match_is_the_ecma_result(self):
        schema = json.loads(bridge.SCHEMA.read_text(encoding="utf-8"))
        patterns = bridge.schema_patterns(schema)
        self.assertTrue(patterns)
        for pattern in patterns:
            self.assertTrue(pattern.startswith("^") and pattern.endswith("$"), pattern)

    def test_strict_layer_rejects_trailing_newline_ids_and_non_date_times(self):
        # Python's re.search lets `$` match before a final "\n", and 2020-12 treats
        # `format` as an annotation unless a checker asserts it; plain jsonschema accepts both.
        example = json.loads((ROOT / EXAMPLE).read_text(encoding="utf-8"))
        self.assertTrue(self.validator.is_valid(example))
        doc = json.loads(json.dumps(example))
        doc["revision"]["id"] = "r1\n"
        self.assertFalse(self.validator.is_valid(doc))
        doc = json.loads(json.dumps(example))
        doc["verification"] = {"files": {}, "publishedAt": "yesterday"}
        self.assertFalse(self.validator.is_valid(doc))
        doc["verification"]["publishedAt"] = "2026-09-25T00:00:00Z"
        self.assertTrue(self.validator.is_valid(doc))

    def test_date_time_check_mirrors_the_helper(self):
        accepted = ("2026-09-25T00:00:00Z", "2026-09-25T23:59:59.123456+05:30", "2024-02-29T00:00:00-00:00",
                    "2026-09-25T00:00:00.5Z", "2026-09-25T00:00:00.12Z", "2026-09-25T00:00:00.1234Z", "2026-09-25T00:00:00.1234567Z")
        rejected = ("yesterday", "2026-09-25", "2026-09-25T00:00:00", "2026-02-30T00:00:00Z", "0000-01-01T00:00:00Z",
                    "2026-09-25T24:00:00Z", "2026-09-25T00:00:60Z", "2026-09-25T00:00:00+24:00", "2026-09-25t00:00:00z",
                    "2026-09-25T00:00:00Z\n", "２026-09-25T00:00:00Z")
        example = json.loads((ROOT / EXAMPLE).read_text(encoding="utf-8"))
        for value in accepted + rejected:
            with self.subTest(value=value):
                doc = json.loads(json.dumps(example))
                doc["verification"] = {"files": {}, "publishedAt": value}
                with tempfile.TemporaryDirectory() as temp:
                    helper_accepts = "format" not in {error["code"] for error in helper.validate(doc, Path(temp))[0]}
                self.assertEqual(value in accepted, bridge.rfc3339_date_time(value))
                self.assertEqual(value in accepted, helper_accepts, "the helper agrees with the schema layer")

    def test_case_schema_expectations(self):
        for path in CASES:
            case = load(path)
            if case["expect"]["schema"] == "skip":
                continue
            with self.subTest(case=case["id"]):
                self.assertEqual(case["expect"]["schema"], bridge.schema_result(case, self.validator))


class HelperLayerTests(unittest.TestCase):
    def test_case_helper_expectations(self):
        for path in CASES:
            case = load(path)
            expected = case["expect"]["helper"]
            with self.subTest(case=case["id"]), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                bridge.materialise(case, root)
                actual = bridge.helper_result(case, root, helper)
                self.assertEqual(expected["ok"], actual["ok"], actual)
                self.assertEqual(sorted(expected["codes"]), actual["codes"])
                self.assertEqual(sorted(expected["warnings"]), actual["warnings"])
                self.assertEqual(sorted(expected["stale"]), actual["stale"])
                if expected["fingerprints"] is not None:
                    self.assertEqual(bridge.substitute(expected["fingerprints"]), actual["fingerprints"])

    def test_helper_round_trip(self):
        """Publish every eligible case with the real CLI, then validate the published artifact with the helper."""
        ran = 0
        for path in CASES:
            case = load(path)
            expected = case["expect"]["helper"]
            if not expected["ok"] or case["divergence"] is not None or "raw" in case or "verification" in case["document"]:
                continue
            ran += 1
            with self.subTest(case=case["id"]), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                bridge.materialise(case, root)
                (root / case["artifact"]).unlink()  # publish creates the first revision
                draft = root / ".mlview" / "llm" / "run" / "draft.json"
                draft.parent.mkdir(parents=True)
                draft.write_text(json.dumps(bridge.substitute(case["document"])), encoding="utf-8")
                published = subprocess.run(
                    [sys.executable, str(bridge.HELPER), "publish", ".mlview/llm/run/draft.json",
                     "--workspace", str(root), "--output", case["artifact"]],
                    text=True, capture_output=True, cwd=root,
                )
                self.assertEqual("", published.stderr)
                self.assertEqual(0, published.returncode, published.stdout)
                result = json.loads(published.stdout)
                self.assertEqual(sorted(expected["warnings"]), sorted({w["code"] for w in result.get("warnings", [])}))
                output = json.loads((root / case["artifact"]).read_bytes().decode("utf-8"))
                if expected["fingerprints"] is not None:
                    self.assertEqual(bridge.substitute(expected["fingerprints"]), output["verification"]["files"])
                checked = subprocess.run(
                    [sys.executable, str(bridge.HELPER), "validate", case["artifact"], "--workspace", str(root)],
                    text=True, capture_output=True, cwd=root,
                )
                self.assertEqual("", checked.stderr)
                self.assertEqual(0, checked.returncode, checked.stdout)
                self.assertEqual(output["verification"]["files"], json.loads(checked.stdout)["files"])
        self.assertGreaterEqual(ran, 10)


class ParityExpectationTests(unittest.TestCase):
    def test_committed_expectations_satisfy_the_parity_invariant(self):
        """P1 and P3 on the committed expectations (the extension runner re-checks P1-P3 on actual results)."""
        checked = 0
        for path in CASES:
            case = load(path)
            if case["divergence"] is not None:
                continue
            expect = case["expect"]
            with self.subTest(case=case["id"]):
                if not expect["extension"]["stale"]:
                    checked += 1
                    self.assertEqual(expect["helper"]["ok"], expect["extension"]["ok"], "P1")
                if expect["helper"]["ok"] and expect["extension"]["ok"] and expect["schema"] != "skip":
                    self.assertEqual("valid", expect["schema"], "P3")
        self.assertGreater(checked, 0)


class WholeDocumentTests(unittest.TestCase):
    def test_workspace_holds_exactly_the_listed_test_documents(self):
        found = sorted(path.name for path in (ROOT / TEST_WORKSPACE).glob("*.mlview.json"))
        self.assertEqual([f"{name}.mlview.json" for name in TEST_DOCUMENTS], found)

    def test_each_sample_diagram_test_document_and_the_example_are_schema_valid_and_structurally_valid(self):
        validator = bridge.strict_validator()
        if validator is None:
            self.skipTest("jsonschema is not installed (python -m pip install -r requirements-dev.txt)")
        self.assertGreaterEqual(len(sample_diagrams()), 1)
        paths = listed_documents()
        for rel in paths + [EXAMPLE]:
            with self.subTest(document=rel):
                doc = helper._parse((ROOT / rel).read_bytes())
                self.assertEqual([], [f"{e.json_path}: {e.message}" for e in validator.iter_errors(doc)])
                problems = helper.Problems()
                helper._basic_shape(doc, problems)
                helper._references(doc, problems)
                self.assertEqual([], problems.items)

    def test_each_test_document_validates_fully_and_fresh_against_its_workspace(self):
        for name in TEST_DOCUMENTS:
            with self.subTest(document=name):
                doc = helper._parse((ROOT / TEST_WORKSPACE / f"{name}.mlview.json").read_bytes())
                warnings: list = []
                errors, hashes = helper.validate(doc, ROOT / TEST_WORKSPACE, warnings=warnings)
                self.assertEqual([], errors)
                self.assertEqual([], warnings)
                self.assertEqual(doc["verification"]["files"], hashes)


if __name__ == "__main__":
    unittest.main()
