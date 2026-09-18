## Change

Describe the user problem and resulting behavior.

## Validation

List commands actually run and their results. Mark skipped checks explicitly.

- [ ] Relevant helper, evaluation, viewer or extension regressions pass.
- [ ] `python tools/verify.py --all` and `python scripts/check_docs.py` pass.
- [ ] `sh scripts/e2e.sh` (or PowerShell equivalent) passes for integration changes.
- [ ] Skill and viewer source changes have their generated copies synchronized.
- [ ] New artifact fields follow the WorkflowDocument contract and boundary validators.

## Evidence and limitations

Distinguish unit tests from live native-host exercises and semantic human review.
Preserve recorded outputs and disclose unresolved or unsupported interpretations.
Do not attach credentials, private source excerpts or raw assistant histories.
