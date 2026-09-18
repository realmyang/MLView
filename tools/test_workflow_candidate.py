import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("workflow_candidate.py")
SPEC = importlib.util.spec_from_file_location("workflow_candidate", SCRIPT)
candidate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(candidate)


class CandidateTests(unittest.TestCase):
    def fixture(self, root):
        for name in (*candidate.COMPONENTS, "skills/mlview/SKILL.md", "skills/mlview/LICENSE",
                     "skills/mlview/references/new-guide.md"):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(name, encoding="utf-8")

    def test_snapshot_covers_all_portable_files_and_never_claims_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            self.fixture(root)
            record = candidate.snapshot(root)
            self.assertFalse(record["pilotApproved"])
            self.assertEqual(3, len(record["skill"]["files"]))
            self.assertEqual([], candidate.check(record, root))
            (root / "skills/mlview/references/extra.md").write_text("new", encoding="utf-8")
            self.assertEqual(["portable skill payload changed"], candidate.check(record, root))

    def test_drift_in_viewer_is_detected_independently_of_skill(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            self.fixture(root)
            record = candidate.snapshot(root)
            (root / "webview/dist/mlview.js").write_text("changed", encoding="utf-8")
            self.assertEqual(["changed component: webview/dist/mlview.js"], candidate.check(record, root))

    def test_check_rejects_escape_and_omitted_components(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            self.fixture(root)
            record = candidate.snapshot(root)
            record["components"][0]["path"] = "../outside"
            with self.assertRaises(ValueError):
                candidate.check(record, root)
            record = candidate.snapshot(root)
            record["components"].pop()
            with self.assertRaisesRegex(ValueError, "requires component identities"):
                candidate.check(record, root)

    def test_check_rejects_forged_approval_gate_and_record_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            self.fixture(root)
            for field, value in (("pilotApproved", True), ("remainingGates", []),
                                 ("note", "Human approved")):
                record = candidate.snapshot(root)
                record[field] = value
                with self.subTest(field=field), self.assertRaises(ValueError):
                    candidate.check(record, root)
            record = candidate.snapshot(root)
            record["approvedBy"] = "someone"
            with self.assertRaisesRegex(ValueError, "unexpected or missing"):
                candidate.check(record, root)

    def test_source_metadata_is_typed_but_informational(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            self.fixture(root)
            record = candidate.snapshot(root)
            record["source"] = {"commit": "a" * 40, "workingTreeChanged": None}
            self.assertEqual([], candidate.check(record, root))
            for source in ({"commit": "not-a-commit", "workingTreeChanged": False},
                           {"commit": None, "workingTreeChanged": 0},
                           {"commit": None, "workingTreeChanged": None, "extra": True}):
                record = candidate.snapshot(root)
                record["source"] = source
                with self.subTest(source=source), self.assertRaisesRegex(ValueError, "source metadata"):
                    candidate.check(record, root)

    def test_components_are_exact_and_identities_have_closed_typed_shape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            self.fixture(root)
            extra = root / "extra.txt"
            extra.write_text("extra", encoding="utf-8")
            record = candidate.snapshot(root)
            record["components"].append(candidate.file_identity(extra, root))
            with self.assertRaises(ValueError):
                candidate.check(record, root)
            for field, value in (("sha256", "bad"), ("bytes", True)):
                record = candidate.snapshot(root)
                record["components"][0][field] = value
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, "identity"):
                    candidate.check(record, root)
            record = candidate.snapshot(root)
            record["components"][0]["extra"] = "field"
            with self.assertRaisesRegex(ValueError, "identity"):
                candidate.check(record, root)

    def test_vsix_is_explicit_optional_and_checked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            self.fixture(root)
            package = root / "dist/mlview.vsix"
            package.parent.mkdir()
            package.write_bytes(b"vsix")
            record = candidate.snapshot(root, Path("dist/mlview.vsix"))
            self.assertEqual("dist/mlview.vsix", record["vsix"]["path"])
            self.assertEqual(len(candidate.COMPONENTS), len(record["components"]))
            self.assertEqual([], candidate.check(record, root))
            package.write_bytes(b"changed")
            self.assertEqual(["changed component: dist/mlview.vsix"], candidate.check(record, root))
            wrong = root / "dist/not-vsix.zip"
            wrong.write_bytes(b"zip")
            with self.assertRaisesRegex(ValueError, r"\.vsix"):
                candidate.snapshot(root, Path("dist/not-vsix.zip"))

    def test_rejects_internal_and_external_symlink_paths_without_absolute_diagnostics(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside:
            root = Path(temp).resolve()
            self.fixture(root)
            real = root / "real-dist"
            real.mkdir()
            (real / "mlview.js").write_text("alias", encoding="utf-8")
            dist = root / "webview/dist"
            for child in dist.iterdir():
                child.unlink()
            dist.rmdir()
            try:
                dist.symlink_to(real, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            with self.assertRaisesRegex(ValueError, "regular non-symlink"):
                candidate.file_identity(dist / "mlview.js", root)
            outside_file = Path(outside) / "private.vsix"
            outside_file.write_bytes(b"private")
            linked = root / "linked.vsix"
            linked.symlink_to(outside_file)
            with self.assertRaisesRegex(ValueError, "regular non-symlink") as linked_error:
                candidate.snapshot(root, Path("linked.vsix"))
            self.assertNotIn(str(outside_file), str(linked_error.exception))
            with self.assertRaises(ValueError) as caught:
                candidate.snapshot(root, outside_file)
            message = str(caught.exception)
            self.assertNotIn(str(root), message)
            self.assertNotIn(str(outside_file), message)

    def test_snapshot_uses_null_when_git_metadata_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            self.fixture(root)
            record = candidate.snapshot(root)
            self.assertIsNone(record["source"]["commit"])
            self.assertIsNone(record["source"]["workingTreeChanged"])
