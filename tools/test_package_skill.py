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
