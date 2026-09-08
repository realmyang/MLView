"""The shared harness for the per-rule fixtures (CONTRACTS section 7.3, A7).

Imported as `rule_harness` - a unique name, because two `conftest.py` files
on `sys.path` (this one and `tests/core/conftest.py`) shadow each other
depending on collection order. `conftest.py` re-exports everything here, so
either import spelling works.

Every rule ships two fixtures under `tests/fixtures/rules/`:

* `<CODE>_bad.py` - **self-describing**: one `# MLVIEW-EXPECT:` line per issue
  the rule must raise, in the first comment block::

      # MLVIEW-EXPECT: MLV201 line=21 confidence>=0.6

  Recognised fields: `line=<n>`, `confidence>=<f>` (also `>`, `<=`, `<`, `==`),
  `severity=<low|medium|high>`, `bucket=<certain|likely|possible|speculative>`,
  `suppressed=<true|false>`, `ghost=<true|false>` (the issue owns a ghost node),
  `file=<relpath>` (for a multi-file fixture directory). Only `<CODE>` is
  required; anything omitted is not asserted.

* `<CODE>_good.py` - the **nearest false-positive trap**, headed by
  `# MLVIEW-EXPECT-NONE: <CODE>`; the rule must stay silent on it.

Nothing here imports or executes the fixture: it is parsed statically, exactly
like any analyzed workspace.

Adding a rule therefore costs one rule module, two fixture files and one line
in the parametrisation of `test_seed_rules.py` (or your own test module) -
`analyze_fixture` / `assert_fixture` do the rest.
"""

from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


from mlview.api import AnalyzeOptions, analyze_to_dict

TESTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FIXTURES = os.path.join(TESTS_DIR, "fixtures")
RULE_FIXTURES = os.path.join(FIXTURES, "rules")
CLEAN_DIR = os.path.join(TESTS_DIR, "clean")
REPO_ROOT = os.path.abspath(os.path.join(TESTS_DIR, "..", ".."))
CONTRACTS_DIR = os.path.join(REPO_ROOT, "contracts")
SCHEMA_PATH = os.path.join(CONTRACTS_DIR, "graph.schema.json")
SAMPLES_DIR = os.path.join(REPO_ROOT, "samples")
TOOLS_DIR = os.path.join(REPO_ROOT, "analyzer", "tools")
DOCS_RULES = os.path.join(REPO_ROOT, "docs", "rules")

EXPECT_RE = re.compile(r"#\s*MLVIEW-EXPECT:\s*(?P<body>.+?)\s*$")
EXPECT_NONE_RE = re.compile(r"#\s*MLVIEW-EXPECT-NONE:\s*(?P<codes>[A-Z0-9,\s]+?)\s*$")
_CODE_RE = re.compile(r"^(MLV[0-9]{3})")
_FIELD_RE = re.compile(r"(?P<key>[a-zA-Z_]+)\s*(?P<op>>=|<=|==|=|>|<)\s*(?P<value>\S+)")
_COMPARE = {
    ">=": lambda a, b: a >= b, ">": lambda a, b: a > b,
    "<=": lambda a, b: a <= b, "<": lambda a, b: a < b,
    "==": lambda a, b: a == b, "=": lambda a, b: a == b,
}
_BOOL = {"true": True, "false": False, "yes": True, "no": False, "1": True, "0": False}


# --------------------------------------------------------------- expectations
@dataclass(frozen=True)
class Expectation:
    """One `# MLVIEW-EXPECT:` line."""

    code: str
    raw: str
    line: Optional[int] = None
    file: Optional[str] = None
    severity: Optional[str] = None
    bucket: Optional[str] = None
    suppressed: Optional[bool] = None
    ghost: Optional[bool] = None
    confidence: Tuple[str, float] = ("", 0.0)

    def describe(self) -> str:
        return "%s (%s)" % (self.raw, self.code)


def parse_expectations(source: str) -> Tuple[List[Expectation], List[str]]:
    """`(expected issues, codes that must NOT fire)` from a fixture's header."""
    expected: List[Expectation] = []
    silent: List[str] = []
    for text in source.splitlines():
        none_match = EXPECT_NONE_RE.search(text)
        if none_match:
            silent.extend(c.strip() for c in none_match.group("codes").split(",") if c.strip())
            continue
        match = EXPECT_RE.search(text)
        if not match:
            continue
        expected.append(_parse_one(match.group("body")))
    return expected, silent


def _parse_one(body: str) -> Expectation:
    code_match = _CODE_RE.match(body.strip())
    if code_match is None:
        raise AssertionError("MLVIEW-EXPECT line does not start with a rule code: %r" % body)
    fields: Dict[str, Any] = {"code": code_match.group(1), "raw": body.strip()}
    for field_match in _FIELD_RE.finditer(body[code_match.end():]):
        key = field_match.group("key").lower()
        op = field_match.group("op")
        value = field_match.group("value")
        if key == "line":
            fields["line"] = int(value)
        elif key == "confidence":
            fields["confidence"] = (op, float(value))
        elif key in ("file", "severity", "bucket"):
            fields[key] = value
        elif key in ("suppressed", "ghost"):
            fields[key] = _BOOL.get(value.lower(), True)
        else:
            raise AssertionError("unknown MLVIEW-EXPECT field %r in %r" % (key, body))
    return Expectation(**fields)


# ------------------------------------------------------------------- analysis
@dataclass
class FixtureRun:
    """The analysis of one fixture path, plus its parsed header."""

    path: str
    doc: Dict[str, Any]
    expected: List[Expectation] = field(default_factory=list)
    silent: List[str] = field(default_factory=list)

    @property
    def issues(self) -> List[Dict[str, Any]]:
        return list(self.doc.get("issues", []))

    def of(self, code: str) -> List[Dict[str, Any]]:
        return [i for i in self.issues if i["code"] == code]

    def ghost_nodes(self) -> List[Dict[str, Any]]:
        return [n for n in self.doc.get("nodes", []) if n.get("ghost")]

    def summary(self) -> str:
        if not self.issues:
            return "(no issues)"
        return "; ".join("%s@%s:%d conf=%.2f %s"
                         % (i["code"], i["loc"]["file"], i["loc"]["line"],
                            i["confidence"], i["severity"])
                         for i in self.issues)


def fixture_path(name: str) -> str:
    """`"MLV201_bad"` / `"MLV201_bad.py"` / an absolute path -> absolute path."""
    if os.path.isabs(name) and os.path.exists(name):
        return name.replace("\\", "/")
    candidate = name if name.endswith(".py") or os.path.isdir(
        os.path.join(RULE_FIXTURES, name)) else name + ".py"
    path = os.path.join(RULE_FIXTURES, candidate)
    if not os.path.exists(path):
        raise AssertionError("no rule fixture %r under %s" % (name, RULE_FIXTURES))
    return os.path.abspath(path).replace("\\", "/")


def _read_header(path: str) -> str:
    if os.path.isdir(path):
        parts = []
        for source in sorted(glob.glob(os.path.join(path, "**", "*.py"), recursive=True)):
            with open(source, encoding="utf-8") as fh:
                parts.append(fh.read())
        return "\n".join(parts)
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def analyze_fixture(name: str, **options) -> FixtureRun:
    """Analyze one fixture file (or directory) and parse its expectations."""
    path = fixture_path(name)
    doc = analyze_to_dict(AnalyzeOptions(paths=(path,), **options))
    expected, silent = parse_expectations(_read_header(path))
    return FixtureRun(path=path, doc=doc, expected=expected, silent=silent)


# ------------------------------------------------------------------ assertions
def _match(issue: Dict[str, Any], want: Expectation) -> Optional[str]:
    """`None` when the issue satisfies the expectation, else why it does not."""
    loc = issue.get("loc", {})
    if want.line is not None and loc.get("line") != want.line:
        return "line %s != %s" % (loc.get("line"), want.line)
    if want.file is not None and loc.get("file") != want.file:
        return "file %s != %s" % (loc.get("file"), want.file)
    if want.severity is not None and issue.get("severity") != want.severity:
        return "severity %s != %s" % (issue.get("severity"), want.severity)
    if want.bucket is not None and issue.get("confidenceBucket") != want.bucket:
        return "bucket %s != %s" % (issue.get("confidenceBucket"), want.bucket)
    if want.suppressed is not None and bool(issue.get("suppressed")) != want.suppressed:
        return "suppressed %s != %s" % (issue.get("suppressed"), want.suppressed)
    op, threshold = want.confidence
    if op and not _COMPARE[op](float(issue.get("confidence", 0.0)), threshold):
        return "confidence %.3f fails %s%s" % (issue.get("confidence", 0.0), op, threshold)
    return None


def assert_expectation(run: FixtureRun, want: Expectation) -> Dict[str, Any]:
    """Assert one `# MLVIEW-EXPECT:` line and return the issue that satisfied it."""
    candidates = run.of(want.code)
    assert candidates, ("%s did not fire in %s.\n  expected: %s\n  actual:   %s"
                        % (want.code, os.path.basename(run.path), want.describe(),
                           run.summary()))
    reasons = []
    for issue in candidates:
        reason = _match(issue, want)
        if reason is None:
            if want.ghost:
                ghosts = [n for n in run.ghost_nodes() if issue["id"] in n.get("issueIds", [])]
                assert ghosts, ("%s fired but declared no ghost node in %s"
                                % (want.code, os.path.basename(run.path)))
            return issue
        reasons.append("%s:%s -> %s" % (issue["loc"]["file"], issue["loc"]["line"], reason))
    raise AssertionError("%s fired in %s but no occurrence matched.\n"
                         "  expected: %s\n  mismatches:\n    %s"
                         % (want.code, os.path.basename(run.path), want.describe(),
                            "\n    ".join(reasons)))


def assert_fires(name: str, **options) -> FixtureRun:
    """Run a `_bad` fixture and assert every `# MLVIEW-EXPECT:` line it declares."""
    run = analyze_fixture(name, **options)
    assert run.expected, ("%s declares no `# MLVIEW-EXPECT:` header - a bad fixture "
                          "must say what it expects" % os.path.basename(run.path))
    for want in run.expected:
        assert_expectation(run, want)
    return run


def assert_silent(name: str, *codes: str, **options) -> FixtureRun:
    """Run a `_good` fixture and assert the named codes (or its header's) stay quiet."""
    run = analyze_fixture(name, **options)
    wanted = [c.upper() for c in codes] or run.silent
    assert wanted, ("%s declares no `# MLVIEW-EXPECT-NONE:` header and no code was "
                    "passed" % os.path.basename(run.path))
    for code in wanted:
        fired = run.of(code)
        assert not fired, ("%s fired on the good fixture %s at line(s) %s - this is the "
                           "false-positive trap it must survive.\n  %s"
                           % (code, os.path.basename(run.path),
                              ", ".join(str(i["loc"]["line"]) for i in fired), run.summary()))
    return run


def rule_fixture_pairs() -> List[str]:
    """Every rule code that has both a `_bad` and a `_good` fixture on disk."""
    codes = set()
    for path in glob.glob(os.path.join(RULE_FIXTURES, "MLV*_bad.py")):
        code = os.path.basename(path).split("_", 1)[0]
        if os.path.exists(os.path.join(RULE_FIXTURES, "%s_good.py" % code)):
            codes.add(code)
    return sorted(codes)


# --------------------------------------------------- workspaces and validation
def analyze_paths(*paths: str, **options) -> Dict[str, Any]:
    """Analyze arbitrary paths (a directory, or several files) as one workspace."""
    return analyze_to_dict(AnalyzeOptions(paths=tuple(paths), **options))


def write_workspace(root: str, files: Dict[str, str]) -> str:
    """Write `{relpath: source}` under `root` and return the forward-slashed root."""
    for relpath, text in files.items():
        target = os.path.join(root, relpath.replace("/", os.sep))
        parent = os.path.dirname(target)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    return str(root).replace("\\", "/")


def _load_validator():
    import importlib.util
    path = os.path.join(CONTRACTS_DIR, "validate_sample.py")
    spec = importlib.util.spec_from_file_location("mlview_rule_contract_validator", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_VALIDATOR = None


def validate(doc) -> List[str]:
    """Every `contracts/validate_sample.py` error in a document (empty = valid)."""
    global _VALIDATOR
    if _VALIDATOR is None:
        _VALIDATOR = _load_validator()
    return list(_VALIDATOR.validate_graph(doc, schema_path=SCHEMA_PATH))


def good_fixtures() -> List[str]:
    """Every `<CODE>_good.py` on disk, sorted."""
    return sorted(glob.glob(os.path.join(RULE_FIXTURES, "MLV*_good.py")))


def bad_fixtures() -> List[str]:
    return sorted(glob.glob(os.path.join(RULE_FIXTURES, "MLV*_bad.py")))


def clean_corpus() -> List[str]:
    return sorted(glob.glob(os.path.join(CLEAN_DIR, "*.py")))


def counts(doc: Dict[str, Any]) -> Dict[str, int]:
    """`{severity: n}` over the *unsuppressed* issues of a document."""
    out = {"low": 0, "medium": 0, "high": 0}
    for issue in doc.get("issues", []):
        if issue.get("suppressed"):
            continue
        out[issue["severity"]] = out.get(issue["severity"], 0) + 1
    return out


def describe(doc: Dict[str, Any]) -> str:
    if not doc.get("issues"):
        return "(no issues)"
    return "; ".join("%s@%s:%d %s conf=%.2f"
                     % (i["code"], i["loc"]["file"], i["loc"]["line"], i["severity"],
                        i["confidence"])
                     for i in doc["issues"])
