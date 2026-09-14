#!/usr/bin/env python
"""Checks 9, 10 and 11 of the doc gate: claims a machine can settle.

`check_docs.py` checks whether the prose names things that exist. These three
check whether it names the *right numbers* — the cases where a figure written in
Markdown has an authoritative copy somewhere in the tree, and the two silently
drifted apart. Stdlib only, offline, and they read files the gate already has.

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

Imported by `scripts/check_docs.py`; `scripts/test_check_docs.py` tests it.
"""
from __future__ import annotations

import io
import json
import re
from pathlib import Path

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


def run(root: Path, paths, problems: list) -> None:
    """All three checks, in the order the docstring numbers them."""
    check_accuracy_numbers(root, problems)
    check_artifact_uploads(root, problems)
    check_step_counts(root, paths, problems)
