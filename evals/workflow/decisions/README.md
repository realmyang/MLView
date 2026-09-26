# Owner decisions

These files hold the pilot owner's reference decisions, second reviews, run policy and development adjudication. Every value starts as `pending`; only the named human reviewer replaces it.
Read the [review guide](../reference-candidates/REVIEW_GUIDE.md) first; `python tools/workflow_eval.py template --show <task>` prints a pristine copy of any file.
Check a file with `python tools/workflow_eval.py check <task>` (or `run-policy`, `development-adjudication`); the check never writes. A complete task or run-policy file ends with "ready to freeze", a complete development adjudication with "complete".
`python tools/workflow_eval.py freeze --campaign <name>` copies completed decisions into `evals/workflow/pilot/<name>/`; it records the reviewers' decisions and adds no approval.
