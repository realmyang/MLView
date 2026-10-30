"""The limits table of docs/format.md prints the numbers that the schema and the code hold.

The table stands between the ``limits`` markers. LIMITS below lists each of its rows under the
text of the row's first cell, with the place every number of the row comes from, in the order
the row prints them: a JSON pointer into contracts/workflow.schema.json, a constant of
skills/mlview/scripts/artifact.py, or a constant of the extension's source. One number may name
several places, which must then agree.

A row fails when a number it prints differs from one of those places, when the words around
its numbers are not the row's words in WORDS, when its last cell does not name exactly the layers
that state its numbers, or when the table and LIMITS do not list the same rows. Every upper bound
that the schema states must be a place of LIMITS.

Whether the helper and the extension apply these bounds is not read here:
tools/test_format_bounds.py and vscode-extension/test/format-bounds.test.js drive each bound.
"""
from __future__ import annotations

import ast
import copy
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = ROOT / "docs" / "format.md"
SCHEMA = ROOT / "contracts" / "workflow.schema.json"
HELPER = ROOT / "skills" / "mlview" / "scripts" / "artifact.py"
EXTENSION = ROOT / "vscode-extension" / "src"
BEGIN, END = "<!-- limits:begin -->", "<!-- limits:end -->"
HEADER = ("Limit on", "Value", "Stated by")
MIB = 1024 * 1024
LAYERS = ("schema", "helper", "extension")
NODE, EDGE, FINDING, EVIDENCE = (f"/$defs/{name}/properties" for name in ("node", "edge", "finding", "evidence"))


def schema(pointer: str) -> tuple[str, str, int]:
    return ("schema", pointer, 1)


def helper(name: str, unit: int = 1) -> tuple[str, str, int]:
    return ("helper", name, unit)


def extension(file: str, name: str, unit: int = 1) -> tuple[str, str, int]:
    return ("extension", f"{file}:{name}", unit)


# The ID row prints the pattern itself, in a code span, and no number.
ID_ROW = "An ID"
ID_PATTERN = (schema("/$defs/id/pattern"), helper("ID_RE"), extension("workflowDocument.ts", "ID_PATTERN"))

LIMITS: dict[str, list[tuple]] = {
    "`phases`": [(schema("/properties/phases/minItems"),), (schema("/properties/phases/maxItems"),)],
    "`nodes`": [(schema("/properties/nodes/minItems"),), (schema("/properties/nodes/maxItems"),)],
    "`edges`": [(schema("/properties/edges/maxItems"),)],
    "`findings`": [(schema("/properties/findings/maxItems"),)],
    "`evidence`": [(schema("/properties/evidence/maxItems"),)],
    "A list of references": [(schema("/$defs/refs/maxItems"),)],
    ID_ROW: [],
    "`title`": [(schema("/properties/title/maxLength"),)],
    "`producer.model`": [(schema("/properties/producer/properties/model/maxLength"),)],
    "`request.question`": [(schema("/properties/request/properties/question/maxLength"),)],
    "`request.scope`": [(schema("/properties/request/properties/scope/maxLength"),)],
    "`request.configuration`": [(schema("/properties/request/properties/configuration/maxLength"),)],
    "`request.entrypoints`": [(schema("/properties/request/properties/entrypoints/maxItems"),),
                              (schema("/properties/request/properties/entrypoints/items/maxLength"),)],
    "`label` of a phase": [(schema("/$defs/phase/properties/label/maxLength"),)],
    "`label` of a node or an edge": [(schema(NODE + "/label/maxLength"), schema(EDGE + "/label/maxLength"))],
    "`kind` of a node or an edge": [(schema(NODE + "/kind/maxLength"), schema(EDGE + "/kind/maxLength"))],
    "`detail` of a node": [(schema(NODE + "/detail/maxLength"),)],
    "`title` of a finding": [(schema(FINDING + "/title/maxLength"),)],
    "`message` of a finding": [(schema(FINDING + "/message/maxLength"),)],
    "`suggestion` of a finding": [(schema(FINDING + "/suggestion/maxLength"),)],
    "`file` of an evidence record": [(schema(EVIDENCE + "/file/maxLength"), helper("MAX_EVIDENCE_PATH"))],
    "`quote` of an evidence record": [(schema(EVIDENCE + "/quote/maxLength"), helper("MAX_QUOTE"))],
    "`coverage.summary`": [(schema("/properties/coverage/properties/summary/maxLength"),)],
    "`coverage.inspectedFiles`": [(schema("/properties/coverage/properties/inspectedFiles/maxItems"),),
                                  (schema("/properties/coverage/properties/inspectedFiles/items/maxLength"),)],
    "`coverage.limitations`": [(schema("/properties/coverage/properties/limitations/maxItems"),),
                               (schema("/properties/coverage/properties/limitations/items/maxLength"),)],
    "`verification.files`": [(schema("/properties/verification/properties/files/maxProperties"), helper("MAX_TRACKED"),
                              extension("workflowDocument.ts", "MAX_TRACKED_FILES")),
                             (schema("/properties/verification/properties/files/propertyNames/maxLength"),)],
    "The document file": [(helper("MAX_DOCUMENT", MIB), extension("workflowDocument.ts", "MAX_DOCUMENT_BYTES", MIB))],
    "A cited source file": [(helper("MAX_SOURCE", MIB), extension("workflowDocument.ts", "MAX_SOURCE_BYTES", MIB))],
    "JSON nesting of the document": [(helper("MAX_JSON_DEPTH"), extension("revisionLineage.ts", "MAX_JSON_DEPTH"))],
    "JSON nesting of a cited notebook": [(helper("MAX_NOTEBOOK_DEPTH"),)],
}


# The words of each row's second cell, with `#` for a number and `…` for the content of a code span.
# A row that is not listed here gives one number of characters.
CHARACTERS = "# characters"
WORDS = {
    "`phases`": "# to # records", "`nodes`": "# to # records",
    "`edges`": "at most # records", "`findings`": "at most # records", "`evidence`": "at most # records",
    "A list of references": "at most # IDs",
    ID_ROW: "`…`: a letter or a digit, then letters, digits, `…`, `…`, `…` or `…`",
    "`request.entrypoints`": "# paths of at most # characters",
    "`coverage.inspectedFiles`": "# paths of at most # characters",
    "`coverage.limitations`": "# entries of at most # characters",
    "`verification.files`": "# files, each path of at most # characters",
    "The document file": "# MiB", "A cited source file": "# MiB",
    "JSON nesting of the document": "# levels", "JSON nesting of a cited notebook": "# levels",
}
# The keywords of JSON Schema that set an upper bound.
UPPER = ("maxLength", "maxItems", "maxProperties", "maxContains", "maximum", "exclusiveMaximum")


def upper_bounds(node, pointer: str = ""):
    """The JSON pointer of every upper bound that a schema states."""
    if isinstance(node, dict):
        for key, value in node.items():
            here = pointer + "/" + key.replace("~", "~0").replace("/", "~1")
            if key in UPPER and isinstance(value, int) and not isinstance(value, bool):
                yield here
            else:
                yield from upper_bounds(value, here)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from upper_bounds(value, f"{pointer}/{index}")


def unlisted_bounds(schema_document: dict) -> list[str]:
    """The upper bounds of the schema that no row of LIMITS names."""
    named = {where for groups in LIMITS.values() for group in groups for layer, where, _ in group if layer == "schema"}
    return sorted(pointer for pointer in upper_bounds(schema_document) if pointer not in named)


def words(cell: str) -> str:
    """A cell of the table with `#` for each number and `…` for the content of each code span."""
    return re.sub(r"\d+", "#", re.sub(r"`[^`]*`", "`…`", cell))


def at(document: dict, pointer: str):
    """The value a JSON pointer names. A missing member raises KeyError with the pointer."""
    value = document
    for part in pointer.split("/")[1:]:
        try:
            value = value[int(part)] if isinstance(value, list) else value[part.replace("~1", "/").replace("~0", "~")]
        except (KeyError, IndexError, ValueError):
            raise KeyError(pointer) from None
    return value


def _product(node: ast.AST) -> int:
    """An integer literal, or a product of integer literals."""
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        return _product(node.left) * _product(node.right)
    raise ValueError("not an integer or a product of integers")


def helper_constants(source: str) -> dict[str, int | str]:
    """The helper's module-level integer constants, and the pattern of every ``NAME = re.compile(<literal>)``."""
    found: dict[str, int | str] = {}
    for node in ast.parse(source).body:
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)):
            continue
        name, value = node.targets[0].id, node.value
        try:
            found[name] = _product(value)
        except ValueError:
            if (isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute) and value.func.attr == "compile"
                    and value.args and isinstance(value.args[0], ast.Constant) and isinstance(value.args[0].value, str)):
                found[name] = value.args[0].value
    return found


EXPORT = re.compile(r"^export const ([A-Z][A-Z0-9_]*) = (\d[\d_]*(?:\s*\*\s*\d[\d_]*)*);", re.M)
EXPORT_PATTERN = re.compile(r"^export const ([A-Z][A-Z0-9_]*) = /(.+)/;$", re.M)


def extension_constants(sources: dict[str, str]) -> dict[str, int | str]:
    """{"<file>:<NAME>": value} for every ``export const NAME = <integers multiplied>;`` of the given sources,
    and the source of every ``export const NAME = /<pattern>/;``."""
    found: dict[str, int | str] = {}
    for file, text in sources.items():
        for name, expression in EXPORT.findall(text):
            value = 1
            for factor in expression.split("*"):
                value *= int(factor.strip().replace("_", ""))
            found[f"{file}:{name}"] = value
        for name, pattern in EXPORT_PATTERN.findall(text):
            found[f"{file}:{name}"] = pattern
    return found


def table_rows(text: str) -> list[tuple[str, str, str]]:
    if text.count(BEGIN) != 1 or text.count(END) != 1 or text.index(BEGIN) > text.index(END):
        raise AssertionError(f"docs/format.md needs exactly one {BEGIN} ... {END} section")
    rows = []
    for line in text[text.index(BEGIN) + len(BEGIN):text.index(END)].splitlines():
        if not line.strip():
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not line.startswith("|") or len(cells) != 3:
            raise AssertionError(f"a row of the limits table is not three cells: {line}")
        if set(line) <= set("|-: "):
            continue
        rows.append((cells[0], cells[1], cells[2]))
    if not rows or rows[0] != HEADER:
        raise AssertionError(f"the limits table starts with the header {' | '.join(HEADER)}")
    return rows[1:]


def problems(text: str, schema_document: dict, helper_source: str, extension_sources: dict[str, str]) -> list[str]:
    """What is wrong with the limits table of the given document text; empty when nothing is."""
    in_helper, in_extension = helper_constants(helper_source), extension_constants(extension_sources)

    def value(place: tuple[str, str, int]):
        layer, name, unit = place
        try:
            found = at(schema_document, name) if layer == "schema" else (in_helper if layer == "helper" else in_extension)[name]
        except KeyError:
            return f"missing: {layer} {name}"
        if isinstance(found, int) and unit != 1:
            return found // unit if found % unit == 0 else f"not a whole multiple: {layer} {name}"
        return found

    out: list[str] = []
    rows = table_rows(text)
    names = [name for name, _, _ in rows]
    for name in names:
        if names.count(name) > 1 and f"listed twice: {name}" not in out:
            out.append(f"listed twice: {name}")
    out += [f"a row of the table that LIMITS does not list: {name}" for name in names if name not in LIMITS]
    out += [f"a row of LIMITS that the table does not have: {name}" for name in LIMITS if name not in names]
    for name, printed, stated in rows:
        if name not in LIMITS:
            continue
        places = [ID_PATTERN] if name == ID_ROW else LIMITS[name]
        spans = re.findall(r"`([^`]*)`", printed)
        numbers = [int(number) for number in re.findall(r"\d+", re.sub(r"`[^`]*`", " ", printed))]
        if name == ID_ROW:
            expected = [value(place) for place in ID_PATTERN]
            if len(set(expected)) != 1 or expected[0] not in spans:
                out.append(f"{name}: the row prints {spans}, the schema, the helper and the extension hold {expected}")
        else:
            expected = []
            for group in places:
                values = [value(place) for place in group]
                if len(set(values)) != 1:
                    out.append(f"{name}: the places that state one number disagree: " + ", ".join(
                        f"{layer} {where} = {found}" for (layer, where, _), found in zip(group, values)))
                expected.append(values[0])
            if numbers != expected:
                out.append(f"{name}: the row prints {numbers}, the sources hold {expected}")
        if words(printed) != WORDS.get(name, CHARACTERS):
            out.append(f"{name}: the row says `{words(printed)}`, its words are `{WORDS.get(name, CHARACTERS)}`")
        layers = [layer for layer in LAYERS if any(place[0] == layer for group in places for place in group)]
        if [part.strip() for part in stated.split(",")] != layers:
            out.append(f"{name}: the last cell says `{stated}`, the numbers are stated by: {', '.join(layers)}")
    return out


def current() -> tuple[str, dict, str, dict[str, str]]:
    return (DOCUMENT.read_text(encoding="utf-8"), json.loads(SCHEMA.read_text(encoding="utf-8")), HELPER.read_text(encoding="utf-8"),
            {path.name: path.read_text(encoding="utf-8") for path in sorted(EXTENSION.glob("*.ts"))})


class FormatLimitsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text, cls.schema, cls.helper, cls.extension = current()

    def changed(self, old: str, new: str) -> list[str]:
        self.assertEqual(1, self.text.count(old), old)
        return problems(self.text.replace(old, new), self.schema, self.helper, self.extension)

    def test_the_table_prints_what_the_schema_and_the_code_hold(self):
        self.assertEqual([], problems(self.text, self.schema, self.helper, self.extension))

    def test_every_row_is_listed_once(self):
        names = [name for name, _, _ in table_rows(self.text)]
        self.assertEqual(sorted(LIMITS), sorted(names))

    def test_a_changed_number_in_the_table_is_reported(self):
        self.assertEqual(["`nodes`: the row prints [1, 2001], the sources hold [1, 2000]"],
                         self.changed("| `nodes` | 1 to 2000 records |", "| `nodes` | 1 to 2001 records |"))
        self.assertEqual(["The document file: the row prints [4], the sources hold [2]"],
                         self.changed("| The document file | 2 MiB |", "| The document file | 4 MiB |"))

    def test_a_changed_limit_in_the_schema_is_reported(self):
        schema_document = copy.deepcopy(self.schema)
        schema_document["properties"]["edges"]["maxItems"] += 1
        self.assertEqual(["`edges`: the row prints [4000], the sources hold [4001]"],
                         problems(self.text, schema_document, self.helper, self.extension))

    def test_a_changed_constant_of_the_helper_is_reported(self):
        found = problems(self.text, self.schema, self.helper.replace("MAX_QUOTE = 16000", "MAX_QUOTE = 16001"), self.extension)
        self.assertEqual(1, len(found), found)
        self.assertIn("`quote` of an evidence record: the places that state one number disagree", found[0])
        found = problems(self.text, self.schema, self.helper.replace("MAX_NOTEBOOK_DEPTH = 500", "MAX_NOTEBOOK_DEPTH = 400"), self.extension)
        self.assertEqual(["JSON nesting of a cited notebook: the row prints [500], the sources hold [400]"], found)

    def test_a_changed_constant_of_the_extension_is_reported(self):
        name = "workflowDocument.ts"
        sources = dict(self.extension, **{name: self.extension[name].replace("MAX_SOURCE_BYTES = 8 * 1024 * 1024", "MAX_SOURCE_BYTES = 16 * 1024 * 1024")})
        found = problems(self.text, self.schema, self.helper, sources)
        self.assertEqual(1, len(found), found)
        self.assertIn("A cited source file: the places that state one number disagree", found[0])

    def test_a_changed_id_pattern_is_reported(self):
        schema_document = copy.deepcopy(self.schema)
        schema_document["$defs"]["id"]["pattern"] = "^[a-z]+$"
        found = problems(self.text, schema_document, self.helper, self.extension)
        self.assertEqual(1, len(found), found)
        self.assertTrue(found[0].startswith("An ID: the row prints "), found[0])
        name = "workflowDocument.ts"
        sources = dict(self.extension, **{name: self.extension[name].replace("{0,127}$/;", "{0,63}$/;")})
        found = problems(self.text, self.schema, self.helper, sources)
        self.assertEqual(1, len(found), found)
        self.assertTrue(found[0].startswith("An ID: the row prints "), found[0])

    def test_a_changed_word_in_the_table_is_reported(self):
        # The unit, the direction of a bound, and the words of the ID row.
        self.assertEqual(["A cited source file: the row says `# GiB`, its words are `# MiB`"],
                         self.changed("| A cited source file | 8 MiB |", "| A cited source file | 8 GiB |"))
        self.assertEqual(["`request.question`: the row says `# bytes`, its words are `# characters`"],
                         self.changed("| `request.question` | 4000 characters |", "| `request.question` | 4000 bytes |"))
        self.assertEqual(["`edges`: the row says `at least # records`, its words are `at most # records`"],
                         self.changed("| `edges` | at most 4000 records |", "| `edges` | at least 4000 records |"))
        found = self.changed("$`: a letter or a digit, then letters,", "$`: a letter, then letters,")
        self.assertEqual(1, len(found), found)
        self.assertTrue(found[0].startswith("An ID: the row says `"), found[0])
        self.assertEqual(sorted(WORDS), sorted(name for name in LIMITS if name in WORDS))

    def test_every_upper_bound_of_the_schema_is_a_row(self):
        self.assertEqual([], unlisted_bounds(self.schema))
        self.assertTrue(list(upper_bounds(self.schema)))
        # A bound that the schema gains and no row prints.
        schema_document = copy.deepcopy(self.schema)
        schema_document["$defs"]["evidence"]["properties"]["line"]["maximum"] = 100000
        schema_document["properties"]["title"]["maxLength"] += 1
        self.assertEqual(["/$defs/evidence/properties/line/maximum"], unlisted_bounds(schema_document))

    def test_a_wrong_layer_is_reported(self):
        self.assertEqual(["`quote` of an evidence record: the last cell says `schema`, the numbers are stated by: schema, helper"],
                         self.changed("| 16000 characters | schema, helper |", "| 16000 characters | schema |"))

    def test_a_row_that_is_missing_or_unknown_is_reported(self):
        self.assertEqual(["a row of LIMITS that the table does not have: `title`"],
                         self.changed("| `title` | 200 characters | schema |\n", ""))
        self.assertEqual(["a row of the table that LIMITS does not list: `subtitle`", "a row of LIMITS that the table does not have: `title`"],
                         self.changed("| `title` | 200 characters | schema |", "| `subtitle` | 200 characters | schema |"))

    def test_a_row_that_is_not_three_cells_is_refused(self):
        with self.assertRaises(AssertionError):
            self.changed("| `title` | 200 characters | schema |", "| `title` | 200 characters |")

    def test_every_place_named_in_the_list_exists(self):
        in_helper, in_extension = helper_constants(self.helper), extension_constants(self.extension)
        for name, groups in list(LIMITS.items()) + [(ID_ROW, [ID_PATTERN])]:
            for layer, where, _ in (place for group in groups for place in group):
                with self.subTest(row=name, place=where):
                    if layer == "schema":
                        at(self.schema, where)
                    else:
                        self.assertIn(where, in_helper if layer == "helper" else in_extension)


if __name__ == "__main__":
    unittest.main()
