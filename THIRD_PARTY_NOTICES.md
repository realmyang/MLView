# Third-party notices

MLView is MIT-licensed ([`LICENSE`](LICENSE), Copyright (c) 2026 realmyang). This file lists the
third-party software that is **redistributed inside an MLView artifact** — the wheel, the VSIX, the
Claude Code plugin and the standalone HTML report — together with the licence text each one ships
under, copied verbatim from the package as installed.

The list is short on purpose. MLView has **no Python runtime dependency at all**
(`analyzer/pyproject.toml` declares `dependencies = []`) and the viewer bundle has exactly one
(`webview/package.json` declares `"@dagrejs/dagre": "3.1.1"`, which brings `@dagrejs/graphlib` with
it). Everything else in the toolchain is build-time only and reaches no artifact; the last section
says which, and why.

## What ships, and what is inside it

The viewer is built once — `webview/build.mjs` runs esbuild over `webview/src/main.ts` into
`webview/dist/mlview.js` (an IIFE, global `MLView`) and `webview/dist/mlview.css` — and that one
bundle is then copied, unchanged, into every host by `tools/sync-assets.py` and `tools/sync-core.py`.
`webview/src/layout/layout.ts` does `import dagre from '@dagrejs/dagre'`, so dagre and graphlib are
**inlined into `mlview.js`** rather than loaded at runtime. That is the whole of the redistribution,
and it reaches all four artifacts:

| Artifact | Path that carries the bundle | Third-party code inside |
|---|---|---|
| Wheel (`mlview-0.1.0-py3-none-any.whl`) | `mlview/emit/assets/mlview.js` | `@dagrejs/dagre`, `@dagrejs/graphlib` |
| VSIX (`vscode-extension/`) | `media/mlview.js`, and again under `core/mlview/emit/assets/mlview.js` | the same two |
| Claude Code plugin (`claude-plugin/`) | `vendor/mlview/emit/assets/mlview.js` | the same two |
| Standalone HTML report | the bundle inlined into the single `.html` file by `mlview.emit.html_out` | the same two |

Nothing else is vendored. No font, stylesheet, icon set or polyfill is bundled: the viewer's type is
a system stack chosen at runtime (`--mlv-font: var(--vscode-font-family, ui-sans-serif, -apple-system,
…)` in `webview/dist/mlview.dev.css`), no `.woff`, `.woff2`, `.ttf` or `.otf` file is tracked
anywhere in the repository, and the bundle makes no network request — `webview/test/bundle.test.mjs`
asserts the built file contains no markup-string assignment, no `eval(`, no dynamic `import()` and
no `http://` or `https://` URL, in the script or the stylesheet.

## @dagrejs/dagre 3.1.1 — MIT

Directed-graph layout. Used by `webview/src/layout/layout.ts` for the `rankdir: 'LR'` pass that
positions nodes and groups; `webview/src/layout/wrap.ts` and `webview/src/layout/routing.ts` then
re-flow and route on top of its output.

* Homepage: <https://github.com/dagrejs/dagre>
* Copyright (c) 2012-2014 Chris Pettitt

```
Copyright (c) 2012-2014 Chris Pettitt

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

## @dagrejs/graphlib 4.0.5 — MIT

The graph data structure dagre is built on; pulled in transitively as dagre's only dependency, and
reached through `dagre.graphlib.Graph` in `webview/src/layout/layout.ts`.

* Homepage: <https://github.com/dagrejs/graphlib>
* Copyright (c) 2012-2014 Chris Pettitt

```
Copyright (c) 2012-2014 Chris Pettitt

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

Both files are byte-identical (`shasum -a 256` of
`webview/node_modules/@dagrejs/dagre/LICENSE` and
`webview/node_modules/@dagrejs/graphlib/LICENSE` agree), which is why the two blocks above read the
same; they are reproduced separately because each package must carry its own notice.

## The two corpora carry no third-party code

MLView is measured against two bodies of code, and **neither one puts anybody else's source in this
repository**:

* **The labelled corpus** — the 158 programs under `analyzer/tests/accuracy/corpus/`, plus
  `samples/vision_pipeline` and `samples/vision_pipeline_clean` — is written for MLView, with the
  defect in each program recorded beside it in a `labels.json`
  (`analyzer/tests/accuracy/corpus/adv_active_bad/labels.json` and 157 siblings). No file in it
  carries a copyright line, a `SPDX-` tag, an "All rights reserved" or a "licensed under": the
  programs exist to plant a specific mistake, not to reproduce anyone's project.
* **The public corpus** is a *manifest*, `analyzer/tests/public_corpus/repos.json`: 37 entries, each
  a URL, a commit SHA, a sparse-checkout path list, an SPDX id and a `redistribute` flag. Not one
  line of those repositories is committed here. `python tools/public_corpus.py fetch` clones them
  into `MLVIEW_PUBLIC_CORPUS_DIR` (default `.public-corpus/`, which `.gitignore` excludes), MLView
  reads them with `ast` and never copies them, and **every one of the 37 entries is marked
  `"redistribute": false`** — the manifest's own note explains that the flag marks source that must
  never be copied into this tree or into a build artefact, which is what keeps `yolov5`
  (AGPL-3.0-only), `stable-diffusion` (CreativeML Open RAIL-M) and `wandb-examples` (no LICENSE file
  at the pinned SHA) safe to analyse and impossible to redistribute by accident.

## Build-time and test-time only — not redistributed

None of the following reaches the wheel, the VSIX, the plugin or the report, so none of them needs a
notice above. They are listed so a reviewer can see the whole toolchain in one place.

| Package | Version | Licence | Where it is used | Why it does not ship |
|---|---|---|---|---|
| `esbuild` | 0.28.2 | MIT | bundles the viewer (`webview/build.mjs`) and the extension (`vscode-extension/esbuild.mjs`) | a bundler; its output is MLView's own code plus the two packages above |
| `typescript` | 5.9.3 | Apache-2.0 | `npm run check` type-checks the viewer and the extension | type checking emits nothing |
| `jsdom` | 26.1.0 | MIT | the viewer's DOM for `webview/test/*.test.mjs` | test-only, a `devDependency` |
| `@types/node` | 20.11.30 | MIT | extension type declarations | declarations, erased at build |
| `@types/vscode` | 1.100.0 | MIT | extension type declarations | declarations, erased at build |
| `pytest` (>=7) | — | MIT | the analyzer suite | an optional `dev` extra in `analyzer/pyproject.toml` |
| `jsonschema` (>=4) | — | MIT | `contracts/validate_sample.py` schema checks | the same optional `dev` extra; imported inside a `try`, and absent it the validator reports that it cannot schema-check rather than importing at load |

`vscode-extension/package.json` declares `"dependencies": {}`, and `vscode-extension/.vscodeignore`
excludes `node_modules/**`, so the VSIX contains no npm package at all — only `out/extension.js`
(esbuild output of `vscode-extension/src/**`, with `vscode` left external), `media/`, and the
analyzer copy under `core/`.

One third-party *document* is checked in as a test fixture and is likewise never shipped:
`analyzer/tests/fixtures/sarif-schema-2.1.0.json`, the OASIS **SARIF 2.1.0** JSON schema, against
which `analyzer/tests/core/test_sarif.py` validates what `analyzer/src/mlview/emit/sarif_out.py`
writes. It lives under `analyzer/tests/`, and the wheel packages only `mlview*`
(`[tool.setuptools.packages.find]`), so it is absent from every artifact.

## Keeping this file honest

If you add a runtime dependency to `webview/package.json`, or make the analyzer depend on a package,
add it here with its licence text copied verbatim out of the installed package — not retyped, and not
summarised to an SPDX id. `npm ls --omit=dev --all` in `webview/` prints exactly the set that has to
appear above; today it prints two lines.
