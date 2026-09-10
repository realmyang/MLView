#!/usr/bin/env python
"""The two LATER projection shapes, taught to the fuzz generator (HEALTH-02).

`scope_gen.py` knows what a schema-valid MLView document looked like before
Sprint 5. This module knows the two shapes Sprint 5 adds on top of it, so the
differential fuzzer can produce them too:

* **PERF-04 rollup** (`docs/contracts/11.46-rollup.md`) - a document that hit
  `--max-nodes` and was *rolled up* rather than mutilated: non-ghost `op`
  children folded into their unit, optionally a whole file folded into a
  synthesized summary node, every fold carrying a transitive `rolledUp` count;
  edges re-pointed at the survivor, parallels merged into one carrying a
  `weight`, edges internal to a fold **absorbed**; `stats.truncated` true with a
  `Diagnostic{kind: "truncated"}` that says "rolled up".
* **MLV-P12 pipelines** (`docs/contracts/11.47-pipelines.md`) - the root
  `pipelines[]` block over the reach of each `workspace.entrypoints` entry under
  `data`/`call` edges **and containment**, emitted only when two or more
  pipelines are non-empty; plus the `pipeline:<entrypoint>` selectors.

**Everything here is feature-probed, never assumed.** `contracts/graph.schema.json`
is `additionalProperties: false` at every level, so a generator that invented
`rolledUp` before the schema declared it would produce documents that do not
validate - which the fuzzer reports as a GENERATOR BUG, not as a port
divergence. So this module reads the schema, decides for itself which of the two
shapes the repository currently supports, fills the *declared* members, and
`capability_note()` states in one line what it could not generate and why. A
fuzz run against a checkout where those amendments have not landed is therefore
a smaller run that says so, never a green run that silently checked nothing.

The `pipeline:` **selectors are emitted regardless**: if only one of the two
`project()` implementations has learned the new scope kind, the ports disagree
about a selector's outcome - a refusal on one side, a projection on the other -
and that is precisely the CONTRACTS 11.16 "they move together" drift this fuzzer
exists to catch.

What it deliberately does not do: reproduce the analyzer's *choice* of what to
fold (11.46 A1's ordering is a heuristic and `test_rollup.py` owns it) or its
ranking of entrypoints. It produces documents in the contracted **shape**, which
is all a projection can see.

Pure and seeded, like `scope_gen.py`: same seed, same bytes.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import random
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
CONTRACTS = os.path.join(REPO, "contracts")
for _path in (HERE, CONTRACTS):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from validate_sample import (DEFAULT_SCHEMA, STAGE_ORDER,  # noqa: E402
                             bucket_for)

#: Keys `digest_of` / `digestOf` may carry *beyond* the frozen shape. The fuzzer
#: probes which of these the Python twin actually emits and tells the harness;
#: see `scope_fuzz.digest_extras()`.
DIGEST_EXTRAS: Tuple[str, ...] = ("rolledUp", "weight", "pipelines")


# --------------------------------------------------------------- the probe
def _load_schema() -> Dict[str, Any]:
    with io.open(DEFAULT_SCHEMA, encoding="utf-8") as fh:
        return json.load(fh)


def _deref(schema: Dict[str, Any], node: Any) -> Dict[str, Any]:
    """One level of `$ref` into `$defs`, which is all this schema uses."""
    seen = 0
    while isinstance(node, dict) and "$ref" in node and seen < 8:
        ref = node["$ref"]
        if not ref.startswith("#/$defs/"):
            return {}
        node = schema.get("$defs", {}).get(ref.split("/")[-1], {})
        seen += 1
    return node if isinstance(node, dict) else {}


def _shape_of(schema: Dict[str, Any], owner: str, field: str) -> Optional[Dict[str, Any]]:
    """The declaration of one optional field, or None when it is not declared."""
    holder = schema.get("$defs", {}).get(owner) if owner else schema
    if not isinstance(holder, dict):
        return None
    prop = (holder.get("properties") or {}).get(field)
    return _deref(schema, prop) if prop is not None else None


class Support(object):
    """What the *current* schema lets this generator produce."""

    def __init__(self, schema: Dict[str, Any]) -> None:
        self.rolled_up = _shape_of(schema, "Node", "rolledUp")
        self.weight = _shape_of(schema, "Edge", "weight")
        pipelines = _shape_of(schema, "", "pipelines")
        self.pipelines_item = (_deref(schema, (pipelines or {}).get("items") or {})
                               if pipelines else None)
        self.missing: List[str] = []
        if self.rolled_up is None:
            self.missing.append("Node.rolledUp")
        if self.weight is None:
            self.missing.append("Edge.weight")
        if not self.pipelines_item:
            self.missing.append("pipelines[]")

    @property
    def rollup(self) -> bool:
        return self.rolled_up is not None and self.weight is not None

    @property
    def pipelines(self) -> bool:
        return bool(self.pipelines_item)


_SUPPORT: Optional[Support] = None


def support() -> Support:
    global _SUPPORT
    if _SUPPORT is None:
        _SUPPORT = Support(_load_schema())
    return _SUPPORT


def capability_note() -> str:
    """One line naming what this generator can and cannot produce today."""
    have = support()
    can = [name for name, ok in (("rolled-up (capped) documents", have.rollup),
                                 ("pipelines[] documents", have.pipelines)) if ok]
    line = "generating " + (" and ".join(can) if can else "no LATER shapes")
    if have.missing:
        line += ("; the schema does not declare %s, so those shapes are OUTSIDE "
                 "this run" % ", ".join(have.missing))
    return line


# ------------------------------------------------------------ filling shapes
def _fill(shape: Dict[str, Any], values: Dict[str, Any]) -> Optional[Any]:
    """Build a value for a declared shape from a bag of computed members.

    An integer or number declaration takes `values["_count"]`. An object
    declaration takes every one of its *required* members from `values`, plus
    any optional member the bag happens to know. A required member this module
    cannot compute returns None - the caller then skips the shape rather than
    guessing, and the run says which member stopped it.
    """
    kind = shape.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), None)
    if kind in ("integer", "number"):
        return values.get("_count")
    if kind == "string":
        return values.get("_label")
    if kind != "object":
        return None
    out: Dict[str, Any] = {}
    for name in shape.get("required") or []:
        if name not in values:
            return None
        out[name] = values[name]
    for name in shape.get("properties") or {}:
        if name not in out and name in values:
            out[name] = values[name]
    return out


def _unfillable(shape: Optional[Dict[str, Any]], values: Dict[str, Any]) -> str:
    """The member name that stopped `_fill`, for the honest note."""
    if not shape or shape.get("type") != "object":
        return ""
    for name in shape.get("required") or []:
        if name not in values:
            return name
    return ""


def _sha12(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


# ------------------------------------------------------------------- rollup
def _survivor(folded: Dict[str, str], node_id: str) -> str:
    """The end of the fold chain: an op folded into a unit folded into a file."""
    seen = 0
    while node_id in folded and seen < 64:
        node_id = folded[node_id]
        seen += 1
    return node_id


def _majority(values: Sequence[str], order=None) -> str:
    """Most common, ties broken by `order` (ascending name by default)."""
    counts: Dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    key = (lambda v: (-counts[v], order(v))) if order else (lambda v: (-counts[v], v))
    return sorted(counts, key=key)[0]


def _file_summary(path: str, root: str, members: Sequence[Dict[str, Any]]
                  ) -> Dict[str, Any]:
    """11.46 A3, to the letter - a synthesized file summary node."""
    confidence = max(m["confidence"] for m in members)
    return {
        "id": "n:" + _sha12("%s|%s|file-rollup" % (path, path)),
        "kind": _majority([m["kind"] for m in members]),
        "level": "stage",
        "stage": _majority([m["stage"] for m in members],
                           order=lambda s: STAGE_ORDER[s]),
        "label": path.rsplit("/", 1)[-1],
        "sublabel": "%d nodes rolled up" % len(members),
        "qualname": path,
        "loc": {"file": path, "absFile": root + "/" + path, "line": 1, "col": 0,
                "endLine": 1, "endCol": 0},
        "parent": None,
        "attrs": {"rollup": "file"},
        "produces": [], "consumes": [],
        "ghost": False,
        "dynamic": any(m["dynamic"] for m in members),
        "confidence": confidence,
        "confidenceBucket": bucket_for(confidence),
        "issueIds": [],
        "collapsedByDefault": True,
        "stageEvidence": [{"kind": "scope_static", "detail": "file rollup",
                           "weight": 0.5}],
    }


def _merge_edges(graph: Dict[str, Any], folded: Dict[str, str],
                 have: Support) -> Tuple[int, int]:
    """Re-point, absorb, merge (11.46 B2/B3). Returns (merged, absorbed)."""
    merged: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    members: Dict[str, List[Dict[str, Any]]] = {}
    order: List[Tuple[str, str, str]] = []
    absorbed: List[str] = []
    for edge in graph["edges"]:
        source = _survivor(folded, edge["source"])
        target = _survivor(folded, edge["target"])
        if source == target:                 # B3: internal to a fold, absorbed
            absorbed.append(edge["id"])
            continue
        edge["source"], edge["target"] = source, target
        key = (source, edge["kind"], target)
        if key not in merged:
            merged[key] = edge
            members[edge["id"]] = [edge]
            order.append(key)
        else:
            members[merged[key]["id"]].append(edge)

    remap: Dict[str, str] = {}
    out: List[Dict[str, Any]] = []
    for key in order:
        first = merged[key]
        group = members[first["id"]]
        labels = {e.get("label") for e in group}
        label = labels.pop() if len(labels) == 1 else None
        if label is None:
            first.pop("label", None)
        else:
            first["label"] = label
        first["confidence"] = max(e["confidence"] for e in group)
        new_id = "e:" + _sha12("%s|%s|%s|%s" % (key[0], key[1], key[2],
                                                first.get("label") or ""))
        if len(group) > 1:
            value = _fill(have.weight or {}, {"_count": len(group),
                                              "_label": str(len(group))})
            if value is not None:
                first["weight"] = value
        for member in group:
            remap[member["id"]] = new_id
        first["id"] = new_id
        out.append(first)
    graph["edges"] = out

    for issue in graph["issues"]:
        mapped: List[str] = []
        for edge_id in issue["edgeIds"]:
            new = remap.get(edge_id)
            if new is not None and new not in mapped:
                mapped.append(new)
        issue["edgeIds"] = mapped
    return sum(1 for e in out if "weight" in e), len(absorbed)


def roll_up(graph: Dict[str, Any], rng: random.Random) -> Tuple[Dict[str, Any], str]:
    """Fold a document the way `--max-nodes` now does (11.46 phases 1 and 2).

    Returns `(graph, note)`; `note` is empty when the document really was rolled
    up and names the reason when it was left alone. The result is not normalized
    here - `scope_fuzz` runs the shared `normalize()` afterwards, so a rolled-up
    document lands on exactly the same invariants as any other.
    """
    have = support()
    if not have.rollup:
        return graph, ("unsupported: the schema declares neither Node.rolledUp "
                       "nor Edge.weight")
    nodes = graph["nodes"]
    by_id = {n["id"]: n for n in nodes}
    folded: Dict[str, str] = {}

    # Phase 1: non-ghost op children fold into their unit. A5: never a ghost.
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for node in nodes:
        parent = node.get("parent")
        if parent in by_id and node["level"] == "op" and not node["ghost"]:
            groups.setdefault(parent, []).append(node)
    for parent_id in rng.sample(sorted(groups),
                                max(1, int(len(groups) * rng.choice((0.4, 0.7, 1.0))))
                                ) if groups else []:
        for child in groups[parent_id]:
            folded[child["id"]] = parent_id

    # Phase 2 (sometimes): one whole file folds into a synthesized summary node.
    summaries: List[Dict[str, Any]] = []
    root = graph["workspace"]["root"]
    if rng.random() < 0.4:
        by_file: Dict[str, List[Dict[str, Any]]] = {}
        for node in nodes:
            if node["id"] in folded or node["ghost"]:
                continue
            by_file.setdefault(node["loc"]["file"], []).append(node)
        candidates = sorted(path for path, members in by_file.items()
                            if len(members) >= 2)
        if candidates:
            path = rng.choice(candidates)
            summary = _file_summary(path, root, by_file[path])
            if summary["id"] not in by_id:
                summaries.append(summary)
                for member in by_file[path]:
                    folded[member["id"]] = summary["id"]
    if not folded:
        return graph, "n/a: nothing to fold - no unit with non-ghost op children"

    for summary in summaries:                # available as a fold destination
        by_id[summary["id"]] = summary

    # B1: the count is transitive, and it lands on the node that survives.
    counts: Dict[str, int] = {}
    for node_id in folded:
        counts[_survivor(folded, node_id)] = counts.get(
            _survivor(folded, node_id), 0) + 1
    blocked = ""
    for survivor_id, count in counts.items():
        value = _fill(have.rolled_up or {}, {"_count": count, "_label": str(count)})
        if value is None:
            blocked = _unfillable(have.rolled_up, {"_count": count})
            break
        by_id[survivor_id]["rolledUp"] = value
    if blocked:
        return graph, ("unsupported: Node.rolledUp requires a member this "
                       "generator cannot compute: %s" % blocked)

    # B4: every anchor maps through the fold, de-duplicated, order preserved.
    for issue in graph["issues"]:
        mapped: List[str] = []
        for node_id in issue["nodeIds"]:
            survivor = _survivor(folded, node_id)
            if survivor not in mapped:
                mapped.append(survivor)
        issue["nodeIds"] = mapped

    merged, absorbed = _merge_edges(graph, folded, have)

    kept = [n for n in nodes if n["id"] not in folded] + summaries
    for node in kept:                        # parents follow the fold as well
        parent = node.get("parent")
        node["parent"] = _survivor(folded, parent) if parent else parent
        if node["parent"] == node["id"]:
            node["parent"] = None
    graph["nodes"] = kept
    graph["stats"]["truncated"] = True
    graph["diagnostics"] = [d for d in graph["diagnostics"]
                            if d.get("kind") != "truncated"]
    graph["diagnostics"].append(truncation_diagnostic(
        graph,
        "%d node(s) rolled up into %d file summary node(s), %d edge(s) merged, "
        "%d absorbed" % (len(folded), len(summaries), merged, absorbed),
        count=len(folded)))
    return graph, ""


def truncation_diagnostic(graph: Dict[str, Any], suffix: str = "",
                          count: int = 0) -> Dict[str, Any]:
    """11.46 C4/D: a truncated document owes the reader one `truncated` note.

    Every generated document passes through here, not only the rolled-up ones:
    `scope_gen` flips `stats.truncated` on a tenth of its documents, and a
    document that claims to be capped and says nothing about it would fail the
    same check group a real one would. The node count is re-derived every time,
    so a *reduced* document never keeps a number that was true before the
    minimizer deleted half of it.
    """
    message = "budget reached: %d node(s) kept" % len(graph["nodes"])
    if suffix:
        message += "; " + suffix
    return {"kind": "truncated", "message": message, "count": count}


# ---------------------------------------------------------------- pipelines
def analyzer_block(graph: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """The block **the shipped analyzer would emit** for this document, or None.

    There is deliberately no second implementation here. A generated document
    must be one the analyzer could have produced: a block computed by a subtly
    different local copy of 11.47 A would make the fuzz run assert parity over a
    document that cannot exist, which is worse than not fuzzing the shape at
    all. If `mlview.core.pipelines` is not importable, this generator produces no
    pipelines and the run says so.
    """
    try:
        from mlview.core.pipelines import pipelines_block
    except Exception:                       # pragma: no cover - old checkout
        return None
    try:
        return pipelines_block(graph)
    except Exception:                       # pragma: no cover - defensive
        return None


def pipeline_entries(graph: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], str]:
    """The `pipelines[]` block (11.47 D), or the reason there is none."""
    have = support()
    if not have.pipelines:
        return [], "unsupported: the schema declares no root pipelines[]"
    shipped = analyzer_block(graph)
    if shipped is None:
        return [], ("unsupported: mlview.core.pipelines is not importable, so "
                    "this generator has no relation to compute the block with")
    if len(shipped) < 2:
        return [], "n/a: fewer than two non-empty pipelines (11.47 D)"
    required = set((have.pipelines_item or {}).get("required") or [])
    missing = sorted(required - set(shipped[0]))
    if missing:
        return [], ("unsupported: pipelines_block does not emit the required "
                    "member(s) %s" % ", ".join(missing))
    return shipped, ""


def with_pipelines(graph: Dict[str, Any], rng: random.Random
                   ) -> Tuple[Dict[str, Any], str]:
    """Give the document two or three entrypoints and the matching block."""
    files = sorted({n["loc"]["file"] for n in graph["nodes"]})
    if len(files) > 1:
        wanted = min(len(files), rng.choice((2, 2, 3)))
        graph["workspace"]["entrypoints"] = sorted(
            set([files[0]] + rng.sample(files[1:], wanted - 1)))
    entries, note = pipeline_entries(graph)
    if note:
        return graph, note
    graph["pipelines"] = entries
    return graph, ""


def renormalize(graph: Dict[str, Any]) -> Dict[str, Any]:
    """Re-derive the LATER blocks after a reduction, so a *minimized* document
    is as valid as a generated one - the contract `scope_gen.normalize()` keeps
    for the frozen shape.

    `rolledUp` counts nodes that are already gone, so it survives further
    deletion untouched and `stats.truncated` stays sticky with it (11.46 C5).
    The pipelines block is recomputed over whatever nodes and edges are left,
    and dropped entirely when fewer than two pipelines are left non-empty.
    """
    if any("rolledUp" in n for n in graph["nodes"]) or \
            any("weight" in e for e in graph["edges"]):
        graph["stats"]["truncated"] = True
    if "pipelines" in graph:
        entries, note = pipeline_entries(graph)
        if note or len(entries) < 2:
            graph.pop("pipelines", None)
        else:
            graph["pipelines"] = entries
    previous = [d for d in graph.get("diagnostics") or []
                if d.get("kind") == "truncated"]
    diagnostics = [d for d in graph.get("diagnostics") or []
                   if d.get("kind") != "truncated"]
    if graph["stats"].get("truncated"):
        # The fold detail is the old note's; only the kept-node count is stale.
        suffix = (previous[0]["message"].split("; ", 1)[1]
                  if previous and "; " in previous[0]["message"] else "")
        diagnostics.append(truncation_diagnostic(
            graph, suffix, count=(previous[0].get("count") if previous else 0) or 0))
    diagnostics.sort(key=lambda d: (d["kind"], d.get("file") or "",
                                    d.get("line") or 0, d["message"]))
    graph["diagnostics"] = diagnostics
    return graph


# ---------------------------------------------------------------- selectors
def decorate(graph: Dict[str, Any], rng: random.Random) -> Tuple[Dict[str, Any], List[str]]:
    """Apply the LATER shapes to a freshly generated document.

    Roughly a third of documents are rolled up and roughly half carry a
    pipelines block, so one run sees plain, capped, multi-pipeline and
    both-at-once documents. Every skip is a note the run prints.
    """
    notes: List[str] = []
    if rng.random() < 0.35:
        graph, note = roll_up(graph, rng)
        if note:
            notes.append(_tagged("rollup", note))
    if rng.random() < 0.5:
        graph, note = with_pipelines(graph, rng)
        if note:
            notes.append(_tagged("pipelines", note))
    return graph, notes


def _tagged(shape: str, note: str) -> str:
    """`"unsupported: rollup - ..."` / `"n/a: pipelines - ..."`.

    The two are different facts and a run must not blur them: *unsupported*
    means this checkout cannot express the shape at all and the run proved
    nothing about it; *n/a* means this particular document did not qualify,
    which is ordinary.
    """
    tag, _, rest = note.partition(": ")
    return "%s: %s - %s" % (tag, shape, rest)


def selectors_for(graph: Dict[str, Any], rng: random.Random, count: int
                  ) -> List[Tuple[str, Optional[int]]]:
    """`pipeline:` selectors - 11.47 B's four spellings, plus the two misses.

    Emitted whether or not the grammar has landed: two ports that disagree about
    whether `pipeline:` parses at all is exactly the drift worth catching.
    """
    entrypoints = list(graph["workspace"].get("entrypoints") or [])
    pool: List[Tuple[str, Optional[int]]] = []
    for entry in entrypoints:
        pool.append(("pipeline:" + entry, rng.choice((None, 0, 1, 2))))
        pool.append(("pipeline:" + entry.rsplit("/", 1)[-1], rng.choice((None, 1))))
        pool.append(("pipeline:" + entry.upper(), None))
        pool.append(("pipeline:" + entry.replace("/", "\\"), None))
    pool.extend([("pipeline:nope.py", None), ("pipeline:", None),
                 ("pipeline:main.py", 3)])
    if count >= len(pool):
        return pool
    return rng.sample(pool, count)


__all__ = ["DIGEST_EXTRAS", "Support", "support", "capability_note", "decorate",
           "roll_up", "truncation_diagnostic", "with_pipelines",
           "pipeline_entries", "renormalize", "selectors_for"]
