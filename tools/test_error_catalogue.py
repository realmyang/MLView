"""The helper's error and warning codes are catalogued in both contract documents.

The codes are read from skills/mlview/scripts/artifact.py by an AST scan: the first literal
argument of every ``.add(...)`` call, every literal ``"code"`` value in a dict display, the
codes ``_path_syntax`` returns, and the second literal argument of every ``_warn(...)`` call.
The scan refuses any other way of choosing a code, so a new code cannot hide from it. Both
docs/WORKFLOW_CONTRACT.md (a table) and skills/mlview/references/WORKFLOW_CONTRACT.md (a compact
list the model reads) must list exactly these codes, with matching kinds, between the
``helper-codes`` markers; every code a conformance case expects must be catalogued.

These are documentation checks. They are not semantic accuracy or live-host validation.
"""
from __future__ import annotations

import ast
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "skills" / "mlview" / "scripts" / "artifact.py"
CONTRACT = ROOT / "docs" / "WORKFLOW_CONTRACT.md"
SKILL_REFERENCE = ROOT / "skills" / "mlview" / "references" / "WORKFLOW_CONTRACT.md"
CASES = ROOT / "contracts" / "conformance" / "cases"
BEGIN, END = "<!-- helper-codes:begin -->", "<!-- helper-codes:end -->"
CODE = re.compile(r"[a-z][a-z0-9_]*", re.ASCII)
TABLE_ROW = re.compile(r"^\| `([a-z][a-z0-9_]*)` \| (error|warning) \| [^|]+ \| [^|]+ \|$")
LIST_ITEM = re.compile(r"^- ([a-z][a-z0-9_]*): \S")
LIST_KIND = re.compile(r"^(Errors|Warnings) \(")
# The skill reference is model context: keep its list compact.
SKILL_LIST_LIMIT = 4096


def _literal(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def helper_codes(source: str) -> tuple[dict[str, str], list[str]]:
    """({code: "error" | "warning"}, problems) for the helper source."""
    tree = ast.parse(source)
    codes: dict[str, str] = {}
    problems: list[str] = []

    def found(code: str | None, kind: str, node: ast.AST) -> None:
        if code is None or not CODE.fullmatch(code):
            problems.append(f"line {node.lineno}: a {kind} code is not a literal identifier")
        elif codes.setdefault(code, kind) != kind:
            problems.append(f"line {node.lineno}: {code} is used both as an error and as a warning")

    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}

    def enclosing(node: ast.AST) -> str | None:
        while node in parents:
            node = parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node.name
        return None

    # Problems.add and _warn receive a code as a parameter and put it into an entry; the only
    # computed code passed to Problems.add is the one _path_syntax returned (``syntax[0]``).
    forwarders = {"add", "_warn"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if key is not None and _literal(key) == "code":
                    if _literal(value) is not None:
                        found(_literal(value), "error", node)
                    elif not (enclosing(node) in forwarders and isinstance(value, ast.Name) and value.id == "code"):
                        problems.append(f"line {node.lineno}: a computed \"code\" in {enclosing(node)}()")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "add":
                first = node.args[0] if node.args else None
                if first is not None and _literal(first) is not None:
                    found(_literal(first), "error", node)
                elif (isinstance(func.value, ast.Name) and func.value.id in {"p", "problems"}
                      and not (isinstance(first, ast.Subscript) and isinstance(first.value, ast.Name) and first.value.id == "syntax")):
                    problems.append(f"line {node.lineno}: Problems.add() with a computed code")
            elif isinstance(func, ast.Name) and func.id == "_warn":
                found(_literal(node.args[1]) if len(node.args) > 1 else None, "warning", node)
        elif isinstance(node, ast.Return) and enclosing(node) == "_path_syntax" and isinstance(node.value, ast.Tuple):
            found(_literal(node.value.elts[0]), "error", node)
    return codes, problems


def _section(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    if text.count(BEGIN) != 1 or text.count(END) != 1 or text.index(BEGIN) > text.index(END):
        raise AssertionError(f"{path.relative_to(ROOT).as_posix()} needs exactly one {BEGIN} ... {END} section")
    return text[text.index(BEGIN) + len(BEGIN):text.index(END)].splitlines()


def contract_codes() -> dict[str, str]:
    codes: dict[str, str] = {}
    for line in _section(CONTRACT):
        match = TABLE_ROW.match(line)
        if match:
            if match.group(1) in codes:
                raise AssertionError(f"docs/WORKFLOW_CONTRACT.md lists {match.group(1)} twice")
            codes[match.group(1)] = match.group(2)
        elif line.startswith("| `"):
            raise AssertionError(f"malformed catalogue row in docs/WORKFLOW_CONTRACT.md: {line}")
    return codes


def skill_codes() -> dict[str, str]:
    codes: dict[str, str] = {}
    kind: str | None = None
    for line in _section(SKILL_REFERENCE):
        heading = LIST_KIND.match(line)
        if heading:
            kind = "error" if heading.group(1) == "Errors" else "warning"
            continue
        match = LIST_ITEM.match(line)
        if match:
            if kind is None or match.group(1) in codes:
                raise AssertionError(f"skill reference catalogue line out of place or repeated: {line}")
            codes[match.group(1)] = kind
        elif line.startswith("- "):
            raise AssertionError(f"malformed catalogue line in the skill reference: {line}")
    return codes


class ErrorCatalogueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.codes, cls.problems = helper_codes(HELPER.read_text(encoding="utf-8"))

    def test_the_scan_sees_every_code_the_helper_can_emit(self):
        self.assertEqual([], self.problems)
        kinds = sorted(self.codes.values())
        # 58 error codes and 2 warnings when the catalogue was written (Campaign 2 SPEC 7.3).
        self.assertGreaterEqual(kinds.count("error"), 58)
        self.assertEqual(["excluded_inspected", "not_fingerprinted"], sorted(code for code, kind in self.codes.items() if kind == "warning"))

    def test_the_scan_refuses_computed_codes(self):
        codes, problems = helper_codes(
            "def check(p, name):\n    p.add(name, '$', 'x')\n    p.add('literal_code', '$', 'x')\n"
            "def emit():\n    return {'code': 'from_' + 'parts'}\n"
            "def _warn(warnings, code, path, message):\n    warnings.append({'code': code})\n"
            "def note(w, name):\n    _warn(w, 'soft', '$', 'x')\n    _warn(w, name, '$', 'x')\n"
            "def both(p, w):\n    p.add('soft', '$', 'x')\n")
        self.assertEqual({"literal_code": "error", "soft": "warning"}, codes)
        self.assertEqual(4, len(problems), problems)
        self.assertIn("both as an error and as a warning", problems[-1])

    def test_the_contract_table_lists_exactly_the_helper_codes(self):
        self.assertEqual(self.codes, contract_codes())

    def test_the_skill_reference_lists_exactly_the_helper_codes_compactly(self):
        self.assertEqual(self.codes, skill_codes())
        text = SKILL_REFERENCE.read_bytes()
        section = text[text.index(BEGIN.encode()):text.index(END.encode())]
        self.assertLess(len(section), SKILL_LIST_LIMIT)

    def test_every_code_a_conformance_case_expects_is_catalogued(self):
        expected: dict[str, str] = {}
        for path in sorted(CASES.glob("*.json")):
            helper = json.loads(path.read_text(encoding="utf-8"))["expect"]["helper"]
            expected.update({code: "error" for code in helper["codes"]})
            expected.update({code: "warning" for code in helper["warnings"]})
        self.assertTrue(expected)
        for code, kind in sorted(expected.items()):
            with self.subTest(code=code):
                self.assertEqual(kind, self.codes.get(code))
                self.assertEqual(kind, contract_codes().get(code))
                self.assertEqual(kind, skill_codes().get(code))


if __name__ == "__main__":
    unittest.main()
