import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

HELPER = Path(__file__).parents[1] / "scripts" / "artifact.py"
SPEC = importlib.util.spec_from_file_location("mlview_artifact", HELPER)
artifact = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(artifact)


def document(file="train.py", quote="def train():", **evidence_extra):
    evidence = {"id": "ev", "file": file, "line": 1, "endLine": 1, "quote": quote, **evidence_extra}
    return {
        "workflowVersion": "1.0", "title": "Training",
        "producer": {"kind": "host-llm", "host": "codex"},
        "revision": {"id": "r1"},
        "request": {"question": "Explain training", "scope": "train.py"},
        "phases": [{"id": "p", "label": "Train"}],
        "nodes": [{"id": "n", "label": "Train", "phase": "p", "basis": "observed", "evidence": ["ev"]}],
        "edges": [], "findings": [], "evidence": [evidence],
        "coverage": {"status": "scoped", "summary": "Inspected entrypoint", "inspectedFiles": [file], "limitations": []},
    }


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "train.py").write_text("def train():\n    pass\n", encoding="utf-8")

    def tearDown(self): self.temp.cleanup()

    def validate(self, doc): return artifact.validate(doc, self.root)[0]

    def test_valid_document_and_semantic_edge_cycle(self):
        doc = document()
        doc["nodes"].append({"id": "n2", "label": "Repeat", "phase": "p", "basis": "inferred", "evidence": ["ev"]})
        doc["edges"] = [
            {"id": "e1", "source": "n", "target": "n2", "label": "next", "basis": "observed", "evidence": ["ev"]},
            {"id": "e2", "source": "n2", "target": "n", "label": "loop", "basis": "inferred", "evidence": ["ev"]},
        ]
        self.assertEqual([], self.validate(doc))

    def test_quote_range_and_utf8(self):
        (self.root / "train.py").write_bytes("café\r\nnext\r\n".encode())
        doc = document(quote="café\nnext")
        doc["evidence"][0]["endLine"] = 2
        self.assertEqual([], self.validate(doc))
        doc["evidence"][0]["quote"] = "wrong"
        self.assertIn("quote_mismatch", {e["code"] for e in self.validate(doc)})

    def test_notebook_cell_anchor(self):
        notebook = {"cells": [{"cell_type": "code", "source": ["x = 1\n", "train(x)"]}], "nbformat": 4, "nbformat_minor": 5, "metadata": {}}
        (self.root / "model.ipynb").write_text(json.dumps(notebook), encoding="utf-8")
        self.assertEqual([], self.validate(document("model.ipynb", "train(x)", cell=0) | {"evidence": [{"id": "ev", "file": "model.ipynb", "cell": 0, "line": 2, "endLine": 2, "quote": "train(x)"}]}))

    def test_parent_cycle_is_rejected_but_conceptual_parent_is_allowed(self):
        doc = document()
        doc["nodes"] = [
            {"id": "a", "label": "A", "phase": "p", "parent": "b", "basis": "observed", "evidence": []},
            {"id": "b", "label": "B", "phase": "p", "parent": "a", "basis": "observed", "evidence": []},
        ]
        self.assertIn("parent_cycle", {e["code"] for e in self.validate(doc)})

    def test_revision_cannot_parent_itself(self):
        doc = document()
        doc["revision"]["parent"] = doc["revision"]["id"]
        self.assertIn("revision", {error["code"] for error in self.validate(doc)})

    def test_symlink_escape_is_rejected(self):
        outside = Path(self.temp.name).parent / (self.root.name + "-outside.txt")
        outside.write_text("secret\n", encoding="utf-8")
        try:
            (self.root / "link.py").symlink_to(outside)
            errors = self.validate(document("link.py", "secret"))
            self.assertIn("path_outside_workspace", {e["code"] for e in errors})
        finally: outside.unlink()

    def test_paths_reject_ambiguous_segments(self):
        for path in ("./train.py", "folder//train.py"):
            with self.subTest(path=path):
                errors = self.validate(document(path, "def train():"))
                self.assertIn("path_outside_workspace", {error["code"] for error in errors})

    def run_cli(self, command, doc, output="workflow.mlview.json"):
        draft = self.root / "draft.json"; draft.write_text(json.dumps(doc), encoding="utf-8")
        return subprocess.run([sys.executable, str(HELPER), command, str(draft), "--workspace", str(self.root), "--output", output], text=True, capture_output=True)

    def run_upsert(self, doc, collection, record, draft_name="draft.json"):
        draft = self.root / draft_name; draft.write_text(json.dumps(doc), encoding="utf-8")
        record_path = self.root / "record.json"; record_path.write_text(json.dumps(record), encoding="utf-8")
        result = subprocess.run([
            sys.executable, str(HELPER), "upsert", draft_name, "--workspace", str(self.root),
            "--collection", collection, "--record", str(record_path),
        ], text=True, capture_output=True)
        return result, draft

    def test_publish_revision_guard_and_no_absolute_output(self):
        first = self.run_cli("publish", document())
        self.assertEqual(0, first.returncode, first.stdout)
        response = json.loads(first.stdout)
        self.assertEqual("workflow.mlview.json", response["output"])
        self.assertNotIn(str(self.root), first.stdout)
        stale = document(); stale["revision"] = {"id": "r2", "parent": "wrong"}
        result = self.run_cli("publish", stale)
        self.assertEqual("revision_conflict", json.loads(result.stdout)["errors"][0]["code"])
        self.assertEqual("r1", json.loads((self.root / "workflow.mlview.json").read_text())["revision"]["id"])

    def test_stale_draft_fingerprint_is_rejected(self):
        doc = document(); doc["verification"] = {"files": {"train.py": "0" * 64}, "publishedAt": "2020-01-01T00:00:00Z"}
        result = self.run_cli("publish", doc)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("stale_source", {e["code"] for e in json.loads(result.stdout)["errors"]})

    def test_published_at_requires_rfc3339_syntax(self):
        doc = document()
        digest = artifact.validate(doc, self.root)[1]["train.py"]
        for timestamp in ("2026-09-18 12:00:00+00:00", "2026-09-18T12:00:00+01:02:03", "2026-09-18T12:00:00+01:60", "2026-09-18T12:00:00+24:00"):
            with self.subTest(timestamp=timestamp):
                doc["verification"] = {"files": {"train.py": digest}, "publishedAt": timestamp}
                self.assertIn("format", {error["code"] for error in self.validate(doc)})

    def test_output_path_must_use_portable_relative_syntax(self):
        for output in (".", r"nested\workflow.json"):
            with self.subTest(output=output):
                result = self.run_cli("publish", document(), output=output)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("output_path", json.loads(result.stdout)["errors"][0]["code"])

    def test_same_revision_id_cannot_change_content(self):
        self.assertEqual(0, self.run_cli("publish", document()).returncode)
        changed = document(); changed["revision"]["parent"] = "r1"; changed["title"] = "Changed"
        result = self.run_cli("publish", changed)
        self.assertEqual("revision", json.loads(result.stdout)["errors"][0]["code"])

    def test_source_edit_during_publish_is_rejected(self):
        draft = self.root / "draft.json"; draft.write_text(json.dumps(document()), encoding="utf-8")
        real_validate = artifact.validate
        calls = 0
        def changing_validate(doc, root):
            nonlocal calls
            calls += 1
            result = real_validate(doc, root)
            if calls == 1:
                (self.root / "train.py").write_text("changed\n", encoding="utf-8")
            return result
        stdout = StringIO()
        with mock.patch.object(artifact, "validate", side_effect=changing_validate), redirect_stdout(stdout):
            code = artifact.main(["publish", str(draft), "--workspace", str(self.root)])
        self.assertEqual(1, code)
        self.assertEqual("source_changed", json.loads(stdout.getvalue())["errors"][0]["code"])
        self.assertFalse((self.root / "workflow.mlview.json").exists())

    def test_malformed_reference_types_are_json_errors_not_crashes(self):
        for field, value in (("id", {}), ("phase", {}), ("parent", []), ("basis", []), ("evidence", [{}])):
            with self.subTest(field=field):
                doc = document(); doc["nodes"][0][field] = value
                self.assertTrue(self.validate(doc))

    def test_hashes_include_inspected_context_without_evidence(self):
        (self.root / "config.yaml").write_text("batch: 8\n", encoding="utf-8")
        doc = document(); doc["coverage"]["inspectedFiles"].append("config.yaml")
        result = self.run_cli("publish", doc)
        self.assertEqual(0, result.returncode, result.stdout)
        files = json.loads((self.root / "workflow.mlview.json").read_text())["verification"]["files"]
        self.assertEqual({"config.yaml", "train.py"}, set(files))

    def test_existing_publish_lock_is_actionable_and_not_stolen(self):
        lock = self.root / "workflow.mlview.json.lock"; lock.write_text("", encoding="utf-8")
        result = self.run_cli("publish", document())
        self.assertEqual("publish_locked", json.loads(result.stdout)["errors"][0]["code"])
        self.assertTrue(lock.exists())

    def test_deeply_nested_json_returns_sanitized_error(self):
        draft = self.root / "nested.json"
        draft.write_text("[" * 10000 + "]" * 10000, encoding="utf-8")
        result = subprocess.run([sys.executable, str(HELPER), "validate", str(draft), "--workspace", str(self.root)], text=True, capture_output=True)
        self.assertEqual(1, result.returncode)
        self.assertEqual("invalid_json", json.loads(result.stdout)["errors"][0]["code"])
        self.assertEqual("", result.stderr)

    def test_output_io_errors_are_sanitized(self):
        blocker = self.root / "blocker"
        blocker.write_text("file", encoding="utf-8")
        result = self.run_cli("publish", document(), output="blocker/workflow.json")
        self.assertEqual(1, result.returncode)
        self.assertEqual("publication_io", json.loads(result.stdout)["errors"][0]["code"])
        self.assertNotIn(str(self.root), result.stdout + result.stderr)

    def test_publication_io_failure_removes_owned_lock(self):
        draft = self.root / "draft.json"; draft.write_text(json.dumps(document()), encoding="utf-8")
        stdout = StringIO()
        with mock.patch.object(artifact, "_publish_locked", side_effect=OSError("private path")), redirect_stdout(stdout):
            code = artifact.main(["publish", str(draft), "--workspace", str(self.root)])
        self.assertEqual(1, code)
        self.assertEqual("publication_io", json.loads(stdout.getvalue())["errors"][0]["code"])
        self.assertNotIn("private path", stdout.getvalue())
        self.assertFalse((self.root / "workflow.mlview.json.lock").exists())

    def test_competing_publishers_do_not_both_win(self):
        drafts = []
        for revision in ("race-a", "race-b"):
            doc = document(); doc["revision"] = {"id": revision}
            path = self.root / f"{revision}.json"; path.write_text(json.dumps(doc), encoding="utf-8"); drafts.append(path)
        commands = [[sys.executable, str(HELPER), "publish", str(path), "--workspace", str(self.root)] for path in drafts]
        processes = [subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for command in commands]
        results = [process.communicate(timeout=10) + (process.returncode,) for process in processes]
        self.assertEqual(1, sum(code == 0 for _, _, code in results), results)
        loser_codes = {json.loads(stdout)["errors"][0]["code"] for stdout, _, code in results if code != 0}
        self.assertTrue(loser_codes <= {"publish_locked", "revision_conflict"}, loser_codes)

    def test_upsert_replaces_one_record_and_clears_publication_stamp(self):
        doc = document()
        digest = artifact.validate(doc, self.root)[1]["train.py"]
        doc["verification"] = {"files": {"train.py": digest}, "publishedAt": "2026-09-18T12:00:00Z"}
        replacement = {"id": "n", "label": "Train carefully", "phase": "p", "basis": "observed", "evidence": ["ev"]}
        result, draft = self.run_upsert(doc, "nodes", replacement)
        self.assertEqual(0, result.returncode, result.stdout)
        response = json.loads(result.stdout)
        self.assertEqual("replaced", response["action"])
        edited = json.loads(draft.read_text(encoding="utf-8"))
        self.assertEqual([replacement], edited["nodes"])
        self.assertNotIn("verification", edited)
        self.assertEqual([], artifact.validate(edited, self.root)[0])

    def test_upsert_can_revise_a_checkpoint_with_stale_publication_fingerprints(self):
        doc = document()
        doc["verification"] = {"files": {"train.py": "0" * 64}, "publishedAt": "2026-09-18T12:00:00Z"}
        replacement = {"id": "n", "label": "Rechecked training", "phase": "p", "basis": "observed", "evidence": ["ev"]}
        result, draft = self.run_upsert(doc, "nodes", replacement)
        self.assertEqual(0, result.returncode, result.stdout)
        edited = json.loads(draft.read_text(encoding="utf-8"))
        self.assertNotIn("verification", edited)
        self.assertEqual("Rechecked training", edited["nodes"][0]["label"])

    def test_duplicate_json_members_and_existing_edit_lock_are_rejected(self):
        draft = self.root / "draft.json"
        draft.write_text(json.dumps(document()), encoding="utf-8")
        record = self.root / "record.json"
        record.write_text('{"id":"n","id":"other"}', encoding="utf-8")
        result = subprocess.run([
            sys.executable, str(HELPER), "upsert", "draft.json", "--workspace", str(self.root),
            "--collection", "nodes", "--record", "record.json",
        ], text=True, capture_output=True)
        self.assertEqual("invalid_json", json.loads(result.stdout)["errors"][0]["code"])

        record.write_text(json.dumps({"id": "n", "label": "N", "phase": "p", "basis": "observed", "evidence": ["ev"]}), encoding="utf-8")
        lock = self.root / "draft.json.lock"
        lock.write_text("", encoding="utf-8")
        result = subprocess.run([
            sys.executable, str(HELPER), "upsert", "draft.json", "--workspace", str(self.root),
            "--collection", "nodes", "--record", "record.json",
        ], text=True, capture_output=True)
        self.assertEqual("draft_locked", json.loads(result.stdout)["errors"][0]["code"])
        self.assertEqual(document(), json.loads(draft.read_text(encoding="utf-8")))
        self.assertTrue(lock.exists())

    def test_upsert_detects_a_noncooperating_draft_change(self):
        draft = self.root / "draft.json"; draft.write_text(json.dumps(document()), encoding="utf-8")
        replacement = {"id": "n", "label": "Replacement", "phase": "p", "basis": "observed", "evidence": ["ev"]}
        changed = document(); changed["title"] = "External edit"
        real_validate = artifact.validate
        calls = 0
        def changing_validate(doc, root):
            nonlocal calls
            calls += 1
            result = real_validate(doc, root)
            if calls == 2:
                draft.write_text(json.dumps(changed), encoding="utf-8")
            return result
        stdout = StringIO()
        with mock.patch.object(artifact, "validate", side_effect=changing_validate), redirect_stdout(stdout):
            code = artifact._upsert_draft(draft, "nodes", replacement, self.root)
        self.assertEqual(1, code)
        self.assertEqual("draft_conflict", json.loads(stdout.getvalue())["errors"][0]["code"])
        self.assertEqual("External edit", json.loads(draft.read_text(encoding="utf-8"))["title"])
        self.assertFalse(any(self.root.glob(".mlview-draft-*.tmp")))

    def test_upsert_rejects_nonobject_checkpoint_and_published_target(self):
        record = {"id": "n", "label": "N", "phase": "p", "basis": "observed", "evidence": ["ev"]}
        result, draft = self.run_upsert([], "nodes", record)
        self.assertEqual(1, result.returncode)
        self.assertEqual("checkpoint_invalid", json.loads(result.stdout)["errors"][0]["code"])
        self.assertEqual([], json.loads(draft.read_text(encoding="utf-8")))

        published = self.root / "workflow.mlview.json"
        published.write_text(json.dumps(document()), encoding="utf-8")
        record_path = self.root / "record.json"
        record_path.write_text(json.dumps(record), encoding="utf-8")
        before = published.read_bytes()
        result = subprocess.run([
            sys.executable, str(HELPER), "upsert", published.name, "--workspace", str(self.root),
            "--collection", "nodes", "--record", record_path.name,
        ], text=True, capture_output=True)
        self.assertEqual("published_target", json.loads(result.stdout)["errors"][0]["code"])
        self.assertEqual(before, published.read_bytes())

    def test_oversized_conflict_read_preserves_the_checkpoint(self):
        draft = self.root / "draft.json"
        original = json.dumps(document()).encode("utf-8")
        draft.write_bytes(original)
        replacement = {"id": "n", "label": "Replacement", "phase": "p", "basis": "observed", "evidence": ["ev"]}
        with mock.patch.object(artifact, "_read_bounded", side_effect=[original, ValueError("grew too large")]), redirect_stdout(StringIO()) as stdout:
            code = artifact._upsert_draft(draft, "nodes", replacement, self.root)
        self.assertEqual(1, code)
        self.assertEqual("draft_conflict", json.loads(stdout.getvalue())["errors"][0]["code"])
        self.assertEqual(original, draft.read_bytes())
        self.assertFalse(any(self.root.glob(".mlview-draft-*.tmp")))

    def test_invalid_upsert_preserves_draft_bytes(self):
        invalid_edge = {"id": "bad", "source": "n", "target": "missing", "label": "next", "basis": "observed", "evidence": ["ev"]}
        result, draft = self.run_upsert(document(), "edges", invalid_edge)
        before = json.dumps(document()).encode()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("reference", {error["code"] for error in json.loads(result.stdout)["errors"]})
        self.assertEqual(before, draft.read_bytes())
        self.assertFalse(any(self.root.glob(".mlview-draft-*.tmp")))

    def test_upsert_refuses_invalid_checkpoint_and_symlink_target(self):
        invalid = document(); invalid["nodes"][0]["phase"] = "missing"
        result, draft = self.run_upsert(invalid, "nodes", {"id": "n", "label": "N", "phase": "p", "basis": "observed", "evidence": ["ev"]})
        self.assertEqual("checkpoint_invalid", json.loads(result.stdout)["errors"][0]["code"])
        link = self.root / "linked.json"; link.symlink_to(draft)
        record_path = self.root / "record.json"
        linked = subprocess.run([
            sys.executable, str(HELPER), "upsert", "linked.json", "--workspace", str(self.root),
            "--collection", "nodes", "--record", str(record_path),
        ], text=True, capture_output=True)
        self.assertEqual("draft_path", json.loads(linked.stdout)["errors"][0]["code"])


if __name__ == "__main__": unittest.main()
