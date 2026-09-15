#!/usr/bin/env python
"""Check 16 of the doc gate: a gate claimed green on a CI matrix that never ran.

`doc_numbers.py` (checks 9-11) and `doc_figures.py` (13-15) hold a number in the
prose against a machine-readable copy in the tree. This one holds a *claim* that
has no copy anywhere: what the reader is told was verified, against what the
repository's own record says was verified. Stdlib only, offline.

16. **A gate claimed green on CI that CI never ran** (DOCS-CI-OVERCLAIM).
    `README.md` opened "What is verified, and what is not" with *"Every gate
    above is green on the build machine **and on the CI matrix**"*, and
    `docs/STATUS.md` said the listed surfaces were *"exercised end to end on this
    machine and, on every push, **across the CI matrix**"*. Meanwhile every job
    of every push on the branch came back *"The job was not started because
    recent account payments have failed or your spending limit needs to be
    increased"* -- so nothing in the tree had run on Python 3.10, 3.11 or 3.12,
    on a Windows runner or on a macOS runner, and the five full-tier jobs had
    never run at all. `CHANGELOG.md` and `scripts/README.md` row 25 said so
    plainly; the two documents a newcomer reads first did not. That is this
    project's standing criterion -- *state what you could not check* -- failing
    on the one page where it is read first.

    The rule is narrow on purpose. A document may describe the matrix, name it,
    say what it would cover, or report that one identified run was green. What it
    may not do is put a **green claim and the matrix in the same breath** without
    saying in that same breath whether the matrix ran. Saying it did not run is
    the escape, and it is the whole fix.

Only the "living" documents are checked, for the reason `doc_figures.py` gives:
a dated record of what was true when it was written is not a claim about today.

Run:  imported by `scripts/check_docs.py`; its cases are in
      `scripts/test_doc_claims.py`, run from `scripts/test_check_docs.py`.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

#: A green claim and the CI matrix within one clause of each other. The distance
#: is bounded because `scripts/README.md` row 25 says "the last full green push
#: (run 34454599867)" -- a claim about one run that really did execute, and
#: exactly what this must never flag.
GREEN_CI_RE = re.compile(
    r"\bgreen\b[^.]{0,45}\bCI\s+matrix\b"
    r"|\bCI\s+matrix\b[^.]{0,45}\bgreen\b"
    r"|\bgreen\b\s+(?:on|across)\s+CI\b"
    r"|\bacross\s+the\s+CI\s+matrix\b", re.I)

#: ...unless the same breath says whether it ran. This is the fix passing.
GREEN_CI_OK_RE = re.compile(
    r"has\s+not\s+run|have\s+not\s+run|never\s+run|not\s+started|would\s+not"
    r"|is\s+blocked|unstarted|no\s+CI\s+job", re.I)

MESSAGE = ("%s:%d: claims a gate is green on CI (%r), but no CI job has started "
           "on this branch -- say what the matrix did run, or name the block, "
           "the way CHANGELOG.md and scripts/README.md row 25 do "
           "(DOCS-CI-OVERCLAIM)")


def paragraphs(lines):
    """(first line number, the paragraph joined onto one line) for each block of
    consecutive non-blank lines.

    Paragraphs rather than lines, because the claim this check exists for was
    wrapped across two of them: "green on the build machine / and on the CI
    matrix". `check_docs.bullets()` is the list-item twin of this.
    """
    start, buf = 0, []
    for n, line in enumerate(lines, 1):
        if line.strip():
            if not buf:
                start = n
            buf.append(line.strip())
            continue
        if buf:
            yield start, " ".join(buf)
        buf = []
    if buf:
        yield start, " ".join(buf)


def check_document(rel: str, lines, problems: list) -> None:
    """Check 16 over one document's lines, appending to `problems`."""
    for n, text in paragraphs(lines):
        found = GREEN_CI_RE.search(text)
        if not found or GREEN_CI_OK_RE.search(text):
            continue
        problems.append(MESSAGE % (rel, n, found.group(0)[:70]))


def run(root: Path, paths, problems: list) -> None:
    """The entry point `check_docs.run` calls, with the living documents."""
    for path in paths:
        try:
            lines = io.open(path, encoding="utf-8", newline="").read().splitlines()
        except OSError:  # pragma: no cover - check_docs only passes real files
            continue
        check_document(Path(path).relative_to(root).as_posix(), lines, problems)
