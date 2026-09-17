---
name: mlview-legacy-visualize
description: Run MLView's legacy static Python analyzer only when the user explicitly asks for the legacy analyzer, legacy MLGraph, or deterministic static rule output.
---

# Legacy static MLView analysis

This compatibility skill is not the default MLView workflow. For normal
visualization, use the `mlview` skill, let the active Claude model inspect the
source and configuration, publish `workflow.mlview.json`, and open it in VS
Code. Do not substitute this analyzer result for a model-authored workflow.

When the user explicitly requests legacy analysis, use the bundled `mlview_*`
MCP tools or `python -m mlview analyze <path>`. The analyzer parses Python
without importing or executing target code. Report its coverage diagnostics,
static `MLV###` findings, and limitations as legacy static results.

For legacy scope discovery, `scope: "units"` lists container units only. A call
site such as `train_test_split` may still resolve as `unit:train_test_split`
without appearing in that catalogue. Use `python -m mlview analyze <path>
--list-scopes` for the unbudgeted list.

If a legacy payload reports `framework_filter`, say that the selected framework
suppressed other rule families and offer to rerun with `framework: "auto"`.
Older cached documents may call the equivalent row `framework_suppressed`.
