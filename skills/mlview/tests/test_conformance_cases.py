"""Staged helper-side conformance cases (Campaign 1, stream A).

Every case in conformance/cases is self-contained: its files are materialised in
a fresh temporary workspace, `$sha256` placeholders are replaced by digests, and
the helper's result is compared with `expect.helper` (plus `expect.schema` when
jsonschema is installed). Cases whose helper result is ok, that carry no
`verification` and no divergence are also published and re-validated (the
helper half of the round trip). Stream E moves the cases to
contracts/conformance/cases and replaces this runner.
"""
import base64
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
HELPER = HERE.parent / "scripts" / "artifact.py"
CASES = sorted((HERE / "conformance" / "cases").glob("*.json"))
AREAS = {"shape", "path", "evidence", "notebook", "fingerprint", "freshness", "encoding", "revision", "size"}
CASE_ID = re.compile(r"^([a-z]+)-(\d{3})-([a-z0-9]+(?:-[a-z0-9]+)*)$")

SPEC = importlib.util.spec_from_file_location("mlview_artifact_conformance", HELPER)
artifact = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(artifact)


def load_case(path):
    return json.loads(path.read_text(encoding="utf-8"))


def content(spec):
    if set(spec) == {"text"}:
        return spec["text"].encode("utf-8")
    if set(spec) == {"base64"}:
        return base64.b64decode(spec["base64"], validate=True)
    if set(spec) == {"generate"}:
        fill, size = spec["generate"]["fill"], spec["generate"]["bytes"]
        if len(fill) != 1 or not fill.isascii() or not isinstance(size, int) or size < 0:
            raise ValueError("generate needs one ASCII fill character and a byte count")
        return fill.encode("ascii") * size
    raise ValueError(f"unknown file content specification: {sorted(spec)}")


def substitute(value):
    if isinstance(value, dict):
        if set(value) == {"$sha256"}:
            return hashlib.sha256(content(value["$sha256"])).hexdigest()
        return {key: substitute(child) for key, child in value.items()}
    if isinstance(value, list):
        return [substitute(child) for child in value]
    return value


def materialise(case, root):
    for rel, spec in case["files"].items():
        target = root.joinpath(*PurePosixPath(rel).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content(spec))


def helper_result(case, root):
    """Return {ok, codes, warnings, fingerprints, stale} as the case format defines them."""
    if "raw" in case:
        try:
            doc = artifact._parse(case["raw"].encode("utf-8"))
        except (UnicodeError, ValueError, RecursionError):
            return {"ok": False, "codes": ["invalid_json"], "warnings": [], "fingerprints": {}, "stale": []}
    else:
        doc = substitute(case["document"])
    warnings = []
    errors, hashes = artifact.validate(doc, root, warnings=warnings)
    return {
        "ok": not errors,
        "codes": sorted({error["code"] for error in errors}),
        "warnings": sorted({warning["code"] for warning in warnings}),
        "fingerprints": hashes,
        "stale": sorted({error["file"] for error in errors if error["code"] == "stale_source"}),
    }


class ConformanceCaseTests(unittest.TestCase):
    def test_cases_exist(self):
        self.assertTrue(CASES)

    def test_case_files_are_well_formed(self):
        for path in CASES:
            with self.subTest(case=path.name):
                self.assertLessEqual(path.stat().st_size, 100_000)
                case = load_case(path)
                self.assertEqual(path.stem, case["id"])
                match = CASE_ID.fullmatch(case["id"])
                self.assertIsNotNone(match)
                self.assertIn(match.group(1), AREAS)
                self.assertTrue(case["findings"] and all(isinstance(item, str) for item in case["findings"]))
                self.assertIsInstance(case["description"], str)
                self.assertEqual(1, ("document" in case) + ("raw" in case))
                if "document" in case: self.assertIsInstance(case["document"], dict)
                else: self.assertIsInstance(case["raw"], str)
                self.assertTrue(case["artifact"].endswith(".mlview.json"))
                folded = set()
                for rel in case["files"]:
                    self.assertNotIn("\\", rel)
                    self.assertFalse(rel.startswith("/"))
                    self.assertFalse(any(part in {"", ".", ".."} for part in rel.split("/")))
                    self.assertNotIn(rel.lower(), folded, "case-only siblings are not portable")
                    folded.add(rel.lower())
                    content(case["files"][rel])
                expect = case["expect"]
                self.assertIn(expect["schema"], {"valid", "invalid", "skip"})
                for layer in ("helper", "extension"):
                    self.assertTrue(expect[layer] == "unverified" or isinstance(expect[layer], dict))
                divergence = case["divergence"]
                if divergence is not None:
                    self.assertIn(divergence["status"], {"open", "accepted"})
                    self.assertTrue(divergence["layers"] and divergence["findings"] and divergence["note"])

    def test_helper_expectations(self):
        for path in CASES:
            case = load_case(path)
            expected = case["expect"]["helper"]
            if expected == "unverified":
                continue
            with self.subTest(case=case["id"]), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                materialise(case, root)
                actual = helper_result(case, root)
                self.assertEqual(expected["ok"], actual["ok"], actual)
                self.assertEqual(sorted(expected["codes"]), actual["codes"])
                self.assertEqual(sorted(expected["warnings"]), actual["warnings"])
                self.assertEqual(sorted(expected["stale"]), actual["stale"])
                if expected["fingerprints"] is not None:
                    self.assertEqual(substitute(expected["fingerprints"]), actual["fingerprints"])

    def test_schema_expectations(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema is not installed")
        validator = Draft202012Validator(json.loads((ROOT / "contracts" / "workflow.schema.json").read_text(encoding="utf-8")))
        for path in CASES:
            case = load_case(path)
            expected = case["expect"]["schema"]
            if expected == "skip":
                continue
            with self.subTest(case=case["id"]):
                if "raw" in case:
                    try: doc = json.loads(case["raw"])
                    except ValueError: doc = None
                else:
                    doc = substitute(case["document"])
                self.assertEqual(expected, "valid" if doc is not None and validator.is_valid(doc) else "invalid")

    def test_helper_round_trip(self):
        ran = 0
        for path in CASES:
            case = load_case(path)
            expected = case["expect"]["helper"]
            if expected == "unverified" or not expected["ok"] or case["divergence"] is not None or "raw" in case or "verification" in case["document"]:
                continue
            ran += 1
            with self.subTest(case=case["id"]), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                materialise(case, root)
                draft = root / ".mlview" / "llm" / "run" / "draft.json"
                draft.parent.mkdir(parents=True)
                draft.write_text(json.dumps(substitute(case["document"])), encoding="utf-8")
                published = subprocess.run(
                    [sys.executable, str(HELPER), "publish", ".mlview/llm/run/draft.json", "--workspace", str(root), "--output", case["artifact"]],
                    text=True, capture_output=True, cwd=root,
                )
                self.assertEqual("", published.stderr)
                self.assertEqual(0, published.returncode, published.stdout)
                self.assertEqual(sorted(expected["warnings"]), sorted({w["code"] for w in json.loads(published.stdout).get("warnings", [])}))
                output = json.loads((root / case["artifact"]).read_text(encoding="utf-8"))
                if expected["fingerprints"] is not None:
                    self.assertEqual(substitute(expected["fingerprints"]), output["verification"]["files"])
                checked = subprocess.run(
                    [sys.executable, str(HELPER), "validate", case["artifact"], "--workspace", str(root)],
                    text=True, capture_output=True, cwd=root,
                )
                self.assertEqual("", checked.stderr)
                self.assertEqual(0, checked.returncode, checked.stdout)
                self.assertEqual(output["verification"]["files"], json.loads(checked.stdout)["files"])
        self.assertGreater(ran, 0)


if __name__ == "__main__":
    unittest.main()
