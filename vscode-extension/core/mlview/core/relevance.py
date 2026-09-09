"""PERF-03 (CONTRACTS 11.28) — the relevance prefilter.

A realistic repository is mostly not machine learning. On the 500-file mixed
synthetic this module is measured against (50 framework-touching modules, 450
ordinary application modules), `build_workspace` costs **1126 ms** over all 501
files and **76 ms** over the 51 the prefilter keeps, while the parse it cannot
avoid costs 313 ms either way. That single number — 1050 ms of IR that no rule
ever reads — is the whole of PERF-03.

The filter is three steps and one refusal:

1. **Seed by byte scan.** A module is a *seed* when its source contains any
   token in `framework_tokens()`. The token set is **derived** from the
   knowledge tables (`knowledge._MODULE_FRAMEWORK` plus the roots of every
   wrapper, model base and hook owner MLView knows), minus a short, stated list
   of roots that are not evidence of anything — `os`, `json`, `random`,
   `pickle`, `argparse`, `yaml`, `toml`, `tomllib`. Those eight are in the
   knowledge tables for good reasons and appear in essentially every Python
   file, so treating them as evidence makes the filter a no-op. Deriving the
   rest means a framework added to `knowledge/` becomes a seed token in the
   same commit, with no second list to update.

2. **Build the module import graph, and only that.** Every file is still
   `ast.parse`d on a cold run — that is how imports are read, and there is no
   cheaper honest way — but nothing else is built for a module that does not
   survive. Relative imports, sibling imports and package `__init__` bases are
   resolved through `ir.symbols`' own `_relative_base` / `_sibling_module`, so
   the graph follows **exactly** ANA-3's rules, and re-export chains are
   followed to their definition module up to `ir.build_ir._MAX_REEXPORT_HOPS`
   hops. That last part is why the roadmap sequences PERF-03 *after* ANA-3: a
   `pkg/__init__.py` that publishes `from .net import Net` is precisely the
   chain a naive filter cuts.

3. **Keep everything within `hops` of a seed, in either direction.** Both
   directions, because a `utils.py` that wraps `train_test_split` without
   importing sklearn itself is reached *from* an ML module, while the config
   module an ML module imports is reached *by* it. The default is 2. Every
   `__init__.py` on a kept module's package path is kept too: importing
   `pkg.mod` executes `pkg/__init__.py`, so a package `__init__` belongs to its
   package whether or not an import statement names it.

**The refusal.** If nothing is a seed, nothing is set aside. A workspace with
no framework token anywhere is not a workspace this filter has an opinion
about, and returning an empty analysis for it would be the worst possible
answer. The same rule makes every single-file invocation — every
`tests/fixtures/rules/*.py` case — byte-identical in both modes.

**What it cannot see, stated out loud.** The seed scan is a byte match: it
cannot tell `import torch` from the word `torch` in a docstring, and it errs
towards keeping. The hop count cannot see a module reached only through
`importlib`, a plugin registry or a dotted name held in a string — those are
the modules `--relevance all` exists for, and the count of what was set aside
is emitted as a `config_warning` naming that flag, because a filter that
quietly shrinks the answer is precisely the failure mode this project refuses.
A workspace-wide **absence** rule (MLV601) also means "absent from the kept
set" under `--relevance ml`; it reports the same finding, anchored inside the
kept set rather than on whichever file happened to sort first.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .graph import Diagnostic

__all__ = [
    "DEFAULT_HOPS", "GENERIC_ROOTS", "MODES", "FileFacts", "Relevance",
    "facts_from_payload", "facts_of", "facts_of_parsed", "framework_tokens",
    "import_graph", "is_seed", "raw_imports", "relevance_diagnostic",
    "resolve_imports", "select",
]

#: `--relevance` values. `all` is the identity: every discovered file survives.
MODES = ("ml", "all")
DEFAULT_HOPS = 2

#: Knowledge roots that are **not** evidence of machine learning. Every one of
#: them is legitimately in the tables (`json.load`, `pickle.dump`,
#: `argparse.ArgumentParser`, `random.seed`, `os.environ` all matter to some
#: rule) and every one of them appears in ordinary application code, so using
#: them as seeds keeps the whole repository and buys nothing. This is the only
#: hand-maintained half of the token set, and it is stated here rather than
#: buried in a regex.
GENERIC_ROOTS = frozenset({
    "argparse", "json", "os", "pickle", "random", "toml", "tomllib", "yaml",
})


@lru_cache(maxsize=1)
def framework_tokens() -> Tuple[str, ...]:
    """The seed token set, derived from the knowledge tables. Sorted."""
    from .. import knowledge as K

    roots: Set[str] = set(K._MODULE_FRAMEWORK)
    for table in (K.ALL, K.WRAPPER_FQNS):
        for fqn in table:
            roots.add(fqn.split(".")[0])
    for group in (getattr(K, "MODEL_BASES", ()), K.HOOK_OWNER_BASES, K.LIGHTNING_ROOTS):
        for fqn in group:
            roots.add(fqn.split(".")[0])
    roots -= GENERIC_ROOTS
    roots.discard("")
    return tuple(sorted(roots))


@lru_cache(maxsize=1)
def _pattern():
    return re.compile(r"(?<![0-9A-Za-z_])(?:%s)(?![0-9A-Za-z_])"
                      % "|".join(re.escape(t) for t in framework_tokens()))


def is_seed(source: str) -> bool:
    """True when `source` mentions any framework token as a whole word."""
    return _pattern().search(source) is not None


# ------------------------------------------------------------------- facts
#: One import statement, reduced to what the graph needs and nothing else:
#: `(level, module, ((name, asname), ...), plain)`. `plain` marks `import x`
#: as opposed to `from x import y`. Pure JSON, pure content — it depends on the
#: file's bytes and on nothing about the workspace around it, which is what
#: makes it cacheable across a run that added or removed a file.
ImportRow = Tuple[int, str, Tuple[Tuple[str, str], ...], bool]


@dataclass(frozen=True)
class FileFacts:
    """The per-file facts the prefilter needs. Derived from one file's bytes."""

    relpath: str
    seed: bool
    imports: Tuple[ImportRow, ...]

    def payload(self) -> Dict[str, object]:
        """The JSON form written to the sidecar. Compact on purpose."""
        return {"s": 1 if self.seed else 0,
                "i": [[row[0], row[1], [list(p) for p in row[2]], 1 if row[3] else 0]
                      for row in self.imports]}


def facts_from_payload(relpath: str, payload: Mapping[str, object]) -> Optional[FileFacts]:
    """Rebuild `FileFacts` from a sidecar payload, or None if it is malformed."""
    try:
        rows: List[ImportRow] = []
        for row in payload["i"]:                      # type: ignore[index]
            level, module, names, plain = row
            rows.append((int(level), str(module),
                         tuple((str(a), str(b)) for a, b in names), bool(plain)))
        return FileFacts(relpath=relpath, seed=bool(payload["s"]),  # type: ignore[index]
                         imports=tuple(rows))
    except (KeyError, TypeError, ValueError):
        return None


def raw_imports(tree: ast.Module) -> Tuple[ImportRow, ...]:
    """Every import in the module, nested ones included, in `ast.walk` order."""
    rows: List[ImportRow] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            rows.append((0, "", tuple((a.name, a.asname or "") for a in node.names), True))
        elif isinstance(node, ast.ImportFrom):
            rows.append((node.level or 0, node.module or "",
                         tuple((a.name, a.asname or "") for a in node.names), False))
    return tuple(rows)


def facts_of_parsed(parsed) -> FileFacts:
    """The facts for one `ingest.parse.ParsedFile`."""
    return FileFacts(relpath=parsed.relpath, seed=is_seed(parsed.source),
                     imports=raw_imports(parsed.tree))


def facts_of(parsed_files: Sequence[object]) -> Dict[str, FileFacts]:
    """`relpath -> FileFacts` for a whole parsed set. Test and `all`-mode path."""
    return {p.relpath: facts_of_parsed(p) for p in parsed_files}


def resolve_imports(facts: FileFacts, dotted: str, is_package: bool,
                    workspace_names: Set[str]) -> Tuple[Set[str], Dict[str, str]]:
    """`(module targets, local alias -> dotted target)` for one file.

    The two helpers are `ir.symbols`' own, deliberately: `_relative_base` is
    where ANA-3 lives (a package `__init__`'s dotted name **is** its package)
    and `_sibling_module` is why a bare `from model import Net` in
    `experiments/exp1/train.py` resolves at all. A second implementation of
    either would be a second opinion about what a module is called.
    """
    from ..ir.symbols import _relative_base, _sibling_module

    targets: Set[str] = set()
    aliases: Dict[str, str] = {}
    for level, module, names, plain in facts.imports:
        if plain:
            for name, asname in names:
                target = _sibling_module(name, dotted, workspace_names)
                targets.add(target)
                aliases[asname or name.split(".")[0]] = target
            continue
        if level:
            base = _relative_base(dotted, level, is_package)
            owner = "%s.%s" % (base, module) if module else base
        else:
            owner = _sibling_module(module, dotted, workspace_names)
        if owner:
            targets.add(owner)
        for name, asname in names:
            if name == "*":
                continue
            aliases[asname or name] = ("%s.%s" % (owner, name)) if owner else name
    return targets, aliases


# --------------------------------------------------------------- import graph
def _longest_owner(dotted: str, by_dotted: Mapping[str, str]) -> Optional[str]:
    """The workspace module owning `dotted` — the longest prefix that is one.

    `pkg.net.Net` belongs to `pkg.net`; `pkg.Net` (an ANA-3 re-export) belongs
    to `pkg`, the package `__init__`, and the second hop is what the re-export
    walk below adds.
    """
    probe = dotted
    while probe:
        owner = by_dotted.get(probe)
        if owner is not None:
            return owner
        probe = probe.rpartition(".")[0]
    return None


def import_graph(facts: Mapping[str, FileFacts]) -> Dict[str, Tuple[str, ...]]:
    """`relpath -> the workspace relpaths it imports`, re-exports followed.

    Only imports are resolved; no scopes, no calls, no bindings. On the 500-file
    synthetic this costs ~116 ms against the ~1.1 s `build_workspace` spends on
    the same files.
    """
    from ..ir.build_ir import _MAX_REEXPORT_HOPS, dotted_for, is_package

    by_dotted: Dict[str, str] = {}
    for relpath in sorted(facts):
        dotted = dotted_for(relpath)
        if dotted:
            by_dotted.setdefault(dotted, relpath)
    names = set(by_dotted)

    resolved: Dict[str, Tuple[str, Set[str], Dict[str, str]]] = {}
    alias_of: Dict[str, str] = {}
    for relpath in sorted(facts):
        dotted = dotted_for(relpath)
        targets, aliases = resolve_imports(facts[relpath], dotted,
                                           is_package(relpath), names)
        resolved[relpath] = (dotted, targets, aliases)
        if not dotted:
            continue
        for local, target in aliases.items():
            if target and "." in target:
                alias_of["%s.%s" % (dotted, local)] = target

    def follow(dotted: str) -> str:
        """Walk a re-export chain to where it lands. Bounded and cycle-safe."""
        seen = {dotted}
        for _hop in range(_MAX_REEXPORT_HOPS):
            nxt = alias_of.get(dotted)
            if nxt is None or nxt in seen:
                break
            dotted = nxt
            seen.add(dotted)
        return dotted

    out: Dict[str, Tuple[str, ...]] = {}
    for relpath, (_dotted, targets, aliases) in resolved.items():
        edges: Set[str] = set()
        for candidate in set(targets) | {v for v in aliases.values() if v}:
            owner = _longest_owner(candidate, by_dotted)
            if owner is not None and owner != relpath:
                edges.add(owner)
            landed = follow(candidate)
            if landed != candidate:
                owner = _longest_owner(landed, by_dotted)
                if owner is not None and owner != relpath:
                    edges.add(owner)
        out[relpath] = tuple(sorted(edges))
    return out


# ------------------------------------------------------------------ decision
@dataclass(frozen=True)
class Relevance:
    """The prefilter's decision. `kept` and `set_aside` are sorted relpaths."""

    mode: str
    hops: int
    kept: Tuple[str, ...]
    seeds: Tuple[str, ...]
    set_aside: Tuple[str, ...]
    #: Why nothing was set aside, when nothing was: "" (something was),
    #: "mode" (`--relevance all`), "no-seeds", or "nothing-to-drop".
    reason: str = ""

    @property
    def narrowed(self) -> bool:
        return bool(self.set_aside)


def _package_inits(kept: Set[str], everything: Set[str]) -> Set[str]:
    """Every `__init__.py` on the package path of a kept module."""
    out: Set[str] = set()
    for relpath in kept:
        parts = relpath.split("/")[:-1]
        for depth in range(1, len(parts) + 1):
            candidate = "/".join(parts[:depth]) + "/__init__.py"
            if candidate in everything:
                out.add(candidate)
    return out


def select(facts: Mapping[str, FileFacts], mode: str = "all",
           hops: int = DEFAULT_HOPS, pinned: Iterable[str] = ()) -> Relevance:
    """Decide which modules the IR and the rules will see.

    `pinned` relpaths are always seeds: a path the caller named explicitly is
    the question being asked, and a filter may never answer a different one.
    """
    everything = set(facts)
    ordered = tuple(sorted(everything))
    if mode != "ml":
        return Relevance(mode="all", hops=hops, kept=ordered, seeds=(),
                         set_aside=(), reason="mode")

    pins = {p for p in pinned if p in everything}
    seeds = {rel for rel, fact in facts.items() if fact.seed} | pins
    if not seeds:
        # Nothing looked like machine learning. That is not a licence to
        # return an empty analysis - it is a reason to have no opinion.
        return Relevance(mode="ml", hops=hops, kept=ordered, seeds=(),
                         set_aside=(), reason="no-seeds")

    graph = import_graph(facts)
    undirected: Dict[str, Set[str]] = {rel: set() for rel in everything}
    for source, targets in graph.items():
        for target in targets:
            if target in undirected:
                undirected[source].add(target)
                undirected[target].add(source)

    frontier = set(seeds)
    kept = set(seeds)
    for _hop in range(max(0, int(hops))):
        nxt: Set[str] = set()
        for rel in frontier:
            nxt |= undirected.get(rel, set()) - kept
        if not nxt:
            break
        kept |= nxt
        frontier = nxt

    kept |= _package_inits(kept, everything)
    set_aside = tuple(sorted(everything - kept))
    return Relevance(mode="ml", hops=hops, kept=tuple(sorted(kept)),
                     seeds=tuple(sorted(seeds)), set_aside=set_aside,
                     reason="" if set_aside else "nothing-to-drop")


def relevance_diagnostic(relevance: Relevance) -> Optional[Diagnostic]:
    """The `config_warning` naming the set-aside count and the flag that
    includes them, or None when the filter changed nothing.

    None when nothing was set aside is not politeness: it is what makes
    `--relevance ml` and `--relevance all` byte-identical on every workspace
    the filter did not narrow, which is every fixture and every sample.
    """
    if not relevance.set_aside:
        return None
    shown = ", ".join(relevance.set_aside[:4])
    more = (" and %d more" % (len(relevance.set_aside) - 4)
            if len(relevance.set_aside) > 4 else "")
    return Diagnostic(
        kind="config_warning",
        message="Relevance prefilter (--relevance ml): %d file(s) set aside as "
                "unreachable from any framework import within %d hop(s) - %s%s. "
                "They were read but not analyzed; re-run with --relevance all "
                "to include them, or raise --relevance-hops."
                % (len(relevance.set_aside), relevance.hops, shown, more),
        count=len(relevance.set_aside))
