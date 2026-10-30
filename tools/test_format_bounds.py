"""Every upper bound of the schema is a bound that the helper applies, at the same value.

The helper does not load the schema: it holds its limits as numbers in its own code. For each
``max*`` keyword of contracts/workflow.schema.json this test makes two copies of a generated test
document, one with the field at the bound and one a single step past it, and gives both to the
schema and to the helper. Each must accept the first and refuse the second, and the helper's message
must name the bound's number. A string is made a second time from characters outside the basic
plane, which count once each.

A bound that the test cannot drive fails it, so a new upper bound in the schema needs a case here.
vscode-extension/test/format-bounds.test.js asks the extension the same questions.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("mlview_conformance_bridge", ROOT / "contracts" / "conformance" / "helper_bridge.py")
bridge = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader
_SPEC.loader.exec_module(bridge)
helper = bridge.load_helper()

SCHEMA = json.loads((ROOT / "contracts" / "workflow.schema.json").read_text(encoding="utf-8"))
WORKSPACE = ROOT / "contracts" / "conformance" / "documents" / "workspace"
BASE = json.loads((WORKSPACE / "d03-two-files.mlview.json").read_text(encoding="utf-8"))
# The keywords of JSON Schema that set an upper bound.
UPPER = ("maxLength", "maxItems", "maxProperties", "maxContains", "maximum", "exclusiveMaximum")
# The record definitions of the schema and the list of the document that holds such records.
RECORDS = {"phase": "phases", "node": "nodes", "edge": "edges", "finding": "findings", "evidence": "evidence"}
# The helper's codes for a value past a bound: a list or an object that is too large, a string that is too long.
PAST_A_BOUND = ("limit", "type")


def bounds(node=SCHEMA, pointer: str = ""):
    """(JSON pointer, value) for every upper bound that the schema states."""
    if isinstance(node, dict):
        for key, value in node.items():
            here = pointer + "/" + key.replace("~", "~0").replace("/", "~1")
            if key in UPPER and isinstance(value, int) and not isinstance(value, bool):
                yield here, value
            else:
                yield from bounds(value, here)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from bounds(value, f"{pointer}/{index}")


def padded(records: list, size: int) -> None:
    """Grow a list of records to the size with copies of one that cites evidence, each under an ID of its own."""
    first = copy.deepcopy(next((record for record in records if record.get("evidence")), records[0]))
    while len(records) < size:
        records.append(dict(copy.deepcopy(first), id=f"pad-{len(records)}"))


def sized(pointer: str, size: int, wide: bool = False):
    """A copy of the base document whose field under the bound has the size, or None for a bound with no case here."""
    doc = copy.deepcopy(BASE)
    text = ("\U0001F600" if wide else "a") * size
    parts = pointer.split("/")[1:]
    keyword = parts[-1]
    if parts[0] == "$defs" and parts[1] in RECORDS and parts[2] == "properties" and len(parts) == 5 and keyword == "maxLength":
        doc[RECORDS[parts[1]]][0][parts[3]] = text
    elif parts[:2] == ["$defs", "refs"] and keyword == "maxItems":
        # The evidence list of the first node, with as many evidence records as it names.
        padded(doc["evidence"], len(doc["evidence"]) + size)
        doc["nodes"][0]["evidence"] = [record["id"] for record in doc["evidence"][-size:]] if size else []
    elif parts[0] == "properties" and len(parts) == 3 and keyword == "maxLength":
        doc[parts[1]] = text
    elif parts[0] == "properties" and len(parts) == 3 and keyword == "maxItems":
        padded(doc[parts[1]], size)
    elif parts[0] == "properties" and parts[2] == "properties" and len(parts) == 5 and keyword == "maxLength":
        doc[parts[1]][parts[3]] = text
    elif parts[0] == "properties" and parts[2] == "properties" and len(parts) == 5 and keyword == "maxItems":
        held = list(doc[parts[1]].get(parts[3], []))
        doc[parts[1]][parts[3]] = held + [f"pad/{index}.py" for index in range(size - len(held))]
    elif parts[0] == "properties" and parts[2] == "properties" and parts[4:] == ["items", "maxLength"]:
        doc[parts[1]][parts[3]] = list(doc[parts[1]].get(parts[3], [])) + [text]
    elif parts[:4] == ["properties", "verification", "properties", "files"] and parts[4:] == ["maxProperties"]:
        files = doc["verification"]["files"]
        digest = next(iter(files.values()))
        files.update({f"pad/{index}.py": digest for index in range(size - len(files))})
    elif parts[:4] == ["properties", "verification", "properties", "files"] and parts[4:] == ["propertyNames", "maxLength"]:
        doc["verification"]["files"][text] = next(iter(doc["verification"]["files"].values()))
    else:
        return None
    return doc


def cases():
    """(pointer, value, wide) for every bound, and a second time for a string of characters outside the basic plane."""
    for pointer, value in sorted(bounds()):
        yield pointer, value, False
        if pointer.endswith("/maxLength"):
            yield pointer, value, True


def helper_refusals(doc: dict) -> list[str]:
    """What the helper says about a value past a bound, as `validate` reports it for a document of the test workspace."""
    return sorted(f"{item['path']}: {item['message']}" for item in helper.validate(doc, WORKSPACE)[0] if item["code"] in PAST_A_BOUND)


class FormatBoundsTests(unittest.TestCase):
    def test_every_upper_bound_of_the_schema_has_a_case(self):
        found = sorted(bounds())
        self.assertEqual([], [pointer for pointer, value in found if sized(pointer, value) is None])
        # The reading is not empty: the schema bounds strings, lists and one object.
        self.assertEqual({"maxLength", "maxItems", "maxProperties"}, {pointer.rsplit("/", 1)[1] for pointer, _ in found})

    def test_a_bound_without_a_case_is_seen(self):
        changed = copy.deepcopy(SCHEMA)
        changed["$defs"]["evidence"]["properties"]["line"]["maximum"] = 100000
        added = sorted(set(bounds(changed)) - set(bounds()))
        self.assertEqual([("/$defs/evidence/properties/line/maximum", 100000)], added)
        self.assertIsNone(sized(*added[0]))

    def test_the_base_document_is_within_every_limit(self):
        self.assertEqual([], helper_refusals(BASE))

    def test_the_schema_accepts_each_bound_and_refuses_one_step_past_it(self):
        validator = bridge.strict_validator()
        if validator is None:
            self.skipTest("jsonschema is not installed (python -m pip install -r requirements-dev.txt)")

        def refused(doc):
            return sorted({error.validator for error in validator.iter_errors(doc) if error.validator in UPPER})

        for pointer, value, wide in cases():
            with self.subTest(bound=pointer, value=value, wide=wide):
                self.assertEqual([], refused(sized(pointer, value, wide)))
                self.assertEqual([pointer.rsplit("/", 1)[1]], refused(sized(pointer, value + 1, wide)))

    def test_the_helper_accepts_each_bound_and_names_it_one_step_past_it(self):
        for pointer, value, wide in cases():
            with self.subTest(bound=pointer, value=value, wide=wide):
                self.assertEqual([], helper_refusals(sized(pointer, value, wide)))
                said = helper_refusals(sized(pointer, value + 1, wide))
                self.assertTrue(any(re.search(rf"(?<!\d){value}(?!\d)", message) for message in said), said)


if __name__ == "__main__":
    unittest.main()
