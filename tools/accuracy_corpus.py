#!/usr/bin/env python3
"""ANA-12 - loading, matching and scoring the labelled accuracy corpus.

The measurement half of `tools/accuracy.py`, split out so neither file grows
past what one sitting can hold. Nothing here prints; `accuracy.py` owns the
tables, the gate and the CLI.

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

import json
import os
import sys
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACCURACY_DIR = os.path.join(REPO_ROOT, "analyzer", "tests", "accuracy")
CORPUS_DIR = os.path.join(ACCURACY_DIR, "corpus")
BASELINE_PATH = os.path.join(ACCURACY_DIR, "baseline.json")

# The VS Code Problems panel hides anything below this (`mlview.minConfidence`,
# vscode-extension/package.json). A finding under it is emitted but unseen, so
# the report scores recall twice: raw, and as the user would experience it.
VISIBLE_THRESHOLD = 0.6

EPSILON = 1e-9
HIGH_VALUE = ("high", "medium")


# ------------------------------------------------------------------ analyzer
def _import_analyzer():
    try:
        from mlview.api import AnalyzeOptions, analyze_to_dict  # noqa: F401
    except ImportError:
        sys.path.insert(0, os.path.join(REPO_ROOT, "analyzer", "src"))
    from mlview.api import AnalyzeOptions, analyze_to_dict
    return AnalyzeOptions, analyze_to_dict


# -------------------------------------------------------------------- corpus
class CorpusError(Exception):
    pass


class Program:
    """One labelled project: a directory of sources plus its `labels.json`."""

    def __init__(self, name: str, labels_path: str, labels: Dict[str, Any]) -> None:
        self.name = name
        self.labels_path = labels_path
        self.labels = labels
        here = os.path.dirname(labels_path)
        root = labels.get("root")
        self.root = os.path.normpath(os.path.join(here, root)) if root else here
        self.tuned = bool(labels.get("tuned"))
        self.expected = [dict(row) for row in labels.get("expected", [])]
        self.forbidden = [dict(row) for row in labels.get("forbidden", [])]
        self.graph = labels.get("graph") or {}

    @property
    def title(self) -> str:
        return self.labels.get("title", self.name)


def load_programs(corpus_dir: str = CORPUS_DIR,
                  only: Sequence[str] = ()) -> List[Program]:
    if not os.path.isdir(corpus_dir):
        raise CorpusError("no corpus directory at %s" % corpus_dir)
    programs: List[Program] = []
    for name in sorted(os.listdir(corpus_dir)):
        path = os.path.join(corpus_dir, name, "labels.json")
        if not os.path.isfile(path):
            continue
        if only and name not in only:
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                labels = json.load(handle)
        except ValueError as exc:
            raise CorpusError("%s is not valid JSON: %s" % (path, exc))
        program = Program(name, path, labels)
        if not os.path.isdir(program.root):
            raise CorpusError("%s points at a missing root: %s"
                              % (path, program.root))
        for row in program.forbidden:
            if not row.get("why"):
                raise CorpusError("%s: every forbidden label must cite why (%s)"
                                  % (path, row.get("code")))
        programs.append(program)
    if not programs:
        raise CorpusError("no labelled programs found under %s" % corpus_dir)
    if only:
        missing = sorted(set(only) - {p.name for p in programs})
        if missing:
            raise CorpusError("no such program(s): %s" % ", ".join(missing))
    return programs


# ------------------------------------------------------------------ matching
def _norm(path: Optional[str]) -> str:
    text = (path or "").replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text


def _locations(issue: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    loc = issue.get("loc")
    if isinstance(loc, dict):
        yield loc
    for related in issue.get("relatedLocs") or ():
        if isinstance(related, dict):
            yield related


def _covers(locations: Iterable[Dict[str, Any]], file: str,
            line: Optional[int]) -> bool:
    """True when any of `locations` sits in `file` and spans `line`."""
    target = _norm(file)
    for loc in locations:
        if _norm(loc.get("file")) != target:
            continue
        if line is None:
            return True
        start = loc.get("line")
        if start is None:
            continue
        end = loc.get("endLine") or start
        if start <= line <= max(start, end):
            return True
    return False


def _anchor(label: Dict[str, Any]) -> str:
    return label.get("anchor") or ("line" if label.get("line") else "file")


def matches(issue: Dict[str, Any], label: Dict[str, Any]) -> bool:
    """Does `issue` satisfy `label`? Code always; then the label's anchor.

    `project` - anywhere in the program (MLV601 is a whole-workspace claim).
    `file`    - any of the finding's locations lands in that file.
    `line`    - one of them *spans* the labelled line, so a loop-anchored
                absence finding still matches the statement inside the loop
                that a human would point at.
    """
    if issue.get("code") != label.get("code"):
        return False
    anchor = _anchor(label)
    if anchor == "project":
        return True
    line = label.get("line") if anchor == "line" else None
    return _covers(_locations(issue), label.get("file", ""), line)


# ------------------------------------------------------------------- scoring
def score_program(program: Program, doc: Dict[str, Any]) -> Dict[str, Any]:
    findings = [i for i in doc.get("issues", []) if not i.get("suppressed")]
    claimed = [False] * len(findings)
    rows: List[Dict[str, Any]] = []

    for label in program.expected:
        verdict = label.get("verdict", "expected")
        hit = None
        for index, issue in enumerate(findings):
            if claimed[index] or not matches(issue, label):
                continue
            claimed[index] = True
            hit = issue
            break
        rows.append({"label": label, "verdict": verdict, "issue": hit})

    forbidden_hits: List[Dict[str, Any]] = []
    unlabelled: List[Dict[str, Any]] = []
    for index, issue in enumerate(findings):
        if claimed[index]:
            continue
        rule = next((f for f in program.forbidden if matches(issue, f)), None)
        if rule is not None:
            forbidden_hits.append({"issue": issue, "label": rule})
        else:
            unlabelled.append(issue)

    return {
        "name": program.name,
        "title": program.title,
        "tuned": program.tuned,
        "rows": rows,
        "forbidden": forbidden_hits,
        "unlabelled": unlabelled,
        "findings": len(findings),
        "graph": score_graph(program, doc),
        "stats": doc.get("stats", {}),
        "files": doc.get("workspace", {}).get("filesAnalyzed", 0),
    }


def _anchors(doc: Dict[str, Any]) -> set:
    """`(file, line)` for every node in the document, from `loc` and `defLoc`.

    Anchoring is exact on purpose. A `unit` node spans a whole function, so a
    containment test would score an op as *recovered* merely because the
    function that should have contained it exists - which is precisely the
    failure mode the class-method blind spot produces, and precisely what this
    score has to be able to see.
    """
    out = set()
    for node in doc.get("nodes", []):
        for key in ("loc", "defLoc"):
            loc = node.get(key)
            if isinstance(loc, dict) and loc.get("line") is not None:
                out.add((_norm(loc.get("file")), int(loc["line"])))
    return out


def score_graph(program: Program, doc: Dict[str, Any]) -> Dict[str, Any]:
    """Hand-labelled human-diagram ops recovered, and the edge count."""
    ops = program.graph.get("ops") or []
    anchors = _anchors(doc)
    recovered, missing = [], []
    for op in ops:
        key = (_norm(op.get("file")), int(op.get("line")))
        (recovered if key in anchors else missing).append(op)
    expected_edges = int(program.graph.get("edges") or 0)
    actual_edges = int(doc.get("stats", {}).get("edges") or 0)
    return {
        "opsLabelled": len(ops),
        "opsRecovered": len(recovered),
        "missing": missing,
        "score": (len(recovered) / len(ops)) if ops else 1.0,
        "edgesLabelled": expected_edges,
        "edgesActual": actual_edges,
        "edgeRatio": round(actual_edges / expected_edges, 4) if expected_edges else 1.0,
    }


def _visible(issue: Optional[Dict[str, Any]]) -> bool:
    return bool(issue) and float(issue.get("confidence", 0.0)) >= VISIBLE_THRESHOLD


def aggregate(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Per-rule, overall, unseen-only, graph and calibration figures."""
    per_rule: Dict[str, Dict[str, int]] = {}
    buckets: Dict[str, Dict[str, Any]] = {}

    def bucket_of(issue: Dict[str, Any]) -> Dict[str, Any]:
        name = issue.get("confidenceBucket", "unknown")
        return buckets.setdefault(name, {"tp": 0, "fp": 0, "confidence": []})

    def rule_of(code: str) -> Dict[str, int]:
        return per_rule.setdefault(code, {"expected": 0, "recovered": 0,
                                          "visible": 0, "fp": 0})

    totals = {"expected": 0, "recovered": 0, "visible": 0,
              "highExpected": 0, "highRecovered": 0, "fp": 0, "tp": 0}
    unseen = dict(totals)

    for result in results:
        buckets_of_program = unseen if not result["tuned"] else None
        for row in result["rows"]:
            label, issue = row["label"], row["issue"]
            if row["verdict"] == "acceptable":
                continue
            rule = rule_of(label["code"])
            rule["expected"] += 1
            totals["expected"] += 1
            high = label.get("severity") in HIGH_VALUE
            if high:
                totals["highExpected"] += 1
            if buckets_of_program is not None:
                unseen["expected"] += 1
                if high:
                    unseen["highExpected"] += 1
            if issue is None:
                continue
            rule["recovered"] += 1
            totals["recovered"] += 1
            totals["tp"] += 1
            bucket_of(issue)["tp"] += 1
            bucket_of(issue)["confidence"].append(float(issue.get("confidence", 0.0)))
            if high:
                totals["highRecovered"] += 1
            if _visible(issue):
                rule["visible"] += 1
                totals["visible"] += 1
            if buckets_of_program is not None:
                unseen["recovered"] += 1
                unseen["tp"] += 1
                if high:
                    unseen["highRecovered"] += 1
                if _visible(issue):
                    unseen["visible"] += 1

        for entry in list(result["forbidden"]) + [{"issue": i} for i in result["unlabelled"]]:
            issue = entry["issue"]
            rule_of(issue["code"])["fp"] += 1
            totals["fp"] += 1
            bucket_of(issue)["fp"] += 1
            bucket_of(issue)["confidence"].append(float(issue.get("confidence", 0.0)))
            if buckets_of_program is not None:
                unseen["fp"] += 1

    ops_labelled = sum(r["graph"]["opsLabelled"] for r in results)
    ops_recovered = sum(r["graph"]["opsRecovered"] for r in results)

    calibration = {}
    for name, data in buckets.items():
        n = data["tp"] + data["fp"]
        mean_conf = (sum(data["confidence"]) / len(data["confidence"])
                     if data["confidence"] else 0.0)
        observed = (data["tp"] / n) if n else 0.0
        calibration[name] = {
            "n": n, "tp": data["tp"], "fp": data["fp"],
            "meanConfidence": round(mean_conf, 4),
            "observedPrecision": round(observed, 4),
            "error": round(abs(mean_conf - observed), 4),
        }

    return {
        "overall": _ratios(totals),
        "unseen": _ratios(unseen),
        "perRule": {code: _rule_ratios(data) for code, data in sorted(per_rule.items())},
        "graphFidelity": {
            "opsLabelled": ops_labelled,
            "opsRecovered": ops_recovered,
            "score": round(ops_recovered / ops_labelled, 4) if ops_labelled else 1.0,
            "perProgram": {r["name"]: round(r["graph"]["score"], 4) for r in results},
        },
        "calibration": calibration,
        "forbiddenFindings": sum(len(r["forbidden"]) for r in results),
        "unlabelledFindings": sum(len(r["unlabelled"]) for r in results),
        "programs": len(results),
    }


def _ratios(totals: Dict[str, int]) -> Dict[str, Any]:
    expected = totals["expected"]
    high = totals["highExpected"]
    labelled = totals["tp"] + totals["fp"]
    return {
        "expectedLabels": expected,
        "recovered": totals["recovered"],
        "recall": round(totals["recovered"] / expected, 4) if expected else 0.0,
        "visibleRecovered": totals["visible"],
        "visibleRecall": round(totals["visible"] / expected, 4) if expected else 0.0,
        "highValueLabels": high,
        "highValueRecovered": totals["highRecovered"],
        "highValueRecall": round(totals["highRecovered"] / high, 4) if high else 0.0,
        "falsePositives": totals["fp"],
        "precision": round(totals["tp"] / labelled, 4) if labelled else 1.0,
    }


def _rule_ratios(data: Dict[str, int]) -> Dict[str, Any]:
    expected, recovered, fp = data["expected"], data["recovered"], data["fp"]
    precision = recovered / (recovered + fp) if (recovered + fp) else 1.0
    recall = recovered / expected if expected else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {"expected": expected, "recovered": recovered, "visible": data["visible"],
            "falsePositives": fp, "precision": round(precision, 4),
            "recall": round(recall, 4), "f1": round(f1, 4)}


def run_corpus(corpus_dir: str = CORPUS_DIR,
               only: Sequence[str] = ()) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    AnalyzeOptions, analyze_to_dict = _import_analyzer()
    programs = load_programs(corpus_dir, only)
    results = []
    for program in programs:
        doc = analyze_to_dict(AnalyzeOptions(paths=(program.root,)))
        results.append(score_program(program, doc))
    return results, aggregate(results)

