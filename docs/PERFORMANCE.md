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
runtime/platform metadata, fixture composition, operation timings (mount,
select, SVG export, revision update, dispose), represented node count checks,
DOM element count, SVG bytes and process memory snapshots. Every authored node
ID must be represented; the run fails on hidden truncation or incomplete
disposal. The SVG export starts from the header's ⋯ menu, as a reader starts it.

Viewer M2 removed the scope picker and the export request message, so the
benchmarks no longer time "Scope to 5" or "Reset all". Those columns in the
dated tables below are historical observations of the earlier viewer; no new
baseline has been recorded since the change.

The following single-round baseline was recorded on 2026-09-18 using Node
26.4.0 on macOS 26.6.2 (25G83), arm64, against `webview/dist/mlview.js` SHA-256
`7bc843a1af4c20ce4c9914e1e81bfcc4e137cc38fadc5849890cec5049da4e29`.
Each size ran in a fresh process with exposed GC. Times are milliseconds and
are descriptive observations, not pass/fail budgets. Rebuilds after that hash
need a new run before comparing source changes.

This historical run used an early synthetic generator that the renderer could
normalize but the native artifact validator correctly rejected: its producer
host was outside the contract enum and some evidence references or bases were
invalid. The measurements remain useful only as historical renderer-shape
observations. They do not show that those fixtures were valid native artifacts.

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
run as copyable JSON. It checks represented node IDs after mount, selection
and update, and requires a real SVG `exportFile` payload.

Each browser timing is frame-inclusive elapsed time through two
`requestAnimationFrame` callbacks. That includes an opportunity for style,
layout and paint work but does not guarantee paint completed. When available,
the heap value is the browser's live JavaScript heap sampled immediately after
the revision update; it is neither total nor peak memory. Record the OS and
foreground-tab state alongside the JSON because the page cannot determine them.

## Focused Chrome baseline

The authoritative browser run on 2026-09-18 used Chrome 153.0.8010.53 on
macOS 26.6.2, arm64. It used the corrected generator at
`webview/tools/benchmark-model.mjs` SHA-256
`3ee5015a2ae136ea570bef1889e01bc189e669c17a22d252baaafa20ef7a710e`
and the built viewer SHA-256
`08346b352692bed3fb6850d9a7548a4daf3bc38eabf3acd881595607121aa536`.
All four generated documents passed the canonical artifact validator against
their synthetic source workspace before measurement. Chrome ran with a fresh,
isolated profile in a 1,440 × 900 CSS pixel page viewport and the fixed
1,200 × 650 diagram viewport at device-pixel ratio 1. The page reported
`visibilityState: visible` and `document.hasFocus(): true` before and after both
runs.

The cold run cleared the browser cache and captured a DevTools trace and CPU
sampling profile, so profiler overhead is part of its elapsed times. The warm
run repeated the complete sequence in the same page without profiling. Times
below are milliseconds.

| Run | Nodes | Mount | Select | Scope to 5 | Reset all | SVG export | Revision update | Dispose |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Cold/profiled | 100 | 101.9 | 24.7 | 15.6 | 42.6 | 23.1 | 26.7 | 14.6 |
| Warm | 100 | 33.7 | 16.3 | 16.7 | 33.3 | 24.9 | 33.3 | 16.4 |
| Cold/profiled | 500 | 509.9 | 14.4 | 16.3 | 183.5 | 53.3 | 180.2 | 16.9 |
| Warm | 500 | 199.9 | 23.1 | 17.9 | 166.8 | 41.1 | 175.2 | 15.6 |
| Cold/profiled | 1,000 | 650.3 | 23.0 | 23.6 | 576.2 | 98.7 | 672.2 | 8.7 |
| Warm | 1,000 | 600.9 | 14.8 | 16.6 | 524.5 | 86.4 | 567.0 | 10.5 |
| Cold/profiled | 2,000 | 2,220.0 | 36.3 | 31.7 | 2,174.9 | 190.9 | 2,338.3 | 17.3 |
| Warm | 2,000 | 2,006.8 | 23.8 | 35.2 | 2,082.4 | 195.9 | 2,248.0 | 16.9 |

The cold trace attributes 10,015.7 ms to script-related events, 847.0 ms to
style/layout-related events and 142.7 ms to paint events on the main thread.
These categories can overlap through nested trace events, so their totals must
not be added or interpreted as percentages of wall time. The main style/layout
events were `UpdateLayoutTree` (437.1 ms), `Layout` (317.2 ms) and `PrePaint`
(87.9 ms).

The 10,560.1 ms CPU sample identifies obstacle-aware edge routing as the main
hot spot. `blocks` accounts for 6,002.8 ms of sampled self time, followed by
`getBoundingClientRect` at 684.2 ms, `segHitsBox` at 375.1 ms and `pathCrosses`
at 369.8 ms. SVG base64 encoding accounts for 194.5 ms and cross-lane routing
for 173.1 ms. This agrees with mount, reset and revision update growing much
faster than narrow scope, selection or disposal: the current router repeatedly
scans box and ancestry geometry while rebuilding the full view.

These are two descriptive runs on one Chrome/macOS configuration, not budgets,
cross-engine claims or proof of paint completion. The warm live-heap samples
also include allocations retained from the cold run and are not leak evidence.
No optimization has been implemented or validated from this profile yet.

## Native VS Code observation

The same corrected, canonically validated fixtures and viewer bundle were also
exercised in the actual VS Code host: Code 1.138.0, Electron 42.10.0 and
Chromium 148.0.7778.280 on macOS. The webview reported a 576 × 928 CSS pixel
viewport in a split-editor layout and remained visible and focused for every
sample. Every authored node ID was represented.

| Nodes | End-to-end update latency | DOM elements | Live JS heap after update |
|---:|---:|---:|---:|
| 100 | 486 ms | 3,788 | 5,086,520 bytes |
| 500 | 832 ms | 16,034 | 15,944,290 bytes |
| 1,000 | 1,572 ms | 31,470 | 29,682,817 bytes |
| 2,000 | 4,608 ms | 62,983 | 45,047,185 bytes |

This is end-to-end observed latency from writing the watched artifact through
native validation, extension messaging, rendering, two animation-frame
callbacks and an external 100 ms polling loop. It is not a pure renderer
measurement and does not guarantee paint completion. The polling cadence also
limits timing precision. Its different Chromium version, host capabilities and
much narrower viewport mean these values and DOM counts cannot be compared
directly with the standalone Chrome table. The heap samples are live JavaScript
heap snapshots, not total or peak process memory.

## Notebook cell jumps in VS Code (viewer M3, 2026-10-02)

A synthetic notebook (200 cells, 171 of them code with outputs, 3,826,440
bytes) and a diagram citing 60 of its cells were opened in an isolated VS Code
1.139.0 Extension Development Host on macOS. A script sent 60 cell jumps
through the viewer's bridge over the DevTools protocol, either one every
150 ms ("paced") or all at once ("burst"), and recorded a CPU profile of the
extension host and of the workbench renderer (0.5 ms sampling). These are
single runs on one machine: read them as an attribution of costs, not as a
budget.

| Run | Extension host busy | MLView's own code | Hashing the notebook | Garbage collection |
|---|---:|---:|---:|---:|
| Paced, before the jump cache | 466 ms of 12.1 s | 36 ms | 93 ms (60 reads) | 45 ms |
| Paced, with the jump cache | 310 ms of 12.1 s | 45 ms | 1.3 ms (1 read) | 11 ms |
| Burst, before the jump cache | 206 ms of 3.2 s | 11 ms | 101 ms | 22 ms |
| Burst, with the jump cache | 70 ms of 3.2 s | 13 ms | none sampled | under 1 ms |

"Busy" is the profile's time not spent idle. Before the cache every jump
hashed the whole notebook again to prove it unchanged; now the first jump
hashes it once and later jumps compare the file's size, inode and times. In a burst the host opens only the last jump, and a jump a later one
has overtaken now stops before it reads the file.

The workbench renderer was busy for about 2.2 to 2.3 s of each 12 s paced run
(VS Code's own notebook and editor code); MLView runs no code there outside
its webview. Creating and then deleting 2,000 files in the workspace, in one
profiled run with counting breakpoints on MLView's listener, called MLView's
file-watcher listener 1,157 times, about 1 ms of MLView code and 5 ms of path
handling in total. Unlike the table above, these figures cannot be re-derived:
that run's output and profile were not kept. The watcher (`**/*`) shares VS Code's own workspace
watching and adds no operating-system watcher, and it has to see every cited
or inspected file, whatever its name, so it was left as it is.

With Pylance 2026.4.1 installed and a Python language server running, the same
paced run spent 42 ms in MLView's code and 528 ms busy in the extension host;
the renderer was busy for 2.6 s. The extra time is outside MLView's code (in
Pylance, VS Code's messaging and the workbench); these runs cannot divide it
further. No freeze was reproduced.
