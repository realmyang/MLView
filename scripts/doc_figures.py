#!/usr/bin/env python
"""Checks 13, 14, 15 and 23 of the doc gate: figures a document keeps quoting.

`doc_numbers.py` (checks 9-11) compares a number in the prose with a
machine-readable copy in the tree. These three do the same for the three figures
that rot fastest in `README.md`, `docs/STATUS.md` and `scripts/README.md` -- the
documents that claim to say what is verified *today*. Stdlib only, offline.

Only those three "living" documents are checked by 13-15. `docs/CONTRACTS.md`
amendments, `docs/ROADMAP.md` landed notes and the frozen design records are
dated records of what was true when they were written; holding them to today's
tree would ask the history to be rewritten, which is the opposite of the point.
Check 23 is the single, named exception, and §16.4 is why: every figure in
CONTRACTS is supposed to name the command that settles it, and §7's diff counts
are the one paragraph that states four bare numbers instead. It reads that
paragraph and nothing else in the file.

13. **A summary table that disagrees with the run below it.** The Components
    table at the top of `docs/STATUS.md` is the document's headline: four rows,
    each quoting a package's test count. In Sprint 5 it was refreshed in wave 1
    and left alone in waves 2 and 3, so every row was stale and each was
    contradicted 1900 lines further down by the same file's own gate paragraph
    (`analyzer **2024 passed / 4 skipped**` against a table saying 1855)
    (REV5-05). Both figures are in one file, so the file may settle it: the
    per-package counts in the Components table must equal the counts in the LAST
    `**Gates` paragraph of the same document. The same check holds the table's
    bundled-core file count (`core/mlview` at **96** files) to the number of
    syncable files `tools/sync-core.py` actually copies out of
    `analyzer/src/mlview` -- the figure `tools/verify.py --all`'s `vsix: synced
    core` row prints, which had drifted to 88 by the same mechanism.

14. **A fixture battery quoted at the size it used to be.** `README.md` called
    `contracts/scope.cases.json` "the ten-selector battery" for three sprints
    while the file grew to 13 projecting cases, 7 error cases and 5 promoted
    counterexamples; `scripts/README.md` and `docs/STATUS.md` carried the same
    "ten selectors plus six error codes" (REV5-08). The battery is a JSON file
    with a `kind` on every case, so the count is not a matter of opinion: any
    claim of `N selectors` / `N projections` / `N error cases` /
    `N promoted counterexamples` in a block that names the file is held to it.
    Spelled-out numbers count -- "the ten-selector battery" is the claim that
    started this. Check 8's `at the time` escape applies here too, and the
    bundled-core count of check 13 is read out of table rows only, so a
    paragraph recording what a past round measured stays as it was written.

15. **Two gate documents naming different runs for the same claim.** "The last
    full green push" is a singular: `README.md` cited run 34422156964 for it
    while `scripts/README.md` row 25 cited 34441571480, a later and greener run,
    in the same commit (REV5-07). Every run id quoted next to that phrase must
    therefore be the same id, whichever document quotes it -- unless the block
    says `at the time`, which is how the paragraph that *narrates* this incident
    is allowed to keep quoting both.

23. **The one paragraph of the contract that states a bare figure.** §7's
    *"The shipped sample pair, measured"* recorded `summary.nodes` as
    **25 added / 15 removed / 8 changed / 31 unchanged** with the headline
    `+25 nodes · -15 nodes · ...`, and named `python -m mlview diff` as "the
    authority for these four counts now" -- while the authority said
    26 / 15 / 8 / 36 and the two tests §7 names as its only pins had *already*
    been updated to say so (REV-04). The section's own JSONC sketch carried a
    third set again, `-16 nodes`, from a round before that. One command, one
    contract section, three mutually inconsistent figure sets, and no check
    could see any of them because CONTRACTS.md is in `check_docs.SKIP` by
    design. `analyzer/tests/core/test_diff.py` asserts the four node counts, the
    four edge counts and the headline as literals, so it is the machine-readable
    copy this check needs; it is **read as text**, never imported, the way
    `doc_surfaces.py` parses `core/selectors.py`.

Imported by `scripts/check_docs.py`; `scripts/test_doc_figures.py` tests it.
"""
from __future__ import annotations

import io
import json
import re
from pathlib import Path

#: The documents that describe the tree as it is *now*, and so may be held to it.
LIVING_DOCS = ("README.md", "docs/STATUS.md", "scripts/README.md")
#: check 8's escape, reused verbatim by checks 14 and 15: a block that says in
#: words that it is recording what was true *at the time* is a record, not a
#: claim about the tree today, and rewriting it would erase the record.
HISTORICAL_RE = re.compile(r"\bat the time\b", re.I)


def _lines(path: Path) -> list:
    return io.open(path, encoding="utf-8", newline="").read().splitlines()


def _blocks(lines):
    """[(first line no, [lines])] for every run of non-blank lines.

    A Markdown table row is a block of its own: consecutive rows are one
    paragraph to a blank-line split, but each row is a separate claim.
    """
    out, start, buf = [], 0, []
    for n, line in enumerate(lines, 1):
        if not line.strip():
            if buf:
                out.append((start, buf))
                start, buf = 0, []
            continue
        if line.lstrip().startswith("|"):
            if buf:
                out.append((start, buf))
                start, buf = 0, []
            out.append((n, [line]))
            continue
        if not buf:
            start = n
        buf.append(line)
    if buf:
        out.append((start, buf))
    return out


# ----------------------------------------------------------------- check 13
STATUS_DOC = "docs/STATUS.md"
#: (package name as the gate paragraph spells it, the Components row's first cell)
PACKAGE_ROWS = (
    ("analyzer", re.compile(r"^\|\s*Analyzer\b")),
    ("webview", re.compile(r"^\|\s*Viewer\b")),
    ("vscode-extension", re.compile(r"^\|\s*VS Code extension\b")),
    ("claude-plugin", re.compile(r"^\|\s*Claude Code plugin\b")),
)
# `**2024 passed, 4 skipped**`, `**521 tests pass**`, `**370 passed / 7 skipped**`,
# `**372 tests**` -- one shape, because the table and the paragraph word it
# differently and both are the same measurement.
COUNT = (r"\*\*(\d+)\s+(?:passed|tests?)(?:\s+pass(?:ed)?)?"
         r"(?:\s*[,/]\s*(\d+)\s+skipped)?\*\*")
COUNT_RE = re.compile(COUNT)
GATE_PARA_RE = re.compile(r"^\*\*Gates\b")
CORE_FILES_RE = re.compile(r"`core/mlview`\s+at\s+\*\*(\d+)\*\*\s+files")
# Only a table row makes a *summary* claim. The prose around it narrates what a
# past round measured ("this file said `core/mlview` at **79** files while
# `verify.py` printed **80**", the HOST-8 incident) and rewriting that would
# erase the record -- the same reasoning as check 8's `at the time` escape.
SUMMARY_ROW_RE = re.compile(r"^\s*\|")


def _paragraph_from(lines, index) -> str:
    """`lines[index:]` up to the first blank line, joined -- prose wraps."""
    out = []
    for line in lines[index:]:
        if not line.strip():
            break
        out.append(line)
    return " ".join(out)


def _core_file_count(root: Path):
    """How many files `tools/sync-core.py` copies out of `analyzer/src/mlview`.

    Imported rather than reimplemented: the skip rules (`__pycache__`, `tests`,
    `*.pyc`) belong to that script, and a second copy of them here would be one
    more thing to drift.
    """
    script = root / "tools" / "sync-core.py"
    source = root / "analyzer" / "src" / "mlview"
    if not script.is_file() or not source.is_dir():
        return None
    import importlib.util  # noqa: PLC0415 - only this check needs it

    spec = importlib.util.spec_from_file_location("mlview_sync_core_docs", str(script))
    if spec is None or spec.loader is None:  # pragma: no cover - unreachable in tree
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        return len(module._rel_files(str(source)))
    except Exception:  # pragma: no cover - a broken sync-core fails its own gate
        return None


def check_summary_table(root: Path, problems: list) -> None:
    """REV5-05: the Components table and the newest gate paragraph, one file."""
    doc = root / STATUS_DOC
    if not doc.is_file():
        return
    lines = _lines(doc)

    gate_at = [n for n, line in enumerate(lines) if GATE_PARA_RE.match(line)]
    if gate_at:
        paragraph = _paragraph_from(lines, gate_at[-1])
        for package, row_re in PACKAGE_ROWS:
            gate = re.search(r"\b%s\s+%s" % (re.escape(package), COUNT), paragraph)
            row = next(((n, COUNT_RE.search(line))
                        for n, line in enumerate(lines, 1) if row_re.match(line)), None)
            if not gate or not row or not row[1]:
                continue
            n, found = row
            for what, said, holds in (("tests", found.group(1), gate.group(1)),
                                      ("skips", found.group(2), gate.group(2))):
                if said is None or holds is None or said == holds:
                    continue
                problems.append(
                    "%s:%d: the Components table says %s has %s %s, but this "
                    "file's own newest `**Gates` paragraph (line %d) says %s -- "
                    "the headline summary may not disagree with the run it "
                    "summarises; re-run the suite and update both (REV5-05)"
                    % (STATUS_DOC, n, package, said, what, gate_at[-1] + 1, holds))

    files = _core_file_count(root)
    if files is None:
        return
    for n, line in enumerate(lines, 1):
        if not SUMMARY_ROW_RE.match(line):
            continue
        found = CORE_FILES_RE.search(line)
        if found and int(found.group(1)) != files:
            problems.append(
                "%s:%d: says the VSIX bundles `core/mlview` at %s files, but "
                "`tools/sync-core.py` copies %d out of analyzer/src/mlview -- "
                "that is the number `python tools/verify.py --all` prints on its "
                "`vsix: synced core` row (REV5-05)"
                % (STATUS_DOC, n, found.group(1), files))


# ----------------------------------------------------------------- check 14
SCOPE_CASES = "contracts/scope.cases.json"
WORDS = ("zero one two three four five six seven eight nine ten eleven twelve "
         "thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty").split()
NUMBER = r"(\d+|" + "|".join(WORDS) + r")"
# The nouns are deliberately narrow. A bare `N cases` is not one of them: STATUS
# and the roadmap are full of sentences about fuzz cases, corpus cases and test
# cases that have nothing to do with this file's size.
KINDS = (("projecting case", "project"), ("projection", "project"),
         ("selector", "project"), ("error case", "error"), ("error code", "error"),
         ("promoted counterexample", "fuzz"))
CLAIM_RE = re.compile(NUMBER + r"[- ](" + "|".join(k for k, _ in KINDS) + r")s?\b",
                      re.I)
KIND_OF = dict(KINDS)


def _number(token: str) -> int:
    return int(token) if token.isdigit() else WORDS.index(token.lower())


def _battery(root: Path):
    """`{kind: count}` straight out of the fixture file, or None."""
    path = root / SCOPE_CASES
    if not path.is_file():
        return None
    try:
        data = json.loads(io.open(path, encoding="utf-8").read())
    except ValueError:  # pragma: no cover - a corrupt battery fails its own gate
        return None
    cases = data.get("cases") or []
    return {"project": sum(1 for c in cases if c.get("kind") == "project"),
            "error": sum(1 for c in cases if c.get("kind") == "error"),
            "fuzz": len(data.get("fuzzCases") or [])}


def check_scope_battery(root: Path, paths, problems: list) -> None:
    """REV5-08: the battery is a JSON file, so its size is not an opinion."""
    counts = _battery(root)
    if counts is None:
        return
    for path in paths:
        rel = path.relative_to(root).as_posix()
        if rel not in LIVING_DOCS:
            continue
        for start, block in _blocks(_lines(path)):
            text = " ".join(block)
            if SCOPE_CASES not in text or HISTORICAL_RE.search(text):
                continue
            for found in CLAIM_RE.finditer(text):
                kind = KIND_OF[found.group(2).lower()]
                said, holds = _number(found.group(1)), counts[kind]
                if said == holds:
                    continue
                problems.append(
                    "%s:%d: says the scope battery holds %s %s(s), but `%s` holds "
                    "%d -- the file is the count, and it grows every time the "
                    "fuzzer promotes a counterexample (REV5-08)"
                    % (rel, start, found.group(1), found.group(2), SCOPE_CASES, holds))


# ----------------------------------------------------------------- check 15
GREEN_PUSH_RE = re.compile(r"last full green push", re.I)
RUN_ID_RE = re.compile(r"\brun\s+(\d{6,})\b")


def check_one_green_push(root: Path, paths, problems: list) -> None:
    """REV5-07: "the last full green push" names one run, in every document."""
    cited: dict = {}
    for path in paths:
        rel = path.relative_to(root).as_posix()
        if rel not in LIVING_DOCS:
            continue
        for start, block in _blocks(_lines(path)):
            text = " ".join(block)
            if not GREEN_PUSH_RE.search(text) or HISTORICAL_RE.search(text):
                continue
            for found in RUN_ID_RE.finditer(text):
                cited.setdefault(found.group(1), "%s:%d" % (rel, start))
                break  # the first id in the block is the one the phrase claims
    if len(cited) > 1:
        problems.append(
            "the docs name %d different runs as the last full green push -- %s. "
            "One push is the last one; `gh run list --branch <branch>` settles "
            "which, and both gate documents then quote it (REV5-07)"
            % (len(cited), "; ".join("%s says run %s" % (where, run)
                                     for run, where in sorted(cited.items()))))


#: The contract section check 23 reads, and the test that pins its figures.
CONTRACTS_DOC = "docs/CONTRACTS.md"
DIFF_PIN_TEST = "analyzer/tests/core/test_diff.py"
#: `## 7. ` up to the next `## ` heading. Anchored on the heading number so the
#: check cannot wander into §17's errata, which quote superseded figures on
#: purpose and must keep quoting them.
CONTRACTS_S7_RE = re.compile(r"^## 7\.[^\n]*\n(.*?)(?=^## )", re.M | re.S)
#: `summary["nodes"] == {"added": 26, "removed": 15, ...}` in the pinning test.
PIN_DICT_RE = re.compile(
    r"""summary\[.(nodes|edges).\]\s*==\s*\{(.*?)\}""", re.S)
PIN_FIELD_RE = re.compile(r"""["'](\w+)["']\s*:\s*(\d+)""")
PIN_HEADLINE_RE = re.compile(r"""summary\[.headline.\]\s*==\s*["'](.+?)["']""")
#: ...and the three shapes §7 states them in.
PROSE_NODES_RE = re.compile(
    r"\*\*(\d+) added / (\d+) removed / (\d+) changed / (\d+) unchanged\*\*")
PROSE_EDGES_RE = re.compile(r"`summary\.edges` is `(\d+) / (\d+) / (\d+) / (\d+)`")
PROSE_HEADLINE_RE = re.compile(r'\+\d+ nodes [^`"]*?\d+ fixed')


def _diff_pins(root: Path):
    """The four node counts, the four edge counts and the headline, read as text
    out of the analyzer's own test. Returns None when the test has been renamed
    or restructured -- a check that guesses is worse than a check that abstains,
    and `test_the_real_pin_is_still_readable_and_the_real_contract_agrees` in
    the suite fails loudly if it ever does abstain on the real tree."""
    pin = root / DIFF_PIN_TEST
    if not pin.is_file():
        return None
    text = io.open(pin, encoding="utf-8", newline="").read()
    counts = {}
    for kind, body in PIN_DICT_RE.findall(text):
        counts[kind] = {k: int(v) for k, v in PIN_FIELD_RE.findall(body)}
    headline = PIN_HEADLINE_RE.search(text)
    if not headline or set(counts) != {"nodes", "edges"}:
        return None
    for kind in ("nodes", "edges"):
        if set(counts[kind]) != {"added", "removed", "changed", "unchanged"}:
            return None
    return counts, headline.group(1)


def check_contract_diff_figures(root: Path, problems: list) -> None:
    """REV-04: §7's four counts against the test §7 names as their pin."""
    doc = root / CONTRACTS_DOC
    pins = _diff_pins(root)
    if not doc.is_file() or pins is None:
        return
    counts, headline = pins
    section = CONTRACTS_S7_RE.search(
        io.open(doc, encoding="utf-8", newline="").read())
    if section is None:
        return
    body = section.group(1)
    where = "%s §7" % CONTRACTS_DOC

    found = PROSE_NODES_RE.search(body)
    if found:
        said = [int(g) for g in found.groups()]
        want = [counts["nodes"][k]
                for k in ("added", "removed", "changed", "unchanged")]
        if said != want:
            problems.append(
                "%s: says `summary.nodes` is %s over the shipped sample pair; "
                "`%s` asserts %s. `python -m mlview diff` settles it and §7 says "
                "so itself (check 23, REV-04)"
                % (where, " / ".join(map(str, said)), DIFF_PIN_TEST,
                   " / ".join(map(str, want))))

    found = PROSE_EDGES_RE.search(body)
    if found:
        said = [int(g) for g in found.groups()]
        want = [counts["edges"][k]
                for k in ("added", "removed", "changed", "unchanged")]
        if said != want:
            problems.append(
                "%s: says `summary.edges` is %s; `%s` asserts %s (check 23, "
                "REV-04)" % (where, " / ".join(map(str, said)), DIFF_PIN_TEST,
                             " / ".join(map(str, want))))

    # Every headline in the section -- the prose one AND the JSONC sketch's
    # illustrative one, which is how three different figure sets got into one
    # section in the first place.
    for quoted in sorted(set(PROSE_HEADLINE_RE.findall(body))):
        if quoted.replace("\u2212", "-") != headline.replace("\u2212", "-"):
            problems.append(
                "%s: quotes the diff headline as %r; `%s` asserts %r. An "
                "illustrative headline in the schema sketch is still a figure a "
                "reader will copy (check 23, REV-04)"
                % (where, quoted, DIFF_PIN_TEST, headline))


# ------------------------------------ check 24: the adjudicated false positives
#: The public corpus's own record. Every verdict in it was written by a person
#: who read the cited source, which is what makes the count quotable at all.
ADJUDICATION = "analyzer/tests/public_corpus/adjudication.json"
#: A paragraph only states this figure when it is talking about that gate. The
#: labelled corpus's "zero false positives" is a different measurement in the same
#: words, and it lives in paragraphs that name neither the corpus nor the file.
FP_CONTEXT_RE = re.compile(r"public\s+corpus|adjudicat|nobody\s+thought\s+to\s+label",
                           re.I)
FP_COUNT_RE = re.compile(r"\*{0,2}([A-Za-z]+|\d+)\*{0,2}\s+(?:adjudicated\s+)?"
                         r"false\s+positives?\b", re.I)
#: ...and the shape the wrong sentence was actually written in. "It is the only
#: gate that can see a false positive nobody thought to label, and it has caught
#: four" states the figure without repeating the noun, which is exactly how it
#: escaped every reading of the page (PUB-R02).
FP_CAUGHT_RE = re.compile(r"\b(?:has\s+)?caught\s+\*{0,2}([A-Za-z]+|\d+)\*{0,2}\b", re.I)
#: The escape, and the same one check 22's mirror needs: a paragraph that names
#: this check is documenting the rule, not stating the figure. `scripts/README.md`
#: row 18c quotes the wrong sentence verbatim so a reader knows what was wrong,
#: and a gate that fails its own documentation for quoting it teaches people to
#: stop writing the documentation.
FP_META_RE = re.compile(r"check\s*24|PUB-R02|doc_figures", re.I)
#: Written-out numbers count: "it has caught four" was the whole of PUB-R02, and a
#: check that only reads digits would have passed the sentence that was wrong.
WORD_NUMBERS = {"zero": 0, "no": 0, "one": 1, "two": 2, "three": 3, "four": 4,
                "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
                "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
                "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
                "nineteen": 19, "twenty": 20}


def _adjudicated_false_positives(root: Path):
    """How many verdicts in the public corpus's record are false positives.

    None when the file is unreadable or shaped differently than expected -- a
    check that guesses is worse than one that abstains, and the suite asserts it
    does not abstain on the real tree.
    """
    path = root / ADJUDICATION
    if not path.is_file():
        return None
    try:
        data = json.loads(io.open(path, encoding="utf-8").read())
        verdicts = data["verdicts"]
        return sum(1 for v in verdicts.values() if v.get("verdict") == "false-positive")
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


def check_false_positive_count(root: Path, paths, problems: list) -> None:
    """Check 24: a prose count of the false positives the public corpus caught,
    against the file that holds them.

    `docs/STATUS.md` said *four* in two places while `adjudication.json` held
    eleven and `README.md` said eleven -- the current-state page contradicting the
    front page by a factor of nearly three, on the number that is the whole
    argument for the gate existing. The last commit before the review was titled
    *"Correct the README's count of false positives the public corpus caught"*;
    the same correction was not carried to STATUS. Deriving it is the fix, because
    the figure moves again the next time the gate catches something (PUB-R02).
    """
    want = _adjudicated_false_positives(root)
    if want is None:
        return
    for path in paths:
        rel = path.relative_to(root).as_posix()
        if rel not in LIVING_DOCS:
            continue
        for start, block in _blocks(_lines(path)):
            text = " ".join(block)
            if (not FP_CONTEXT_RE.search(text) or HISTORICAL_RE.search(text)
                    or FP_META_RE.search(text)):
                continue
            for found in list(FP_COUNT_RE.finditer(text)) + list(FP_CAUGHT_RE.finditer(text)):
                token = found.group(1).lower()
                said = int(token) if token.isdigit() else WORD_NUMBERS.get(token)
                if said is None or said == want:
                    continue
                problems.append(
                    "%s:%d: says the public corpus caught %s false positive(s); "
                    "`%s` holds %d with verdict `false-positive` -- the count is "
                    "in the file, so quote it or drop the figure (check 24, "
                    "PUB-R02)" % (rel, start, found.group(1), ADJUDICATION, want))


# ------------------------------- check 25: the third-party notice's own versions
NOTICES = "THIRD_PARTY_NOTICES.md"
#: The two packages the viewer bundle inlines, and where their real versions live.
NOTICE_PACKAGES = ("@dagrejs/dagre", "@dagrejs/graphlib")
NOTICE_VERSION_RE = "## %s (\\S+) — MIT"


def check_notice_versions(root: Path, problems: list) -> None:
    """Check 25: the versions `THIRD_PARTY_NOTICES.md` names are the ones on disk.

    This is the one public-facing document where a wrong version number is a
    licence-compliance problem rather than a typo, and until PUB-R11 it was the
    one community file no check read at all. It abstains when `webview/node_modules`
    has not been installed -- the doc gate runs in a CI job that never touches it.
    """
    notices = root / NOTICES
    if not notices.is_file():
        return
    text = io.open(notices, encoding="utf-8").read()
    for package in NOTICE_PACKAGES:
        manifest = root / "webview" / "node_modules" / Path(package) / "package.json"
        if not manifest.is_file():
            continue  # not installed here; nothing to compare against
        try:
            installed = json.loads(io.open(manifest, encoding="utf-8").read())["version"]
        except (ValueError, KeyError):  # pragma: no cover - a corrupt package.json
            continue
        said = re.search(NOTICE_VERSION_RE % re.escape(package), text)
        if not said:
            problems.append(
                "%s: names no version for `%s`, which the viewer bundle inlines "
                "and every artifact redistributes -- the section heading is "
                "`## %s <version> — MIT` (check 25, PUB-R11)"
                % (NOTICES, package, package))
        elif said.group(1) != installed:
            problems.append(
                "%s: says `%s` %s; `webview/node_modules` has %s. A notice that "
                "names the wrong version is a licence claim about software that "
                "is not the software shipped (check 25, PUB-R11)"
                % (NOTICES, package, said.group(1), installed))


def run(root: Path, paths, problems: list) -> None:
    """All six checks, in the order the docstring numbers them."""
    check_summary_table(root, problems)
    check_scope_battery(root, paths, problems)
    check_one_green_push(root, paths, problems)
    check_contract_diff_figures(root, problems)
    check_false_positive_count(root, paths, problems)
    check_notice_versions(root, problems)
