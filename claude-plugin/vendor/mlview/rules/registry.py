"""The rule registry: `@rule`, discovery, and `run_all`.

Every `rules/r_*.py` module is imported once (sorted by filename); each
`@rule`-decorated function registers a `RuleSpec`. `run_all` executes the
enabled rules in code order, catching exceptions into a `rule_error`
diagnostic unless `--strict` is in force.
"""

from __future__ import annotations

import importlib
import os
import pkgutil
import traceback
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from ..core.graph import Diagnostic

__all__ = ["RuleSpec", "rule", "REGISTRY", "discover_rules", "all_rules", "run_all",
           "rule_for", "reset_registry", "cross_file_codes"]

REGISTRY: Dict[str, "RuleSpec"] = {}
_DISCOVERED = False


@dataclass(frozen=True)
class RuleSpec:
    """Everything the registry knows about one rule."""

    code: str
    severity: str
    base_prior: float
    frameworks: Tuple[str, ...]
    rule_version: int
    tags: Tuple[str, ...]
    absence: bool
    enabled: bool
    title: str
    why: str
    fix_hint: str
    func: Callable
    module: str = ""
    #: This rule's finding is anchored in the file under analysis but its
    #: evidence lives in a *sibling* module - a model class, a DataLoader.
    #: Analysing one file of a package therefore loses the finding silently,
    #: which is what `core/coverage.single_file_diagnostic` reports (COVERAGE).
    #: Appended last and defaulted, so every existing construction still works.
    cross_file: bool = False

    @property
    def docs(self) -> str:
        return "docs/rules/%s.md" % self.code


def rule(code: str, severity: str = "medium", base_prior: float = 0.8,
         frameworks: Sequence[str] = (), rule_version: int = 1,
         tags: Sequence[str] = (), absence: bool = False, enabled: bool = True,
         cross_file: bool = False,
         title: str = "", why: str = "", fix_hint: str = ""):
    """Register a rule function. See `docs/ISSUE_RULES.md` section 5."""

    def decorator(func: Callable) -> Callable:
        spec = RuleSpec(
            code=code, severity=severity, base_prior=float(base_prior),
            frameworks=tuple(frameworks), rule_version=int(rule_version),
            tags=tuple(tags), absence=bool(absence), enabled=bool(enabled),
            cross_file=bool(cross_file),
            title=title, why=why, fix_hint=fix_hint, func=func,
            module=getattr(func, "__module__", ""))
        REGISTRY[code] = spec
        setattr(func, "mlview_rule", spec)
        return func

    return decorator


def reset_registry() -> None:  # pragma: no cover - test helper
    global _DISCOVERED
    REGISTRY.clear()
    _DISCOVERED = False


def discover_rules(force: bool = False) -> Dict[str, RuleSpec]:
    """Import every `rules/r_*.py` module exactly once."""
    global _DISCOVERED
    if _DISCOVERED and not force:
        return REGISTRY
    package_dir = os.path.dirname(os.path.abspath(__file__))
    names = sorted(name for _finder, name, _ispkg in pkgutil.iter_modules([package_dir])
                   if name.startswith("r_"))
    for name in names:
        importlib.import_module("%s.%s" % (__package__, name))
    _DISCOVERED = True
    return REGISTRY


def all_rules() -> List[RuleSpec]:
    """Every registered rule, ordered by code."""
    discover_rules()
    return [REGISTRY[code] for code in sorted(REGISTRY)]


def cross_file_codes() -> List[str]:
    """Every enabled rule whose evidence routinely lives in another module."""
    return [spec.code for spec in all_rules() if spec.enabled and spec.cross_file]


def rule_for(code: str) -> Optional[RuleSpec]:
    discover_rules()
    return REGISTRY.get(code.upper())


def _applies(spec: RuleSpec, frameworks: Iterable[str], framework_filter: str) -> bool:
    if not spec.frameworks:
        return True
    declared = set(spec.frameworks)
    if framework_filter and framework_filter != "auto":
        return framework_filter in declared
    detected = set(frameworks)
    if not detected:
        return True
    return bool(declared & detected) or "all" in declared


def run_all(ctx, strict: bool = False, disabled: Sequence[str] = (),
            framework: str = "auto") -> List:
    """Run every enabled rule against `ctx`; returns the issues it produced."""
    off = {c.upper() for c in disabled or ()}
    for spec in all_rules():
        if not spec.enabled or spec.code.upper() in off:
            continue
        if not _applies(spec, ctx.frameworks, framework):
            continue
        ctx.current_rule = spec
        try:
            produced = spec.func(ctx)
            if produced is not None:
                list(produced)          # generators are consumed here
        except Exception as exc:        # noqa: BLE001 - rules must never crash the run
            if strict:
                raise
            ctx.diagnostics.append(Diagnostic(
                kind="rule_error",
                message="%s raised %s: %s" % (spec.code, type(exc).__name__, exc),
                ruleCode=spec.code))
            if os.environ.get("MLVIEW_DEBUG"):  # pragma: no cover - debugging aid
                import sys
                traceback.print_exc(file=sys.stderr)
        finally:
            ctx.current_rule = None
    return ctx.issues
