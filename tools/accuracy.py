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

Exit codes: `0` green, `2` a **forbidden** finding fired (never tolerated),
`3` a recall or graph-fidelity regression against the committed baseline,
`4` the corpus or a `labels.json` is malformed.

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
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from accuracy_corpus import (  # noqa: E402  - after the sys.path fix above
    ACCURACY_DIR, BASELINE_PATH, CORPUS_DIR, EPSILON, HIGH_VALUE, REPO_ROOT,
    VISIBLE_THRESHOLD, CorpusError, Program, aggregate, load_programs, matches,
    run_corpus, score_graph, score_program)

# Re-exported so `analyzer/tests/accuracy/test_accuracy.py` can load this one
# file and reach the whole surface: the tool a human runs and the module the
# suite asserts are then provably the same code.
__all__ = ["main", "render", "check", "build_baseline", "load_baseline",
           "run_corpus", "load_programs", "score_program", "score_graph",
           "aggregate", "matches", "Program", "CorpusError", "EPSILON",
           "VISIBLE_THRESHOLD", "CORPUS_DIR", "BASELINE_PATH"]

EXIT_OK, EXIT_FORBIDDEN, EXIT_REGRESSION, EXIT_CORPUS = 0, 2, 3, 4


# ----------------------------------------------------------------- rendering
def _pct(value: float) -> str:
    return "%5.1f%%" % (100.0 * value)


def render(results: Sequence[Dict[str, Any]], report: Dict[str, Any],
           verbose: bool = False) -> str:
    out: List[str] = []
    add = out.append

    add("MLView accuracy corpus - %d labelled programs" % report["programs"])
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
            _pct(result["graph"]["score"]).strip(),
            "" if not result["forbidden"] else "  FORBIDDEN"))
    add("-" * 74)
    add("* tuned: the rules were developed against this project; excluded from the")
    add("  unseen headline below.")
    add("")

    add("per-rule precision / recall  (labelled corpus, unsuppressed findings)")
    add("")
    add("%-8s %8s %8s %8s %8s %10s %8s %7s" % (
        "rule", "labels", "found", "visible", "fp", "precision", "recall", "f1"))
    add("-" * 74)
    for code, data in report["perRule"].items():
        add("%-8s %8d %8d %8d %8d %10s %8s %7.2f" % (
            code, data["expected"], data["recovered"], data["visible"],
            data["falsePositives"],
            _pct(data["precision"]) if data["recovered"] + data["falsePositives"] else "     -",
            _pct(data["recall"]) if data["expected"] else "     -",
            data["f1"]))
    add("-" * 74)
    add("visible = confidence >= %.2f, the VS Code Problems panel default." % VISIBLE_THRESHOLD)
    add("")

    graph = report["graphFidelity"]
    add("graph fidelity - hand-labelled human-diagram ops recovered")
    add("")
    add("%-24s %8s %8s %8s %10s" % ("program", "ops", "recovered", "score", "edges"))
    add("-" * 62)
    for result in sorted(results, key=lambda r: r["name"]):
        g = result["graph"]
        add("%-24s %8d %8d %8s %10s" % (
            result["name"], g["opsLabelled"], g["opsRecovered"],
            _pct(g["score"]).strip(), "%d/%d" % (g["edgesActual"], g["edgesLabelled"])))
    add("-" * 62)
    add("%-24s %8d %8d %8s" % ("TOTAL", graph["opsLabelled"], graph["opsRecovered"],
                               _pct(graph["score"]).strip()))
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


def build_baseline(report: Dict[str, Any], note: str = "") -> Dict[str, Any]:
    import datetime
    return {
        "recordedOn": datetime.date.today().isoformat(),
        "note": note or ("ANA-12 day one. Recall may only ratchet up; a forbidden "
                         "finding is never tolerated. Regenerate with "
                         "`python tools/accuracy.py --update-baseline` and say in "
                         "the commit body which rule change earned the new number."),
        "programs": report["programs"],
        "overall": report["overall"],
        "unseen": report["unseen"],
        "perRule": report["perRule"],
        "graphFidelity": {k: v for k, v in report["graphFidelity"].items()
                          if k != "perProgram"},
        "calibration": report["calibration"],
    }


# ----------------------------------------------------------------------- CLI
def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tools/accuracy.py", description="ANA-12 labelled-accuracy referee")
    parser.add_argument("--corpus", default=CORPUS_DIR)
    parser.add_argument("--baseline", default=BASELINE_PATH)
    parser.add_argument("--program", action="append", default=[],
                        help="score only this program (repeatable)")
    parser.add_argument("--update-baseline", action="store_true",
                        help="rewrite the baseline from this run (ratchet up)")
    parser.add_argument("--json", dest="json_path", default=None,
                        help="also write the machine-readable report here")
    parser.add_argument("--no-gate", action="store_true",
                        help="print the report without failing on a regression")
    parser.add_argument("--verbose", action="store_true",
                        help="also list every missed label and missing graph op")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    try:
        results, report = run_corpus(args.corpus, tuple(args.program))
    except CorpusError as exc:
        sys.stderr.write("accuracy: %s\n" % exc)
        return EXIT_CORPUS

    if not args.quiet:
        print(render(results, report, verbose=args.verbose))

    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")

    if args.update_baseline:
        if args.program:
            sys.stderr.write("accuracy: refusing to rebaseline from a subset "
                             "(--program was given)\n")
            return EXIT_CORPUS
        with open(args.baseline, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(build_baseline(report), handle, indent=2, sort_keys=True)
            handle.write("\n")
        print("baseline written to %s" % args.baseline)
        return EXIT_FORBIDDEN if report["forbiddenFindings"] else EXIT_OK

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
    if args.no_gate:
        return EXIT_OK
    return EXIT_FORBIDDEN if report["forbiddenFindings"] else EXIT_REGRESSION


if __name__ == "__main__":
    sys.exit(main())

