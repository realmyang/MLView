#!/usr/bin/env python
"""Documentation gate: keep the prose honest about the tree it describes.

Eight checks, all offline and stdlib-only:

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

Usage:  python scripts/check_docs.py [--root DIR] [--quiet]
Exit 0 when clean, 1 when a problem is found. The report goes to stdout.
"""
from __future__ import annotations

import argparse
import io
import re
import sys
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parent.parent

# Docs that describe the tree as it *is*: every path they name must exist, and
# they may not claim a green test fails.
CURRENT_GLOBS = ("README.md", "docs/STATUS.md", "scripts/README.md",
                 "*/README.md", "docs/rules/README.md")
# Docs that describe the tree as it was *planned*: frozen design records, checked
# for dead Markdown links only. Rewriting them to match the build would erase the
# record of what was decided. docs/CONTRACTS.md is normative and frozen, and is
# never held to this gate at all.
PLAN_GLOBS = ("docs/ARCHITECTURE.md", "docs/REQUIREMENTS.md",
              "docs/ISSUE_RULES.md", "docs/UX_DESIGN.md")
SKIP = {"docs/CONTRACTS.md"}

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
# "45 nodes, 39 edges" / "45 nodes / 45 edges" -- the two shapes the docs use.
GRAPH_SIZE_RE = re.compile(r"(\d+)\s+nodes\s*[,/]\s*(\d+)\s+edges")
# ...but only where the subject is the one demo graph. `vision_pipeline_clean`
# is a different sample, and contracts/graph.sample.json a different graph
# again, so neither may be compared against these counts.
DEMO_SUBJECT_RE = re.compile(r"samples/vision_pipeline(?![\w])|\.mlview/graph\.json")


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


def shell_scripts(root: Path):
    """Every POSIX shell script that is *source* in this tree."""
    for path in sorted(root.rglob("*.sh")):
        rel = path.relative_to(root)
        if ENDING_SKIP_PARTS.intersection(rel.parts) or not path.is_file():
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
    """Gather every `N nodes / M edges` claim made about the demo graph."""
    rel = path.relative_to(root).as_posix()
    for n, line in enumerate(lines, 1):
        if not DEMO_SUBJECT_RE.search(line):
            continue
        for nodes, edges in GRAPH_SIZE_RE.findall(line):
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
        collect_graph_sizes(root, path, lines, sizes)
    for path in plan:
        lines = read(path)
        check_paths(root, path, lines, problems, backticks=False)
        check_build_state(root, path, lines, problems)
    check_graph_sizes(sizes, problems)
    scripts = list(shell_scripts(root))
    check_line_endings(root, scripts + current + plan, problems)
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
              "LF in every shell script, one graph size)"
              % len(files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
