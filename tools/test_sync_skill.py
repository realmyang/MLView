import importlib.util
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
