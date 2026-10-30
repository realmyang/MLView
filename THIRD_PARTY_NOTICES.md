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

## Build and test dependencies

`esbuild`, TypeScript, jsdom, `@types/node`, `@types/vscode`, and `@vscode/vsce`
are development dependencies in the npm manifests and lockfiles. `pytest` and
`jsonschema` are listed in `requirements-dev.txt`. They are not bundled into
the distributed skill or extension. The extension packages with
`--no-dependencies` and excludes `node_modules`.

The opt-in screenshot harness in `webview/tools/screenshots/` (not distributed)
holds a small table of VS Code default theme colours and an excerpt of VS
Code's default webview stylesheet, from
[microsoft/vscode](https://github.com/microsoft/vscode) (MIT License,
Copyright (c) Microsoft Corporation).

When adding redistributed dependencies, preserve their full license text here
and in the distributed package. `npm ls --omit=dev --all` in `webview/` lists
the viewer's runtime dependency tree.
