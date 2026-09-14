"""Calls into a third-party library MLView has no knowledge table for.

DGRG-01 / TAB-01 / PUB-10 / INFRA-03 — the second-worst failure the product
names: *a stage claimed absent, a call dropped, a crash swallowed.*

ANA-5a (`core/unresolved.py`) covers the case where the **callee expression**
defeats the analyzer — a subscript callee, a `match`-assigned name, a lambda.
It does not cover the far commoner case where the callee resolves perfectly
well and MLView simply does not know what it *is*:

    from stable_baselines3 import PPO
    model = PPO("MlpPolicy", "CartPole-v1")
    model.learn(total_timesteps=10_000)
    model.save("out")

`PPO` resolves to a clean FQN through an ordinary import binding, so
`_note_unresolved` never fires; `model.learn(...)` is a method on an opaque
value, which `resolve.py:288` exempts for a separate and good reason. The
measured result on `adv_rl_sb3_clean` was five nodes out of eighteen call
sites, `model`, `objective`, `train`, `eval` and `deliver` all declared NOT
DETECTED, `diagnostics: []`, and the verdict *"No findings: no rule fired on
this workspace."* — a clean bill of health for a file the analyzer understood
almost nothing of.

CONTRACTS 11.23 A8 is normative here: no emitter may claim a stage is absent
without qualification when a call was unresolved. This module makes that
guarantee hold **by construction** for any library MLView has never heard of,
rather than only for the two shapes ANA-5a happens to catch.

**Shape.** One row per `(file, top-level package)`, never one per site, for the
same reason 11.18 C1 gives: a library called forty times in one file is one
fact about that file. Only *third-party* packages count — a stdlib call, a
workspace module and a package with any knowledge row at all are all excluded,
so a torch project never acquires a note about `os.path.join`.

**Kind.** `unresolved_callee`, deliberately: the kind is already in
`emit/answers._COVERAGE_KINDS` and already feeds the `"(unverified: N calls
…)"` qualifier and the *"so this is not a clean bill of health"* clause, and
`contracts/graph.schema.json` is a frozen contract this component does not own.
A dedicated `unknown_framework` kind is proposed but not taken in
CONTRACTS 11.52 B2; nothing here depends on it landing.
"""

from __future__ import annotations

import sys
from typing import Dict, List, Optional, Set, Tuple

from .. import knowledge as K
from .graph import Diagnostic
from .unresolved import UNRESOLVED_KIND

__all__ = ["unknown_framework_diagnostics", "unknown_framework_count",
           "unknown_framework_packages"]

#: How many distinct callees one message names before it says "and N more".
_NAMED_SITES = 3

#: Packages that are never a "framework" in the sense this module means, even
#: when they carry no knowledge row: the standard library, the universal
#: utility belt, and MLView's own test scaffolding.
_NEVER_A_FRAMEWORK = frozenset({
    "typing", "typing_extensions", "dataclasses", "abc", "builtins",
    "__future__", "tqdm", "rich", "click", "absl", "six", "attr", "attrs",
    "pytest", "unittest", "setuptools", "pkg_resources", "logging",
})


def _stdlib_names() -> Set[str]:
    names = set(getattr(sys, "stdlib_module_names", ()) or ())
    return names | _NEVER_A_FRAMEWORK


def _package_of(fqn: str) -> str:
    return (fqn or "").split(".")[0]


def _workspace_packages(workspace) -> Set[str]:
    out: Set[str] = set()
    for dotted in workspace.by_dotted:
        if dotted:
            out.add(dotted.split(".")[0])
    for relpath in workspace.modules:
        head = relpath.replace("\\", "/").split("/")[0]
        out.add(head[:-3] if head.endswith(".py") else head)
    return out


def _modelled_packages() -> Set[str]:
    """Every top-level package MLView has *any* knowledge of.

    The granularity matters: the claim this module makes is "MLView has never
    heard of this library", not "this particular function is missing a row".
    `torch.flatten` carries no exact row, and saying so on every torch file
    would bury the one case that matters under noise the reader cannot act on.
    """
    out = {name for name in K._MODULE_FRAMEWORK}       # noqa: SLF001 - same package
    for fqn in K.ALL:
        head = _package_of(fqn)
        if head:
            out.add(head)
    for prefix, _row in K._PREFIX_RULES:               # noqa: SLF001
        head = _package_of(prefix)
        if head:
            out.add(head)
    return out


def _iter_unknown(workspace):
    """`(relpath, package, short name, line)` for every unmodelled library call.

    A call counts when its FQN resolved into a **top-level package MLView has
    no knowledge of at all**. `call.unresolved_callee` sites are skipped:
    ANA-5a already speaks for those, and one call must not produce two coverage
    claims.
    """
    skip = _stdlib_names() | _workspace_packages(workspace) | _modelled_packages()
    for relpath in sorted(workspace.modules):
        module = workspace.modules[relpath]
        for call in module.calls:
            if call.unresolved_callee:
                continue
            fqn = call.fqn or call.import_fqn
            if not fqn or "." not in fqn:
                continue
            package = _package_of(fqn)
            if not package or package in skip:
                continue
            if K.lookup(fqn) is not None:
                continue
            yield relpath, package, call.short_name or fqn.rsplit(".", 1)[-1], call.loc.line


def unknown_framework_packages(workspace) -> List[str]:
    """Every third-party package the workspace calls and MLView cannot model."""
    seen: List[str] = []
    for _rel, package, _short, _line in _iter_unknown(workspace):
        if package not in seen:
            seen.append(package)
    return sorted(seen)


def unknown_framework_count(workspace) -> int:
    """How many call sites went into a library with no knowledge row."""
    return sum(1 for _row in _iter_unknown(workspace))


def _message(package: str, sites: List[Tuple[str, int]]) -> str:
    ordered = sorted(set(sites), key=lambda s: (s[1], s[0]))
    named = ", ".join("`%s(...)` at line %d" % (short, line)
                      for short, line in ordered[:_NAMED_SITES])
    more = ""
    if len(ordered) > _NAMED_SITES:
        more = " and %d more" % (len(ordered) - _NAMED_SITES)
    return ("MLView has no knowledge table for `%s`, so it read %d call%s into it "
            "(%s%s) without understanding what they do. Those calls draw no node, "
            "and any stage they belong to may be present without being detected - "
            "a gap in coverage, not a clean result."
            % (package, len(ordered), "" if len(ordered) == 1 else "s", named, more))


def unknown_framework_diagnostics(workspace) -> List[Diagnostic]:
    """One diagnostic per `(file, package)`, in sort order."""
    sites: Dict[Tuple[str, str], List[Tuple[str, int]]] = {}
    order: List[Tuple[str, str]] = []
    for relpath, package, short, line in _iter_unknown(workspace):
        key = (relpath, package)
        if key not in sites:
            sites[key] = []
            order.append(key)
        sites[key].append((short, line))
    out: List[Diagnostic] = []
    for relpath, package in order:
        rows = sites[(relpath, package)]
        out.append(Diagnostic(
            kind=UNRESOLVED_KIND, message=_message(package, rows),
            file=relpath or None, line=min(line for _s, line in rows) or None,
            scope=package, count=len(set(rows))))
    return out
