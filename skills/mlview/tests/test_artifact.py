import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
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
        stale = [e for e in json.loads(result.stdout)["errors"] if e["code"] == "stale_source"]
        self.assertEqual(1, len(stale), result.stdout)
        self.assertEqual("train.py", stale[0]["file"])
        self.assertEqual("verification.files", stale[0]["path"])
        self.assertIn("delete the draft's verification block", stale[0]["message"])
        self.assertFalse((self.root / "workflow.mlview.json").exists())

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

    def test_publish_rejects_self_parent(self):
        self.assertEqual(0, self.run_cli("publish", document()).returncode)
        changed = document(); changed["revision"]["parent"] = "r1"; changed["title"] = "Changed"
        result = self.run_cli("publish", changed)
        self.assertEqual("revision", json.loads(result.stdout)["errors"][0]["code"])

    def test_parent_revision_id_cannot_be_reused(self):
        self.assertEqual(0, self.run_cli("publish", document()).returncode)
        second = document(); second["revision"] = {"id": "r2", "parent": "r1"}
        self.assertEqual(0, self.run_cli("publish", second).returncode)
        reused = document(); reused["revision"] = {"id": "r1", "parent": "r2"}; reused["title"] = "Different content reusing r1"
        result = self.run_cli("publish", reused)
        self.assertEqual(1, result.returncode)
        error = json.loads(result.stdout)["errors"][0]
        self.assertEqual("revision_id_reused", error["code"])
        self.assertEqual("revision.id", error["path"])
        self.assertEqual("revision ID r1 was already used by this artifact (the published revision's parent); choose a new ID", error["message"])
        self.assertEqual("r2", json.loads((self.root / "workflow.mlview.json").read_text())["revision"]["id"])

    def test_source_edit_during_publish_is_rejected(self):
        draft = self.root / "draft.json"; draft.write_text(json.dumps(document()), encoding="utf-8")
        real_validate = artifact.validate
        calls = 0
        def changing_validate(doc, root, **kwargs):
            nonlocal calls
            calls += 1
            result = real_validate(doc, root, **kwargs)
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
        error = json.loads(result.stdout)["errors"][0]
        self.assertEqual(("invalid_json", "$", "nesting is too deep"), (error["code"], error["path"], error["message"]))
        self.assertEqual("", result.stderr)

    def test_output_io_errors_are_sanitized(self):
        blocker = self.root / "blocker"
        blocker.write_text("file", encoding="utf-8")
        result = self.run_cli("publish", document(), output="blocker/workflow.mlview.json")
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
        def changing_validate(doc, root, **kwargs):
            nonlocal calls
            calls += 1
            result = real_validate(doc, root, **kwargs)
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

    # Helpers for the contract tests below.

    def write_draft(self, doc, name="draft.json"):
        draft = self.root / name
        draft.parent.mkdir(parents=True, exist_ok=True)
        draft.write_text(json.dumps(doc), encoding="utf-8")
        return draft

    def run_main(self, *args):
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = artifact.main(list(args))
        self.assertEqual("", stderr.getvalue())
        lines = stdout.getvalue().splitlines()
        self.assertEqual(1, len(lines), stdout.getvalue())
        self.assertNotIn(str(self.root), stdout.getvalue())
        return code, json.loads(lines[0])

    def run_raw(self, *args, cwd=None):
        result = subprocess.run([sys.executable, str(HELPER), *args], text=True, capture_output=True, cwd=cwd)
        self.assertEqual("", result.stderr)
        self.assertNotIn(str(self.root), result.stdout)
        return result.returncode, json.loads(result.stdout)

    def codes(self, doc, warnings=None):
        return {error["code"] for error in artifact.validate(doc, self.root, warnings=warnings)[0]}

    # CONTRACT-1

    def test_null_node_parent_is_rejected_and_not_published(self):
        doc = document()
        doc["nodes"].append({"id": "child", "label": "Child", "phase": "p", "parent": None, "basis": "observed", "evidence": ["ev"]})
        errors = self.validate(doc)
        parent = [error for error in errors if error["code"] == "parent"]
        self.assertEqual("nodes[1].parent", parent[0]["path"])
        self.assertEqual("must be the ID of a different node; omit parent for root nodes", parent[0]["message"])
        for value in ("", "missing", "child"):
            with self.subTest(parent=value):
                doc["nodes"][1]["parent"] = value
                self.assertIn("parent", self.codes(doc))
        doc["nodes"][1]["parent"] = None
        result = self.run_cli("publish", doc)
        self.assertEqual(1, result.returncode)
        self.assertFalse((self.root / "workflow.mlview.json").exists())

    def test_null_verification_is_a_type_error(self):
        doc = document(); doc["verification"] = None
        errors = self.validate(doc)
        self.assertEqual([("type", "verification")], [(error["code"], error["path"]) for error in errors])

    # CONTRACT-3

    def test_publish_refuses_an_artifact_over_the_size_limit(self):
        self.assertEqual(0, self.run_cli("publish", document()).returncode)
        artifact_path = self.root / "workflow.mlview.json"
        before = artifact_path.read_bytes()
        second = document(); second["revision"] = {"id": "r2", "parent": "r1"}
        second["nodes"][0]["detail"] = "x" * 500
        draft = self.write_draft(second)
        # The existing artifact and the draft must still fit (the helper refuses to publish over an
        # oversize artifact); only the new revision is too large.
        limit = max(len(before), len(draft.read_bytes())) + 10
        with mock.patch.object(artifact, "MAX_DOCUMENT", limit):
            code, response = self.run_main("publish", str(draft), "--workspace", str(self.root))
        self.assertEqual(1, code)
        error = response["errors"][0]
        self.assertEqual(("document_too_large", "$"), (error["code"], error["path"]))
        self.assertRegex(error["message"], rf"^published artifact would be \d+ bytes; the limit is {limit}$")
        self.assertEqual(before, artifact_path.read_bytes())
        self.assertFalse(any(self.root.glob(".mlview-*.tmp")))
        self.assertFalse((self.root / "workflow.mlview.json.lock").exists())

    # CONTRACT-4

    def test_unpaired_surrogates_are_rejected_by_every_command(self):
        doc = document(); doc["title"] = "Loss \ud83d spike"
        errors = self.validate(doc)
        self.assertIn(("text_encoding", "$.title", "contains an unpaired surrogate; use valid Unicode text"), {(e["code"], e["path"], e["message"]) for e in errors})
        keyed = document(); keyed["nodes"][0]["\udc00"] = 1
        self.assertIn("text_encoding", self.codes(keyed))
        for command in ("validate", "publish"):
            with self.subTest(command=command):
                code, response = self.run_raw(command, str(self.write_draft(doc)), "--workspace", str(self.root))
                self.assertEqual(1, code)
                self.assertIn("text_encoding", {error["code"] for error in response["errors"]})
        self.assertFalse((self.root / "workflow.mlview.json").exists())
        record = {"id": "n", "label": "Bad \udc00 label", "phase": "p", "basis": "observed", "evidence": ["ev"]}
        result, draft = self.run_upsert(document(), "nodes", record)
        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stderr)
        self.assertIn("text_encoding", {error["code"] for error in json.loads(result.stdout)["errors"]})
        self.assertEqual(document(), json.loads(draft.read_text(encoding="utf-8")))

    # CONTRACT-6

    def test_binary_and_latin1_inspected_files_are_fingerprinted_from_raw_bytes(self):
        pdf = b"%PDF-1.4\n\x00\xff\xfe binary\n%%EOF\n"
        latin1 = "name = caf\xe9\n".encode("latin-1")
        (self.root / "paper.pdf").write_bytes(pdf)
        (self.root / "latin1.cfg").write_bytes(latin1)
        doc = document(); doc["coverage"]["inspectedFiles"] += ["paper.pdf", "latin1.cfg"]
        result = self.run_cli("publish", doc)
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertNotIn("warnings", json.loads(result.stdout))
        files = json.loads((self.root / "workflow.mlview.json").read_text(encoding="utf-8"))["verification"]["files"]
        self.assertEqual(hashlib.sha256(pdf).hexdigest(), files["paper.pdf"])
        self.assertEqual(hashlib.sha256(latin1).hexdigest(), files["latin1.cfg"])

    def test_oversize_inspected_file_is_listed_without_a_fingerprint(self):
        (self.root / "big.bin").write_bytes(b"a" * 100)
        doc = document(); doc["coverage"]["inspectedFiles"].append("big.bin")
        draft = self.write_draft(doc)
        with mock.patch.object(artifact, "MAX_SOURCE", 64):
            code, response = self.run_main("validate", str(draft), "--workspace", str(self.root))
        self.assertEqual(0, code, response)
        self.assertEqual({"train.py"}, set(response["files"]))
        self.assertEqual([{"code": "not_fingerprinted", "path": "coverage.inspectedFiles[1]", "message": "file is larger than 64 bytes; listed without a freshness fingerprint"}], response["warnings"])

    def test_inspected_directory_is_still_rejected(self):
        (self.root / "sub").mkdir()
        doc = document(); doc["coverage"]["inspectedFiles"].append("sub")
        errors = self.validate(doc)
        self.assertEqual([("invalid_path", "coverage.inspectedFiles[1]")], [(e["code"], e["path"]) for e in errors])

    # CONTRACT-15 and SKILL-4

    def test_relative_draft_resolves_against_the_workspace(self):
        self.write_draft(document(), ".mlview/llm/run/draft.json")
        for command in ("validate", "publish"):
            with self.subTest(command=command):
                code, response = self.run_raw(command, ".mlview/llm/run/draft.json", "--workspace", self.root.name, cwd=self.root.parent)
                self.assertEqual(0, code, response)
        self.assertTrue((self.root / "workflow.mlview.json").is_file())

    def test_draft_path_syntax_errors(self):
        for value in ("sub\\draft.json", "C:draft.json"):
            with self.subTest(value=value):
                code, response = self.run_raw("validate", value, "--workspace", str(self.root))
                self.assertEqual(1, code)
                self.assertEqual(("draft_path", "draft"), (response["errors"][0]["code"], response["errors"][0]["path"]))

    def test_missing_draft_is_draft_not_found(self):
        code, response = self.run_raw("validate", "missing/draft.json", "--workspace", str(self.root))
        self.assertEqual(1, code)
        self.assertEqual([{"code": "draft_not_found", "path": "draft", "message": "draft file does not exist (relative paths are resolved against --workspace)"}], response["errors"])
        code, response = self.run_raw("validate", str(self.root / "missing" / "draft.json"), "--workspace", str(self.root))
        self.assertEqual([{"code": "draft_not_found", "path": "draft", "message": "draft file does not exist"}], response["errors"])
        record = self.root / "record.json"; record.write_text("{}", encoding="utf-8")
        self.write_draft(document())
        code, response = self.run_raw("upsert", "missing.json", "--workspace", str(self.root), "--collection", "nodes", "--record", "record.json")
        self.assertEqual("draft_not_found", response["errors"][0]["code"])

    def test_oversized_draft_is_draft_too_large(self):
        draft = self.root / "draft.json"; draft.write_bytes(b" " * (artifact.MAX_DOCUMENT + 1))
        code, response = self.run_raw("validate", str(draft), "--workspace", str(self.root))
        self.assertEqual(1, code)
        self.assertEqual([{"code": "draft_too_large", "path": "draft", "message": "draft file exceeds 2097152 bytes"}], response["errors"])

    def test_non_utf8_draft_is_draft_encoding(self):
        draft = self.root / "draft.json"; draft.write_bytes(b'{"title": "caf\xe9"}')
        code, response = self.run_raw("publish", str(draft), "--workspace", str(self.root))
        self.assertEqual(1, code)
        self.assertEqual(("draft_encoding", "draft"), (response["errors"][0]["code"], response["errors"][0]["path"]))

    def test_parse_error_reports_line_and_column(self):
        draft = self.root / "draft.json"; draft.write_text('{\n  "title": "x"\n  "nodes": []\n}\n', encoding="utf-8")
        code, response = self.run_raw("validate", str(draft), "--workspace", str(self.root))
        self.assertEqual(1, code)
        self.assertEqual([{"code": "invalid_json", "path": "$", "message": "Expecting ',' delimiter at line 3, column 3", "line": 3, "column": 3}], response["errors"])

    def test_duplicate_member_error_names_the_key(self):
        draft = self.root / "draft.json"; draft.write_text('{"title": "a", "title": "b"}', encoding="utf-8")
        code, response = self.run_raw("validate", str(draft), "--workspace", str(self.root))
        self.assertEqual([{"code": "invalid_json", "path": "$", "message": "duplicate JSON member: title"}], response["errors"])
        draft.write_text('{"%s": 1, "%s": 2}' % ("k" * 300, "k" * 300), encoding="utf-8")
        code, response = self.run_raw("validate", str(draft), "--workspace", str(self.root))
        self.assertEqual("duplicate JSON member: " + "k" * 200, response["errors"][0]["message"])

    def test_record_errors_use_the_record_path(self):
        self.write_draft(document())
        base = ("upsert", "draft.json", "--workspace", str(self.root), "--collection", "nodes", "--record")
        code, response = self.run_raw(*base, "missing-record.json")
        self.assertEqual([{"code": "draft_not_found", "path": "record", "message": "record file does not exist (relative paths are resolved against --workspace)"}], response["errors"])
        outside = self.root.parent / (self.root.name + "-record.json")
        outside.write_text("{}", encoding="utf-8")
        try:
            code, response = self.run_raw(*base, str(outside))
            self.assertEqual(("draft_path", "record"), (response["errors"][0]["code"], response["errors"][0]["path"]))
        finally: outside.unlink()
        (self.root / "record.json").write_text('{"id": ', encoding="utf-8")
        code, response = self.run_raw(*base, "record.json")
        self.assertEqual(("invalid_json", "record"), (response["errors"][0]["code"], response["errors"][0]["path"]))
        self.assertIn("line", response["errors"][0])

    def test_revision_conflict_names_the_published_revision(self):
        orphan = document(); orphan["revision"] = {"id": "r2", "parent": "r1"}
        result = self.run_cli("publish", orphan)
        self.assertEqual("no artifact is published at workflow.mlview.json; omit revision.parent", json.loads(result.stdout)["errors"][0]["message"])
        self.assertEqual(0, self.run_cli("publish", document()).returncode)
        for revision in ({"id": "r2", "parent": "wrong"}, {"id": "r2"}):
            with self.subTest(revision=revision):
                stale = document(); stale["revision"] = revision
                error = json.loads(self.run_cli("publish", stale).stdout)["errors"][0]
                self.assertEqual(("revision_conflict", "does not match the published revision r1"), (error["code"], error["message"]))

    def test_producer_error_lists_supported_hosts(self):
        doc = document(); doc["producer"]["host"] = "claude"
        error = [e for e in self.validate(doc) if e["code"] == "producer"][0]
        self.assertIn("copilot, codex, claude-code, unknown", error["message"])

    def test_quote_mismatch_shows_the_cited_lines(self):
        error = [e for e in self.validate(document(quote="def train()")) if e["code"] == "quote_mismatch"][0]
        self.assertEqual('quote does not exactly match the cited lines; the cited lines are: "def train():"', error["message"])
        (self.root / "long.py").write_text("x" * 150 + "\n" + "y" * 150 + "\n", encoding="utf-8")
        doc = document("long.py", "wrong"); doc["evidence"][0]["endLine"] = 2
        error = [e for e in self.validate(doc) if e["code"] == "quote_mismatch"][0]
        self.assertTrue(error["message"].endswith(json.dumps("x" * 150 + "\n" + "y" * 49)), error["message"])

    # SKILL-2 and CRIT-1

    def test_owned_path_predicate(self):
        owned = (".mlview/llm/run/draft.json", ".MLView/notes.md", ".agents/skills/mlview/SKILL.md", ".claude/skills/mlview/scripts/artifact.py",
                 ".github/skills/MLVIEW/references/x.md", "workflow.mlview.json", "sub/Diagram.MLView.JSON", "old.draft.json", "a/b.DRAFT.json")
        project = ("skills/mlview/SKILL.md", "train.py", ".mlviewer/x.py", "mlview.json", "draft.jsonl", ".agents/skills/other/SKILL.md", "notes.mlview.json.bak")
        for rel in owned:
            with self.subTest(rel=rel): self.assertTrue(artifact.is_owned_path(rel))
        for rel in project:
            with self.subTest(rel=rel): self.assertFalse(artifact.is_owned_path(rel))
        # SECURITY2-1: U+017F (long s) and U+212A (Kelvin sign) fold to s and k, as APFS resolves them.
        for rel in (".claude/\u017fkills/mlview/SKILL.md", ".agents/s\u212aills/mlview/SKILL.md", ".github/\u017fKILLS/mlview/x",
                    "other.mlview.j\u017fon", "notes.draft.j\u017fon", ".mlview/\u212a.md"):
            with self.subTest(rel=rel): self.assertTrue(artifact.is_owned_path(rel))
        for rel in (".mlv\u0130ew/x", ".claude/\u0161kills/mlview/SKILL.md", "\u212aeras.mlview.jsonl"):
            with self.subTest(rel=rel): self.assertFalse(artifact.is_owned_path(rel))

    def test_refinement_listing_the_artifact_is_not_fingerprinted(self):
        self.assertEqual(0, self.run_cli("publish", document()).returncode)
        second = document(); second["revision"] = {"id": "r2", "parent": "r1"}
        second["coverage"]["inspectedFiles"].append("workflow.mlview.json")
        result = self.run_cli("publish", second)
        self.assertEqual(0, result.returncode, result.stdout)
        response = json.loads(result.stdout)
        self.assertEqual([{"code": "excluded_inspected", "path": "coverage.inspectedFiles[1]", "message": "MLView-owned file is listed but not fingerprinted; list only project files"}], response["warnings"])
        published = json.loads((self.root / "workflow.mlview.json").read_text(encoding="utf-8"))
        self.assertEqual({"train.py"}, set(published["verification"]["files"]))
        code, check = self.run_raw("validate", "workflow.mlview.json", "--workspace", str(self.root))
        self.assertEqual(0, code, check)
        self.assertEqual([], check["errors"])
        self.assertEqual(["excluded_inspected"], [w["code"] for w in check["warnings"]])

    def test_evidence_on_mlview_files_is_excluded(self):
        self.write_draft(document(), "workflow.mlview.json")
        for rel in ("workflow.mlview.json", ".mlview/llm/run/draft.json", ".Agents/Skills/MLView/SKILL.md"):
            with self.subTest(rel=rel):
                errors = self.validate(document(rel, "{"))
                self.assertEqual([("excluded_evidence", "evidence[0].file")], [(e["code"], e["path"]) for e in errors if e["path"].startswith("evidence")])
                self.assertEqual("evidence must cite project files, not an MLView artifact, draft or installed MLView skill file", errors[0]["message"])

    def test_output_must_end_in_mlview_json(self):
        result = self.run_cli("publish", document(), output="diagram.json")
        self.assertEqual(1, result.returncode)
        self.assertEqual([{"code": "output_path", "path": "--output", "message": "must be a workspace-relative path ending in .mlview.json"}], json.loads(result.stdout)["errors"])
        self.assertFalse((self.root / "diagram.json").exists())
        result = self.run_cli("publish", document(), output="out/Diagram.MLView.JSON")
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertEqual("out/Diagram.MLView.JSON", json.loads(result.stdout)["output"])

    def test_installed_skill_files_are_listed_without_a_fingerprint(self):
        skill = self.root / ".agents/skills/mlview/SKILL.md"
        skill.parent.mkdir(parents=True); skill.write_text("changed after publish\n", encoding="utf-8")
        doc = document(); doc["coverage"]["inspectedFiles"].append(".agents/skills/mlview/SKILL.md")
        digest = artifact.validate(document(), self.root)[1]["train.py"]
        doc["verification"] = {"files": {"train.py": digest, ".agents/skills/mlview/SKILL.md": "0" * 64}, "publishedAt": "2026-09-25T00:00:00Z"}
        warnings = []
        errors, hashes = artifact.validate(doc, self.root, warnings=warnings)
        self.assertEqual([], errors)
        self.assertEqual({"train.py"}, set(hashes))
        self.assertEqual([("excluded_inspected", "coverage.inspectedFiles[1]")], [(w["code"], w["path"]) for w in warnings])
        skill.unlink()
        self.assertEqual([], artifact.validate(doc, self.root)[0])
        doc["coverage"]["inspectedFiles"][1] = ".agents/skills/mlview/../SKILL.md"
        self.assertEqual({"path_outside_workspace"}, self.codes(doc))

    # SKILL-3

    def test_narrowed_scope_verification_key_is_ignored(self):
        (self.root / "config.yaml").write_text("batch: 8\n", encoding="utf-8")
        first = document(); first["coverage"]["inspectedFiles"].append("config.yaml")
        self.assertEqual(0, self.run_cli("publish", first).returncode)
        published = json.loads((self.root / "workflow.mlview.json").read_text(encoding="utf-8"))
        (self.root / "config.yaml").write_text("batch: 16\n", encoding="utf-8")
        narrowed = document(); narrowed["revision"] = {"id": "r2", "parent": "r1"}
        narrowed["verification"] = published["verification"]
        narrowed["verification"]["files"]["unlisted/other.py"] = "1" * 64
        result = self.run_cli("publish", narrowed)
        self.assertEqual(0, result.returncode, result.stdout)
        files = json.loads((self.root / "workflow.mlview.json").read_text(encoding="utf-8"))["verification"]["files"]
        self.assertEqual({"train.py"}, set(files))

    # SKILL-5

    def test_bundled_example_validates_with_the_helper(self):
        example = json.loads((HELPER.parents[1] / "references" / "workflow-example.json").read_text(encoding="utf-8"))
        (self.root / "train.py").write_text("def train():\n", encoding="utf-8")
        self.assertEqual([], self.validate(example))
        self.assertEqual("example-model", example["producer"]["model"])
        self.assertEqual("loop", example["nodes"][1]["parent"])

    # SKILL-9

    def test_bom_source_accepts_line1_quote_with_or_without_the_bom(self):
        raw = b"\xef\xbb\xbfimport torch\nx = 1\n"
        (self.root / "bom.py").write_bytes(raw)
        for quote in ("import torch", "\ufeffimport torch"):
            with self.subTest(quote=quote):
                errors, hashes = artifact.validate(document("bom.py", quote), self.root)
                self.assertEqual([], errors)
                self.assertEqual(hashlib.sha256(raw).hexdigest(), hashes["bom.py"])
        doc = document("bom.py", "import torch\nx = 1"); doc["evidence"][0]["endLine"] = 2
        self.assertEqual([], self.validate(doc))
        doc = document("bom.py", "\ufeffx = 1"); doc["evidence"][0].update(line=2, endLine=2)
        self.assertIn("quote_mismatch", self.codes(doc))
        notebook = {"cells": [{"cell_type": "code", "source": ["train(x)"]}], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
        (self.root / "bom.ipynb").write_bytes(b"\xef\xbb\xbf" + json.dumps(notebook).encode("utf-8"))
        self.assertEqual([], self.validate(document("bom.ipynb", "train(x)", cell=0)))

    # SKILL-11

    def test_resolve_runtime_errors_are_reported_as_json(self):
        (self.root / "loop.py").write_text("x = 1\n", encoding="utf-8")
        real_resolve = Path.resolve
        def looping(path, *args, **kwargs):
            if path.name in {"loop.py", "loop.mlview.json", "loop.draft.json"}:
                raise RuntimeError(f"Symlink loop from {path}")
            return real_resolve(path, *args, **kwargs)
        draft = self.write_draft(document("loop.py", "x = 1"))
        with mock.patch.object(Path, "resolve", looping):
            code, response = self.run_main("validate", str(draft), "--workspace", str(self.root))
            self.assertEqual(1, code)
            self.assertEqual(("path_outside_workspace", "evidence[0].file"), (response["errors"][0]["code"], response["errors"][0]["path"]))
            code, response = self.run_main("publish", str(self.write_draft(document())), "--workspace", str(self.root), "--output", "loop.mlview.json")
            self.assertEqual(("output_path", 1), (response["errors"][0]["code"], code))
            self.write_draft(document(), "loop.draft.json")
            code, response = self.run_main("upsert", "loop.draft.json", "--workspace", str(self.root), "--collection", "nodes", "--record", "record.json")
            self.assertEqual(("draft_path", "draft"), (response["errors"][0]["code"], response["errors"][0]["path"]))

    def test_unexpected_exception_is_a_sanitized_internal_error(self):
        draft = self.write_draft(document())
        with mock.patch.object(artifact, "_match_mode", side_effect=ZeroDivisionError(str(self.root))):
            code, response = self.run_main("publish", str(draft), "--workspace", str(self.root))
        self.assertEqual(1, code)
        self.assertEqual({"ok": False, "errors": [{"code": "internal_error", "path": "$", "message": "the helper failed unexpectedly (ZeroDivisionError)"}]}, response)
        self.assertFalse((self.root / "workflow.mlview.json.lock").exists())
        self.assertFalse((self.root / "workflow.mlview.json").exists())
        self.assertFalse(any(self.root.glob(".mlview-*.tmp")))

    def test_notebooks_with_nan_or_infinity_are_not_json(self):
        # Campaign 2 SPEC 7.2: json.loads accepted NaN and Infinity in a cited notebook, while the
        # viewer's JSON.parse refuses the notebook, so a helper-valid citation failed in the viewer.
        message = "cited notebook is not valid JSON (NaN, Infinity or a syntax error); the viewer cannot read it"
        for constant in ("NaN", "Infinity", "-Infinity", "nan", "1,"):
            with self.subTest(constant=constant):
                text = '{"cells": [{"cell_type": "code", "execution_count": %s, "source": ["fit(x)"]}], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}' % constant
                (self.root / "flow.ipynb").write_text(text, encoding="utf-8")
                self.assertIsNone(artifact._parse_notebook(text))
                errors = self.validate(document("flow.ipynb", "fit(x)", cell=0))
                self.assertEqual([("notebook_cell", "evidence[0].cell", message)], [(e["code"], e["path"], e["message"]) for e in errors])
        # A cell that does not exist in a valid notebook keeps its own message.
        (self.root / "flow.ipynb").write_text('{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}', encoding="utf-8")
        self.assertEqual(["cell does not identify valid notebook source"], [e["message"] for e in self.validate(document("flow.ipynb", "fit(x)", cell=0))])

    def test_duplicate_notebook_members_keep_the_last_value_like_json_parse(self):
        text = '{"cells": [{"cell_type": "code", "source": ["old(x)"], "source": ["fit(x)"]}], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}'
        (self.root / "flow.ipynb").write_text(text, encoding="utf-8")
        self.assertEqual([], self.validate(document("flow.ipynb", "fit(x)", cell=0)))
        self.assertIn("quote_mismatch", {e["code"] for e in self.validate(document("flow.ipynb", "old(x)", cell=0))})

    def test_deeply_nested_notebook_metadata_is_a_notebook_cell_error(self):
        # Deep enough that json.loads raises RecursionError on every supported Python (3.14 parses
        # 20000 levels on an 8 MiB stack; 1,000,000 fails on 3.10 through 3.14).
        nested = "[" * 1_000_000 + "]" * 1_000_000
        text = '{"cells": [{"cell_type": "code", "source": "train(x)"}], "metadata": {"deep": %s}, "nbformat": 4, "nbformat_minor": 5}' % nested
        (self.root / "deep.ipynb").write_text(text, encoding="utf-8")
        errors = self.validate(document("deep.ipynb", "train(x)", cell=0))
        self.assertEqual([("notebook_cell", "evidence[0].cell")], [(e["code"], e["path"]) for e in errors])

    # SKILL-12

    @unittest.skipIf(os.name == "nt", "POSIX file modes")
    def test_replacement_files_keep_the_target_mode_or_honour_the_umask(self):
        draft = self.write_draft(document())
        artifact_path = self.root / "workflow.mlview.json"
        old = os.umask(0o027)
        try:
            self.assertEqual(0, self.run_main("publish", str(draft), "--workspace", str(self.root))[0])
            self.assertEqual(0o640, artifact_path.stat().st_mode & 0o777)
            os.chmod(artifact_path, 0o644)
            second = document(); second["revision"] = {"id": "r2", "parent": "r1"}
            os.umask(0o077)
            self.assertEqual(0, self.run_main("publish", str(self.write_draft(second)), "--workspace", str(self.root))[0])
            self.assertEqual(0o644, artifact_path.stat().st_mode & 0o777)
            checkpoint = self.write_draft(document(), "checkpoint.draft.json"); os.chmod(checkpoint, 0o644)
            (self.root / "record.json").write_text(json.dumps({"id": "n", "label": "Renamed", "phase": "p", "basis": "observed", "evidence": ["ev"]}), encoding="utf-8")
            code, response = self.run_main("upsert", "checkpoint.draft.json", "--workspace", str(self.root), "--collection", "nodes", "--record", "record.json")
            self.assertEqual(0, code, response)
            self.assertEqual(0o644, checkpoint.stat().st_mode & 0o777)
        finally:
            os.umask(old)

    # SKILL-18

    def test_notebook_is_parsed_once_for_many_citations(self):
        source = [f"step_{i} = {i}\n" for i in range(200)]
        notebook = {"cells": [{"cell_type": "code", "source": source}], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
        (self.root / "many.ipynb").write_text(json.dumps(notebook), encoding="utf-8")
        doc = document("many.ipynb", "step_0 = 0", cell=0)
        doc["evidence"] = [{"id": f"ev{i}", "file": "many.ipynb", "cell": 0, "line": i + 1, "endLine": i + 1, "quote": f"step_{i} = {i}"} for i in range(200)]
        doc["nodes"][0]["evidence"] = ["ev0"]
        with mock.patch.object(artifact, "_parse_notebook", wraps=artifact._parse_notebook) as parse:
            self.assertEqual([], self.validate(doc))
        self.assertEqual(1, parse.call_count)

    # SKILL-21 (plus the helper half of CONTRACT-10: NUL in entrypoints)

    def test_drive_qualified_and_nul_paths_are_rejected(self):
        drive = "must be a slash-separated relative path without a drive letter"
        errors = self.validate(document("C:/x/train.py", "def train():"))
        self.assertIn(("invalid_path", "evidence[0].file", drive), {(e["code"], e["path"], e["message"]) for e in errors})
        doc = document(); doc["request"]["entrypoints"] = ["a\u0000b.py", "C:/train.py", "train.py"]
        errors = self.validate(doc)
        self.assertEqual([("invalid_path", "request.entrypoints[0]"), ("invalid_path", "request.entrypoints[1]")], [(e["code"], e["path"]) for e in errors])
        self.assertEqual(drive, errors[1]["message"])
        doc = document(); doc["coverage"]["inspectedFiles"].append("c:train.py")
        self.assertEqual({"invalid_path"}, self.codes(doc))
        doc = document(); doc["verification"] = {"files": {"C:/train.py": "0" * 64}, "publishedAt": "2026-09-25T00:00:00Z"}
        self.assertEqual({"invalid_path"}, self.codes(doc))
        result = self.run_cli("publish", document(), output="C:/x/workflow.mlview.json")
        self.assertEqual([{"code": "output_path", "path": "--output", "message": drive}], json.loads(result.stdout)["errors"])


    # Review round 1

    def upsert_raw(self, target, record):
        (self.root / "record.json").write_text(json.dumps(record), encoding="utf-8")
        return self.run_raw("upsert", target, "--workspace", str(self.root), "--collection", "nodes", "--record", "record.json")

    def test_upsert_refuses_published_artifacts_in_any_case_spelling(self):
        # HELPER1-1 / SECURITY1-6: the guard folds case like --output and the owned-path rule.
        record = {"id": "n2", "label": "N2", "phase": "p", "basis": "observed", "evidence": ["ev"]}
        self.assertEqual(0, self.run_cli("publish", document(), output="Diagram.MLVIEW.JSON").returncode)
        upper = self.root / "Diagram.MLVIEW.JSON"
        before = upper.read_bytes()
        code, response = self.upsert_raw("Diagram.MLVIEW.JSON", record)
        self.assertEqual((1, "published_target"), (code, response["errors"][0]["code"]))
        self.assertEqual(before, upper.read_bytes())
        self.assertEqual(0, self.run_cli("publish", document()).returncode)
        published = self.root / "workflow.mlview.json"
        before = published.read_bytes()
        for alias in ("WORKFLOW.MLVIEW.JSON", "workflow.mlview.jſon"):
            with self.subTest(alias=alias):
                try:
                    aliased = os.path.samefile(self.root / alias, published)
                except OSError:
                    aliased = False
                if not aliased:
                    self.skipTest("the file system does not map this spelling onto the artifact")
                code, response = self.upsert_raw(alias, record)
                self.assertEqual((1, "published_target"), (code, response["errors"][0]["code"]))
                self.assertEqual(before, published.read_bytes())

    def test_missing_workspace_is_reported(self):
        # HELPER1-2: a --workspace that does not exist is not a directory of workspace files.
        draft = self.write_draft(document())
        code, response = self.run_raw("validate", str(draft), "--workspace", str(self.root / "missing"))
        self.assertEqual(1, code)
        self.assertEqual([{"code": "workspace_path", "path": "--workspace", "message": "must be an existing directory (the VS Code workspace folder that will contain the artifact)"}], response["errors"])

    def test_tracked_file_limit_is_reported_by_validate_and_publish(self):
        # HELPER1-3: verification.files holds at most 2000 keys, so validate refuses more tracked files.
        (self.root / "ctx").mkdir()
        doc = document()
        doc["coverage"]["inspectedFiles"] = [f"ctx/f{i}.txt" for i in range(2000)]
        for rel in doc["coverage"]["inspectedFiles"]: (self.root / rel).write_text("x\n", encoding="utf-8")
        message = "at most 2000 distinct tracked files (cited evidence files plus inspected project files) can be fingerprinted; list fewer files"
        errors = self.validate(doc)
        self.assertEqual([("limit", "coverage.inspectedFiles", message)], [(e["code"], e["path"], e["message"]) for e in errors])
        result = self.run_cli("publish", doc)
        self.assertEqual(1, result.returncode)
        self.assertEqual(["limit"], [e["code"] for e in json.loads(result.stdout)["errors"]])
        doc["coverage"]["inspectedFiles"][-1] = "train.py"  # the cited file inside the list: 2000 tracked
        self.assertEqual([], self.validate(doc))
        doc["coverage"]["inspectedFiles"][-1] = ".mlview/notes.md"  # owned entries are not tracked: 1999 + train.py
        self.assertEqual([], self.validate(doc))

    def test_final_publish_problems_that_are_not_source_changes_are_reported_as_is(self):
        # HELPER1-3: source_changed only when fingerprints move.
        draft = self.write_draft(document())
        real_validate = artifact.validate
        calls = 0
        def final_error(doc, root, **kwargs):
            nonlocal calls
            calls += 1
            errors, hashes = real_validate(doc, root, **kwargs)
            return (errors + [{"code": "limit", "path": "verification.files", "message": "must contain at most 2000 entries"}] if calls == 2 else errors), hashes
        with mock.patch.object(artifact, "validate", side_effect=final_error):
            code, response = self.run_main("publish", str(draft), "--workspace", str(self.root))
        self.assertEqual(1, code)
        self.assertEqual(["limit"], [e["code"] for e in response["errors"]])
        self.assertFalse((self.root / "workflow.mlview.json").exists())

    def test_nesting_beyond_the_depth_limit_is_invalid_json_on_every_python(self):
        # HELPER1-4: validate walks never see deep structures (3.12+ parses far deeper than the recursion limit).
        # Deep inputs are written as raw text: before Python 3.12, json.loads/json.dumps of 1500+
        # levels raise RecursionError in the test itself, while the helper must still answer.
        def with_raw(doc, key, raw):
            return json.dumps({**doc, key: "__RAW__"}).replace('"__RAW__"', raw)
        for depth in (65, 1500, 5000):
            with self.subTest(depth=depth):
                draft = self.root / "draft.json"
                draft.write_text(with_raw(document(), "junk", "[" * (depth - 1) + "]" * (depth - 1)), encoding="utf-8")
                code, response = self.run_raw("validate", str(draft), "--workspace", str(self.root))
                self.assertEqual((1, [{"code": "invalid_json", "path": "$", "message": "nesting is too deep"}]), (code, response["errors"]))
        doc = document(); doc["junk"] = json.loads("[" * 62 + "]" * 62)
        code, response = self.run_raw("validate", str(self.write_draft(doc)), "--workspace", str(self.root))
        self.assertEqual(["additional_property"], [e["code"] for e in response["errors"]])
        self.write_draft(document())
        (self.root / "record.json").write_text(with_raw({"id": "n2"}, "label", "[" * 1500 + "]" * 1500), encoding="utf-8")
        code, response = self.run_raw("upsert", "draft.json", "--workspace", str(self.root), "--collection", "nodes", "--record", "record.json")
        self.assertEqual((1, [{"code": "invalid_json", "path": "record", "message": "nesting is too deep"}]), (code, response["errors"]))
        self.assertFalse((self.root / "draft.json.lock").exists())
        # A library caller that skips the parse guard still gets errors, never a RecursionError.
        deep = "x"
        for _ in range(5000):
            deep = [deep]
        doc = document(); doc["title"] = deep
        self.assertIn("type", {e["code"] for e in self.validate(doc)})

    def test_publish_refuses_an_oversize_existing_artifact(self):
        # HELPER1-5: the viewer calls an artifact over 2 MiB unreadable; the helper refuses to publish over it.
        published = self.root / "workflow.mlview.json"
        big = document(); big["coverage"]["limitations"] = ["x" * 1500] * 2100
        published.write_text(json.dumps(big), encoding="utf-8")
        self.assertGreater(published.stat().st_size, artifact.MAX_DOCUMENT)
        before = published.read_bytes()
        second = document(); second["revision"] = {"id": "r2", "parent": "r1"}
        result = self.run_cli("publish", second)
        self.assertEqual([{"code": "published_invalid", "path": "workflow.mlview.json", "message": "existing artifact exceeds 2097152 bytes"}], json.loads(result.stdout)["errors"])
        self.assertEqual(before, published.read_bytes())

    def test_publish_refuses_an_artifact_without_a_valid_revision_id(self):
        # HELPER1-6: consistent published_invalid, never an overwrite or an impossible revision_conflict.
        published = self.root / "workflow.mlview.json"
        for revision in ({"id": None}, {"id": 5}, {"id": "bad id"}, {}, None, "r1"):
            with self.subTest(revision=revision):
                existing = document(); existing["revision"] = revision
                published.write_text(json.dumps(existing), encoding="utf-8")
                before = published.read_bytes()
                result = self.run_cli("publish", document())
                self.assertEqual([{"code": "published_invalid", "path": "workflow.mlview.json", "message": "existing artifact has no valid revision.id"}], json.loads(result.stdout)["errors"])
                self.assertEqual(before, published.read_bytes())
        published.write_text("[" * 100 + "]" * 100, encoding="utf-8")
        self.assertEqual("existing artifact is invalid", json.loads(self.run_cli("publish", document()).stdout)["errors"][0]["message"])

    def test_nan_and_infinity_are_not_json_in_an_artifact_or_a_draft(self):
        # SPECDOCS2-3: json.loads accepts NaN, Infinity and -Infinity; the viewer's JSON.parse does
        # not, and refuses Refine saying this helper will not publish over such a file.
        self.assertEqual(0, self.run_cli("publish", document()).returncode)
        published = self.root / "workflow.mlview.json"
        valid = published.read_text(encoding="utf-8")
        second = document(); second["revision"] = {"id": "r2", "parent": "r1"}
        for constant in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(artifact=constant):
                published.write_text(valid.replace("{", '{"x": ' + constant + ",", 1), encoding="utf-8")
                before = published.read_bytes()
                result = self.run_cli("publish", second)
                self.assertEqual(1, result.returncode)
                self.assertEqual([{"code": "published_invalid", "path": "workflow.mlview.json", "message": "existing artifact is invalid"}], json.loads(result.stdout)["errors"])
                self.assertEqual(before, published.read_bytes())
            with self.subTest(draft=constant):
                draft = self.root / "draft.json"
                draft.write_text(json.dumps(document()).replace('"line": 1', '"line": ' + constant, 1), encoding="utf-8")
                code, response = self.run_raw("validate", str(draft), "--workspace", str(self.root))
                self.assertEqual((1, [{"code": "invalid_json", "path": "$", "message": f"{constant} is not valid JSON"}]), (code, response["errors"]))
        with self.assertRaises(ValueError):
            artifact._parse(b'{"x": NaN}')

    def test_aliases_of_mlview_files_are_never_fingerprinted(self):
        # SECURITY1-5: a symlink or hard link to the artifact is an MLView file under another name.
        self.assertEqual(0, self.run_cli("publish", document()).returncode)
        published = self.root / "workflow.mlview.json"
        links = []
        try:
            os.symlink("workflow.mlview.json", self.root / "notes.json"); links.append("notes.json")
        except (OSError, NotImplementedError):
            pass
        try:
            os.link(published, self.root / "copy.json"); links.append("copy.json")
        except (OSError, NotImplementedError):
            pass
        if not links:
            self.skipTest("links are unavailable here")
        second = document(); second["revision"] = {"id": "r2", "parent": "r1"}
        second["coverage"]["inspectedFiles"] += links
        result = self.run_cli("publish", second)
        response = json.loads(result.stdout)
        self.assertEqual(0, result.returncode, response)
        self.assertEqual([f"coverage.inspectedFiles[{1 + i}]" for i in range(len(links))], [w["path"] for w in response["warnings"]])
        self.assertEqual({"excluded_inspected"}, {w["code"] for w in response["warnings"]})
        self.assertEqual(["train.py"], sorted(json.loads(published.read_text(encoding="utf-8"))["verification"]["files"]))
        # The published revision is not immediately stale.
        code, response = self.run_raw("validate", "workflow.mlview.json", "--workspace", str(self.root))
        self.assertEqual((0, []), (code, response["errors"]))
        if "notes.json" in links:
            self.assertEqual({"excluded_evidence"}, self.codes(document("notes.json", "{")))

    def test_published_at_accepts_any_fraction_length_on_every_python(self):
        # SPECDOCS1-5: fromisoformat accepted only 3 or 6 fraction digits before Python 3.11, so the
        # check must not depend on it. Simulate the old parser to prove that on any interpreter.
        class Pre311Datetime(artifact.datetime):
            @classmethod
            def fromisoformat(cls, value):
                fraction = value.split(".", 1)[1].rstrip("Z").split("+")[0].split("-")[0] if "." in value else ""
                if fraction and len(fraction) not in (3, 6): raise ValueError("pre-3.11 fraction rule")
                return artifact.datetime.fromisoformat(value)
        for value in ("2026-09-25T00:00:00.5Z", "2026-09-25T00:00:00.12Z", "2026-09-25T00:00:00.1234Z", "2026-09-25T00:00:00.1234567+01:00"):
            with self.subTest(value=value), mock.patch.object(artifact, "datetime", Pre311Datetime):
                doc = document(); doc["verification"] = {"files": {}, "publishedAt": value}
                self.assertEqual(set(), self.codes(doc))
        for value in ("0000-01-01T00:00:00Z", "2026-09-25T00:00:00+24:00", "２026-09-25T00:00:00Z", "2026-09-25T00:00:00Z\n", "2026-02-30T00:00:00Z"):
            with self.subTest(value=value):
                doc = document(); doc["verification"] = {"files": {}, "publishedAt": value}
                self.assertEqual({"format"}, self.codes(doc))

    def test_published_at_profile_is_stricter_than_rfc3339(self):
        # Campaign 2 SPEC 7.1 (conformance shape-016 to shape-018): uppercase T and Z only, no leap
        # second, any fraction length; the schema layer and the extension share this profile.
        for value, valid in (("2026-09-25T10:00:00.123456789Z", True), ("2026-09-25T10:00:00z", False),
                             ("2026-09-25t10:00:00Z", False), ("2026-06-30T23:59:60Z", False),
                             ("2026-09-25T10:00:00+05:59", True), ("2026-09-25T10:00:00+05:60", False)):
            with self.subTest(value=value):
                doc = document(); doc["verification"] = {"files": {}, "publishedAt": value}
                self.assertEqual(set() if valid else {"format"}, self.codes(doc))


if __name__ == "__main__": unittest.main()
