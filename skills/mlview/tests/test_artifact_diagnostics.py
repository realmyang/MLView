"""Helper diagnostics, the read-only excerpt command, non-blocking hygiene warnings, the basis
summary and multi-record upsert (Campaign 3 shakedown issues 2, 3, 5, 7 and 11).

These are local unit tests of skills/mlview/scripts/artifact.py. They are not semantic accuracy,
human review or live-host validation.
"""
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
SPEC = importlib.util.spec_from_file_location("mlview_artifact_diagnostics", HELPER)
artifact = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(artifact)

SOURCE = "import torch\n\ndef train(model, data):\n    for batch in data:\n        loss = model(batch)\n        loss.backward()\n    return model\n"


def document(evidence=None, nodes=None, edges=None, findings=None, inspected=("train.py",)):
    evidence = evidence if evidence is not None else [{"id": "ev", "file": "train.py", "line": 3, "endLine": 3, "quote": "def train(model, data):"}]
    return {
        "workflowVersion": "1.0", "title": "Training",
        "producer": {"kind": "host-llm", "host": "codex"},
        "revision": {"id": "r1"},
        "request": {"question": "Explain training", "scope": "train.py"},
        "phases": [{"id": "p", "label": "Train"}],
        "nodes": nodes if nodes is not None else [{"id": "n", "label": "Train", "phase": "p", "basis": "observed", "evidence": ["ev"]}],
        "edges": edges if edges is not None else [], "findings": findings if findings is not None else [], "evidence": evidence,
        "coverage": {"status": "scoped", "summary": "Inspected entrypoint", "inspectedFiles": list(inspected), "limitations": []},
    }


def node(node_id, evidence=("ev",), **extra):
    return {"id": node_id, "label": node_id.title(), "phase": "p", "basis": "observed", "evidence": list(evidence), **extra}


def edge(edge_id, source, target, **extra):
    return {"id": edge_id, "source": source, "target": target, "label": "next", "basis": "observed", "evidence": ["ev"], **extra}


class HelperCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        (self.root / "train.py").write_text(SOURCE, encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def errors(self, doc):
        return artifact.validate(doc, self.root)[0]

    def warnings(self, doc):
        found = []
        errors = artifact.validate(doc, self.root, warnings=found)[0]
        self.assertEqual([], errors)
        return found

    def run_main(self, *args):
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = artifact.main(list(args))
        self.assertEqual("", stderr.getvalue())
        lines = stdout.getvalue().splitlines()
        self.assertEqual(1, len(lines), stdout.getvalue())
        self.assertNotIn(str(self.root), stdout.getvalue())
        return code, json.loads(lines[0])

    def run_cli(self, *args):
        result = subprocess.run([sys.executable, str(HELPER), *args], text=True, capture_output=True)
        self.assertEqual("", result.stderr)
        self.assertNotIn(str(self.root), result.stdout)
        return result.returncode, json.loads(result.stdout)

    def write(self, rel, data):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes): path.write_bytes(data)
        else: path.write_text(data, encoding="utf-8")
        return path


class QuoteMismatchTests(HelperCase):
    def mismatch(self, doc, index=0):
        found = [e for e in self.errors(doc) if e["code"] == "quote_mismatch" and e["path"] == f"evidence[{index}].quote"]
        self.assertEqual(1, len(found), self.errors(doc))
        return found[0]

    def test_error_names_the_record_range_and_line_counts(self):
        error = self.mismatch(document([{"id": "ev-loop", "file": "train.py", "line": 4, "endLine": 6,
                                         "quote": "    for batch in data:\n        loss = model(batch)\n        loss.backward"}]))
        self.assertEqual(("ev-loop", "train.py", 4, 6, 3, 3), tuple(error[k] for k in ("id", "file", "line", "endLine", "citedLines", "quoteLines")))
        self.assertNotIn("cell", error)
        self.assertEqual({"rangeLine": 3, "line": 6, "column": 22, "startColumn": 1, "quote": "        loss.backward", "cited": "        loss.backward()"}, error["difference"])
        self.assertTrue(error["message"].startswith('quote does not exactly match the cited lines of evidence "ev-loop" (train.py, lines 4-6). '), error["message"])
        self.assertIn("First difference at line 3 of the quote (source line 6), column 22", error["message"])

    def test_wrong_range_points_to_the_unique_place_the_quote_occurs(self):
        # Right text, wrong line numbers: the most common shakedown mismatch.
        error = self.mismatch(document([{"id": "ev", "file": "train.py", "line": 3, "endLine": 4,
                                         "quote": "        loss = model(batch)\n        loss.backward()"}]))
        self.assertEqual({"line": 5, "endLine": 6}, error["foundAt"])
        self.assertIn("The quoted text occurs exactly once, at lines 5-6: if that is the code you meant, set line and endLine to that range.", error["message"])

    def test_no_location_hint_when_the_quote_occurs_nowhere_or_more_than_once(self):
        self.write("twice.py", "x = 1\ny = 2\nx = 1\n")
        doc = document([{"id": "ev", "file": "twice.py", "line": 2, "endLine": 2, "quote": "x = 1"}], inspected=("twice.py",))
        self.assertNotIn("foundAt", self.mismatch(doc))
        doc["evidence"][0]["quote"] = "z = 3"
        error = self.mismatch(doc)
        self.assertNotIn("foundAt", error)
        self.assertNotIn("occurs exactly once", error["message"])

    def test_trailing_newline_is_named_and_the_join_convention_stated(self):
        error = self.mismatch(document([{"id": "ev", "file": "train.py", "line": 3, "endLine": 3, "quote": "def train(model, data):\n"}]))
        self.assertEqual({"rangeLine": 2, "line": 4, "column": 1, "startColumn": 1, "quote": "", "cited": None}, error["difference"])
        self.assertEqual((2, 1), (error["quoteLines"], error["citedLines"]))
        self.assertIn("the quote has \"\" where the cited lines have nothing (the cited range has ended)", error["message"])
        self.assertIn("The quote ends with a line break: cited lines are joined with LF and have none after the last line.", error["message"])
        self.assertIn("The quote has 2 lines; the cited range has 1.", error["message"])
        self.assertNotIn("foundAt", error, "line 4 is not empty, so the quote's lines occur nowhere")
        # Line 2 is empty, so "import torch\n" does occur, once, at lines 1-2.
        error = self.mismatch(document([{"id": "ev", "file": "train.py", "line": 1, "endLine": 1, "quote": "import torch\n"}]))
        self.assertEqual({"line": 1, "endLine": 2}, error["foundAt"])
        self.assertIn("The quote ends with a line break", error["message"])

    def test_a_range_ending_on_an_empty_line_the_quote_omits(self):
        error = self.mismatch(document([{"id": "ev", "file": "train.py", "line": 1, "endLine": 2, "quote": "import torch"}]))
        self.assertIn("The cited range ends on an empty line that the quote leaves out; end the range one line earlier.", error["message"])
        self.assertEqual({"rangeLine": 2, "line": 2, "column": 1, "startColumn": 1, "quote": None, "cited": ""}, error["difference"])

    def test_invisible_characters_are_visible_in_both_sides(self):
        self.write("ws.py", "a = 1\t\nb = 2  \n")
        doc = document([{"id": "ev", "file": "ws.py", "line": 1, "endLine": 2, "quote": "a = 1\nb = 2"}], inspected=("ws.py",))
        error = self.mismatch(doc)
        self.assertEqual({"rangeLine": 1, "line": 1, "column": 6, "startColumn": 1, "quote": "a = 1", "cited": "a = 1\t"}, error["difference"])
        self.assertIn('where the cited lines have "a = 1\\t"', error["message"])
        self.assertIn("Only whitespace differs", error["message"])
        # Carriage returns in the quote never match: the source is read with CRLF as LF.
        doc["evidence"][0]["quote"] = "a = 1\t\r\nb = 2  "
        error = self.mismatch(doc)
        self.assertEqual("a = 1\t\r", error["difference"]["quote"])
        self.assertIn("carriage return", error["message"])
        self.assertIn('"a = 1\\t\\r"', error["message"])

    def test_a_bom_inside_a_quote_is_shown_escaped(self):
        doc = document([{"id": "ev", "file": "train.py", "line": 3, "endLine": 3, "quote": "\ufeffdef train(model, data):"}])
        error = self.mismatch(doc)
        self.assertEqual("\ufeffdef train(model, data):", error["difference"]["quote"])
        self.assertIn("\\ufeff", json.dumps(error))
        # On line 1 a leading BOM is accepted with or without it, so it is never reported there.
        self.write("bom.py", "\ufeffimport os\nx = 1\n".encode("utf-8"))
        doc = document([{"id": "ev", "file": "bom.py", "line": 1, "endLine": 1, "quote": "\ufeffimport sys"}], inspected=("bom.py",))
        self.assertEqual({"rangeLine": 1, "line": 1, "column": 8, "startColumn": 1, "quote": "import sys", "cited": "import os"}, self.mismatch(doc)["difference"])

    def test_messages_stay_bounded_for_long_lines(self):
        self.write("long.py", "v = [" + "1, " * 5000 + "]\n")
        quote = "v = [" + "1, " * 2500 + "2, " + "1, " * 2499 + "]"
        doc = document([{"id": "ev", "file": "long.py", "line": 1, "endLine": 1, "quote": quote}], inspected=("long.py",))
        error = self.mismatch(doc)
        self.assertEqual(5 + 3 * 2500 + 1, error["difference"]["column"])
        self.assertLessEqual(len(error["difference"]["quote"]), artifact.QUOTE_WINDOW)
        self.assertLess(len(json.dumps(error)), 1500)

    def test_notebook_mismatch_names_the_cell_and_searches_only_that_cell(self):
        notebook = {"cells": [{"cell_type": "code", "source": ["x = 1\n", "fit(x)\n", "y = 2"]}, {"cell_type": "code", "source": "fit(x)"}],
                    "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
        self.write("flow.ipynb", json.dumps(notebook))
        doc = document([{"id": "ev", "file": "flow.ipynb", "cell": 0, "line": 1, "endLine": 1, "quote": "fit(x)"}], inspected=("flow.ipynb",))
        error = self.mismatch(doc)
        self.assertEqual(0, error["cell"])
        self.assertEqual({"line": 2, "endLine": 2}, error["foundAt"], "cell 1 also holds fit(x), but only cell 0 is searched")
        self.assertIn("(flow.ipynb cell 0, line 1)", error["message"])
        self.assertIn("at line 2 of this cell", error["message"])

    def test_non_string_quote_is_reported_with_the_record(self):
        doc = document([{"id": "ev", "file": "train.py", "line": 3, "endLine": 3, "quote": 7}])
        error = self.mismatch(doc)
        self.assertTrue(error["message"].endswith("The quote must be a string."), error["message"])
        self.assertNotIn("difference", error)

    def test_range_error_names_the_largest_valid_line(self):
        doc = document([{"id": "ev", "file": "train.py", "line": 3, "endLine": 30, "quote": "x"}])
        error = [e for e in self.errors(doc) if e["code"] == "range"][0]
        self.assertEqual(8, error["maxLine"])
        self.assertIn("1 <= line <= endLine <= 8", error["message"])

    def test_the_quote_is_still_checked_after_an_unexpected_cell(self):
        doc = document([{"id": "ev", "file": "train.py", "cell": 0, "line": 3, "endLine": 3, "quote": "def train(model, data)"}])
        self.assertEqual(["unexpected_cell", "quote_mismatch"], [e["code"] for e in self.errors(doc)])
        doc["evidence"][0]["quote"] = "def train(model, data):"
        self.assertEqual(["unexpected_cell"], [e["code"] for e in self.errors(doc)])


class ReferenceDetailTests(HelperCase):
    def test_unknown_references_name_the_value_and_index(self):
        doc = document(nodes=[node("n", evidence=("ev", "ev-missing")), node("m")], edges=[edge("e", "n", "ghost")],
                       findings=[{"id": "f", "title": "T", "message": "M", "severity": "low", "nodeIds": ["n", "nope"], "basis": "observed", "evidence": ["ev"], "counterEvidence": [5]}])
        found = {(e["code"], e["path"]): e for e in self.errors(doc)}
        self.assertEqual({"code": "reference", "path": "nodes[0].evidence[1]", "message": 'unknown evidence ID "ev-missing"', "index": 1, "value": "ev-missing"}, found[("reference", "nodes[0].evidence[1]")])
        self.assertEqual({"code": "reference", "path": "edges[0].target", "message": 'unknown node ID "ghost"', "value": "ghost"}, found[("reference", "edges[0].target")])
        self.assertEqual('unknown node ID "nope"', found[("reference", "findings[0].nodeIds[1]")]["message"])
        self.assertEqual({"code": "reference", "path": "findings[0].counterEvidence[0]", "message": "unknown evidence ID: expected an ID string, found a number", "index": 0},
                         found[("reference", "findings[0].counterEvidence[0]")])
        self.assertEqual("references must be unique strings", found[("duplicate_reference", "findings[0].counterEvidence")]["message"])

    def test_unknown_phase_names_the_value(self):
        doc = document(nodes=[node("n", phase="later")])
        error = [e for e in self.errors(doc) if e["code"] == "reference"][0]
        self.assertEqual(("nodes[0].phase", 'unknown phase ID "later"', "later"), (error["path"], error["message"], error["value"]))

    def test_duplicates_name_the_value_and_both_positions(self):
        doc = document(nodes=[node("n", evidence=("ev", "ev")), node("n")])
        found = {e["code"]: e for e in self.errors(doc)}
        self.assertEqual({"code": "duplicate_reference", "path": "nodes[0].evidence[1]", "index": 1, "firstIndex": 0, "value": "ev",
                          "message": 'evidence ID "ev" is already listed at nodes[0].evidence[0]; list each ID once'}, found["duplicate_reference"])
        self.assertEqual({"code": "duplicate_id", "path": "nodes[1].id", "firstIndex": 0, "value": "n",
                          "message": 'ID "n" is already used by nodes[0]; IDs are unique within a collection'}, found["duplicate_id"])


class DuplicateMemberTests(HelperCase):
    def test_other_problems_surface_in_the_same_round(self):
        doc = document([{"id": "ev", "file": "train.py", "line": 3, "endLine": 3, "quote": "def train(model, data)"}])
        text = json.dumps(doc)
        text = text.replace('"findings": []', '"findings": [], "findings": []').replace('"label": "Train", "phase"', '"label": "A", "label": "Train", "phase"', 1)
        draft = self.write("draft.json", text)
        code, response = self.run_cli("validate", str(draft), "--workspace", str(self.root))
        self.assertEqual(1, code)
        continued = "; the rest of the draft was validated with its last value, as JSON.parse reads it"
        self.assertEqual([
            {"code": "invalid_json", "path": "$", "member": "nodes[0].label", "message": "duplicate JSON member: label (at nodes[0].label)" + continued},
            {"code": "invalid_json", "path": "$", "member": "findings", "message": "duplicate JSON member: findings" + continued},
        ], response["errors"][:2])
        self.assertEqual(["quote_mismatch"], [e["code"] for e in response["errors"][2:]])

    def test_a_repeated_member_alone_still_fails_and_is_never_published(self):
        draft = self.write("draft.json", json.dumps(document()).replace('"edges": []', '"edges": [], "edges": []'))
        for command in ("validate", "publish"):
            with self.subTest(command=command):
                code, response = self.run_cli(command, str(draft), "--workspace", str(self.root))
                self.assertEqual(1, code)
                self.assertEqual(["invalid_json"], [e["code"] for e in response["errors"]])
        self.assertFalse((self.root / "workflow.mlview.json").exists())

    def test_many_repeats_are_listed_up_to_a_bound(self):
        members = ", ".join('"k": %d' % i for i in range(30))
        draft = self.write("draft.json", "{%s}" % members)
        code, response = self.run_main("validate", str(draft), "--workspace", str(self.root))
        repeats = [e for e in response["errors"] if e["code"] == "invalid_json"]
        self.assertEqual(artifact.MAX_DUPLICATE_MEMBERS + 1, len(repeats))
        self.assertEqual("9 more duplicate JSON members are not listed", repeats[-1]["message"])

    def test_upsert_and_the_strict_parser_still_refuse_repeats(self):
        with self.assertRaises(ValueError):
            artifact._parse(b'{"a": 1, "a": 2}')
        draft = self.write("draft.json", json.dumps(document()).replace('"edges": []', '"edges": [], "edges": []'))
        self.write("record.json", json.dumps(node("n")))
        code, response = self.run_main("upsert", "draft.json", "--workspace", str(self.root), "--collection", "nodes", "--record", "record.json")
        self.assertEqual(1, code)
        self.assertEqual([{"code": "invalid_json", "path": "$", "member": "edges", "message": "duplicate JSON member: edges"}], response["errors"])
        self.assertIn('"edges": [], "edges": []', draft.read_text(encoding="utf-8"))


class ExcerptTests(HelperCase):
    def excerpt(self, *args, workspace=None):
        return self.run_main("excerpt", *args, "--workspace", str(workspace or self.root))

    def assert_accepted(self, record, rel):
        """The printed record validates exactly as printed."""
        doc = document([record], nodes=[node("n", evidence=(record["id"],))], inspected=(rel,))
        self.assertEqual([], self.errors(doc))

    def test_plain_file_range_and_single_line(self):
        code, record = self.excerpt("train.py", "--lines", "4-6", "--id", "ev-loop")
        self.assertEqual(0, code)
        self.assertEqual({"id": "ev-loop", "file": "train.py", "line": 4, "endLine": 6,
                          "quote": "    for batch in data:\n        loss = model(batch)\n        loss.backward()"}, record)
        self.assertEqual(["id", "file", "line", "endLine", "quote"], list(record))
        self.assert_accepted(record, "train.py")
        code, record = self.excerpt("train.py", "--lines", "3")
        self.assertEqual({"id": "ev-train.py-3", "file": "train.py", "line": 3, "endLine": 3, "quote": "def train(model, data):"}, record)
        self.assert_accepted(record, "train.py")

    def test_crlf_bom_tabs_and_trailing_spaces_are_read_as_validate_reads_them(self):
        self.write("crlf.py", b"\xef\xbb\xbfa = 1\r\n\tb = 2  \r\nc = 3\rd = 4\r\n")
        code, record = self.excerpt("crlf.py", "--lines", "1-4")
        self.assertEqual(0, code)
        self.assertEqual("a = 1\n\tb = 2  \nc = 3\nd = 4", record["quote"])
        self.assert_accepted(record, "crlf.py")
        code, record = self.excerpt("crlf.py", "--lines", "4-5")
        self.assertEqual("d = 4\n", record["quote"], "the empty line after the final newline is addressable, as in validate")
        self.assert_accepted(record, "crlf.py")

    def test_notebook_cells_use_zero_based_cells_and_cell_lines(self):
        notebook = {"cells": [{"cell_type": "markdown", "source": ["# Title\n"]}, {"cell_type": "code", "source": ["x = load()\n", "fit(x)\n", "y = 2"]}],
                    "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
        self.write("nb/flow.ipynb", json.dumps(notebook))
        code, record = self.excerpt("nb/flow.ipynb", "--lines", "2-3", "--cell", "1")
        self.assertEqual({"id": "ev-nb-flow.ipynb-c1-2-3", "file": "nb/flow.ipynb", "cell": 1, "line": 2, "endLine": 3, "quote": "fit(x)\ny = 2"}, record)
        self.assertEqual(["id", "file", "cell", "line", "endLine", "quote"], list(record))
        self.assert_accepted(record, "nb/flow.ipynb")
        code, response = self.excerpt("nb/flow.ipynb", "--lines", "1")
        self.assertEqual((1, [("notebook_cell", "--cell")]), (code, [(e["code"], e["path"]) for e in response["errors"]]))
        code, response = self.excerpt("nb/flow.ipynb", "--lines", "1", "--cell", "9")
        self.assertEqual([("notebook_cell", "--cell")], [(e["code"], e["path"]) for e in response["errors"]])
        code, response = self.excerpt("train.py", "--lines", "1", "--cell", "0")
        self.assertEqual((1, [("unexpected_cell", "--cell")]), (code, [(e["code"], e["path"]) for e in response["errors"]]))

    def test_out_of_range_and_malformed_ranges(self):
        for lines in ("0", "7-3", "5-99", "100"):
            with self.subTest(lines=lines):
                code, response = self.excerpt("train.py", "--lines", lines)
                self.assertEqual(1, code)
                self.assertEqual([{"code": "range", "path": "--lines", "maxLine": 8, "message": "line range is invalid for the cited source: need 1 <= START <= END <= 8"}], response["errors"])
        for lines in ("", "a-b", "3:5", "3-", "-3", "1,2"):
            with self.subTest(lines=lines):
                code, response = self.excerpt("train.py", f"--lines={lines}")
                self.assertEqual([("arguments", "--lines")], [(e["code"], e["path"]) for e in response["errors"]])
        code, response = self.excerpt("train.py")
        self.assertEqual([("arguments", "--lines")], [(e["code"], e["path"]) for e in response["errors"]])
        code, response = self.excerpt("train.py", "--lines", "3", "--id", "bad id")
        self.assertEqual([("id", "--id")], [(e["code"], e["path"]) for e in response["errors"]])

    def test_paths_are_confined_like_evidence_paths(self):
        outside = self.root.parent / (self.root.name + "-outside.py")
        outside.write_text("secret\n", encoding="utf-8")
        try:
            for value, code in ((str(outside), "path_outside_workspace"), ("../" + outside.name, "path_outside_workspace"), ("./train.py", "path_outside_workspace"),
                                ("missing.py", "path_outside_workspace"), ("C:/train.py", "invalid_path"), ("sub\\train.py", "invalid_path")):
                with self.subTest(value=value):
                    status, response = self.excerpt(value, "--lines", "1")
                    self.assertEqual((1, [(code, "file")]), (status, [(e["code"], e["path"]) for e in response["errors"]]))
                    self.assertNotIn("secret", json.dumps(response))
                    hinted = value == str(outside) or value.startswith("C:")
                    self.assertEqual(hinted, response["errors"][0]["message"].endswith("; pass the path relative to --workspace, as evidence[].file records it"))
        finally:
            outside.unlink()
        (self.root / "folder").mkdir()
        status, response = self.excerpt("folder", "--lines", "1")
        self.assertEqual([("invalid_path", "file")], [(e["code"], e["path"]) for e in response["errors"]])

    def test_mlview_files_are_refused(self):
        for rel in (".mlview/llm/run/draft.json", "workflow.mlview.json", "notes.draft.json", ".agents/skills/mlview/SKILL.md", ".Claude/Skills/MLView/SKILL.md"):
            with self.subTest(rel=rel):
                self.write(rel, "{}\n")
                status, response = self.excerpt(rel, "--lines", "1")
                self.assertEqual((1, [("excluded_evidence", "file")]), (status, [(e["code"], e["path"]) for e in response["errors"]]))

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_symlinks_inside_outside_and_onto_mlview_files(self):
        (self.root / "alias.py").symlink_to(self.root / "train.py")
        status, record = self.excerpt("alias.py", "--lines", "1")
        self.assertEqual((0, "alias.py", "import torch"), (status, record["file"], record["quote"]), "a symlink inside the workspace keeps its own path, as in validate")
        self.assert_accepted(record, "alias.py")
        outside = self.root.parent / (self.root.name + "-target.py")
        outside.write_text("secret\n", encoding="utf-8")
        try:
            (self.root / "escape.py").symlink_to(outside)
            status, response = self.excerpt("escape.py", "--lines", "1")
            self.assertEqual([("path_outside_workspace", "file")], [(e["code"], e["path"]) for e in response["errors"]])
        finally:
            outside.unlink()
        self.write(".mlview/notes.py", "x = 1\n")
        (self.root / "notes.py").symlink_to(self.root / ".mlview" / "notes.py")
        status, response = self.excerpt("notes.py", "--lines", "1")
        self.assertEqual([("excluded_evidence", "file")], [(e["code"], e["path"]) for e in response["errors"]])

    def test_large_non_utf8_and_over_long_sources(self):
        self.write("big.py", "x = 1\n" * 20)
        with mock.patch.object(artifact, "MAX_SOURCE", 64):
            status, response = self.excerpt("big.py", "--lines", "1")
        self.assertEqual((1, [("source_too_large", "file")]), (status, [(e["code"], e["path"]) for e in response["errors"]]))
        self.write("latin1.py", "caf\xe9 = 1\n".encode("latin-1"))
        status, response = self.excerpt("latin1.py", "--lines", "1")
        self.assertEqual([("source_encoding", "file")], [(e["code"], e["path"]) for e in response["errors"]])
        self.write("wide.py", ("y" * 1000 + "\n") * 20)
        status, response = self.excerpt("wide.py", "--lines", "1-17")
        self.assertEqual([("limit", "--lines")], [(e["code"], e["path"]) for e in response["errors"]])
        status, record = self.excerpt("wide.py", "--lines", "1-15")
        self.assertEqual(0, status)
        self.assert_accepted(record, "wide.py")

    def test_default_ids_are_valid_and_bounded(self):
        rel = "/".join(["deep"] * 60) + "/train file (copy).py"
        self.write(rel, "a\nb\n")
        status, record = self.excerpt(rel, "--lines", "1-2")
        self.assertEqual(0, status)
        self.assertTrue(artifact._id(record["id"]), record["id"])
        self.assertTrue(record["id"].startswith("ev-") and record["id"].endswith("-train-file-copy-.py-1-2"), record["id"])
        self.assert_accepted(record, rel)

    def test_excerpt_is_read_only_and_prints_one_json_line(self):
        before = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*"))
        code, record = self.run_cli("excerpt", "train.py", "--lines", "1-2", "--workspace", str(self.root))
        self.assertEqual(0, code)
        self.assertEqual("import torch\n", record["quote"])
        self.assertEqual(before, sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*")))


class WarningTests(HelperCase):
    def test_a_clean_document_has_no_warnings_and_a_single_node_is_not_isolated(self):
        self.assertEqual([], self.warnings(document()))
        doc = document(nodes=[node("a"), node("b"), node("group", evidence=()), node("child", parent="group")], edges=[edge("e", "a", "b")])
        self.assertEqual([], self.warnings(doc))

    def test_each_hygiene_warning(self):
        evidence = [{"id": "ev", "file": "train.py", "line": 3, "endLine": 3, "quote": "def train(model, data):"},
                    {"id": "ev-unused", "file": "train.py", "line": 1, "endLine": 1, "quote": "import torch"}]
        self.write("long.py", "x = 1\n" * 70)
        evidence.append({"id": "ev-wide", "file": "long.py", "line": 1, "endLine": 61, "quote": "\n".join(["x = 1"] * 61)})
        nodes = [node("a", evidence=("ev", "ev-wide")), node("b"), node("alone")]
        edges = [edge("e1", "a", "b"), edge("e-self", "b", "b"), edge("e-loop", "a", "a", kind="Loop")]
        findings = [{"id": "f", "title": "T", "message": "M", "severity": "low", "nodeIds": ["a"], "basis": "inferred", "evidence": ["ev"], "counterEvidence": ["ev"]}]
        doc = document(evidence, nodes, edges, findings, inspected=("train.py", "long.py", "train.py"))
        found = self.warnings(doc)
        self.assertEqual([
            ("unreferenced_evidence", "evidence[1]"), ("isolated_node", "nodes[2]"), ("self_edge", "edges[1]"),
            ("wide_evidence", "evidence[2]"), ("evidence_overlap", "findings[0].counterEvidence[0]"), ("duplicate_inspected", "coverage.inspectedFiles[2]"),
        ], [(w["code"], w["path"]) for w in found])
        messages = {w["code"]: w["message"] for w in found}
        self.assertEqual('evidence "ev-unused" is not cited by any node, edge or finding; cite it where it supports a claim, or remove it', messages["unreferenced_evidence"])
        self.assertEqual('node "alone" has no edge, parent or child; connect it, nest it under a group node, or remove it', messages["isolated_node"])
        self.assertIn('edge "e-self" connects node "b" to itself; give it kind "loop"', messages["self_edge"])
        self.assertIn('evidence "ev-wide" spans 61 lines (more than 60)', messages["wide_evidence"])
        self.assertIn('finding "f" lists evidence "ev" in both evidence and counterEvidence', messages["evidence_overlap"])
        self.assertEqual('"train.py" is already listed at coverage.inspectedFiles[0]; list each file once', messages["duplicate_inspected"])
        self.assertTrue(all(set(w) == {"code", "path", "message"} for w in found))

    def test_sixty_lines_is_not_wide(self):
        self.write("long.py", "x = 1\n" * 70)
        doc = document([{"id": "ev", "file": "long.py", "line": 5, "endLine": 64, "quote": "\n".join(["x = 1"] * 60)}], inspected=("long.py",))
        self.assertEqual([], self.warnings(doc))

    def test_each_code_is_capped_with_a_count(self):
        evidence = [{"id": "ev", "file": "train.py", "line": 3, "endLine": 3, "quote": "def train(model, data):"}]
        evidence += [{"id": f"ev-{i:02d}", "file": "train.py", "line": 1, "endLine": 1, "quote": "import torch"} for i in range(13)]
        found = self.warnings(document(evidence))
        self.assertEqual(artifact.WARNING_CAP + 1, len(found))
        self.assertEqual([f"evidence[{i}]" for i in range(1, 11)] + ["evidence"], [w["path"] for w in found])
        self.assertEqual("3 more uncited evidence records are not listed (13 in all)", found[-1]["message"])
        self.assertEqual(found, self.warnings(document(evidence)), "deterministic")

    def test_warnings_never_change_validity_exit_codes_or_publication(self):
        doc = document(nodes=[node("a"), node("b")], evidence=[{"id": "ev", "file": "train.py", "line": 3, "endLine": 3, "quote": "def train(model, data):"},
                                                                {"id": "ev-2", "file": "train.py", "line": 1, "endLine": 1, "quote": "import torch"}])
        draft = self.write("draft.json", json.dumps(doc))
        code, response = self.run_cli("validate", str(draft), "--workspace", str(self.root))
        self.assertEqual((0, True, []), (code, response["ok"], response["errors"]))
        self.assertEqual(["unreferenced_evidence", "isolated_node", "isolated_node"], [w["code"] for w in response["warnings"]])
        code, response = self.run_cli("publish", str(draft), "--workspace", str(self.root))
        self.assertEqual((0, True), (code, response["ok"]))
        self.assertEqual(["unreferenced_evidence", "isolated_node", "isolated_node"], [w["code"] for w in response["warnings"]])
        self.assertTrue((self.root / "workflow.mlview.json").exists())

    def test_warnings_are_not_computed_for_an_invalid_document(self):
        doc = document(nodes=[node("a"), node("b", phase="missing")])
        found = []
        errors = artifact.validate(doc, self.root, warnings=found)[0]
        self.assertEqual(["reference"], [e["code"] for e in errors])
        self.assertEqual([], found)
        draft = self.write("draft.json", json.dumps(doc))
        code, response = self.run_cli("validate", str(draft), "--workspace", str(self.root))
        self.assertEqual((1, False), (code, "warnings" in response))


class BasisSummaryTests(HelperCase):
    def test_validate_reports_basis_counts(self):
        nodes = [node("a"), node("b", basis="inferred"), node("c", basis="unresolved", evidence=())]
        edges = [edge("e1", "a", "b"), edge("e2", "b", "c", basis="inferred")]
        findings = [{"id": "f", "title": "T", "message": "M", "severity": "low", "nodeIds": [], "basis": "unresolved", "evidence": []}]
        draft = self.write("draft.json", json.dumps(document(nodes=nodes, edges=edges, findings=findings)))
        code, response = self.run_cli("validate", str(draft), "--workspace", str(self.root))
        self.assertEqual(0, code, response)
        self.assertEqual({"nodes": {"observed": 1, "inferred": 1, "unresolved": 1}, "edges": {"observed": 1, "inferred": 1, "unresolved": 0},
                          "findings": {"observed": 0, "inferred": 0, "unresolved": 1}}, response["basis"])
        code, response = self.run_cli("publish", str(draft), "--workspace", str(self.root))
        self.assertNotIn("basis", response, "the summary belongs to validate output")


class MultiRecordUpsertTests(HelperCase):
    def setUp(self):
        super().setUp()
        self.draft = self.write("draft.json", json.dumps(document()))

    def upsert(self, collection, records):
        self.write("records.json", json.dumps(records))
        return self.run_main("upsert", "draft.json", "--workspace", str(self.root), "--collection", collection, "--record", "records.json")

    def test_an_array_is_applied_in_order_and_validated_once(self):
        # A new evidence record and an edit that cites it would each fail alone in the other order;
        # within one collection the batch is applied in order and only the result is validated.
        code, response = self.upsert("evidence", [
            {"id": "ev-loop", "file": "train.py", "line": 4, "endLine": 4, "quote": "    for batch in data:"},
            {"id": "ev", "file": "train.py", "line": 3, "endLine": 3, "quote": "def train(model, data):"},
        ])
        self.assertEqual(0, code, response)
        self.assertEqual({"ok": True, "errors": [], "draft": "draft.json", "collection": "evidence",
                          "records": [{"id": "ev-loop", "action": "inserted"}, {"id": "ev", "action": "replaced"}],
                          "warnings": [{"code": "unreferenced_evidence", "path": "evidence[1]",
                                        "message": 'evidence "ev-loop" is not cited by any node, edge or finding; cite it where it supports a claim, or remove it'}]}, response)
        code, response = self.upsert("nodes", [node("loop", evidence=("ev-loop",)), node("n", evidence=("ev",), label="Train loop"), node("loop", evidence=("ev-loop",), label="Batches")])
        self.assertEqual(0, code, response)
        self.assertEqual([{"id": "loop", "action": "inserted"}, {"id": "n", "action": "replaced"}, {"id": "loop", "action": "replaced"}], response["records"])
        edited = json.loads(self.draft.read_text(encoding="utf-8"))
        self.assertEqual([("n", "Train loop"), ("loop", "Batches")], [(n["id"], n["label"]) for n in edited["nodes"]])

    def test_a_batch_is_all_or_nothing(self):
        before = self.draft.read_bytes()
        code, response = self.upsert("nodes", [node("ok"), node("bad", evidence=("ev-missing",))])
        self.assertEqual(1, code)
        self.assertEqual([("reference", "nodes[2].evidence[0]")], [(e["code"], e["path"]) for e in response["errors"]])
        self.assertEqual(before, self.draft.read_bytes())
        code, response = self.upsert("nodes", [node("ok"), {"label": "no id"}, "text"])
        self.assertEqual([("record", "record[1].id"), ("record", "record[2].id")], [(e["code"], e["path"]) for e in response["errors"]])
        code, response = self.upsert("nodes", [])
        self.assertEqual([{"code": "record", "path": "record", "message": "record file must hold one record object or a non-empty array of records"}], response["errors"])
        self.assertEqual(before, self.draft.read_bytes())
        self.assertFalse((self.root / "draft.json.lock").exists())

    def test_a_single_record_keeps_its_result_fields(self):
        self.write("records.json", json.dumps(node("n", label="Renamed")))
        code, response = self.run_main("upsert", "draft.json", "--workspace", str(self.root), "--collection", "nodes", "--record", "records.json")
        self.assertEqual(0, code, response)
        self.assertEqual({"ok": True, "errors": [], "draft": "draft.json", "collection": "nodes", "id": "n", "action": "replaced",
                          "records": [{"id": "n", "action": "replaced"}]}, response)
        code, response = self.run_main("upsert", "draft.json", "--workspace", str(self.root), "--collection", "nodes", "--record", "records.json")
        self.write("records.json", "[]")
        code, response = self.run_main("upsert", "draft.json", "--workspace", str(self.root), "--collection", "nodes", "--record", "records.json")
        self.assertEqual("record", response["errors"][0]["code"])


if __name__ == "__main__":
    unittest.main()
