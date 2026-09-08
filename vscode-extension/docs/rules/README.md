# Offline rule documentation

`docs/rules/MLVxxx.md` are the pages generated from the analyzer rule registry
(`analyzer/tools/gen_rule_docs.py` writes them to `<repo>/docs/rules/`). They are copied here by
`vscode-extension/tools/sync-rule-docs.mjs`, which `npm run compile` and `npm run pretest` run —
so `scripts/build.ps1` keeps them current, and `vsce package` ships them.

They must live *here*, inside the extension, because CONTRACTS.md §6 freezes a diagnostic's code
as `{ value: "MLV201", target: Uri.joinPath(ctx.extensionUri, 'docs', 'rules', 'MLV201.md') }` —
a **local** file, so rule docs work with no network. `src/diagnostics.ts` also tries
`<parent-of-extensionPath>/docs/rules`, but that only resolves in a dev checkout: in a real
install the parent is `~/.vscode/extensions`. Without the copy in this directory every diagnostic
would fall back to a bare string code, the Problems-panel rule code would stop being a link, and
`MLView: Open Rule Documentation` would degrade to a one-line notification.

Do not edit these pages by hand — regenerate them and re-run `npm run sync:rule-docs`.
`node tools/sync-rule-docs.mjs --check` fails if this directory has drifted, and
`test/invariants.test.js` asserts the two directories agree page for page.
