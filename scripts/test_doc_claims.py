#!/usr/bin/env python
"""Tests for scripts/doc_claims.py: check 16, DOCS-CI-OVERCLAIM.

Each case builds a throwaway tree in a temp directory and runs the whole doc
gate against it with --root, so nothing here depends on the state of the real
repo -- the same shape as `scripts/test_check_docs.py`, whose `main()` runs this
module too.

Run:  python scripts/test_doc_claims.py   (or: pytest scripts/test_doc_claims.py)
"""
from __future__ import annotations

import io
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_docs  # noqa: E402
import doc_claims  # noqa: E402


def _tree(files: dict) -> Path:
    root = Path(tempfile.mkdtemp(prefix="mlview-docclaims-"))
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        io.open(target, "w", encoding="utf-8", newline="\n").write(text)
    return root


#: The defect, word for word as README.md carried it.
OVERCLAIM_README = """# Demo

## What is verified, and what is not

Every gate above is green on the build machine and on the CI matrix. What that
does not cover: the extension host has never been driven under automation.
"""

#: ...and as docs/STATUS.md carried it, wrapped across two lines so the check is
#: held to reading paragraphs rather than lines.
OVERCLAIM_STATUS = """# Status

**Exercised end to end** on this machine and, on every push, across the CI
matrix: the analyzer and its rules, the CLI, and all four parity gates.
"""

#: The fix: green and the matrix may sit as close as they like, once the same
#: breath says whether the matrix ran.
HONEST_README = """# Demo

## What is verified, and what is not

Every gate above is green on the build machine. The CI matrix has not run:
GitHub has refused to start a job on this branch since its Actions billing was
blocked, so nothing here has run on Windows or on macOS.
"""

#: scripts/README.md row 25's shape - a claim about one run that did execute.
RUN_ID_README = """# Demo

Both figures are arithmetic over the per-job durations of the last full green
push (run 34454599867), which ran 12 jobs for about 44 billable minutes.
"""

#: A doc may describe the matrix all it likes when it claims nothing green.
DESCRIPTIVE_README = """# Demo

The CI matrix runs a cheap tier on every push and the full matrix on every pull
request: ubuntu, Windows and macOS, Python 3.10-3.13, two Node versions.
"""


def test_the_readme_overclaim_is_caught():
    """DOCS-CI-OVERCLAIM: README asserted the matrix as achieved verification
    while every job of every push on the branch came back unstarted."""
    root = _tree({"README.md": OVERCLAIM_README})
    try:
        problems, _ = check_docs.run(root)
        assert len(problems) == 1, problems
        assert "DOCS-CI-OVERCLAIM" in problems[0], problems
        assert "README.md:5" in problems[0], problems
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_status_overclaim_is_caught_across_a_line_wrap():
    """The claim was wrapped: "across the CI / matrix". Lines would miss it."""
    problems: list = []
    doc_claims.check_document("docs/STATUS.md", OVERCLAIM_STATUS.splitlines(),
                              problems)
    assert len(problems) == 1, problems
    assert "docs/STATUS.md:3" in problems[0], problems


def test_naming_the_block_in_the_same_breath_is_not_a_claim():
    """The fix has to pass, or the check would forbid saying the true thing."""
    root = _tree({"README.md": HONEST_README})
    try:
        assert check_docs.run(root)[0] == []
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_green_push_named_by_run_id_is_not_a_matrix_claim():
    """scripts/README.md row 25 says "the last full green push (run N)" -- a
    claim about one run that really did execute, and not this defect."""
    root = _tree({"README.md": RUN_ID_README})
    try:
        assert check_docs.run(root)[0] == []
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_describing_the_matrix_without_claiming_it_green_is_fine():
    root = _tree({"README.md": DESCRIPTIVE_README})
    try:
        assert check_docs.run(root)[0] == []
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_real_repo_makes_no_such_claim():
    """The tree this ships in must not carry the defect it was written for."""
    problems: list = []
    root = Path(__file__).resolve().parent.parent
    for rel in ("README.md", "docs/STATUS.md", "scripts/README.md", "CHANGELOG.md"):
        lines = io.open(root / rel, encoding="utf-8", newline="").read().splitlines()
        doc_claims.check_document(rel, lines, problems)
    assert problems == [], problems


def main() -> int:
    import test_check_docs
    failed = test_check_docs.run_module(sys.modules[__name__])
    print(("%d test(s) failed" % failed) if failed else "doc_claims self-test OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
