"""Pure payload builders for the MLView MCP tools.

Nothing in this module touches the filesystem, the network, argparse or the MCP
SDK: every function takes an already-loaded graph document (the dict produced by
``mlview.api.analyze_to_dict``) and returns the small dict a tool hands back to
the model.  Keeping them pure is what lets ``tests/test_digest_budget.py`` prove
the 4 KB budget on a 500-node synthetic graph without starting a server.

The single hard rule enforced here: **every payload is <= 4096 bytes in the
encoding the MCP SDK actually hands the model** — the indented ``content[0].text``
block, which is larger than the compact ``structuredContent`` one (see
``mlview_budget.payload_size``).  Detail that does not fit lives on disk behind
``graphPath`` and the payload says so with ``truncated: true``.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence

from mlview_budget import (  # the shared 4 KB budget machinery
    LIMIT_BYTES,
    PROTECTED_KEYS,
    clip_text_lines,
    compact_size,
    fit,
    payload_size,
    serialize,
)
from mlview_groups import (  # RAIL-GROUP: one row per rule / file / severity
    GROUP_BY_MODES,
    group_issues,
    group_note,
)
from mlview_notes import (  # the "is an empty result good news?" helpers
    corpus_note as _corpus_note,
    coverage_note as _coverage_note,
    coverage_notes,
    diagnostics_summary,
)
import mlview_scope as scopes  # the section 11.1 grammar at the tool boundary
from mlview_views import (  # filtered views + the shapes they render into
    json_index,
    neighbourhood_ids,
    stage_scope_ids,
    stage_summary_mermaid,
    stage_summary_text,
    subgraph,
)

SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2}

#: The eight canonical pipeline stages (CONTRACTS section 1, `StageId`),
#: re-exported from `mlview_scope` so the accepted-value vocabulary has exactly
#: one home (CONTRACTS 11.10). Used to tell "scope=stage:nosuch" (a caller
#: mistake, worth an error) apart from "scope=stage:eval on a project with no
#: eval lane" (a real, reportable answer).
STAGE_IDS = scopes.STAGE_IDS

GRAPH_FORMATS = ("mermaid", "text", "json")

#: `mlview_issues`' documented default row cap, and the floor a non-positive one
#: is held to. One row, not twenty: `mlview_scope.clamp_depth` holds `depth` at the
#: nearest LEGAL value rather than at its default, and this is the same treatment.
DEFAULT_ISSUE_LIMIT = 20
MIN_ISSUE_LIMIT = 1

#: `mlview_analyze`'s documented graph cap (CONTRACTS section 3, `--max-nodes`).
DEFAULT_MAX_NODES = 400


def _reject(argument: str, value: Any, accepted: Sequence[str], extra: str = "") -> None:
    """Raise the message the model should see for an out-of-range enum value.

    ``ValueError`` is what the server's ``visible_errors`` wrapper turns into a
    ``ToolError``, so the text below reaches the model verbatim and it can retry
    with a real value. Silently coercing instead (mermaid for a bad `format`,
    `low` for a bad `minSeverity`) hands back a confident, wrong-shaped answer
    that the caller has no way to detect.
    """
    raise ValueError(
        "%s=%r is not valid; accepted values are %s%s"
        % (argument, value, ", ".join(repr(a) for a in accepted), extra)
    )


def clamp_limit(limit: Any, default: int = DEFAULT_ISSUE_LIMIT) -> tuple:
    """``(rows, note)`` — the row cap held at or above 1, saying so when it moved.

    The `depth` treatment (`mlview_scope.clamp_depth`) applied to the one other
    numeric argument that can empty a payload on its own. `limit=0` and
    `limit=-3` used to return ``issues: []`` beside a ``countBySeverity`` of
    fifteen findings and no note — and an empty list from a tool the caller asked
    for a LISTING is the shape a model reads as "there are none".

    Out of range is clamped **and said**, never one without the other: an enum is
    rejected (`_reject`) because there is no nearest legal value, a bound has one.
    A value that is not a number at all cannot be honoured, so the documented
    default is used and the note names it.
    """
    if limit is None:
        return default, None
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return default, "limit=%r is not an integer; the default %d was used" % (
            limit, default,
        )
    if value < MIN_ISSUE_LIMIT:
        return MIN_ISSUE_LIMIT, "limit=%d is below the minimum %d; %d was used" % (
            value, MIN_ISSUE_LIMIT, MIN_ISSUE_LIMIT,
        )
    return value, None


def max_nodes_note(max_nodes: Any, default: int = DEFAULT_MAX_NODES) -> tuple:
    """``(budget, note)`` — `maxNodes` as the analyzer will read it, said out loud.

    NOT a clamp, deliberately. CONTRACTS 11.46 A is normative: `apply_node_budget`
    returns having mutated nothing when ``max_nodes <= 0``, so a non-positive
    budget means **uncapped**, and `--max-nodes 0` on the CLI means the same
    thing. Substituting the default here would make the two hosts disagree about
    one number. What was missing is the sentence: the payload came back with the
    whole graph and ``truncated: false`` and nothing said the cap had been
    dropped, so a caller that asked for a small graph believed it got one.

    A value that is not an integer cannot be honoured at all, so the documented
    default is used and the note names it.
    """
    if max_nodes is None:
        return default, None
    try:
        value = int(max_nodes)
    except (TypeError, ValueError):
        return default, "maxNodes=%r is not an integer; the default %d was used" % (
            max_nodes, default,
        )
    if value <= 0:
        # Kept SHORT on purpose: `note` is a PROTECTED key, so every byte of it is
        # paid for by `fit` shedding a row from `topIssues` — measured, a 232-byte
        # sentence here cost the digest one of its eight findings. A bound note
        # must never be more expensive than the finding it displaces.
        return value, (
            "maxNodes=%d is not a cap: a non-positive budget keeps the whole graph"
            % value
        )
    return value, None


# ------------------------------------------------------------------- mlview_analyze
def analyze_payload(
    digest_dict: Dict[str, Any],
    graph_path: str,
    report_path: Optional[str] = None,
    limit: int = LIMIT_BYTES,
    graph: Optional[Dict[str, Any]] = None,
    scope: Optional[str] = None,
    extra_notes: Sequence[str] = (),
) -> Dict[str, Any]:
    """The `mlview_analyze` result: the core digest plus the on-disk pointers.

    ``graph`` is optional and used only for the diagnostics summary and the
    "nothing was analyzed" note; the digest itself already carries the counts.

    ``scope`` is the normalized selector when the digest describes a PROJECTION
    (CONTRACTS 11.10). It is echoed as a top-level key and it adds the
    filtered-view note, because a scoped digest's counts are a statement about
    the scope and the model is told elsewhere to report lane absences as
    findings. ``graphPath`` still points at the FULL document either way.
    """
    out = dict(digest_dict)
    out["graphPath"] = graph_path
    if report_path:
        out["reportPath"] = report_path
    diagnostics = diagnostics_summary(graph) if graph else []
    if diagnostics:
        out["diagnostics"] = diagnostics
    # ROADMAP COVERAGE: the tally above says a kind fired and how many times; only
    # this block says WHICH RULES stayed silent, which is what `commands/mlview.md`
    # tells the model to report before the finding count.
    coverage = coverage_notes(graph)
    if coverage:
        out["coverage"] = coverage
    notes = [n for n in extra_notes if n]
    if scope:
        # `digest()` already emits the richer CONTRACTS 11.6 block
        # {spec, kind, target, depth, nodesInScope, nodesTotal} for a projected
        # document, and that block is the whole reason a scoped digest cannot be
        # mistaken for a project-wide one — so it is never overwritten with the
        # bare selector string. Only a caller that projected without going through
        # `digest` gets the string form.
        if not isinstance(out.get("scope"), dict):
            out["scope"] = scope
        notes.append(scopes.filtered_view_note(scope))
    blind = _coverage_note(coverage)
    if blind:
        notes.insert(0, blind)
    note = _corpus_note(
        int(out.get("filesAnalyzed") or 0), int(out.get("filesFailed") or 0), diagnostics
    )
    if note:
        # "nothing was analyzed" leads, then the coverage caveat: the order the
        # command body tells the model to speak them in.
        notes.insert(0, note)
    if notes:
        out["note"] = "; ".join(notes)
    out.setdefault("truncated", False)
    return fit(out, limit)


# -------------------------------------------------------------------- mlview_issues
def issues_payload(
    graph: Dict[str, Any],
    min_severity: str = "low",
    min_confidence: float = 0.0,
    codes: Optional[Sequence[str]] = None,
    limit: int = 20,
    graph_path: Optional[str] = None,
    limit_bytes: int = LIMIT_BYTES,
    scope: Optional[str] = None,
    extra_notes: Sequence[str] = (),
    group_by: Optional[str] = None,
    known_codes: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """The `mlview_issues` result: counts plus the ranked, filtered issue rows.

    Raises ``ValueError`` when ``min_severity`` is not one of low/medium/high —
    a typo must not quietly widen the filter to everything.

    With ``scope`` set, ``graph`` is expected to be the PROJECTION and only the
    retained findings are listed; the selector is echoed and the filtered-view
    note is added, so "3 issues" cannot be read as "this project has 3 issues".

    ``limit`` is a BOUND, not an enum: out of range is clamped to the nearest legal
    value and the note says it moved (`clamp_limit`), the way `depth` already was.
    ``known_codes`` is optional and used only for the note: with it, a `code` entry
    that names no rule is reported as a typo rather than answering with an empty
    list a caller cannot tell from a clean project.

    With ``group_by`` set (RAIL-GROUP) the surviving rows are folded into one row
    per rule / file / severity and ``issues`` is omitted: eleven codes repeated ten
    times is one answer, not a hundred and ten, and the fold happens BEFORE the
    4 KB budget sheds anything. The note says the rows were folded and not
    filtered, so a grouped answer is never read as a shorter finding list.
    """
    if min_severity is None:
        min_severity = "low"
    if min_severity not in SEVERITY_ORDER:
        _reject("minSeverity", min_severity, tuple(SEVERITY_ORDER))
    floor = SEVERITY_ORDER[min_severity]
    wanted = {c.strip().upper() for c in (codes or []) if c and c.strip()}

    counts = {"low": 0, "medium": 0, "high": 0}
    suppressed = 0
    baselined = 0
    rows: List[Dict[str, Any]] = []

    for issue in graph.get("issues", []):
        if issue.get("suppressed"):
            suppressed += 1
            continue
        # CI-ADOPT: a baselined finding is MARKED, never deleted — it is still in the
        # document, and `mlview issues --show-suppressed` still lists it. Here it is
        # excluded from the rows and from the counts for the same reason the CLI
        # excludes it from `--fail-on`: the ratchet says it was already known.
        if issue.get("baselined"):
            baselined += 1
            continue
        severity = issue.get("severity", "low")
        if severity in counts:
            counts[severity] += 1
        if SEVERITY_ORDER.get(severity, 0) < floor:
            continue
        if float(issue.get("confidence", 0.0)) < min_confidence:
            continue
        if wanted and issue.get("code") not in wanted:
            continue
        loc = issue.get("loc") or {}
        rows.append(
            {
                "id": issue.get("id"),
                "code": issue.get("code"),
                "severity": severity,
                "confidenceBucket": issue.get("confidenceBucket"),
                "title": issue.get("title"),
                "message": issue.get("message"),
                "fixHint": issue.get("fixHint"),
                "file": loc.get("file"),
                "line": loc.get("line"),
                # CI-ADOPT: present only on an attributed run. `new` = inside an added
                # hunk, `touched` = a changed file (or a related location inside a
                # hunk), `existing` = neither.
                **({"change": issue["change"]} if issue.get("change") else {}),
                "related": [
                    {"role": r.get("role"), "file": r.get("file"), "line": r.get("line")}
                    for r in (issue.get("relatedLocs") or [])
                ],
            }
        )

    # RAIL-GROUP: fold BEFORE the row limit and before `fit`, or the group counts
    # would describe the rows that survived a cap rather than the findings.
    groups: Optional[List[Dict[str, Any]]] = None
    mode = None
    if group_by is not None:
        # A blank or misspelled mode is a caller mistake, exactly like a bad
        # minSeverity: coercing it to "no grouping" would answer a different
        # question in the shape the caller asked for, which is undetectable.
        mode = str(group_by).strip().lower()
        if mode not in GROUP_BY_MODES:
            _reject("groupBy", group_by, GROUP_BY_MODES)
        groups = group_issues(rows, mode)

    matched = len(rows)
    limit, limit_note = clamp_limit(limit)
    rows = rows[:limit]

    # An empty list is the payload a model is most likely to read as "nothing
    # here", so every reason it could be empty has to be sayable. `code` is the
    # one filter whose value can be nonsense: a severity or a groupBy outside the
    # enum is already rejected outright, and a real rule that simply found
    # nothing is a fact about the project, not a mistake.
    code_note = None
    if wanted:
        known = {str(c).strip().upper() for c in known_codes} if known_codes is not None else None
        parts = []
        unknown = sorted(c for c in wanted if known is not None and c not in known)
        if unknown:
            parts.append("%s names no rule in this analyzer" % ", ".join(unknown))
        if not matched:
            parts.append(
                "no finding matched code=%s (%d in this analysis)"
                % (sorted(wanted), sum(counts.values()))
            )
        code_note = "; ".join(parts) or None
    workspace = graph.get("workspace") or {}
    files_analyzed = int(workspace.get("filesAnalyzed") or 0)
    files_failed = int(workspace.get("filesFailed") or 0)
    notebooks_skipped = int(workspace.get("notebooksSkipped") or 0)
    out: Dict[str, Any] = {
        "countBySeverity": counts,
        "suppressedCount": suppressed,
        **({"baselinedCount": baselined} if baselined else {}),
        # Without these three, "0 issues" from an empty directory, from a directory
        # whose every file failed to parse, and from genuinely clean code are the
        # same payload — and the command body turns that into a clean bill of health.
        "filesAnalyzed": files_analyzed,
        "filesFailed": files_failed,
        "notebooksSkipped": notebooks_skipped,
        "truncated": False,
    }
    if groups is None:
        out["issues"] = rows
    else:
        out["groupBy"] = mode
        out["groups"] = groups
    diagnostics = diagnostics_summary(graph)
    if diagnostics:
        out["diagnostics"] = diagnostics
    # ROADMAP COVERAGE: see `analyze_payload`; the tally cannot carry a rule code.
    coverage = coverage_notes(graph)
    if coverage:
        out["coverage"] = coverage
    notes = [n for n in extra_notes if n]
    if code_note:
        # `code` filters the rows BEFORE they are folded, so this sentence is true
        # of a grouped answer too.
        notes.append(code_note)
    if limit_note and groups is None:
        # ...whereas `limit` caps only the flat list, which a grouped payload does
        # not carry. Saying "1 was used" beside eleven groups would describe a cut
        # that did not happen, which is the failure this note exists to prevent.
        notes.append(limit_note)
    if groups is not None:
        notes.append(group_note(out["groupBy"], groups, matched))
    if scope:
        out["scope"] = scope
        notes.append(scopes.filtered_view_note(scope))
    blind = _coverage_note(coverage)
    if blind:
        notes.insert(0, blind)
    note = _corpus_note(files_analyzed, files_failed, diagnostics)
    if note:
        notes.insert(0, note)
    if notes:
        out["note"] = "; ".join(notes)
    if graph_path:
        out["graphPath"] = graph_path
    return fit(out, limit_bytes)


# --------------------------------------------------------------------- mlview_graph
def graph_payload(
    graph: Dict[str, Any],
    fmt: str,
    scope: Optional[str],
    depth: Optional[int] = None,
    renderers: Optional[Dict[str, Any]] = None,
    graph_path: Optional[str] = None,
    limit_bytes: int = LIMIT_BYTES,
) -> Dict[str, Any]:
    """The `mlview_graph` result: ``{format, content, scope, graphPath}``.

    ``renderers`` supplies ``{"mermaid": fn, "text": fn}`` so this stays testable
    without importing the analyzer's emitters.

    ``scope`` accepts the two catalogue values — ``"stages"`` (one row per lane)
    and ``"units"`` (the scopable-unit menu) — plus the whole CONTRACTS 11.1
    selector grammar, which is applied by ``mlview.core.project``: the one
    projection, so the CLI, the report, the webview and this tool cannot drift.

    Raises ``ValueError`` for an unrecognized ``fmt`` or ``scope`` rather than
    coercing: a silent fall back to mermaid, or to the whole graph, comes back
    labelled as if it were what the caller asked for.
    """
    if fmt is None:
        fmt = "mermaid"
    fmt = str(fmt).strip().lower() or "mermaid"
    if fmt not in GRAPH_FORMATS:
        _reject("format", fmt, GRAPH_FORMATS)
    renderers = renderers or {}
    scope = (scope or "").strip() or None
    depth, depth_note = scopes.clamp_depth(depth)

    view = graph
    scope_label = "all"
    notes: List[str] = []
    unit_rows: Optional[List[Dict[str, Any]]] = None
    if depth_note:
        notes.append(depth_note)

    if scope in scopes.CATALOG_SCOPES:
        scope_label = scope
        if scope == "units":
            unit_rows = scopes.catalog_rows(graph)
    elif scope is not None:
        parsed = scopes.parse(scope, depth)
        if parsed.kind == "stage":
            row = next(
                (r for r in graph.get("stages", []) if r.get("id") == parsed.target), None
            )
            if row is not None and not row.get("present"):
                notes.append(
                    "stage %r was not detected in this project, so the diagram is "
                    "empty; that absence is itself a finding" % parsed.target
                )
        if not parsed.is_all:
            view = scopes.project(graph, parsed)
            scope_label = parsed.spec
            if (view.get("view") or {}).get("empty"):
                notes.append(
                    "%s matched no nodes; the whole graph has %d — widen the "
                    "selector, or call scope='units' to see what is scopable"
                    % (scope_label, len(graph.get("nodes", [])))
                )

    if scope_label not in ("all",) + scopes.CATALOG_SCOPES:
        # The diagram body is a FILTERED view: its per-stage node counts describe
        # this scope only. Say so, so a narrowed call cannot be read as a
        # project-wide statement about which stages exist.
        notes.append(scopes.filtered_view_note(scope_label))
        # ...and carry the one project-level fact a *clipped* body can lose. The
        # renderers print their absence line last, so a scope whose diagram
        # overflows the 4 KB budget used to drop it silently — and `note` is a
        # PROTECTED key that neither the clip nor `fit` can shed.
        absent = [
            r.get("id") for r in graph.get("stages", [])
            if r.get("id") and not r.get("present")
        ]
        if absent:
            notes.append(
                "absent from the whole project (a project-level fact, unrelated "
                "to this scope): %s" % ", ".join(absent)
            )

    raw = ""
    if scope_label == "stages":
        if fmt == "json":
            raw = json.dumps(
                [
                    {
                        "stage": s.get("id"),
                        "label": s.get("label"),
                        "nodeCount": s.get("nodeCount", 0),
                        "present": bool(s.get("present")),
                        "maxSeverity": s.get("maxSeverity"),
                    }
                    for s in graph.get("stages", [])
                ],
                ensure_ascii=False,
            )
        elif fmt == "text":
            raw = stage_summary_text(graph)
        else:
            raw = stage_summary_mermaid(graph)
    elif scope_label == "units":
        raw = ""  # rendered inside the budget walk, which sheds whole rows
    elif fmt == "text":
        raw = renderers["text"](view)
    elif fmt == "mermaid":
        raw = renderers["mermaid"](view)

    note = "%% truncated - read the full graph at %s" % (graph_path or "<graphPath>")
    if fmt in ("text", "json"):
        note = "... truncated - read the full graph at %s" % (graph_path or "<graphPath>")

    def assemble(
        content: str, clipped: bool, extra: Sequence[str] = ()
    ) -> Dict[str, Any]:
        built: Dict[str, Any] = {
            "format": fmt,
            "scope": scope_label,
            "content": content,
            "truncated": clipped,
        }
        all_notes = list(notes) + [n for n in extra if n]
        if all_notes:
            built["note"] = "; ".join(all_notes)
        if graph_path:
            built["graphPath"] = graph_path
        return built

    # The content is nested INSIDE a JSON string, so every quote in it costs two
    # bytes in the assembled payload. That inflation cannot be predicted from the
    # raw length, so the budget is walked down until the payload really fits
    # rather than computed once and hoped for.
    budget = limit_bytes - 256
    out = assemble(raw, False)
    for _ in range(16):
        extra: List[str] = []
        if unit_rows is not None:
            content, kept_rows, total_rows = scopes.catalog_content(
                unit_rows, fmt, budget
            )
            clipped = kept_rows < total_rows
            if clipped:
                # `note` is a PROTECTED key, so this sentence survives both the
                # clip above and `fit` below — the shed rows cannot leave without
                # the payload saying how many went and where the rest are.
                extra.append(scopes.catalog_clipped_note(kept_rows, total_rows))
        elif fmt == "json" and scope_label != "stages":
            content, clipped = json_index(view, budget)
        else:
            content, clipped = clip_text_lines(raw, budget, note)
        out = assemble(content, clipped, extra)
        if payload_size(out) <= limit_bytes:
            return out
        budget = int(budget * 0.75)
    return fit(out, limit_bytes)


# ------------------------------------------------------------------- mlview_explain
def explain_node_payload(
    graph: Dict[str, Any],
    node_id: str,
    source_lines: Optional[List[str]] = None,
    graph_path: Optional[str] = None,
    max_source_lines: int = 60,
    limit_bytes: int = LIMIT_BYTES,
) -> Dict[str, Any]:
    """The `mlview_explain` node result: record, edges, issues, evidence, source."""
    node = next((n for n in graph.get("nodes", []) if n.get("id") == node_id), None)
    if node is None:
        raise ValueError(
            "no node %r in this graph; run mlview_analyze first, or pass the "
            "graphPath it returned" % node_id
        )
    loc = node.get("loc") or {}

    def _edge_row(edge: Dict[str, Any], other_key: str) -> Dict[str, Any]:
        other = next(
            (n for n in graph.get("nodes", []) if n.get("id") == edge.get(other_key)), {}
        )
        return {
            "kind": edge.get("kind"),
            "label": edge.get("label"),
            "nodeId": edge.get(other_key),
            "node": other.get("label"),
            "line": (edge.get("loc") or {}).get("line"),
        }

    incoming = [_edge_row(e, "source") for e in graph.get("edges", []) if e.get("target") == node_id]
    outgoing = [_edge_row(e, "target") for e in graph.get("edges", []) if e.get("source") == node_id]

    issue_ids = set(node.get("issueIds") or [])
    issues = [
        {
            "code": i.get("code"), "severity": i.get("severity"), "title": i.get("title"),
            "message": i.get("message"), "fixHint": i.get("fixHint"),
            "line": (i.get("loc") or {}).get("line"),
        }
        for i in graph.get("issues", [])
        if i.get("id") in issue_ids
    ]

    source = ""
    if source_lines:
        start = max(1, int(loc.get("line", 1)))
        end = min(len(source_lines), max(start, int(loc.get("endLine", start))))
        if end - start + 1 > max_source_lines:
            end = start + max_source_lines - 1
        source = "\n".join(
            "%5d| %s" % (num, source_lines[num - 1].rstrip("\n"))
            for num in range(start, min(end, len(source_lines)) + 1)
        )

    out: Dict[str, Any] = {
        "nodeId": node_id,
        "kind": node.get("kind"),
        "level": node.get("level"),
        "stage": node.get("stage"),
        "label": node.get("label"),
        "sublabel": node.get("sublabel"),
        "qualname": node.get("qualname"),
        "fqn": node.get("fqn"),
        "framework": node.get("framework"),
        "file": loc.get("file"),
        "line": loc.get("line"),
        "endLine": loc.get("endLine"),
        "ghost": bool(node.get("ghost")),
        "dynamic": bool(node.get("dynamic")),
        "confidenceBucket": node.get("confidenceBucket"),
        "parent": node.get("parent"),
        "stageEvidence": [
            {"kind": e.get("kind"), "detail": e.get("detail"), "weight": e.get("weight")}
            for e in (node.get("stageEvidence") or [])
        ],
        "incoming": incoming,
        "outgoing": outgoing,
        "issues": issues,
        "source": source,
        "truncated": False,
    }
    if graph_path:
        out["graphPath"] = graph_path
    return fit(out, limit_bytes)


def explain_rule_payload(
    code: str,
    doc_text: Optional[str],
    spec: Optional[Dict[str, Any]] = None,
    doc_path: Optional[str] = None,
    limit_bytes: int = LIMIT_BYTES,
) -> Dict[str, Any]:
    """The `mlview_explain` rule result: the offline doc, or the registry record."""
    out: Dict[str, Any] = {"code": code, "truncated": False}
    if spec:
        out.update(
            {
                "severity": spec.get("severity"),
                "frameworks": list(spec.get("frameworks") or []),
                "tags": list(spec.get("tags") or []),
                "absence": bool(spec.get("absence")),
                "enabled": bool(spec.get("enabled", True)),
                "title": spec.get("title"),
                "why": spec.get("why"),
                "fixHint": spec.get("fix_hint") or spec.get("fixHint"),
            }
        )
    if doc_text:
        out["docPath"] = doc_path or ""
        out["doc"] = doc_text
    elif not spec:
        raise ValueError(
            "unknown rule code %r — call mlview_explain with a code the analyzer "
            "reported, or run `python -m mlview rules --list`" % code
        )
    else:
        out["doc"] = ""
        out["docNote"] = (
            "No offline doc page at docs/rules/%s.md yet; the registry record above "
            "is the authoritative description." % code
        )
    return fit(out, limit_bytes)


#: VIEW-07. What this server can and cannot produce, said in one sentence so the
#: model repeats a true thing when the user asks for "an image". The MCP host has
#: no renderer: the diagram's geometry exists only inside the viewer, so the honest
#: answer is the HTML file plus where its export menu lives.
EXPORT_HINT = (
    "SVG/PNG export is a viewer feature: open reportPath and use the report's "
    "export menu, or run 'MLView: Export Diagram as SVG'/'... as PNG' in VS Code. "
    "This tool writes HTML only."
)


def open_diagram_payload(
    report_path: str, report_url: str, opened: bool, note: Optional[str] = None,
    limit_bytes: int = LIMIT_BYTES, scope: Optional[str] = None,
) -> Dict[str, Any]:
    """The `mlview_open_diagram` result.

    With ``scope``, the written report still embeds the FULL graph and opens *at*
    that scope through the two root attributes (CONTRACTS 11.8), so the note says
    the picture is filtered while the file is not.

    ``exportHint`` (VIEW-07) is constant and always present: it is the one place a
    terminal host is told that a picture file is the viewer's job, so that asking
    for an SVG produces a path and an instruction rather than an invented file.
    """
    out: Dict[str, Any] = {
        "reportPath": report_path,
        "reportUrl": report_url,
        "opened": bool(opened),
        "exportHint": EXPORT_HINT,
        "truncated": False,
    }
    notes = [n for n in (note,) if n]
    if scope:
        out["scope"] = scope
        notes.append(scopes.filtered_view_note(scope))
    if notes:
        out["note"] = "; ".join(notes)
    return fit(out, limit_bytes)


__all__ = [
    # re-exported from mlview_budget so callers keep one import
    "LIMIT_BYTES", "PROTECTED_KEYS", "payload_size", "compact_size", "serialize",
    "fit", "clip_text_lines",
    # the accepted argument values, and the per-tool builders
    "SEVERITY_ORDER", "STAGE_IDS", "GRAPH_FORMATS", "scopes",
    "DEFAULT_ISSUE_LIMIT", "MIN_ISSUE_LIMIT", "DEFAULT_MAX_NODES",
    "clamp_limit", "max_nodes_note",
    "analyze_payload", "issues_payload", "graph_payload", "diagnostics_summary",
    "coverage_notes",  # re-exported from mlview_notes: the COVERAGE reader
    # re-exported from mlview_views so callers and tests keep one import
    "subgraph", "stage_scope_ids", "neighbourhood_ids",
    "explain_node_payload", "explain_rule_payload", "open_diagram_payload",
    "EXPORT_HINT",
]
