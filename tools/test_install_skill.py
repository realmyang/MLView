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
            self.assertTrue((root / target / "scripts/artifact.py").is_file())
            self.assertFalse((root / ".claude").exists())

    def test_rejects_destination_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError): installer.install(Path(temp), "../outside")

    def test_rejects_symlinked_parent_escape(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside:
            root = Path(temp)
            (root / ".agents").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError): installer.install(root)
            self.assertEqual([], list(Path(outside).iterdir()), "validation must precede outside directory creation")

    def test_rejects_unowned_destination_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); target = root / ".agents/skills/mlview"
            target.mkdir(parents=True); (target / "personal.txt").write_text("keep")
            with self.assertRaises(ValueError): installer.install(root)

    def test_rejects_copying_source_onto_itself(self):
        source = SCRIPT.resolve().parents[1]
        with self.assertRaises(ValueError): installer.install(source, "skills/mlview")


if __name__ == "__main__": unittest.main()
