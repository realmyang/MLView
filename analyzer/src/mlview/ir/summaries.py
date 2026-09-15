"""DATAFLOW-IP - the interprocedural summary pass.

Recall stops at the object boundary, and the object boundary is where real ML
code lives. `r_leakage.py` gates MLV101 on `ref.has("FEATURES", "RAW_DATA")`
and the tag never crossed `__init__`, so a Lightning `DataModule` that fits a
`StandardScaler` on the whole feature matrix before `random_split`, and a
research script that fits a `MinMaxScaler` over a whole series before a
chronological cut, were both **silent** - two genuine high-severity leaks from
one missing pass.

This module is that pass. It runs after `propagate_parameters`, iterates to a
fixed point, and carries three summaries plus the provenance that makes each
one auditable:

**CONSTRUCTOR.** For every workspace class, the argument tags at every
construction site are mapped onto `__init__`'s parameters and then onto any
`self.<attr>` assigned directly from such a parameter, unioned into the class
scope's bindings - which is where `bindings._store` already redirects `self.*`
and where a sibling method's `binding_of("self.features", ...)` already looks.

**RETURN.** `ir.returns` is run to its own fixed point instead of the fixed two
levels, so a tag flows out through a chain of helpers rather than one of them.

**METHOD-ARG.** The argument-to-parameter summary plain functions already get
from `propagate_parameters`, applied to **bound-method** call sites now that
ANA-2 resolves them - and applied with **intersection**, not first-wins: a
helper called from two sites with different tag sets keeps only what both
sites agree on. Union there is exactly how a cross-object false positive gets
made, and one high-severity false positive costs more than ten misses.

Three things bound it, all of them stated rather than discovered:

* **the cap** (`DEFAULT_MAX_HOPS`) - a chain longer than the cap is not
  propagated, and every truncation is returned as a note the pipeline emits as
  a `truncated` diagnostic;
* **the weight** (`IP_HOP_WEIGHT`, applied by the rules) - every hop is a place
  the analysis could be wrong, so every hop is one factor in the confidence
  product and a cross-object finding never reaches `certain`;
* **the mode** - nothing here runs unless `--dataflow ip` asked for it, so
  `local` emits byte-identical bytes.
"""

from __future__ import annotations

import ast
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .model import CallSite, ClassIR, FunctionIR, ScopeIR, ValueRef, sort_tags
from .provenance import DEFAULT_MAX_HOPS, Hop, extend, merge_chains
from .returns import infer_returns
from .symbols import dotted_text

__all__ = ["propagate_summaries", "DEFAULT_MAX_HOPS"]

#: How many times the whole summary pass may re-run inside one IR round before
#: it declares itself done. The pass is monotone in practice and settles in two
#: or three; the cap only stops a pathological oscillation.
_MAX_SUMMARY_ROUNDS = 4

#: How many truncation notes are reported individually. A note exists so a
#: reader can go and look at the chain; five hundred of them are a wall, not a
#: disclosure, so the rest are counted in one row instead of listed. Measured:
#: 13 on a 490-file workspace, so the cap is never reached in practice and is
#: here for the workspace that would reach it.
_MAX_NOTES = 25


# ---------------------------------------------------------------------------
# what one call site says about one parameter
# ---------------------------------------------------------------------------
class _Fact:
    """The tags, class and provenance one argument expression contributes."""

    __slots__ = ("tags", "class_ir", "is_config", "producer", "chain",
                 "container", "container_scope", "container_module")

    def __init__(self, tags=(), class_ir=None, is_config=False, producer=None,
                 chain=(), container=None, container_scope=None,
                 container_module=None) -> None:
        self.tags: Set[str] = set(tags)
        self.class_ir = class_ir
        self.is_config = bool(is_config)
        self.producer = producer
        self.chain: Tuple[Hop, ...] = tuple(chain)
        #: REC-04. The dict / tuple / list literal this argument *is*, with the
        #: scope its elements must be read in. A `state` parameter read as
        #: `state["scaler"]` was the one shape GRAPH-R3's carriage could not
        #: reach, because carriage stopped at the scope that wrote the literal.
        self.container = container
        self.container_scope = container_scope
        self.container_module = container_module

    def known(self) -> bool:
        return bool(self.tags or self.class_ir is not None
                    or self.container is not None)


def _fact_at(site: CallSite, arg: Optional[ast.expr]) -> _Fact:
    # GRAPH-R3: `argument_value` reads a name *or* an inline construction, so
    # `train(Net(), loader)` states the same fact `train(model, loader)` does.
    from .resolve_passes import argument_value   # local: peers import each other

    ref = argument_value(site, arg) if arg is not None else None
    if ref is None:
        return _Fact()
    return _Fact(tags=ref.tags, class_ir=ref.class_ir, is_config=ref.is_config,
                 producer=ref.producer, chain=getattr(ref, "provenance", ()),
                 container=getattr(ref, "container", None),
                 container_scope=getattr(ref, "container_scope", None) or (
                     ref.scope if getattr(ref, "container", None) is not None
                     else None),
                 container_module=getattr(ref, "container_module", None))


def _pairs(site: CallSite, params: Sequence[str]) -> Dict[str, ast.expr]:
    """`{parameter: argument expression}` for one call site."""
    out: Dict[str, ast.expr] = {}
    for index, arg in enumerate(site.args):
        if index >= len(params):
            break
        out[params[index]] = arg
    for key in sorted(site.kwarg_nodes):
        if key in params:
            out[key] = site.kwarg_nodes[key]
    return out


def _intersect(facts: Sequence[_Fact]) -> _Fact:
    """The one fact every call site agrees on.

    Intersection, never union. With two call sites passing `train_x` and
    `test_x`, the union would hand the helper both TRAIN_SPLIT and TEST_SPLIT
    and MLV102 ("fitted on held-out data", severity high) would fire on
    correct code. What both sites really agree on is FEATURES, and that is all
    this returns. A site whose argument resolved to nothing contributes the
    empty set on purpose: *"I could not check that site"* is not agreement.
    """
    if not facts:
        return _Fact()
    tags = set(facts[0].tags)
    for other in facts[1:]:
        tags &= other.tags
    classes = {id(f.class_ir) for f in facts}
    class_ir = facts[0].class_ir if (len(classes) == 1
                                     and facts[0].class_ir is not None) else None
    # The same discipline for the container: every site has to be passing the
    # very same literal, or the parameter inherits none. Two call sites with
    # two different dicts agree on nothing, and a guessed container would make
    # `state["model"]` in the callee stand for an object no caller passed.
    holders = {id(f.container) for f in facts}
    holder = (facts[0] if len(holders) == 1 and facts[0].container is not None
              else None)
    return _Fact(tags=tags, class_ir=class_ir,
                 is_config=all(f.is_config for f in facts),
                 producer=facts[0].producer if len(facts) == 1 else None,
                 container=holder.container if holder is not None else None,
                 container_scope=holder.container_scope if holder is not None else None,
                 container_module=holder.container_module if holder is not None
                 else None)


# ---------------------------------------------------------------------------
# seeding a parameter
# ---------------------------------------------------------------------------
def _seedable(scope: ScopeIR, param: str, func: FunctionIR) -> bool:
    """May this pass write the parameter's binding?

    Two owners come first and neither is overruled: an **annotation**
    (`seed_annotations` states a type the code itself declared) and a **real
    store** inside the function body (`def f(ds): ds = ds.map(...)`). What is
    left - an absent binding, or the first-wins guess `propagate_parameters`
    wrote - is exactly what the intersection is entitled to correct.
    """
    if param in (func.annotations or {}):
        return False
    existing = scope.bindings.get(param)
    if existing is None:
        return True
    history = scope.binding_history.get(param) or ()
    return all(existing is not ref for ref in history)


def _seed(func: FunctionIR, param: str, fact: _Fact, chain: Tuple[Hop, ...],
          sites: int) -> bool:
    """Write one parameter binding; True when something changed."""
    scope = func.scope
    if not _seedable(scope, param, func):
        return False
    existing = scope.bindings.get(param)
    if not fact.known():
        # Nothing the call sites agree on. Only *clear* a first-wins guess, and
        # only when there really were several sites to disagree - never invent
        # an empty binding, which would turn an untracked name into a resolved
        # one and stop ANA-5a reporting it.
        if (existing is None or sites < 2
                or not (existing.tags or existing.class_ir is not None)):
            return False
        scope.bindings[param] = ValueRef(name=param, scope=scope, loc=func.loc)
        return True
    tags = sort_tags(fact.tags)
    if (existing is not None and tuple(existing.tags) == tags
            and existing.class_ir is fact.class_ir
            and getattr(existing, "container", None) is fact.container
            and tuple(getattr(existing, "provenance", ())) == chain):
        return False
    scope.bindings[param] = ValueRef(
        name=param, scope=scope, tags=tags, producer=fact.producer, loc=func.loc,
        class_ir=fact.class_ir, is_config=fact.is_config, provenance=chain,
        container=fact.container, container_scope=fact.container_scope,
        container_module=fact.container_module)
    return True


def _chain_for(sites: Sequence[CallSite], func: FunctionIR, kind: str,
               chains: Sequence[Tuple[Hop, ...]], max_hops: int,
               notes: List[Tuple[str, int, str]], param: str
               ) -> Optional[Tuple[Hop, ...]]:
    """The provenance to record, or None when the pass must stop here."""
    anchor = sites[0]
    detail = ("%s(...)" % (anchor.short_name or func.name) if len(sites) == 1
              else "%d call sites of %s" % (len(sites), func.name))
    hop = Hop(kind=kind, detail=detail, loc=anchor.loc)
    if len(sites) > 1 and any(len(c) for c in chains):
        # Several sites, at least one of which already arrived through hops of
        # its own. Merging chains of different shapes would put a line number
        # on a claim the analysis never made, so this stops and says so.
        notes.append((anchor.loc.file, anchor.loc.line,
                      "`%s` is called from %d sites whose arguments arrive through "
                      "different interprocedural chains; MLView does not merge them, "
                      "so `%s` keeps only what a call site states directly."
                      % (func.qualname, len(sites), param)))
        return None
    base = merge_chains(chains, hop) if len(sites) == 1 and chains else ()
    chain = extend(base, hop, max_hops)
    if chain is None:
        notes.append((anchor.loc.file, anchor.loc.line,
                      "a value tag reached `%s` after the %d-hop interprocedural cap; "
                      "MLView stops following it there, so anything downstream of "
                      "`%s` is neither confirmed nor ruled out."
                      % (func.qualname, max_hops, param)))
    return chain


def _summarize_args(func: FunctionIR, sites: Sequence[CallSite], kind: str,
                    max_hops: int, notes: List[Tuple[str, int, str]]) -> bool:
    """Argument -> parameter, intersected over `sites`. True when anything moved."""
    params = list(func.params)
    if func.is_method and params and params[0] == "self":
        params = params[1:]
    if not params or not sites:
        return False
    mapped = [_pairs(site, params) for site in sites]
    changed = False
    for param in params:
        facts = [_fact_at(site, mapped[i].get(param)) for i, site in enumerate(sites)]
        merged = _intersect(facts)
        if not merged.known():
            if _seed(func, param, merged, (), len(sites)):
                changed = True
            continue
        chains = [f.chain for f in facts if f.known()]
        chain = _chain_for(sites, func, kind, chains, max_hops, notes, param)
        if chain is None:
            continue
        if _seed(func, param, merged, chain, len(sites)):
            changed = True
    return changed


# ---------------------------------------------------------------------------
# CONSTRUCTOR
# ---------------------------------------------------------------------------
def _init_attributes(init: FunctionIR) -> List[Tuple[str, str, object]]:
    """`[(attribute, parameter, loc)]` for every `self.<attr> = <param>` in `__init__`.

    Deliberately only a bare `ast.Name` on the right: `self.x = transform(p)`
    is a call whose output tags `call_output_tags` already owns, and
    `self.x = p[0]` is a subscript whose meaning MLView does not know.
    """
    params = set(init.params)
    out: List[Tuple[str, str, object]] = []
    for record in init.module.assignments:
        if record.scope is not init.scope or record.kind not in ("assign", "ann"):
            continue
        if record.call is not None or not isinstance(record.value, ast.Name):
            continue
        source = record.value.id
        if source not in params or source == "self":
            continue
        for target in record.targets:
            name = dotted_text(target)
            if name and name.startswith("self."):
                out.append((name, source, record.loc))
    out.sort(key=lambda row: (row[0], row[1]))
    return out


def _constructor_summary(cls: ClassIR, sites: Sequence[CallSite], max_hops: int,
                         notes: List[Tuple[str, int, str]]) -> bool:
    """Ctor argument -> `__init__` parameter -> `self.<attr>`, into the class scope."""
    init = cls.methods.get("__init__")
    if init is None or not sites:
        return False
    changed = _summarize_args(init, sites, "constructor", max_hops, notes)
    for attr, param, loc in _init_attributes(init):
        seed = init.scope.bindings.get(param)
        if seed is None or not seed.tags or not getattr(seed, "provenance", ()):
            # No interprocedural fact to carry. A purely local one (an
            # annotation, say) already reaches the attribute through
            # `bind_module`, and duplicating it here would double-count a hop.
            continue
        target = cls.scope.bindings.get(attr)
        if target is None:
            target = ValueRef(name=attr, scope=cls.scope, loc=loc)
            cls.scope.bindings[attr] = target
            changed = True
        before = (tuple(target.tags), tuple(getattr(target, "provenance", ())))
        # Union into the attribute: the parameter is one of the things the
        # attribute can hold, never the only one.
        target.add_tags(seed.tags)
        if not getattr(target, "provenance", ()):
            target.provenance = tuple(seed.provenance)
        if (tuple(target.tags), tuple(target.provenance)) != before:
            changed = True
    return changed


# ---------------------------------------------------------------------------
# the pass
# ---------------------------------------------------------------------------
def _call_index(workspace):
    """`(by target function, by constructed class)` in a stable order."""
    by_func: Dict[int, List[CallSite]] = {}
    by_class: Dict[int, List[CallSite]] = {}
    for relpath in sorted(workspace.modules):
        for call in workspace.modules[relpath].calls:
            if call.target_function is not None:
                by_func.setdefault(id(call.target_function), []).append(call)
            if call.class_ir is not None:
                by_class.setdefault(id(call.class_ir), []).append(call)
    return by_func, by_class


def _return_fixed_point(workspace, max_hops: int) -> None:
    """RETURN: run `ir.returns` until the summaries stop moving."""
    from .converge import summary_key

    previous = None
    for _round in range(_MAX_SUMMARY_ROUNDS):
        infer_returns(workspace, max_depth=max_hops)
        digest = hash(tuple(
            (relpath, qualname,
             summary_key(workspace.modules[relpath].functions[qualname].return_summary))
            for relpath in sorted(workspace.modules)
            for qualname in sorted(workspace.modules[relpath].functions)))
        if digest == previous:
            return
        previous = digest


def propagate_summaries(workspace, max_hops: int = DEFAULT_MAX_HOPS
                        ) -> List[Tuple[str, int, str]]:
    """Run CONSTRUCTOR, RETURN and METHOD-ARG to a fixed point.

    Returns `(relpath, line, message)` for every chain the hop cap or an
    ambiguous call-site set stopped, deduplicated and sorted. The pipeline
    turns them into `truncated` diagnostics: "I stopped following this" is a
    fact the reader needs, and silence here looks exactly like a clean read.
    """
    notes: List[Tuple[str, int, str]] = []
    for _round in range(_MAX_SUMMARY_ROUNDS):
        by_func, by_class = _call_index(workspace)
        changed = False
        for qualname in sorted(workspace.classes):
            cls = workspace.classes[qualname]
            if _constructor_summary(cls, by_class.get(id(cls)) or [], max_hops, notes):
                changed = True
        for qualname in sorted(workspace.functions):
            func = workspace.functions[qualname]
            if func.name == "__init__" and func.is_method:
                # CONSTRUCTOR owns it, and it owns the *construction* sites.
                # `super().__init__()` and any other explicit call of an
                # `__init__` would otherwise intersect a second, unrelated set
                # of arguments over the top of them.
                continue
            if _summarize_args(func, by_func.get(id(func)) or [], "method-arg",
                               max_hops, notes):
                changed = True
        _return_fixed_point(workspace, max_hops)
        if not changed:
            break
    seen: Set[Tuple[str, int, str]] = set()
    unique = [note for note in notes if not (note in seen or seen.add(note))]
    unique.sort()
    if len(unique) > _MAX_NOTES:
        extra = len(unique) - _MAX_NOTES
        unique = unique[:_MAX_NOTES]
        unique.append((unique[-1][0], unique[-1][1],
                       "%d further interprocedural chain(s) were stopped by the "
                       "%d-hop cap or by call sites MLView would not merge; they are "
                       "counted rather than listed." % (extra, max_hops)))
    return unique
