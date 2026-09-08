"""Orchestration of the IR passes.

    parse -> symbols -> scopes/calls -> bindings -> receiver resolution
          -> class-base closure -> loop classification

Binding rounds repeat because receiver resolution needs bindings and binding
tags need resolved receivers; `_run_rounds` stops at the fixed point rather
than at a fixed count (PERF-02, `ir/converge.py`).
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Sequence, Tuple

from .. import knowledge as K
from ..ingest.parse import ParsedFile
from .bindings import bind_module, binding_of
from .converge import MAX_ROUNDS, state_digest
from .resolve import (mark_fitted, propagate_parameters, resolve_calls,
                      seed_annotations)
from .model import ClassIR, ModuleIR, WorkspaceIR
from .returns import infer_returns
from .scopes import classify_loops, walk_module
from .symbols import build_symbol_table

__all__ = ["build_workspace", "dotted_for", "FRAMEWORK_ORDER"]

FRAMEWORK_ORDER = {name: i for i, name in enumerate(K.FRAMEWORKS)}
_MAX_BASE_ROUNDS = 5


def dotted_for(relpath: str) -> str:
    """`models/net.py` -> `models.net`; `pkg/__init__.py` -> `pkg`."""
    path = relpath[:-3] if relpath.endswith(".py") else relpath
    parts = [p for p in path.split("/") if p not in ("", ".")]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def build_workspace(root: str, parsed_files: Sequence[ParsedFile]) -> WorkspaceIR:
    """Build the full workspace IR from parsed files."""
    workspace = WorkspaceIR(root=root)
    dotted_names = {dotted_for(p.relpath) for p in parsed_files}
    dotted_names.discard("")

    for parsed in parsed_files:
        dotted = dotted_for(parsed.relpath)
        symbols = build_symbol_table(parsed.tree, dotted, dotted_names)
        module = walk_module(parsed, symbols, dotted)
        workspace.modules[parsed.relpath] = module
        if dotted:
            workspace.by_dotted[dotted] = module

    for module in workspace.modules.values():
        for qualname, cls in module.classes.items():
            workspace.classes[qualname] = cls
        for qualname, func in module.functions.items():
            workspace.functions[qualname] = func

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

    workspace.unresolved_imports = _unresolved_imports(workspace, dotted_names)
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
    for relpath in sorted(workspace.modules):
        resolve_calls(workspace.modules[relpath], workspace)
    # one level of return-type inference, so the *next* binding round can
    # type `opt = build_optimizer(model, cfg)` (see ir/returns.py)
    infer_returns(workspace)


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
    found: set = set()
    for module in workspace.modules.values():
        found.update(module.frameworks)
        for call in module.calls:
            for fqn in call.canonical_fqns:
                fw = K.framework_of(fqn)
                if fw and fw != "other":
                    found.add(fw)
                    break
    return tuple(sorted(found, key=lambda f: FRAMEWORK_ORDER.get(f, 99)))


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
