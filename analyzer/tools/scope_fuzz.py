#!/usr/bin/env python
"""Differential-fuzz the two `project()` implementations (HEALTH-02, 11.30).

    PYTHONUTF8=1 python analyzer/tools/scope_fuzz.py --cases 200 [--seed N]
    python tools/verify.py --scopes --fuzz 200          # the same thing, as a gate row

`analyzer/src/mlview/core/project.py` and `webview/src/scope/project.ts` are one
algorithm written twice, and CONTRACTS 11.16 says they move together. The
fixture battery proves it on **one** frozen 45-node document over 16 selectors;
this proves it on generated ones. The documents come from `scope_gen.py` -
node counts 5..500, hierarchy depth, cross-stage parents, ghost density, issues
anchored on up to four nodes, issues anchored on an *edge* whose nodes are
elsewhere, disconnected components - and the selectors span every scope kind at
every legal depth. This file is the driver: build a batch, run ONE node process
over it, compare, minimize, promote.

Three properties keep it a gate rather than a lottery:

* **Seeded.** `--seed` reproduces a run byte for byte; a failure is replayable.
* **Schema-valid inputs.** Every generated document passes
  `contracts/validate_sample.py` (schema + all ten invariant groups) before it
  is projected, so a divergence is a divergence about the *specification* and
  never about garbage. A generated document that does not validate fails the
  run - the generator is held to the same standard as the analyzer.
* **One comparison.** Both sides are reduced by the `digest_of` in
  `gen_scope_fixtures.py` (Python) and its twin in
  `webview/test/scope_fuzz.test.mjs` (JavaScript), so this checks exactly what
  the parity gate checks: id lists in order, `issue.nodeIds` rotation,
  `viewRole`, the eight stage rows, `stats` and the whole `view`.

Every counterexample is **promoted** with `--promote`: it is minimized by delta
debugging (each pass proposes random subsets *and* every one-element deletion,
and one node process answers them all, so the shrink is geometric), then
appended to
`contracts/scope.cases.json`'s `fuzzCases` with its own graph, so the battery
grows and `webview/test/scope_fuzz.test.mjs` replays it forever after with no
Python in the loop.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(REPO, "analyzer", "src")
CONTRACTS = os.path.join(REPO, "contracts")
for _path in (HERE, SRC, CONTRACTS):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from gen_scope_fixtures import (CASES, outcome_of, render,  # noqa: E402
                                _read, _write)
import gen_scope_fixtures                                       # noqa: E402
from scope_gen import (make_graph, normalize, selectors_for,  # noqa: E402
                       validate)
from validate_sample import validate_graph                    # noqa: E402

HARNESS = "test/scope_fuzz.test.mjs"


# ------------------------------------------------------------------ harness
def _webview(repo_root: str) -> str:
    return os.path.join(repo_root, "webview")


def run_harness(repo_root: str, batch: Dict[str, Any], bundle: Optional[str],
                env: Optional[Dict[str, str]] = None
                ) -> Tuple[int, str, Dict[str, Any]]:
    """One node process for a whole batch. Returns (rc, output, report)."""
    tmp = tempfile.mkdtemp(prefix="mlview-fuzz-")
    batch_path = os.path.join(tmp, "batch.json")
    report_path = os.path.join(tmp, "report.json")
    with io.open(batch_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(batch, fh, separators=(",", ":"))
    run_env = dict(os.environ if env is None else env)
    run_env["MLVIEW_FUZZ_BATCH"] = batch_path
    run_env["MLVIEW_FUZZ_REPORT"] = report_path
    if bundle:
        run_env["MLVIEW_FUZZ_BUNDLE"] = bundle
    proc = subprocess.run(["node", "--test", HARNESS], cwd=_webview(repo_root),
                          env=run_env, capture_output=True, shell=False)
    text = (proc.stdout + proc.stderr).decode("utf-8", "replace")
    report: Dict[str, Any] = {}
    if os.path.exists(report_path):
        with io.open(report_path, encoding="utf-8") as fh:
            report = json.load(fh)
    return proc.returncode, text, report


def build_batch(seed: int, graphs: int, per_graph: int,
                on_invalid: Callable[[str, List[str]], None]) -> Dict[str, Any]:
    """`graphs` seeded documents, `per_graph` selectors each, with the Python
    answer already computed. Every document is validated first."""
    rng = random.Random(seed)
    out: List[Dict[str, Any]] = []
    for index in range(graphs):
        graph_seed = seed * 1000 + index
        graph = make_graph(graph_seed)
        errors = validate(graph)
        if errors:
            on_invalid("g%04d" % index, errors)
            continue
        cases = []
        for case_index, (spec, depth) in enumerate(
                selectors_for(graph, rng, per_graph)):
            cases.append({"name": "g%04d/c%02d" % (index, case_index),
                          "spec": spec, "depth": depth,
                          "expect": outcome_of(graph, spec, depth)})
        out.append({"name": "g%04d" % index, "seed": graph_seed,
                    "nodes": len(graph["nodes"]), "graph": graph,
                    "cases": cases})
    return {"version": 1, "seed": seed, "graphs": out}


# --------------------------------------------------------------- minimizing
def _drop_nodes(graph: Dict[str, Any], doomed) -> Dict[str, Any]:
    """Delete `doomed` and re-point every orphan at its nearest surviving
    ancestor, so the containment forest and the level ranking both survive."""
    reduced = json.loads(json.dumps(graph))
    by_id = {n["id"]: n for n in reduced["nodes"]}
    reduced["nodes"] = [n for n in reduced["nodes"] if n["id"] not in doomed]
    for node in reduced["nodes"]:
        parent = node.get("parent")
        while parent is not None and parent in doomed:
            parent = by_id[parent].get("parent")
        node["parent"] = parent
    return normalize(reduced)


def _candidates(graph: Dict[str, Any], rng: random.Random
                ) -> List[Tuple[str, Dict[str, Any]]]:
    """One pass of proposals: aggressive random subsets FIRST, then single
    deletions.

    A generated counterexample can be 500 nodes and its minimal form is a
    handful, so one-element deletions alone would need hundreds of passes. Each
    pass therefore also proposes keeping a random half (and 70%, and 85%) of the
    nodes, which is what makes the shrink geometric; the single deletions polish
    what the subsets cannot reach.
    """
    nodes, edges, issues = graph["nodes"], graph["edges"], graph["issues"]
    out: List[Tuple[str, Dict[str, Any]]] = []
    if len(nodes) > 6:
        for index, ratio in enumerate((0.4, 0.5, 0.5, 0.5, 0.6, 0.7, 0.7, 0.85,
                                       0.85, 0.9)):
            keep = set(n["id"] for n in
                       rng.sample(nodes, max(2, int(len(nodes) * ratio))))
            doomed = {n["id"] for n in nodes if n["id"] not in keep}
            if doomed:
                out.append(("subset%d" % index, _drop_nodes(graph, doomed)))
    for node in (nodes if len(nodes) <= 24 else rng.sample(nodes, 24)):
        out.append(("node " + node["id"], _drop_nodes(graph, {node["id"]})))
    for edge in (edges if len(edges) <= 24 else rng.sample(edges, 24)):
        reduced = json.loads(json.dumps(graph))
        reduced["edges"] = [e for e in reduced["edges"] if e["id"] != edge["id"]]
        out.append(("edge " + edge["id"], normalize(reduced)))
    for issue in (issues if len(issues) <= 24 else rng.sample(issues, 24)):
        reduced = json.loads(json.dumps(graph))
        reduced["issues"] = [i for i in reduced["issues"] if i["id"] != issue["id"]]
        out.append(("issue " + issue["id"], normalize(reduced)))
    return out


def _size(graph: Dict[str, Any]) -> Tuple[int, int, int]:
    return (len(graph["nodes"]), len(graph["edges"]), len(graph["issues"]))


def minimize(repo_root: str, graph: Dict[str, Any], spec: str,
             depth: Optional[int], bundle: Optional[str], log,
             max_passes: int = 40, budget: int = 300) -> Dict[str, Any]:
    """Delta-debug the counterexample: each pass proposes many reductions at
    once and ONE node process answers them all, so a 500-node graph becomes a
    handful of nodes in a couple of dozen node invocations rather than hundreds.

    Probes are checked against the ten invariant groups but not against the
    schema: every element they keep was already schema-valid and a deletion
    cannot make a kept element's *shape* wrong. The winner is fully validated
    before it is promoted.
    """
    rng = random.Random(0xC0FFEE)
    deadline = time.time() + budget
    for _ in range(max_passes):
        if time.time() > deadline:
            log("    minimization budget spent")
            break
        probes = []
        for label, reduced in _candidates(graph, rng):
            if validate_graph(reduced, run_schema=False):
                continue
            probes.append({"name": label, "graph": reduced,
                           "cases": [{"name": label, "spec": spec, "depth": depth,
                                      "expect": outcome_of(reduced, spec, depth)}]})
        if not probes:
            break
        _, _, report = run_harness(repo_root, {"version": 1, "graphs": probes},
                                   bundle)
        failing = {f["graph"] for f in report.get("failures") or []}
        winners = [p for p in probes if p["name"] in failing]
        if not winners:
            break
        graph = min(winners, key=lambda p: _size(p["graph"]))["graph"]
        log("    reduced to %d nodes / %d edges / %d issues" % _size(graph))
    errors = validate(graph)
    if errors:                                   # never promote an invalid graph
        raise SystemExit("minimized counterexample does not validate: %s"
                         % errors[0])
    return graph


def _detail_for(repo_root: str, graph: Dict[str, Any], spec: str,
                depth: Optional[int], bundle: Optional[str]) -> str:
    """The divergence, re-measured on one document. Used for a promoted note."""
    probe = {"name": "min", "graph": graph,
             "cases": [{"name": "min", "spec": spec, "depth": depth,
                        "expect": outcome_of(graph, spec, depth)}]}
    _, _, report = run_harness(repo_root, {"version": 1, "graphs": [probe]},
                               bundle)
    failures = report.get("failures") or []
    return (failures[0].get("detail", "") if failures else
            "no longer diverges on the minimized document")[:200]


def promote(entries: List[Dict[str, Any]]) -> int:
    """Append counterexamples to `contracts/scope.cases.json` and regenerate."""
    payload = json.loads(_read(CASES))
    existing = payload.get("fuzzCases") or []
    known = {c["name"] for c in existing}
    added = [e for e in entries if e["name"] not in known]
    payload["fuzzCases"] = existing + added
    _write(CASES, render(payload))
    gen_scope_fixtures.main([])
    return len(added)


# -------------------------------------------------------------------- driver
def fuzz(repo_root: str, cases: int, seed: int, per_graph: int,
         bundle: Optional[str], do_promote: bool, log,
         env: Optional[Dict[str, str]] = None,
         max_promote: int = 3) -> Tuple[int, str]:
    """Returns (failures, one-line summary)."""
    graphs = max(1, (cases + per_graph - 1) // per_graph)
    invalid: List[str] = []
    started = time.time()
    batch = build_batch(seed, graphs, per_graph,
                        lambda name, errs: invalid.append("%s: %s" % (name, errs[0])))
    generated = time.time() - started
    if invalid:
        for line in invalid[:3]:
            log("  GENERATOR BUG: produced a document that does not validate: %s"
                % line)
        return len(invalid), ("the generator produced %d document(s) that do not "
                              "validate" % len(invalid))
    total = sum(len(g["cases"]) for g in batch["graphs"])
    sizes = sorted(g["nodes"] for g in batch["graphs"])
    log("  %d graphs (%d..%d nodes) x %d selectors = %d cases, generated in %.1fs"
        % (len(batch["graphs"]), sizes[0], sizes[-1], per_graph, total, generated))

    rc, text, report = run_harness(repo_root, batch, bundle, env)
    failures = report.get("failures") or []
    if not report:
        tail = "\n".join(text.strip().splitlines()[-6:])
        return 1, "the harness produced no report (rc=%d):\n%s" % (rc, tail)
    elapsed = time.time() - started
    if not failures:
        return 0, ("%d cases over %d generated graphs (%d..%d nodes), python == "
                   "typescript, %.1fs" % (total, len(batch["graphs"]), sizes[0],
                                          sizes[-1], elapsed))

    log("  %d of %d cases DIVERGE (%.1fs)" % (len(failures), total, elapsed))
    graph_by_name = {g["name"]: g for g in batch["graphs"]}
    entries: List[Dict[str, Any]] = []
    for failure in failures[:max(1, max_promote)]:
        log("    %s  %s depth=%s" % (failure["case"], failure["spec"],
                                     failure["depth"]))
        log("      %s" % failure.get("detail", ""))
        if not do_promote:
            continue
        source = graph_by_name[failure["graph"]]
        small = minimize(repo_root, source["graph"], failure["spec"],
                         failure["depth"], bundle, log)
        entries.append({
            "name": "fuzz_%d_%s" % (seed, failure["case"].replace("/", "_")),
            "kind": "fuzz", "spec": failure["spec"], "depth": failure["depth"],
            # The note is re-measured on the MINIMIZED document: the detail from
            # the original names an array index that no longer exists.
            "note": _detail_for(repo_root, small, failure["spec"],
                                failure["depth"], bundle),
            "discoveredBy": ("analyzer/tools/scope_fuzz.py --seed %d (graph seed "
                             "%d)%s, minimized to %d nodes / %d edges / %d issues"
                             % (seed, source["seed"],
                                " against an alternative bundle" if bundle
                                else "", len(small["nodes"]),
                                len(small["edges"]), len(small["issues"]))),
            "graph": small,
        })
    if entries:
        added = promote(entries)
        log("  promoted %d counterexample(s) into contracts/scope.cases.json"
            % added)
    return len(failures), ("%d of %d cases diverge: %s %s depth=%s"
                           % (len(failures), total, failures[0]["graph"],
                              failures[0]["spec"], failures[0]["depth"]))


def _replay_row(repo_root: str, base_env) -> Tuple[str, bool, str]:
    """The promoted counterexamples, replayed through the port with no Python
    in the loop - `webview/test/scope_fuzz.test.mjs` in its no-env mode."""
    promoted = 0
    try:
        with io.open(CASES, encoding="utf-8") as fh:
            promoted = len(json.load(fh).get("fuzzCases") or [])
    except (OSError, ValueError):
        pass
    proc = subprocess.run(["node", "--test", HARNESS], cwd=_webview(repo_root),
                          env=base_env(), capture_output=True, shell=False)
    if proc.returncode != 0:
        text = (proc.stdout + proc.stderr).decode("utf-8", "replace")
        first = next((l.strip() for l in text.splitlines()
                      if l.strip().startswith(("not ok", "\u2716"))), "")
        return ("scopes: promoted", False,
                "a promoted counterexample no longer projects identically%s"
                % ((": %s" % first) if first else ""))
    if not promoted:
        return ("scopes: promoted", True,
                "no counterexamples promoted yet (contracts/scope.cases.json "
                "fuzzCases is empty)")
    return ("scopes: promoted", True,
            "%d promoted counterexample(s) replay, python == typescript" % promoted)


def check_fuzz(repo_root: str, cli_env, base_env, cases: int, seed: int = 0
               ) -> List[Tuple[str, bool, str]]:
    """The two `tools/verify.py --scopes --fuzz N` rows (HEALTH-02, 11.30):
    the growing battery of promoted counterexamples, then N fresh graphs."""
    harness = os.path.join(_webview(repo_root), HARNESS.replace("/", os.sep))
    if not os.path.isfile(harness):
        return [("scopes: fuzz", False,
                 "webview/%s is missing - the differential fuzzer has no harness"
                 % HARNESS)]
    results = [_replay_row(repo_root, base_env)]
    lines: List[str] = []
    #: The seed travels in the environment so `verify.py` gains exactly ONE new
    #: option (`--fuzz N`); the nightly workflow sets it to replay a failure.
    seed = seed or int(os.environ.get("MLVIEW_FUZZ_SEED") or 0) or \
        int(time.time()) % 100000
    lines.append("seed %d (MLVIEW_FUZZ_SEED replays it)" % seed)
    failures, summary = fuzz(repo_root, cases, seed, _PER_GRAPH, None, False,
                             lines.append, env=base_env())
    if failures:
        results.append(("scopes: fuzz", False,
                        summary + "".join("\n      " + l for l in lines)))
    else:
        results.append(("scopes: fuzz", True, "%s, %s" % (summary, lines[0])))
    return results


_PER_GRAPH = 5


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", type=int, default=200,
                        help="how many (graph, selector) pairs to check")
    parser.add_argument("--seed", type=int, default=0,
                        help="0 means a clock-derived seed, printed so it can be replayed")
    parser.add_argument("--per-graph", type=int, default=_PER_GRAPH,
                        help="selectors per generated graph")
    parser.add_argument("--bundle", default=None,
                        help="an alternative webview bundle (for proving the fuzzer bites)")
    parser.add_argument("--promote", action="store_true",
                        help="minimize every counterexample into contracts/scope.cases.json")
    parser.add_argument("--max-promote", type=int, default=3,
                        help="how many counterexamples one run may promote")
    args = parser.parse_args(argv)

    seed = args.seed or int(time.time()) % 100000
    def log(line):
        sys.stderr.write(line + "\n")
    log("scope fuzz: seed %d, %d cases%s"
        % (seed, args.cases, ", bundle " + args.bundle if args.bundle else ""))
    failures, summary = fuzz(REPO, args.cases, seed, max(1, args.per_graph),
                             args.bundle, args.promote, log,
                             max_promote=args.max_promote)
    log(("FAIL " if failures else "PASS ") + summary)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
