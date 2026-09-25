import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

SCRIPT = Path(__file__).with_name("package_skill.py")
SPEC = importlib.util.spec_from_file_location("package_skill", SCRIPT)
packager = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(packager)


class PackageSkillTests(unittest.TestCase):
    def test_bundle_identity_covers_paths_bytes_and_all_payload_files(self):
        payload = {"z.txt": b"two", "a.txt": b"one", "LICENSE": b"license"}
        identity = packager.bundle_identity(payload)
        expected = hashlib.sha256(b"LICENSE\0license\0a.txt\0one\0z.txt\0two\0").hexdigest()
        self.assertEqual(expected, identity["sha256"])
        self.assertEqual(identity, packager.bundle_identity(dict(reversed(list(payload.items())))))
        self.assertEqual(3, len(identity["files"]))
        self.assertNotEqual(identity["sha256"], packager.bundle_identity({**payload, "a.txt": b"ONE"})["sha256"])
        self.assertNotEqual(identity["sha256"], packager.bundle_identity({"renamed.txt": b"one", "z.txt": b"two"})["sha256"])

    def test_portable_filter_skips_tests_caches_and_editor_or_os_files(self):
        # EVAL-8: one rule for the packager, the plugin sync, the installer and the candidate.
        for relative in ("SKILL.md", "LICENSE", "references/WORKFLOW_CONTRACT.md", "scripts/artifact.py",
                         "references/workflow-example.json", "notes.v2.md"):
            with self.subTest(relative=relative):
                self.assertTrue(packager.portable(relative))
                self.assertTrue(packager.portable(Path(relative)))
        for relative in ("tests/test_artifact.py", "scripts/__pycache__/artifact.cpython-313.pyc", "scripts/artifact.pyc",
                         ".DS_Store", "references/.DS_Store", "._SKILL.md", "references/._training-state.md",
                         ".git/config", ".mlview-install.json", ".hidden/SKILL.md", "SKILL.md~", ".SKILL.md.swp",
                         "references/notes.swo", "Thumbs.db", "references/THUMBS.DB", "desktop.ini", "Desktop.ini",
                         "backup~/SKILL.md", "", "../SKILL.md"):
            with self.subTest(relative=relative):
                self.assertFalse(packager.portable(relative))
                if relative:
                    self.assertFalse(packager.portable(Path(relative)))

    def test_every_tracked_skill_file_outside_tests_is_portable(self):
        # A real dotfile or backup file committed to the skill would silently leave the bundle; fail instead.
        try:
            listed = subprocess.run(["git", "ls-files", "-z", "--", "skills/mlview"], cwd=SCRIPT.parents[1],
                                    capture_output=True, check=True).stdout.decode("utf-8").split("\0")
        except (OSError, subprocess.CalledProcessError) as exc:
            self.skipTest(f"git is unavailable here: {exc}")
        tracked = [path.removeprefix("skills/mlview/") for path in listed if path]
        if not tracked:
            self.skipTest("not a Git checkout")
        shipped = [path for path in tracked if not path.startswith("tests/")]
        self.assertTrue(shipped)
        self.assertEqual([], [path for path in shipped if not packager.portable(path)])
        self.assertLessEqual(set(shipped), set(packager.canonical_files()))

    def test_editor_and_os_files_leave_the_bundle_identity_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "skill"
            for relative, contents in packager.canonical_files().items():
                (source / relative).parent.mkdir(parents=True, exist_ok=True)
                (source / relative).write_bytes(contents)
            clean = packager.bundle_identity(packager.canonical_files(source))
            self.assertEqual(packager.bundle_identity(packager.canonical_files()), clean)
            for junk in (".DS_Store", "._SKILL.md", "references/.DS_Store", "references/._WORKFLOW_CONTRACT.md",
                         "scripts/__pycache__/artifact.cpython-313.pyc", "SKILL.md~", "references/.notes.md.swp",
                         "Thumbs.db", "desktop.ini", ".mlview-install.json", ".git/HEAD", "tests/test_extra.py"):
                (source / junk).parent.mkdir(parents=True, exist_ok=True)
                (source / junk).write_bytes(b"junk")
            self.assertEqual(clean, packager.bundle_identity(packager.canonical_files(source)))

    def test_canonical_skill_license_matches_repository_license(self):
        self.assertEqual(
            (SCRIPT.parents[1] / "LICENSE").read_bytes(),
            (SCRIPT.parents[1] / "skills/mlview/LICENSE").read_bytes(),
        )

    def test_canonical_payload_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "skill"
            source.mkdir()
            outside = Path(temp) / "secret"
            outside.write_text("do not package", encoding="utf-8")
            try:
                (source / "linked").symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            with self.assertRaisesRegex(ValueError, "must not contain symlinks"):
                packager.canonical_files(source)

    def test_archives_are_reproducible_and_exact_canonical_copies(self):
        expected = packager.canonical_files()
        prefixes = {"shared": ".agents/skills/mlview", "claude-code": ".claude/skills/mlview"}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for host, prefix in prefixes.items():
                first, second = root / f"{host}-1.zip", root / f"{host}-2.zip"
                packager.package(first, host)
                packager.package(second, host)
                self.assertEqual(hashlib.sha256(first.read_bytes()).digest(), hashlib.sha256(second.read_bytes()).digest())
                with ZipFile(first) as archive:
                    actual = {name.removeprefix(prefix + "/"): archive.read(name) for name in archive.namelist()}
                    self.assertEqual(expected, actual)
                    self.assertEqual((SCRIPT.parents[1] / "LICENSE").read_bytes(), actual["LICENSE"])
                    self.assertTrue(all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist()))

    def test_extracted_skill_validates_and_publishes_without_checkout_imports(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "skill.zip"
            workspace = root / "workspace"
            packager.package(archive, "shared")
            workspace.mkdir()
            with ZipFile(archive) as zipped:
                zipped.extractall(workspace)
            (workspace / "train.py").write_text("def train():\n    return 1\n", encoding="utf-8")
            draft = json.loads((workspace / ".agents/skills/mlview/references/workflow-example.json").read_text(encoding="utf-8"))
            draft_path = workspace / "draft.json"
            draft_path.write_text(json.dumps(draft), encoding="utf-8")
            helper = workspace / ".agents/skills/mlview/scripts/artifact.py"
            env = os.environ.copy()
            env.update({"PYTHONPATH": "", "PYTHONDONTWRITEBYTECODE": "1"})
            for command in ("validate", "publish"):
                result = subprocess.run(
                    [sys.executable, "-I", str(helper), command, str(draft_path), "--workspace", str(workspace)],
                    cwd=root, env=env, text=True, capture_output=True, check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr + result.stdout)
                self.assertTrue(json.loads(result.stdout)["ok"])
            self.assertTrue((workspace / "workflow.mlview.json").is_file())


if __name__ == "__main__":
    unittest.main()
