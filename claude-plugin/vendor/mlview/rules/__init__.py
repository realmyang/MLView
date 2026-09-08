"""MLView rules: the registry, the confidence model, suppression, the rules.

Adding a rule is one file, `rules/r_<something>.py`:

    from .registry import rule

    @rule(code="MLV999", severity="medium", base_prior=0.85, frameworks=["torch"],
          rule_version=1, tags=["correctness"], title="...", why="...",
          fix_hint="...")
    def my_rule(ctx):
        for call in ctx.calls_of("torch.optim.Optimizer.step"):
            node = ctx.node_for_call(call)
            if node is None:
                continue
            ctx.issue(message="...", loc=call.loc, node_ids=[node],
                      evidence=[("fqn_resolved", call.fqn, 1.0)])

plus `tests/fixtures/rules/MLV999_bad.py` (with a `# MLVIEW-EXPECT:` header)
and `MLV999_good.py`.
"""

from __future__ import annotations

from .confidence import bucket_for, cap_severity, compute_confidence
from .context import GraphContext
from .registry import (REGISTRY, RuleSpec, all_rules, cross_file_codes,
                       discover_rules, rule, rule_for, run_all)
from .suppress import RuleConfig, Suppressor, load_config

__all__ = [
    "GraphContext", "rule", "RuleSpec", "REGISTRY", "all_rules", "discover_rules",
    "run_all", "rule_for", "cross_file_codes", "Suppressor", "RuleConfig", "load_config",
    "compute_confidence", "cap_severity", "bucket_for",
]
