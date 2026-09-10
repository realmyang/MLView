"""Regenerate the scope parity fixtures from the Python `project()`.

    PYTHONUTF8=1 python analyzer/tools/gen_scope_fixtures.py [--check]

Writes two files, both computed over the **frozen** `contracts/graph.sample.json`
so the gate can never churn when a rule changes (CONTRACTS 11.15, FEATURES 7):

* ``contracts/scope.cases.json``    - the inputs: thirteen projecting cases plus
  one case per error code. Hand-readable, and the only file a port needs to iterate.
* ``contracts/scope.expected.json`` - the outputs: the full projected document
  for every projecting case, and ``{code, term, candidates}`` for every error
  case.

``--check`` regenerates in memory and byte-diffs against the files on disk,
exiting 1 on drift; it writes nothing. `tools/verify.py --scopes` runs it.

Consumers deep-compare: the `nodes` / `edges` / `issues` id lists **in order**,
every `issue.nodeIds` (so the stable rotation is checked), every node's
`viewRole`, all eight `stage.nodeCount` / `issueCounts` / `maxSeverity`,
`stats`, and the whole `view` object. `diagnostics` prose is deliberately NOT
contractual - only the codes, terms and candidate lists of errors are.

HEALTH-02 adds a **second, growing** array to both files: ``fuzzCases``. A case
there is a counterexample the differential fuzzer
(``analyzer/tools/scope_fuzz.py``) found - one selector on **its own** generated
graph, carried inline because it is not the frozen golden. The inputs are data
the fuzzer promoted and this file carries through verbatim; only the
expectations are generated, and as a ``digest`` (the comparable subset listed
above) rather than a whole document, so a 300-node counterexample costs
kilobytes rather than megabytes. ``webview/test/scope_fuzz.test.mjs`` replays
them through the TypeScript port. ``cases`` is untouched, so the frozen battery,
``scope_parity.test.mjs`` and the gate's "10 projections + 6 error cases" row
all keep their exact shape (CONTRACTS 11.30).
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(REPO, "analyzer", "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from mlview.core.project import ScopeError, parse_scope, project  # noqa: E402

GRAPH = os.path.join(REPO, "contracts", "graph.sample.json")
CASES = os.path.join(REPO, "contracts", "scope.cases.json")
EXPECTED = os.path.join(REPO, "contracts", "scope.expected.json")
GRAPH_REL = "contracts/graph.sample.json"
GENERATOR = "analyzer/tools/gen_scope_fixtures.py"

#: (name, spec, depth, note). `depth: None` means "the per-kind default".
PROJECTING = [
    ("all", "all", None,
     "identity: the output equals the input and carries no `view`"),
    ("stage_train", "stage:train", 0, "a whole lane, no boundary ring"),
    ("unit_train_train", "unit:train.train", 1,
     "tier-1 qualname hit, descendant closure, one boundary ring"),
    ("unit_batch_loop_d0", "unit:batch_loop", 0,
     "tier-3 bare name; exercises the ancestor closure (context)"),
    ("unit_batch_loop_d2", "unit:batch_loop", 2, "depth monotonicity against d0"),
    ("file_data_py", "file:data.py", 0, "bare basename match"),
    ("concern_evaluation", "concern:evaluation", 0, "a preset over eval + deliver"),
    ("concern_optimization", "concern:optimization", 0,
     "a preset over model + objective + train"),
    ("node_smallnet", "node:n:8d3e0f7a2b61", 1,
     "legacy pinpoint selector; exercises the stable rotation of issue.nodeIds"),
    ("unit_nope", "unit:Nope", None,
     "empty but legal: eight stage rows at nodeCount 0, view.empty true, exit 0"),
    # MLV-P12 (CONTRACTS 11.47). The frozen golden has exactly one entrypoint,
    # `train.py`, so these exercise the relation itself - seeds, the closure
    # over data and call edges plus containment, and the ancestor context - on
    # a graph where nothing is shared and both ports must still agree.
    ("pipeline_train", "pipeline:train.py", None,
     "the whole pipeline of the only entrypoint; nothing is shared"),
    ("pipeline_train_basename", "pipeline:TRAIN.PY", 1,
     "case-folded bare basename, plus one boundary ring"),
    ("pipeline_train_d2", "pipeline:train.py", 2,
     "depth monotonicity against the depth-0 case"),
]

#: One case per error code (`unknown_unit` is never raised - see 11.2 step 9).
ERRORS = [
    ("err_bad_selector", "bogus:x", None, "unknown kind"),
    ("err_unknown_stage", "stage:nope", None, "not one of the eight StageIds"),
    ("err_unknown_concern", "concern:nope", None, "not a preset or an alias"),
    ("err_unknown_node", "node:n:deadbeefdead", None, "no such node in this graph"),
    ("err_unknown_file", "file:nope.py", None, "no loc.file matches"),
    ("err_bad_depth", "stage:train", 3, "depth outside 0..2"),
    ("err_unknown_pipeline", "pipeline:nope.py", None,
     "not one of workspace.entrypoints (CONTRACTS 11.47 B1)"),
]


#: The stage keys a projection is contracted to reproduce (11.2 step 9).
STAGE_KEYS = ("id", "label", "order", "present", "nodeCount", "issueCounts",
              "maxSeverity")


def load_graph(path: str = GRAPH):
    with io.open(path, encoding="utf-8-sig") as fh:
        return json.load(fh)


def digest_of(doc):
    """The comparable subset of a projected document (CONTRACTS 11.30).

    Exactly what `webview/test/scope_parity.test.mjs` deep-compares, in one
    JSON-shaped value so a port can be checked without shipping a whole
    document per case: the node / edge / issue id lists **in order**, every
    `issue.nodeIds` and `edgeIds` (so the stable rotation of step 6 is
    checked), every node's `viewRole` and filtered `issueIds`, each edge's
    filtered `issueIds`, all eight stage rows, `stats`, and the whole `view`.

    `diagnostics` is deliberately absent: 11.2 step 10 appends resolution
    warnings whose *prose* is free, and the two ports word them differently.
    `webview/test/scope_fuzz.test.mjs` builds the identical value in
    JavaScript; the two functions are the only place the shape is written.
    """
    return {
        "nodes": [[n["id"], n.get("viewRole"), list(n.get("issueIds") or [])]
                  for n in doc.get("nodes") or []],
        "edges": [[e["id"], list(e.get("issueIds") or [])]
                  for e in doc.get("edges") or []],
        "issues": [[i["id"], list(i.get("nodeIds") or []),
                    list(i.get("edgeIds") or [])]
                   for i in doc.get("issues") or []],
        "stages": [{k: s.get(k) for k in STAGE_KEYS}
                   for s in doc.get("stages") or []],
        "stats": doc.get("stats"),
        "view": doc.get("view"),
    }


def error_triple(exc: ScopeError):
    """The only contractual part of a rejected selector (11.1)."""
    return {"code": exc.code, "term": exc.term, "candidates": list(exc.candidates)}


def outcome_of(graph, spec, depth):
    """`project()` or the error it raised, as the two ports must both report it."""
    try:
        scope = parse_scope(spec, depth)
    except ScopeError as exc:
        return {"kind": "error", "raisedBy": "parse", "error": error_triple(exc)}
    try:
        return {"kind": "project", "digest": digest_of(project(graph, scope))}
    except ScopeError as exc:
        return {"kind": "error", "raisedBy": "resolve", "error": error_triple(exc)}


def _existing_fuzz_cases():
    """The promoted counterexamples on disk - inputs, never regenerated here."""
    text = _read(CASES)
    if not text:
        return []
    try:
        return json.loads(text).get("fuzzCases") or []
    except ValueError:
        return []


def build_fuzz_expected(fuzz_cases):
    """One expectation per promoted counterexample, over its OWN graph."""
    out = []
    for case in fuzz_cases:
        row = {"name": case["name"], "spec": case["spec"],
               "depth": case.get("depth")}
        row.update(outcome_of(case["graph"], case["spec"], case.get("depth")))
        out.append(row)
    return out


def build_cases():
    """The inputs, exactly as both ports iterate them."""
    cases = [{"name": name, "kind": "project", "spec": spec, "depth": depth,
              "note": note} for name, spec, depth, note in PROJECTING]
    cases += [{"name": name, "kind": "error", "spec": spec, "depth": depth,
               "note": note} for name, spec, depth, note in ERRORS]
    return {
        "$comment": "Scope parity battery (CONTRACTS 11.15). Inputs only; the "
                    "expected outputs live in contracts/scope.expected.json. "
                    "Both are generated by " + GENERATOR + " - do not hand-edit. "
                    "`fuzzCases` (CONTRACTS 11.30) are counterexamples promoted "
                    "by analyzer/tools/scope_fuzz.py, each carrying its OWN "
                    "generated graph; they are inputs and are carried through "
                    "verbatim.",
        "version": 1,
        "graph": GRAPH_REL,
        "generatedBy": GENERATOR,
        "cases": cases,
        "fuzzCases": _existing_fuzz_cases(),
    }


def build_expected(graph):
    """The outputs: a full projected document, or an error triple."""
    out = []
    for name, spec, depth, _note in PROJECTING:
        doc = project(graph, parse_scope(spec, depth))
        out.append({"name": name, "kind": "project", "spec": spec, "depth": depth,
                    "doc": doc})
    for name, spec, depth, _note in ERRORS:
        raised_by = "parse"
        try:
            scope = parse_scope(spec, depth)
        except ScopeError as exc:
            error = exc
        else:
            raised_by = "resolve"
            try:
                project(graph, scope)
            except ScopeError as exc:
                error = exc
            else:
                raise SystemExit("case %s did not raise" % name)
        out.append({"name": name, "kind": "error", "spec": spec, "depth": depth,
                    "raisedBy": raised_by,
                    "error": {"code": error.code, "term": error.term,
                              "candidates": list(error.candidates)}})
    return {
        "$comment": "Expected output of project() for every case in "
                    "contracts/scope.cases.json, generated from the Python "
                    "implementation by " + GENERATOR + ". `diagnostics` prose is "
                    "NOT contractual; ids, order, roles, aggregates, `view` and "
                    "the error triples are.",
        "version": 1,
        "graph": GRAPH_REL,
        "generatedBy": GENERATOR,
        "cases": out,
        "fuzzCases": build_fuzz_expected(_existing_fuzz_cases()),
    }


def render(payload) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _read(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with io.open(path, encoding="utf-8") as fh:
        return fh.read()


def _write(path: str, text: str) -> None:
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if either file on disk is out of date")
    args = parser.parse_args(argv)

    graph = load_graph()
    files = [(CASES, render(build_cases())), (EXPECTED, render(build_expected(graph)))]
    summary = ("%d projecting case(s) + %d error case(s) over %s"
               % (len(PROJECTING), len(ERRORS), GRAPH_REL))
    promoted = len(_existing_fuzz_cases())
    if promoted:
        summary += (" + %d promoted counterexample(s) on their own graphs"
                    % promoted)

    if args.check:
        stale = [path for path, text in files if _read(path) != text]
        if stale:
            sys.stderr.write("scope fixtures are out of date: %s\n"
                             % ", ".join(os.path.basename(p) for p in stale))
            return 1
        sys.stderr.write("scope fixtures are current: %s\n" % summary)
        return 0

    for path, text in files:
        _write(path, text)
        sys.stderr.write("wrote %s (%d bytes)\n"
                         % (path.replace("\\", "/"), len(text.encode("utf-8"))))
    sys.stderr.write("%s\n" % summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
