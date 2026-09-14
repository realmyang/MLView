#!/usr/bin/env python
"""Tests for scripts/doc_surfaces.py -- checks 16, 17 and 18 of the doc gate.

Same shape as `scripts/test_doc_figures.py`, whose `_tree` helper and `REPO` these
reuse: each case builds a throwaway tree and runs the check against it, so
nothing here depends on the state of the real repo. Three cases at the end *do*
read the real repo and assert the three defects that motivated these checks are
gone from it -- and each of those three is written so that reverting the fix
brings the failure back, which is the only property that makes a regression test
one.

HOSTS-UX-DOCS-PIPELINE: `pipeline:` (CONTRACTS 11.47) and `symbol:` parsed
everywhere and were advertised in `mlview analyze --help`, `README.md` and
neither `claude-plugin/commands/*.md`. The MCP docstring and the three VS Code
language-model tool descriptions carried the full grammar, so the gap was exactly
the surfaces a *person* reads.
PUB-17: `tools/public_corpus.py`'s docstring called `.public-corpus/`
"git-ignored" while `.gitignore` had no such entry, so `fetch` put ~1.8 GB of
clones into `git status`.
HOSTS-UX-WEBVIEW-RUNNER: `webview/package.json`'s `test` script named its thirty
files one by one, so three regression files added in the hardening round never
ran and `npm test` reported "534 pass, todo 0" with all three failing on disk.

`scripts/test_check_docs.py` runs these too, so the drivers and CI keep one
doc-gate self-test entry point. Run either file under pytest for the same set.
"""
from __future__ import annotations

import io
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_docs  # noqa: E402
import doc_surfaces  # noqa: E402
from test_check_docs import REPO, _tree  # noqa: E402

# --------------------------------------------------------------------- check 16
# A miniature of the parser: two kinds, so a fixture cannot accidentally satisfy
# the check by quoting the real repo's vocabulary.
SELECTORS = '''"""A stand-in for the real selectors module."""
SCOPE_KINDS = ("unit", "widget")
'''

CLI_PARSER = '''import argparse


def _add_scope_flags(parser):
    parser.add_argument("--scope", dest="scope", metavar="SPEC", default=None,
                        help=%r)
'''

FULL_HELP = "project: 'all', unit:<name>, symbol:<name>, widget:<name>"
SHORT_HELP = "project: 'all', unit:<name>, symbol:<name>"

#: One surface file that names every spelling, and the same one short of `widget:`.
FULL_DOC = ("# Demo\n\nOne selector: `unit:SmallCNN`, `symbol:SmallCNN`, "
            "`widget:w1`, or `all`.\n")
SHORT_DOC = "# Demo\n\nOne selector: `unit:SmallCNN`, `symbol:SmallCNN`, or `all`.\n"


def _selector_tree(help_text: str, readme: str, command: str) -> Path:
    return _tree({
        doc_surfaces.SELECTORS_SRC: SELECTORS,
        doc_surfaces.CLI_PARSER_SRC: CLI_PARSER % help_text,
        "README.md": readme,
        "claude-plugin/commands/mlview.md": command,
        "claude-plugin/commands/mlview-issues.md": command,
        "claude-plugin/server/mlview_mcp.py": '"""%s"""\n' % FULL_DOC,
    })


def _surfaces(root: Path) -> list:
    problems: list = []
    doc_surfaces.run(root, [], problems)
    return problems


def test_a_selector_the_parser_accepts_but_no_list_advertises_is_caught():
    """HOSTS-UX-DOCS-PIPELINE, in miniature: `widget:` parses, nothing says so."""
    root = _selector_tree(SHORT_HELP, SHORT_DOC, SHORT_DOC)
    try:
        problems = _surfaces(root)
        assert len(problems) == 4, problems  # the help string and three docs
        assert all("`widget`" in p and "check 16" in p for p in problems), problems
        assert any(doc_surfaces.CLI_PARSER_SRC in p for p in problems), problems
        assert any("claude-plugin/commands/mlview-issues.md" in p
                   for p in problems), problems
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_every_list_advertising_every_spelling_is_clean():
    root = _selector_tree(FULL_HELP, FULL_DOC, FULL_DOC)
    try:
        assert _surfaces(root) == [], _surfaces(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_one_surface_falling_behind_is_named_alone():
    """The point of listing the surfaces separately: the report says which one."""
    root = _selector_tree(FULL_HELP, FULL_DOC, SHORT_DOC)
    try:
        problems = _surfaces(root)
        assert len(problems) == 2, problems
        assert all("commands/mlview" in p for p in problems), problems
        assert not any("README.md" in p for p in problems), problems
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_spellings_come_from_the_parser_not_from_this_file():
    """Add a kind to `SCOPE_KINDS` and every advertised list fails until it names
    it -- the check cannot be satisfied by editing an expected-value list here."""
    root = _selector_tree(FULL_HELP, FULL_DOC, FULL_DOC)
    try:
        assert doc_surfaces.scope_spellings(root) == (
            "all", "symbol", "unit", "widget")
        path = root / doc_surfaces.SELECTORS_SRC
        io.open(path, "w", encoding="utf-8", newline="\n").write(
            SELECTORS.replace('"widget")', '"widget", "sprocket")'))
        assert "sprocket" in doc_surfaces.scope_spellings(root)
        problems = _surfaces(root)
        assert len(problems) == 5, problems
        assert all("`sprocket`" in p for p in problems), problems
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_tree_with_no_analyzer_is_not_held_to_a_grammar_it_has_not_got():
    root = _tree({"README.md": "# Demo\n"})
    try:
        assert _surfaces(root) == [], _surfaces(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_cli_parser_with_no_scope_help_is_itself_the_finding():
    root = _tree({doc_surfaces.SELECTORS_SRC: SELECTORS,
                  doc_surfaces.CLI_PARSER_SRC: "import argparse\n"})
    try:
        problems = _surfaces(root)
        assert len(problems) == 1, problems
        assert "no `--scope` help string" in problems[0], problems
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_bare_english_word_all_is_not_an_advertisement():
    """`all` has no colon, so it needs its own shape -- otherwise every sentence
    containing the word "all" would satisfy the check for it."""
    assert doc_surfaces.advertises("show `all` of it", "all")
    assert doc_surfaces.advertises("or 'all'", "all")
    assert not doc_surfaces.advertises("narrows all the surfaces", "all")
    assert doc_surfaces.advertises("pass `pipeline:train.py`", "pipeline")
    assert not doc_surfaces.advertises("one pipeline per entrypoint", "pipeline")


# --------------------------------------------------------------------- check 17
PUBLIC_CORPUS = '''"""Clones into ``.downloads/`` beside the repo, git-ignored."""
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CORPUS_DIR = os.path.join(REPO_ROOT, ".downloads")
'''


def _corpus_tree(gitignore: str) -> Path:
    return _tree({"tools/public_corpus.py": PUBLIC_CORPUS, ".gitignore": gitignore,
                  "README.md": "# Demo\n"})


def test_a_generated_directory_no_gitignore_line_covers_is_caught():
    """PUB-17, in miniature."""
    root = _corpus_tree("node_modules/\n.mlview/\n")
    try:
        problems: list = []
        doc_surfaces.check_generated_dirs(root, problems)
        assert len(problems) == 1, problems
        assert "`.downloads/`" in problems[0] and "PUB-17" in problems[0], problems
        assert "DEFAULT_CORPUS_DIR" in problems[0], problems
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_gitignore_line_in_any_of_its_spellings_clears_it():
    for line in (".downloads/", ".downloads", "/.downloads", "/.downloads/"):
        root = _corpus_tree("# a comment\n\nnode_modules/\n%s\n" % line)
        try:
            problems: list = []
            doc_surfaces.check_generated_dirs(root, problems)
            assert problems == [], (line, problems)
        finally:
            shutil.rmtree(root, ignore_errors=True)


def test_a_commented_out_gitignore_line_does_not_count():
    root = _corpus_tree("# .downloads/\nnode_modules/\n")
    try:
        problems: list = []
        doc_surfaces.check_generated_dirs(root, problems)
        assert len(problems) == 1, problems
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_directory_name_is_read_from_the_tool_not_spelled_twice():
    """Rename the constant's value and the check follows it, so the gate cannot
    go on protecting a directory the tool stopped using."""
    root = _corpus_tree(".downloads/\n")
    try:
        io.open(root / "tools/public_corpus.py", "w", encoding="utf-8",
                newline="\n").write(PUBLIC_CORPUS.replace(".downloads", ".clones"))
        assert doc_surfaces.generated_dir(
            root, "tools/public_corpus.py", "DEFAULT_CORPUS_DIR")[0] == ".clones"
        problems: list = []
        doc_surfaces.check_generated_dirs(root, problems)
        assert len(problems) == 1 and "`.clones/`" in problems[0], problems
    finally:
        shutil.rmtree(root, ignore_errors=True)


# --------------------------------------------------------------------- check 18
def _package_tree(test_script: str, files=("a.test.mjs", "b.test.mjs"),
                  extra=None) -> Path:
    tree = {"README.md": "# Demo\n",
            "webview/package.json": json.dumps(
                {"name": "w", "scripts": {"test": test_script}}, indent=2) + "\n"}
    for name in files:
        tree["webview/test/" + name] = "// a test\n"
    tree.update(extra or {})
    return _tree(tree)


def test_a_test_script_that_enumerates_and_misses_a_file_is_caught():
    """HOSTS-UX-WEBVIEW-RUNNER, in miniature."""
    root = _package_tree("node --test test/a.test.mjs")
    try:
        problems: list = []
        doc_surfaces.check_test_scripts(root, problems)
        assert len(problems) == 1, problems
        assert "`test/b.test.mjs`" in problems[0], problems
        assert "HOSTS-UX-WEBVIEW-RUNNER" in problems[0], problems
        assert "a.test.mjs" not in problems[0].split("does not list", 1)[1]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_complete_enumeration_is_clean():
    root = _package_tree("node --test test/a.test.mjs test/b.test.mjs")
    try:
        problems: list = []
        doc_surfaces.check_test_scripts(root, problems)
        assert problems == [], problems
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_discovering_runner_is_not_held_to_a_file_list():
    root = _package_tree("node tools/run-tests.mjs",
                         extra={"webview/tools/run-tests.mjs": "// discovery\n"})
    try:
        problems: list = []
        doc_surfaces.check_test_scripts(root, problems)
        assert problems == [], problems
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_test_script_naming_a_file_that_is_not_in_the_tree_is_caught():
    """A renamed helper silently shrinks the suite the same way a missing one
    silently never joins it."""
    root = _package_tree("node tools/run-tests.mjs")
    try:
        problems: list = []
        doc_surfaces.check_test_scripts(root, problems)
        assert len(problems) == 1, problems
        assert "tools/run-tests.mjs" in problems[0], problems
        assert "not in the tree" in problems[0], problems
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------- the real repo, not a fixture
def test_the_real_tree_advertises_every_selector_its_parser_accepts():
    """The HOSTS-UX-DOCS-PIPELINE repro, run against the repo itself."""
    spellings = doc_surfaces.scope_spellings(REPO)
    assert "pipeline" in spellings and "symbol" in spellings, spellings
    problems: list = []
    doc_surfaces.check_selector_surfaces(REPO, problems)
    assert problems == [], "\n".join(problems)
    for rel in (doc_surfaces.CLI_PARSER_SRC,) + doc_surfaces.SELECTOR_SURFACES:
        text = io.open(REPO / rel, encoding="utf-8").read()
        assert "pipeline:" in text, rel


def test_the_real_tree_git_ignores_the_public_corpus_clones():
    """The PUB-17 repro, run against the repo itself."""
    name, _ = doc_surfaces.generated_dir(
        REPO, "tools/public_corpus.py", "DEFAULT_CORPUS_DIR")
    assert name == ".public-corpus", name
    assert name.strip("/") in doc_surfaces.ignored_names(REPO)
    problems: list = []
    doc_surfaces.check_generated_dirs(REPO, problems)
    assert problems == [], "\n".join(problems)


def test_the_real_packages_run_every_test_file_they_hold():
    """The HOSTS-UX-WEBVIEW-RUNNER repro, run against the repo itself: both JS
    packages discover, and the three hardening files are on disk to be found."""
    problems: list = []
    doc_surfaces.check_test_scripts(REPO, problems)
    assert problems == [], "\n".join(problems)
    for pkg in doc_surfaces.TEST_SCRIPT_PACKAGES:
        manifest = json.loads(io.open(REPO / pkg / "package.json",
                                      encoding="utf-8").read())
        script = manifest["scripts"]["test"]
        assert "run-tests.mjs" in script, (pkg, script)
        assert (REPO / pkg / "tools/run-tests.mjs").is_file(), pkg
    names = {p.name for p in (REPO / "webview/test").iterdir()}
    assert {"hardening_canvas_overlays.test.mjs", "hardening_chipwall.test.mjs",
            "hardening_cleanstate.test.mjs"} <= names, sorted(names)


def test_the_doc_gate_runs_these_three_checks():
    """Wiring, asserted: `check_docs.run` must call this module, or the three
    cases above are decoration in exactly the way check 18 is about."""
    problems, _ = check_docs.run(REPO)
    assert problems == [], "\n".join(problems)
    source = io.open(REPO / "scripts/check_docs.py", encoding="utf-8").read()
    assert "doc_surfaces.run(root, current, problems)" in source


def main() -> int:
    from test_check_docs import run_module

    failed = run_module(sys.modules[__name__])
    print(("%d test(s) failed" % failed) if failed else "doc_surfaces self-test OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
