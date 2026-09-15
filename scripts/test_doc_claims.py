#!/usr/bin/env python
"""Tests for scripts/doc_claims.py: check 22, DOCS-CI-OVERCLAIM.

Each case builds a throwaway tree in a temp directory and runs the whole doc
gate against it with --root, so nothing here depends on the state of the real
repo -- the same shape as `scripts/test_check_docs.py`, whose `main()` runs this
module too.

The last two cases are the exception and they are deliberate. REV-01: this file
and `doc_claims.py` were written once, cited twice by name in `docs/CONTRACTS.md`
§16.4 and §17 E28, and then not carried onto the branch that shipped -- so the
contract asserted a running gate that was not in the tree, and the defect the
gate exists for was ungated again. `test_the_gate_is_wired_into_check_docs`
pins the wiring, and `test_contracts_names_no_script_that_is_missing` pins the
citation, because `docs/CONTRACTS.md` is in `check_docs.SKIP` by design and no
other check reads it at all.

Run:  python scripts/test_doc_claims.py   (or: pytest scripts/test_doc_claims.py)
"""
from __future__ import annotations

import io
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_docs  # noqa: E402
import doc_claims  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


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

#: The second escape, and the one this check was blind to until the matrix
#: actually ran: green and "CI matrix" in one breath, with the run named. The
#: paragraph above never puts the two words near each other, so it passed
#: without ever exercising the escape it was written for.
GREEN_MATRIX_WITH_RUN = """# Demo

Every gate above is green across the CI matrix: run 34975667772 took all
thirteen jobs on ubuntu, Windows and macOS, Python 3.10-3.13 and Node 20/22.
"""

#: ...and the same sentence with the run id taken out, which must still fail.
GREEN_MATRIX_WITHOUT_RUN = """# Demo

Every gate above is green across the CI matrix: all thirteen jobs on ubuntu,
Windows and macOS, Python 3.10-3.13 and Node 20/22.
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


def test_a_green_matrix_is_sayable_once_the_run_is_named():
    """The escape the rule always claimed and the code never had.

    Until 2026-09-15 no run on any branch had started a job, so every honest
    sentence about the matrix was a negative one and the negations were enough.
    Once run 34975667772 took all thirteen jobs, a check that accepted only
    "the matrix has not run" would have forbidden the true sentence and
    permitted nothing but the false one.
    """
    root = _tree({"README.md": GREEN_MATRIX_WITH_RUN})
    try:
        assert check_docs.run(root)[0] == []
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_same_claim_with_no_run_named_is_still_caught():
    """The escape is the run id, not the wording: take it out and this is the
    defect again, which is what keeps the new branch from being a hole."""
    root = _tree({"README.md": GREEN_MATRIX_WITHOUT_RUN})
    try:
        problems, _ = check_docs.run(root)
        assert len(problems) == 1, problems
        assert "DOCS-CI-OVERCLAIM" in problems[0], problems
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
    for rel in ("README.md", "docs/STATUS.md", "scripts/README.md", "CHANGELOG.md"):
        lines = io.open(REPO / rel, encoding="utf-8", newline="").read().splitlines()
        doc_claims.check_document(rel, lines, problems)
    assert problems == [], problems


def test_the_gate_is_wired_into_check_docs():
    """REV-01: the module existing is not the gate running. `check_docs.run`
    must call it, or the whole file is decoration -- which is precisely how the
    check went missing the first time."""
    source = io.open(REPO / "scripts/check_docs.py", encoding="utf-8").read()
    assert "import doc_claims" in source, "check_docs.py does not import the module"
    assert "doc_claims.run(" in source, "check_docs.run() never calls check 22"
    # And end to end, through the public entry point, over a real tree.
    root = _tree({"README.md": OVERCLAIM_README})
    try:
        problems, _ = check_docs.run(root)
        assert any("DOCS-CI-OVERCLAIM" in p for p in problems), problems
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_contracts_names_no_script_that_is_missing():
    """REV-01, the other half: `docs/CONTRACTS.md` cited `scripts/doc_claims.py`
    by name while the file was not in the tree. CONTRACTS.md is in
    `check_docs.SKIP` -- normative and frozen, so checks 1-2 never read it -- and
    that exemption is exactly why a contract can name a file that does not
    exist. A contract may describe a build; it may not invent one."""
    text = io.open(REPO / "docs/CONTRACTS.md", encoding="utf-8").read()
    named = sorted(set(re.findall(r"`(scripts/[A-Za-z0-9_./-]+\.(?:py|sh|ps1))`", text)))
    assert named, "the citation pattern stopped matching; the check is now blind"
    missing = [rel for rel in named if not (REPO / rel).is_file()]
    assert missing == [], (
        "docs/CONTRACTS.md cites %s, which is not in the tree" % ", ".join(missing))
    assert "scripts/doc_claims.py" in named, (
        "§16.4 no longer names this gate; if it was removed on purpose, remove "
        "this assertion with it")


def main() -> int:
    import test_check_docs
    failed = test_check_docs.run_module(sys.modules[__name__])
    print(("%d test(s) failed" % failed) if failed else "doc_claims self-test OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
