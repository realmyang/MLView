#!/usr/bin/env python
"""Checks 9, 10, 11, 19 and 20 of the doc gate: claims a machine can settle.

`check_docs.py` checks whether the prose names things that exist. These five
check whether it names the *right numbers* — the cases where a figure written in
Markdown has an authoritative copy somewhere in the tree, and the two silently
drifted apart. Checks 19 and 20 are the same idea pointed at two claims that are
not numbers but are just as checkable: a command line a CI job generates (is it
one the tool accepts?) and a document's list of which rules pay the
interprocedural hop weight (does the code hold such a list at all?). Stdlib
only, offline, and they read files the gate already has.

9.  **The accuracy headline agrees with the recorded baseline.** `docs/ACCURACY.md`
    §3 quotes precision, three recall readings and graph fidelity;
    `analyzer/tests/accuracy/baseline.json` is the ratchet the gate actually
    enforces. When the ANA-1 re-baseline moved graph fidelity 0.6619 -> 0.8633 the
    baseline was re-recorded and the document was not, so the honesty document
    published `92 of 139, 66.2%` while the gate held 120 of 139 — and went on to
    explain the stale figure with a defect the same branch had repaired
    (TB-08 / DOC-ACCURACY-02). Nothing could catch it: the doc gate did not even
    look at that file. Both are machine-readable, so they are now compared.

10. **An artifact upload whose path is hidden says so.** `actions/upload-artifact`
    skips dot-directories unless `include-hidden-files: true` is set, and with
    `if-no-files-found: warn` the step then *passes* while uploading nothing. Both
    e2e jobs uploaded `.mlview/*.html`; across four runs the repository archived
    zero artifacts and every run was green (CI-ARTIFACTS-01). A silent upload is
    worse than a failed one, so the combination is now a build error here.

11. **"N steps" is the number of steps.** ANA-12's acceptance asked the e2e driver
    to gain an accuracy row, and the reason given for leaving it out was that four
    documents quote "17 steps" (ANA12-E2E-05). This check makes that the cheap
    edit it should be: it counts the rows each driver can print, requires the
    PowerShell and the POSIX driver to print the *same* table, and holds every
    `N steps` / `N-step` claim on a line naming `e2e` to that count.

19. **A CI command line the tool would refuse.** `.github/workflows/public-corpus.yml`
    built `python tools/public_corpus.py fetch --repo <names>` from its
    `workflow_dispatch` `repos` input, and that option lived only on the
    top-level parser: argparse answered `unrecognized arguments` and exited 2, so
    every dispatch that used the documented input died at the job's first step,
    and nothing in the tree could notice because a workflow is text nobody runs
    until the schedule does (PUB2-10). A workflow's `run:` lines are now parsed
    with **the tool's own parser** — `build_parser()` in `tools/public_corpus.py`
    and `tools/verify.py` — after expanding each conditional fragment
    (`${{ ... || '' }}`, `${VAR:+...}`) into every literal line it can produce.
    The authority is never a list in this file: the workflow names the script and
    the script answers with its parser, so a new option, a renamed subcommand or
    a second CI line is covered the day it is written.

20. **A closed list of rules where the code holds none.** `docs/ACCURACY.md` §6
    said *"Only MLV101 and MLV102 consume the hop chain"*, and by then IP-01 had
    made the payment rule-agnostic: `RuleContext.note_hops` records every
    interprocedurally widened value **whichever** rule reads it, and `issue()`
    charges that rule one `cross_file` factor. Measured on the labelled corpus in
    `ip`, the rules that actually paid were MLV101, MLV401 and MLV803 — so the
    sentence was wrong in both directions at once, and it is the sentence a rule
    author reads to decide whether hop weights are their problem (VIS2-17). A
    living doc may therefore name an exclusive list of rule codes for the hop
    chain only when a constant in `analyzer/src/mlview/rules/` enumerates exactly
    those codes; otherwise the list is a guess with no way to go stale loudly.

Imported by `scripts/check_docs.py`; `scripts/test_doc_numbers.py` tests it.
"""
from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import doc_figures  # noqa: E402  - sibling module, after the sys.path fix above

#: Which documents may be held to today's tree, and the one phrase that marks a
#: paragraph as a record of what was true when it was written. Both are policy,
#: not detail, so they are read from the sibling that first wrote them down
#: rather than copied: two gates disagreeing about what "living" means is the
#: same class of defect as the ones they catch.
LIVING_DOCS = doc_figures.LIVING_DOCS
HISTORICAL_RE = doc_figures.HISTORICAL_RE


def _lines(path: Path) -> list:
    # newline='' so a CRLF file is read as written, like check_docs.read.
    return io.open(path, encoding="utf-8", newline="").read().splitlines()


# ------------------------------------------------------------------ check 9
ACCURACY_DOC = "docs/ACCURACY.md"
ACCURACY_BASELINE = "analyzer/tests/accuracy/baseline.json"
# A percentage is printed to one decimal, so a claim may sit half a tenth from
# the stored ratio without being wrong. Anything further apart is a stale doc.
PCT_TOLERANCE = 0.06

GRAPH_RE = re.compile(r"Graph fidelity: (\d+) of (\d+) hand-labelled ops, "
                      r"([\d.]+)%")
HEADLINE_RE = re.compile(r"^(overall|unseen)\s+labels\s+(\d+)\s+recall\s+([\d.]+)%"
                         r"\s+visible\s+([\d.]+)%\s+high\+medium\s+([\d.]+)%"
                         r"\s+precision\s+([\d.]+)%")
READING_RE = re.compile(r"^\|\s*(raw|visible|high\+medium) recall\s*\|\s*"
                        r"\*\*([\d.]+)%\*\*\s*\|(.*)$")
# (reading label) -> (ratio key, recovered key, denominator key or None)
READINGS = {
    "raw": ("recall", "recovered", "expectedLabels"),
    "visible": ("visibleRecall", "visibleRecovered", None),
    "high+medium": ("highValueRecall", "highValueRecovered", "highValueLabels"),
}


def _off(claim: float, ratio: float) -> bool:
    return abs(claim - ratio * 100.0) > PCT_TOLERANCE


def check_accuracy_numbers(root: Path, problems: list) -> None:
    """docs/ACCURACY.md section 3 against analyzer/tests/accuracy/baseline.json."""
    doc, baseline_path = root / ACCURACY_DOC, root / ACCURACY_BASELINE
    if not doc.is_file() or not baseline_path.is_file():
        return
    try:
        baseline = json.loads(io.open(baseline_path, encoding="utf-8").read())
    except ValueError:  # pragma: no cover - a corrupt baseline fails its own gate
        return
    lines = io.open(doc, encoding="utf-8", newline="").read().splitlines()

    def complain(n, said, holds, what):
        problems.append(
            "%s:%d: says %s but %s holds %s -- re-run `python tools/accuracy.py` "
            "and paste the current numbers; the gate and the honesty document may "
            "not disagree about %s (TB-08)"
            % (ACCURACY_DOC, n, said, ACCURACY_BASELINE, holds, what))

    graph = baseline.get("graphFidelity") or {}
    for n, line in enumerate(lines, 1):
        found = GRAPH_RE.search(line)
        if found and graph:
            got, total, pct = int(found.group(1)), int(found.group(2)), float(found.group(3))
            if (got, total) != (graph.get("opsRecovered"), graph.get("opsLabelled")) \
                    or _off(pct, graph.get("score", 0.0)):
                complain(n, "graph fidelity %d of %d, %.1f%%" % (got, total, pct),
                         "%s of %s, %.1f%%" % (graph.get("opsRecovered"),
                                               graph.get("opsLabelled"),
                                               graph.get("score", 0.0) * 100),
                         "graph fidelity")

        found = HEADLINE_RE.match(line)
        if found:
            scope = baseline.get(found.group(1)) or {}
            claimed = {"labels": int(found.group(2)), "recall": float(found.group(3)),
                       "visibleRecall": float(found.group(4)),
                       "highValueRecall": float(found.group(5)),
                       "precision": float(found.group(6))}
            if scope.get("expectedLabels") != claimed["labels"]:
                complain(n, "%s over %d labels" % (found.group(1), claimed["labels"]),
                         "%s" % scope.get("expectedLabels"), "the label count")
            for key in ("recall", "visibleRecall", "highValueRecall", "precision"):
                if key in scope and _off(claimed[key], scope[key]):
                    complain(n, "%s %s %.1f%%" % (found.group(1), key, claimed[key]),
                             "%.1f%%" % (scope[key] * 100), key)

        found = READING_RE.match(line)
        if found:
            ratio_key, got_key, total_key = READINGS[found.group(1)]
            unseen = baseline.get("unseen") or {}
            counts = [int(x) for x in re.findall(r"\d+", found.group(3))]
            if ratio_key in unseen and _off(float(found.group(2)), unseen[ratio_key]):
                complain(n, "unseen %s recall %s%%" % (found.group(1), found.group(2)),
                         "%.1f%%" % (unseen[ratio_key] * 100), "unseen recall")
            wanted = [unseen.get(got_key)]
            if total_key:
                wanted.append(unseen.get(total_key))
            if counts[:len(wanted)] != wanted:
                complain(n, "%s recall over %s" % (found.group(1),
                                                   " of ".join(str(c) for c in counts[:len(wanted)])),
                         " of ".join(str(w) for w in wanted), "the label counts")


# ----------------------------------------------------------------- check 10
UPLOAD_RE = re.compile(r"uses:\s*actions/upload-artifact@")
PATH_KEY_RE = re.compile(r"^\s*path:\s*(\S.*?)\s*$")
HIDDEN_OK_RE = re.compile(r"^\s*include-hidden-files:\s*true\s*$")
#: `KEY: value` under any `env:` mapping, top-level or per-job. Only used to
#: resolve `${{ env.KEY }}` inside an upload path.
ENV_KEY_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*):\s*(\S.*?)\s*$")
ENV_REF_RE = re.compile(r"\$\{\{\s*env\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
#: Any other expression (`${{ github.workspace }}`): it cannot introduce a dot
#: segment of its own, so it is collapsed to a placeholder before the test.
EXPR_RE = re.compile(r"\$\{\{[^}]*\}\}")


def workflow_env(lines) -> dict:
    """Every `env:` mapping in one workflow, flattened into one dict.

    PUB-01 wrote `path: ${{ env.MLVIEW_PUBLIC_CORPUS_DIR }}/_reports/report.json`
    where the workflow's own `env:` set that variable to
    `${{ github.workspace }}/.public-corpus`. The literal path has a hidden
    segment and the written one does not, so the check that exists for exactly
    this incident saw nothing. Resolving the reference is the difference between
    a gate and a spelling convention.
    """
    values: dict = {}
    for index, line in enumerate(lines):
        if not re.match(r"^\s*env:\s*$", line):
            continue
        indent = len(line) - len(line.lstrip())
        for later in lines[index + 1:]:
            if not later.strip() or later.lstrip().startswith("#"):
                continue
            if len(later) - len(later.lstrip()) <= indent:
                break
            found = ENV_KEY_RE.match(later)
            if found:
                values[found.group(1)] = found.group(2).strip("'\"")
    return values


def resolve_path(target: str, values: dict) -> str:
    """`${{ env.X }}/y` -> the literal path, with other expressions collapsed."""
    for _ in range(4):  # env values may themselves reference env
        expanded = ENV_REF_RE.sub(
            lambda m: values.get(m.group(1), m.group(0)), target)
        if expanded == target:
            break
        target = expanded
    return EXPR_RE.sub("EXPR", target)


def _yaml_steps(lines):
    """Yield the block of lines belonging to each `- ` list item.

    The block ends at the first non-blank, non-comment line indented no deeper
    than the item itself -- not merely at the next `- ` item. `on:`'s
    `- cron: '20 4 * * 1'` sits at indent 4 and every step of the job below it at
    indent 6, so the old rule found no boundary at all and handed the schedule
    entry a block running to end of file: one upload step was then reported
    twice, once under its own name and once under the cron line, in a gate whose
    whole value is naming the line to go and fix.
    """
    starts = [n for n, line in enumerate(lines) if re.match(r"^\s*-\s", line)]
    for start in starts:
        indent = len(lines[start]) - len(lines[start].lstrip())
        end = len(lines)
        for later in range(start + 1, len(lines)):
            text = lines[later]
            if not text.strip() or text.lstrip().startswith("#"):
                continue
            if len(text) - len(text.lstrip()) <= indent:
                end = later
                break
        yield start, lines[start:end]


def check_artifact_uploads(root: Path, problems: list) -> None:
    """CI-ARTIFACTS-01: a hidden upload path needs `include-hidden-files: true`."""
    workflows = root / ".github" / "workflows"
    if not workflows.is_dir():
        return
    for path in sorted(workflows.glob("*.yml")) + sorted(workflows.glob("*.yaml")):
        rel = path.relative_to(root).as_posix()
        lines = io.open(path, encoding="utf-8", newline="").read().splitlines()
        values = workflow_env(lines)
        for start, block in _yaml_steps(lines):
            if not any(UPLOAD_RE.search(line) for line in block):
                continue
            if any(HIDDEN_OK_RE.match(line) for line in block):
                continue
            for line in block:
                found = PATH_KEY_RE.match(line)
                if not found:
                    continue
                written = found.group(1).strip("'\"")
                target = resolve_path(written, values)
                if not any(part.startswith(".") and part not in (".", "..")
                           for part in target.split("/")[:-1]):
                    continue
                problems.append(
                    "%s:%d: uploads `%s` from a hidden directory without "
                    "`include-hidden-files: true` -- upload-artifact skips "
                    "dot-paths, so the glob matches nothing, the step still "
                    "passes under `if-no-files-found: warn`, and the run archives "
                    "no artifact at all (CI-ARTIFACTS-01)"
                    % (rel, start + 1,
                       target if target == written
                       else "%s (written `%s`)" % (target, written)))


# ----------------------------------------------------------------- check 11
E2E_SH = "scripts/e2e.sh"
E2E_PS1 = "scripts/e2e.ps1"
SH_ROW_RE = (re.compile(r'^\s*step\s+"([^"]+)"'),
             re.compile(r'^\s*record\s+[A-Z]+\s+"([^"]+)"'))
PS_ROW_RE = (re.compile(r"^\s*Invoke-Step\s+'([^']+)'"),
             re.compile(r"^\s*Add-Result\s+'([^']+)'"))
# "18 steps", "18-step", "the same 18 steps". A spelled-out number ("grew four
# steps") is deliberately not a claim about the total.
STEP_CLAIM_RE = re.compile(r"(\d+)[ -]steps?\b")
E2E_LINE_RE = re.compile(r"e2e", re.I)


def _rows(path: Path, patterns) -> set:
    """Every distinct row name the driver can print. A row is one table line
    however many branches can produce it, which is what `N steps` counts."""
    names = set()
    for line in io.open(path, encoding="utf-8", newline="").read().splitlines():
        for pattern in patterns:
            found = pattern.match(line)
            if found:
                names.add(found.group(1))
    return names


def check_step_counts(root: Path, paths, problems: list) -> None:
    """ANA12-E2E-05: both drivers print one table, and the docs quote its size."""
    sh, ps1 = root / E2E_SH, root / E2E_PS1
    if not sh.is_file() or not ps1.is_file():
        return
    rows_sh, rows_ps1 = _rows(sh, SH_ROW_RE), _rows(ps1, PS_ROW_RE)
    if rows_sh != rows_ps1:
        problems.append(
            "%s and %s no longer run the same table: %s -- the two drivers are "
            "documented as doing the same thing, so a row added to one belongs in "
            "the other (ANA12-E2E-05)"
            % (E2E_SH, E2E_PS1,
               "; ".join(sorted(["only in e2e.sh: `%s`" % n for n in rows_sh - rows_ps1]
                                + ["only in e2e.ps1: `%s`" % n for n in rows_ps1 - rows_sh]))))
        return
    total = len(rows_sh)
    checked = list(paths) + sorted((root / ".github" / "workflows").glob("*.yml"))
    for path in checked:
        rel = path.relative_to(root).as_posix()
        for n, line in enumerate(io.open(path, encoding="utf-8",
                                         newline="").read().splitlines(), 1):
            if not E2E_LINE_RE.search(line):
                continue
            for claimed in STEP_CLAIM_RE.findall(line):
                if int(claimed) == total:
                    continue
                problems.append(
                    "%s:%d: says the e2e driver has %s steps, but `%s` and `%s` "
                    "print %d rows -- run `sh scripts/e2e.sh` and quote the table "
                    "it prints (ANA12-E2E-05)"
                    % (rel, n, claimed, E2E_SH, E2E_PS1, total))


# ----------------------------------------------------------------- check 19
# `python tools/public_corpus.py`, `python3 scripts/foo.py`, `PYTHONUTF8=1 python
# tools/verify.py`. The tool is a repo-relative path, which is what lets the
# check ask *that* file for its parser instead of holding a table of its flags.
TOOL_RE = re.compile(r"(?:^|\s)(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*"
                     r"(?:python3?|py)\s+(?:-\S+\s+)*((?:tools|scripts)/[\w./-]+\.py)\b")
RUN_KEY_RE = re.compile(r"^(\s*)(?:-\s+)?run:\s*(\|[-+]?|>[-+]?)?\s*(.*?)\s*$")
# One `run:` line can hold several commands. Each is judged on its own.
SHELL_SPLIT_RE = re.compile(r"&&|\|\||[;|]")
# `${{ ... }}`, inner braces and all: `format('--repo {0}', inputs.repos)` has a
# `}` in the middle of it, which is precisely the expression this check exists
# for, so the pattern is lazy to the closing pair rather than "no braces inside".
GH_EXPR_RE = re.compile(r"\$\{\{.*?\}\}")
# `inputs.strict == 'true'` contributes no text to the line; without this the
# check would try `... check --report R true` and blame the workflow for it.
GH_COMPARISON_RE = re.compile(r"[=!]=\s*(?:'[^']*'|\"[^\"]*\"|[\w.]+)")
GH_FORMAT_RE = re.compile(r"format\(\s*'([^']*)'[^)]*\)")
GH_LITERAL_RE = re.compile(r"'([^']*)'|\"([^\"]*)\"|(?<![\w.$])(\d+)(?![\w.])")
# `${REPOS:+--repo "$REPOS"}` - the shell's own conditional, and the way an
# untrusted `workflow_dispatch` input reaches a command line without being pasted
# into the script by `${{ }}`. Either it contributes its text or it contributes
# nothing, so it expands to exactly two lines.
SH_ALT_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*):\+([^{}]*)\}")
#: What a `{0}` in a `format()` template stands for. Any value the input can
#: hold is one token to argparse, so one placeholder covers them all.
PLACEHOLDER = "VALUE"
#: A line with more than a handful of conditionals is not a command line.
MAX_VARIANTS = 12


def _run_scripts(lines):
    """Yield (line number of the first body line, [body lines]) per `run:`.

    A block scalar's body ends at the first non-blank line indented no deeper
    than the `run:` key itself - the same boundary rule `_yaml_steps` needed,
    for the same reason. Blank lines stay in the body so a line number is the
    offset into it.
    """
    index = 0
    while index < len(lines):
        found = RUN_KEY_RE.match(lines[index])
        if not found:
            index += 1
            continue
        if found.group(3) and not found.group(2):
            yield index + 1, [found.group(3)]       # `run: python tools/x.py`
            index += 1
            continue
        indent, body, start = len(found.group(1)), [], index + 2
        index += 1
        while index < len(lines):
            text = lines[index]
            if text.strip() and (len(text) - len(text.lstrip())) <= indent:
                break
            body.append(text)
            index += 1
        if body:
            yield start, body


def _command_lines(lines):
    """(line number, one logical shell command) for every `run:` body line.

    `\\`-continuations are joined, because the defect this check exists for was
    written across three of them.
    """
    for start, body in _run_scripts(lines):
        buffer, at = "", None
        for offset, text in enumerate(body):
            stripped = text.strip()
            if not buffer and (not stripped or stripped.startswith("#")):
                continue
            if at is None:
                at = start + offset
            if stripped.endswith("\\"):
                buffer += stripped[:-1] + " "
                continue
            buffer += stripped
            if buffer.strip():
                yield at, buffer.strip()
            buffer, at = "", None
        if buffer.strip():
            yield at or start, buffer.strip()


def _github_candidates(expression: str) -> list:
    """Every literal a `${{ ... }}` expression can put on the command line."""
    inner = GH_COMPARISON_RE.sub(" ", expression[3:-2])
    out: list = []

    def take(value):
        if value not in out:
            out.append(value)

    for found in GH_FORMAT_RE.finditer(inner):
        take(re.sub(r"\{\d+\}", PLACEHOLDER, found.group(1)))
    for found in GH_LITERAL_RE.finditer(GH_FORMAT_RE.sub(" ", inner)):
        take(next(group for group in found.groups() if group is not None))
    # An expression with no literal at all (`${{ github.workspace }}`) is one
    # opaque token, not an empty one: dropping it would shift the argument after
    # it into the option's place and invent a failure.
    return out or ["EXPR"]


def _variants(command: str) -> list:
    """Every literal command line this one can become, conditionals expanded."""
    out = [command]
    for _ in range(4):
        grown, changed = [], False
        for text in out:
            found = min((m for m in (GH_EXPR_RE.search(text), SH_ALT_RE.search(text))
                         if m), key=lambda m: m.start(), default=None)
            if found is None:
                grown.append(text)
                continue
            changed = True
            candidates = (_github_candidates(found.group(0))
                          if found.re is GH_EXPR_RE else ["", found.group(2)])
            for candidate in candidates:
                grown.append(text[:found.start()] + candidate + text[found.end():])
        out = grown[:MAX_VARIANTS]
        if not changed:
            break
    return out


def tool_parser(root: Path, rel: str, cache: dict):
    """The tool's own `build_parser()`, or None when it does not offer one.

    A tool that does not expose one is simply not checked: this gate may not
    become a reason to import something with side effects, and it runs in a CI
    job that never installs `mlview`.
    """
    if rel not in cache:
        cache[rel] = None
        path = root / rel
        if path.is_file():
            saved = list(sys.path)
            try:
                name = "_mlview_doc_gate_" + re.sub(r"\W", "_", rel)
                spec = importlib.util.spec_from_file_location(name, path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                factory = getattr(module, "build_parser", None)
                cache[rel] = factory if callable(factory) else None
            except Exception:  # pragma: no cover - an unimportable tool is not a doc defect
                cache[rel] = None
            finally:
                sys.path[:] = saved
    return cache[rel]


def _refusal(parser, argv) -> str:
    """argparse's own message when it would refuse this argv, else ``''``."""
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            parser.parse_args(argv)
    except SystemExit as stop:
        if stop.code:
            message = " ".join(err.getvalue().split())
            return message or ("exit %s" % stop.code)
    except Exception as exc:  # pragma: no cover - a parser with a raising type
        return "%s: %s" % (type(exc).__name__, exc)
    return ""


def check_ci_command_lines(root: Path, problems: list) -> None:
    """PUB2-10: a command line CI generates is one the tool has to accept."""
    workflows = root / ".github" / "workflows"
    if not workflows.is_dir():
        return
    cache: dict = {}
    for path in sorted(workflows.glob("*.yml")) + sorted(workflows.glob("*.yaml")):
        rel = path.relative_to(root).as_posix()
        reported: set = set()
        for number, command in _command_lines(_lines(path)):
            # Expand first, split second: `${{ a && b || '' }}` carries the
            # shell's own `||` inside it, so splitting a raw line on shell
            # operators tears the expression in half and blames the tool for it.
            for variant in _variants(command):
                for segment in SHELL_SPLIT_RE.split(variant):
                    found = TOOL_RE.search(segment)
                    if not found:
                        continue
                    tool = found.group(1)
                    factory = tool_parser(root, tool, cache)
                    if factory is None or (number, tool) in reported:
                        continue
                    try:
                        argv = shlex.split(segment[found.end(1):].strip(),
                                           comments=True)
                    except ValueError:  # pragma: no cover - unbalanced quoting
                        continue
                    refusal = _refusal(factory(), argv)
                    if not refusal:
                        continue
                    reported.add((number, tool))
                    problems.append(
                        "%s:%d: CI runs `%s %s`, and %s refuses it: %s -- a "
                        "workflow is generated text nobody runs until the "
                        "schedule does, so its command lines are parsed with "
                        "the tool's own `build_parser()` (PUB2-10)"
                        % (rel, number, tool, " ".join(argv), tool, refusal))


# ----------------------------------------------------------------- check 20
RULES_DIR = "analyzer/src/mlview/rules"
HOP_MECHANISM = "analyzer/src/mlview/rules/context.py"
RULE_CODE_RE = re.compile(r"\bMLV\d{3}\b")
# A constant that could be the list the prose claims: named for the mechanism,
# and holding rule codes. `HOP_KINDS` holds hop kinds, not codes, so it is not.
HOP_CONST_RE = re.compile(r"(?:^|_)(?:HOP|IP|CROSS_FILE|INTERPROC\w*)(?:_|$)")
# The claim, in the two orders it gets written: "only MLV101 and MLV102 consume
# the hop chain" and "MLV101 and MLV102 are the only rules that pay for a hop".
# The gaps are bounded and may not cross a sentence end, so a bullet that names
# rule codes and a bullet that says "only" further down the same list are two
# claims, not one -- the folded block is a whole Markdown list, and an unbounded
# pattern read three of those as an exclusivity claim about hops on its first run.
HOP_CLAIM_RE = re.compile(
    r"\bonly\b[^.;:!?]{0,70}?\bMLV\d{3}\b[^.;!?]{0,160}?\bhops?\b"
    r"|\bMLV\d{3}\b[^.;:!?]{0,90}?\bonly\b[^.;!?]{0,120}?\bhops?\b", re.I)


def _folded(lines):
    """(line number, one folded block) per Markdown block.

    A blank line, a new bullet and a table row each start a block: the claim in
    ACCURACY.md §6 is one bullet wrapped over four lines, and the bullet under it
    is a different claim.
    """
    start, buf = 0, []
    for number, line in enumerate(lines, 1):
        text = line.strip()
        starts_block = (not text or text.startswith("|")
                        or re.match(r"[-*]\s+|\d+\.\s+", text))
        if starts_block and buf:
            yield start, " ".join(buf)
            start, buf = 0, []
        if not text:
            continue
        if not buf:
            start = number
        buf.append(text)
    if buf:
        yield start, " ".join(buf)


def hop_code_constants(root: Path) -> list:
    """Every module-level constant in the rules package that enumerates codes.

    Parsed, never imported: the doc gate runs where `mlview` is not installed.
    """
    out: list = []
    package = root / RULES_DIR
    if not package.is_dir():
        return out
    for path in sorted(package.glob("*.py")):
        try:
            tree = ast.parse(io.open(path, encoding="utf-8").read())
        except (OSError, SyntaxError):  # pragma: no cover - a broken rules tree
            continue
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if not any(HOP_CONST_RE.search(name) for name in names):
                continue
            if not isinstance(node.value, (ast.Tuple, ast.List, ast.Set)):
                continue
            codes = {e.value for e in node.value.elts
                     if isinstance(e, ast.Constant) and isinstance(e.value, str)
                     and RULE_CODE_RE.fullmatch(e.value)}
            if codes and len(codes) == len(node.value.elts):
                out.append(codes)
    return out


def check_hop_claims(root: Path, paths, problems: list) -> None:
    """VIS2-17: the hop weight is charged to whichever rule read the value."""
    if not (root / HOP_MECHANISM).is_file():
        return
    held = hop_code_constants(root)
    # Every current-state doc, not just the three `LIVING_DOCS` figures live in:
    # the sentence this check exists for is in `docs/ACCURACY.md`, which is where
    # a rule author goes to find out whether hop weights are their problem.
    for path in paths:
        rel = path.relative_to(root).as_posix()
        for number, block in _folded(_lines(path)):
            if HISTORICAL_RE.search(block):
                continue
            for found in HOP_CLAIM_RE.finditer(block):
                claimed = set(RULE_CODE_RE.findall(found.group(0)))
                if not claimed or any(claimed == codes for codes in held):
                    continue
                problems.append(
                    "%s:%d: names %s as the rules that pay the interprocedural "
                    "hop weight, and no constant in `%s` enumerates them -- "
                    "`RuleContext.note_hops` in `%s` records the hop for "
                    "whichever rule read the widened value and `issue()` charges "
                    "that rule one `cross_file` factor, so the payers are "
                    "measured, not listed (VIS2-17)"
                    % (rel, number, ", ".join(sorted(claimed)), RULES_DIR,
                       HOP_MECHANISM))


def run(root: Path, paths, problems: list) -> None:
    """All five checks, in the order the docstring numbers them."""
    check_accuracy_numbers(root, problems)
    check_artifact_uploads(root, problems)
    check_step_counts(root, paths, problems)
    check_ci_command_lines(root, problems)
    check_hop_claims(root, paths, problems)
