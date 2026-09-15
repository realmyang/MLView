# MLView — Flow animation and scoped views

**Status:** design frozen 2026-09-07. Written by the lead from four proposals and two independent judge passes.
**Normative companion:** `docs/CONTRACTS.md` §11 carries the frozen, implementable contracts. Where this document
explains, §11 binds. Where the two disagree, §11 wins.
**Requirements:** `docs/REQUIREMENTS.md` **R2.11** (flow) and **R1.12** (scoped views).

Every number in §8 was produced by running the real projection algorithm over the real analyzed document
(`.mlview/graph.json` — `samples/vision_pipeline`, 59 nodes / 51 edges / 15 issues) and over the frozen
`contracts/graph.sample.json` (12 / 14 / 6). Nothing here is estimated.

---

## 1. The two requests

> **1.** "Make the flow of the diagram more visible: for example, when hovering the cursor over a connection,
> highlight the connection and shows the flow from outlet to inlet like a electron moving through a cable
> from one end to the other."

> **2.** "Enable visualisation for only part of a codebase/repo. For example, visualisation over a custom defined
> class for train test split, or perhaps model optimization, or perhaps evaluation on inference result."

They are one product idea in two halves. Today the diagram tells you *what is connected*; it does not tell you
*which way anything moves*, and it insists on showing you all of it. Feature 1 makes a single connection legible
as a direction. Feature 2 makes a single concern legible as a picture. Together they answer "what happens to my
inference result?" with a diagram small enough to read and a motion that says which way to read it.

### 1.1 Goals

| | Goal | How it is judged |
|---|---|---|
| **G1** | A connection's direction is unmistakable in one gesture, without reading the arrowhead. | F1-A1, F1-A2 |
| **G2** | A whole lineage reads as one current with a source and a sink, not as 18 simultaneous twitches. | F1-A4 |
| **G3** | The motion never lies: it always runs producer → consumer, never reversed to point at the cursor. | F1-A3 |
| **G4** | Motion is optional, and its absence loses no information. | F1-A6, F1-A7 |
| **G5** | A user can say "show me the evaluation path" and get exactly that, with its inputs visible as stubs. | F2-A5, F2-A6 |
| **G6** | A scope is a *view*, never a smaller analysis and never a smaller audit. | F2-A1, F2-A11 |
| **G7** | The same scope produces the same picture in Python and in the browser, provably. | F2-A12 |
| **G8** | Nothing existing regresses: every gate green, every unscoped byte identical. | F2-A13, F2-A14 |

### 1.2 Non-goals — see §10 for the full cut list with reasons

Play-the-pipeline. A travelling payload label. Direction-limited scopes (`up`/`down`). Named or bookmarked scopes.
A sixth MCP tool. Scoped diagnostics. A minimap ghost layer. Scope-aware `--max-nodes`. Any change to what the
analyzer parses.

---

## 2. Feature 1 — flow visibility

### 2.1 The mental model

An edge is a cable. It has an **outlet** on the producer, an **inlet** on the consumer, and a **charge** that
travels the cable from one to the other. Hovering a cable runs one charge along it. Hovering a card runs a train
of charges along everything the card is wired to, hop by hop, so the current visibly radiates.

### 2.2 The finding that makes this cheap

**Direction never has to be derived.** Every router in `routeEdges` (`webview/src/layout/routing.ts:205-274`)
emits `points` from the source box to the target box — `routeBack` (`:241`), `routeContainment` (`:244`),
`routeCrossLane` (`:246`) and `routeWithinLane` (`:249`) all do, and `source: bucket.s` / `target: bucket.t` are
set at `:261-262`. `points[0]` is therefore always on the producer's face and `points[n-1]` always on the
consumer's.

Consequence: animating `stroke-dashoffset` along the edge's own `d` flows **inward** on an upstream edge and
**outward** on a downstream one, with **zero reversal logic anywhere**. Upstream and downstream come out right
for free. Nothing in this design may reintroduce a per-edge direction decision.

Two more things already exist and must be reused rather than rebuilt:

- `RoutedEdge.midAngle` (`routing.ts:267`) — the direction of the path at its midpoint. This is exactly what the
  reduced-motion chevron needs.
- `edgeHoverIntent` (`canvasview.ts:399-422`) — the 400 ms open / 120 ms close delays that keep a pointer sweep
  from opening anything. Flow hangs off this, so the sweep invariant
  (`webview/test/interaction.test.mjs:104-116`) holds with no new timing model.

And one gap this closes: `.mlv-edge__hit` is `tabindex="-1"` and nothing ever focuses it
(`webview/src/render/edges.ts:66-70`), so **a connection is unreachable from the keyboard today**.

### 2.3 The object model

Four optional parts per edge, created **lazily** on first flow inside the already-debounced 400 ms callback,
and destroyed by the next `render()`:

| Part | Element | Position |
|---|---|---|
| outlet | `<circle class="mlv-edge__port mlv-edge__port--out" r="3.5">` | `route.points[0]` |
| charge | `<path class="mlv-edge__flow" pathLength="100">` with `d = route.d` | rides the visible geometry, drawn above `.mlv-edge__path` |
| inlet | `<circle class="mlv-edge__port mlv-edge__port--in" r="3.5">` | `route.points[points.length - 1]` |
| direction mark (reduced motion only) | `<path class="mlv-edge__dir">` | `route.mid`, rotated by `route.midAngle` |

Ports live in the **SVG edge layer, not on the card**. Routing is obstacle-aware (`routing.ts:85-99`), so a route
leaves an arbitrary face at an arbitrary offset and a card cannot know where its own port is. The card's
contribution is a ring: `.is-flow-source` (source card, 2 px in its stage hue) and `.is-flow-target` (target card,
2 px `--mlv-accent`). That upgrades the endpoint ring `UX_DESIGN.md` §4.5 already specifies so the two ends are
told apart.

### 2.4 Two motion modes, split by cost

**Pulse** (`.is-flowing--pulse`) — one charge, outlet to inlet, looping. Used where exactly one connection is the
subject: edge hover, edge keyboard focus, edge selection.

- `stroke-dasharray: var(--mlv-flow-head) var(--mlv-flow-len)` — exactly one 12 px charge on a cable of length L.
- `stroke-dashoffset` animates `+12px → -L`, so the charge enters at the outlet and fully exits at the inlet.
- Duration `clamp(380, round(L / 320 × 1000), 2200)` ms, written inline as `--mlv-flow-dur`. Constant apparent
  speed: a 60 px stub and a 900 px cross-lane detour read the same.

**Stream** (`.is-flowing`) — a train of charges at a constant 220 px/s. Used for node-hover lineage and focus mode,
where 3-120 edges animate at once.

- `stroke-dasharray: var(--mlv-flow-head) var(--mlv-flow-gap)`; `stroke-dashoffset: 0 → -(head + gap)`.
- Head, gap and speed are all constants, so **the period is a constant too**. Stream mode therefore needs
  **no per-edge JavaScript and no inline style except the hop delay**.

`L` is always the **polyline length** summed from `route.points` — never `path.getTotalLength()`. Verified in this
environment: jsdom does not implement `getTotalLength` (it is not a function), and `window.CSS` is `undefined`
entirely. Measuring the DOM would mean the tested path and the shipped path are different paths. `orthPath`
shortens each corner by about `0.86 × CORNER_R` (8 px), so a four-corner route's polyline is a few percent long;
at 220 px/s that is invisible, and no test may assert an exact duration.

### 2.5 The interaction table

`FLOW` below means: flow is on (`data-flow` is `motion` or `static`) and the canvas is not `data-flow="off"`.

| # | Gesture | Precondition | Effect |
|---|---|---|---|
| 1 | Pointer enters `.mlv-edge__hit` | FLOW | After the existing 400 ms open delay: that `<g>` gains `.is-flowing--pulse`; one charge travels outlet → inlet; outlet and inlet dots appear; the source card gains `.is-flow-source` and the target `.is-flow-target`; the edge label becomes visible. **Nothing dims** — this is a local read, not a trace. |
| 2 | Pointer leaves that edge | — | After the existing 120 ms close delay: every flow element is removed, all four classes and every `--mlv-flow-*` inline property are cleared. |
| 3 | `.mlv-edge__hit` takes DOM focus | FLOW | Identical to row 1, plus one aria-live announcement (`"Connection: <source label> to <target label>, <edge label>"`). |
| 4 | Click an edge (or `Enter` on a focused edge) | FLOW | The pulse **latches**: it keeps running with the pointer anywhere, so the connection can be studied. |
| 5 | Pointer enters a node card | FLOW, flow-eligible lit edges ≤ `FLOW_MAX_EDGES` | After 400 ms: the existing `.is-lit` lineage trace, and every flow-eligible lit edge additionally gains `.is-flowing` with `--mlv-flow-delay: min(hop, 6) × 90ms`. Upstream edges flow inward, downstream outward — automatically (§2.2). |
| 6 | Pointer leaves the node | — | Trace cleared; every flow element cleared. |
| 7 | `f` — focus mode on the selection | FLOW | The same stream, **latched**, so a pipeline can be read at leisure. |
| 8 | Click a node card | — | **No flow.** A flow on every click makes ordinary navigation twitch; the latched form of node flow is focus mode. |
| 9 | `e` / `Shift+E` | a node is selected | Cycle that node's incident routes **in the current projection**, selecting and `focus()`ing each `.mlv-edge__hit` in turn (row 3 then applies). Closes the keyboard gap in §2.2. |
| 10 | Toolbar flow button | — | Toggles flow entirely off/on. `aria-pressed` reflects it; the choice persists as `ViewState.flow`. |
| 11 | `Escape` | — | Dismiss cascade, in this exact order: **shortcut sheet → focus mode → scope → selection → blur**. Whichever rung fires also stops the flow that rung owned. |
| 12 | lineage exceeds `FLOW_MAX_EDGES` (120) | — | Nothing animates. `.is-lit` still applies, so the lineage still reads; the canvas takes `data-flow="static"` for the duration of that trace. Scoping the diagram (Feature 2) is the documented way to get the animation back — see §5. |
| 13 | `prefers-reduced-motion: reduce` | — | `data-motion="reduced"`; `.mlv-edge__flow` is **never built**; the static substitute of §2.8 is used instead. |

### 2.6 Cadence and colour per edge kind

Direction is never computed; only density and colour vary, so the four kinds stay distinguishable in greyscale
(R1.3). One stream speed — **220 px/s** — for every kind; the gap alone changes, so a loop looks busy and a call
looks sparse while everything moves at the same rate.

| `kind` (`subkind`) | Meaning of the charge | Stream gap | Stream period | In a lineage stream? |
|---|---|---|---|---|
| `data` | producer → consumer; the charge *is* the value | 34 px | 210 ms | yes |
| `call` | caller → callee | 96 px | 490 ms | yes |
| `control` (`enter`) | construct → body | 96 px | 490 ms | yes |
| `control` (`back`) | last statement → loop head; the recirculation | 24 px | 165 ms | yes |
| `config` | a literal reaching its consumer | — | — | **no** — pulse only, on direct hover or selection |

Period arithmetic, stated so the tokens can be checked: `(head + gap) ÷ 220 px·s⁻¹`, i.e. `(12+34)/220 = 209 ms`,
`(12+96)/220 = 491 ms`, `(12+24)/220 = 164 ms`, rounded to 210 / 490 / 165 ms.

`config` is excluded from lineage streams because config nodes are fan-out hubs (`TrainConfig()` reaches
everything), config edges are already the faintest thing on the canvas and have their arrowhead suppressed
(`webview/src/styles/edge.css:40-44, :81-83`), and including them makes a node hover look like static.

**Charge colour** resolves through existing tokens, and the two rules are written so **source order cannot decide
the winner** (the precedence bug in the original proposal):

```css
.mlv-edge[data-stage]:not(.has-issue) { --mlv-flow-color: var(--mlv-stage); }
.mlv-edge.has-issue                   { --mlv-flow-color: var(--mlv-sev);   }
```

`data-stage` is stamped on the edge `<g>` from the **source** node's stage, which makes `--mlv-stage` resolve for
free (`webview/src/styles/node.css:274-286` binds it from a bare attribute selector — worth a comment at that site,
because the selector will now also match 45-300 SVG groups). In the `hc` theme both resolve to `var(--mlv-text)` at
4 px, since high contrast has no hues.

This is the single best use of the motion in the product: edge `e:be0648ecd817`
(`model.SmallCNN --logits--> train.train.criterion`) already carries `data-sev="high"` and `class="has-issue"`
(`edges.ts:62-65`) because MLV401 is attached to it — so **the wrong tensor is literally the one you watch move
into the loss**, in red, at no extra cost.

### 2.7 Motion spec

Technique: **CSS `stroke-dashoffset` on a lazily created overlay path.** Not SMIL `animateMotion`/`mpath`, for
three reasons: SMIL `dur` is an attribute, so `prefers-reduced-motion` cannot reach it; SMIL needs per-element
`beginElement()` instead of the class toggles this viewer is built on (`canvasview.ts:9-11`, `trace.ts:1-5`) and
drifts out of phase across a lineage; and Chromium — which is the VS Code webview — has twice moved to remove it.

Two observable attributes on `.mlv-canvas`, each with one job:

| Attribute | Values | Set from |
|---|---|---|
| `data-motion` | `full` \| `reduced` | `matchMedia('(prefers-reduced-motion: reduce)')`, re-read on its `change` event |
| `data-flow` | `motion` \| `static` \| `off` | `off` when the user toggled it off; `static` when `data-motion="reduced"` **or** the current trace exceeds `FLOW_MAX_EDGES`; `motion` otherwise |

Both are assertable in a runner that executes no CSS animations at all, which is the whole point.

Tokens (`webview/src/styles/tokens.css`, light `:root`; two overrides in the `hc` block):

```
--mlv-flow-speed:        220;      /* px/s, stream — documentary; the three durations below encode it */
--mlv-flow-pulse-speed:  320;      /* px/s, single pass */
--mlv-flow-head:         12px;     /* charge length */
--mlv-flow-gap:          34px;     /* data */
--mlv-flow-gap-call:     96px;     /* call, control:enter */
--mlv-flow-gap-back:     24px;     /* control:back */
--mlv-flow-dur-data:     210ms;    /* (12+34)/220 */
--mlv-flow-dur-call:     490ms;    /* (12+96)/220 */
--mlv-flow-dur-back:     165ms;    /* (12+24)/220 */
--mlv-flow-dur-min:      380ms;    /* pulse clamp */
--mlv-flow-dur-max:      2200ms;
--mlv-flow-hop:          90ms;     /* per-hop wave delay, capped at 6 hops */
--mlv-flow-width:        3px;
--mlv-flow-port-r:       3.5px;
--mlv-flow-color:        var(--mlv-accent);   /* fallback; overridden per §2.6 */
```

No new colour needs a `@contrast:` annotation: every flow colour is an already-annotated token
(`--mlv-sev*`, `--mlv-stage*`, `--mlv-accent`, `--mlv-text`), and the flow path carries no text.

**Nothing animates that the user did not cause**, and nothing loops without a live pointer, focus, selection or
focus-mode latch — `UX_DESIGN.md` principle 5 (line 14) and §11 (line 517).

### 2.8 Reduced motion — the trap, and the substitute

`webview/src/styles/base.css:207-213` already clamps every animation under `prefers-reduced-motion`:

```css
animation-duration: 0.01ms !important;
animation-iteration-count: 1 !important;
```

That **freezes** an animation; it does not remove it. Relying on it alone would park a 12 px charge stub at the
outlet of every flowing edge — a bug that reads as a rendering fault, not as a preference. So reduced motion is
handled twice, deliberately:

1. **JS:** when `data-motion="reduced"`, `.mlv-edge__flow` and the ports' arrival animation are **never created**.
2. **CSS:** `@media (prefers-reduced-motion: reduce) { .mlv-edge__flow { display: none !important } }`, so a stale
   element from a mid-session preference change cannot appear.

The substitute carries the same information with no motion, and is what `UX_DESIGN.md:343` already promised plus
direction:

- the cable goes 2.5 px `--mlv-accent` (the promised "static double-width stroke");
- a `.mlv-edge__dir` chevron sits at `route.mid`, rotated by `route.midAngle` — pointing at the inlet;
- the ports are drawn statically: **outlet hollow, inlet filled**;
- the `.is-flow-source` / `.is-flow-target` card rings still apply.

A reduced-motion user still learns which end is which, in one glance, from three redundant cues (chevron, hollow
vs filled, ring hue).

A per-edge `<linearGradient>` was considered for the static cue and rejected: it needs a uniquely-id'd `<def>` per
flowing edge, and the codebase already assumes globally unique ids for its arrow markers (`edges.ts:38-42`); a
second id namespace is not worth one gradient.

### 2.9 Performance

- **45-edge sample:** hovering `train.train` lights ~16 edges → 16 thin animated strokes. Comfortably inside a frame.
- **150-node / 300-edge synthetic** (`webview/test/helpers.mjs:132`): a hub node can light most of the graph.
  `FLOW_MAX_EDGES = 120`; above it the trace goes `data-flow="static"` and nothing animates.
- `stroke-dashoffset` is not GPU-composited in Chromium — it repaints the edge layer every frame. That is the
  accepted cost, capped at 120 strokes. Therefore: **no `will-change`** (it would promote 120 layers for nothing),
  **no `filter: drop-shadow`** anywhere (it forces a filter-region repaint per frame), and **no halo** — the pulse
  halo is cut.
- Lazy creation happens inside the 400 ms hover callback, never on `pointerenter`, so a pointer sweeping the canvas
  allocates nothing.
- A hidden VS Code panel pauses CSS animations for free. Because play-mode is cut, there is no `setTimeout` chain
  and therefore no timer to leak into a hidden panel.

### 2.10 Accessibility

- Flow announcements happen **only** for keyboard-driven flows (rows 3 and 9). Announcing on pointer hover would
  narrate every mouse sweep into the live region — the aural equivalent of the strobing the 400 ms delay exists
  to stop.
- `edgeAria` (`edges.ts:105-109`) gains the direction in words:
  `"data edge labelled logits, flows from SmallCNN to criterion. Activate to open the call site."`
  This requires endpoint labels, so `EdgeVisual` gains optional `sourceLabel` / `targetLabel`, filled by
  `render/scene.ts` from the index it already has.
- The flow toolbar button is a real `aria-pressed` toggle with a title that names the current state.
- Nothing in the flow layer carries a `data-*-id`, so `webview/test/parity.test.mjs` (identical id sets across the
  two bridges) is unaffected by construction.

### 2.11 Acceptance criteria

| ID | Pri | Criterion |
|---|---|---|
| **F1-A1** | P0 | Hovering an edge for 400 ms gives its `<g>` `.is-flowing--pulse`, one `.mlv-edge__flow` whose `d` **equals** `.mlv-edge__path`'s `d`, and two `.mlv-edge__port` circles whose `(cx,cy)` equal the first and last coordinate pair of that `d`. `pointerleave` + 200 ms removes all of it and every `--mlv-flow-*` inline property. |
| **F1-A2** | P0 | The source card carries `.is-flow-source` and the target `.is-flow-target` while a single edge flows; a re-render leaves neither behind. `.mlv-edge__hit`'s `aria-label` matches `/flows from .* to .*/` and names both endpoint labels. |
| **F1-A3** | P0 | Duration is computed from `RoutedEdge.points` only: `pulseDurationMs(160) === 500`, `pulseDurationMs(40) === 380`, `pulseDurationMs(4000) === 2200`; a longer route yields a strictly larger `--mlv-flow-dur` until the clamp. A source scan of `webview/src` finds **zero** occurrences of `getTotalLength`. |
| **F1-A4** | P0 | Hovering `train.train` gives every flow-eligible `.is-lit` edge `.is-flowing` and an inline `--mlv-flow-delay`; an edge two hops out carries `180ms` where a one-hop edge carries `90ms`; unlit edges carry neither; `config`-kind edges are `.is-lit` but never `.is-flowing`. |
| **F1-A5** | P0 | Clicking an edge leaves `.is-selected.is-flowing--pulse` applied one second later with no pointer over it; `Escape` clears both. Clicking a node card produces no `.is-flowing*` anywhere. |
| **F1-A6** | P0 | With `matchMedia` stubbed to match `(prefers-reduced-motion: reduce)` **before** mount: `.mlv-canvas` has `data-motion="reduced"`, the document contains **zero** `.mlv-edge__flow`, hovering an edge still yields two ports and exactly one `.mlv-edge__dir` carrying a `rotate(` transform, and `dist/mlview.css` contains a `prefers-reduced-motion` block naming `mlv-edge__flow`. |
| **F1-A7** | P0 | The toolbar flow button starts `aria-pressed="true"`; clicking it gives the canvas `data-flow="off"` and hovering an edge then builds no flow element. The recording bridge's last saved state has `flow === false`; remounting with that state restores both. |
| **F1-A8** | P0 | On `makeSyntheticGraph(150, 300)`, hovering the highest-degree node yields `document.querySelectorAll('.mlv-edge.is-flowing').length === 0`, `data-flow="static"`, and `.is-lit` still applied to more than 120 edges. |
| **F1-A9** | P0 | Edge `e:be0648ecd817` carries `data-sev="high"`, `has-issue` and `data-stage="model"`; `dist/mlview.css` contains `.mlv-edge.has-issue` setting `--mlv-flow-color` to `var(--mlv-sev)` and `.mlv-edge[data-stage]:not(.has-issue)` setting it to `var(--mlv-stage)`. Reordering the two rules cannot change the result. |
| **F1-A10** | P1 | With a node selected, `e` selects exactly one incident edge, focuses its `.mlv-edge__hit`, pulses it, and puts both endpoint labels in the live region; `Shift+E` moves to a different edge id and branches on `ev.shiftKey` explicitly. `KEYMAP` contains rows for `e` and `Shift+E`, so the `?` sheet lists them. |
| **F1-A11** | P0 | `npm test` in `webview/` passes unchanged with the new suite added — in particular the pointer-sweep invariant (`interaction.test.mjs:104-116`: no flow element is created during a sweep), `parity.test.mjs` (identical id sets), and `layout.test.mjs` (150 nodes under 300 ms with the polyline length computed). |

### 2.12 Amendment (2026-09-08) — the charge is a dot, and Go to never blanks the report

Two changes, both renderer-local, both normative in `CONTRACTS.md` (§11.13.1 and §11.17).

**The charge is a dot with a halo, not a line.** §2.7 specified the single-connection charge as a 12 px dash head
sliding along `stroke-dashoffset`. On a 3 px stroke, in a diagram made of 3 px strokes, that reads as a *brighter
piece of cable* rather than as something travelling *through* one — the mental model of §2.1 never actually
appeared on screen. A pulse now draws `<g class="mlv-edge__charge">`: three concentric circles — halo `r 9` at
~0.18 alpha, glow `r 5.5` at ~0.42, and a `--mlv-surface`-filled core `r 2.6` ringed in `--mlv-flow-color` —
moved by a SMIL `<animateMotion calcMode="linear" rotate="auto">` whose `<mpath>` rides the edge's own
`.mlv-edge__path`, at the same `pulseDurationMs` speed §2.7 fixed. The soft edge is stacked opacity, never
`feGaussianBlur`: a filter region on a moving element is re-rasterized every frame, which §2.9 rules out. A route
longer than 360 px carries a second dot at `begin="-<dur/2>ms"` so the cable is never empty. `.mlv-edge__flow`
stays on a pulsing edge as a *static* full-length wash, because that is what keeps `--mlv-flow-color` on the
whole cable — the severity connection reads red along its length, not only under the dot. The **lineage stream
of §2.6 is unchanged**: there the question is density per hop, which a dash pattern answers in one glance and
thirty independent dots do not, and a stream may light up to `FLOW_MAX_EDGES` cables where one SMIL timeline per
edge buys nothing. Reduced motion is unaffected in intent and stricter in mechanism: SMIL ignores the CSS
`animation-duration` clamp, so the charge group carries its own `display: none !important` under
`prefers-reduced-motion`.

**Opening code from the standalone report never navigates the report.** §5.1 has the report open a location at
`vscode://file/…`; the implementation clicked a hidden same-frame `<a>`. Embedded in a sandboxed iframe — which
is how a report is shared on claude.ai — that is a top-level navigation to a forbidden scheme, so the browser
replaces the frame with *"This content is blocked. Contact the site owner to fix the issue."* and the diagram is
gone. Every path that opens code went through it: the Issues rail's **Go to**, the Inspector's **Open
`file:line`**, the related-location links, and node and edge clicks. The outcome is now decided by one pure
function of two booleans — `embedded` (`window.self !== window.top`, a throw counting as embedded) and `local`
(`location.protocol === "file:"`). Top-level **and** local hands the URL to the OS through a throwaway hidden
`<iframe>`, keeping the existing 400 ms blur fallback. Every other case copies `file:line` and raises a toast
carrying an **Open in VS Code** anchor with `target="_blank"`, which a permissive host follows and a sandbox
without `allow-popups` silently drops. The report itself does not move in any branch.

---

### 2.13 Amendment (2026-09-08) — the dot travels, and the toast is a control

Follow-up to §2.12, renderer-local, normative in `CONTRACTS.md` §11.13.2 and §11.17.1. Everything below was
measured in Chromium against the shipped `.mlview/report.html`, not inferred.

**The dot now leaves the outlet.** `<animateMotion>` with no `begin` starts at `0s` on the *SVG document*
timeline, which has been running since the page loaded — so a dot built inside a hover callback appeared at
`(page uptime mod dur) / dur` along the cable. Over twelve hovers of one 1269 ms cable the first painted
position was 0.44, 0.22, 0.16, 0.15, 0.05, 0.99, 0.96, 0.82, 0.66, 0.49, 0.40, 0.36: scattered, never at the
outlet, and about one hover in four spent its whole visible life beside the *inlet* — the destination — after a
400 ms hover-intent dwell the reader had already paid for. Each pulse now reads the owning `<svg>`'s clock once
and anchors both dots to it (`begin="<t0>s"`, the twin at `t0 - dur/2`), so the travel starts where the gesture
does. Re-measured after the fix: 0.000 on all twelve hovers.

**And it arrives.** `repeatCount="indefinite"` wraps in one frame, so a charge at fixed opacity blinked out at
the inlet and in at the outlet ~190 px away (~640 px on a long route), once per 0.4–2.2 s for as long as the
pointer rested. A dash *texture* can wrap unnoticed; a single trackable bead teleporting reads as a glitch. The
charge now fades over the first and last 8% of its cycle, driven by the same `--mlv-flow-dur` — `opacity` on an
element the compositor is already moving, so §2.9's ban on filters and `will-change` is untouched, and §2.8's
`reduce` path still removes the dot outright rather than fading it.

**High contrast gets the ring back as geometry.** §2.6 resolves both colour rules to ink in hc, which made the
halo the same white as the cable it rides: the "hue around the dot" delivered without hue. In hc the halo is now
an outline circle — `fill: none`, `stroke: var(--mlv-text)` at 1.2 px, `r 9` — which is legible on both hc
grounds and invents no hue that theme has ruled out.

**A motion-preference flip mid-session rebuilds what was running.** Flipping to `reduce` used to strip a
selected or keyboard-focused connection of its charge *and* of the ports and chevron §2.8 promises in its place,
and flipping back restored neither: the reduced-motion reader, the one audience with no animation to fall back
on, was left holding a connection that was emphasised, focused, and pointed nowhere. The watcher now re-runs the
live rung, exactly as the flow toggle does.

**Apparent pulse speed is clamp-bound, and the docs now say so.** §2.4's `clamp(380, L/320 × 1000, 2200)` is
unchanged, but both clamps bind in the shipped sample — a 72 px call edge runs at 0.59x nominal, a 2128 px data
edge at 3.02x, a 5.1x spread under one gesture. That was invisible as a scrolling dash and is legible as a
single bead. Changing it means changing F1-A3 and three docs, so it is recorded here rather than done quietly.

**The toast that §2.12 left behind is now a control.** In every embedded or `http(s)` report the toast IS the
whole outcome of **Go to** / **Open `file:line`** / a node click, and its anchor is the only affordance. It had
no `role` and no live region, so a screen-reader user pressing "Open model.py:34" was told nothing at all; the
anchor sat 17 Tab presses away inside a hard 3000 ms life; and a second message stacked an opaque card exactly
on top of the first, burying a live link that stayed in the tab order. Floating messages now share one
persistent `role="status"` host holding exactly one card, the timer holds while the pointer or focus is on it,
and a keyboard-raised toast puts focus on its anchor and hands focus back when it goes. The deep-link path is
percent-encoded, so a checkout under `…/issue#1/…` no longer produces a link to a different file; a location
with no absolute path offers no anchor at all; and a run of clicks invokes the OS handler once rather than six
times at once. In a sandbox without `allow-popups` the anchor click still does nothing visible — that is the
safety §2.12 bought — so the message it sits on now stays put while the reader is reading it.

---

## 3. Feature 2 — scoped views

### 3.1 The one-sentence definition

> **A scope is a pure projection of the finished whole-workspace graph document. It is never a smaller set of
> files handed to the parser, and never a smaller audit.**

The analyzer always walks the whole workspace, so cross-file resolution and workspace-wide rules (MLV601, "no seed
anywhere") keep working. Then one function, `project(doc, scope) -> doc'`, filters the already-sorted arrays and
re-derives the aggregates. `--include` / `--exclude` remain what they are — **discovery** filters that genuinely
change the analysis — and the docs must keep saying so, because that is the confusion this feature invites.

### 3.2 The scope model

A scope is `(kind, target, depth)`. One string on every surface:

```
<kind>:<target>        e.g.  unit:sklearn_baseline.baseline
                             concern:evaluation
                             stage:train
                             file:train.py
```

| kind | target | seed set = nodes where… | default depth |
|---|---|---|---|
| `unit` | a qualname, an FQN, a bare class/function name, or a node id | tiered resolution (§3.3), **plus the whole descendant subtree** | 1 |
| `stage` | one of the eight `StageId`s | `node.stage == target` | 0 |
| `file` | a workspace-relative path (forward slashes), or a bare basename | `loc.file == target`, else basename match | 0 |
| `concern` | one of four presets, or an alias | `node.stage` ∈ the preset's stages | 0 |
| `node` | a node id (`n:…`) — **legacy pinpoint selector, kept for MCP compatibility** | that node alone, **no** descendant closure | 1 |

`symbol:` is accepted and **normalized to `unit:`** — one line in the parser, because "symbol" is the word the
user, the docs and every model will reach for first.

**Why `unit:` also takes a node id:** the tools hand back ids; a human types a qualname. Both must work or someone
has to translate.

**Why `unit:`/`node:` default to depth 1 and the others to 0:** a unit or a node is a *point*, and its interface is
most of what you came to see; a stage, a file or a concern is already a *region*, and a ring around a whole lane is
mostly noise. Verified consequence: `node:<id>` at depth 1 produces **exactly** the node set that today's
`neighbourhood_ids(graph, id, 1)` produces on the sample — zero churn for the most common existing MCP call.

**Concern presets (FROZEN).** Four presets **partition** all eight stages, so no stage is unreachable and no stage
is claimed by two concerns:

| concern | stages | aliases |
|---|---|---|
| `config` | `config` | `setup` |
| `data` | `data`, `preprocess` | `preprocessing`, `dataset` |
| `optimization` | `model`, `objective`, `train` | `training` |
| `evaluation` | `eval`, `deliver` | `inference`, `eval` |

An alias resolves **before** validation; `view.scope` always records the canonical name, so `concern:inference` and
`concern:evaluation` produce byte-identical documents.

**`depth`** is an integer `0..2` counting hops along real `edges[]`. **Containment is not a hop** — parents come
from the ancestor closure (§3.4 step 4), children only from the `unit:`/`node:` descendant closure. That is what
makes `depth` mean exactly one thing, and makes it monotone and testable.

**Direction is cut.** `both` is the only behaviour. `both` at depth 1 covers every demo in every proposal;
`up`/`down` would double the parity battery and add a second axis to every CLI, MCP, protocol and UI shape for a
gesture nobody needed at depth 1.

### 3.3 `unit:` resolution — tiered, first non-empty tier wins

Resolution runs against the **finished graph document**, never the IR. That is precisely what lets TypeScript
resolve identically with no analyzer.

0. `target` ends with `()` → strip it. `target` starts with `n:` and matches a node id → that node, done.
1. `node.qualname == target` (`unit:sklearn_baseline.baseline`, and the disambiguated form `unit:data.ToTensor#2`)
2. `node.fqn == target` (`unit:torch.optim.Adam`)
3. last dotted segment of `qualname == target` **and** `node.level ∈ {stage, unit}` — i.e. a *definition*
4. last dotted segment of `qualname == target`, any level — call-site ops
5. `node.label == target` or `node.label == target + "()"`

Then tiers 1-5 again, ASCII-case-insensitively, emitting a `config_warning` diagnostic naming the canonical
spelling on a hit. Same exact-then-insensitive fallback for `file:`.

Tier 3 is what makes `unit:train` mean the function `train.train` (a 10-node subtree) rather than also dragging in
the unrelated `model.train()` op node `train.train.train`. Verified. `unit:train_test_split` has no tier-3 match
and correctly falls to tier 4, landing on the call-site op.

**Ambiguity is reported, never silently narrowed.** *Every* node in the winning tier becomes an anchor,
`view.resolvedTo` lists them all, `view.ambiguous` is `true`, and a `config_warning` names the qualnames that would
disambiguate. Verified on the sample: `unit:batch_loop` resolves to **two** anchors —
`train.train.batch_loop` and `train.validate.batch_loop` — and shows both.

### 3.4 The projection algorithm, step by step

Input: a finalized, schema-valid document `D` and a `Scope`. Output: a finalized, schema-valid document `D'`.
Pure — no filesystem, no IR, no randomness, no clock.

1. **Seeds.** Per the §3.2 table.
2. **Core.** For `unit:` and `node:` — wait, precisely: for `unit:`, `core` = the seeds ∪ their transitive
   **descendant** closure over `parent` (a unit means its whole definition, not just its header card). For
   `node:`, `core` = the seed alone. For `stage:`, `file:`, `concern:`, `core` = the seeds as-is — those kinds
   already denote a set, and a descendant closure would drag in nodes that are by definition outside it
   (`train.train.device` is stage `config` but a child of `train()`; `stage:train` must not swallow it).
3. **Boundary.** BFS over `edges[]` in both directions, `depth` rings from `core`. `boundary` = everything
   reached, minus `core`.
4. **Context (ancestor closure).** For every node in `core ∪ boundary`, walk `parent` upward, adding each ancestor
   not already kept. `context` = the ancestors added this way.
5. **Edges.** Keep edge `e` iff `e.source ∈ kept ∧ e.target ∈ kept`, where `kept = core ∪ boundary ∪ context`.
6. **Issues.** Retain issue `I` iff **either** some `n ∈ I.nodeIds` is in `core`, **or** some `id ∈ I.edgeIds` names
   a kept edge whose **both** endpoints are in `core`. Then:
   - `I.nodeIds ← [n for n in I.nodeIds if n ∈ kept]`, order preserved;
   - **re-anchor:** if `nodeIds[0] ∉ core`, **stably rotate** the first core element to the front (the rest keeps
     its relative order). This keeps invariant 1.1.3 true *and* puts the badge on a real card instead of a faded
     boundary stub;
   - `I.edgeIds ← [e for e in I.edgeIds if e is a kept edge]`.
   Suppressed issues follow the same rule and stay `suppressed: true`.
7. **Ghost pruning.** Drop any kept node with `ghost: true` whose `issueIds` contain no retained issue, then
   re-filter edges and every `I.nodeIds`; drop any issue whose `nodeIds` became empty. This is
   `_drop_orphan_ghosts` (`analyzer/src/mlview/core/pipeline.py:257`) applied to the projection, and it is what
   keeps invariant 1.1.8 true.
8. **Node roles.** Every kept node gets `viewRole: "core" | "boundary" | "context"`. `n.issueIds` is filtered to
   retained issues.
9. **Aggregates.** `stages[]` stays **all eight rows in `order`**. `stage.nodeCount` counts kept nodes of that
   stage in **all three roles** — it must describe the picture that is drawn. `stage.issueCounts` and
   `stage.maxSeverity` are recomputed over retained non-suppressed issues. **`stage.present` is carried through
   from `D` untouched** (§3.6). `stats.nodes` / `stats.edges` are the kept counts; `stats.issues` and
   `stats.suppressed` the retained counts; `stats.truncated` and `stats.durationMs` are carried through.
10. **Carried verbatim.** `schemaVersion`, `generator`, `workspace` (every field), `diagnostics`. A projection
    **never restates project-level truth**: `root`, `entrypoints`, `filesAnalyzed`, `filesFailed`,
    `notebooksSkipped`, `frameworks` and `configPath` all describe the analysis, which really was
    whole-workspace. Scope diagnostics are appended and the array re-sorted by its existing key.
11. **`view`** is appended as the **last key** of the document.

**The ordering invariant — and why parity is affordable.** Steps 1-10 only *remove* elements from arrays that are
already canonically sorted, and only *filter* the `nodeIds` / `edgeIds` / `issueIds` lists. **No output array is
ever re-sorted, so the TypeScript port never reimplements a comparator** and cannot drift on ordering. The single
non-filter operation in the whole algorithm is the stable rotation in step 6, specified as a rotation precisely so
both languages produce the same list. This is a normative property, not an implementation note: a port that sorts
anything is wrong even if its output happens to match.

### 3.5 Edge cases, decided

| Case | Behaviour |
|---|---|
| Grammatically valid selector that matches **no** nodes (`concern:deliver`, `unit:Nope`) | A **valid, empty document**: all eight stage rows with `nodeCount: 0`, empty `nodes`/`edges`/`issues`, `view.empty: true`, `view.resolvedTo: []`, plus a `config_warning` diagnostic naming the whole-graph size. **Exit 0.** "This concern does not exist in this codebase" is a finding, exactly as `mlview_payloads.py:270-274` already treats an absent stage. |
| Grammatically invalid selector | Usage error: **exit 1**, an error **code** plus the offending term plus a sorted, ≤10-entry candidate list on **stderr**, stdout untouched. Codes: `bad_selector`, `unknown_stage`, `unknown_concern`, `unknown_node`, `unknown_file`, `unknown_unit`, `bad_depth`. Only the codes, the term and the candidate list are contractual — **message prose is free**, so nobody maintains two English strings in two languages. |
| `depth` outside `0..2` | `bad_depth`, exit 1. |
| Ambiguous `unit:` | All anchors kept; `view.ambiguous: true`; `config_warning` naming the disambiguating qualnames. Never a silent "best" pick. |
| A `context` ancestor whose only descendants are `boundary` | Kept. It is a frame around drawn cards; dropping it would re-orphan them. |
| `parent` crossing a stage lane (`train.train.device` is `config` under a `train` parent) | Untouched. Roles are assigned per node; the containment forest is preserved exactly. |
| An issue anchored on a ghost (MLV201 → `__ghost_zero_grad`, MLV301 → `__ghost_model_eval`) | The ghost is an ordinary node for retention; if the ghost is core the issue is retained and the ghost survives step 7. |
| An issue whose only `core` member is its **second** anchor (MLV401 under `unit:SmallCNN`) | Retained, and `nodeIds` rotates from `[criterion, SmallCNN]` to `[SmallCNN, criterion]` so the badge lands on the core card. **Verified.** |
| Boundary→boundary edge between two drawn cards | Kept. It is truth, not noise. A hop-difference rule would strand ring-2 nodes at `depth: 2` and would have to be ported identically for no gain. |
| `--max-nodes` and `--scope` together | The cap stays **before** projection, where it already lives (`pipeline.py:166`), and is not re-applied. Moving it after would make Python (project→cap) and TypeScript (already-capped→project) disagree whenever the cap binds, which kills parity. Disclosed with a `truncated` diagnostic mentioning scoping, and `view.of.nodes` always reports the pre-projection count. |
| `--fail-on` with `--scope` | Evaluates the **retained** issues, which is what makes `--scope unit:baseline --fail-on high` a useful per-module gate. The CLI prints the scope on the stderr `--fail-on` line so the narrowing is visible in a CI log. |
| A saved `ViewState.scope` that no longer resolves after a re-analysis | The scope is dropped, the full graph is shown, and a toast says "Scope no longer matches — cleared". |
| An out-of-scope node is explicitly revealed (`revealNode`, Alt+M, an issue row) | The scope **auto-clears**, the node is centred, and a toast offers **Undo**. An explicit navigation beats a scope set two minutes ago; today's path toasts "Node not found in this graph" (`app.ts:629`), which under a scope is a false statement. |
| Search under a scope | Search always runs over the **full** graph, so a scope is never a trap. An out-of-scope hit is tagged, and activating it takes the row above. |
| Collapse state under a scope | The collapse set is held against the **full** id space and filtered at projection time, so collapsing inside a scope and then clearing it does not lose the collapse. |

### 3.6 `stage.present`, and the two defects that carrying it through exposes

`stage.present` is **project-level truth** and is carried through a projection unchanged. This is not a
preference; it is a fix for a confirmed defect documented at `claude-plugin/server/mlview_views.py:11-17` and
`:88-96`: a filtered view that recomputed `present` told the model that seven stages the project actually has
were missing, and `claude-plugin/commands/mlview.md` instructs the model to report exactly that as a finding.

Carrying it through correctly at the document level breaks **two** consumers that assume otherwise. Both are P0
and both must land in the same change.

**Defect 1 — empty swimlane bands (TypeScript).** `webview/src/layout/model.ts:87` admits a lane when
`s.present || rootsByLane.get(s.id).length > 0`. Verified. The comment at `mlview_views.py:96` claiming
"renderers already skip a lane with no nodes in it" is **false for this renderer**. Under
`concern:evaluation` at depth 1 on the sample, `config` and `objective` are `present: true` with `nodeCount: 0`
— **two empty bands would be drawn**, and a scope with a narrow core can produce up to seven.

> **Fix:** while the document carries `view`, a lane is admitted only when it has drawn roots. The
> excluded-but-present stages are surfaced in a **"not in this scope"** chip row beside the existing
> "not detected" row (`ui/chrome.ts:236-241`), so the information is not lost — it is correctly labelled.

**Defect 2 — the contract validator (Python).** `contracts/validate_sample.py:300-301` asserts
`present == true ⟹ (nodes or issues)`. Verified by running it against a real projection:

```
FAIL p.json - 2 problem(s):
  - stages: stage config is present but has neither nodes nor issues
  - stages: stage objective is present but has neither nodes nor issues
```

So **every scoped document fails the contract validator today**. The same assumption is hard-coded at
`analyzer/tests/core/test_graph_invariants.py:151`.

> **Fix:** the invariant becomes conditional. In `validate_sample.py`, guard the `elif not nodes and not
> any(counts.values())` branch with `and doc.get("view") is None`; in `test_graph_invariants.py:151`, assert the
> equality only for documents without `view`, and for projections assert the weaker, correct pair:
> `present == D.present` (carried through) and `nodeCount == len(kept nodes in that stage)`.

No proposal and no judge caught Defect 2. It was found by running the projection through the shipped validator,
which is exactly why the parity fixture (§7) validates every case rather than only comparing ids.

### 3.7 The scoped view — entering, reading, living in it, leaving

**Entering.** Two entry points in v1, both keyboard-reachable:

1. **Inspector → "Scope to this"** (`ui/rail.ts:402-410`, under the existing Open/Ask row). Reads
   *"Scope to this unit"* for a `unit`/`stage`-level node and *"Scope to this step"* for an `op`.
2. **The scope picker in the toolbar** — a button labelled with the active scope, default **"Everything ▾"**. Its
   menu lists *Everything*, the four **Concerns** with live counts, each present stage, and each scopable unit
   (any node with children, or `level ∈ {stage, unit}`) grouped by file and labelled
   `baseline() · sklearn_baseline.py:18 · 13 nodes`. A concern that matches nothing renders disabled as
   *"not detected in this project"* — itself a finding.

Plus `s` on a selection, `Shift+S` to clear, `]`/`[` to step depth, and — only if it costs nothing —
`Shift+Enter` on a search row.

**Reading.** A breadcrumb chip, first element after the brand, `role="status"`. This is the `Breadcrumb`
component the inventory at `docs/UX_DESIGN.md:559` already reserves:

```
⤢  Scoped to baseline()  ·  depth 1  ·  13 of 59 nodes    [−] [+]    [×]
```

- The `13 of 59` comes from `view.of.nodes` — **project-level truth**, so a scoped view can never be read as a
  statement about the project.
- `title` carries the raw selector; an overflow item **Copy scope** puts `unit:sklearn_baseline.baseline` on the
  clipboard, ready to paste into `/mlview --scope`.
- `[−]/[+]` step depth, debounced 120 ms because each step is a relayout. `[×]` clears.
- The `[×]` tooltip reads **"Clears the scope. Filters are separate."** — the one sentence that keeps the two
  narrowing concepts apart.
- Under `stats.truncated` it reads `13 of 400 shown` and the truncation banner stays up.

**Boundary and context, rendered.** A `boundary` card is drawn in its real lane, 1 px dashed, its label in a
declared `--mlv-fg-boundary` token (never opacity alone — that is how the contrast gate is passed), and it carries
**no severity badge**: its findings are out of scope and a badge you cannot open is a lie. Its accessible name ends
`", outside the current scope"`. A `context` node draws as an **empty frame** — the containment box with its header
and nothing claimed inside it.

**The issue rail** shows only retained findings and always says how many are hidden:

```
3 of 15 findings shown · 12 outside this scope — Show all
```

`Show all` clears the scope. A **fourth** empty state joins the three the rail already tells apart
(`ui/rail.ts:181-186`): **"No findings in this scope"** with *"15 elsewhere — Show all"*, distinct from
"No issues found" (a clean bill of health) and "No issues match these filters". Getting these apart is what stops a
scope from reading as a clean bill of health.

**Empty scope** gets its own designed state — *"Nothing in this scope · `unit:model.Foo` matched no nodes"* with
**Widen (+1 hop)** and **Clear scope** — not the filter-empty state (`ui/states.ts:68`), which would say the wrong
thing.

**Leaving.** `[×]`, `Shift+S`, `Show all`, the picker's *Everything*, or the `Escape` cascade (§2.5 row 11).
Clearing restores the **viewport and the selection** from before the scope was set, so `[×]` feels like a back
button rather than a reset.

### 3.8 Scope is not a filter — and the UI must say so

Two narrowings now live on one screen, which is the real usability risk:

| | Stage **filter** chips | **Scope** |
|---|---|---|
| Mechanism | dims (`webview/src/filters.ts:81-84`) | removes and relayouts |
| Control | the chip row | the breadcrumb and the picker |
| Cleared by | "Clear filters" | `[×]` / `Shift+S` |
| Affects each other | never | never |

Mitigation, stated once and enforced: the two are named differently wherever they meet
(*"Show only these findings"* vs *"Scope diagram to this stage"*), `[×]`'s tooltip says "Filters are separate", and
clearing one never clears the other.

### 3.9 What a scope never does

- It **never changes what the analyzer parses**. `workspace.filesAnalyzed` is identical with and without `--scope`.
- It **never changes the VS Code Problems panel, the status-bar count, or the issue quick pick.** A view must not
  quietly reduce the number of defects a developer is told about. `vscode-extension/src/diagnostics.ts` is
  **deliberately untouched** by this feature, and a test asserts `DiagnosticsPublisher` output is byte-identical
  while scoped.
- It **never restates project-level truth**: not `workspace.*`, not `generator.*`, not `stage.present`, not
  `view.of`.
- It **never re-sorts** an array.
- It **never appears in an unscoped document.** No `--scope` → no `view` key, byte-identical output to today.

### 3.10 Acceptance criteria

| ID | Pri | Criterion |
|---|---|---|
| **F2-A1** | P0 | Analysis stays whole-workspace: for every battery scope, `workspace.filesAnalyzed`, `filesFailed`, `notebooksSkipped`, `frameworks`, `entrypoints`, `root` and `generator.*` are byte-identical to the unscoped run, and MLV601 (a workspace-wide rule) still fires in the unscoped document. |
| **F2-A2** | P0 | `project(doc, scope)` is pure and produces a schema-valid document: every battery case validates against `contracts/graph.schema.json` **and** passes `contracts/validate_sample.py`'s invariant groups (with the §3.6 Defect-2 guard applied); `stages` is always 8 rows in `order`. |
| **F2-A3** | P0 | Graph invariants 1.1.1-1.1.8 hold on every projected document: ids unique; `parent` a forest with strictly lower parent level; `issue.nodeIds[0] ∈ nodes[]`; every `edge.source`/`target` ∈ `nodes[]`; every ghost has ≥1 retained issue. |
| **F2-A4** | P0 | Every output array is a **subsequence** of the corresponding unscoped array, in the same relative order — asserted directly, for `nodes`, `edges` and `issues`, on every battery case. |
| **F2-A5** | P0 | Issue retention, measured on `samples/vision_pipeline`: `concern:evaluation` depth 1 → exactly `{MLV103, MLV301, MLV302}`; `unit:SmallCNN` depth 1 → exactly `{MLV401, MLV702}` with MLV401's `nodeIds[0] == n:3e1a658e7bad`; `stage:train` → exactly `{MLV201, MLV205, MLV501, MLV601}`; `concern:optimization` → exactly `{MLV201, MLV205, MLV401, MLV501, MLV601, MLV702}`. |
| **F2-A6** | P0 | Roles, measured on `samples/vision_pipeline`: `concern:evaluation` depth 1 → 8 core / 8 boundary / 3 context, and the context set is exactly `{data.__main__, sklearn_baseline.baseline, train.train}`; `unit:sklearn_baseline.baseline` → 13 core / 0 boundary / 0 context. |
| **F2-A7** | P0 | `stage.present` is carried through: under `unit:sklearn_baseline.baseline`, stages that are `present: true` unscoped are still `present: true` at `nodeCount: 0`; the seven `workspace` keys are byte-equal to the unscoped run. |
| **F2-A8** | P0 | **No empty bands.** Under `concern:evaluation` depth 1, `frame.lanes` contains only lanes with ≥1 drawn root; no lane has height with zero boxes inside it; `config` and `objective` appear in the "not in this scope" chip row. |
| **F2-A9** | P0 | Determinism: two projections of the same document with the same scope are byte-identical, in-process twice and once in a subprocess with a different `PYTHONHASHSEED`. |
| **F2-A10** | P0 | CLI exit behaviour: valid + non-empty → 0; valid + empty → 0 with the `config_warning` in the JSON and a stderr note; `--scope bogus:x`, `--scope stage:nope`, `--scope concern:nope`, `--depth 3`, `--depth -1`, `--scope node:n:deadbeef` → 1 each, code + candidates on stderr, **stdout clean**; `--scope` with `--demo` → 1. |
| **F2-A11** | P0 | Problems-panel immunity: setting a scope and re-rendering leaves `DiagnosticsPublisher.publish` output byte-identical; `vscode-extension/src/diagnostics.ts` has no diff in this change. |
| **F2-A12** | P0 | **Parity.** For every case in `contracts/scope.cases.json`, the TypeScript `project()` and the Python `project()` agree on the node id list, the edge id list, the issue id list **in order**, the per-node `viewRole`, every `stage.nodeCount`/`issueCounts`/`maxSeverity`, `stats`, and the whole `view` object. Wired into `scripts/e2e.ps1`, not only the viewer suite. |
| **F2-A13** | P0 | No regression: `analyze --demo --json -` still byte-equals `contracts/graph.sample.json`; an unscoped `analyze` is byte-identical to the pre-change output after stripping `generatedAt`/`durationMs`; `'view' not in analyze_to_dict(unscoped_options)`; both schema copies stay byte-identical; `schemaVersion` stays `"1.0"`. |
| **F2-A14** | P0 | Every existing suite passes: `pytest analyzer/tests`, `npm test` in `webview`, `node --test vscode-extension/test`, `claude-plugin/tests`, `tools/verify.py --all`, `scripts/e2e.ps1`. The two plugin tests named in §6.4 are updated, and no others move. |
| **F2-A15** | P1 | Depth monotonicity: for `unit:train_test_split`, node sets satisfy `d0 ⊆ d1 ⊆ d2`; `d0` has zero `boundary`-role nodes. |
| **F2-A16** | P1 | `mlview_graph {scope:"units"}` returns a catalogue ≤4096 bytes; `TOOL_NAMES` is still exactly five. |

---

## 4. Where the two features meet

No proposal addressed this, and both judge passes named it the biggest gap in the set. Four rules, all cheap,
all testable.

**C1 — a scope change clears every flow element.** Re-projection rebuilds the scene, so a stale
`.mlv-edge__flow` or a leftover `--mlv-flow-*` inline property must not survive. `clearFlow` is idempotent; the
re-projection path calls it once over the edge map before rebuilding, and resets the remembered
`flowEdgeId` / `flowSourceId` / `flowTargetId`. Same as `render()` already does for the connector layer
(`canvasview.ts:340`).

**C2 — a lineage stream stops at the scope boundary, and says nothing beyond it.** An edge is **flow-eligible**
in a *lineage stream* iff its kind is not `config` **and** (the document has no `view` **or** both endpoints have
`viewRole === "core"`). A boundary node's other connections are cut, so a charge animating into it would be a lie
about where the value goes. Edges touching a `boundary` or `context` node still **light** (`.is-lit`) — they are
real edges and they are drawn — they just do not stream.

**C3 — direct hover and selection still pulse any drawn edge**, including one that touches a boundary node. That
edge is fully drawn and fully real; the user pointed at *it*, not at the lineage. The boundary card's own
"3 more upstream nodes outside the scope" hover text carries the rest of the meaning.

**C4 — `e` / `Shift+E` iterate only routes that exist in the current projection.** They read `this.routes`, which
is already rebuilt per projection, so this falls out — but it must be asserted, because a cached incident list
would silently select a route that is no longer in the DOM.

**And the pleasant interaction:** `FLOW_MAX_EDGES` and scoping are complements. When a graph is too dense to
animate (row 12 of §2.5), **scoping it is the escape hatch** — the empty-state copy for the capped trace says so,
and the two features are cross-referenced in the docs on exactly that point.

One composition test is mandatory: apply a scope, relayout, hover an edge inside it, assert the flow renders;
hover a node whose lineage crosses the boundary, assert core-to-core edges stream and boundary-touching edges are
`.is-lit` but not `.is-flowing`.

---

## 5. Host integration

### 5.1 The viewer (both hosts, and the report)

The viewer holds the **full** document and re-projects locally. A scope change never posts `requestRefresh` and
never touches the analyzer — instant re-scope, and the standalone report (which has no host at all) behaves
identically. `App.setGraph` (`app.ts:207-243`) splits into `setGraph(full)` — which stores `fullGraph` — and
`applyProjection()`, which is the old body verbatim fed the projected document. Everything downstream (chrome
stats, rail, outline, minimap, layout, search) is scoped with **no further edits**, because they all read only the
index.

**How the initial scope reaches `mount()` — the decision that keeps two frozen surfaces frozen.**
`CONTRACTS` **A3** freezes `mount(root, graph, bridge)` and **A4** specifies the report bootstrap as a literal
three-line string. Neither is amended. The initial scope travels as an optional attribute on the root element the
report already emits:

```html
<div id="mlview-root" data-mlview-scope="concern:evaluation" data-mlview-depth="1"></div>
```

`mount()` reads it from `root` itself. Consequences, all good:

- `mount`'s signature is untouched — **A3 stays frozen, literally**.
- The A4 three-line bootstrap string is untouched — the change is in the `<div>` line, which A4 already describes
  separately.
- `vscode-extension/src/panel.ts`'s two `mount` call sites are untouched; the webview gets its scope via the
  `setScope` message, which it needs anyway.
- **`view` keeps exactly one meaning**: "this document *is* the projection". The report embeds the full graph,
  which carries no `view`; the viewer applies the scope and computes `view` itself.
- The report and the webview then run the **identical** code path — full graph in, `setScope` applied, TypeScript
  `project()` computes `view`. That is where the parity guarantee comes from, for free.

### 5.2 VS Code

**Commands** (both `"category": "MLView"`, which `test/manifest.test.js` asserts):

| id | title | menu / binding |
|---|---|---|
| `mlview.scopeToSymbol` | `MLView: Scope Diagram to Symbol` | `alt+shift+m` when `editorTextFocus && editorLangId == python`; `editor/context` group `mlview@3`; command palette |
| `mlview.clearScope` | `MLView: Clear Diagram Scope` | command palette |

`scopeToSymbol` resolves the cursor to the **enclosing unit**: run `findNodeAtLine`
(`vscode-extension/src/locationIndex.ts:97-135`, which already picks the *narrowest* containing node), then climb
`parent` to the narrowest ancestor with `level ∈ {unit, stage}`, and post `setScope` with that node's qualname.
Both bodies live in a new `src/scopeCommands.ts` mirroring `revealInDiagram.ts:29-76`, so `panel.ts` grows only
`postSetScope` plus an `onScopeChanged` handler.

**Panel title** reflects the scope: `MLView — validate()` with description `5 of 59 nodes`, from the
`scopeChanged` message. Three lines, and it is what makes the feature feel real.

**Settings: none added.** Deliberate. The flow toggle is renderer-owned and rides the existing
`saveState`/`loadState` pair as `ViewState.flow`, exactly like `minimapCollapsed`; adding
`mlview.flowAnimation` would put a field in `Capabilities` for a preference the webview can own itself, and the
standalone report has no host to read a setting from. `mlview.defaultScope` is cut (§10).

**Chat and language-model tools are untouched.** Prose-to-scope resolution in `chat.ts` and a `scope` input on the
three `languageModelTools` are both cut for v1 (§10).

**Diagnostics are untouched.** `src/diagnostics.ts` has no diff in this change (F2-A11).

### 5.3 Claude Code plugin

**Still exactly five tools.** `CONTRACTS` A7 pins `claude-plugin/tests/` to the five names and
`mlview_mcp.py:404-407` declares them; nothing here adds a sixth.

- **`mlview_graph`** — `scope` accepts the full §3.2 grammar on top of today's `"stages"` / `"stage:<id>"` /
  `"node:<id>"`, and gains one new catalogue value **`"units"`**: one row per scopable unit
  (`{nodeId, label, qualname, file, line, nodeCount, maxSeverity}`), rendered as text/json/mermaid and shed to fit
  4 KB by the existing budget machinery. This is discovery without a new tool. Its contracted error text
  (`mlview_mcp.py:290-292`, which promises to name the accepted values) is extended in the same edit — otherwise a
  documented contract becomes a lie the model will act on.
- **`mlview_analyze`**, **`mlview_issues`**, **`mlview_open_diagram`** each gain optional `scope` and `depth`.
  Omitting them reproduces today's result byte-for-byte.
- Every scoped result keeps the existing filtered-view `note` (`mlview_payloads.py:295-303`) and adds
  `"scope": "<selector>"`.
- **The analysis cache is never keyed on scope.** `load_graph` (`mlview_workspace.py:182`) keeps caching on
  `(resolved, framework, maxNodes, signature)`, `project()` is applied to the cached dict, and `graphPath` keeps
  pointing at the **full** document — so a model can always widen for free and a scoped call costs no re-analysis.
- `commands/mlview.md` frontmatter becomes `argument-hint: "[path] [--scope SPEC]"`; the CLI fallback line gains
  `--scope "$2"`.
- `skills/mlview-visualize/SKILL.md` gains a **"When to scope"** section:

  > A question about one concern gets a scoped call; a question about the project does not.
  > "is my evaluation right?" → `scope: "concern:evaluation"`. "where does the split happen?" →
  > `scope: "unit:train_test_split"`. "walk me through SmallCNN" → `scope: "unit:SmallCNN"`.
  > **"review this project" → no scope.** Narrowing first is how you miss the finding that lives in the lane you
  > did not look at. A scoped result's counts describe the scope; only an unscoped run, or `scope:"stages"`, is a
  > statement about the project — say which one you used.

---

## 6. Ownership and sequencing

Four component agents plus the lead's review rounds. The **whole `webview/` tree is one agent**, which dissolves
the file-collision problem both judge passes flagged: flow needs `app.ts`, `chrome.ts` and `commands.ts`, and scope
needs `canvasview.ts`, so splitting the viewer by feature collides on both.

| # | Component | Directories | Blocks / blocked by |
|---|---|---|---|
| 1 | **Analyzer core** | `analyzer/`, `contracts/` | Blocks 2, 3, 4 on the fixture. Ship `contracts/scope.cases.json` + `scope.expected.json` **first**. |
| 2 | **Viewer** | `webview/` | Flow work blocks nothing — start it immediately, in parallel with 1. Hold the scope UI until the fixture lands. |
| 3 | **VS Code extension** | `vscode-extension/` | Needs only the two protocol messages, agreed in round 0. |
| 4 | **Claude plugin + docs** | `claude-plugin/`, `tools/`, `scripts/`, `docs/`, `README.md` | Needs the core's `project()`; wires the gates. |

**The integrator (lead) alone runs `tools/sync-assets.py`**, once per review round. Every viewer change moves
`dist/mlview.js` and therefore `generator.rendererSha`; letting feature agents sync assets turns a build session
into a merge fight.

**If the session runs short**, ship: flow (all of §2), the core projection + CLI + MCP scope, and the viewer's
scope picker and breadcrumb. Defer: the depth stepper, the boundary `+1` affordance, the reveal-auto-clear-with-undo
toast, and `e`/`Shift+E`.

---

## 7. Parity — one algorithm, two languages

The top risk in Feature 2 is two implementations drifting. Three defences, in order of force:

1. **Structural.** The projection is filter-only over already-sorted arrays (§3.4), so **no comparator is
   duplicated**. The one non-filter step is a stable rotation, specified as a rotation for exactly this reason.
   A port that sorts anything is wrong by definition.
2. **The gate.** `contracts/scope.cases.json` — the selector battery — and `contracts/scope.expected.json`,
   generated from the Python `project()` by `analyzer/tools/gen_scope_fixtures.py`, both computed over the
   **frozen** `contracts/graph.sample.json`. The golden cannot churn, so a rule change can never redden the scope
   gate. `webview/test/scope_parity.test.mjs` runs the TypeScript `project()` over the same golden and deep-compares
   every case. `tools/verify.py --scopes` regenerates and byte-diffs. `scripts/e2e.ps1` runs it.
3. **Behavioural.** A second, smaller battery over `samples/vision_pipeline` asserts the measured demo figures
   (F2-A5, F2-A6). These live in the analyzer suite, not the parity gate, because they legitimately move when a
   rule changes.

The gate compares **roles and order**, not only id sets — the two things a loose port gets subtly wrong.

**The battery** (10 cases, all computed over `contracts/graph.sample.json`; the figures are real):

| # | Selector | depth | nodes (core/bnd/ctx) | edges | issues |
|---|---|---|---|---|---|
| 1 | `all` | — | 12 (—) | 14 | 6 — the identity case: output must be byte-identical to the input and carry **no** `view` |
| 2 | `stage:train` | 0 | 4 (4/0/0) | 3 | `{MLV201, MLV601}` |
| 3 | `unit:train.train` | 1 | 9 (4/5/0) | 11 | `{MLV201, MLV601}` |
| 4 | `unit:batch_loop` | 0 | 3 (2/0/1) | 2 | `{MLV201}` — exercises **context** and **ambiguity** (2 anchors) |
| 5 | `unit:batch_loop` | 2 | 10 (2/8/0) | 13 | `{MLV201}` — depth monotonicity |
| 6 | `file:data.py` | 0 | 2 (2/0/0) | 0 | `{MLV110}` |
| 7 | `concern:evaluation` | 0 | 1 (1/0/0) | 0 | `{MLV302}` |
| 8 | `concern:optimization` | 0 | 6 (6/0/0) | 7 | `{MLV201, MLV401, MLV601}` |
| 9 | `node:n:8d3e0f7a2b61` | 1 | 5 (1/4/0) | 7 | `{MLV401}` — exercises the **stable rotation** (`nodeIds` becomes `[SmallNet, criterion]`) |
| 10 | `unit:Nope` / `stage:deliver` | — | 0 | 0 | `{}` — the empty-but-legal case, `view.empty: true`, exit 0 |

Plus the six error codes as non-projecting cases asserting `(code, term, candidates)` only.

---

## 8. Demo scripts

All figures below were produced by running the projection over the real analyzed document. Every symbol is real.

### Demo A — flow, on the whole diagram

```
PYTHONUTF8=1 python -m mlview analyze samples/vision_pipeline --html .mlview/report.html --open
```

1. **One value, one charge.** Hover the `data` edge `data.train_loader --train_loader--> train.train.batch_loop`
   (`e:3b3705186dbd`). The cable brightens; a hollow teal dot appears on the right face of the `train_loader`
   card; a 12 px teal charge leaves it, runs the orthogonal elbow across the data→train gutter at 320 px/s, and
   lands on the batch loop, whose inlet dot flares. `train_loader` wears an outlet ring in the data hue; the loop
   wears an inlet ring in the accent.
2. **Severity where it matters.** Hover `model.SmallCNN --logits--> train.train.criterion` — edge
   `e:be0648ecd817`, the one MLV401 ("Softmax applied before CrossEntropyLoss", **high**) attaches to. The `<g>`
   already carries `data-sev="high"` and `has-issue`, so `--mlv-flow-color` resolves to `--mlv-sev` and the charge
   runs **red**. The wrong tensor is the one you watch move into the loss.
3. **A lineage as a wave.** Hover the `train.train` card. Its lineage lights and dims the rest, and every lit
   non-config edge streams, staggered 90 ms per hop: upstream from `data.TRAIN_TRANSFORM → data.full_train →
   data.random_split → data.train_loader` inward, downstream toward `train.validate` and
   `model.SmallCNN → train.train.optimizer` outward.
4. **Loops read as loops.** The three `control:back` edges — `train.train.step --next batch--> train.train.batch_loop`
   (`e:8f8c45b7c89c`), `train.train.batch_loop --next epoch--> train.train.epoch_loop` (`e:ad932321d1d7`), and
   `train.validate.preds --next batch--> train.validate.batch_loop` (`e:75cb1c81a315`) — recirculate at a 24 px gap,
   visibly denser than the 34 px data stream, so the two nested loops read as loops.
5. **Latch it.** Click that `logits` edge: the red pulse keeps running with the pointer anywhere. `Escape` stops it.
   Or press `f` on `train.train` to latch the whole lineage stream.
6. **Keyboard.** Select `model.SmallCNN` and press `e` repeatedly: its ten incident routes each become selected,
   take keyboard focus on their hit path, pulse, and announce
   *"Connection: SmallCNN to criterion, logits."*
7. **Reduced motion.** With the OS preference set, step 1 becomes: 2.5 px accent cable, a chevron at the midpoint
   pointing at the loop, a hollow outlet and a filled inlet, both card rings. Nothing moves; nothing is lost.
8. **Scale.** In `webview/test/flow.test.mjs`, `makeSyntheticGraph(150, 300)` hovers a hub node that lights more
   than 120 edges: the canvas flips to `data-flow="static"`, nothing animates, the lineage still reads, and the
   copy points at scoping.

### Demo B — "visualise the custom train/test split"

```
PYTHONUTF8=1 python -m mlview analyze samples/vision_pipeline \
    --scope unit:train_test_split --html .mlview/split.html --open
```

`unit:train_test_split` finds no `stage`/`unit` node with that last segment, falls to tier 4, and resolves to the
call-site op `n:55662bceebd0` = `sklearn_baseline.baseline.train_test_split` (`sklearn_baseline.py:26`).
At the default depth 1: **1 core, 6 boundary, 1 context — 8 nodes, 8 edges, 2 issues.**

The boundary ring is exactly the split's real interface: upstream `X_scaled`; downstream `X_train_pca`,
`X_test_pca`, `fit`, `scores`, `holdout`. The context node is the `baseline()` unit frame (`n:55a674d1b10e`), so the
split renders **inside its function** rather than floating as a lane root — the whole reason for the ancestor
closure. Six edges enter from outside and one leaves (`view.hidden.inboundEdges: 6`, `outboundEdges: 1`).

The two retained findings are **MLV602** ("Split without random_state", `sklearn_baseline.py:26`, anchored on the
split itself) and — the point of the demo — **MLV101** ("Preprocessing fitted before the train/test split",
`sklearn_baseline.py:24`), which survives because `train_test_split` is its *secondary* anchor. MLV103 (PCA outside
CV, anchored on `scores`, a boundary node) is correctly dropped: boundary is not core.

With flow on, hover `X_scaled --X_scaled--> train_test_split` (`e:47ad8c0fb4a5`) and watch the leak flow into the
split that MLV101 is about.

### Demo C — "model optimization"

```
PYTHONUTF8=1 python -m mlview analyze samples/vision_pipeline --scope concern:optimization --format summary
```

`optimization` = `model + objective + train`. **13 core, 0 boundary, 1 context — 14 nodes, 14 edges, 6 issues:**
MLV201 (`__ghost_zero_grad`, `train.py:29`), MLV205 (`train.py:34`), MLV501 (`train.py:29`), MLV401 (`train.py:31`),
MLV702 (`model.py:34`), MLV601 (`train.py:28`). The data-hygiene family (MLV110/111/112/602) and the evaluation
family (MLV103/301/302) are correctly outside. The single context node is `sklearn_baseline.baseline`, kept because
`clf` — a `model`-stage node — lives inside it.

Narrow further:

```
PYTHONUTF8=1 python -m mlview analyze samples/vision_pipeline --scope unit:SmallCNN
```

**1 core, 10 boundary, 0 context — 11 nodes, 13 edges, 2 issues:** MLV702 (the class itself) and MLV401, whose
badge **re-anchors from `train.train.criterion` onto `n:3e1a658e7bad` (`SmallCNN`)** so the marker lands on a core
card. That is rule 6 of §3.4, visible.

### Demo D — "evaluation on inference result"

```
PYTHONUTF8=1 python -m mlview analyze samples/vision_pipeline --scope concern:evaluation --depth 1 --format mermaid
```

`evaluation` = `eval + deliver`. **7 core, 7 boundary, 3 context — 17 nodes, 19 edges, exactly 3 issues:**
MLV301 ("Evaluation runs without `model.eval()`", **high**, anchored on the ghost `n:5061360697f9` =
`train.validate.batch_loop.__ghost_model_eval`, `train.py:44`), MLV302 (`train.py:44`), MLV103
(`sklearn_baseline.py:34`).

The core spans **both** evaluation paths at once — the torch `validate()` loop (`train.py:41`) and the sklearn
`cross_val_score` / `predict` / `accuracy_score` chain — which is exactly the cross-file recovery a file-filtered
analysis would have lost. This is the demo that proves §3.1.

The boundary ring is seven nodes and shows what feeds evaluation: `model.SmallCNN`, `data.val_loader`,
`sklearn_baseline.baseline.clf`, `X_train_pca`, `X_test_pca`, `train_test_split`, and
`train.train.epoch_loop` (reached by the call edge `e:b4488eb78293`, `validate()`). The context frames are exactly
`{data.__main__, sklearn_baseline.baseline, train.train}`.

The picture reads instantly: *evaluation eats one model and four prepared matrices, and one of its inputs is a
split with no `random_state`.* And it says so while `config` and `objective` — both `present: true`, both empty in
this scope — sit in the **"not in this scope"** chip row rather than as two empty bands (§3.6, Defect 1).

### Demo E — the agent path, no source reading

```
/mlview samples/vision_pipeline --scope concern:evaluation
```

`mlview_graph {scope:"units"}` returns the catalogue — `unit:sklearn_baseline.baseline · baseline() ·
sklearn_baseline.py:18 · 13 nodes`, `unit:train.train · train() · train.py:18 · 10`, `unit:train.validate ·
validate() · train.py:41 · 4`, `unit:model.SmallCNN`, `unit:model.ConvBlock`, `unit:data.__main__` — so the model
can answer "show me the evaluation path" without guessing a file name. Then `mlview_analyze {scope:
"concern:evaluation"}` (digest ≤4 KB, carrying the `scope` block and the filtered-view note) and
`mlview_open_diagram {scope:"concern:evaluation"}`, which writes and opens the report. `graphPath` still points at
the full 54-node document, so widening back is free.

### Demo F — VS Code, cursor to scope

Put the caret on `samples/vision_pipeline/train.py:44` (inside `validate`) and run **MLView: Scope Diagram to
Symbol** (`Alt+Shift+M`). `findNodeAtLine` returns the narrowest node (the batch loop `n:e37b3b62a066`);
the parent climb reaches `train.validate`. The panel posts `setScope("unit:train.validate")`.

Panel tab: **MLView — validate()**, description **11 of 59 nodes**. In scope: `validate()`, its batch loop,
`logits` (the forward pass, drawn since GRAPH-R3), `preds`, and the `model.eval()` ghost (5 core); boundary
`model.SmallCNN`, `train.train.model`, `data.val_loader`, `train.train.epoch_loop`; context `train.train`,
`data.__main__`. Rail: MLV301 + MLV302, with
*"2 of 15 findings shown · 13 outside this scope — Show all"*.

**The Problems panel still shows all 15 findings.** The scope is a view, not a mute button.

### Demo G — the gate, on screen

```
PYTHONUTF8=1 python tools/verify.py --scopes
```

prints `scope parity  OK  10 cases, python == typescript` — the same ten selectors projected identically by the
Python core and by the viewer's own TypeScript, over the frozen golden.

---

## 9. Risks

| Risk | Mitigation |
|---|---|
| **Two implementations of one algorithm drift.** | §7's three defences. The structural one (filter-only, no duplicated comparator) is the load-bearing part; the gate catches the rest. |
| **The reduced-motion clamp freezes rather than removes** (`base.css:207`), parking a 12 px stub at every outlet. | Never build the element **and** an explicit `display: none !important` block. F1-A6 asserts both. |
| **`--demo` and the golden are the most fragile thing in the repo.** `test_schema.py` compares `--demo` bytes to `contracts/graph.sample.json` and both schema copies to each other. | Never touch `graph.sample.json`; edit both schema copies in one scripted edit; keep `schemaVersion` at `"1.0"`; reject `--scope` with `--demo`. |
| **`view` leaking into unscoped output** would break `tools/verify.py --parity`, the determinism test and every host snapshot. | `project()` is the only writer of `view`; the CLI calls it only when a spec was given; F2-A13 asserts `'view' not in analyze_to_dict(unscoped)`. |
| **Regressing the MLV-R2-103 `present` fix.** | Carried through in step 9, restated in the schema description, in §11, and in three tests. Plus the two consequent fixes in §3.6, which are what make carrying it through actually safe. |
| **`stroke-dashoffset` repaints the edge layer every frame.** | `FLOW_MAX_EDGES = 120` with a hard static fallback; no `will-change`, no `drop-shadow`, no halo; the toolbar toggle is the user's escape hatch and scoping is the structural one. |
| **Widening issue retention to core-to-core edges changes existing MCP output.** | Verified a no-op on both samples (the only edge-bearing issue, MLV401, also lists both endpoint nodes). Re-checked by F2-A14 before merge; if a count moves, the widening is reverted to node-only and recorded. |
| **`stage:<id>` gains one context node vs today's `mlview_graph`.** | Accepted as a deliberate superset (the ancestor closure replaces the parent-to-null promotion). Verified: exactly one node on the sample. The two affected plugin tests are named in the work-list. |
| **A scoped summary read as a project statement** — the same class of bug as MLV-R2-103. | `view.of` is always project-level; every renderer prints "N of M"; the filtered-view note is preserved; diagnostics are never scoped. |
| **Two narrowings on one screen** (filters dim, scope removes). | §3.8: different verbs, different controls, neither clears the other, and the `[×]` tooltip says so. |
| **Relayout cost on depth stepping.** | 120 ms debounce; the existing 150-node / 300 ms perf assertion is re-run with a scope applied. |
| **Boundary contrast.** A faded boundary done with opacity alone fails the existing contrast gate in one theme. | A declared `--mlv-fg-boundary` token plus the dashed border carrying the meaning. |

---

## 10. Non-goals — the cut list, with reasons

**Feature 1**

- **Play-the-pipeline** (`a`, a `FlowPlayer`, `data-flow-stage`). A `setTimeout` state machine needing teardown on
  stop, relayout, background pointerdown, `visibilitychange` and destroy, plus a separate reduced-motion stepper
  and its own aria announcements. A second feature nobody asked for, and the likeliest source of a leaked timer
  announcing stages into a live region in a hidden panel.
- **The travelling payload label** (`offset-path`). Untestable in-suite — `window.CSS` is `undefined` in jsdom, so
  the supported branch is reachable only by stubbing — and the static midpoint label already names the variable at
  full LOD (`edge.css:126-129`).
- **The pulse halo.** A second animated stroke for polish, on the one code path that already repaints per frame.
- **`getTotalLength()`.** One code path in browser and jsdom; the corner-rounding error is invisible at 220 px/s.
- **A keyboard binding for the flow toggle.** The toolbar button and the OS preference are enough; every key is a
  row a user must learn.
- **Per-kind stream speeds.** One speed, three gaps (§2.6). Same rate, different density.

**Feature 2**

- **`direction: up|down`.** `both` at depth 1 covers every demo; direction doubles the parity battery and adds a
  second axis to every CLI, MCP, protocol and UI shape.
- **Selector kinds `dir:`, `nodes:`, `issue:`, comma-unions, the `+pin` suffix.** A pin is a whole
  state-management concept (an id that must survive a re-analysis where that id is gone) for a P1 gesture.
- **A sixth MCP tool (`mlview_scopes`) and a `scopes` CLI subcommand.** Discovery rides on
  `mlview_graph {scope:"units"}` plus `--list-scopes`, keeping A7's exactly-five-tools assertion green.
- **Four of six entry points**: the stage-chip caret menu, the Outline row button, `Alt`+click on cards, and
  `Ctrl+Shift+S`.
- **The minimap ghost silhouette**, the Inspector "why is this in scope" line, `--scope-freeze`, report filename
  slugging, and a second CodeLens.
- **Scoped export, chat-prose scope resolution, and a `scope` input on the three language-model tools.**
- **Named / bookmarked scopes and an `mlview.defaultScope` setting.**
- **Scope-aware `--max-nodes`.** Genuinely better output, but it would make Python and TypeScript disagree whenever
  the cap binds. Disclosed instead.
- **Scoped mermaid/text styling.** One line each (`scope: <spec> — N of M nodes`); no `classDef mlvBoundary`, no
  role-marker column.
- **A scoped CI gate beyond `--fail-on` reading the retained list** (which is free). No stderr disclosure doc, no
  CI guide, until someone asks.

**Both**

- Any change to what the analyzer parses. Any change to `schemaVersion`. Any change to
  `contracts/graph.sample.json`. Any scoping of VS Code diagnostics.

---

## 11. Decisions register

Every ambiguity the proposals left open, decided here, with the reason.

1. **Schema home: root-level `view`, node-level `viewRole`.** Not `workspace.scope` — `workspace` is contractually
   the full analysis, and nesting a projection marker inside it invites exactly the confusion this design spends a
   page preventing. Not root `scope` — the word already means three different things in this tree
   (`ir/scopes.py`/`ScopeIR`, `HostToUi.analysisStarted.scope`, `mlview_graph(scope=)`).
2. **`view` is emitted only by a real projection.** Its absence *is* the "whole workspace" signal, and it is what
   keeps `--demo` and every unscoped byte identical.
3. **`schemaVersion` stays `"1.0"`.** Every prior document still validates; hosts check the MAJOR only; the golden
   carries `"1.0"` and `--demo` must match it byte-for-byte; consumers feature-detect on `view`, which is more
   precise than a version number.
4. **Three roles, not a boolean.** A `context` ancestor is an empty frame; a `boundary` node is a faded stub with
   no badge. They render differently, so one optional enum beats one optional boolean.
5. **Ancestor closure, not `parent → null`.** Verified: it is what puts `train_test_split()` inside its
   `baseline()` frame instead of floating as a lane root. Cost: `stage:<id>` gains one context node vs today's MCP
   output. Accepted; the two tests are named.
6. **Issue retention = any `nodeId ∈ core`, or an `edgeId` on a core-to-core edge.** Measured: "any kept node"
   drags five foreign-lane findings into `stage:train` through boundary stubs; "`nodeIds[0]` survives" loses MLV401
   from the model scope, which is the most interesting cross-boundary finding there.
7. **`nodeIds` is stably rotated so `nodeIds[0] ∈ core`.** Keeps invariant 1.1.3 true and puts the badge on a real
   card. It is the only non-filter step in the algorithm, and it is a rotation precisely so both languages agree.
8. **Four selector kinds plus one legacy alias**; `symbol:` normalizes to `unit:`. Ship the simplest grammar that
   covers every demo.
9. **`unit:` takes a qualname, an FQN, a bare name **or** a node id**, and always closes over descendants.
   `node:` stays the pinpoint selector with legacy depth 1 — that is what keeps `mlview_graph {scope:"node:…"}`
   byte-identical.
10. **Depth 0..2; default 1 for `unit:`/`node:`, 0 for `stage:`/`file:`/`concern:`.** A point wants its interface;
    a region does not want a ring.
11. **Containment is not a hop.** `depth` counts real edges only; parents come from the ancestor closure. One
    meaning, monotone, testable.
12. **Edges kept iff both endpoints survive.** The same rule the shipped `subgraph()` uses. A hop-difference rule
    would strand ring-2 nodes at depth 2 and would have to be ported identically for no gain.
13. **Empty scope → exit 0 with a valid empty document; invalid selector → exit 1.** "This concern does not exist
    here" is a finding; a misspelled kind is a caller error. No new exit code.
14. **Four concern presets partitioning all eight stages.** A partition guarantees no stage is unreachable and no
    stage is claimed twice — safer than presets defined by stages *and* kinds, which puts stage assignment in a
    second place that can disagree with the first.
15. **`stage.present` is carried through, and the two consumers that assumed otherwise are fixed** (`model.ts:87`
    and `validate_sample.py:300`). This is the decision that makes the other one honest.
16. **The initial scope reaches the report through `data-mlview-scope` on `#mlview-root`, not a fourth `mount()`
    argument and not a second meaning for `view`.** A3 and A4 stay frozen, `panel.ts`'s two call sites are
    untouched, `view` keeps one meaning, and the report and the webview run the identical code path — which is
    where the parity guarantee comes from for free. This dissolves the one direct conflict between the two judge
    passes rather than picking a side.
17. **The viewer holds the full graph and re-projects locally.** No host round trip; the standalone report, which
    has no host, behaves identically.
18. **Protocol messages are `setScope` / `scopeChanged`, and their selector field is named `spec`.** Not `scope` —
    `analysisStarted` and `requestRefresh` already carry a field literally named `scope` with values
    `'workspace' | 'file'`.
19. **Flow direction is never derived per edge.** Every router already emits source→target; a design that
    reintroduces a direction decision is wrong.
20. **Flow announces itself only for keyboard-driven flows.** Announcing on hover narrates every mouse sweep into
    the live region.
21. **Only error *codes*, the offending term, and a sorted ≤10 candidate list are contractual.** Message prose is
    free; maintaining two English strings in two languages is a trap with no user benefit.
22. **The parity fixture is computed over the frozen `contracts/graph.sample.json`**, not over
    `samples/vision_pipeline`, which the rules agent owns (A12). The gate must not churn when a rule changes.
23. **A lineage stream requires both endpoints to be `core`; a direct hover pulses any drawn edge.** The stream
    makes a claim about a path; a hover makes a claim about one connection.
24. **The MCP analysis cache is never keyed on scope**, and `graphPath` keeps pointing at the full document, so a
    model can always widen for free.
25. **`--list-scopes` is a flag on `analyze`, not a subcommand.** It makes the catalogue the requested payload and
    exits 0, which is exactly what the stdout invariant permits; it is mutually exclusive with `--json` and
    `--html`.
26. **No new VS Code settings.** The flow preference is renderer-owned via `ViewState`, and the standalone report
    has no host to read a setting from.
