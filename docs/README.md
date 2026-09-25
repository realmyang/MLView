# Documentation

Start with the [project overview](../README.md) and
[installation and refinement guide](LLM_WORKFLOW.md).

| Document | Purpose |
|---|---|
| [WorkflowDocument contract](WORKFLOW_CONTRACT.md) | Artifact semantics, evidence and validation boundaries |
| [Current status](STATUS.md) | What ships and what still needs validation |
| [Improvement research](IMPROVEMENT_RESEARCH_2026-09-18.md) | Prioritized proposals grounded in source, evaluation records and primary research |
| [Trust and usability campaign](TRUST_USABILITY_CAMPAIGN.md) | Implemented first campaign, validation and remaining human/live checks |
| [Performance baseline](PERFORMANCE.md) | Reproducible synthetic scale harness and measured limits |
| [Validation](VALIDATION.md) | Current local check results and their limits |
| [Contributing](../CONTRIBUTING.md) | Development setup and release gates |
| [Agent guide](../CLAUDE.md) | Project rules, boundaries and checks for coding agents |
| [Evaluation protocol](../evals/workflow/README.md) | Native-host semantic and human review |
| [Human review guide](../evals/workflow/reference-candidates/REVIEW_GUIDE.md) | Decisions needed from the pilot owner, with a plain-text template |
| [Security policy](../SECURITY.md) | Trust boundaries and private reporting |

## Historical records

The static analyzer was removed at the maintainer's request on 2026-09-18. Older
architecture, requirements, rule-design, accuracy and contract documents are
retained as historical decision records. Their commands and file paths describe
old revisions and are not instructions for the current product. The implementation
itself, old rule catalog and old generated reports are available in Git history.

- [Codex handoff](CODEX_HANDOFF.md): Codex-era takeover state and dated work
  history through 2026-09-24.
