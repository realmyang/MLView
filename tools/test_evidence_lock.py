"""The evidence lock pins every immutable evaluation evidence file (EVAL-17, Campaign 2 D17).

These checks prove bytes only. They are not a review, an approval or semantic accuracy.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("evidence_lock.py")
SPEC = importlib.util.spec_from_file_location("evidence_lock", SCRIPT)
lock = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(lock)
ROOT = SCRIPT.resolve().parents[1]


class EvidenceLockTests(unittest.TestCase):
    def test_the_lock_equals_the_evidence_tree_in_both_directions(self):
        self.assertEqual([], lock.check())
        self.assertGreaterEqual(len(lock.load()), 95)

    def test_every_tracked_evidence_file_is_locked(self):
        try:
            listed = subprocess.run(["git", "ls-files", "-z", "--", "evals/workflow", "samples"], cwd=ROOT,
                                    capture_output=True, check=True).stdout.decode("utf-8").split("\0")
        except (OSError, subprocess.CalledProcessError) as exc:
            self.skipTest(f"git is unavailable here: {exc}")
        tracked = {path for path in listed if path and lock.in_roots(path)}
        if not tracked:
            self.skipTest("not a Git checkout")
        self.assertEqual(tracked, set(lock.load()))
        self.assertEqual([], sorted(path for path in tracked if lock.is_junk(path)))

    def test_the_lock_file_is_canonical_json(self):
        raw = (ROOT / lock.LOCK).read_bytes()
        self.assertEqual(lock.canonical_json({"format": 1, "files": lock.load()}), raw)

    def test_roots(self):
        for rel in ("evals/workflow/development/dev-gan.json", "evals/workflow/development/native-reviews/codex/dev-gan.json",
                    "evals/workflow/fixtures/historical-paths.json", "evals/workflow/reference-candidates/pilot-flax.json",
                    "evals/workflow/reference-candidates/licenses/README.md", "samples/configured_training.mlview.json",
                    "samples/configured_training/configs/distill.json"):
            with self.subTest(rel=rel):
                self.assertTrue(lock.in_roots(rel))
        for rel in ("evals/workflow/tasks.json", "evals/workflow/repositories.json", "evals/workflow/README.md",
                    "evals/workflow/reference-candidates/README.md", "evals/workflow/reference-candidates/REVIEW_GUIDE.md",
                    "evals/workflow/reference-candidates/nested/pilot.json", "evals/workflow/decisions/pilot-nanogpt.md",
                    "evals/workflow/pilot/pilot-01/freeze.json", "samples/configured_training.mlview.json.bak",
                    "samples/vision_pipeline/train.py", "evals/workflow/development", "tools/evidence_lock.json"):
            with self.subTest(rel=rel):
                self.assertFalse(lock.in_roots(rel))


class TempCopyTests(unittest.TestCase):
    """The same checks against a temporary copy of the evidence and the lock."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.locked = lock.load()
        for rel in self.locked:
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / rel, self.root / rel)
        (self.root / "tools").mkdir()
        shutil.copyfile(ROOT / lock.LOCK, self.root / lock.LOCK)
        self.assertEqual([], lock.check(self.root))

    def tearDown(self): self.temp.cleanup()

    def test_a_flipped_byte_is_reported_with_its_path(self):
        rel = "evals/workflow/development/native-reviews/codex/dev-gan.json"
        data = bytearray((self.root / rel).read_bytes())
        data[len(data) // 2] ^= 0x01
        (self.root / rel).write_bytes(bytes(data))
        problems = lock.check(self.root)
        self.assertEqual(1, len(problems), problems)
        self.assertTrue(problems[0].startswith(f"changed: {rel} (locked sha256 "), problems[0])
        self.assertIn("Evidence is immutable", problems[0])

    def test_missing_extra_linked_and_junk_files(self):
        (self.root / "evals/workflow/fixtures/vision_gan/models.py").unlink()
        (self.root / "evals/workflow/development/new-record.json").write_text("{}", encoding="utf-8")
        (self.root / "evals/workflow/reference-candidates/pilot-new.json").write_text("{}", encoding="utf-8")
        for junk in (".DS_Store", "__pycache__/engine.cpython-313.pyc", "engine.py~", ".mlview/workflow.mlview.json"):
            (self.root / "samples/configured_training" / junk).parent.mkdir(parents=True, exist_ok=True)
            (self.root / "samples/configured_training" / junk).write_bytes(b"junk")
        (self.root / "evals/workflow/reference-candidates/README.md").write_text("living doc", encoding="utf-8")
        problems = lock.check(self.root)
        self.assertEqual([
            "locked evidence is missing: evals/workflow/fixtures/vision_gan/models.py",
            "not locked: evals/workflow/development/new-record.json (lock new evidence with: python tools/evidence_lock.py --add evals/workflow/development/new-record.json)",
            "not locked: evals/workflow/reference-candidates/pilot-new.json (lock new evidence with: python tools/evidence_lock.py --add evals/workflow/reference-candidates/pilot-new.json)",
        ], problems)
        try:
            (self.root / "evals/workflow/fixtures/linked.py").symlink_to(self.root / "evals/workflow/fixtures/README.md")
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")
        self.assertIn("symbolic link in the evidence roots: evals/workflow/fixtures/linked.py", lock.check(self.root))

    def test_add_only_appends_new_files(self):
        before = (self.root / lock.LOCK).read_bytes()
        record = self.root / "evals/workflow/development/records-2026-10/summary.json"
        record.parent.mkdir()
        record.write_text('{"synthetic": true}\n', encoding="utf-8")
        added, unchanged = lock.add(["evals/workflow/development/records-2026-10", "evals/workflow/development/dev-gan.json"], self.root)
        self.assertEqual((["evals/workflow/development/records-2026-10/summary.json"], ["evals/workflow/development/dev-gan.json"]), (added, unchanged))
        self.assertEqual([], lock.check(self.root))
        after = lock.load(self.root)
        self.assertEqual({**self.locked, added[0]: lock.entry(record)}, after)
        self.assertEqual(lock.canonical_json({"format": 1, "files": after}), (self.root / lock.LOCK).read_bytes())
        self.assertNotEqual(before, (self.root / lock.LOCK).read_bytes())
        self.assertEqual(([], [added[0]]), lock.add([str(record)], self.root), "an absolute path inside the repository works")

    def test_add_refuses_changes_paths_outside_the_roots_and_non_files_writing_nothing(self):
        before = (self.root / lock.LOCK).read_bytes()
        (self.root / "evals/workflow/development/dev-gan.json").write_text("edited", encoding="utf-8")
        (self.root / "evals/workflow/tasks.json").write_text("{}", encoding="utf-8")
        (self.root / "evals/workflow/decisions").mkdir()
        (self.root / "evals/workflow/fixtures/.DS_Store").write_bytes(b"junk")
        (self.root / "evals/workflow/fixtures/new.py").write_text("x = 1\n", encoding="utf-8")
        cases = {
            "evals/workflow/development/dev-gan.json": "evals/workflow/development/dev-gan.json: refusing to change a locked entry; evidence is immutable, so add a new dated record instead",
            "evals/workflow/tasks.json": "evals/workflow/tasks.json: outside the evidence roots",
            "evals/workflow/decisions": "evals/workflow/decisions: outside the evidence roots",
            "evals/workflow/fixtures/.DS_Store": "evals/workflow/fixtures/.DS_Store: editor or OS file, not evidence",
            "evals/workflow/fixtures/absent.py": "evals/workflow/fixtures/absent.py: not a regular file",
            "../outside.json": "../outside.json: outside the repository",
            str(Path(tempfile.gettempdir()).resolve() / "elsewhere.json"): "outside the repository",
        }
        for path, message in cases.items():
            with self.subTest(path=path), self.assertRaises(ValueError) as refused:
                lock.add(["evals/workflow/fixtures/new.py", path], self.root)
            self.assertIn(message, str(refused.exception))
            self.assertEqual(before, (self.root / lock.LOCK).read_bytes(), "a refused --add writes nothing")

    def test_command_line(self):
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, capture_output=True, text=True, env=env)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(f"evidence-lock: OK {len(self.locked)} files match tools/evidence_lock.json\n", result.stdout)
        refused = subprocess.run([sys.executable, str(SCRIPT), "--add", "evals/workflow/tasks.json"], cwd=ROOT, capture_output=True, text=True, env=env)
        self.assertEqual(1, refused.returncode)
        self.assertEqual("evidence-lock: evals/workflow/tasks.json: outside the evidence roots\n", refused.stderr)


if __name__ == "__main__":
    unittest.main()
