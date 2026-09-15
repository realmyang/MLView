"""Orchestration of the IR passes.

    parse -> symbols -> scopes/calls -> bindings -> receiver resolution
          -> class-base closure -> loop classification

Binding rounds repeat because receiver resolution needs bindings and binding
tags need resolved receivers; `_run_rounds` stops at the fixed point rather
than at a fixed count (PERF-02, `ir/converge.py`).
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Sequence, Tuple

from .. import knowledge as K
from ..ingest.parse import ParsedFile
from .bindings import bind_module, binding_of, rebind_projections
from .converge import MAX_ROUNDS, state_digest
from .resolve import (mark_fitted, propagate_parameters, resolve_calls,
                      seed_annotations)
from .model import ClassIR, ModuleIR, WorkspaceIR, sort_tags
from .provenance import DEFAULT_MAX_HOPS
from .returns import ReturnSlot, ReturnSummary, infer_returns
from .scopes import classify_loops, walk_module
from .summaries import propagate_summaries
from .symbols import build_symbol_table

__all__ = ["build_workspace", "dotted_for", "is_package", "FRAMEWORK_ORDER",
           "DATAFLOW_MODES", "DEFAULT_DATAFLOW"]

#: DATAFLOW-IP. `ip` is the default from R1 on: it runs `ir.summaries` -
#: constructor, return and method-argument summaries - to a fixed point, so a
#: tag can cross the object boundary. `local` stops at the first `def` and is
#: byte-identical to the analysis that shipped before the flag existed; it
#: stays as the opt-out, not as the default.
#:
#: The flip is a **widening**, measured, not an opinion: on the labelled corpus
#: `ip` has the same precision as `local` (100%, zero forbidden findings) and
#: strictly more recall, every hop costs an explicit `IP_HOP_WEIGHT` factor and
#: names itself in the evidence, and no cross-object finding can reach
#: `certain`. The shipped sample is a frozen artefact, so `analyze --demo` and
#: `contracts/graph.sample.json` are untouched by it.
#:
#: This constant is the authority. `AnalyzeOptions.dataflow`, the `--dataflow`
#: flag and `tools/accuracy.py` all read it rather than spelling "ip" again.
DATAFLOW_MODES = ("local", "ip")
DEFAULT_DATAFLOW = "ip"

FRAMEWORK_ORDER = {name: i for i, name in enumerate(K.FRAMEWORKS)}
_MAX_BASE_ROUNDS = 5
#: ANA-3: how many `from . import X` hops a re-export chain may take before
#: the analyzer stops following it and says so.
_MAX_REEXPORT_HOPS = 3


def dotted_for(relpath: str) -> str:
    """`models/net.py` -> `models.net`; `pkg/__init__.py` -> `pkg`."""
    path = relpath[:-3] if relpath.endswith(".py") else relpath
    parts = [p for p in path.split("/") if p not in ("", ".")]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def is_package(relpath: str) -> bool:
    """`pkg/__init__.py` - the module whose dotted name *is* its package."""
    return relpath.replace("\\", "/").endswith("__init__.py")


def build_workspace(root: str, parsed_files: Sequence[ParsedFile],
                    dataflow: str = DEFAULT_DATAFLOW,
                    max_hops: int = DEFAULT_MAX_HOPS) -> WorkspaceIR:
    """Build the full workspace IR from parsed files.

    `dataflow` (DATAFLOW-IP) selects how far a value tag may travel: `local`
    stops at the first `def`, exactly as before this parameter existed, and
    `ip` runs the interprocedural summary pass inside every IR round. The
    parameter is appended last and defaulted, so every existing caller gets the
    analysis it always got.
    """
    workspace = WorkspaceIR(root=root)
    workspace.dataflow = dataflow if dataflow in DATAFLOW_MODES else DEFAULT_DATAFLOW
    workspace.ip_max_hops = int(max_hops)
    dotted_names = {dotted_for(p.relpath) for p in parsed_files}
    dotted_names.discard("")

    for parsed in parsed_files:
        dotted = dotted_for(parsed.relpath)
        # ROB-01: one module must never cost the workspace. A 700-branch `elif`
        # chain and a 1200-term `+` expression are both legal Python that
        # `ast.parse` accepts and that blow the interpreter's recursion limit
        # in the IR walk - and the exception escaped all the way to `cli.main`,
        # so the run exited 3 with no document at all and every healthy sibling
        # file was lost with it. The contract's answer for an unusable file is
        # one diagnostic naming it, which is what this produces.
        try:
            symbols = build_symbol_table(parsed.tree, dotted, dotted_names,
                                         is_package=is_package(parsed.relpath))
            module = walk_module(parsed, symbols, dotted)
        except RecursionError:
            workspace.walk_failures.append(
                (parsed.relpath, "RecursionError: the module nests too deeply for "
                                 "static analysis; it was skipped"))
            continue
        except Exception as exc:        # pragma: no cover - defensive
            workspace.walk_failures.append(
                (parsed.relpath, "%s: %s" % (type(exc).__name__, exc)))
            continue
        workspace.modules[parsed.relpath] = module
        if dotted:
            workspace.by_dotted[dotted] = module

    for module in workspace.modules.values():
        for qualname, cls in module.classes.items():
            workspace.classes[qualname] = cls
        for qualname, func in module.functions.items():
            workspace.functions[qualname] = func

    reexports, capped = _reexport_map(workspace)
    workspace.reexports = reexports

    _resolve_class_bases(workspace)

    _run_rounds(workspace)
    for relpath in sorted(workspace.modules):
        mark_fitted(workspace.modules[relpath])

    for relpath in sorted(workspace.modules):
        module = workspace.modules[relpath]
        classify_loops(module, binding_of)
        for func in module.functions.values():
            func.loops = [l for l in module.loops if l.function is func]
        _mark_kwargs_forwarding(module)

    workspace.unresolved_imports = _unresolved_imports(workspace, dotted_names) + capped
    workspace.frameworks = _detect_frameworks(workspace)
    workspace.wrappers = _detect_wrappers(workspace)
    workspace.dynamic_scopes = [s for relpath in sorted(workspace.modules)
                                for s in workspace.modules[relpath].scopes if s.dynamic]
    return workspace


def _ir_round(workspace: WorkspaceIR) -> None:
    """One binding / annotation / parameter / resolution / return pass."""
    for relpath in sorted(workspace.modules):
        bind_module(workspace.modules[relpath], workspace)
    for relpath in sorted(workspace.modules):
        seed_annotations(workspace.modules[relpath], workspace)
    for relpath in sorted(workspace.modules):
        propagate_parameters(workspace.modules[relpath], workspace)
    # DATAFLOW-IP: the interprocedural summaries run **after**
    # `propagate_parameters`, because they correct its first-wins guess with an
    # intersection over every call site, and **before** `resolve_calls`, so a
    # receiver typed through a hop resolves in the same round.
    if getattr(workspace, "dataflow", DEFAULT_DATAFLOW) == "ip":
        workspace.ip_notes = propagate_summaries(
            workspace, getattr(workspace, "ip_max_hops", DEFAULT_MAX_HOPS))
    # VIS2-06: the statements that read a value **out of** a parameter
    # container, re-read now that the parameter has a type. See
    # `ir/bindings.rebind_projections`.
    for relpath in sorted(workspace.modules):
        rebind_projections(workspace.modules[relpath], workspace)
    for relpath in sorted(workspace.modules):
        resolve_calls(workspace.modules[relpath], workspace)
    # one level of return-type inference, so the *next* binding round can
    # type `opt = build_optimizer(model, cfg)` (see ir/returns.py). DATAFLOW-IP
    # raises that one level to the hop cap - `propagate_summaries` already ran
    # the pass to its fixed point, and this last call must not walk back down
    # to the default depth and overwrite what it found.
    if getattr(workspace, "dataflow", DEFAULT_DATAFLOW) == "ip":
        infer_returns(workspace,
                      max_depth=getattr(workspace, "ip_max_hops", DEFAULT_MAX_HOPS))
    else:
        infer_returns(workspace)
    _tag_hook_returns(workspace)


def _tag_hook_returns(workspace: WorkspaceIR) -> None:
    """FW-RECOG: `configure_optimizers()` returns an OPTIMIZER, by contract.

    The hook's contract *is* its return type - Lightning will call `.step()` on
    whatever comes back - so the tag is a framework fact, not an inference.
    Without it a `configure_optimizers` that returns a factory call, a dict or
    a tuple hands its caller an untagged value, and nothing downstream knows an
    optimizer was ever declared. The FQNs and the workspace class the inference
    pass did recover are kept untouched; only the tag set grows.
    """
    for relpath in sorted(workspace.modules):
        module = workspace.modules[relpath]
        for qualname in sorted(module.classes):
            cls = module.classes[qualname]
            if not cls.is_hook_owner:
                continue
            func = cls.methods.get("configure_optimizers")
            if func is None or not func.returns:
                continue
            summary = func.return_summary
            scalar = summary.scalar if summary is not None else None
            tags = sort_tags(tuple(scalar.tags if scalar else ()) + ("OPTIMIZER",))
            func.return_summary = ReturnSummary(
                scalar=ReturnSlot(fqns=scalar.fqns if scalar else (), tags=tags,
                                  class_ir=scalar.class_ir if scalar else None),
                positions=summary.positions if summary is not None else ())


def _run_rounds(workspace: WorkspaceIR) -> None:
    """Run the IR passes to their fixed point (PERF-02).

    Bindings need resolved receivers, receiver resolution needs bindings and
    return inference needs both, so the passes run in rounds. The count used to
    be a literal `range(4)`: three rounds wasted on a small workspace, one too
    few for a 5-deep cross-module chain. The loop now stops the round after
    `state_digest` stops moving - which is the fixed point by definition,
    because every pass is a deterministic function of that state - and records
    whether it stopped there or on `MAX_ROUNDS`.
    """
    previous = None
    workspace.ir_rounds = 0
    workspace.ir_converged = False
    for _iteration in range(MAX_ROUNDS):
        _ir_round(workspace)
        workspace.ir_rounds += 1
        current = state_digest(workspace)
        if current == previous:
            workspace.ir_converged = True
            return
        previous = current


def _reexport_map(workspace: WorkspaceIR) -> Tuple[Dict[str, str],
                                                   List[Tuple[str, int, str]]]:
    """ANA-3: `pkg.Net` -> `pkg.net.Net`, the symbol a re-export points at.

    `pkg/__init__.py` doing `from .net import Net` publishes the class under
    `pkg.Net`, a name no `ClassIR` carries, so `from pkg import Net` in a
    sibling module resolved to nothing and the class was drawn as an orphan.
    The walk is capped at `_MAX_REEXPORT_HOPS` and is cycle-safe; a chain that
    outruns the cap is *reported* (as a `dynamic_scope` note) rather than
    silently dropped, so the bound is stated instead of discovered.

    Returns the resolved map and the (relpath, line, message) rows for the
    chains that did not land.

    Two things `raw` is used for, and only one of them may see every module
    (REV-02). **Resolution** needs every module, because a plain consumer
    re-importing a name is a legitimate hop. **Blame** does not: reporting one
    row per unlanded key turned a single over-long chain rooted in one
    `pkg/__init__.py` into one honest note plus one note per importer, each
    naming a file that re-exports nothing and a relationship that does not
    exist - measured at 1 cause + 4 importers = 5 notes, and 41 for a facade
    imported from 40 modules. Only a package `__init__` is blamed now, and only
    once per distinct terminal chain.

    REV-03: the hop loop exits for two different reasons and they used to share
    one message, so a two-module cycle was reported as "re-exported through
    more than 3 modules" - a diagnostic whose whole job is to say *why* MLView
    stopped, telling the reader to shorten a chain that is two modules long.
    """
    raw: Dict[str, str] = {}
    owner: Dict[str, Tuple[str, int]] = {}
    for relpath in sorted(workspace.modules):
        module = workspace.modules[relpath]
        symbols = getattr(module, "symbols", None)
        dotted = module.dotted
        if symbols is None or not dotted:
            continue
        for local in sorted(symbols.aliases):
            target = symbols.aliases[local]
            key = "%s.%s" % (dotted, local)
            if not target or target == key or "." not in target:
                continue
            if key in workspace.classes or key in workspace.functions:
                continue          # the module defines it itself; not a re-export
            if target.rpartition(".")[0] not in workspace.by_dotted:
                continue          # not a workspace symbol - a third-party import
            raw[key] = target
            owner[key] = (relpath, symbols.alias_sites.get(local, 1))

    resolved: Dict[str, str] = {}
    capped: List[Tuple[str, int, str]] = []
    blamed: Dict[Any, str] = {}
    for key in sorted(raw):
        current, seen, landed, cycle = key, {key}, False, False
        chain = [key]
        for _hop in range(_MAX_REEXPORT_HOPS):
            nxt = raw.get(current)
            if nxt is None:
                break
            if nxt in seen:
                cycle = True
                chain.append(nxt)
                break
            current = nxt
            seen.add(current)
            chain.append(current)
            if current in workspace.classes or current in workspace.functions:
                landed = True
                break
        if landed:
            if current != key:
                resolved[key] = current
            continue
        if not cycle and raw.get(current) is None:
            continue                      # the chain simply ran out; not our note
        relpath, line = owner[key]
        if not is_package(relpath):
            # A plain consumer module re-importing the name is a hop, never the
            # cause. Blaming it names the wrong file and the wrong symbol.
            continue
        # One row per distinct terminal chain: a cycle is identified by the set
        # of names in it (every member would otherwise report the same loop
        # from its own starting point), a cap by where the walk stopped.
        mark = (frozenset(seen), "cycle") if cycle else (current, "cap")
        if mark in blamed:
            continue
        blamed[mark] = key
        if cycle:
            message = ("`%s` re-exports in a cycle (%s) (line %d); MLView stops "
                       "following the chain there, so symbols imported under "
                       "that name stay unresolved."
                       % (key, " -> ".join(chain), line))
        else:
            message = ("`%s` is re-exported through more than %d modules "
                       "(line %d); MLView stops following the chain there, so "
                       "symbols imported under that name stay unresolved."
                       % (key, _MAX_REEXPORT_HOPS, line))
        capped.append((relpath, line, message))
    capped.sort()
    return resolved, capped


def _unresolved_imports(workspace: WorkspaceIR, dotted_names) -> List[Tuple[str, int, str]]:
    """Imports that named nothing, while a workspace module of that name exists.

    Cross-file resolution degrading silently is worse than degrading loudly:
    the graph simply comes back smaller and the issue list changes in both
    directions with nothing to point at. Reported as a `dynamic_scope`
    diagnostic by the pipeline.
    """
    known = set(dotted_names)
    out: List[Tuple[str, int, str]] = []
    for relpath in sorted(workspace.modules):
        module = workspace.modules[relpath]
        symbols = getattr(module, "symbols", None)
        if symbols is None:
            continue
        seen = set()
        for name, line in symbols.import_sites:
            if not name or name in seen:
                continue
            if name in known or any(w.startswith(name + ".") for w in known):
                continue
            head = name.split(".")[0]
            matches = sorted(w for w in known if head in w.split("."))
            if not matches:
                continue
            seen.add(name)
            out.append((relpath, line,
                        "`import %s` (line %d) resolved to nothing: the workspace has "
                        "%s, but it is not reachable under that name from %s, so every "
                        "symbol imported from it stays unresolved."
                        % (name, line, ", ".join(matches[:3]), relpath)))
    out.sort()
    return out


def _normalize_bases(cls: ClassIR, workspace: WorkspaceIR) -> Tuple[str, ...]:
    out: List[str] = []
    for base in cls.bases:
        if base in workspace.classes:
            out.append(base)
            continue
        local = "%s.%s" % (cls.module.dotted, base) if cls.module.dotted else base
        if local in workspace.classes:
            out.append(local)
            continue
        out.append(base)
    return tuple(out)


def _resolve_class_bases(workspace: WorkspaceIR) -> None:
    for cls in workspace.classes.values():
        cls.bases = _normalize_bases(cls, workspace)
        cls.resolved_bases = tuple(cls.bases)
    for _round in range(_MAX_BASE_ROUNDS):
        changed = False
        for cls in workspace.classes.values():
            resolved = list(cls.resolved_bases)
            for base in list(resolved):
                parent = workspace.classes.get(base)
                if parent is None:
                    continue
                for inherited in parent.resolved_bases:
                    if inherited not in resolved and inherited != cls.qualname:
                        resolved.append(inherited)
                        changed = True
            if len(resolved) != len(cls.resolved_bases):
                cls.resolved_bases = tuple(resolved)
        if not changed:
            break


def _mark_kwargs_forwarding(module: ModuleIR) -> None:
    for call in module.calls:
        if getattr(call, "has_kwargs_forward", False) and K.is_known(call.fqn):
            call.scope.mark_dynamic(
                "**kwargs forwarded into %s at line %d" % (call.fqn, call.loc.line))


def _detect_frameworks(workspace: WorkspaceIR) -> Tuple[str, ...]:
    """Every framework this workspace really uses.

    VIS2-15. `workspace.frameworks` is presented by the README, the VS Code
    status-bar tooltip and every chat/LM digest as a statement about the
    project, and a **method-name** match alone was enough to make one: a
    `np.array(...).tolist()` resolved to `pandas.Series.tolist` (the only
    table that carried `tolist`) and put `pandas` in the list for a pure
    numpy + torch vision project with no `import pandas` anywhere.

    The ambiguity is confined to one place and the guard is confined with it.
    An untyped frame receiver has no constructor to hang a method off, so
    `ir/resolve` proposes `pandas.DataFrame.<m>`, `pandas.Series.<m>` and
    `numpy.ndarray.<m>` in a **fixed order** and whichever is listed first
    wins - a guess, not a resolution. A framework credited only through one of
    those three bases is therefore kept only when the workspace imports it.
    Everything else is unchanged: a framework named by a constructor FQN came
    from the import table in the first place, and `tf.keras.Model.compile`
    still credits `keras` on a file that imports only `tensorflow`, because
    `tf.keras` really is Keras.
    """
    imported: set = set()
    for module in workspace.modules.values():
        imported.update(module.frameworks)
    found: set = set(imported)
    for module in workspace.modules.values():
        for call in module.calls:
            for fqn in call.canonical_fqns:
                fw = K.framework_of(fqn)
                if not fw or fw == "other":
                    continue
                guessed = (fqn in K.METHODS
                           and fqn.startswith(_FRAME_GUESS_PREFIXES))
                if not guessed or fw in imported:
                    found.add(fw)
                break
    return tuple(sorted(found, key=lambda f: FRAMEWORK_ORDER.get(f, 99)))


#: VIS2-15. The three receiver bases `ir/resolve._FRAME_BASES` proposes, in
#: order, for a value it could not type. `tolist` was registered for pandas
#: only, so `np.array(...).tolist()` resolved to `pandas.Series.tolist` and put
#: **pandas** - which the README, the VS Code status-bar tooltip and every chat
#: digest present as a fact about the project - into `workspace.frameworks` for
#: a pure numpy + torch vision workspace with no `import pandas` anywhere.
_FRAME_GUESS_PREFIXES = ("pandas.DataFrame.", "pandas.Series.", "numpy.ndarray.")


def _module_wrappers(module: ModuleIR) -> List[str]:
    labels: List[str] = []

    def add(label: str) -> None:
        if label not in labels:
            labels.append(label)

    for _name, fqn in module.symbols.aliases.items():
        label = K.WRAPPER_FQNS.get(fqn)
        if label:
            add(label)
    for call in module.calls:
        for fqn in call.canonical_fqns:
            label = K.WRAPPER_FQNS.get(fqn)
            if label:
                add(label)
    for cls in module.classes.values():
        for base in cls.resolved_bases:
            if base in K.WRAPPER_BASES:
                add(K.WRAPPER_FQNS.get(base, "Lightning"))
    return labels


def _detect_wrappers(workspace: WorkspaceIR) -> Tuple[str, ...]:
    """Wrapper labels per module, then the workspace union.

    Iron law 4 gates absence rules when a framework owns the training loop -
    but ownership is a property of the code the finding is *in*, not of the
    workspace: one unrelated HuggingFace script must not silently delete every
    finding in a hand-written `train.py` next to it.
    """
    own = {relpath: _module_wrappers(workspace.modules[relpath])
           for relpath in sorted(workspace.modules)}
    for relpath in sorted(workspace.modules):
        module = workspace.modules[relpath]
        labels = list(own[relpath])
        for imported in module.imports:
            for other_rel in sorted(workspace.modules):
                other = workspace.modules[other_rel]
                if other is module:
                    continue
                if other.dotted == imported or other.dotted.startswith(imported + "."):
                    for label in own[other_rel]:
                        if label not in labels:
                            labels.append(label)
        module.wrappers = tuple(sorted(labels))
    union: List[str] = []
    for relpath in sorted(own):
        for label in own[relpath]:
            if label not in union:
                union.append(label)
    return tuple(sorted(union))
