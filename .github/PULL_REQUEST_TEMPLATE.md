## Change

Describe the user problem and resulting behavior.

## Validation

List commands actually run and their results. Mark skipped checks explicitly.

- [ ] Relevant helper, viewer or extension tests pass.
- [ ] `python tools/verify.py --all` and `python scripts/check_docs.py` pass.
- [ ] `sh scripts/e2e.sh` (or PowerShell equivalent) passes for integration changes.
- [ ] Skill and viewer source changes have their generated copies synchronized.
- [ ] A change to the format touches the five places that CONTRIBUTING.md lists, with a conformance case.

## Limitations

Say what the checks you ran do not show. Unit tests are not a check in a live
assistant or in VS Code, and they do not show that a diagram is right.
Do not attach credentials, private source excerpts or assistant session logs.
