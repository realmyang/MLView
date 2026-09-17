#!/usr/bin/env python
"""Checks 16, 17 and 18 of the doc gate: a surface that advertises less than the
build accepts, and a gate that runs less than the tree holds.

`doc_numbers.py` (checks 9-11) and `doc_figures.py` (checks 13-15) compare a
*number* in the prose with a machine-readable copy in the tree. These three
compare a *list*: the selectors a user is told exist against the ones the parser
accepts, the directories a tool says are git-ignored against `.gitignore`, and
the test files a package's `test` script runs against the ones on disk. All
three are the same defect wearing three hats -- **a surface that under-reports
the build is indistinguishable from a build that cannot do the thing**, and no
existing check could see any of them, because nothing here is a number.

Stdlib only, offline, and nothing is imported from the analyzer: the doc gate
runs in the `vscode-extension` CI job, which sets up Python but never installs
`mlview`, so `analyzer/src/mlview/core/selectors.py` is **parsed**, never
imported.

16. **A selector the CLI accepts that a user-facing list does not advertise.**
    CONTRACTS 11.47 added `pipeline:<entrypoint>` to the §11.1 grammar and 11.47
    B2 listed the six places that had to learn the new kind -- `SCOPE_KINDS`, the
    `bad_selector` candidates, `mlview.api`, `webview/src/scope/selector.ts`, the
    MCP `mlview_graph` docstring and `--list-scopes`. Every one of those is a
    *machine* surface. The legacy surfaces a person or a model actually read were
    not on the list and did not change: `mlview analyze --help`, `README.md`'s
    legacy section, `/mlview-issues`, and the legacy MCP server. So the only way
    a CLI user could learn
    that `pipeline:` exists was to type a wrong selector and read the refusal
    (`try: all, concern, file, node, pipeline, stage, symbol, unit`), and a model
    reading the legacy command's body would never pass the one selector that answers
    "show me just the training entrypoint" on a multi-script repo -- the shape
    half the public corpus has. `symbol:` had been in the same position since it
    was added. The parser's own `SCOPE_KINDS` tuple is the authority, so the
    check cannot be satisfied by editing a list of expected values here: add a
    kind to the analyzer and every advertised list fails until it names it.

    `vscode-extension/package.json` is deliberately **not** in the surface list:
    11.40 A2 makes the MCP docstring its source text word for word, and
    `vscode-extension/test/lmtool.test.js` already asserts the containment. Two
    gates on one string would only teach the next author to satisfy the weaker.

17. **A generated directory a tool documents as git-ignored that `.gitignore`
    does not cover.** `tools/public_corpus.py`'s docstring says its clones go to
    ``.public-corpus/`` "beside the repo, git-ignored"; `.gitignore` had no such
    entry, so `python tools/public_corpus.py fetch` put 24 real repositories --
    about 1.8 GB -- into `git status` as untracked, one `git add -A` away from
    being committed (PUB-17). The tool's own constant is the authority here too:
    the check reads `DEFAULT_CORPUS_DIR` out of the module rather than trusting a
    literal spelled a second time in this file.

18. **A `test` script that enumerates its test files and misses one.**
    `webview/package.json`'s `test` script named its thirty files one by one, so
    three regression files added in the hardening round were invisible to
    `npm test` and therefore to the `webview` CI job, which reported "534 pass,
    todo 0" with all three on disk and failing (HOSTS-UX-WEBVIEW-RUNNER). This is
    the one failure mode where writing a regression test is not enough to make it
    a gate, and the only one of these three that costs a *test* rather than a
    sentence. A package that discovers its tests (`node tools/run-tests.mjs`,
    which is what both JS packages now do, or pytest) names no test file and is
    not held to anything; a package that goes back to enumerating them must
    enumerate all of them. Every `.mjs`/`.js`/`.cjs` path a `test` script names
    must also exist, so a renamed file fails here instead of silently reducing
    the suite.

Imported by `scripts/check_docs.py`; `scripts/test_doc_surfaces.py` tests it.
"""
from __future__ import annotations

import ast
import io
import json
import re
from pathlib import Path

# ------------------------------------------------------------------ check 16
#: The parser's own tuple of selector kinds -- read, never imported.
SELECTORS_SRC = "analyzer/src/mlview/core/selectors.py"
#: The `--scope` help string is a user-facing selector list like any other; it
#: just happens to live in Python.
CLI_PARSER_SRC = "analyzer/src/mlview/cli_parser.py"
#: Spellings that are legal in the kind slot but are not `SCOPE_KINDS` entries.
EXTRA_SPELLINGS = ("symbol", "all")
#: Legacy prose surfaces that advertise the static analyzer selector grammar.
#: The LLM-native `/mlview` command consumes a WorkflowDocument and has no
#: reason to teach the replaced analyzer's selector vocabulary.
LEGACY_SELECTOR_SURFACES = (
    "README.md",
    "claude-plugin/commands/mlview-issues.md",
    "claude-plugin/server/mlview_mcp.py",
)
#: Explicit classification prevents a future broad `commands/*.md` sweep from
#: accidentally forcing static-analyzer language back into the native command.
NATIVE_WORKFLOW_SURFACES = ("claude-plugin/commands/mlview.md",)
#: Backward-compatible name for callers that enumerate the checked surfaces.
SELECTOR_SURFACES = LEGACY_SELECTOR_SURFACES
#: `all` is the one spelling with no colon, so it needs its own shape: quoted or
#: backticked, never the bare English word.
ALL_RE = re.compile(r"[`'\"]all[`'\"]")

# ------------------------------------------------------------------ check 17
#: (module, constant) pairs naming a directory the tool creates inside the repo.
GENERATED_DIRS = (
    ("tools/public_corpus.py", "DEFAULT_CORPUS_DIR"),
)
GITIGNORE = ".gitignore"

# ------------------------------------------------------------------ check 18
#: The two packages whose `npm test` is a CI gate. `claude-plugin` is pytest,
#: which discovers by construction and has no script to hold.
TEST_SCRIPT_PACKAGES = ("webview", "vscode-extension")
TEST_FILE_RE = re.compile(r"\.test\.[cm]?js$")
#: A file path inside an npm script: `tools/run-tests.mjs`, `test/a11y.test.mjs`.
SCRIPT_FILE_RE = re.compile(r"[\w./-]+\.[cm]?js\b")


def _read(path: Path) -> str:
    return io.open(path, encoding="utf-8", newline="").read()


def _assigned(tree: ast.AST, name: str):
    """The value node of the first module-level `name = ...` / `name: T = ...`."""
    for node in ast.walk(tree):
        target = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target = node.target.id
        elif (isinstance(node, ast.Assign) and len(node.targets) == 1
              and isinstance(node.targets[0], ast.Name)):
            target = node.targets[0].id
        if target == name and getattr(node, "value", None) is not None:
            return node.value
    return None


# ------------------------------------------------------------------ check 16
def scope_spellings(root: Path):
    """Everything legal in a selector's kind slot, from the parser's own tuple."""
    path = root / SELECTORS_SRC
    if not path.is_file():
        return ()
    try:
        value = _assigned(ast.parse(_read(path)), "SCOPE_KINDS")
        kinds = ast.literal_eval(value) if value is not None else ()
    except (SyntaxError, ValueError):
        return ()
    if not isinstance(kinds, (tuple, list)):
        return ()
    return tuple(sorted({str(k) for k in kinds} | set(EXTRA_SPELLINGS)))


def scope_help(root: Path):
    """(the `--scope` help string, its line) out of the CLI parser."""
    path = root / CLI_PARSER_SRC
    if not path.is_file():
        return None, 0
    try:
        tree = ast.parse(_read(path))
    except SyntaxError:
        return None, 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        first = node.args[0]
        if not (isinstance(first, ast.Constant) and first.value == "--scope"):
            continue
        for keyword in node.keywords:
            if keyword.arg == "help" and isinstance(keyword.value, ast.Constant):
                return str(keyword.value.value), node.lineno
    return None, 0


def advertises(text: str, spelling: str) -> bool:
    return bool(ALL_RE.search(text)) if spelling == "all" else (spelling + ":") in text


def check_selector_surfaces(root: Path, problems: list) -> None:
    """16: every selector is named on every legacy surface that advertises it."""
    spellings = scope_spellings(root)
    if not spellings:
        return  # no analyzer in this tree; checks 1-2 already say so
    surfaces = []
    help_text, help_line = scope_help(root)
    if help_text is not None:
        surfaces.append((CLI_PARSER_SRC, help_line, help_text))
    elif (root / CLI_PARSER_SRC).is_file():
        problems.append(
            "%s: no `--scope` help string found, so nothing holds `mlview analyze "
            "--help` to the selectors the parser accepts (check 16)"
            % CLI_PARSER_SRC)
    for rel in SELECTOR_SURFACES:
        path = root / rel
        if path.is_file():
            surfaces.append((rel, 0, _read(path)))

    for rel, line, text in surfaces:
        missing = [s for s in spellings if not advertises(text, s)]
        if not missing:
            continue
        where = ("%s:%d" % (rel, line)) if line else rel
        problems.append(
            "%s: the parser accepts %s, and this selector list does not "
            "advertise %s -- a selector a reader is never shown is a selector "
            "nobody passes, and `SCOPE_KINDS` in `%s` is the only authority "
            "(check 16)"
            % (where, ", ".join("`%s`" % s for s in missing),
               "it" if len(missing) == 1 else "them", SELECTORS_SRC))


# ------------------------------------------------------------------ check 17
def generated_dir(root: Path, rel: str, const: str):
    """(directory name, line) out of `X = os.path.join(REPO_ROOT, "<name>")`."""
    path = root / rel
    if not path.is_file():
        return None, 0
    try:
        value = _assigned(ast.parse(_read(path)), const)
    except SyntaxError:
        return None, 0
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value, value.lineno
    if isinstance(value, ast.Call) and value.args:
        last = value.args[-1]
        if isinstance(last, ast.Constant) and isinstance(last.value, str):
            return last.value, value.lineno
    return None, 0


def ignored_names(root: Path):
    path = root / GITIGNORE
    if not path.is_file():
        return set()
    names = set()
    for raw in _read(path).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        names.add(line.strip("/"))
    return names


def check_generated_dirs(root: Path, problems: list) -> None:
    """17: a directory a tool fills must be one `.gitignore` covers."""
    ignored = ignored_names(root)
    for rel, const in GENERATED_DIRS:
        name, line = generated_dir(root, rel, const)
        if not name or "/" in name.strip("/"):
            continue
        if name.strip("/") in ignored:
            continue
        problems.append(
            "%s:%d: `%s` writes into `%s/`, which `%s` does not cover -- running "
            "the tool puts its whole download into `git status`, one `git add -A` "
            "from being committed (check 17, PUB-17)"
            % (rel, line, const, name.strip("/"), GITIGNORE))


# ------------------------------------------------------------------ check 18
def check_test_scripts(root: Path, problems: list) -> None:
    """18: an enumerating `test` script must enumerate every test on disk."""
    for pkg in TEST_SCRIPT_PACKAGES:
        manifest = root / pkg / "package.json"
        if not manifest.is_file():
            continue
        try:
            script = (json.loads(_read(manifest)).get("scripts") or {}).get("test")
        except ValueError:
            continue
        if not script:
            continue
        named = SCRIPT_FILE_RE.findall(script)
        for token in named:
            if not (root / pkg / token).is_file():
                problems.append(
                    "%s/package.json: the `test` script runs `%s`, which is not "
                    "in the tree (check 18)" % (pkg, token))
        test_dir = root / pkg / "test"
        if not test_dir.is_dir():
            continue
        on_disk = sorted(p.name for p in test_dir.iterdir()
                         if p.is_file() and TEST_FILE_RE.search(p.name))
        enumerated = {token.rsplit("/", 1)[-1] for token in named
                      if TEST_FILE_RE.search(token)}
        if not enumerated:
            continue  # the script discovers its tests; nothing to fall behind
        missing = [name for name in on_disk if name not in enumerated]
        if missing:
            problems.append(
                "%s/package.json: the `test` script lists its test files one by "
                "one and does not list %s, so `npm test` reports a green suite "
                "that never ran %s -- a regression test the gate does not run is "
                "decoration (check 18, HOSTS-UX-WEBVIEW-RUNNER)"
                % (pkg, ", ".join("`test/%s`" % m for m in missing),
                   "it" if len(missing) == 1 else "them"))


def run(root: Path, paths, problems: list) -> None:
    """All three checks, in the order the docstring numbers them."""
    check_selector_surfaces(root, problems)
    check_generated_dirs(root, problems)
    check_test_scripts(root, problems)
