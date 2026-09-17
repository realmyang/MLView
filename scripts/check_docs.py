#!/usr/bin/env python
"""Documentation gate: keep the prose honest about the tree it describes.

Twenty-three checks, all offline and stdlib-only. Checks 1-8, 12 and 21 live
here; the thirteen that compare a number, a list, or a command line in the prose
with the machine-readable copy the tree already holds live next door -- checks
9-11 and 19-20 in `scripts/doc_numbers.py`, checks 13-15 and 23 in
`scripts/doc_figures.py`, checks 16-18 in `scripts/doc_surfaces.py` -- and check
22, which holds a claim that has no copy anywhere at all, lives in
`scripts/doc_claims.py`. All four are summarised at the bottom of this list:

1. **Dead paths.** Every repo-relative path written in backticks or in a Markdown
   link inside a current-state doc must exist on disk. Catches renamed modules,
   moved fixtures and invented file names.
2. **Dead links.** Every relative Markdown link target must exist, in plan docs
   too.
3. **Stale failure claims.** A "known gaps" bullet that names a test file *and*
   says it fails is true only until someone fixes the test. When the named test
   file is in the tree and the suites are green, the claim has to go: the honesty
   section of a README is exactly where a stale claim costs the most. This is the
   regression gate for MLV-R1-006, where the README kept describing a
   `manifest.test.js` failure that had already been repaired.
4. **Unanchored gap bullets.** Check 3 only catches a claim shaped like "test X
   fails". A *behavioural* claim ("the gate is workspace-wide") sailed straight
   through it, which is how MLV-R2-109 happened: the README kept describing a
   workspace-wide framework gate long after `ctx.wrappers_for()` made it
   per-module. So every bullet under a "Known gaps" heading must now cite
   something this gate can check -- a repo path, or a code symbol -- in
   backticks. A rule code is not enough: `MLV301` says nothing about the tree.
   A claim nobody can check is a claim nobody can retire.
5. **Dead symbol citations.** Every backticked code symbol cited by such a bullet
   must still exist somewhere in the source tree. Rename `workspace.wrappers` to
   `wrappers_for` and the bullet that cited the old name fails the build, which
   is the moment to reread the sentence around it.
6. **Build-state claims inside a plan doc.** The frozen design records are
   link-checked only, on purpose: they say what was *planned*, and rewriting them
   to match the build erases the decision record. So a sentence in one of them
   that reports what the build currently *does* ("the breadcrumb is now built")
   is wrong twice over -- it overwrites the record, and it is exempt from checks
   1, 3, 4 and 5 by construction, so nothing would ever notice when it rots. This
   is the regression gate for MLV-R1-H08; the shipped behaviour belongs in
   `README.md` / `docs/STATUS.md`, which this gate does check.
7. **Line endings.** A POSIX shell script written with CRLF is broken on every
   platform it exists for: `#!/usr/bin/env sh<CR>` asks the kernel for a program
   literally named `sh<CR>`, and a stray CR rides on the end of every variable
   it assigns. Git Bash's `igncr` hides all of it on Windows, which is exactly
   why it ships. This is the regression gate for MLV-R2-H02: `scripts/e2e.sh`,
   the documented POSIX twin of `scripts/e2e.ps1`, was rewritten LF->CRLF and
   stayed green here while being unrunnable under dash. The same pass flipped
   two Markdown docs wholesale, which turned two small edits into 400-line
   rewrites and let a stale figure ride through review unseen -- so a checked
   doc may not *mix* the two conventions either.
8. **Disagreeing graph sizes.** `45 nodes, 39 edges` in one doc and
   `45 nodes / 45 edges` in another cannot both describe the demo graph. One
   run produces one graph, so every `N nodes / M edges` claim about
   `samples/vision_pipeline` (or the `.mlview/graph.json` it emits) has to
   agree with every other. This is the regression gate for MLV-R2-H05.
9. **A headline that disagrees with its own gate.** `docs/ACCURACY.md` quotes
   figures whose authoritative copy is `analyzer/tests/accuracy/baseline.json`.
10. **An artifact upload that silently uploads nothing**, because its path is
    hidden and `include-hidden-files` was not set.
11. **A step count that is not the number of steps** either e2e driver runs.
12. **A shipped roadmap item that the roadmap does not say shipped.** Seven of
    Sprint 4's NEXT items landed with a section in `docs/STATUS.md` and nothing
    at all under their own `docs/ROADMAP.md` heading (PROC-01). That is not
    bookkeeping: the roadmap's own framing -- *every analyzer change must state
    what it could not analyze* -- is discharged in the `**Landed ...**` notes,
    and the acceptance clause a change deviated from is written in the roadmap,
    not in STATUS. So when a `docs/STATUS.md` paragraph opens by naming a
    roadmap item (`**FW-RECOG -- ...`, `**PERF-03, the relevance prefilter**`),
    that item's roadmap section must carry a `**Landed` note. A landed note also
    has to sit *inside* an item's section: H3's was written below the `### LATER`
    divider, where it read as an item of its own.

13. **A summary table that disagrees with the run below it**: `docs/STATUS.md`'s
    Components table against the newest `**Gates` paragraph of the same file, and
    its bundled-core file count against the tree.
14. **A fixture battery quoted at the size it used to be**, against
    `contracts/scope.cases.json`.
15. **Two gate documents naming different runs** for "the last full green push".

16. **A selector the legacy CLI accepts that a legacy user-facing list does not
    advertise.** `pipeline:` (CONTRACTS 11.47) and `symbol:` were legal
    everywhere and missing from legacy CLI help, README guidance,
    `/mlview-issues`, and the legacy MCP server. The LLM-native `/mlview`
    command authors WorkflowDocument and is outside this static grammar gate.
17. **A generated directory a tool calls git-ignored that `.gitignore` does not
    cover**, so running the tool puts its whole download into `git status`.
18. **A `test` script that enumerates its test files and misses one**, so
    `npm test` reports a green suite that never ran the new regression test.

19. **A command line a CI job generates that its own tool would refuse**, checked
    by handing the arguments to that tool's `build_parser()`.
20. **A closed list of rule codes the code does not hold**, where the mechanism
    the prose is describing is rule-agnostic.

21. **A known gap waiting for something that has already landed.** Check 4 made
    every gap bullet cite a path or a symbol; a bullet may now cite one and still
    be false, because it names its own retirement condition and the condition is
    met. `README.md` said the `/mlview-issues` `Bash` fallback "groups only once
    the matching `--group-by` flag lands on `analyzer/src/mlview/cli.py`" while
    `mlview issues --group-by rule` had been printing the grouped table for two
    sprints (HOSTS-UX-R2-07). The bullet named the flag and the file in one
    clause, so the gate had everything it needed: when a gap says *once X lands
    on `<path>`* and X is already in that file, the bullet is the stale thing,
    not the build. Rephrase it as a statement of fact -- the check only fires on
    a landing clause, never on a bullet that describes what the code does today.

22. **A gate claimed green on a CI matrix that never ran**, with no sentence in
    the same breath naming the run that was green or saying whether the matrix
    ran at all -- **and its mirror**: a living document asserting the matrix has
    not run while another living document in the same tree names a run that was
    green. `docs/STATUS.md` carried both halves at once for a day (PUB-R01).
23. **The one paragraph of `docs/CONTRACTS.md` that states a bare figure**: §7's
    four diff counts and its headline, against the test §7 names as their pin.
24. **A prose count of the false positives the public corpus caught**, against
    `analyzer/tests/public_corpus/adjudication.json`. The current-state page said
    *four* while the file held eleven and `README.md` said eleven (PUB-R02).
25. **The versions `THIRD_PARTY_NOTICES.md` names**, against the packages under
    `webview/node_modules`. It abstains where they are not installed (PUB-R11).

`scripts/doc_numbers.py` carries checks 9-11 and 19-20, `scripts/doc_figures.py`
checks 13-15, 23, 24 and 25, `scripts/doc_surfaces.py` checks 16-18 and
`scripts/doc_claims.py` check 22 and its mirror, with the incident behind each.

Usage:  python scripts/check_docs.py [--root DIR] [--quiet]
Exit 0 when clean, 1 when a problem is found. The report goes to stdout.
"""
from __future__ import annotations

import argparse
import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import doc_claims  # noqa: E402  - sibling modules, after the sys.path fix above
import doc_figures  # noqa: E402
import doc_numbers  # noqa: E402
import doc_surfaces  # noqa: E402

DEFAULT_ROOT = Path(__file__).resolve().parent.parent

# Docs that describe the tree as it *is*: every path they name must exist, and
# they may not claim a green test fails.
# `THIRD_PARTY_NOTICES.md` is here since PUB-R11: it was the one public-facing
# community file no check read at all, and it is the file where a wrong version
# number is a licence-compliance problem rather than a typo. Check 25 holds its
# two versions to `webview/node_modules`; the path and claim checks apply to it
# like any other living document.
CURRENT_GLOBS = ("README.md", "docs/STATUS.md", "docs/ACCURACY.md",
                 "scripts/README.md", "*/README.md", "docs/rules/README.md",
                 "THIRD_PARTY_NOTICES.md")
# Docs that describe the tree as it was *planned*: frozen design records, checked
# for dead Markdown links only. Rewriting them to match the build would erase the
# record of what was decided. docs/CONTRACTS.md is normative and frozen, and is
# never held to this gate at all.
PLAN_GLOBS = ("docs/ARCHITECTURE.md", "docs/REQUIREMENTS.md",
              "docs/ISSUE_RULES.md", "docs/UX_DESIGN.md")
# `docs/CONTRACTS.md` is normative and carries the dated measurements of every
# amendment folded into it; a gate that forced those to be rewritten would make
# its own §17 errata impossible, which is why every figure in it names the
# command that settles it instead (CONTRACTS v1.1 §16.4).
#
# `docs/archive/` is the same decision one step further: an archived spec must
# keep, byte for byte, the text the rest of the tree was built against. Nothing
# under it is collected by the globs above today (they reach one directory deep);
# the entries below are belt and braces for the day one of them widens.
SKIP = {"docs/CONTRACTS.md",
        "docs/archive/README.md",
        "docs/archive/CONTRACTS-v1.0-amended.md"}

PATH_RE = re.compile(r"`([^`\s]+/[^`\s]*)`")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
# Generated, external or placeholder targets that are legitimately absent.
IGNORED_PREFIXES = ("http://", "https://", "mailto:", "//", "~", "#", ".mlview/",
                    "out/", "dist/", "node_modules/", "$", "%")
IGNORED_SUBSTRINGS = ("<", ">", "*", "{", "}", "|", "...", "..")
# A path claim must name a file of a kind this repo contains. That keeps JSON-RPC
# method names (`tools/call`, `tools/list`) and deliberate extension-less
# shorthands (`scripts/e2e`, meaning both .ps1 and .sh) out of the gate while
# every real file reference stays in it.
EXTENSIONS = (".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".json", ".md", ".ps1",
              ".sh", ".css", ".html", ".ipynb", ".yml", ".yaml", ".txt", ".vsix")

# --------------------------------------------------------------- gap bullets
# Source the symbol citations in a "Known gaps" bullet are checked against. Docs
# are deliberately excluded: a doc may not vouch for itself.
SOURCE_DIRS = ("analyzer", "claude-plugin", "contracts", "samples", "scripts",
               "tools", "vscode-extension", "webview")
SOURCE_EXTENSIONS = (".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".json")
SOURCE_SKIP_PARTS = {"node_modules", "out", "dist", "build", "coverage",
                     "__pycache__", ".mlview", ".git", ".venv"}

CODE_RE = re.compile(r"`([^`\n]+)`")
# A dotted name, optionally called with simple arguments: `wrappers_for`,
# `ctx.wrappers_for(loc.file)`, `mlview.showSpeculative`, `LoopUnit.depth`.
SYMBOL_TOKEN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*"
                             r"(?:\.[A-Za-z_][A-Za-z0-9_]*)*"
                             r"(?:\(\s*[A-Za-z0-9_.,'\"\s]*\))?$")
# Code-shaped, so plain English in backticks (`medium`, `high`) is left alone.
CODE_SHAPE_RE = re.compile(r"_|\.|[a-z][A-Z]")
CAMEL_RE = re.compile(r"[a-z][A-Z]")
# Short names (`N`, `id`) match too much to be evidence of anything.
MIN_SYMBOL = 3

KNOWN_GAPS_RE = re.compile(r"^\s*(?:#+\s*|\*\*\s*)?known gaps\b", re.I)
SECTION_END_RE = re.compile(r"^(?:#|---|\*\*[^*]+\*\*:?\s*$)")

_SYMBOL_CACHE: dict = {}

# ---------------------------------------------------------- line endings
# Generated and vendored trees keep whatever endings their tools wrote; the
# pristine pre-feature snapshot under .workflows/ is a diffing aid, not source.
ENDING_SKIP_PARTS = SOURCE_SKIP_PARTS | {".workflows"}
CR, LF = bytes([13]), bytes([10])
CRLF = CR + LF

# ------------------------------------------------------ graph-size claims
# "45 nodes, 39 edges" / "45 nodes / 45 edges" / "54 nodes and 51 edges" -- the
# three shapes the docs use. `and` was added for PROC-09: §11.19 wrote the claim
# that way and the pattern could not see it.
GRAPH_SIZE_RE = re.compile(r"(\d+)\s+nodes\s*(?:[,/]\s*|\s+and\s+)(\d+)\s+edges")
# ...but only where the subject is the one demo graph. `vision_pipeline_clean`
# is a different sample, and contracts/graph.sample.json a different graph
# again, so neither may be compared against these counts.
DEMO_SUBJECT_RE = re.compile(r"samples/vision_pipeline(?![\w])|\.mlview/graph\.json")
# A doc that records what a past release measured is not making a claim about
# today's graph, and rewriting it would erase the record. PROC-09: two such
# sentences were sitting in `docs/STATUS.md` and `docs/ROADMAP.md` quoting the
# 52 edges the sample had before REV-01 dropped the one backwards data edge. The
# marker is deliberately one fixed phrase and not a guess: a figure escapes the
# gate only when its own two-line window says, in words, that it is historical.
HISTORICAL_SIZE_RE = re.compile(r"\bat the time\b", re.I)

# --------------------------------------------------- roadmap landed notes
# PROC-01. `#### PERF-03 · Relevance prefilter`, `#### ANA-7 / ANA-8 / ANA-9 ·
# The three rule tiers`, `#### ★ DATAFLOW-IP · Interprocedural value summaries`.
ROADMAP = "docs/ROADMAP.md"
STATUS = "docs/STATUS.md"
ROADMAP_ITEM_RE = re.compile(r"^####\s+(?:★\s*)?(.+?)\s+·")
# A STATUS paragraph that opens by naming an item: `**FW-RECOG — four framework
# tables`, `**PERF-03, the relevance prefilter**`, `**NB, host half — ...`.
# Only tokens that are *also* roadmap heading ids are read as a claim, so
# `**The re-baseline.**` and a mention inside a sentence are both left alone.
STATUS_LEAD_RE = re.compile(r"^\*\*([A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*)\b")
LANDED_RE = re.compile(r"^\*\*Landed\b")
# `### NEXT`, `#### NB · ...`, `---`: where one item's section stops.
ROADMAP_BOUNDARY_RE = re.compile(r"^(?:#{2,4}\s|---\s*$)")


TESTFILE_RE = re.compile(r"[\w./-]*(?:test_[\w-]+\.py|[\w-]+\.test\.[cm]?js"
                         r"|tests?/[\w./-]+\.[cm]?js)")
FAILS_RE = re.compile(r"\b(fails?|failing|is red|breaks?)\b", re.I)

# --------------------------------------------------- build-state in a plan doc
# Only phrases that *report the state of the build*. "SVG is built with
# createElementNS" and "no element is built at all" describe a mechanism, not a
# milestone, and must stay legal in a design record.
BUILD_STATE_RE = re.compile(
    r"\b(?:is|are|was|were)\s+(?:now|already)\s+"
    r"(?:built|shipped|implemented|live|in the tree|in the build)\b"
    r"|\b(?:has|have)\s+been\s+(?:built|shipped|implemented|landed)\b"
    r"|\b(?:now|already)\s+(?:built|shipped|implemented|ships|lands)\b"
    r"|\bas\s+(?:built|shipped)\b"
    r"|\bship(?:s|ped)\s+(?:today|now)\b"
    r"|\bin the shipped build\b", re.I)


def _collect(root: Path, globs, already):
    found = []
    for pattern in globs:
        for path in sorted(root.glob(pattern)):
            rel = path.relative_to(root).as_posix()
            if rel in SKIP or path in already or path in found or not path.is_file():
                continue
            if "node_modules" in rel or rel.startswith("out/"):
                continue
            found.append(path)
    return found


def docs(root: Path):
    """(current-state docs, plan docs) -- the first set gets every check."""
    current = _collect(root, CURRENT_GLOBS, [])
    return current, _collect(root, PLAN_GLOBS, current)


def read(path: Path) -> list[str]:
    # newline='' stops CRLF becoming a phantom character; splitlines takes both.
    return io.open(path, encoding="utf-8", newline="").read().splitlines()


def is_path_claim(root: Path, token: str) -> bool:
    if token.startswith(IGNORED_PREFIXES) or any(s in token for s in IGNORED_SUBSTRINGS):
        return False
    if not token.endswith(EXTENSIONS):
        return False
    return token.split("/", 1)[0] in {p.name for p in root.iterdir()}


def resolves(root: Path, token: str) -> bool:
    target = token.split("#", 1)[0].rstrip("/")
    return not target or (root / target).exists()


def check_paths(root: Path, path: Path, lines, problems, backticks: bool = True) -> None:
    rel = path.relative_to(root).as_posix()
    for n, line in enumerate(lines, 1):
        if backticks:
            for token in PATH_RE.findall(line):
                if is_path_claim(root, token) and not resolves(root, token) \
                        and not (path.parent / token).exists():
                    problems.append("%s:%d: `%s` does not exist" % (rel, n, token))
        for token in LINK_RE.findall(line):
            if token.startswith(IGNORED_PREFIXES) or any(s in token for s in IGNORED_SUBSTRINGS):
                continue
            candidate = token.split("#", 1)[0]
            if not candidate or (path.parent / candidate).exists() or resolves(root, candidate):
                continue
            problems.append("%s:%d: link target %s does not exist" % (rel, n, token))


def bullets(lines):
    """Yield (line number, folded text) per Markdown bullet, so a claim spread
    over four indented lines is still matched as one string."""
    start, buf = 0, []
    for n, line in enumerate(lines, 1):
        if re.match(r"\s*[-*]\s+", line):
            if buf:
                yield start, " ".join(buf)
            start, buf = n, [line.strip().lstrip("-*").strip()]
        elif buf and line.strip() and line.startswith((" ", "\t")):
            buf.append(line.strip())
        elif buf:
            yield start, " ".join(buf)
            start, buf = 0, []
    if buf:
        yield start, " ".join(buf)


def check_failure_claims(root: Path, path: Path, lines, problems) -> None:
    rel = path.relative_to(root).as_posix()
    for n, text in bullets(lines):
        if not FAILS_RE.search(text):
            continue
        for named in TESTFILE_RE.findall(text):
            named = named.strip("`.,")
            if not is_path_claim(root, named) or not resolves(root, named):
                continue
            problems.append(
                "%s:%d: claims a test fails, but %s is in the tree and the suites "
                "are green -- delete or reword the claim (MLV-R1-006)" % (rel, n, named))


def check_build_state(root: Path, path: Path, lines, problems) -> None:
    """MLV-R1-H08: a plan doc may not report what the build currently does."""
    rel = path.relative_to(root).as_posix()
    for n, line in enumerate(lines, 1):
        found = BUILD_STATE_RE.search(line)
        if not found:
            continue
        problems.append(
            "%s:%d: plan doc reports build state (\"%s\") -- this file is a "
            "frozen design record and is link-checked only, so a current-state "
            "claim here erases the decision and nothing can catch it when it "
            "rots; put it in README.md or docs/STATUS.md instead (MLV-R1-H08)"
            % (rel, n, found.group(0)))


def source_symbols(root: Path) -> set:
    """Every identifier that occurs anywhere in the source tree, cached per root."""
    key = str(root)
    cached = _SYMBOL_CACHE.get(key)
    if cached is not None:
        return cached
    names: set = set()
    word = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
    for folder in SOURCE_DIRS:
        base = root / folder
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or not path.name.endswith(SOURCE_EXTENSIONS):
                continue
            if SOURCE_SKIP_PARTS.intersection(path.relative_to(root).parts):
                continue
            try:
                text = io.open(path, encoding="utf-8", errors="replace",
                               newline="").read()
            except OSError:  # pragma: no cover - unreadable file
                continue
            names.update(word.findall(text))
    _SYMBOL_CACHE[key] = names
    return names


def symbol_names(token: str):
    """The identifiers a backticked token asserts exist -- () if it asserts none.

    The last segment of a dotted chain is always checked (that is the member
    being named); earlier segments only when they are themselves code-shaped, so
    a throwaway receiver like `ctx` never has to be a real global.
    """
    token = token.strip()
    if not SYMBOL_TOKEN_RE.match(token):
        return ()
    head = token.split("(", 1)[0]
    if not CODE_SHAPE_RE.search(head):
        return ()
    parts = [part for part in head.split(".") if part]
    if not parts:
        return ()
    wanted = {parts[-1]}
    wanted.update(p for p in parts[:-1] if "_" in p or CAMEL_RE.search(p))
    return tuple(sorted(n for n in wanted if len(n) >= MIN_SYMBOL))


def known_gap_sections(lines):
    """Yield (offset, block) per "Known gaps" section.

    `offset` is the 0-based index of the heading, so block line k (1-based,
    as `bullets` numbers it) is file line offset + k + 1.
    """
    index = 0
    while index < len(lines):
        if KNOWN_GAPS_RE.match(lines[index]):
            end = index + 1
            while end < len(lines) and not SECTION_END_RE.match(lines[end].strip()):
                end += 1
            yield index, lines[index + 1:end]
            index = end
        else:
            index += 1


def check_gap_bullets(root: Path, path: Path, lines, problems) -> None:
    rel = path.relative_to(root).as_posix()
    symbols = None
    for offset, block in known_gap_sections(lines):
        for n, text in bullets(block):
            anchored = False
            for token in CODE_RE.findall(text):
                token = token.strip()
                if is_path_claim(root, token):
                    anchored = (anchored or resolves(root, token)
                                or (path.parent / token).exists())
                    continue
                names = symbol_names(token)
                if not names:
                    continue
                if symbols is None:
                    symbols = source_symbols(root)
                missing = [name for name in names if name not in symbols]
                if missing:
                    problems.append(
                        "%s:%d: known gap cites `%s`, but %s is nowhere in the "
                        "source -- the code moved and the bullet did not "
                        "(MLV-R2-109)" % (rel, offset + n + 1, token,
                                          ", ".join("`%s`" % m for m in missing)))
                else:
                    anchored = True
            if not anchored:
                problems.append(
                    "%s:%d: known gap cites nothing checkable -- name the file or "
                    "the code symbol it is about, in backticks, so the gate can "
                    "retire the bullet when the code moves (MLV-R2-109)"
                    % (rel, offset + n + 1))


# ------------------------------------------------- check 21: landed gaps
# A clause that names its own retirement condition: "... groups only once the
# matching `--group-by` flag lands on `analyzer/src/mlview/cli.py`". The window
# may not cross a sentence end, so the name and the path have to be in one
# breath -- but `.py` and `.md` are dots inside a sentence, not the end of one,
# which is why the boundary is "a dot followed by whitespace" and not "a dot".
_IN_SENTENCE = r"(?:(?!\.[\s)]|\.$)[^\n])"
LANDING_RE = re.compile(r"\b(?:once|until|when|after)\b" + _IN_SENTENCE +
                        r"{0,200}?\bland(?:s|ed|ing)?\b" + _IN_SENTENCE + r"{0,160}",
                        re.I)
# The thing being waited for: a command-line flag, or a code symbol check 5
# would already recognise. Prose in backticks is not a landing condition.
FLAG_TOKEN_RE = re.compile(r"^--[a-z][a-z0-9-]+$")


def _landing_spellings(token: str) -> set:
    """Every way the named thing could be written in the file that would host it.

    `--group-by` is `group_by` in an argparse `dest` and `"--group-by"` in the
    `add_argument` call, and a bullet that waits for it is stale either way.
    """
    bare = token.lstrip("-")
    return {token, bare, bare.replace("-", "_")}


def check_landed_gaps(root: Path, path: Path, lines, problems) -> None:
    """HOSTS-UX-R2-07: a gap that waits for something already in the named file."""
    rel = path.relative_to(root).as_posix()
    for offset, block in known_gap_sections(lines):
        for n, text in bullets(block):
            for clause in LANDING_RE.findall(text):
                tokens = [t.strip() for t in CODE_RE.findall(clause)]
                targets = [t for t in tokens
                           if is_path_claim(root, t) and (root / t).is_file()]
                names = [t for t in tokens
                         if FLAG_TOKEN_RE.match(t)
                         or (SYMBOL_TOKEN_RE.match(t) and CODE_SHAPE_RE.search(t)
                             and len(t) >= MIN_SYMBOL)]
                for target in targets:
                    body = io.open(root / target, encoding="utf-8",
                                   errors="replace").read()
                    for name in names:
                        if name == target or not any(
                                spelling in body
                                for spelling in _landing_spellings(name)):
                            continue
                        problems.append(
                            "%s:%d: known gap waits for `%s` to land on `%s`, "
                            "and it is already there -- say what the build does "
                            "instead of what it is waiting for (HOSTS-UX-R2-07)"
                            % (rel, offset + n + 1, name, target))


def downloaded_parts(root: Path) -> set:
    """`ENDING_SKIP_PARTS` plus every directory a tool *downloads* into the tree.

    PUB-01 put a pinned set of third-party repositories under `.public-corpus/`
    (the name is read from `tools/public_corpus.py`, never spelled here), and
    they carry shell scripts of their own -- 24 repositories and 26 scripts when
    that incident was written, 37 and 169 two waves later, which is exactly why
    no count belongs in this docstring. Holding somebody else's `get_coco.sh` to this
    repo's line-ending convention would fail the doc gate on a machine that had
    run `python tools/public_corpus.py fetch` and pass on one that had not --
    a gate whose verdict depends on what is cached is not a gate.
    """
    parts = set(ENDING_SKIP_PARTS)
    for rel, const in doc_surfaces.GENERATED_DIRS:
        name, _ = doc_surfaces.generated_dir(root, rel, const)
        if name:
            parts.add(name.strip("/"))
    return parts


def shell_scripts(root: Path):
    """Every POSIX shell script that is *source* in this tree."""
    skip = downloaded_parts(root)
    for path in sorted(root.rglob("*.sh")):
        rel = path.relative_to(root)
        if skip.intersection(rel.parts) or not path.is_file():
            continue
        yield path


def check_line_endings(root: Path, paths, problems) -> None:
    """MLV-R2-H02: LF in the shell scripts, one convention per checked file."""
    for path in paths:
        rel = path.relative_to(root).as_posix()
        try:
            data = path.read_bytes()
        except OSError:  # pragma: no cover - unreadable file
            continue
        crlf = data.count(CRLF)
        stray = data.count(CR) - crlf
        bare = data.count(LF) - crlf
        if rel.endswith(".sh"):
            if crlf or stray:
                problems.append(
                    "%s: POSIX shell script carries %d carriage return(s) -- "
                    "`#!/usr/bin/env sh` then names a program \"sh<CR>\", and a "
                    "stray CR rides on every value it assigns; Git Bash's igncr "
                    "hides this on Windows and nothing else does. Rewrite with "
                    "LF (MLV-R2-H02)" % (rel, crlf + stray))
            continue
        if crlf and bare:
            problems.append(
                "%s: mixes %d CRLF and %d LF line ending(s) -- pick one, so the "
                "next edit reads as an edit and not as a whole-file rewrite "
                "(MLV-R2-H02)" % (rel, crlf, bare))


def collect_graph_sizes(root: Path, path: Path, lines, sizes) -> None:
    """Gather every `N nodes / M edges` claim made about the demo graph.

    The window is two lines wide, because prose wraps: `docs/STATUS.md` carried
    `54 nodes / 52\\nedges` for a whole sprint and a one-line scan could not see
    it (PROC-09). A match is attributed to the line it *starts* on, so a claim
    inside one line is counted once and never again by the previous window.
    """
    rel = path.relative_to(root).as_posix()
    for n, line in enumerate(lines, 1):
        nxt = lines[n] if n < len(lines) else ""
        window = line + " " + nxt
        if not DEMO_SUBJECT_RE.search(window) or HISTORICAL_SIZE_RE.search(window):
            continue
        for match in GRAPH_SIZE_RE.finditer(window):
            if match.start() >= len(line):
                continue  # it belongs to the next line's window, not this one
            nodes, edges = match.groups()
            sizes.append((int(nodes), int(edges), "%s:%d" % (rel, n)))


def check_graph_sizes(sizes, problems) -> None:
    """MLV-R2-H05: one run produces one graph, so the docs must agree on it."""
    if len({(nodes, edges) for nodes, edges, _ in sizes}) < 2:
        return
    problems.append(
        "the docs disagree about the size of the demo graph -- %s. One run "
        "produces one graph; `python -m mlview analyze samples/vision_pipeline "
        "--format summary` prints the true counts (MLV-R2-H05)"
        % "; ".join("%s says %d nodes / %d edges" % (where, nodes, edges)
                    for nodes, edges, where in sizes))


def roadmap_sections(lines):
    """[(item ids, heading line no, section line range)] for every `####` item."""
    sections = []
    for start, line in enumerate(lines):
        match = ROADMAP_ITEM_RE.match(line)
        if not match:
            continue
        end = start + 1
        while end < len(lines) and not ROADMAP_BOUNDARY_RE.match(lines[end]):
            end += 1
        # `PERF-01 + PERF-02` and `ANA-7 / ANA-8 / ANA-9` are one section that
        # discharges several ids.
        ids = [part.strip() for part in re.split(r"[/+]", match.group(1))]
        sections.append(([i for i in ids if i], start + 1, range(start, end)))
    return sections


def check_roadmap_landed(root: Path, problems) -> None:
    """PROC-01: an item STATUS.md says shipped must say so in the roadmap too."""
    roadmap, status = root / ROADMAP, root / STATUS
    if not roadmap.is_file() or not status.is_file():
        return
    lines = read(roadmap)
    sections = roadmap_sections(lines)
    landed_at = {n for n, line in enumerate(lines) if LANDED_RE.match(line)}
    covered = {n for _, _, span in sections for n in span}

    for n in sorted(landed_at - covered):
        problems.append(
            "%s:%d: a `**Landed` measurement note that is not inside any item's "
            "section -- it reads as an item of its own and no reader will find "
            "it under the acceptance clause it reconciles (PROC-01)"
            % (ROADMAP, n + 1))

    shipped = {}
    for n, line in enumerate(read(status), 1):
        match = STATUS_LEAD_RE.match(line)
        if match:
            shipped.setdefault(match.group(1), n)

    for ids, heading, span in sections:
        claimed = [i for i in ids if i in shipped]
        if not claimed or any(LANDED_RE.match(lines[n]) for n in span):
            continue
        problems.append(
            "%s:%d: `%s` has shipped -- %s:%d reports it -- but its roadmap "
            "section carries no `**Landed ... measurement note.**`, so the "
            "acceptance clause it was measured against, and the statement of "
            "what it could not analyze, are written nowhere the roadmap's "
            "reader will look (PROC-01)"
            % (ROADMAP, heading, " / ".join(claimed), STATUS,
               shipped[claimed[0]]))


def run(root: Path):
    """Return (problems, files checked). Importable, so the gate has its own test."""
    problems: list[str] = []
    sizes: list = []
    current, plan = docs(root)
    for path in current:
        lines = read(path)
        check_paths(root, path, lines, problems)
        check_failure_claims(root, path, lines, problems)
        check_gap_bullets(root, path, lines, problems)
        check_landed_gaps(root, path, lines, problems)
        collect_graph_sizes(root, path, lines, sizes)
    for path in plan:
        lines = read(path)
        check_paths(root, path, lines, problems, backticks=False)
        check_build_state(root, path, lines, problems)
    check_graph_sizes(sizes, problems)
    check_roadmap_landed(root, problems)
    scripts = list(shell_scripts(root))
    check_line_endings(root, scripts + current + plan, problems)
    # Checks 9-11 and 13-15: numbers the prose shares with a file in the tree.
    doc_numbers.run(root, current, problems)
    doc_figures.run(root, current, problems)
    # Checks 16-18: lists the prose shares with a file in the tree.
    doc_surfaces.run(root, current, problems)
    # Check 22: a claim the tree holds no copy of at all.
    doc_claims.run(root, current, problems)
    return problems, current + plan + scripts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="check the docs against the tree")
    ap.add_argument("--root", default=str(DEFAULT_ROOT), help="repo root to check")
    ap.add_argument("--quiet", action="store_true", help="only print problems")
    args = ap.parse_args(argv)

    problems, files = run(Path(args.root).resolve())
    if problems:
        print("DOC CHECK FAILED (%d problem(s) in %d file(s))" % (len(problems), len(files)))
        for problem in problems:
            print("  " + problem)
        return 1
    if not args.quiet:
        print("DOC CHECK OK (%d files, no dead paths, no stale claims, "
              "every known gap anchored, no build state in a plan doc, "
              "LF in every shell script, one graph size, the accuracy headline "
              "matches the baseline, no silent artifact upload, one e2e step "
              "count, every shipped roadmap item recorded as landed, the "
              "components table agreeing with its own gate paragraph, the scope "
              "battery quoted at its real size, one last-green-push run id, "
              "every selector the parser accepts advertised on every list a "
              "reader sees, every generated directory git-ignored, every test "
              "file its package's `test` script runs, every CI command line one "
              "its own tool accepts, no closed list of rules the code does not "
              "hold, no known gap waiting for something that has landed, no "
              "gate claimed green on a CI matrix without naming the run or "
              "saying whether the matrix ran and none denying a run another "
              "document names, the contract's diff figures equal the test that "
              "pins them, the public corpus's false-positive count equal to its "
              "adjudication file, and the third-party notice naming the versions "
              "that are installed)"
              % len(files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
