#!/usr/bin/env python3
"""ANA-12 - the accuracy referee.

Runs the analyzer over the labelled corpus in `analyzer/tests/accuracy/corpus/`
and prints four tables:

* **per-rule precision / recall / F1** over every labelled program;
* **graph fidelity** - the hand-labelled human-diagram ops each program's graph
  actually recovered;
* **confidence calibration** - each `confidenceBucket` binned against the
  verdict of the findings in it, as a reliability curve;
* the **gate verdict** against `analyzer/tests/accuracy/baseline.json`.

    python tools/accuracy.py                 # print the report and gate
    python tools/accuracy.py --update-baseline
    python tools/accuracy.py --program hydra_research --no-gate
    python tools/accuracy.py --json report.json

Neither tolerance has an escape hatch, and both flags that used to be one
are now closed (TB-02):

* `--no-gate` suppresses the **ratchet** gate only. A `forbidden` finding
  still exits 2, because the tolerance for it is zero and is not a baseline.
* `--update-baseline` refuses to record a number that moved **down**; it
  prints the before/after of every number that moved and exits 3. Recording
  a downward move takes `--allow-regression "<reason>"`, and the reason is
  written into the baseline's `note` so the file says why it went backwards.

Exit codes: `0` green, `2` a **forbidden** finding fired (never tolerated,
and `--no-gate` does not tolerate it either), `3` a recall or graph-fidelity
regression against the committed baseline - or a `--update-baseline` that
would have recorded one - `4` the corpus or a `labels.json` is malformed.

Labelling model (ROADMAP ANA-12, three verdicts, not two):

* `expected`   - a planted defect. Satisfying it is a true positive; leaving it
                 unsatisfied is a miss and moves recall.
* `acceptable` - the tool *may* say this. Neither a true positive nor a false
                 one; it exists so the corpus is not a ceiling.
* `forbidden`  - firing here is wrong, and the label must say why. Any hit is a
                 hard failure regardless of the baseline.

An unsuppressed finding that satisfies no label at all is counted as a false
positive: the corpus is labelled exhaustively on purpose, and `acceptable` is
how a legitimate-but-unplanted observation is expressed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from accuracy_corpus import (  # noqa: E402  - after the sys.path fix above
    ACCURACY_DIR, BASELINE_PATH, CORPUS_DIR, EPSILON, HIGH_VALUE,
    IP_BASELINE_PATH, REPO_ROOT, VISIBLE_THRESHOLD, CorpusError, Program,
    aggregate, load_programs, matches, run_corpus, score_graph, score_program)

# Re-exported so `analyzer/tests/accuracy/test_accuracy.py` can load this one
# file and reach the whole surface: the tool a human runs and the module the
# suite asserts are then provably the same code.
__all__ = ["main", "render", "check", "build_baseline", "load_baseline",
           "baseline_moves", "gated_numbers",
           "run_corpus", "load_programs", "score_program", "score_graph",
           "aggregate", "matches", "Program", "CorpusError", "EPSILON",
           "VISIBLE_THRESHOLD", "CORPUS_DIR", "BASELINE_PATH", "IP_BASELINE_PATH"]

EXIT_OK, EXIT_FORBIDDEN, EXIT_REGRESSION, EXIT_CORPUS = 0, 2, 3, 4


# ----------------------------------------------------------------- rendering
def _pct(value: Optional[float]) -> str:
    """A percentage, or `not labelled` when nothing was measured (ANA-12)."""
    if value is None:
        return "  not labelled"
    return "%5.1f%%" % (100.0 * value)


def render(results: Sequence[Dict[str, Any]], report: Dict[str, Any],
           verbose: bool = False) -> str:
    out: List[str] = []
    add = out.append

    add("MLView accuracy corpus - %d labelled programs%s"
        % (report["programs"],
           "" if report.get("dataflow", "local") == "local"
           else "  [--dataflow %s]" % report["dataflow"]))
    add("")
    add("%-24s %5s %5s %6s %6s %6s %6s %6s" % (
        "program", "files", "found", "labels", "hit", "miss", "fp", "graph"))
    add("-" * 74)
    for result in sorted(results, key=lambda r: r["name"]):
        labels = [r for r in result["rows"] if r["verdict"] != "acceptable"]
        hit = sum(1 for r in labels if r["issue"] is not None)
        fp = len(result["forbidden"]) + len(result["unlabelled"])
        add("%-24s %5d %5d %6d %6d %6d %6d %5s%s" % (
            result["name"] + ("*" if result["tuned"] else ""), result["files"],
            result["findings"], len(labels), hit, len(labels) - hit, fp,
            _pct(result["graph"]["score"]).strip()
            if result["graph"]["score"] is not None else "n/l",
            "" if not result["forbidden"] else "  FORBIDDEN"))
    add("-" * 74)
    add("* tuned: the rules were developed against this project; excluded from the")
    add("  unseen headline below.")
    add("")

    add("per-rule precision / recall  (labelled corpus, unsuppressed findings)")
    add("")
    add("%-9s %7s %6s %8s %4s %10s %8s %6s %13s" % (
        "rule", "labels", "found", "visible", "fp", "precision", "recall", "f1",
        "unseen recall"))
    add("-" * 80)
    for code, data in report["perRule"].items():
        tuned_only = data.get("unseenExpected", 0) == 0 and data["expected"] > 0
        add("%-9s %7d %6d %8d %4d %10s %8s %6.2f %13s" % (
            code + ("*" if tuned_only else ""),
            data["expected"], data["recovered"], data["visible"],
            data["falsePositives"],
            _pct(data["precision"]) if data["recovered"] + data["falsePositives"] else "     -",
            _pct(data["recall"]) if data["expected"] else "     -",
            data["f1"],
            _pct(data.get("unseenRecall")).strip()
            if data.get("unseenRecall") is not None else "-"))
    add("-" * 80)
    add("visible = confidence >= %.2f, the VS Code Problems panel default." % VISIBLE_THRESHOLD)
    add("* every label for this rule lives in a program the rule was developed")
    add("  against, so its recall column is a ceiling and not a measurement: the")
    add("  unseen column is what the rule is known to find on code nobody tuned it")
    add("  on, and `-` there means nothing unseen has been labelled for it yet.")
    add("")

    graph = report["graphFidelity"]
    add("graph fidelity - hand-labelled human-diagram ops recovered")
    add("")
    add("%-24s %8s %12s %13s %10s" % ("program", "ops", "recovered", "score", "edges"))
    add("-" * 70)
    for result in sorted(results, key=lambda r: r["name"]):
        g = result["graph"]
        add("%-24s %8d %12d %13s %10s" % (
            result["name"], g["opsLabelled"], g["opsRecovered"],
            _pct(g["score"]).strip(),
            "%d/%s" % (g["edgesActual"],
                       g["edgesLabelled"] if g["edgesLabelled"] else "-")))
    add("-" * 70)
    add("%-24s %8d %12d %13s" % ("TOTAL", graph["opsLabelled"], graph["opsRecovered"],
                                 _pct(graph["score"]).strip()))
    add("`not labelled` is a program with no `graph` block in its labels.json:")
    add("nobody drew a diagram for it, so nothing was measured. It contributes")
    add("nothing to the TOTAL, and never did.")
    add("")

    add("confidence calibration - bucket vs observed precision")
    add("")
    add("%-14s %6s %6s %6s %14s %14s %8s" % (
        "bucket", "n", "tp", "fp", "mean conf", "observed prec", "error"))
    add("-" * 74)
    order = ["certain", "likely", "possible", "speculative"]
    for name in order + sorted(set(report["calibration"]) - set(order)):
        data = report["calibration"].get(name)
        if not data:
            continue
        add("%-14s %6d %6d %6d %14.3f %14s %8.3f" % (
            name, data["n"], data["tp"], data["fp"], data["meanConfidence"],
            _pct(data["observedPrecision"]).strip(), data["error"]))
    add("-" * 74)
    add("Reported, not gated: at this corpus size a bucket can hold two findings,")
    add("so a single label flips its observed precision by half.")
    add("")

    for scope in ("overall", "unseen"):
        data = report[scope]
        add("%-8s  labels %3d   recall %s   visible %s   high+medium %s   precision %s"
            % (scope, data["expectedLabels"], _pct(data["recall"]),
               _pct(data["visibleRecall"]), _pct(data["highValueRecall"]),
               _pct(data["precision"])))
    add("")

    if verbose:
        add("MISSED LABELS - the planted defects nothing fired on")
        for result in sorted(results, key=lambda r: r["name"]):
            for row in result["rows"]:
                if row["issue"] is not None or row["verdict"] == "acceptable":
                    continue
                label = row["label"]
                add("  %-22s %s  %s:%s  %s" % (
                    result["name"], label["code"], label.get("file", "-"),
                    label.get("line", "-"), label.get("defect", "")))
        add("")
        add("MISSING GRAPH OPS - hand-labelled ops with no node anchored on them")
        for result in sorted(results, key=lambda r: r["name"]):
            for op in result["graph"]["missing"]:
                add("  %-22s %s:%s  %s" % (result["name"], op.get("file"),
                                           op.get("line"), op.get("symbol")))
        add("")

    if report["forbiddenFindings"]:
        add("FORBIDDEN FINDINGS")
        for result in results:
            for hit in result["forbidden"]:
                issue, label = hit["issue"], hit["label"]
                add("  %s  %s at %s:%s" % (result["name"], issue["code"],
                                           issue["loc"]["file"], issue["loc"]["line"]))
                add("      the label says: %s" % label["why"])
        add("")
    if report["unlabelledFindings"]:
        add("UNLABELLED FINDINGS (counted as false positives)")
        for result in results:
            for issue in result["unlabelled"]:
                add("  %s  %s at %s:%s  conf %.2f" % (
                    result["name"], issue["code"], issue["loc"]["file"],
                    issue["loc"]["line"], issue.get("confidence", 0.0)))
        add("")
    return "\n".join(out)


# --------------------------------------------------------------------- gates
def load_baseline(path: str = BASELINE_PATH) -> Optional[Dict[str, Any]]:
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def gated_numbers(data: Dict[str, Any]) -> Dict[str, float]:
    """Every number the ratchet gate reads, flattened to one label -> value map.

    `check()` and `--update-baseline` must agree on *exactly* which numbers may
    only go up; sharing this function is how they are kept from drifting apart
    (TB-02: they had drifted all the way to "one gates, the other does not").
    A baseline and a fresh report have the same shape here, so the same call
    flattens either one.
    """
    out: Dict[str, float] = {}
    for scope in ("overall", "unseen"):
        for key in ("recall", "visibleRecall", "highValueRecall", "precision"):
            out["%s %s" % (scope, key)] = float(
                (data.get(scope) or {}).get(key, 0.0))
    for code, values in sorted((data.get("perRule") or {}).items()):
        out["%s recall" % code] = float((values or {}).get("recall", 0.0))
    out["graph fidelity"] = float((data.get("graphFidelity") or {}).get("score", 0.0))
    return out


def baseline_moves(report: Dict[str, Any], baseline: Optional[Dict[str, Any]]
                   ) -> Tuple[List[Tuple[str, float, float]],
                              List[Tuple[str, float, float]]]:
    """`(down, up)` - every gated number that moved, as `(label, was, now)`.

    A per-rule number the baseline records and the report no longer has counts
    as a move to 0.0, which is a regression: a rule that stopped being scored
    at all is exactly the silent recall loss the ratchet exists to catch.
    """
    if baseline is None:
        return [], []
    was_all = gated_numbers(baseline)
    now_all = gated_numbers(report)
    down: List[Tuple[str, float, float]] = []
    up: List[Tuple[str, float, float]] = []
    for label in sorted(set(was_all) | set(now_all)):
        was = was_all.get(label, 0.0)
        now = now_all.get(label, 0.0)
        if now + EPSILON < was:
            down.append((label, was, now))
        elif was + EPSILON < now:
            up.append((label, was, now))
    return down, up


def check(report: Dict[str, Any], baseline: Optional[Dict[str, Any]]) -> List[str]:
    """Every gate failure, most serious first. Empty means green."""
    failures: List[str] = []
    if report["forbiddenFindings"]:
        failures.append("%d forbidden finding(s) fired - the tolerance is zero, always"
                        % report["forbiddenFindings"])
    if baseline is None:
        return failures
    for scope in ("overall", "unseen"):
        for key in ("recall", "visibleRecall", "highValueRecall", "precision"):
            was = float(baseline.get(scope, {}).get(key, 0.0))
            now = float(report[scope][key])
            if now + EPSILON < was:
                failures.append("%s %s fell from %.4f to %.4f - it may only ratchet up"
                                % (scope, key, was, now))
    if report["unlabelledFindings"]:
        # These already cost precision, but say it in words: a new finding that
        # is legitimate but unplanted is a missing label, not a broken rule.
        failures.append("%d finding(s) satisfy no label - add them to that "
                        "program's `expected` or `acceptable` list"
                        % report["unlabelledFindings"])
    for code, data in (baseline.get("perRule") or {}).items():
        was = float(data.get("recall", 0.0))
        now = float(report["perRule"].get(code, {}).get("recall", 0.0))
        if now + EPSILON < was:
            failures.append("%s recall fell from %.4f to %.4f" % (code, was, now))
    was_graph = float((baseline.get("graphFidelity") or {}).get("score", 0.0))
    now_graph = float(report["graphFidelity"]["score"])
    if now_graph + EPSILON < was_graph:
        failures.append("graph fidelity fell from %.4f to %.4f" % (was_graph, now_graph))
    return failures


def build_baseline(report: Dict[str, Any], note: str = "",
                   regression_reason: str = "") -> Dict[str, Any]:
    import datetime
    note = note or ("ANA-12 day one. Recall may only ratchet up; a forbidden "
                    "finding is never tolerated. Regenerate with "
                    "`python tools/accuracy.py --update-baseline` and say in "
                    "the commit body which rule change earned the new number.")
    if regression_reason:
        # A sanctioned downward move is recorded *in the file*, not only in a
        # commit body: the next reader of this baseline has to be able to see
        # that a number was lowered on purpose, and why.
        note += (" SANCTIONED REGRESSION (--allow-regression): %s"
                 % regression_reason)
    return {
        "recordedOn": datetime.date.today().isoformat(),
        "note": note,
        "programs": report["programs"],
        "dataflow": report.get("dataflow", "local"),
        "overall": report["overall"],
        "unseen": report["unseen"],
        "perRule": report["perRule"],
        "graphFidelity": {k: v for k, v in report["graphFidelity"].items()
                          if k != "perProgram"},
        "calibration": report["calibration"],
    }


# ----------------------------------------------------------------------- CLI
def _update_baseline(args, report: Dict[str, Any]) -> int:
    """`--update-baseline`, with the ratchet actually enforced (TB-02).

    The flag used to rewrite the file from whatever the current run produced,
    which made "recall may only ratchet up" a comment rather than a rule: one
    command erased a regression, and the file it wrote still carried the note
    claiming the invariant. It now loads the baseline it is about to
    overwrite, prints every gated number that moved in either direction, and
    refuses a downward move unless `--allow-regression REASON` says so in as
    many words - and then writes that reason into the baseline's own note.
    """
    if args.program:
        sys.stderr.write("accuracy: refusing to rebaseline from a subset "
                         "(--program was given)\n")
        return EXIT_CORPUS
    if report["forbiddenFindings"]:
        sys.stderr.write("accuracy: refusing to rebaseline while %d forbidden "
                         "finding(s) fire - fix the rule, not the baseline\n"
                         % report["forbiddenFindings"])
        return EXIT_FORBIDDEN

    previous = load_baseline(args.baseline)
    down, up = baseline_moves(report, previous)
    for label, was, now in down:
        print("baseline DOWN  %-28s %.4f -> %.4f" % (label, was, now))
    for label, was, now in up:
        print("baseline up    %-28s %.4f -> %.4f" % (label, was, now))
    if down and not args.allow_regression:
        sys.stderr.write(
            "accuracy: refusing to record %d number(s) that moved down - recall "
            "may only ratchet up. Fix the regression, or re-run with "
            "--allow-regression \"why this is correct\".\n" % len(down))
        return EXIT_REGRESSION
    if down:
        print("recording %d downward move(s): %s" % (len(down), args.allow_regression))
    elif not up and previous is not None:
        print("no gated number moved")

    with open(args.baseline, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(build_baseline(report,
                                 regression_reason=args.allow_regression or ""),
                  handle, indent=2, sort_keys=True)
        handle.write("\n")
    print("baseline written to %s" % args.baseline)
    return EXIT_OK


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tools/accuracy.py", description="ANA-12 labelled-accuracy referee")
    parser.add_argument("--corpus", default=CORPUS_DIR)
    parser.add_argument("--baseline", default=None,
                        help="baseline file (default: the one for --dataflow)")
    # DATAFLOW-IP (CONTRACTS 11.36). `local` is the default here as it is
    # everywhere else, so `python tools/accuracy.py` with no flags measures and
    # gates exactly what it always measured and gated. `ip` scores the
    # interprocedural mode against `baseline.ip.json` - a separate ratchet,
    # because two different analyses cannot share one.
    parser.add_argument("--dataflow", choices=("local", "ip"), default="local",
                        help="which dataflow mode to score (default: local)")
    parser.add_argument("--program", action="append", default=[],
                        help="score only this program (repeatable)")
    parser.add_argument("--update-baseline", action="store_true",
                        help="rewrite the baseline from this run; refuses when "
                             "any gated number would move down")
    parser.add_argument("--allow-regression", dest="allow_regression",
                        metavar="REASON", default=None,
                        help="with --update-baseline: record a downward move, "
                             "writing REASON into the baseline's note")
    parser.add_argument("--json", dest="json_path", default=None,
                        help="also write the machine-readable report here")
    parser.add_argument("--no-gate", action="store_true",
                        help="print the report without failing on a ratchet "
                             "regression; a forbidden finding still exits 2")
    parser.add_argument("--verbose", action="store_true",
                        help="also list every missed label and missing graph op")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    if args.baseline is None:
        args.baseline = IP_BASELINE_PATH if args.dataflow == "ip" else BASELINE_PATH

    try:
        results, report = run_corpus(args.corpus, tuple(args.program),
                                     dataflow=args.dataflow)
    except CorpusError as exc:
        sys.stderr.write("accuracy: %s\n" % exc)
        return EXIT_CORPUS

    report["dataflow"] = args.dataflow
    if not args.quiet:
        print(render(results, report, verbose=args.verbose))

    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")

    if args.update_baseline:
        return _update_baseline(args, report)

    baseline = None if args.program else load_baseline(args.baseline)
    failures = check(report, baseline)
    if baseline is None and not args.program:
        print("no baseline at %s - run --update-baseline to record one"
              % args.baseline)
    if not failures:
        print("accuracy gate: PASS")
        return EXIT_OK
    for line in failures:
        print("accuracy gate: FAIL - %s" % line)
    if report["forbiddenFindings"]:
        # Gate 1 has no flag. `--no-gate` suppresses the *ratchet*, which is a
        # comparison against a baseline; a forbidden finding is not a
        # regression against anything, it is the corpus saying a rule fired
        # where it must never fire, and the tolerance for that is zero always.
        if args.no_gate:
            print("accuracy: --no-gate covers the ratchet gate only - a "
                  "forbidden finding is never tolerated")
        return EXIT_FORBIDDEN
    if args.no_gate:
        return EXIT_OK
    return EXIT_REGRESSION


if __name__ == "__main__":
    sys.exit(main())

