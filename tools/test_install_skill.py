import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("install_skill.py")
SPEC = importlib.util.spec_from_file_location("install_skill", SCRIPT)
installer = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def test_installs_portable_tree_only_at_agents_default(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = installer.install(root)
            self.assertEqual(Path(".agents/skills/mlview"), target)
            self.assertTrue((root / target / "SKILL.md").is_file())
            self.assertEqual((SCRIPT.parents[1] / "LICENSE").read_bytes(), (root / target / "LICENSE").read_bytes())
            self.assertTrue((root / target / "scripts/artifact.py").is_file())
            self.assertFalse((root / ".claude").exists())

    def test_rejects_destination_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError): installer.install(Path(temp), "../outside")

    def test_rejects_nonportable_destination_syntax(self):
        with tempfile.TemporaryDirectory() as temp:
            for destination in (".", ".agents//skills/mlview", r".agents\skills\mlview"):
                with self.subTest(destination=destination), self.assertRaises(ValueError):
                    installer.install(Path(temp), destination)

    def test_rejects_symlinked_parent_escape(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside:
            root = Path(temp)
            try:
                (root / ".agents").symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            with self.assertRaises(ValueError): installer.install(root)
            self.assertEqual([], list(Path(outside).iterdir()), "validation must precede outside directory creation")

    def test_rejects_unowned_destination_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); target = root / ".agents/skills/mlview"
            target.mkdir(parents=True); (target / "personal.txt").write_text("keep")
            with self.assertRaises(ValueError): installer.install(root)

    def test_editor_and_os_files_in_the_destination_are_left_alone(self):
        # EVAL-8: a Finder visit (.DS_Store) or bytecode cache must not block a reinstall.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / installer.install(root)
            for junk in (".DS_Store", "._SKILL.md", "scripts/__pycache__/artifact.cpython-313.pyc", "SKILL.md~"):
                (target / junk).parent.mkdir(parents=True, exist_ok=True)
                (target / junk).write_bytes(b"junk")
            installer.install(root)
            self.assertEqual(b"junk", (target / ".DS_Store").read_bytes())
            self.assertEqual(b"junk", (target / "scripts/__pycache__/artifact.cpython-313.pyc").read_bytes())
            report, ok = installer.doctor(root)
            self.assertTrue(ok, report)
            self.assertEqual([], report["locations"][0]["unexpected"])

    def test_rejects_copying_source_onto_itself(self):
        source = SCRIPT.resolve().parents[1]
        with self.assertRaises(ValueError): installer.install(source, "skills/mlview")

    def test_doctor_checks_required_files_and_reports_its_limits(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            installer.install(root)
            report, ok = installer.doctor(root)
            self.assertTrue(ok)
            self.assertTrue(report["python"]["supported"])
            self.assertIn("native assistant skill discovery", report["limitations"][0])
            (root / ".agents/skills/mlview/references/workflow-example.json").unlink()
            report, ok = installer.doctor(root)
            self.assertFalse(ok)
            self.assertEqual(["references/workflow-example.json"], report["locations"][0]["missing"])

    def test_doctor_reports_layout_collision(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            installer.install(root)
            installer.install(root, ".claude/skills/mlview")
            report, ok = installer.doctor(root)
            self.assertFalse(ok)
            self.assertTrue(report["collision"])

    def test_doctor_rejects_symlinked_required_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            installer.install(root)
            required = root / ".agents/skills/mlview/references/workflow-example.json"
            contents = required.read_text(encoding="utf-8")
            required.unlink()
            outside = root / "example.json"
            outside.write_text(contents, encoding="utf-8")
            try:
                required.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            report, ok = installer.doctor(root)
            self.assertFalse(ok)
            self.assertTrue(report["locations"][0]["unsafeSymlinks"])
            self.assertEqual(["references/workflow-example.json"], report["locations"][0]["missing"])

    def test_doctor_rejects_symlinked_install_ancestor_without_scanning_it(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside:
            root = Path(temp)
            external = Path(outside) / "skills/mlview"
            external.mkdir(parents=True)
            for required in installer.REQUIRED_FILES:
                path = external / required
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("external", encoding="utf-8")
            try:
                (root / ".agents").symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            report, ok = installer.doctor(root)
            self.assertFalse(ok)
            location = report["locations"][0]
            self.assertTrue(location["present"])
            self.assertTrue(location["unsafeSymlinks"])
            self.assertEqual(sorted(file["path"] for file in report["canonicalIdentity"]["files"]), location["missing"])

    def test_doctor_detects_edits_extra_files_and_bundle_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            relative = installer.install(root)
            report, ok = installer.doctor(root)
            location = report["locations"][0]
            self.assertTrue(ok)
            self.assertEqual(report["canonicalIdentity"], location["identity"])
            (root / relative / "SKILL.md").write_text("local changes", encoding="utf-8")
            (root / relative / "unowned.txt").write_text("keep", encoding="utf-8")
            report, ok = installer.doctor(root)
            self.assertFalse(ok)
            location = report["locations"][0]
            self.assertEqual(["SKILL.md"], location["changed"])
            self.assertEqual(["unowned.txt"], location["unexpected"])
            self.assertFalse(location["matchesCanonical"])
            self.assertNotEqual(report["canonicalIdentity"]["sha256"], location["identity"]["sha256"])
            self.assertIn("preserve local edits", report["remediation"][0])
            self.assertEqual("keep", (root / relative / "unowned.txt").read_text(encoding="utf-8"))

    def test_doctor_reports_missing_install(self):
        with tempfile.TemporaryDirectory() as temp:
            report, ok = installer.doctor(Path(temp))
            self.assertFalse(ok)
            self.assertFalse(report["collision"])


if __name__ == "__main__": unittest.main()
