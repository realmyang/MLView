"""Every recorded *.mlview.json artifact keeps passing the helper's structural checks.

Recorded artifacts are immutable evidence: a helper rule change must never make
one of them structurally invalid. Workspace checks (paths, quotes, hashes) are
not run here; evals/workflow/test_example.py pins the sample's full validation.
"""
import importlib.util
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HELPER = Path(__file__).resolve().parents[1] / "scripts" / "artifact.py"
SPEC = importlib.util.spec_from_file_location("mlview_artifact_recorded", HELPER)
artifact = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(artifact)


def recorded_artifacts():
    try:
        listed = subprocess.run(["git", "ls-files", "-z", "--", "*.mlview.json"], cwd=ROOT, capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return [path for path in listed.stdout.decode("utf-8").split("\0") if path]


class RecordedArtifactTests(unittest.TestCase):
    def test_recorded_artifacts_pass_shape_and_reference_checks(self):
        paths = recorded_artifacts()
        if paths is None:
            self.skipTest("git ls-files is unavailable outside a git checkout")
        self.assertIn("samples/configured_training.mlview.json", paths)
        self.assertGreaterEqual(len(paths), 23)
        for rel in paths:
            with self.subTest(artifact=rel):
                doc = artifact._parse((ROOT / rel).read_bytes())
                problems = artifact.Problems()
                artifact._basic_shape(doc, problems)
                artifact._references(doc, problems)
                self.assertEqual([], problems.items)


if __name__ == "__main__":
    unittest.main()
