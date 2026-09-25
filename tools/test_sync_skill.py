import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("sync-skill.py")
SPEC = importlib.util.spec_from_file_location("sync_skill", SCRIPT)
sync_skill = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(sync_skill)


class SyncSkillTests(unittest.TestCase):
    def test_canonical_and_claude_skill_are_identical(self):
        self.assertEqual([], sync_skill.check())

    def test_sync_copies_exactly_the_portable_files_and_keeps_modes(self):
        # EVAL-8: editor and OS files in the canonical tree never reach the plugin copy.
        with tempfile.TemporaryDirectory() as temp:
            source, target = Path(temp) / "skill", Path(temp) / "plugin" / "mlview"
            (source / "scripts").mkdir(parents=True)
            (source / "SKILL.md").write_text("skill", encoding="utf-8")
            (source / "scripts/artifact.py").write_text("print()", encoding="utf-8")
            os.chmod(source / "scripts/artifact.py", 0o755)
            for junk in (".DS_Store", "._SKILL.md", "scripts/__pycache__/artifact.cpython-313.pyc", "SKILL.md~",
                         "tests/test_skill.py", "Thumbs.db"):
                (source / junk).parent.mkdir(parents=True, exist_ok=True)
                (source / junk).write_bytes(b"junk")
            target.mkdir(parents=True)
            (target / "retired.md").write_text("old", encoding="utf-8")
            sync_skill.sync(source, target)
            copied = sorted(path.relative_to(target).as_posix() for path in target.rglob("*") if path.is_file())
            self.assertEqual(["SKILL.md", "scripts/artifact.py"], copied)
            self.assertEqual([], sync_skill.check(source, target))
            if os.name != "nt":
                self.assertEqual(0o755, (target / "scripts/artifact.py").stat().st_mode & 0o777)
            (target / ".DS_Store").write_bytes(b"junk")
            self.assertEqual([], sync_skill.check(source, target), "junk in the copy is not a difference")
            (target / "SKILL.md").write_text("edited", encoding="utf-8")
            self.assertEqual(["different copy: SKILL.md"], sync_skill.check(source, target))

    def test_file_inventory_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            outside = root / "outside"
            outside.write_text("secret", encoding="utf-8")
            skill = root / "skill"
            skill.mkdir()
            try:
                (skill / "linked").symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            with self.assertRaisesRegex(ValueError, "must not contain symlinks"):
                sync_skill.files(skill)


if __name__ == "__main__": unittest.main()
