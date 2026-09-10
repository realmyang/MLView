#!/usr/bin/env python
"""Validate an MLGraph document against the frozen MLView contracts.

Checks, in order:

1. JSON Schema (``contracts/graph.schema.json``) with
   ``jsonschema.Draft202012Validator``.
2. Every invariant from ``docs/CONTRACTS.md`` section 1.1 (id uniqueness,
   parent forest with strictly decreasing level, edge endpoints resolve,
   ghost nodes carry issues, ``issue.nodeIds[0]`` exists).
3. The ordering rules from section 0: stages by ``order``; nodes by
   ``(stage order, file, line, col)``; edges by ``(source, kind, target)``;
   issues by ``(severity desc, file, line, code)``.
4. Cross-object consistency: node/edge <-> issue back-references, per-stage
   ``nodeCount`` / ``issueCounts`` / ``maxSeverity``, ``stats``, and
   ``confidence`` vs ``confidenceBucket``.
5. Location hygiene: forward-slashed relative ``file`` under
   ``workspace.root``, ``endLine >= line``, and ``loc.symbol`` occurring
   inside ``loc.snippet``.

Usage::

    python contracts/validate_sample.py [GRAPH.json] [--schema SCHEMA.json] [-q]

Exits 0 when the document is valid, 1 otherwise. Importable as a library:
``validate_graph(doc)`` and ``validate_file(path)`` both return a list of
human-readable error strings (empty means valid); neither prints anything.
"""

from __future__ import annotations

import json
import os
import re
import sys

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - dependency is declared in the brief
    Draft202012Validator = None

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_GRAPH = os.path.join(HERE, "graph.sample.json")
DEFAULT_SCHEMA = os.path.join(HERE, "graph.schema.json")

STAGE_IDS = ["config", "data", "preprocess", "model", "objective", "train",
             "eval", "deliver"]
STAGE_ORDER = {sid: i for i, sid in enumerate(STAGE_IDS)}
LEVEL_RANK = {"stage": 0, "unit": 1, "op": 2}
SEV_RANK = {"low": 0, "medium": 1, "high": 2}
SEV_DESC = ["high", "medium", "low"]
BUCKETS = [(0.9, "certain"), (0.7, "likely"), (0.5, "possible"), (0.0, "speculative")]
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")

#: When true, a single-line Loc whose snippet contains its symbol exactly once
#: must also have ``col`` pointing at that symbol. The golden sample satisfies
#: this; set it to False if an emitter deliberately anchors ``col`` at the
#: enclosing statement instead of at the symbol.
STRICT_SYMBOL_COL = True


def bucket_for(confidence):
    """The ConfidenceBucket a confidence value must carry."""
    for floor, name in BUCKETS:
        if confidence >= floor:
            return name
    return "speculative"


# --------------------------------------------------------------------------
# schema
# --------------------------------------------------------------------------

def schema_errors(doc, schema_path=DEFAULT_SCHEMA):
    """Draft 2020-12 schema errors, as readable strings."""
    if Draft202012Validator is None:
        return ["jsonschema is not installed; cannot run schema validation"]
    with open(schema_path, encoding="utf-8") as fh:
        schema = json.load(fh)
    validator = Draft202012Validator(schema)
    out = []
    for err in sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in err.absolute_path) or "<root>"
        out.append("schema: %s: %s" % (where, err.message))
    return out


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _iter_locs(doc):
    """Yield (label, loc-dict) for every Loc / RelatedLoc in the document."""
    for n in doc.get("nodes", []):
        if isinstance(n.get("loc"), dict):
            yield ("node %s loc" % n.get("id"), n["loc"])
        if isinstance(n.get("defLoc"), dict):
            yield ("node %s defLoc" % n.get("id"), n["defLoc"])
    for e in doc.get("edges", []):
        if isinstance(e.get("loc"), dict):
            yield ("edge %s loc" % e.get("id"), e["loc"])
    for i in doc.get("issues", []):
        if isinstance(i.get("loc"), dict):
            yield ("issue %s loc" % i.get("id"), i["loc"])
        for k, rl in enumerate(i.get("relatedLocs", []) or []):
            if isinstance(rl, dict):
                yield ("issue %s relatedLocs[%d]" % (i.get("id"), k), rl)


def _dups(values):
    seen, dup = set(), []
    for v in values:
        if v in seen and v not in dup:
            dup.append(v)
        seen.add(v)
    return dup


def _sorted_report(kind, keys, ids):
    """Report the first place a key sequence stops being non-decreasing."""
    errs = []
    for i in range(1, len(keys)):
        if keys[i - 1] > keys[i]:
            errs.append("ordering: %s are not sorted: %s (key %r) precedes %s (key %r)"
                        % (kind, ids[i - 1], keys[i - 1], ids[i], keys[i]))
            break
    return errs


# --------------------------------------------------------------------------
# invariant groups
# --------------------------------------------------------------------------

def _check_ids(doc):
    errs = []
    nodes, edges, issues = doc["nodes"], doc["edges"], doc["issues"]
    for kind, items in (("node", nodes), ("edge", edges), ("issue", issues)):
        dup = _dups([x["id"] for x in items])
        if dup:
            errs.append("ids: duplicate %s ids: %s" % (kind, ", ".join(dup)))
    everything = [x["id"] for x in nodes] + [x["id"] for x in edges] + \
                 [x["id"] for x in issues]
    dup = _dups(everything)
    if dup:
        errs.append("ids: ids are not globally unique: %s" % ", ".join(dup))
    return errs


def _check_hierarchy(doc):
    errs = []
    nodes = doc["nodes"]
    by_id = {n["id"]: n for n in nodes}
    for n in nodes:
        parent = n.get("parent")
        if parent is None:
            continue
        if parent == n["id"]:
            errs.append("hierarchy: node %s is its own parent" % n["id"])
            continue
        if parent not in by_id:
            errs.append("hierarchy: node %s has unknown parent %s" % (n["id"], parent))
            continue
        pl, cl = LEVEL_RANK[by_id[parent]["level"]], LEVEL_RANK[n["level"]]
        if pl >= cl:
            errs.append(
                "hierarchy: node %s (level %s) has parent %s of level %s - a parent "
                "must sit at a lower level (stage > unit > op)"
                % (n["id"], n["level"], parent, by_id[parent]["level"]))
    # forest: walking parents must terminate
    for n in nodes:
        seen, cur = {n["id"]}, n.get("parent")
        while cur is not None and cur in by_id:
            if cur in seen:
                errs.append("hierarchy: parent cycle through node %s" % cur)
                break
            seen.add(cur)
            cur = by_id[cur].get("parent")
    return errs


def _check_edges(doc):
    errs = []
    ids = {n["id"] for n in doc["nodes"]}
    # PERF-04 (CONTRACTS 11.46 C): a document that says it rolled anything up
    # has had EVERY edge re-pointed and de-duplicated, so it may not carry two
    # edges with one (source, kind, target). An untouched document may - two
    # data edges differing only in `label` are ordinary and legal.
    rolled = (any("rolledUp" in n for n in doc["nodes"])
              or any("weight" in e for e in doc["edges"]))
    pairs = {}
    for e in doc["edges"]:
        for end in ("source", "target"):
            if e[end] not in ids:
                errs.append("edges: edge %s %s %s is not a node in nodes[]"
                            % (e["id"], end, e[end]))
        if e["kind"] != "control" and "subkind" in e:
            errs.append("edges: edge %s has subkind %r but kind %r (subkind is only "
                        "meaningful for control edges)" % (e["id"], e["subkind"], e["kind"]))
        if e["source"] == e["target"]:
            errs.append("edges: edge %s is a self-loop on %s; a rollup absorbs an "
                        "edge whose endpoints land on one survivor, it never emits "
                        "one" % (e["id"], e["source"]))
        weight = e.get("weight")
        if weight is not None:
            if isinstance(weight, bool) or not isinstance(weight, int) or weight < 2:
                errs.append("edges: edge %s has weight %r; it must be an integer >= 2 "
                            "(absent means one)" % (e["id"], weight))
        if rolled:
            key = (e["source"], e["kind"], e["target"])
            if key in pairs:
                errs.append("edges: a rolled-up document carries parallel edges %s "
                            "and %s on %s; parallels merge into one carrying a "
                            "weight" % (pairs[key], e["id"], key))
            pairs[key] = e["id"]
    return errs


def _check_issue_links(doc):
    errs = []
    nodes = {n["id"]: n for n in doc["nodes"]}
    edges = {e["id"]: e for e in doc["edges"]}
    issues = {i["id"]: i for i in doc["issues"]}

    for i in doc["issues"]:
        if not i["nodeIds"]:
            errs.append("issues: issue %s (%s) has no nodeIds; nodeIds[0] is the "
                        "primary node" % (i["id"], i["code"]))
        for nid in i["nodeIds"]:
            if nid not in nodes:
                errs.append("issues: issue %s references unknown node %s" % (i["id"], nid))
        for eid in i["edgeIds"]:
            if eid not in edges:
                errs.append("issues: issue %s references unknown edge %s" % (i["id"], eid))
        if _dups(i["nodeIds"]):
            errs.append("issues: issue %s repeats a node id" % i["id"])
        if _dups(i["edgeIds"]):
            errs.append("issues: issue %s repeats an edge id" % i["id"])

    for n in doc["nodes"]:
        for iid in n["issueIds"]:
            if iid not in issues:
                errs.append("issues: node %s references unknown issue %s" % (n["id"], iid))
            elif n["id"] not in issues[iid]["nodeIds"]:
                errs.append("issues: node %s lists issue %s but that issue does not "
                            "list the node" % (n["id"], iid))
        if _dups(n["issueIds"]):
            errs.append("issues: node %s repeats an issue id" % n["id"])
        if n["ghost"] and not n["issueIds"]:
            errs.append("issues: ghost node %s has no issueIds (invariant 1.1.8)" % n["id"])
    for i in doc["issues"]:
        for nid in i["nodeIds"]:
            if nid in nodes and i["id"] not in nodes[nid]["issueIds"]:
                errs.append("issues: issue %s lists node %s but that node does not "
                            "list the issue" % (i["id"], nid))
        for eid in i["edgeIds"]:
            if eid in edges and i["id"] not in edges[eid]["issueIds"]:
                errs.append("issues: issue %s lists edge %s but that edge does not "
                            "list the issue" % (i["id"], eid))
    for e in doc["edges"]:
        for iid in e["issueIds"]:
            if iid not in issues:
                errs.append("issues: edge %s references unknown issue %s" % (e["id"], iid))
            elif e["id"] not in issues[iid]["edgeIds"]:
                errs.append("issues: edge %s lists issue %s but that issue does not "
                            "list the edge" % (e["id"], iid))
    return errs


def _check_ordering(doc):
    errs = []
    stages = doc["stages"]
    seen = [s["id"] for s in stages]
    if seen != STAGE_IDS:
        errs.append("ordering: stages must be exactly %s in that order, got %s"
                    % (STAGE_IDS, seen))
    for s in stages:
        if s["order"] != STAGE_ORDER.get(s["id"], -1):
            errs.append("ordering: stage %s has order %d, expected %d"
                        % (s["id"], s["order"], STAGE_ORDER.get(s["id"], -1)))

    nodes = doc["nodes"]
    keys = [(STAGE_ORDER.get(n["stage"], 99), n["loc"]["file"], n["loc"]["line"],
             n["loc"]["col"]) for n in nodes]
    errs += _sorted_report("nodes", keys, [n["id"] for n in nodes])

    edges = doc["edges"]
    keys = [(e["source"], e["kind"], e["target"]) for e in edges]
    errs += _sorted_report("edges", keys, [e["id"] for e in edges])

    issues = doc["issues"]
    keys = [(-SEV_RANK[i["severity"]], i["loc"]["file"], i["loc"]["line"], i["code"])
            for i in issues]
    errs += _sorted_report("issues", keys, [i["id"] for i in issues])
    return errs


def _check_stage_aggregates(doc):
    errs = []
    for s in doc["stages"]:
        sid = s["id"]
        nodes = [n for n in doc["nodes"] if n["stage"] == sid]
        counts = {"low": 0, "medium": 0, "high": 0}
        for i in doc["issues"]:
            if i["stage"] == sid and not i["suppressed"]:
                counts[i["severity"]] += 1
        if s["nodeCount"] != len(nodes):
            errs.append("stages: stage %s nodeCount=%d but %d nodes carry that stage"
                        % (sid, s["nodeCount"], len(nodes)))
        if s["issueCounts"] != counts:
            errs.append("stages: stage %s issueCounts=%s but the issues give %s"
                        % (sid, s["issueCounts"], counts))
        worst = next((sev for sev in SEV_DESC if counts[sev]), None)
        if s["maxSeverity"] != worst:
            errs.append("stages: stage %s maxSeverity=%r, expected %r"
                        % (sid, s["maxSeverity"], worst))
        if nodes and not s["present"]:
            errs.append("stages: stage %s holds %d nodes but present is false"
                        % (sid, len(nodes)))
        if not s["present"]:
            if s["nodeCount"] or any(counts.values()) or s["maxSeverity"] is not None:
                errs.append("stages: absent stage %s must have nodeCount 0, zero "
                            "issueCounts and maxSeverity null" % sid)
        elif (not nodes and not any(counts.values()) and doc.get("view") is None
                and not doc["stats"].get("truncated")):
            # A PROJECTION (CONTRACTS 11.4 F1) carries `stage.present` through
            # from the whole-workspace document verbatim - it is project-level
            # truth - so a present stage with nothing left in this scope is
            # correct, not a contract violation.
            #
            # VIEW-R1: a ROLLED-UP document is the same situation one cause
            # over. `--max-nodes` folds a stage's nodes onto a summary node
            # whose stage is a majority vote, so the stage can end the fold with
            # nothing carrying its id - and `present` must still say the stage
            # was there, or every emitter reading it turns a fold into a stated
            # absence about the user's code.
            errs.append("stages: stage %s is present but has neither nodes nor issues"
                        % sid)
    return errs


def _check_stats(doc):
    errs = []
    stats = doc["stats"]
    if stats["nodes"] != len(doc["nodes"]):
        errs.append("stats: nodes=%d but nodes[] has %d entries"
                    % (stats["nodes"], len(doc["nodes"])))
    if stats["edges"] != len(doc["edges"]):
        errs.append("stats: edges=%d but edges[] has %d entries"
                    % (stats["edges"], len(doc["edges"])))
    totals = {"low": 0, "medium": 0, "high": 0}
    suppressed = 0
    for i in doc["issues"]:
        if i["suppressed"]:
            suppressed += 1
        else:
            totals[i["severity"]] += 1
    if stats["issues"] != totals:
        errs.append("stats: issues=%s but issues[] gives %s" % (stats["issues"], totals))
    if "suppressed" in stats and stats["suppressed"] != suppressed:
        errs.append("stats: suppressed=%d but %d issues are marked suppressed"
                    % (stats["suppressed"], suppressed))
    errs += _check_rollup(doc, stats)
    errs += _check_pipelines(doc)
    return errs


def _check_rollup(doc, stats):
    """PERF-04 (CONTRACTS 11.46 C). Part of the `stats` group on purpose: it is
    an aggregate claim about the whole document, and folding it in here keeps
    the count of invariant groups at the ten five documents quote."""
    errs = []
    for n in doc["nodes"]:
        rolled = n.get("rolledUp")
        if rolled is None:
            continue
        if isinstance(rolled, bool) or not isinstance(rolled, int) or rolled < 1:
            errs.append("stats: node %s has rolledUp %r; it must be an integer >= 1 "
                        "(absent means zero)" % (n["id"], rolled))
    if not stats.get("truncated"):
        claimed = [n["id"] for n in doc["nodes"] if "rolledUp" in n]
        weighted = [e["id"] for e in doc["edges"] if "weight" in e]
        if claimed:
            errs.append("stats: truncated is false but %d node(s) claim rolledUp "
                        "(first: %s); a full-fidelity document may not claim to "
                        "have summarised anything" % (len(claimed), claimed[0]))
        if weighted:
            errs.append("stats: truncated is false but %d edge(s) carry a weight "
                        "(first: %s)" % (len(weighted), weighted[0]))
    return errs


def _check_pipelines(doc):
    """MLV-P12 (CONTRACTS 11.47 D). Absent is the normal case and is silent."""
    errs = []
    rows = doc.get("pipelines")
    if rows is None:
        return errs
    entrypoints = list(doc["workspace"]["entrypoints"])
    if len(rows) < 2:
        errs.append("pipelines: the block carries %d row(s); it is emitted only "
                    "for two or more non-empty pipelines" % len(rows))
    seen = set()
    for row in rows:
        name = row["entrypoint"]
        if name not in entrypoints:
            errs.append("pipelines: %r is not one of workspace.entrypoints" % name)
        if name in seen:
            errs.append("pipelines: entrypoint %r has two rows" % name)
        seen.add(name)
        if row["exclusiveCount"] + row["sharedCount"] != row["nodeCount"]:
            errs.append("pipelines: %s has nodeCount %d but %d exclusive + %d "
                        "shared" % (name, row["nodeCount"], row["exclusiveCount"],
                                    row["sharedCount"]))
        if row["nodeCount"] < 1:
            errs.append("pipelines: %s has no nodes; an empty pipeline is not a "
                        "row" % name)
    return errs


def _check_confidence(doc):
    errs = []
    for kind, items in (("node", doc["nodes"]), ("issue", doc["issues"])):
        for x in items:
            want = bucket_for(x["confidence"])
            if x["confidenceBucket"] != want:
                errs.append("confidence: %s %s has confidence %s but bucket %r "
                            "(expected %r)" % (kind, x["id"], x["confidence"],
                                               x["confidenceBucket"], want))
    for e in doc["edges"]:
        if not 0.0 <= e["confidence"] <= 1.0:
            errs.append("confidence: edge %s confidence out of range" % e["id"])
    return errs


def _check_locs(doc):
    errs = []
    root = doc["workspace"]["root"]
    if "\\" in root:
        errs.append("workspace: root %r must use forward slashes" % root)
    if root.endswith("/"):
        errs.append("workspace: root %r must not end with a slash" % root)
    for entry in doc["workspace"]["entrypoints"]:
        if "\\" in entry or entry.startswith("/") or re.match(r"^[A-Za-z]:", entry):
            errs.append("workspace: entrypoint %r must be workspace-relative with "
                        "forward slashes" % entry)

    for label, loc in _iter_locs(doc):
        f, abs_f = loc["file"], loc["absFile"]
        if "\\" in f or "\\" in abs_f:
            errs.append("locs: %s uses backslashes (%r / %r)" % (label, f, abs_f))
        if f.startswith("/") or re.match(r"^[A-Za-z]:", f):
            errs.append("locs: %s file %r must be workspace-relative" % (label, f))
        if abs_f != root + "/" + f:
            errs.append("locs: %s absFile %r is not root + '/' + file (%r)"
                        % (label, abs_f, root + "/" + f))
        if loc["endLine"] < loc["line"]:
            errs.append("locs: %s endLine %d < line %d"
                        % (label, loc["endLine"], loc["line"]))
        if loc["endLine"] == loc["line"] and loc["endCol"] < loc["col"]:
            errs.append("locs: %s endCol %d < col %d on a single-line span"
                        % (label, loc["endCol"], loc["col"]))
        sym, snip = loc.get("symbol"), loc.get("snippet")
        if sym is not None and snip is not None and sym not in snip:
            errs.append("locs: %s symbol %r does not occur in snippet %r"
                        % (label, sym, snip))
        if (STRICT_SYMBOL_COL and sym is not None and snip is not None
                and loc["endLine"] == loc["line"]):
            found = snip.find(sym)
            if found >= 0 and found != loc["col"] and snip.count(sym) == 1:
                errs.append("locs: %s col %d does not point at symbol %r "
                            "(it starts at column %d of the snippet)"
                            % (label, loc["col"], sym, found))
    return errs


def _check_generator(doc):
    errs = []
    gen = doc["generator"]
    if not ISO_RE.match(gen["generatedAt"]):
        errs.append("generator: generatedAt %r is not an ISO-8601 UTC timestamp"
                    % gen["generatedAt"])
    return errs


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------

CHECKS = [
    ("ids", _check_ids),
    ("hierarchy", _check_hierarchy),
    ("edges", _check_edges),
    ("issue links", _check_issue_links),
    ("ordering", _check_ordering),
    ("stage aggregates", _check_stage_aggregates),
    ("stats", _check_stats),
    ("confidence", _check_confidence),
    ("locations", _check_locs),
    ("generator", _check_generator),
]


def validate_graph(doc, schema_path=DEFAULT_SCHEMA, run_schema=True):
    """Return a list of error strings for `doc` (empty list means valid)."""
    errs = []
    if run_schema:
        errs += schema_errors(doc, schema_path)
        if errs:
            # The invariant checks assume a schema-valid shape.
            return errs
    for _, fn in CHECKS:
        try:
            errs += fn(doc)
        except Exception as exc:  # defensive: never crash on a malformed doc
            errs.append("internal: check %r raised %s: %s"
                        % (fn.__name__, type(exc).__name__, exc))
    return errs


def validate_file(path=DEFAULT_GRAPH, schema_path=DEFAULT_SCHEMA, run_schema=True):
    """Load `path` and validate it. Returns a list of error strings."""
    try:
        with open(path, encoding="utf-8-sig") as fh:
            doc = json.load(fh)
    except OSError as exc:
        return ["io: cannot read %s: %s" % (path, exc)]
    except ValueError as exc:
        return ["json: %s is not valid JSON: %s" % (path, exc)]
    return validate_graph(doc, schema_path, run_schema)


def _usage():
    return ("usage: python contracts/validate_sample.py [GRAPH.json] "
            "[--schema SCHEMA.json] [-q|--quiet]")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    graph_path, schema_path, quiet = None, DEFAULT_SCHEMA, False
    while argv:
        arg = argv.pop(0)
        if arg in ("-h", "--help"):
            sys.stdout.write(_usage() + "\n")
            return 0
        if arg in ("-q", "--quiet"):
            quiet = True
        elif arg == "--schema":
            if not argv:
                sys.stderr.write("error: --schema needs a path\n" + _usage() + "\n")
                return 1
            schema_path = argv.pop(0)
        elif arg.startswith("--schema="):
            schema_path = arg.split("=", 1)[1]
        elif arg.startswith("-"):
            sys.stderr.write("error: unknown option %s\n%s\n" % (arg, _usage()))
            return 1
        elif graph_path is None:
            graph_path = arg
        else:
            sys.stderr.write("error: at most one graph path\n%s\n" % _usage())
            return 1
    graph_path = graph_path or DEFAULT_GRAPH

    errors = validate_file(graph_path, schema_path)
    name = os.path.normpath(graph_path)
    if errors:
        sys.stderr.write("FAIL %s - %d problem(s):\n" % (name, len(errors)))
        for err in errors:
            sys.stderr.write("  - %s\n" % err)
        return 1
    if not quiet:
        try:
            with open(graph_path, encoding="utf-8-sig") as fh:
                doc = json.load(fh)
            counts = doc["stats"]["issues"]
            sys.stdout.write(
                "OK %s - schema %s + %d invariant groups passed "
                "(%d nodes, %d edges, %d issues: %d high / %d medium / %d low, "
                "%d/8 stages present)\n"
                % (name, doc["schemaVersion"], len(CHECKS), len(doc["nodes"]),
                   len(doc["edges"]), len(doc["issues"]), counts["high"],
                   counts["medium"], counts["low"],
                   sum(1 for s in doc["stages"] if s["present"])))
        except Exception:  # pragma: no cover - already validated above
            sys.stdout.write("OK %s\n" % name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
