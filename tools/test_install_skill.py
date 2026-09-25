import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).with_name("install_skill.py")
SPEC = importlib.util.spec_from_file_location("install_skill", SCRIPT)
installer = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(installer)


def write_tree(root: Path, files: dict) -> None:
    for relative, contents in files.items():
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_bytes(contents)


def installed_files(target: Path) -> dict:
    return {path.relative_to(target).as_posix(): path.read_bytes() for path in target.rglob("*") if path.is_file()}


class InstallManifestTests(unittest.TestCase):
    """SKILL-15: the install manifest, local-edit refusal, --force and retired files."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.source = base / "source-skill"
        self.canonical = installer.canonical_files(installer.SOURCE)
        write_tree(self.source, self.canonical)
        os.chmod(self.source / "scripts/artifact.py", 0o755)
        patcher = mock.patch.object(installer, "SOURCE", self.source)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.workspace = base / "workspace"
        self.workspace.mkdir()
        self.target = self.workspace / ".agents/skills/mlview"

    def tearDown(self): self.temp.cleanup()

    def manifest(self) -> dict:
        return json.loads((self.target / ".mlview-install.json").read_text(encoding="utf-8"))

    def test_install_records_every_installed_file_and_its_bytes(self):
        installer.install(self.workspace)
        expected = {rel: hashlib.sha256(data).hexdigest() for rel, data in self.canonical.items()}
        self.assertEqual({"format": 1, "files": expected}, self.manifest())
        raw = (self.target / ".mlview-install.json").read_text(encoding="utf-8")
        self.assertEqual(json.dumps(self.manifest(), indent=2, sort_keys=True) + "\n", raw)
        self.assertEqual({**self.canonical, ".mlview-install.json": raw.encode("utf-8")}, installed_files(self.target))
        if os.name != "nt":
            self.assertEqual(0o755, (self.target / "scripts/artifact.py").stat().st_mode & 0o777)
        report, ok = installer.doctor(self.workspace)
        self.assertTrue(ok, report)
        self.assertEqual([], report["locations"][0]["unexpected"], "the manifest is not a skill file")
        self.assertEqual(report["canonicalIdentity"], report["locations"][0]["identity"])
        installer.install(self.workspace)  # an unchanged reinstall needs no --force
        self.assertEqual(expected, self.manifest()["files"])

    def test_local_edits_are_refused_without_force_and_replaced_with_it(self):
        installer.install(self.workspace)
        (self.target / "SKILL.md").write_text("my notes", encoding="utf-8")
        (self.target / "references/training-state.md").write_text("mine", encoding="utf-8")
        with self.assertRaises(ValueError) as refused:
            installer.install(self.workspace)
        self.assertEqual("destination has local edits: SKILL.md, references/training-state.md. "
                         "Back them up and rerun with --force to replace them.", str(refused.exception))
        self.assertEqual(b"my notes", (self.target / "SKILL.md").read_bytes(), "a refused install writes nothing")
        installer.install(self.workspace, force=True)
        self.assertEqual(self.canonical["SKILL.md"], (self.target / "SKILL.md").read_bytes())
        self.assertEqual(self.canonical["references/training-state.md"], (self.target / "references/training-state.md").read_bytes())

    def test_upgrade_replaces_unmodified_files_and_deletes_retired_ones(self):
        installer.install(self.workspace)
        # The next release changes SKILL.md, retires one reference and adds another.
        (self.source / "SKILL.md").write_bytes(b"new skill text\n")
        (self.source / "references/training-state.md").unlink()
        (self.source / "references/new-guide.md").write_bytes(b"new guide\n")
        installer.install(self.workspace)
        self.assertEqual(b"new skill text\n", (self.target / "SKILL.md").read_bytes())
        self.assertFalse((self.target / "references/training-state.md").exists())
        self.assertEqual(b"new guide\n", (self.target / "references/new-guide.md").read_bytes())
        self.assertNotIn("references/training-state.md", self.manifest()["files"])
        self.assertEqual(hashlib.sha256(b"new guide\n").hexdigest(), self.manifest()["files"]["references/new-guide.md"])

    def test_an_edited_retired_file_needs_force_and_a_retired_directory_is_pruned(self):
        (self.source / "extras").mkdir()
        (self.source / "extras/old.md").write_bytes(b"old\n")
        installer.install(self.workspace)
        (self.source / "extras/old.md").unlink()
        (self.target / "extras/old.md").write_bytes(b"edited\n")
        with self.assertRaisesRegex(ValueError, r"^destination has local edits: extras/old\.md\. "):
            installer.install(self.workspace)
        self.assertEqual(b"edited\n", (self.target / "extras/old.md").read_bytes())
        installer.install(self.workspace, force=True)
        self.assertFalse((self.target / "extras").exists())

    def test_without_a_manifest_any_differing_skill_file_needs_force(self):
        installer.install(self.workspace)
        (self.target / ".mlview-install.json").unlink()  # an install made before 0.3.0
        installer.install(self.workspace)  # identical files are not edits
        (self.target / "SKILL.md").write_text("pre-0.3.0 local edit", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "^destination has local edits: SKILL.md. "):
            installer.install(self.workspace)
        installer.install(self.workspace, force=True)
        self.assertEqual(self.canonical["SKILL.md"], (self.target / "SKILL.md").read_bytes())

    def test_unusable_manifests_are_ignored_as_a_whole(self):
        installer.install(self.workspace)
        (self.target / "SKILL.md").write_text("edited", encoding="utf-8")
        edited = hashlib.sha256(b"edited").hexdigest()
        for manifest in ('{"format": 1, "files": {"SKILL.md": "%s", "../outside.md": "%s"}}' % (edited, edited),
                         '{"format": 2, "files": {"SKILL.md": "%s"}}' % edited,
                         '{"format": 1, "files": {"SKILL.md": "not-a-digest"}}', "not json", "[]"):
            with self.subTest(manifest=manifest):
                (self.target / ".mlview-install.json").write_text(manifest, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "^destination has local edits: SKILL.md. "):
                    installer.install(self.workspace)
        # A usable manifest that recorded these bytes lets the upgrade replace them.
        (self.target / ".mlview-install.json").write_text('{"format": 1, "files": {"SKILL.md": "%s"}}' % edited, encoding="utf-8")
        installer.install(self.workspace)
        self.assertEqual(self.canonical["SKILL.md"], (self.target / "SKILL.md").read_bytes())

    def test_files_mlview_never_installed_are_refused_even_with_force_and_never_deleted(self):
        installer.install(self.workspace)
        (self.target / "references/personal.md").write_text("keep", encoding="utf-8")
        for force in (False, True):
            with self.subTest(force=force), self.assertRaisesRegex(ValueError, "not owned by the MLView skill: references/personal.md"):
                installer.install(self.workspace, force=force)
        self.assertEqual("keep", (self.target / "references/personal.md").read_text(encoding="utf-8"))

    def test_command_line_force_flag(self):
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        first = subprocess.run([sys.executable, str(SCRIPT), str(self.workspace)], capture_output=True, text=True, env=env)
        self.assertEqual(0, first.returncode, first.stderr)
        target = self.workspace / ".agents/skills/mlview"
        (target / "SKILL.md").write_text("edited", encoding="utf-8")
        refused = subprocess.run([sys.executable, str(SCRIPT), str(self.workspace)], capture_output=True, text=True, env=env)
        self.assertEqual(2, refused.returncode)
        self.assertIn("destination has local edits: SKILL.md. Back them up and rerun with --force to replace them.", refused.stderr)
        forced = subprocess.run([sys.executable, str(SCRIPT), str(self.workspace), "--force"], capture_output=True, text=True, env=env)
        self.assertEqual(0, forced.returncode, forced.stderr)
        self.assertEqual(".agents/skills/mlview\n", forced.stdout)


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
            for required in installer.canonical_files(installer.SOURCE):
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

    def test_doctor_reports_a_symlinked_location_as_present_with_a_working_remediation(self):
        # SKILL-15: a linked location used to read as absent, and its advice ("install") was refused.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            installer.install(root, "real/mlview")
            (root / ".agents/skills").mkdir(parents=True)
            try:
                (root / ".agents/skills/mlview").symlink_to(root / "real/mlview", target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            report, ok = installer.doctor(root)
            self.assertFalse(ok)
            location = report["locations"][0]
            self.assertEqual((True, True, True, None), (location["present"], location["symlinked"], location["unsafeSymlinks"], location["identity"]))
            self.assertEqual([".agents/skills/mlview is a symbolic link; MLView installs only real directories. "
                              "Remove the link (not its target), then run install_skill.py."], report["remediation"])
            self.assertFalse(report["locations"][1]["symlinked"])
            with self.assertRaisesRegex(ValueError, "must not be a symlink"):
                installer.install(root)
            (root / ".agents/skills/mlview").unlink()  # the remediation, then install works
            installer.install(root)
            self.assertTrue(installer.doctor(root)[1])
            self.assertTrue((root / "real/mlview/SKILL.md").is_file(), "removing the link keeps its target")

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
