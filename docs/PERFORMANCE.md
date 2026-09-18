# Authored workflow performance baseline

This benchmark measures the current built viewer with deterministic synthetic
WorkflowDocuments. The fixtures exercise 100, 500, 1,000 and 2,000 nodes with
cycles, groups, nested nodes, long labels, findings and evidence. They do not
describe or interpret a target program and make no semantic claims.

Run the Node/jsdom baseline after building the viewer:

```sh
cd webview
npm run build
node --expose-gc tools/benchmark-workflow.mjs
```

Pass one or more sizes to isolate their process-level memory samples, for
example `node --expose-gc tools/benchmark-workflow.mjs 2000`. Set
`MLVIEW_BENCH_ROUNDS=3` for repeated timing samples. The command emits JSON with
runtime/platform metadata, fixture composition, operation timings, represented
node count checks, DOM element count, SVG bytes and process memory snapshots.
Every authored node ID must be represented; the run fails on hidden truncation
or incomplete disposal.

The following single-round baseline was recorded on 2026-09-18 using Node
26.4.0 on macOS 26.6.2 (25G83), arm64, against `webview/dist/mlview.js` SHA-256
`7bc843a1af4c20ce4c9914e1e81bfcc4e137cc38fadc5849890cec5049da4e29`.
Each size ran in a fresh process with exposed GC. Times are milliseconds and
are descriptive observations, not pass/fail budgets. Rebuilds after that hash
need a new run before comparing source changes.

| Nodes | Edges | Mount | Select | Scope to 5 | Reset all | SVG export | Revision update | Dispose | DOM elements | Heap after update |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | 104 | 138 | 22 | 14 | 82 | 32 | 81 | 4 | 3,404 | 104 MiB |
| 500 | 525 | 875 | 47 | 39 | 769 | 86 | 764 | 20 | 13,967 | 269 MiB |
| 1,000 | 1,051 | 2,664 | 98 | 81 | 2,560 | 140 | 2,559 | 41 | 27,314 | 438 MiB |
| 2,000 | 2,104 | 9,523 | 193 | 112 | 9,432 | 275 | 9,473 | 88 | 54,614 | 857 MiB |

These are jsdom synchronous JavaScript and DOM timings. They do not measure
browser style calculation, layout, paint, compositor work, VS Code webview
startup, extension validation or message transport. jsdom's heap use is not a
browser-memory estimate. The after-dispose snapshot can retain jsdom/runtime
objects until process exit, so one run does not establish a leak.

Mount, reset-to-all and revision update track one another closely and grow much
faster than node count. At 2,000 nodes each is about 9.4–9.5 seconds, while
narrowing to a five-node scope is about 112 ms and SVG construction about 275
ms. The full view creates roughly 27 DOM elements per authored node, and
selection is also scale-sensitive. These uninstrumented totals show that work
shared by full-view mount, reset and update deserves the first profile; they do
not separate graph layout from DOM construction. Source changes should follow a
browser profile before choosing incremental updates, viewport rendering or
layout caching.

For browser layout and paint measurements, serve the repository without adding
dependencies and open the benchmark page in a foreground tab:

```sh
python3 -m http.server 8000 --bind 127.0.0.1
# open http://localhost:8000/webview/tools/benchmark.html
```

The browser page keeps the diagram visible in a reproducible 1,200 × 650 CSS
pixel viewport when page width permits. It records the browser user agent, page
and diagram viewport, device-pixel ratio and timestamp, and offers the complete
run as copyable JSON. It checks represented node IDs after mount, reset and
update, checks the scoped and reset node counts, and requires a real SVG
`exportFile` payload.

Each browser timing is frame-inclusive elapsed time through two
`requestAnimationFrame` callbacks. That includes an opportunity for style,
layout and paint work but does not guarantee paint completed. When available,
the heap value is the browser's live JavaScript heap sampled immediately after
the revision update; it is neither total nor peak memory. Record the OS and
foreground-tab state alongside the JSON because the page cannot determine them.
