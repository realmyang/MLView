"""How a rule *says* something: `ctx.issue(...)`, and everything it costs.

One method does the work, and almost all of it is refusal and de-rating: an
issue with no anchor is dropped, an issue whose evidence walked a long
provenance chain loses confidence, an issue in dynamic scope is capped, a
duplicate id is made unique, and an issue a gate suppressed becomes a
diagnostic instead of a finding - so the Problems panel never goes quiet
without saying why.

`fix` and `ghost` are the two smaller writes: a suggested edit on a finding,
and a node the analyzer had to invent to have something to point at.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..core.graph import Diagnostic, Edge, Evidence, Issue, Node, SEVERITY_RANK
from ..core.ids import issue_id, node_id
from ..ir.model import Loc, ScopeIR
from .confidence import (cap_severity, compute_confidence,
                         interprocedural_evidence, normalize_evidence,
                         notebook_evidence)
from .fixes import FIXABLE_BUCKETS, Fix, build_fix


_GHOST_SLUG = str.maketrans({" ": "_", "(": "", ")": "", ".": "_", "-": "_", "/": "_"})


class IssueMixin:
    """`GraphContext`'s write side. Mixed in, never instantiated."""

    def fix(self, module, title: str, edits: Sequence[Any],
            safety: str = "needs-review") -> Optional[Fix]:
        """Build one validated `Issue.fix` candidate, or `None` (H5).

        The single door a rule may build an edit through, exactly as `issue()`
        is the only door it may publish a finding through. Everything a rule
        could get wrong is checked here rather than in the rule: an edit that
        no builder could compute (`None` in `edits`), an edit that reaches
        outside `module`, and - the one that matters - an edit that does not
        re-parse. A candidate that fails any of them is dropped and the finding
        ships with its prose `fixHint` alone.

        Returning a candidate is not the same as publishing it: `issue()`
        drops the fix when the computed confidence lands below `likely`, so a
        rule can never talk the engine into offering an edit for a finding it
        is not sure about.
        """
        return build_fix(module, title, safety, list(edits))

    def ghost(self, kind: str, parent_node: Node, label: str,
              fqn: Optional[str] = None, confidence: float = 0.9) -> Node:
        """Declare a REQUIRED-BUT-ABSENT step in its correct slot (A9)."""
        slug = label.translate(_GHOST_SLUG).strip("_").lower() or "missing"
        qualname = "%s.__ghost_%s" % (parent_node.qualname, slug)
        node = Node(
            id=node_id(parent_node.loc.file, qualname, kind), kind=kind, level="op",
            stage=parent_node.stage, label=label, qualname=qualname,
            loc=parent_node.loc, sublabel="missing", fqn=fqn,
            framework=parent_node.framework, parent=parent_node.id, ghost=True,
            dynamic=parent_node.dynamic, confidence=confidence,
            stageEvidence=[Evidence("context_confirmed",
                                    "ghost slot for %s" % (self.current_rule.code
                                                           if self.current_rule else "a rule"),
                                    1.0)])
        existing = self.graph.node_by_id(node.id)
        if existing is not None:
            return existing
        self.graph.nodes.append(node)
        self.ghosts.append(node)
        if self._nodes_by_file is not None:
            self._nodes_by_file.setdefault(node.loc.file, []).append(node)
        return node

    def issue(self, title: Optional[str] = None, message: str = "", why: Optional[str] = None,
              fix_hint: Optional[str] = None, loc: Optional[Loc] = None,
              node_ids: Sequence[Any] = (), edge_ids: Sequence[Any] = (),
              related: Sequence[Any] = (), evidence: Sequence[Any] = (),
              tags: Sequence[str] = (), dynamic: Optional[bool] = None,
              stage: Optional[str] = None, qualname: Optional[str] = None,
              severity: Optional[str] = None, wrapper_gated: bool = False,
              fix: Optional[Fix] = None) -> Issue:
        """Build one issue: confidence, severity cap, suppression, ids.

        `severity` may only **lower** the declared severity (MLV301's
        "drop to medium when the architecture cannot be resolved" refinement);
        a rule can never grade itself up, and the absence cap still applies on
        top of whatever it asks for.

        `fix` is H5's opt-in structured edit, built by `ctx.fix`. It is
        attached only when the computed confidence lands in `certain` or
        `likely`: below that the finding itself is a question, and a question
        does not get to edit somebody's training loop. The rule is not
        consulted about that - it hands over a candidate and this decides.
        """
        spec = self.current_rule
        if spec is None:  # pragma: no cover - registry always sets it
            raise RuntimeError("ctx.issue() called outside a rule")
        nodes = [self._as_node(n) for n in node_ids]
        nodes = [n for n in nodes if n is not None]
        edges = [self._as_edge(e) for e in edge_ids]
        edges = [e for e in edges if e is not None]
        primary = nodes[0] if nodes else None
        if loc is None and primary is not None:
            loc = primary.loc
        if loc is None:
            raise ValueError("%s: an issue needs a loc" % spec.code)

        ev = normalize_evidence(evidence)
        # IP-01: every finding derived from a value that crossed an object
        # boundary pays for the crossing, whether or not its rule remembered to
        # ask. Before this, only `r_leakage` called `ctx.hops(...)`, so MLV111,
        # MLV114 and MLV301/302 published cross-object claims at `certain` with
        # evidence reading `dataflow_direct 1.0` - "the tag was established
        # here" - about a tag that arrived from another file, and with no
        # RelatedLoc the reader could open to check. "Never `certain`" is only
        # arithmetic if the arithmetic is unavoidable, so it happens here,
        # ahead of `compute_confidence`, and not in each rule.
        hop_ev, hop_related = self._hop_factors(loc, ev)
        ev = ev + hop_ev
        related = list(related) + hop_related
        # NB: a finding inside a notebook says which cell it is in, and an
        # order-sensitive rule in an out-of-order notebook is de-rated by the
        # weight of that same factor. Appended last so the evidence a rule
        # wrote is untouched, and reached only when the run asked for
        # notebooks - no `.py` finding ever gains a factor here.
        nbmap = self._notebooks.get(loc.file) if self._notebooks else None
        if nbmap is not None:
            ev = ev + notebook_evidence(nbmap, loc.line, spec.code)
        if dynamic is None:
            dynamic = bool(primary.dynamic) if primary is not None else False
        wrapper_present = bool(self.wrappers_for(loc.file))
        # `wrapper_gated` lets a rule that is not an *absence* rule opt into the
        # same x0.4 de-rating instead of deleting its findings outright.
        gate = bool((spec.absence or wrapper_gated) and wrapper_present)
        confidence = compute_confidence(spec.base_prior, ev, dynamic=dynamic,
                                        wrapper_gate=gate)
        declared = spec.severity
        if severity in SEVERITY_RANK and SEVERITY_RANK[severity] < SEVERITY_RANK[declared]:
            declared = severity
        severity = cap_severity(declared, spec.absence, not dynamic, wrapper_present)
        if gate:
            self._note_gate(spec.code, self.wrappers_for(loc.file))

        # ROB-03 / NLP-09. `Issue.id` must be unique inside one document
        # (CONTRACTS section 0 invariant 1) *and* content-addressed, never
        # line-derived (the same section, and `test_id_stability.py`). The old
        # fallback - `loc.symbol` - collapsed two findings of one rule on two
        # call sites of the same criterion into one id, and every host keyed on
        # the id (Problems reveal, `applyFix`, `mlview diff`, the baseline)
        # then treated two distinct high-severity findings as one. The
        # enclosing scope's qualname separates the overwhelmingly common case
        # (a train path and an eval path); `_unique_id` is the last-resort
        # tiebreak for two findings that are genuinely indistinguishable by
        # content, and it keeps the invariant true by construction.
        qual = qualname or (primary.qualname if primary is not None
                            else self._anchor_qualname(loc))
        issue = Issue(
            id=self._unique_id(spec.code, loc, qual),
            code=spec.code, ruleVersion=spec.rule_version, severity=severity,
            confidence=confidence,
            title=title or spec.title or spec.code,
            message=message or title or spec.title or spec.code,
            why=why or spec.why or "",
            fixHint=fix_hint or spec.fix_hint or "See the rule documentation.",
            loc=loc,
            stage=stage or (primary.stage if primary is not None else "train"),
            relatedLocs=[_as_related(r) for r in related],
            nodeIds=[n.id for n in nodes],
            edgeIds=[e.id for e in edges],
            frameworks=tuple(spec.frameworks),
            tags=tuple(tags) or tuple(spec.tags),
            evidence=list(ev),
            suppressed=self.suppressor.is_suppressed(spec.code, loc.file, loc.line),
            docs="docs/rules/%s.md" % spec.code)
        # `issue.confidenceBucket`, never `bucket_for(confidence)`: the bucket
        # the user is shown is computed off the *clamped* value, and a gate that
        # reads a different number from the one on screen is a gate nobody can
        # reason about.
        if fix is not None and issue.confidenceBucket in FIXABLE_BUCKETS:
            issue.fix = fix
        for node in nodes:
            if issue.id not in node.issueIds:
                node.issueIds.append(issue.id)
        for edge in edges:
            if issue.id not in edge.issueIds:
                edge.issueIds.append(issue.id)
        self.issues.append(issue)
        self.graph.issues.append(issue)
        return issue

    # -------------------------------------------------------------- helpers
    def _anchor_qualname(self, loc: Loc) -> str:
        """`<innermost enclosing scope>.<symbol>` for a finding with no node.

        A rule that anchors on a bare call site (MLV401/MLV402 among them)
        hands `issue()` a `loc` and nothing else. Naming only `loc.symbol`
        made `criterion` the whole identity of the finding, so the same
        criterion called on the training path and on the evaluation path
        minted one id twice. The scope qualname is structural, not positional:
        it survives an edit above the function exactly as a node qualname does.
        """
        symbol = loc.symbol or ""
        module = self.modules.get(loc.file)
        if module is None:
            return symbol
        best: Optional[ScopeIR] = None
        for scope in module.scopes:
            if scope.kind == "module" or not _scope_contains(scope, loc):
                continue
            span = getattr(scope, "loc", None)
            if span is None:
                continue
            if best is None or span.line > (best.loc.line if best.loc else -1):
                best = scope
        if best is None:
            return symbol
        return "%s.%s" % (best.qualname, symbol) if symbol else best.qualname

    def _unique_id(self, code: str, loc: Loc, qual: str) -> str:
        """`issue_id` with the document-uniqueness invariant enforced.

        Two findings that agree on code, file, scope and symbol are the one
        case no content-addressed scheme can separate without reading the
        line - so the tiebreak is an occurrence counter on the symbol
        component, deterministic for a given document because rules run in
        registry order and each emits in source order. Everything else keeps
        the §0 formula untouched.
        """
        symbol = loc.symbol or ""
        base = issue_id(code, loc.file, qual, symbol)
        if base not in self._minted_ids:
            self._minted_ids.add(base)
            return base
        for nth in range(2, 1000):
            candidate = issue_id(code, loc.file, qual, "%s#%d" % (symbol, nth))
            if candidate not in self._minted_ids:
                self._minted_ids.add(candidate)
                return candidate
        return base  # pragma: no cover - 1000 identical findings in one scope

    def _hop_factors(self, loc: Loc, evidence: Sequence[Any]
                     ) -> Tuple[Tuple[Any, ...], List[Any]]:
        """The `cross_file` factor and hop `RelatedLoc`s this finding owes (IP-01).

        A read counts for a finding when the rule that made it is the rule
        emitting, and the finding is anchored **inside the scope the value was
        read in**. That is the same "the two share a source range" join
        `apply_config_derating` uses, one level coarser because a hop's own
        location is in the caller's file and can never appear in the finding's
        own range - which is precisely why the reader needs the RelatedLoc.

        One factor per finding, never one per read: several reads out of the
        same object are not independent chances of being wrong, so the finding
        pays the **longest** chain once. A rule that already asked for the
        factor itself (`r_leakage`) is left exactly as it was.
        """
        if not self._hop_reads or self.current_rule is None:
            return (), []
        if any(getattr(e, "kind", "") == "cross_file" for e in evidence):
            return (), []                # the rule paid for it already
        code = self.current_rule.code
        worst = None
        for read_code, scope, ref in self._hop_reads:
            if read_code != code or not _scope_contains(scope, loc):
                continue
            if worst is None or len(ref.provenance) > len(worst.provenance):
                worst = ref
        if worst is None:
            return (), []
        return tuple(interprocedural_evidence(worst)), self.hop_related(worst)

    def _as_node(self, value) -> Optional[Node]:
        if isinstance(value, Node):
            return value
        if isinstance(value, str):
            return self.graph.node_by_id(value)
        return None

    def _as_edge(self, value) -> Optional[Edge]:
        if isinstance(value, Edge):
            return value
        if isinstance(value, str):
            for edge in self.graph.edges:
                if edge.id == value:
                    return edge
        return None

    def _note_gate(self, code: str, wrappers: Sequence[str] = ()) -> None:
        if code in self._gate_codes:
            return
        self._gate_codes.append(code)
        label = ", ".join(wrappers or self.workspace.wrappers)
        for diagnostic in self.diagnostics:
            if diagnostic.kind == "framework_suppressed":
                codes = list(diagnostic.codes or ())
                if code not in codes:
                    codes.append(code)
                diagnostic.codes = sorted(codes)
                diagnostic.count = len(codes)
                diagnostic.message = _gate_message(label, len(codes))
                return
        self.diagnostics.append(Diagnostic(
            kind="framework_suppressed",
            message=_gate_message(label, 1),
            codes=[code], count=1))


def _scope_contains(scope: ScopeIR, loc: Loc) -> bool:
    """Is `loc` inside `scope`? (IP-01's join.)

    A module scope owns its whole file; a class or function scope owns the
    lines of its `def`. `scope.loc` is optional, so a scope with no location
    falls back to the file test alone - over-approximating in the direction
    that costs confidence rather than the one that invents it.
    """
    if scope is None or loc is None:
        return False
    if getattr(scope, "module", None) != getattr(loc, "file", None):
        return False
    span = getattr(scope, "loc", None)
    if span is None or scope.kind == "module":
        return True
    end = max(getattr(span, "endLine", span.line) or span.line, span.line)
    return span.line <= loc.line <= end


def _gate_message(label: str, count: int) -> str:
    """The `framework_suppressed` chip text - counting every gated rule."""
    return ("Training loop handled by %s - %d rule(s) de-rated to speculative."
            % (label, count))


def _as_related(item) -> Dict[str, Any]:
    """Accept `(role, loc)` / `(role, loc, message)` / a ready dict."""
    if isinstance(item, dict):
        return item
    role = item[0]
    loc = item[1]
    message = item[2] if len(item) > 2 else None
    return loc.related_dict(role, message)
