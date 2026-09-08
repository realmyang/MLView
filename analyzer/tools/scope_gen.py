#!/usr/bin/env python
"""The seeded graph generator behind the scope fuzzer (HEALTH-02, 11.30).

Split out of `scope_fuzz.py` so that file stays a *driver* - build a batch, run
one node process, compare, minimize, promote - and this one is the only place
that knows what a schema-valid MLView document looks like.

Everything here is pure and seeded: `make_graph(seed)` returns the same bytes
for the same seed on any interpreter, which is what makes a fuzz failure
replayable from the seed printed in its log. `normalize()` is the shared tail
of both the generator and the minimizer: it re-derives the two-way issue links,
the ghost invariant (1.1.8), the eight stage rows, `stats` and the three sort
orders, so a *reduced* document is as valid as a generated one.

The shapes it can produce, and why each is here (the fixture battery has none of
them): node counts 5-500; three-level hierarchies with cross-stage parents;
orphan nodes with no parent at all; ghost densities up to a half; issues
anchored on one to four nodes; **issues anchored on an edge whose nodes sit
elsewhere**, the branch that CONTRACTS 11.2 step 6 did not spell out and on
which the two ports actually disagreed; one to three disconnected components;
a name pool small enough that bare names collide across files, so every `unit:`
resolution tier is exercised.
"""

from __future__ import annotations

import io
import json
import os
import random
import sys
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
CONTRACTS = os.path.join(REPO, "contracts")
if CONTRACTS not in sys.path:
    sys.path.insert(0, CONTRACTS)

from validate_sample import (DEFAULT_SCHEMA, LEVEL_RANK, STAGE_IDS,  # noqa: E402
                             STAGE_ORDER, bucket_for, validate_graph)

SEVERITIES = ("low", "medium", "high")
SEV_RANK = {"low": 0, "medium": 1, "high": 2}
FRAMEWORKS = ("torch", "sklearn", "pandas", "numpy", "keras", "tf", "hf",
              "lightning", "xgboost", "other")
NODE_KINDS = {
    "stage": ("entrypoint", "function", "class", "train_loop", "eval_loop"),
    "unit": ("function", "class", "train_loop", "eval_loop", "model"),
    "op": ("config", "dataset", "dataloader", "split", "transform", "augment",
           "layer", "loss", "optimizer", "scheduler", "metric", "checkpoint",
           "predict", "artifact", "external", "unknown"),
}
EDGE_KINDS = ("data", "call", "control", "config")
VALUE_TAGS = ("RAW_DATA", "FEATURES", "TARGET", "TRAIN_SPLIT", "VAL_SPLIT",
              "TEST_SPLIT", "MODEL", "LOADER", "BATCH", "LOGITS", "PREDS",
              "LOSS", "OPTIMIZER")
EVIDENCE_KINDS = ("fqn_resolved", "dataflow_direct", "scope_static",
                  "context_confirmed", "cross_file", "name_regex")
DIAGNOSTIC_KINDS = ("parse_error", "dynamic_scope", "untagged_dataflow",
                    "config_warning", "single_file_analysis")
#: A small pool, deliberately, so bare names collide across files and the
#: `unit:` tiers (qualname, fqn, last segment, label) all get exercised.
NAMES = ("load", "Load", "prepare", "batch_loop", "BatchLoop", "train", "fit",
         "evaluate", "score", "build_model", "Net", "step")
FQNS = ("torch.optim.Adam", "sklearn.preprocessing.StandardScaler",
        "torch.nn.Linear", "pandas.read_csv", "sklearn.metrics.accuracy_score")


# --------------------------------------------------------------- validation
_VALIDATOR = None


def _schema_errors(doc) -> List[str]:
    """Schema errors, with the validator compiled once for the whole run."""
    global _VALIDATOR
    if _VALIDATOR is None:
        from jsonschema import Draft202012Validator
        with io.open(DEFAULT_SCHEMA, encoding="utf-8") as fh:
            _VALIDATOR = Draft202012Validator(json.load(fh))
    return ["schema: %s at %s" % (e.message, "/".join(str(p) for p in e.path))
            for e in list(_VALIDATOR.iter_errors(doc))[:5]]


def validate(doc) -> List[str]:
    """Schema + all ten invariant groups, exactly as `validate_sample.py` runs."""
    errs = _schema_errors(doc)
    return errs if errs else validate_graph(doc, run_schema=False)


# --------------------------------------------------------------- generation
#: Ids are 12 hex digits (`^n:[0-9a-f]{12}$`), so the seed is MIXED into 48 bits
#: rather than multiplied into them - a large seed used to overflow the pattern,
#: which `validate()` caught as a generator bug rather than a port divergence.
_ID_SPACE = 16 ** 12
_ID_ROOM = 4096                      # > any one document's nodes, edges or issues


def _id(prefix: str, seed: int, kind: int, index: int) -> str:
    base = ((seed * 2654435761) ^ (kind * 0x9E3779B9)) % (_ID_SPACE - _ID_ROOM)
    return "%s:%012x" % (prefix, base + index)


def _loc(rng: random.Random, root: str, path: str, line: int) -> Dict[str, Any]:
    return {"file": path, "absFile": root + "/" + path, "line": line, "col": 4,
            "endLine": line + rng.randint(0, 2), "endCol": 4 + rng.randint(1, 40)}


def _confidence(rng: random.Random) -> Tuple[float, str]:
    value = round(rng.uniform(0.2, 1.0), 2)
    return value, bucket_for(value)


def _profile(rng: random.Random) -> Dict[str, Any]:
    """Node count 5..500, weighted small so a run sees many shapes cheaply."""
    roll = rng.random()
    if roll < 0.55:
        size = rng.randint(5, 40)
    elif roll < 0.82:
        size = rng.randint(40, 120)
    elif roll < 0.95:
        size = rng.randint(120, 300)
    else:
        size = rng.randint(300, 500)
    return {
        "size": size,
        "files": max(1, min(12, size // 8 + rng.randint(1, 3))),
        "components": rng.choice((1, 1, 2, 3)),
        "ghost_rate": rng.choice((0.0, 0.1, 0.25, 0.5)),
        "orphan_rate": rng.choice((0.0, 0.1, 0.3)),
        "cross_stage": rng.choice((0.0, 0.3, 0.8)),
        "edges_per_node": rng.choice((0.3, 0.8, 1.4, 2.0)),
        "issues_per_node": rng.choice((0.02, 0.05, 0.15, 0.3)),
        # Arity 1 still happens (the count is `randint(1, max_arity)`), but a
        # ceiling of 1 would make the step-6 ROTATION unreachable for a whole
        # document, and rotation is the operation most likely to be ported
        # wrong - it is the only non-filter step in the algorithm.
        "max_arity": rng.choice((2, 3, 4)),
        "edge_anchor_rate": rng.choice((0.0, 0.2, 0.5)),
        "truncated": rng.random() < 0.1,
    }


def make_graph(seed: int) -> Dict[str, Any]:
    """One seeded, schema-valid document. Pure: same seed, same bytes."""
    rng = random.Random(seed)
    p = _profile(rng)
    root = "/w/fuzz%04d" % (seed % 10000)
    files = ["main.py"] + ["pkg/mod%d.py" % i for i in range(1, p["files"])]

    size = p["size"]
    n_stage = max(1, min(6, size // 12))
    n_unit = max(1, min(40, size // 4))
    n_op = max(0, size - n_stage - n_unit)
    levels = ["stage"] * n_stage + ["unit"] * n_unit + ["op"] * n_op

    line_of: Dict[str, int] = {f: 1 for f in files}
    raw: List[Dict[str, Any]] = []
    for index, level in enumerate(levels):
        path = files[index % len(files)] if rng.random() < 0.5 else rng.choice(files)
        line_of[path] += rng.randint(1, 4)
        name = rng.choice(NAMES)
        module = path[:-3].replace("/", ".")
        stage = rng.choice(STAGE_IDS)
        loc = _loc(rng, root, path, line_of[path])
        confidence, bucket = _confidence(rng)
        node: Dict[str, Any] = {
            "kind": rng.choice(NODE_KINDS[level]),
            "level": level,
            "stage": stage,
            "label": name + "()" if level != "op" else name,
            "qualname": "%s.%s" % (module, name) if rng.random() < 0.85 else name,
            "loc": loc,
            "parent": None,
            "attrs": {"lr": "1e-3"} if rng.random() < 0.3 else {},
            "produces": ([{"name": "out", "tags": [rng.choice(VALUE_TAGS)]}]
                         if rng.random() < 0.4 else []),
            "consumes": ([{"name": "x", "tags": [rng.choice(VALUE_TAGS)]}]
                         if rng.random() < 0.4 else []),
            "ghost": False,
            "dynamic": rng.random() < 0.15,
            "confidence": confidence,
            "confidenceBucket": bucket,
            "issueIds": [],
            "collapsedByDefault": rng.random() < 0.2,
            "stageEvidence": [{"kind": rng.choice(EVIDENCE_KINDS),
                               "detail": "generated", "weight": 0.5}],
            "_component": rng.randrange(p["components"]),
            "_sort": (STAGE_ORDER[stage], loc["file"], loc["line"], loc["col"]),
        }
        if rng.random() < 0.25:
            node["fqn"] = rng.choice(FQNS)
        if rng.random() < 0.3:
            node["framework"] = rng.choice(FRAMEWORKS)
        raw.append(node)

    raw.sort(key=lambda n: n["_sort"])
    for index, node in enumerate(raw):
        node["id"] = _id("n", seed, 1, index)
        node.pop("_sort")

    by_level: Dict[str, List[Dict[str, Any]]] = {"stage": [], "unit": [], "op": []}
    for node in raw:
        by_level[node["level"]].append(node)
    for node in raw:                                        # containment forest
        if node["level"] == "stage" or rng.random() < p["orphan_rate"]:
            continue
        pool = by_level["stage"] if node["level"] == "unit" else (
            by_level["unit"] if rng.random() < 0.8 else by_level["stage"])
        pool = [c for c in pool if LEVEL_RANK[c["level"]] < LEVEL_RANK[node["level"]]]
        if p["cross_stage"] < 1.0:
            same = [c for c in pool if c["stage"] == node["stage"]]
            if same and rng.random() > p["cross_stage"]:
                pool = same
        if pool:
            node["parent"] = rng.choice(pool)["id"]

    edges = _make_edges(rng, raw, p, root, seed)
    issues = _make_issues(rng, raw, edges, p, root, seed)
    graph = {
        "schemaVersion": "1.0",
        "generator": {"name": "mlview", "version": "0.1.0",
                      "rendererSha": "0" * 64,
                      "generatedAt": "2026-09-09T00:00:00Z"},
        "workspace": {"root": root, "entrypoints": [files[0]],
                      "filesAnalyzed": len(files), "filesFailed": 0,
                      "notebooksSkipped": 0,
                      "frameworks": sorted({rng.choice(FRAMEWORKS)
                                            for _ in range(rng.randint(1, 3))})},
        "stages": [], "nodes": raw, "edges": edges, "issues": issues,
        "diagnostics": _make_diagnostics(rng, files),
        "stats": {"nodes": 0, "edges": 0,
                  "issues": {"low": 0, "medium": 0, "high": 0},
                  "suppressed": 0, "durationMs": 12,
                  "truncated": bool(p["truncated"])},
    }
    return normalize(graph, rng, p["ghost_rate"])


def _make_edges(rng, nodes, p, root, seed) -> List[Dict[str, Any]]:
    """Edges inside a component only, so disconnected graphs really are."""
    buckets: Dict[int, List[Dict[str, Any]]] = {}
    for node in nodes:
        buckets.setdefault(node["_component"], []).append(node)
    seen = set()
    out: List[Dict[str, Any]] = []
    wanted = int(len(nodes) * p["edges_per_node"])
    for _ in range(wanted):
        pool = buckets[rng.choice(list(buckets))]
        if len(pool) < 2:
            continue
        source, target = rng.sample(pool, 2)
        kind = rng.choice(EDGE_KINDS)
        key = (source["id"], kind, target["id"])
        if key in seen:
            continue
        seen.add(key)
        path = source["loc"]["file"]
        edge = {"kind": kind, "source": source["id"], "target": target["id"],
                "loc": _loc(rng, root, path, source["loc"]["line"]),
                "tags": [rng.choice(VALUE_TAGS)] if kind == "data" else [],
                "confidence": round(rng.uniform(0.3, 1.0), 2), "issueIds": []}
        if kind == "control" and rng.random() < 0.5:
            edge["subkind"] = rng.choice(("enter", "back", "branch"))
        if rng.random() < 0.4:
            edge["label"] = "x%d" % rng.randrange(50)
        out.append(edge)
    out.sort(key=lambda e: (e["source"], e["kind"], e["target"]))
    for index, edge in enumerate(out):
        edge["id"] = _id("e", seed, 2, index)
    return out


def _make_issues(rng, nodes, edges, p, root, seed) -> List[Dict[str, Any]]:
    """Findings anchored on 1..4 nodes, and - the shape no shipped rule emits -
    on an edge whose cited nodes sit somewhere else entirely (11.2 step 6)."""
    count = int(len(nodes) * p["issues_per_node"])
    out: List[Dict[str, Any]] = []
    for _ in range(count):
        arity = rng.randint(1, min(p["max_arity"], len(nodes)))
        anchors = rng.sample(nodes, arity)
        cited: List[str] = []
        roll = rng.random()
        if edges and roll < p["edge_anchor_rate"]:
            # The shape no shipped rule emits and step 6 still has to answer:
            # an issue retained through an EDGE whose cited nodes are elsewhere.
            edge = rng.choice(edges)
            cited = [edge["id"]]
            anchors = [n for n in anchors
                       if n["id"] not in (edge["source"], edge["target"])]
            if not anchors:
                continue
        elif edges and roll < p["edge_anchor_rate"] + 0.3:
            cited = [e["id"] for e in rng.sample(edges, min(2, len(edges)))]
        severity = rng.choice(SEVERITIES)
        confidence, bucket = _confidence(rng)
        path = anchors[0]["loc"]["file"]
        line = anchors[0]["loc"]["line"]
        out.append({
            "code": "MLV%03d" % rng.randrange(101, 900),
            "ruleVersion": 1, "severity": severity, "confidence": confidence,
            "confidenceBucket": bucket, "title": "generated finding",
            "message": "generated", "why": "generated", "fixHint": "generated",
            "loc": _loc(rng, root, path, line), "relatedLocs": [],
            "nodeIds": [n["id"] for n in anchors], "edgeIds": cited,
            "stage": anchors[0]["stage"], "frameworks": [], "tags": [],
            "evidence": [{"kind": rng.choice(EVIDENCE_KINDS),
                          "detail": "generated", "weight": 0.5}],
            "suppressed": rng.random() < 0.15,
            "docs": "docs/rules/MLV101.md",
        })
    out.sort(key=lambda i: (-SEV_RANK[i["severity"]], i["loc"]["file"],
                            i["loc"]["line"], i["code"]))
    for index, issue in enumerate(out):
        issue["id"] = _id("i", seed, 3, index)
    return out


def _make_diagnostics(rng, files) -> List[Dict[str, Any]]:
    out = []
    for _ in range(rng.randint(0, 3)):
        row = {"kind": rng.choice(DIAGNOSTIC_KINDS), "message": "generated note"}
        if rng.random() < 0.5:
            row["file"] = rng.choice(files)
            row["line"] = rng.randint(1, 40)
        out.append(row)
    out.sort(key=lambda d: (d["kind"], d.get("file") or "", d.get("line") or 0,
                            d["message"]))
    return out


# -------------------------------------------------------------- normalization
def normalize(graph: Dict[str, Any], rng: Optional[random.Random] = None,
              ghost_rate: float = 0.0) -> Dict[str, Any]:
    """Re-derive everything a generated or *reduced* document must satisfy.

    Both the generator and the minimizer produce raw parts and then land here:
    reverse links, the ghost invariant (1.1.8: a ghost carries at least one
    finding, so a ghost that lost its last issue is dropped), the eight stage
    rows, `stats`, and the three sort orders. Idempotent.
    """
    first = True
    while True:
        nodes = graph["nodes"]
        by_id = {n["id"]: n for n in nodes}
        edges = [e for e in graph["edges"]
                 if e["source"] in by_id and e["target"] in by_id]
        edge_ids = {e["id"] for e in edges}
        issues = []
        for issue in graph["issues"]:
            issue["nodeIds"] = [n for n in issue["nodeIds"] if n in by_id]
            issue["edgeIds"] = [e for e in issue["edgeIds"] if e in edge_ids]
            if issue["nodeIds"]:
                issue["stage"] = by_id[issue["nodeIds"][0]]["stage"]
                issues.append(issue)
        anchored: Dict[str, List[str]] = {}
        cited: Dict[str, List[str]] = {}
        for issue in issues:
            for node_id in issue["nodeIds"]:
                anchored.setdefault(node_id, []).append(issue["id"])
            for edge_id in issue["edgeIds"]:
                cited.setdefault(edge_id, []).append(issue["id"])
        for node in nodes:
            node["issueIds"] = anchored.get(node["id"], [])
        for edge in edges:
            edge["issueIds"] = cited.get(edge["id"], [])
        if first and rng is not None and ghost_rate:
            for node in nodes:
                if node["issueIds"] and rng.random() < ghost_rate:
                    node["ghost"] = True
        first = False
        doomed = {n["id"] for n in nodes if n["ghost"] and not n["issueIds"]}
        graph["edges"], graph["issues"] = edges, issues
        if not doomed:
            break
        graph["nodes"] = [n for n in nodes if n["id"] not in doomed]
        for node in graph["nodes"]:            # re-point over the dropped ghosts
            parent = node.get("parent")
            while parent is not None and parent in doomed:
                parent = by_id[parent].get("parent")
            node["parent"] = parent

    for node in graph["nodes"]:
        node.pop("_component", None)
    graph["nodes"].sort(key=lambda n: (STAGE_ORDER[n["stage"]], n["loc"]["file"],
                                       n["loc"]["line"], n["loc"]["col"]))
    graph["edges"].sort(key=lambda e: (e["source"], e["kind"], e["target"]))
    graph["issues"].sort(key=lambda i: (-SEV_RANK[i["severity"]], i["loc"]["file"],
                                        i["loc"]["line"], i["code"]))

    stages = []
    for order, sid in enumerate(STAGE_IDS):
        counts = {"low": 0, "medium": 0, "high": 0}
        for issue in graph["issues"]:
            if issue["stage"] == sid and not issue["suppressed"]:
                counts[issue["severity"]] += 1
        node_count = sum(1 for n in graph["nodes"] if n["stage"] == sid)
        worst = next((s for s in ("high", "medium", "low") if counts[s]), None)
        present = bool(node_count or any(counts.values()))
        stages.append({"id": sid, "label": sid.title(), "order": order,
                       "present": present,
                       "nodeCount": node_count if present else 0,
                       "issueCounts": counts if present else
                       {"low": 0, "medium": 0, "high": 0},
                       "maxSeverity": worst if present else None})
    graph["stages"] = stages

    totals = {"low": 0, "medium": 0, "high": 0}
    suppressed = 0
    for issue in graph["issues"]:
        if issue["suppressed"]:
            suppressed += 1
        else:
            totals[issue["severity"]] += 1
    graph["stats"]["nodes"] = len(graph["nodes"])
    graph["stats"]["edges"] = len(graph["edges"])
    graph["stats"]["issues"] = totals
    graph["stats"]["suppressed"] = suppressed
    return graph


# ---------------------------------------------------------------- selectors
def selectors_for(graph: Dict[str, Any], rng: random.Random, count: int
                  ) -> List[Tuple[str, Optional[int]]]:
    """A spread over every scope kind and every legal depth, plus the errors."""
    nodes = graph["nodes"]
    files = sorted({n["loc"]["file"] for n in nodes})
    quals = sorted({n["qualname"] for n in nodes})
    labels = sorted({n["label"] for n in nodes})
    kinds = ["all", "stage", "concern", "file", "unit", "unit", "node", "error"]
    out: List[Tuple[str, Optional[int]]] = []
    for index in range(count):
        kind = kinds[index % len(kinds)] if index < len(kinds) else rng.choice(kinds)
        depth = rng.choice((None, 0, 1, 2))
        if kind == "all":
            spec = "all"
        elif kind == "stage":
            spec = "stage:" + rng.choice(STAGE_IDS)
        elif kind == "concern":
            spec = "concern:" + rng.choice(CONCERN_NAMES)
        elif kind == "file":
            path = rng.choice(files)
            spec = "file:" + rng.choice(
                (path, path.rsplit("/", 1)[-1], path.upper(), "nope.py"))
        elif kind == "node":
            spec = "node:" + (rng.choice(nodes)["id"] if rng.random() < 0.9
                              else "n:000000000000")
        elif kind == "unit":
            target = rng.choice(quals + labels + ["Nope"])
            if rng.random() < 0.2:
                target = target.upper()
            spec = "unit:" + target
        else:
            spec, depth = rng.choice((
                ("bogus:x", None), ("stage:nope", None), ("concern:nope", None),
                ("stage:train", 3), ("", None), ("unit:", None)))
        out.append((spec, depth))
    return out


CONCERN_NAMES = ("config", "data", "optimization", "evaluation", "setup",
                 "dataset", "training", "inference", "eval", "preprocessing")
