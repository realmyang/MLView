#!/usr/bin/env python
"""Tests for scripts/check_docs.py: MLV-R1-006, MLV-R2-109, MLV-R1-H08,
MLV-R2-H02 (line endings) and MLV-R2-H05 (graph sizes).

Each case builds a throwaway tree in a temp directory and runs the checker
against it with --root, so nothing here depends on the state of the real repo.
The last test *does* run against the real repo and requires it to be clean.

Run:  python scripts/test_check_docs.py      (or: pytest scripts/test_check_docs.py)
"""
from __future__ import annotations

import io
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_docs  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def _tree(files: dict) -> Path:
    root = Path(tempfile.mkdtemp(prefix="mlview-doccheck-"))
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        io.open(target, "w", encoding="utf-8", newline="\n").write(text)
    return root


STALE_README = """# Demo

**Known gaps:**

- `vscode-extension/test/manifest.test.js` asserts that `media/` contains only
  its placeholder README, which is true before the sync runs and false after --
  so that one test fails inside `scripts/e2e` immediately after a build.
"""


def test_stale_failure_claim_is_caught():
    """MLV-R1-006: a README that says a green, present test fails must fail."""
    root = _tree({"README.md": STALE_README,
                  "vscode-extension/test/manifest.test.js": "// green\n",
                  "vscode-extension/README.md": "# ext\n"})
    try:
        problems, _ = check_docs.run(root)
        assert len(problems) == 1, problems
        assert "MLV-R1-006" in problems[0]
        assert "manifest.test.js" in problems[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_failure_claim_about_an_absent_test_is_not_a_stale_claim():
    """A claim about a test that is genuinely not in the tree is not stale: the
    complaints are the dead path and the citation it fails to be, never the
    MLV-R1-006 message."""
    root = _tree({"README.md": STALE_README, "vscode-extension/README.md": "# ext\n"})
    try:
        problems, _ = check_docs.run(root)
        assert len(problems) == 2, problems
        assert any("does not exist" in p for p in problems), problems
        assert any("nothing checkable" in p for p in problems), problems
        assert not any("MLV-R1-006" in p for p in problems), problems
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_dead_path_is_caught():
    root = _tree({"README.md": "See `analyzer/src/mlview/gone.py` for details.\n",
                  "analyzer/README.md": "# analyzer\n"})
    try:
        problems, _ = check_docs.run(root)
        assert len(problems) == 1, problems
        assert "gone.py" in problems[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_live_path_and_rpc_method_names_are_clean():
    """`tools/call` is a JSON-RPC method, `scripts/e2e` a two-file shorthand:
    neither is a path claim, while a real file reference still resolves."""
    root = _tree({"README.md": "`tools/call`, `scripts/e2e`, `scripts/build.ps1`\n",
                  "scripts/build.ps1": "# build\n"})
    try:
        problems, _ = check_docs.run(root)
        assert problems == [], problems
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_dead_relative_link_is_caught():
    root = _tree({"README.md": "[gaps](docs/NOPE.md)\n", "docs/STATUS.md": "# status\n"})
    try:
        problems, _ = check_docs.run(root)
        assert len(problems) == 1 and "NOPE.md" in problems[0], problems
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_plan_docs_keep_their_planned_paths():
    """A frozen design doc may name a file that was never built; only its links
    are checked, so the record of what was decided survives."""
    root = _tree({"README.md": "# mlview\n",
                  "docs/ARCHITECTURE.md": "`tools/bench.py` was planned.\n",
                  "tools/sync-core.py": "# core\n"})
    try:
        problems, _ = check_docs.run(root)
        assert problems == [], problems
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- MLV-R2-109
# The round-1 gate only understood "test X fails". A behavioural claim -- "the
# framework gate is workspace-wide" -- outlived the code it described by a whole
# round. These cases pin the two checks that close that hole.

GATE_SOURCE = ('''
class Ctx:
    def wrappers_for(self, file):
        """The frameworks that own the training loop of one module."""
        return ()
''')

STALE_SYMBOL_README = """# Demo

**Known gaps:**

- The absence rules are gated workspace-wide: `ctx.wrappers` is read once for the
  whole run, so one wrapper anywhere de-rates every finding.
"""

LIVE_SYMBOL_README = """# Demo

**Known gaps:**

- The framework gate reaches one import hop: `ctx.wrappers_for()` reads the
  finding's own module and the workspace modules it imports, no further.
"""

UNANCHORED_README = """# Demo

**Known gaps:**

- Loop nesting is flattened one level, so an inner batch loop is a sibling of its
  epoch loop rather than a child.
"""

PROSE_README = """# Demo

## How it works

The gate is implemented by `ctx.wrappers` and friends.
"""


def test_a_gap_bullet_that_cites_a_renamed_symbol_fails():
    """MLV-R2-109: `wrappers` became `wrappers_for` and the bullet did not."""
    root = _tree({"README.md": STALE_SYMBOL_README,
                  "analyzer/src/mlview/rules/context.py": GATE_SOURCE})
    try:
        problems, _ = check_docs.run(root)
        assert len(problems) == 2, problems
        dead = [p for p in problems if "nowhere in the source" in p]
        assert len(dead) == 1, problems
        assert "`ctx.wrappers`" in dead[0] and "MLV-R2-109" in dead[0]
        # ... and losing its only citation leaves the bullet unanchored too.
        assert any("nothing checkable" in p for p in problems), problems
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_gap_bullet_that_cites_a_live_symbol_is_clean():
    root = _tree({"README.md": LIVE_SYMBOL_README,
                  "analyzer/src/mlview/rules/context.py": GATE_SOURCE})
    try:
        assert check_docs.run(root)[0] == [], check_docs.run(root)[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_gap_bullet_that_cites_nothing_fails():
    """A claim with no path, no symbol and no test id can never be retired."""
    root = _tree({"README.md": UNANCHORED_README,
                  "analyzer/src/mlview/rules/context.py": GATE_SOURCE})
    try:
        problems, _ = check_docs.run(root)
        assert len(problems) == 1, problems
        assert "nothing checkable" in problems[0], problems
        assert "README.md:5" in problems[0], problems
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_symbols_outside_a_known_gaps_section_are_not_checked():
    """The symbol gate is aimed at the honesty section, not at every sentence."""
    root = _tree({"README.md": PROSE_README,
                  "analyzer/src/mlview/rules/context.py": GATE_SOURCE})
    try:
        assert check_docs.run(root)[0] == [], check_docs.run(root)[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_symbol_names_reads_only_what_a_token_actually_asserts():
    assert check_docs.symbol_names("ctx.wrappers_for(loc.file)") == ("wrappers_for",)
    assert check_docs.symbol_names("mlview.showSpeculative") == ("showSpeculative",)
    assert check_docs.symbol_names("medium") == ()          # plain English
    assert check_docs.symbol_names("scripts/e2e") == ()     # a path, not a symbol
    assert check_docs.symbol_names("config.N") == ()        # too short to mean anything
    assert check_docs.symbol_names("from config import N") == ()


GATE_LIES = ("gated workspace-wide", "gate is workspace-wide", "workspace-wide gate",
             "anywhere in the workspace", "wrapper *anywhere*", "*anywhere* caps")


def test_the_framework_gate_is_not_described_as_workspace_wide():
    """MLV-R2-109, on the real docs: the gate ships per-module, so no
    current-state doc may call it workspace-wide in its honesty section, and the
    bullet that describes it must cite the function that implements it."""
    for rel in ("README.md", "docs/STATUS.md"):
        text = io.open(REPO / rel, encoding="utf-8", newline="").read()
        gaps = [b for _o, block in check_docs.known_gap_sections(text.splitlines())
                for _n, b in check_docs.bullets(block)]
        assert gaps, "%s has no Known gaps section any more" % rel
        joined = " ".join(gaps).lower()
        for lie in GATE_LIES:
            assert lie not in joined, "%s still says %r" % (rel, lie)
        assert any("wrappers_for" in b for b in gaps), (
            "%s: the gate bullet must cite ctx.wrappers_for()" % rel)


# ---------------------------------------------------------------- MLV-R1-H08
# The plan docs are link-checked only, so a current-state claim inside one is
# invisible to every other check in this file. Round 1 found `docs/UX_DESIGN.md`
# saying the breadcrumb "is now built": a build report inside the decision
# record, exempt from the gate by construction. These cases pin check 6.

BUILT_PLAN_DOC = """# UX

- **Breadcrumb** (`ui/breadcrumb.ts`) is the scope's home and is now built. It
  states what is scoped, then the depth.
"""

MECHANISM_PLAN_DOC = """# UX

- The webview never uses `innerHTML`; SVG and node DOM are built with
  `createElementNS`. Under reduced motion no flow element is built at all.
"""


def test_a_plan_doc_may_not_report_build_state():
    """MLV-R1-H08: "is now built" in a frozen design record fails the run."""
    root = _tree({"README.md": "# mlview\n",
                  "docs/UX_DESIGN.md": BUILT_PLAN_DOC})
    try:
        problems, _ = check_docs.run(root)
        assert len(problems) == 1, problems
        assert "MLV-R1-H08" in problems[0], problems
        assert "docs/UX_DESIGN.md:3" in problems[0], problems
        assert "is now built" in problems[0], problems
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_plan_doc_may_still_describe_a_mechanism():
    """"DOM is built with createElementNS" is how something works, not a
    milestone: the check must not touch design prose."""
    root = _tree({"README.md": "# mlview\n",
                  "docs/UX_DESIGN.md": MECHANISM_PLAN_DOC})
    try:
        assert check_docs.run(root)[0] == [], check_docs.run(root)[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_build_state_is_checked_in_plan_docs_only():
    """A current-state doc is *supposed* to report the state of the build; the
    other five checks are what keep it honest."""
    root = _tree({"README.md": "The scope picker is now built and shipped.\n"})
    try:
        assert check_docs.run(root)[0] == [], check_docs.run(root)[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_real_plan_docs_report_no_build_state():
    """The repo's own four design records, on disk, right now."""
    _current, plan = check_docs.docs(REPO)
    assert len(plan) == 4, [p.name for p in plan]
    problems = []
    for path in plan:
        check_docs.check_build_state(REPO, path, check_docs.read(path), problems)
    assert problems == [], "\n".join(problems)


def test_the_real_repo_is_clean():
    problems, files = check_docs.run(REPO)
    assert problems == [], "\n".join(problems)
    assert len(files) >= 8, "the gate should be looking at the whole doc set"


# ------------------------------------------------------------ line endings
# MLV-R2-H02 / R2-REG-01: scripts/e2e.sh, the documented POSIX twin of
# scripts/e2e.ps1, was rewritten LF->CRLF. Git Bash's igncr hid it here; under
# dash the shebang names a program "sh<CR>", `SKIP_BUILD=0<CR>` fails `-eq`, and
# every artifact lands in a directory called ".mlview<CR>".


def _write_bytes(root: Path, rel: str, data: bytes) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


CRLF_SCRIPT = (b'#!/usr/bin/env sh\r\nset -e\r\nSKIP_BUILD=0\r\n'
               b'OUT="$REPO_ROOT/.mlview"\r\n')
LF_SCRIPT = CRLF_SCRIPT.replace(b'\r\n', b'\n')


def test_crlf_in_a_shell_script_is_caught():
    """MLV-R2-H02: the only non-Windows entry point may not carry CRLF."""
    root = _tree({"README.md": "# mlview\n"})
    try:
        _write_bytes(root, "scripts/e2e.sh", CRLF_SCRIPT)
        problems, files = check_docs.run(root)
        assert len(problems) == 1, problems
        assert "MLV-R2-H02" in problems[0]
        assert "scripts/e2e.sh" in problems[0]
        assert any(p.name == "e2e.sh" for p in files), files
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_an_lf_shell_script_is_clean():
    root = _tree({"README.md": "# mlview\n"})
    try:
        _write_bytes(root, "scripts/e2e.sh", LF_SCRIPT)
        assert check_docs.run(root)[0] == [], check_docs.run(root)[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_vendored_shell_script_is_left_alone():
    """The pre-feature snapshot and node_modules are not this tree's source."""
    root = _tree({"README.md": "# mlview\n"})
    try:
        _write_bytes(root, ".workflows/backup/pre-features/scripts/e2e.sh", CRLF_SCRIPT)
        _write_bytes(root, "webview/node_modules/pkg/install.sh", CRLF_SCRIPT)
        assert check_docs.run(root)[0] == [], check_docs.run(root)[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_real_shell_scripts_are_lf():
    """The regression assertion for R2-REG-01, against the tree as it ships."""
    scripts = list(check_docs.shell_scripts(REPO))
    # pythonpick.sh joined the two drivers when CI-01 taught them to find an
    # interpreter on Linux and macOS. The list is spelled out rather than counted
    # so a new shell file cannot slip in without someone confirming it is LF.
    assert [p.name for p in scripts] == ["build.sh", "e2e.sh", "pythonpick.sh"], scripts
    for path in scripts:
        assert b"\r" not in path.read_bytes(), path


def test_a_doc_may_not_mix_line_endings():
    """A half-converted file turns the next small edit into a whole-file
    rewrite, which is how the stale "39 edges" row rode through review."""
    root = _tree({"README.md": "# mlview\n"})
    try:
        _write_bytes(root, "docs/STATUS.md", b"# status\r\n\r\nhalf\nand half\r\n")
        problems = check_docs.run(root)[0]
        assert len(problems) == 1, problems
        assert "mixes" in problems[0] and "docs/STATUS.md" in problems[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_wholly_crlf_doc_is_left_alone():
    """docs/ARCHITECTURE.md has been CRLF since it was written; one convention
    per file is the rule, not one convention per repo."""
    root = _tree({"README.md": "# mlview\n"})
    try:
        _write_bytes(root, "docs/ARCHITECTURE.md", b"# arch\r\n\r\nall CRLF\r\n")
        assert check_docs.run(root)[0] == [], check_docs.run(root)[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------- graph-size claims
# MLV-R2-H05: docs/STATUS.md said the demo graph had 39 edges long after it had
# 45, and scripts/README.md said 45 on the same day.

DISAGREEING_STATUS = """# Status

| Samples | `samples/vision_pipeline` (45 nodes, 39 edges, 15 issues) |
"""
DISAGREEING_SCRIPTS = """# scripts

Step 17 validates `.mlview/graph.json`: 45 nodes / 45 edges / 15 issues.
"""


def test_disagreeing_graph_sizes_are_caught():
    root = _tree({"README.md": "# mlview\n",
                  "docs/STATUS.md": DISAGREEING_STATUS,
                  "scripts/README.md": DISAGREEING_SCRIPTS})
    try:
        problems = check_docs.run(root)[0]
        assert len(problems) == 1, problems
        assert "MLV-R2-H05" in problems[0]
        assert "docs/STATUS.md:3 says 45 nodes / 39 edges" in problems[0]
        assert "scripts/README.md:3 says 45 nodes / 45 edges" in problems[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_agreeing_graph_sizes_are_clean():
    root = _tree({"README.md": "# mlview\n",
                  "docs/STATUS.md": DISAGREEING_STATUS.replace("39 edges", "45 edges"),
                  "scripts/README.md": DISAGREEING_SCRIPTS})
    try:
        assert check_docs.run(root)[0] == [], check_docs.run(root)[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_another_graph_is_not_compared_against_the_demo():
    """`contracts/graph.sample.json` is a different, smaller graph, and
    `vision_pipeline_clean` a different sample: neither is the demo."""
    root = _tree({"README.md": "# mlview\n",
                  "docs/STATUS.md": DISAGREEING_STATUS.replace("39 edges", "45 edges"),
                  "scripts/README.md": (
                      "# scripts\n\nThe golden `contracts/graph.sample.json` is "
                      "12 nodes / 14 edges, and `samples/vision_pipeline_clean` "
                      "is 55 nodes / 60 edges.\n"),
                  "contracts/graph.sample.json": "{}\n"})
    try:
        assert check_docs.run(root)[0] == [], check_docs.run(root)[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)

# ------------------------------------------------- wrapped and `and` sizes
# PROC-09: `docs/STATUS.md` carried `to **54 nodes / 52\nedges**` for a whole
# sprint and `docs/CONTRACTS.md` §11.19 wrote `54 nodes and 52 edges`. The
# one-line scan and the `[,/]`-only separator meant the gate that exists to stop
# exactly this reported "one graph size" while three docs held the old one.

WRAPPED_STATUS = """# status

`samples/vision_pipeline` is now 54 nodes / 52
edges after the re-baseline.
"""

AND_SCRIPTS = """# scripts

Step 17 validates `samples/vision_pipeline`: 54 nodes and 51 edges.
"""


def test_a_graph_size_that_wraps_across_a_line_break_is_seen():
    """PROC-09: the claim is `54 nodes / 52` on one line and `edges` on the next."""
    root = _tree({"README.md": "# mlview\n",
                  "docs/STATUS.md": WRAPPED_STATUS,
                  "scripts/README.md": AND_SCRIPTS})
    try:
        problems = check_docs.run(root)[0]
        assert len(problems) == 1, problems
        assert "MLV-R2-H05" in problems[0]
        assert "docs/STATUS.md:3 says 54 nodes / 52 edges" in problems[0]
        assert "scripts/README.md:3 says 54 nodes and 51 edges" not in problems[0]
        assert "scripts/README.md:3 says 54 nodes / 51 edges" in problems[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_size_written_with_and_is_seen():
    """`N nodes and M edges` is the shape §11.19 used, and it escaped entirely."""
    root = _tree({"README.md": "# mlview\n",
                  "docs/STATUS.md": WRAPPED_STATUS.replace("52\nedges", "51\nedges"),
                  "scripts/README.md": AND_SCRIPTS.replace("51 edges", "52 edges")})
    try:
        problems = check_docs.run(root)[0]
        assert len(problems) == 1, problems
        assert "scripts/README.md:3 says 54 nodes / 52 edges" in problems[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_figure_marked_as_historical_is_not_a_claim_about_today():
    """A release record may quote what it measured, if it says so in words."""
    root = _tree({"README.md": "# mlview\n",
                  "docs/STATUS.md": WRAPPED_STATUS.replace(
                      "after the re-baseline.",
                      "-- the count at the time; REV-01 later dropped one edge."),
                  "scripts/README.md": AND_SCRIPTS})
    try:
        assert check_docs.run(root)[0] == [], check_docs.run(root)[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_one_line_sizes_are_still_counted_exactly_once():
    """The two-line window may not turn one claim into two."""
    root = _tree({"README.md": "# mlview\n",
                  "scripts/README.md": AND_SCRIPTS})
    try:
        sizes: list = []
        check_docs.collect_graph_sizes(
            root, root / "scripts/README.md",
            check_docs.read(root / "scripts/README.md"), sizes)
        assert sizes == [(54, 51, "scripts/README.md:3")], sizes
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------- roadmap landed notes (PROC-01)
# Seven Sprint 4 NEXT items shipped -- each with its own docs/STATUS.md section
# -- and docs/ROADMAP.md carried a `**Landed ...**` note for wave 1 only. The
# roadmap is where the acceptance clause is written and where the framing "every
# analyzer change must state what it could not analyze" is discharged, so an
# unrecorded item hides both. H3's note made the other half of the same failure:
# it was written below `### LATER`, outside any item's section.

SHIPPED_ROADMAP = """# roadmap

### NEXT

#### PERF-03 · Relevance prefilter

*optimization*

**Acceptance.** The mixed repo drops under 1.5 s.

#### VIEW-99 · Something not built yet

*new-feature*

**Acceptance.** Nothing has happened.
"""

SHIPPED_STATUS = """# status

## Sprint 4 — analyzer, wave 3

**PERF-03, the relevance prefilter.** It shipped and here is the number.
"""


def test_a_shipped_roadmap_item_with_no_landed_note_is_caught():
    """PROC-01: STATUS reports it; the roadmap does not say it shipped."""
    root = _tree({"README.md": "# mlview\n",
                  "docs/ROADMAP.md": SHIPPED_ROADMAP,
                  "docs/STATUS.md": SHIPPED_STATUS})
    try:
        problems = check_docs.run(root)[0]
        assert len(problems) == 1, problems
        assert "PROC-01" in problems[0]
        assert "`PERF-03` has shipped" in problems[0]
        assert "VIEW-99" not in problems[0], "an unshipped item is not overdue"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_shipped_roadmap_item_with_its_landed_note_is_clean():
    root = _tree({"README.md": "# mlview\n",
                  "docs/ROADMAP.md": SHIPPED_ROADMAP.replace(
                      "**Acceptance.** The mixed repo drops under 1.5 s.",
                      "**Acceptance.** The mixed repo drops under 1.5 s.\n\n"
                      "**Landed 2026-09-09 (Sprint 4 wave 3) — measurement "
                      "note.** 2228 ms to 693 ms. **What it could not "
                      "analyze:** a module reached only through `importlib`."),
                  "docs/STATUS.md": SHIPPED_STATUS})
    try:
        assert check_docs.run(root)[0] == [], check_docs.run(root)[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_landed_note_outside_any_item_section_is_caught():
    """H3's note sat below the `### LATER` divider, where it read as an item."""
    root = _tree({"README.md": "# mlview\n",
                  "docs/ROADMAP.md": SHIPPED_ROADMAP + (
                      "\n---\n\n### LATER\n\n"
                      "**Landed 2026-09-09 (Sprint 4 wave 1) — measurement "
                      "note.** Both halves shipped.\n"),
                  "docs/STATUS.md": "# status\n\nNothing shipped.\n"})
    try:
        problems = check_docs.run(root)[0]
        assert len(problems) == 1, problems
        assert "PROC-01" in problems[0]
        assert "not inside any item's section" in problems[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_status_mention_that_is_not_a_lead_in_is_not_a_shipping_claim():
    """`... which is DATAFLOW-IP's problem` names an item without shipping it."""
    root = _tree({"README.md": "# mlview\n",
                  "docs/ROADMAP.md": SHIPPED_ROADMAP,
                  "docs/STATUS.md": "# status\n\n**The wave.** Seven of the "
                                    "labelled ops are PERF-03's problem, and "
                                    "VIEW-99 is gated on ANA-12.\n"})
    try:
        assert check_docs.run(root)[0] == [], check_docs.run(root)[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_real_roadmap_records_every_shipped_sprint_4_item():
    """The tree's own bookkeeping, not a fixture's: PROC-01's actual repro."""
    problems: list = []
    check_docs.check_roadmap_landed(REPO, problems)
    assert problems == [], "\n".join(problems)
    lines = check_docs.read(REPO / "docs/ROADMAP.md")
    landed = [n for n, line in enumerate(lines, 1)
              if check_docs.LANDED_RE.match(line)]
    assert len(landed) >= 20, "wave 2, 3 and 4 each owe a measurement note"


def run_module(module, failed: int = 0) -> int:
    """Run every `test_*` in one module, printing a line each. Shared with
    `scripts/test_doc_numbers.py` (checks 9-11), `scripts/test_doc_figures.py`
    (13-15) and `scripts/test_doc_claims.py` (16), which hold the cases for the
    checks that live next door."""
    for name, fn in sorted(vars(module).items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print("ok   " + name)
        except AssertionError as exc:
            failed += 1
            print("FAIL " + name + ": " + str(exc))
    return failed


def main() -> int:
    # Checks 1-8 and 12 here, 9-11, 13-15 and 16 next door, and the packaged-VSIX
    # gate beside them: one self-test entry point, so the e2e drivers and the CI
    # job keep running every gate's own suite from one line.
    import test_doc_claims
    import test_doc_figures
    import test_doc_numbers
    import test_vsix_check

    failed = run_module(sys.modules[__name__])
    failed = run_module(test_doc_numbers, failed)
    failed = run_module(test_doc_figures, failed)
    failed = run_module(test_doc_claims, failed)
    failed = run_module(test_vsix_check, failed)
    print(("%d test(s) failed" % failed) if failed else "check_docs self-test OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
