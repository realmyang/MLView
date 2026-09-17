import importlib.util
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


if __name__ == "__main__": unittest.main()
