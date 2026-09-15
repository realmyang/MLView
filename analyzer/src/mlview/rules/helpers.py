"""Shared query helpers for rules.

Keeping the loop/callee walking here is what lets a rule stay 10-40 lines.
"""

from __future__ import annotations

import ast
from typing import Iterable, List, Optional, Set, Tuple

from .. import knowledge as K
from ..core.graph import Evidence, clamp_confidence
from ..ir import config_values as CV
from ..ir.model import CallSite, FunctionIR, LoopIR, ValueRef
from ..ir.provenance import DEFAULT_MAX_HOPS, Hop, extend
from ..ir.symbols import dotted_text

__all__ = [
    "within_loop", "loop_chain", "calls_in_loop", "calls_in_function",
    "with_role", "first_with_role", "arg_ref", "traced_arg", "reaches",
    "value_sources", "seed_calls", "is_seeded", "literal_of", "DATA_TAGS",
    "apply_config_derating", "kwarg_literal", "KWARG_ABSENT", "KWARG_RESOLVED",
    "KWARG_UNRESOLVED", "UNRESOLVED_KWARG_WEIGHT", "note_unresolved_kwarg",
]

#: The three states one keyword argument can be in (ANA-01 / ANA-03).
#:
#: Two of them used to be one. A rule that asked `call.kwargs.get("shuffle")`
#: and compared the answer to a string treated *"the author never wrote this
#: keyword"* and *"the author wrote it and the analyzer could not read the
#: expression"* as the same fact, and then published a claim about the first
#: while looking at the second: `reshuffle_each_iteration=get_flag()` produced a
#: **high**-severity `certain` finding whose evidence read "shuffle() does not
#: pass reshuffle_each_iteration=False" about a line that passes exactly that.
#: A high-severity false positive on correct code is the one failure this
#: product cannot afford, so the distinction lives in one helper that every
#: literal-dependent rule reads.
KWARG_ABSENT = "absent"
KWARG_RESOLVED = "resolved"
KWARG_UNRESOLVED = "unresolved"

#: The tags a *projection* may carry across. Selecting columns out of a frame
#: does not change what the rows are; selecting a model out of a dict would be
#: an entirely different claim, so only the data tags travel this way.
DATA_TAGS = ("RAW_DATA", "FEATURES", "TARGET", "TRAIN_SPLIT", "VAL_SPLIT",
             "TEST_SPLIT")
#: How many nested subscripts a projection is followed through.
_MAX_PROJECTION_DEPTH = 3


def literal_of(ctx, expr, scope, module) -> Optional[str]:
    """The literal a name resolves to, following one workspace import.

    `from config import NUM_WORKERS` leaves no binding in the importing module,
    so a rule that wants the *value* of `num_workers=NUM_WORKERS` has to walk
    the import table into `config.py` and read the constant there.

    ANA-10 adds one lookup and no rule changes. `dotted_text` answers `None`
    for `CFG["workers"]`, so a subscript chain is spelled as the dotted path
    `ir.config_values` bound its leaves under - `CFG["data"]["workers"]` and
    `cfg.data.workers` are one name here, because they are one value in every
    container a Python config is actually written as. When the value that comes
    back was resolved out of a config container, the read is recorded on `ctx`
    and `apply_config_derating` turns it into one visible evidence factor on
    whatever finding used it: a config read may never mint a `certain` finding.
    """
    if expr is None:
        return None
    if isinstance(expr, ast.Constant):
        from ..ir.scopes import literal_str
        return literal_str(expr)
    name = dotted_text(expr) or CV.path_name(expr)
    if not name:
        return None
    ref = ctx.binding_of(name, scope)
    if ref is not None and ref.literal is not None:
        _note_config_read(ctx, ref, expr)
        return ref.literal
    symbols = getattr(module, "symbols", None)
    fqn = symbols.resolve(expr) if symbols is not None else None
    if not fqn:
        return None
    head, _dot, attr = fqn.rpartition(".")
    target = ctx.workspace.by_dotted.get(head)
    if target is None or target.module_scope is None:
        return None
    other = target.module_scope.bindings.get(attr)
    return other.literal if other is not None else None


def kwarg_literal(ctx, call: CallSite, key: str) -> Tuple[str, Optional[str]]:
    """`(state, literal)` for one keyword argument - three-way, never two.

    `call.kwargs` holds the constants the IR folded (and, since ANA-10, the
    ones a config container supplied); anything else has to go through
    `literal_of`, which is what `_int_kwarg` already did for `num_workers=` and
    what no other kwarg-reading rule did. The states are `KWARG_ABSENT` (the
    keyword is not written at all), `KWARG_RESOLVED` (with the literal), and
    `KWARG_UNRESOLVED` - the keyword is right there on the line and its value
    is not something a static reader can have.

    A rule must say something different in each of the three, because they are
    three different facts about the program in front of it.
    """
    node = call.kwarg_nodes.get(key)
    if node is None:
        return KWARG_ABSENT, None
    literal = call.kwargs.get(key)
    if literal is None:
        literal = literal_of(ctx, node, call.scope, call.module)
    if literal is None:
        return KWARG_UNRESOLVED, None
    return KWARG_RESOLVED, literal


#: What a keyword the analyzer could not read costs the finding that had to
#: reason around it. 0.6 takes MLV121's 0.95 prior to `possible` and MLV110's
#: 0.85 to `possible`: the pattern really is there, the value that decides
#: whether it is a defect is not, and a finding that says so out loud belongs
#: below `likely` - which is also, by H5's guardrail 3, below the floor where an
#: edit may be offered.
UNRESOLVED_KWARG_WEIGHT = 0.6
#: How many `config_unresolved` notes one module may carry, matching the cap
#: `core/config_nodes` already applies to the YAML notes.
_MAX_UNRESOLVED_NOTES = 3


def note_unresolved_kwarg(ctx, call: CallSite, key: str,
                          consequence: str = "") -> None:
    """Disclose one keyword argument that is written and cannot be read.

    The silence this replaces was the worst kind: the rule turned "I could not
    read this" into a positive claim about the value. Reported under the kind
    ANA-10 already reserved for a configuration MLView declined to resolve, so
    a host needs no new vocabulary.
    """
    relpath = call.loc.file
    seen = getattr(ctx, "_unresolved_kwarg_notes", None)
    if seen is None:
        seen = {}
        setattr(ctx, "_unresolved_kwarg_notes", seen)
    rows = seen.setdefault(relpath, [])
    if (call.loc.line, key) in rows:
        return
    rows.append((call.loc.line, key))
    if len(rows) > _MAX_UNRESOLVED_NOTES:
        return
    spec = getattr(ctx, "current_rule", None)
    ctx.diagnostics.append(
        _unresolved_diagnostic(relpath, call.loc.line, key, spec, consequence))


def _unresolved_diagnostic(relpath: str, line: int, key: str, spec,
                           consequence: str):
    from ..core.graph import Diagnostic
    return Diagnostic(
        kind="config_unresolved", file=relpath, line=line,
        ruleCode=spec.code if spec is not None else None,
        message=("`%s=` is passed at %s:%d and MLView could not resolve its "
                 "value, so %s reasoned about the call without it%s. This is a "
                 "gap in coverage, not a value of False."
                 % (key, relpath, line,
                    spec.code if spec is not None else "the rule",
                    (" - %s" % consequence) if consequence else "")))


def within_loop(loop: Optional[LoopIR], outer: LoopIR) -> bool:
    """True when `loop` is `outer` or nested inside it."""
    while loop is not None:
        if loop is outer:
            return True
        loop = loop.parent_loop
    return False


def loop_chain(loop: LoopIR) -> List[LoopIR]:
    """`loop` and every loop enclosing it, innermost first."""
    out: List[LoopIR] = []
    cur: Optional[LoopIR] = loop
    while cur is not None:
        out.append(cur)
        cur = cur.parent_loop
    return out


def calls_in_loop(ctx, loop: LoopIR, follow: bool = True) -> List[CallSite]:
    """Every call in a loop body, following one level of workspace calls."""
    out = [c for c in loop.module.calls if within_loop(c.loop, loop)]
    if follow:
        for call in list(out):
            target = ctx.follow_call(call)
            if target is not None:
                out.extend(target.calls)
    return out


def calls_in_function(ctx, func: FunctionIR, follow: bool = False) -> List[CallSite]:
    out = list(func.calls)
    if follow:
        for call in list(out):
            target = ctx.follow_call(call)
            if target is not None and target is not func:
                out.extend(target.calls)
    return out


def with_role(calls: Iterable[CallSite], *roles: str) -> List[CallSite]:
    wanted = set(roles)
    out = []
    for call in calls:
        for fqn in call.canonical_fqns or ():
            if K.role_of(fqn) in wanted:
                out.append(call)
                break
    return out


def first_with_role(calls: Iterable[CallSite], *roles: str) -> Optional[CallSite]:
    found = with_role(calls, *roles)
    found.sort(key=lambda c: (c.loc.file, c.loc.line, c.loc.col))
    return found[0] if found else None


def arg_ref(ctx, call: CallSite, index: int = 0) -> Tuple[Optional[str], Optional[ValueRef]]:
    """The name and binding of a positional argument, as of the call's own line.

    PUB-01. Without `at`, `binding_of` answers with the scope's **last** store
    for the name rather than the one that reaches this call. The measured cost
    was a high / `certain` MLV402 on yolov5's `BCEBlurWithLogitsLoss.forward`
    and on every focal-loss implementation written the same way:

        loss = self.loss_fcn(pred, true)     # line 26 - correct, raw logits
        pred = torch.sigmoid(pred)           # line 27 - rebinds AFTER the use

    and a message that gave the defect away - "its input comes from
    torch.sigmoid at m.py:17" for a use at m.py:16. REV-01 built the ordered
    lookup for exactly this; the argument reader simply never asked for it.
    """
    if index >= len(call.args):
        return None, None
    name = dotted_text(call.args[index])
    if not name:
        return None, None
    return name, ctx.binding_of(name, call.scope, at=call.loc.line,
                                in_loop=call.loop is not None)


def traced_arg(ctx, call: CallSite, index: int = 0
               ) -> Tuple[Optional[str], Optional[ValueRef]]:
    """`arg_ref`, plus DATAFLOW-IP's one-step **projection** read.

    `self.scaler.fit_transform(frame[FEATURES])` is how a DataModule is
    written, and `dotted_text` on a `Subscript` is `None`, so the fit site had
    no traced argument at all and MLV101 recorded a coverage gap instead of the
    high-severity leak that was really there. In `--dataflow ip` the subscript
    is followed to its base and the base's data tags are read, as one recorded
    hop: the finding is de-rated once for it and names it in its evidence, so
    the reader sees that the analyzer reasoned about `frame`, not about
    `frame[FEATURES]`.

    In `--dataflow local` this is exactly `arg_ref`, byte for byte.
    """
    name, ref = arg_ref(ctx, call, index)
    if ref is not None or getattr(ctx, "dataflow", "local") != "ip":
        return name, ref
    if index >= len(call.args):
        return name, ref
    found = _projection(ctx, call, call.args[index])
    # Falling back to `arg_ref`'s own answer matters: it is what a COVERAGE
    # note names. Returning `(None, None)` on a projection that found nothing
    # turned one honest note about `X` into two - one about `X` and one about
    # "the value" - which is noise dressed as candour.
    return found if found[1] is not None else (name, ref)


def _projection(ctx, call: CallSite, arg
                ) -> Tuple[Optional[str], Optional[ValueRef]]:
    """The tracked value a subscript expression is a projection of."""
    node, depth = arg, 0
    while isinstance(node, ast.Subscript) and depth < _MAX_PROJECTION_DEPTH:
        node, depth = node.value, depth + 1
    if depth == 0:
        return None, None
    name = dotted_text(node)
    if not name:
        return None, None
    ref = ctx.binding_of(name, call.scope, at=call.loc.line)
    if ref is None or not ref.has(*DATA_TAGS):
        return None, None
    hop = Hop(kind="projection", detail="a subscript of `%s`" % name,
              loc=ref.loc or call.loc)
    chain = extend(getattr(ref, "provenance", ()) or (), hop,
                   getattr(ctx.workspace, "ip_max_hops", DEFAULT_MAX_HOPS))
    if chain is None:
        return None, None            # the cap; stay silent rather than guess
    derived = ValueRef(name=name, scope=ref.scope, tags=ref.tags,
                       producer=ref.producer, loc=ref.loc, sources=ref.sources,
                       class_ir=ref.class_ir, is_config=ref.is_config,
                       via_fqns=ref.via_fqns, provenance=chain)
    # IP-01: the derived ref never went through `ctx.binding_of`, so it has to
    # declare its own hop or a rule reading it would pay nothing for the read.
    ctx.note_hops(derived, call.scope)
    return name, derived


def value_sources(ctx, name: str, scope, depth: int = 6) -> Set[str]:
    """Every name reachable backwards through the SSA-lite chain."""
    seen: Set[str] = set()
    frontier = [name]
    while frontier and depth > 0:
        depth -= 1
        nxt: List[str] = []
        for current in frontier:
            if current in seen:
                continue
            seen.add(current)
            ref = ctx.binding_of(current, scope)
            if ref is None:
                continue
            for source in ref.sources:
                if source not in seen:
                    nxt.append(source)
        frontier = nxt
    return seen


def reaches(ctx, name: str, scope, targets: Iterable[str], depth: int = 6) -> bool:
    """Does `name` derive from any of `targets` (by value identity)?"""
    wanted = {t for t in targets if t}
    if not wanted:
        return False
    if name in wanted:
        return True
    return bool(value_sources(ctx, name, scope, depth) & wanted)


def seed_calls(ctx) -> List[CallSite]:
    """Every call that actually seeds a random source."""
    out: List[CallSite] = []
    for call in ctx.calls_with_role("SEED"):
        fqn = call.fqn or ""
        if fqn.endswith("default_rng") or fqn.endswith("RandomState"):
            if not call.args and not call.kwarg_nodes:
                continue                    # unseeded generator
        out.append(call)
    return out


def is_seeded(ctx) -> bool:
    """A seed call anywhere, or any explicit `random_state=` / `generator=`."""
    if seed_calls(ctx):
        return True
    for relpath in sorted(ctx.modules):
        for call in ctx.modules[relpath].calls:
            for key in ("random_state", "generator", "seed", "random_seed"):
                node = call.kwarg_nodes.get(key)
                if node is None:
                    continue
                if isinstance(node, ast.Constant) and node.value is None:
                    continue
                return True
    return False


# ---------------------------------------------------------------------------
# ANA-10: what a config read costs the finding that used it
# ---------------------------------------------------------------------------
#: One recorded read: which rule made it, where in the source it was made, how
#: many issues the rule had already emitted, and what it costs.
_ConfigNote = Tuple[str, str, int, int, float, str, int]


def _note_config_read(ctx, ref, expr) -> None:
    """Record that the rule now running read a config-resolved literal.

    The read and the finding are joined by the **source range they share**:
    a rule reads `cfg["workers"]` out of a call and then anchors its finding on
    that same call, so an issue whose location (or one of its related
    locations) contains the read is the issue the read fed. Recording the
    issue count at read time keeps a later read from de-rating an earlier
    finding of the same rule.
    """
    read = CV.config_read_of(ref)
    spec = getattr(ctx, "current_rule", None)
    if read is None or spec is None:
        return
    line = getattr(expr, "lineno", None) or read.line
    notes = getattr(ctx, "config_reads", None)
    if notes is None:
        notes = []
        setattr(ctx, "config_reads", notes)
    notes.append((spec.code, read.file, int(line), len(ctx.issues),
                  read.weight, read.fact or read.detail, read.hops))


def _issue_spans(issue) -> List[Tuple[str, int, int]]:
    spans = [(issue.loc.file, issue.loc.line, max(issue.loc.line, issue.loc.endLine))]
    for related in issue.relatedLocs or ():
        if isinstance(related, dict) and related.get("file"):
            start = int(related.get("line", 0) or 0)
            end = int(related.get("endLine", start) or start)
            spans.append((related["file"], start, max(start, end)))
    return spans


def _kwarg_notes(ctx) -> List[_ConfigNote]:
    """The reads that never went through `literal_of` at all.

    A rule that asks *"was `shuffle=True` passed here?"* reads `call.kwargs`,
    and ANA-10 fills that dict from the container - so the read happens in the
    IR pass, before any rule runs, and there is no rule code and no ordering to
    key it by. The note is therefore attached to the **call site**: a finding
    anchored on a call whose keywords a container supplied is de-rated once.
    That over-approximates - the finding may have argued from a different
    keyword - and it over-approximates in the only safe direction, which is
    less confidence rather than more.
    """
    out: List[_ConfigNote] = []
    for relpath in sorted(getattr(ctx, "modules", None) or {}):
        for file, line, read in CV.kwarg_reads(ctx.modules[relpath]):
            out.append(("", file, int(line), 0, read.weight,
                        read.fact or read.detail, read.hops))
    return out


def _names(fact: str, issue) -> bool:
    """Does this read's dotted key appear in the finding's own message?"""
    key = fact.split("`")[1] if fact.count("`") >= 2 else ""
    if not key:
        return False
    leaf = key.rsplit(".", 1)[-1]
    return leaf in (issue.message or "") or key in (issue.message or "")


def _absence_codes() -> frozenset:
    """Rule codes declared `absence=True` - they conclude a call is missing."""
    from .registry import all_rules

    return frozenset(spec.code for spec in all_rules() if getattr(spec, "absence", False))


def apply_config_derating(ctx) -> None:
    """Charge every finding that used a config-resolved literal for the read.

    One factor per issue, never one per read: several reads out of the same
    container are not independent chances of being wrong, so the finding pays
    the **weakest** of them once and the detail names them all. Applied as an
    ordinary evidence factor - the number is visible in `issue.evidence` and
    the confidence is exactly the product it always was - so `MLV112` on
    `num_workers=CFG["workers"]` lands at `likely`, and no rule anywhere had
    to learn what a config container is.
    """
    notes: List[_ConfigNote] = list(getattr(ctx, "config_reads", None) or [])
    notes.extend(_kwarg_notes(ctx))
    if not notes:
        return
    absence_codes = _absence_codes()
    for index, issue in enumerate(ctx.issues):
        spans = _issue_spans(issue)
        matched = [n for n in notes
                   if (not n[0] or n[0] == issue.code) and index >= n[3]
                   and any(f == n[1] and start <= n[2] <= end
                           for f, start, end in spans)]
        # INFRA-13: an *absence* rule concludes that a call is not there. No
        # value of `args.lr` can make `zero_grad()` appear or disappear, and
        # MLV201 was paying x0.8 for a read that happened only because the
        # optimizer's construction site is one of the finding's related
        # locations - the difference between 0.36 and 0.288. A rule that did
        # not branch on the value does not pay for it; the read is still
        # charged when the finding's own message names the key, which is the
        # case where the value really was an operand.
        if matched and issue.code in absence_codes:
            matched = [n for n in matched if _names(n[5], issue)]
        if not matched:
            continue
        weight = min(n[4] for n in matched)
        # ANA-05: the key the finding is actually about comes first. The reads
        # arrive in dictionary order, so an MLV110 finding entirely about
        # `shuffle` opened its explanation with `args.workers` - correct
        # arithmetic, wrong sentence, and it is the sentence a reader sees in
        # the Problems panel. The rationale is stated ONCE at the end rather
        # than once per key, which is what made a two-key call site produce a
        # 300-character row for a one-line finding.
        facts: List[str] = []
        for note in sorted(matched, key=lambda n: (not _names(n[5], issue), n[2])):
            if note[5] not in facts:
                facts.append(note[5])
        detail = "; ".join(facts + [CV.derating_rationale(max(n[6] for n in matched))])
        if any(e.detail == detail for e in issue.evidence):
            continue                     # already charged; never charge twice
        issue.evidence.append(Evidence(
            kind="context_confirmed", detail=detail, weight=weight))
        issue.confidence = clamp_confidence(issue.confidence * weight)
