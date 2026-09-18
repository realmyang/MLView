# Third-party notices

MLView is MIT-licensed ([LICENSE](LICENSE), Copyright (c) 2026 realmyang).
The VSIX redistributes the viewer bundle, including the packages below. The
portable skill and Claude plugin use only Python's standard library.

`webview/build.mjs` bundles `webview/src/main.ts`; `tools/sync-assets.py` copies
its JavaScript and CSS into `vscode-extension/media/`. Dagre and graphlib are
inlined into the JavaScript for local graph layout. Preserve these notices
when redistributing the viewer bundle.

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

## Corpora and evaluation excerpts

The local ML examples in `samples/` and `evals/workflow/fixtures/` were
written for MLView and use the repository's MIT license.

Eight held-out repositories are pinned in `evals/workflow/repositories.json`.
Their checkouts are fetched only on request into ignored `.public-corpus/`;
complete third-party projects are not bundled into MLView distributions.

The authored-workflow reference candidates under
`evals/workflow/reference-candidates/` contain 106 exact anchors from eight
pinned repositories. Their license texts and attribution are preserved below.
These excerpts belong to the research source tree, not the VSIX, Claude plugin,
or standalone skill ZIPs.

| Reference ledger | Pinned upstream source | Upstream license file |
|---|---|---|
| nanoGPT | [`karpathy/nanoGPT@3adf61e`](https://github.com/karpathy/nanoGPT/tree/3adf61e154c3fe3fca428ad6bc3818b27a3b8291) | [Pinned MIT text](evals/workflow/reference-candidates/licenses/nanogpt-LICENSE) |
| Transformers | [`huggingface/transformers@a2c15b3`](https://github.com/huggingface/transformers/tree/a2c15b30764b7c6cb0632ac6aed6eac227edc674) | [Pinned Apache-2.0 text](evals/workflow/reference-candidates/licenses/transformers-LICENSE) |
| scikit-learn | [`scikit-learn/scikit-learn@dd3ca57`](https://github.com/scikit-learn/scikit-learn/tree/dd3ca57300e14d45b7a34fccd0165d143c7a364c) | [Pinned BSD-3-Clause text](evals/workflow/reference-candidates/licenses/scikit-learn-COPYING) |
| Flax | [`google/flax@01854da`](https://github.com/google/flax/tree/01854da11286b4109c59d7fd9205f3822fe807d6) | [Pinned Apache-2.0 text](evals/workflow/reference-candidates/licenses/flax-LICENSE) |
| Diffusers | [`huggingface/diffusers@c419dac`](https://github.com/huggingface/diffusers/tree/c419dac0152186060246c93a095bc1bfaea342b3) | [Pinned Apache-2.0 text](evals/workflow/reference-candidates/licenses/diffusers-LICENSE) |
| MMDetection | [`open-mmlab/mmdetection@cfd5d3a`](https://github.com/open-mmlab/mmdetection/tree/cfd5d3a985b0249de009b67d04f37263e11cdf3d) | [Pinned Apache-2.0 text](evals/workflow/reference-candidates/licenses/mmdetection-LICENSE) |
| CleanRL | [`vwxyzjn/cleanrl@fe8d8a0`](https://github.com/vwxyzjn/cleanrl/tree/fe8d8a03c41a7ef5b523e2e354bd01c363e786bb) | [Pinned project license and incorporated notices](evals/workflow/reference-candidates/licenses/cleanrl-LICENSE) |
| Hands-On ML notebook | [`ageron/handson-ml3@e707c2d`](https://github.com/ageron/handson-ml3/tree/e707c2d659abafb9b1f9fd927907619a128db8d7) | [Pinned Apache-2.0 text](evals/workflow/reference-candidates/licenses/handson-ml3-LICENSE) |

The excerpts retain their upstream license terms rather than becoming MLView
MIT-licensed code. Preserve the license directory, source copyright notices and
pinned source attribution when redistributing these reference ledgers.

## Build and test dependencies

`esbuild`, TypeScript, jsdom, `@types/node`, `@types/vscode`, and `@vscode/vsce`
are development dependencies in the npm manifests and lockfiles. `pytest` and
`jsonschema` are listed in `requirements-dev.txt`. They are not bundled into
the distributed skill or extension. The extension packages with
`--no-dependencies` and excludes `node_modules`.

When adding redistributed dependencies, preserve their full license text here
and in the distributed package. `npm ls --omit=dev --all` in `webview/` lists
the viewer's runtime dependency tree.
