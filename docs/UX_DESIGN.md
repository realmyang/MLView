# MLView — Design System & Interaction Specification

**Status:** frozen for the prototype build. Version 1.0, 2026-09-06; §1, §9 and §11 gained the flow and scope rows when the two features were designed (2026-09-07).
This document is buildable-from: a front-end agent should be able to implement the viewer without asking a question. Anything host-specific (message shapes) is in `CONTRACTS.md`.

**This is a plan, not a build report — including every row added in the second pass.** It records what was *decided*; `scripts/check_docs.py` link-checks it and nothing more, precisely so that editing it to match the build cannot quietly erase a decision. Two consequences: a sentence here may describe something that was never built, and no sentence here may report what the build currently does — the gate fails the run on one that tries (MLV-R1-H08). What actually shipped is described in [README.md](../README.md) and [docs/STATUS.md](STATUS.md), which the gate does check, and bound by [docs/CONTRACTS.md](CONTRACTS.md) §11.

---

## 0. Design principles

1. **The graph is the document; everything else is chrome.** The canvas owns the width by default; the side rail is a collapsible drawer, not a permanent column.
2. **Colour carries meaning exactly twice**: pipeline **stage** (the node's left rail, the lane tint, the minimap dot) and **severity** (the badge only). Nothing else is coloured.
3. **Every affordance is redundant.** Severity = shape + colour + text. Selection = ring + elevation + inspector change. Edge kind = dash pattern + arrowhead + weight, never colour alone.
4. **Progressive disclosure, one gesture apart**: pill → card → hover card → inspector → source code.
5. **Deterministic and quiet.** Same JSON → same picture, every time. Nothing animates that the user did not cause. No idle attention-seeking.
6. **Say what you do not know.** Dashed borders for low confidence, dashed ghosts for absent steps, an explicit banner for partial understanding. An honestly annotated gap beats a confidently sparse diagram.

---

## 1. Application shell

Identical in the VS Code webview and the standalone HTML report; only the `HostBridge` and the theme source differ.

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ TOOLBAR 48px                                                                      │
│ ◈ MLView  ⌗ Everything ▾ │ ⌕ Search ⌘K │ ❗5  ⚠6  ⓘ4 │ Filters ▾ │ ⤢ 84% ⟳ ⤓ ☰│
├──────────────────────────────────────────────────────────────────────────────────┤
│ CHIPS  not detected: augment · tracking │ not in this scope: config · objective   │
├──────────────────────────────────────────────────────────────────────────────────┤
│ BREADCRUMB 32px  Scoped to baseline()  ·  depth 1  ·  13 of 45 nodes  [−][+]  [×] │
├───────────────────────────────────────────────────────┬──────────────────────────┤
│                                                       │  RAIL 360px              │
│  ┌ CONFIG ─────────────────────────────────────────┐  │ ┌──────────────────────┐ │
│  │ [seed?]  [device]  [args]                       │  │ │Issues│Inspector│Outln│ │
│  └─────────────────────────────────────────────────┘  │ ├──────────────────────┤ │
│  ┌ DATA ───────────────────────────────────────────┐  │ │ ⌕ filter…            │ │
│  │ [CIFAR10]──ds──▶[DataLoader] ⚠                  │  │ │ [❗5][⚠6][ⓘ4]        │ │
│  └─────────────────────────────────────────────────┘  │ ├──────────────────────┤ │
│  ┌ PREPROCESS ─────────────────────────────────────┐  │ │ ❗ MLV101  data.py:41│ │
│  │ [StandardScaler] ❗──X──▶[train_test_split]     │  │ │   Scaler fitted      │ │
│  └─────────────────────────────────────────────────┘  │ │   before the split   │ │
│  ┌ MODEL ──────────────────────────────────────────┐  │ │   ▸ fix hint         │ │
│  │ [Net  +12 layers] ❗                            │  │ ├──────────────────────┤ │
│  └─────────────────────────────────────────────────┘  │ │ ❗ MLV201  train.py:44│ │
│  ┌ OBJECTIVE ──────────────────────────────────────┐  │ │   Gradients never    │ │
│  │ [CrossEntropyLoss] ❗   [Adam]  [StepLR]        │  │ │   zeroed             │ │
│  └─────────────────────────────────────────────────┘  │ └──────────────────────┘ │
│  ╭ TRAIN ──────────────────────────────────────────╮  │                          │
│  │ ╭ for epoch ───────────────────────────────────╮│  │                          │
│  │ │ ╭ for batch ─────────────────────────────╮   ││  │                          │
│  │ │ │ ⌐zero_grad⌐ ❗→ fwd → loss → bwd → step│   ││  │                          │
│  │ │ ╰──────────────◀── next batch ───────────╯   ││  │                          │
│  │ ╰────────────────◀── next epoch ──────────────╯│  │                          │
│  ╰─────────────────────────────────────────────────╯  │                          │
│  ┌ EVAL ───────────────────────────────────────────┐  │  ┌──────────────┐        │
│  │ ⌐model.eval()⌐ ❗  [val loop] ⚠  [accuracy]     │  │  │  MINIMAP     │        │
│  └─────────────────────────────────────────────────┘  │  └──────────────┘        │
├───────────────────────────────────────────────────────┴──────────────────────────┤
│ STATUS 24px  38 nodes · 51 edges · ❗5 ⚠6 ⓘ4 · pytorch, sklearn · 0.4s · 3 notes  │
└──────────────────────────────────────────────────────────────────────────────────┘
```

- Toolbar 48 px, chip row 28 px (only when non-empty), breadcrumb 32 px (only when a scope is active), status 24 px. Canvas fills the rest.
- **Scope button** (`⌗`, `ui/chrome.ts`) sits first after the brand and reads `Everything` until a scope is taken, then the scope's label. It opens the **scope picker** (`ui/scopepicker.ts`): a search box over the unit catalogue — biggest unit first, with its file, line, node count and worst severity — plus the four concern presets and the eight stage lanes. Picking one calls `app.setScope(spec)`; nothing is re-analysed, and no host round-trip happens.
- **Breadcrumb** (`ui/breadcrumb.ts`, `role="status"`) is the scope's home. It states, in this order and never any other: what is scoped, the depth, and **`N of M nodes` where `M` is `view.of.nodes` — project-level truth**, so a scoped screen can never be read as a claim about the project's size. `[−]` / `[+]` step the depth 0..2, `[×]` clears the scope, and `[×]`'s tooltip says *"Filters are separate"* — a scope and the severity/stage filters are two narrowings living on one screen, and that sentence is what keeps them apart.
- **The chip row grows a second family.** Beside `not detected: …` (stages the project genuinely lacks — a finding) sits `not in this scope: …` for stages that exist in the project but have no drawn node under the current scope. Two absences with two different meanings never share one word.
- Rail defaults open at 360 px, resizable 280–560 by dragging its left edge (4 px hit area, 1 px visual), collapsible with `☰` or `Ctrl+B`. Below 900 px viewport width it becomes an overlay drawer with a 40 % scrim.
- Minimap bottom-right, 200×130, appears only above 30 nodes, collapsible to a 28 px chevron tab. Node dots use the stage colour; nodes with issues get a 1.5 px ring in the highest severity colour (no glyph — too small); the viewport rectangle is `--mlv-accent` at 12 % fill with a 1 px stroke.
- The zoom control shows a live percentage and is click-to-reset-to-100 %.

---

## 2. Layout

### 2.1 Stage swimlanes — the spine of the product

Eight ordered bands stacked **top → bottom** in canonical pipeline order, with `rankdir: LR` dagre **inside each band**:

| # | `stage` | Label | Covers |
|---|---|---|---|
| 0 | `config` | Configuration | seeds, device selection, argparse/Hydra, hyperparameter constants |
| 1 | `data` | Data | file/db loading, `Dataset` classes, `DataLoader`, samplers |
| 2 | `preprocess` | Preprocess | splits, scalers/encoders/imputers, tokenizers, transforms, augmentation |
| 3 | `model` | Model | `nn.Module` subclasses, layers, estimators, `from_pretrained` |
| 4 | `objective` | Objective | losses, optimizers, schedulers, AMP scaler, clipping |
| 5 | `train` | Train | epoch/batch loops and the update step |
| 6 | `eval` | Evaluate | validation/test loops, metrics |
| 7 | `deliver` | Save / Deploy | checkpoints, tracking, export, inference/serving |

This fixed skeleton is what makes a *second* MLView diagram readable in seconds. A band is a soft-cornered container (radius 14) with a 1 px border, a 4 % tint of its stage hue, and a sticky uppercase 11 px label with `letter-spacing: .04em` at the top-left, plus a right-aligned issue-count cluster.

**Absent stages are not drawn as empty bands** — they appear in the chip row under the toolbar as `not detected: augment · tracking`. Absence is itself a review finding, so it is stated, never silent.

### 2.2 Why per-lane dagre, and what we deliberately do not do

```ts
// layout.ts — deterministic, synchronous, ~180 lines around dagre
for (const lane of stages) {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'LR', ranksep: 72, nodesep: 24, edgesep: 12, marginx: 16, marginy: 16,
               ranker: 'network-simplex' });
  g.setDefaultEdgeLabel(() => ({}));
  for (const n of nodesIn(lane))  g.setNode(n.id, measureAtFullDetail(n));   // ALWAYS full-detail size
  for (const e of edgesWithin(lane)) g.setEdge(e.source, e.target, { weight: EDGE_WEIGHT[e.kind] });
  dagre.layout(g);                                                          // synchronous
  place(lane, g);                                                           // node.x/node.y are CENTRES
}
stackLanesVertically(gutter = 32);
routeCrossLaneEdges();     // vertical elbows through lane gutters, 8px corner radius
routeBackEdges();          // outside the loop container, with a ↻ chevron at the midpoint
```

- **Edge weights bias the ranking toward the real pipeline order**: `data: 4, call: 2, control: 2, config: 1`.
- **Cross-lane edges are not given to dagre.** They are routed afterwards as orthogonal elbows through the lane gutters, which is trivially correct because the lanes are already ordered by the pipeline's semantics.
- **Groups are laid out children-first** and inserted into the parent's dagre pass as a single sized meta-node. We do **not** use dagre's `compound: true` / `setParent` — that API is explicitly unverified, and containment is not something to build on an unverified API in a one-session build.
- **Cycles**: back-edges (the loop return path) are identified by the analyzer as `control/back` and are *removed before* the dagre pass, then drawn afterwards as a rounded path routed outside the loop container. Requirement R1.5 depends on this being visible, not hidden.
- **Determinism**: dagre's `network-simplex` is deterministic given a stable insertion order, and the analyzer emits sorted collections — so positions are identical run to run, which the snapshot tests and screenshots depend on.
- **Budget**: each dagre call sees at most a few dozen nodes, so 300 nodes / 600 edges lays out in well under the 300 ms budget.
- **`LayoutEngine` interface** — `{ name: string; run(graph, opts): LayoutResult }` — so ELK or a flow-mode variant can drop in later without touching a component.

### 2.3 The training loop

The `train` band renders the epoch and batch loops as **concentric rounded containers** with a faint tick mark on the leading edge. Inside the batch container, the canonical five ops (`zero_grad → forward → loss → backward → step`) lay out left → right in execution order. Back-edges are labelled `next batch` / `next epoch` with a ↻ chevron. If `zero_grad` is missing, its slot is a **ghost node** — see §4.4.

### 2.4 Keeping 50–400 nodes readable

Five mechanisms, in the order a user reaches for them:

| Mechanism | Gesture | Effect |
|---|---|---|
| **Auto-collapse on load** | automatic | Groups with > 12 children, and any issue-free subtree once the graph exceeds 120 nodes, start collapsed. First paint is always ≤ ~25 boxes. A toast says *"8 groups collapsed · Expand all (Ctrl+Shift+E)"*. |
| **Collapse / expand** | `Space`, chevron click, double-click on a group header | The group becomes one card with a folder glyph, `41 nodes`, and the aggregated badge cluster. Cross-boundary edges retarget to the collapsed box and merge, showing `×7` and the dominant kind's dash style. **Viewport is anchored**: the point under the cursor stays put (compute the pre/post bbox delta and translate the viewport by it). |
| **LOD by zoom** | zoom | §6 |
| **Focus mode** | `F`, or ◎ on the hover card | Everything outside the k-hop neighbourhood (default 1↑/1↓, adjustable 1–3) drops to `opacity:.22; filter:saturate(.3); pointer-events:none`. A pill appears in the breadcrumb: `Focus: train() · 1↑ 1↓ [− +] [Exit ×]`. `Esc` restores the graph *and* the previous viewport. |
| **Filters** | Toolbar `Filters ▾`, severity chips, `1`/`2`/`3` | Multi-select by severity, stage, framework, node kind, file, and "only nodes with issues ≥ severity". Filtered-out nodes: `opacity:.18`, no interaction, edges hidden. An active-filter chip row appears under the toolbar with `Clear all`. |

Plus **search-first navigation** (§8): most users never pan at all.

---

## 3. Design tokens (`styles/tokens.css`)

Every token has a `--vscode-*` primary and a literal fallback, so **one stylesheet serves both hosts untouched**. A CSS lint rule fails the build on any raw hex, `rgb(`, or hard-coded px for a tokenised property outside this file.

```css
:root {
  /* ── typography ───────────────────────────────────────────────────────── */
  --mlv-font:      var(--vscode-font-family, ui-sans-serif, -apple-system,
                       "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif);
  --mlv-font-mono: var(--vscode-editor-font-family, "Cascadia Code", "JetBrains Mono",
                       Consolas, ui-monospace, monospace);
  --mlv-fs-10: 10.5px; --mlv-fs-11: 11px; --mlv-fs-12: 12px;
  --mlv-fs-13: 13px;   --mlv-fs-14: 14px; --mlv-fs-16: 16px; --mlv-fs-20: 20px;
  --mlv-lh-tight: 1.35; --mlv-lh-body: 1.5;
  --mlv-fw-regular: 450; --mlv-fw-medium: 550; --mlv-fw-semi: 650;
  --mlv-track-caps: .04em;

  /* ── spacing (4px base) ───────────────────────────────────────────────── */
  --mlv-s1: 2px;  --mlv-s2: 4px;  --mlv-s3: 6px;  --mlv-s4: 8px;  --mlv-s5: 12px;
  --mlv-s6: 16px; --mlv-s7: 20px; --mlv-s8: 24px; --mlv-s9: 32px; --mlv-s10: 48px;

  /* ── radii / elevation ────────────────────────────────────────────────── */
  --mlv-r-chip: 4px; --mlv-r-btn: 6px; --mlv-r-node: 10px;
  --mlv-r-lane: 14px; --mlv-r-panel: 12px; --mlv-r-pill: 999px;
  --mlv-sh-1: 0 1px 2px rgba(16,18,24,.06), 0 0 0 1px var(--mlv-border);
  --mlv-sh-2: 0 4px 12px rgba(16,18,24,.10), 0 0 0 1px var(--mlv-border-strong);
  --mlv-sh-3: 0 16px 40px rgba(16,18,24,.18), 0 0 0 1px var(--mlv-border-strong);

  /* ── motion ───────────────────────────────────────────────────────────── */
  --mlv-dur-1: 120ms;   /* hover, press                    */
  --mlv-dur-2: 180ms;   /* popovers, panels, chevrons      */
  --mlv-dur-3: 260ms;   /* layout, centring, collapse      */
  --mlv-ease: cubic-bezier(.2,.8,.2,1);

  /* ── geometry ─────────────────────────────────────────────────────────── */
  --mlv-node-w: 216px; --mlv-node-w-lg: 248px; --mlv-node-w-sm: 176px;
  --mlv-node-h: 72px;  --mlv-rail-w: 4px;      --mlv-group-header-h: 34px;
  --mlv-lane-pad: 20px;
  --mlv-toolbar-h: 48px; --mlv-chips-h: 28px;
  --mlv-breadcrumb-h: 32px; --mlv-status-h: 24px; --mlv-rail-width: 360px;

  /* ── LIGHT surfaces ───────────────────────────────────────────────────── */
  --mlv-bg:            var(--vscode-editor-background, #FBFBFD);
  --mlv-surface:       var(--vscode-editorWidget-background, #FFFFFF);
  --mlv-surface-2:     #F3F4F8;
  --mlv-border:        var(--vscode-widget-border, #E3E5EB);
  --mlv-border-strong: #C9CDD6;
  --mlv-text:          var(--vscode-editor-foreground, #16181D);
  --mlv-text-2:        #5A6070;
  --mlv-text-3:        #878EA0;
  --mlv-accent:        var(--vscode-focusBorder, #3B6CF6);
  --mlv-focus:         var(--vscode-focusBorder, #3B6CF6);
  --mlv-canvas-dot:    #E6E9F0;
  --mlv-edge:          #A8AEBD;

  /* ── stage hues (light) — used at 4% for bands, full for rails/glyphs ─── */
  --mlv-stage-config:     #667085;  --mlv-stage-config-tint:     #6670850A;
  --mlv-stage-data:       #0E9DA8;  --mlv-stage-data-tint:       #0E9DA80A;
  --mlv-stage-preprocess: #7C5CFF;  --mlv-stage-preprocess-tint: #7C5CFF0A;
  --mlv-stage-model:      #3B6CF6;  --mlv-stage-model-tint:      #3B6CF60A;
  --mlv-stage-objective:  #E07B2E;  --mlv-stage-objective-tint:  #E07B2E0A;
  --mlv-stage-train:      #14895F;  --mlv-stage-train-tint:      #14895F0A;
  --mlv-stage-eval:       #BE3FA6;  --mlv-stage-eval-tint:       #BE3FA60A;
  --mlv-stage-deliver:    #8A8F9C;  --mlv-stage-deliver-tint:    #8A8F9C0A;
  --mlv-stage-unknown:    #8A8F9C;  --mlv-stage-unknown-tint:    #8A8F9C08;

  /* ── severity (light) — theme-aware primaries, literal fallbacks ──────── */
  --mlv-sev-high:   var(--vscode-editorError-foreground,   var(--vscode-charts-red,    #D0342C));
  --mlv-sev-medium: var(--vscode-editorWarning-foreground, var(--vscode-charts-yellow, #E8A317));
  --mlv-sev-low:    var(--vscode-editorInfo-foreground,    var(--vscode-charts-blue,   #3B6CF6));
  --mlv-sev-high-ink:   #FFFFFF;   /* glyph on the high fill      */
  --mlv-sev-medium-ink: #3A2500;   /* dark glyph on amber — 4.5:1 */
  --mlv-sev-low-ink:    #FFFFFF;
  --mlv-sev-high-tint:   #D0342C14;
  --mlv-sev-medium-tint: #E8A31718;
  --mlv-sev-low-tint:    #3B6CF614;
}

/* ── DARK ───────────────────────────────────────────────────────────────── */
:root:not([data-theme="light"]) { }          /* placeholder; see media query + explicit */
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) { /* same block as [data-theme="dark"] below */ }
}
body.vscode-dark, :root[data-theme="dark"] {
  --mlv-bg:            var(--vscode-editor-background, #131417);
  --mlv-surface:       var(--vscode-editorWidget-background, #1A1C21);
  --mlv-surface-2:     #22252C;
  --mlv-border:        var(--vscode-widget-border, #2C3038);
  --mlv-border-strong: #3B414C;
  --mlv-text:          var(--vscode-editor-foreground, #E6E8EE);
  --mlv-text-2: #9AA1B1;  --mlv-text-3: #6E7686;
  --mlv-accent: var(--vscode-focusBorder, #6E96FF);
  --mlv-canvas-dot: #23262D;  --mlv-edge: #565D6B;
  --mlv-sh-1: 0 1px 2px rgba(0,0,0,.36), 0 0 0 1px var(--mlv-border);
  --mlv-sh-2: 0 6px 16px rgba(0,0,0,.44), 0 0 0 1px var(--mlv-border-strong);
  --mlv-sh-3: 0 20px 48px rgba(0,0,0,.55), 0 0 0 1px var(--mlv-border-strong);

  --mlv-stage-config: #8B93A7;     --mlv-stage-config-tint: #8B93A71A;
  --mlv-stage-data: #2DC5D0;       --mlv-stage-data-tint: #2DC5D01A;
  --mlv-stage-preprocess: #9E86FF; --mlv-stage-preprocess-tint: #9E86FF1A;
  --mlv-stage-model: #6E96FF;      --mlv-stage-model-tint: #6E96FF1A;
  --mlv-stage-objective: #F0954A;  --mlv-stage-objective-tint: #F0954A1A;
  --mlv-stage-train: #34C08A;      --mlv-stage-train-tint: #34C08A1A;
  --mlv-stage-eval: #E169C9;       --mlv-stage-eval-tint: #E169C91A;
  --mlv-stage-deliver: #8B93A7;    --mlv-stage-deliver-tint: #8B93A71A;
  --mlv-stage-unknown: #6E7686;    --mlv-stage-unknown-tint: #6E76861A;

  --mlv-sev-high:   var(--vscode-editorError-foreground,   var(--vscode-charts-red,    #FF6169));
  --mlv-sev-medium: var(--vscode-editorWarning-foreground, var(--vscode-charts-yellow, #F2B03C));
  --mlv-sev-low:    var(--vscode-editorInfo-foreground,    var(--vscode-charts-blue,   #6E96FF));
  --mlv-sev-high-ink: #1A0405;  --mlv-sev-medium-ink: #2A1A00;  --mlv-sev-low-ink: #0B1020;
}

/* ── HIGH CONTRAST ──────────────────────────────────────────────────────── */
body.vscode-high-contrast, body.vscode-high-contrast-light, :root[data-theme="hc"] {
  --mlv-surface: var(--vscode-editor-background);
  --mlv-surface-2: transparent;
  --mlv-border:        var(--vscode-contrastBorder, currentColor);
  --mlv-border-strong: var(--vscode-contrastBorder, currentColor);
  --mlv-sh-1: 0 0 0 1px var(--vscode-contrastBorder);
  --mlv-sh-2: 0 0 0 2px var(--vscode-contrastBorder);
  --mlv-sh-3: 0 0 0 2px var(--vscode-contrastBorder);
}
body.vscode-high-contrast .mlv-sev-glyph { fill: none; stroke-width: 2; }
body.vscode-high-contrast .mlv-node__rail { width: 6px; }
body.vscode-high-contrast .mlv-lane { border-style: solid; background: transparent; }

@media (prefers-reduced-motion: reduce) {
  * { animation-duration: .01ms !important; transition-duration: .01ms !important; }
}
```

**Standalone parity.** `main.ts` sets `document.documentElement.dataset.theme` from `matchMedia('(prefers-color-scheme: dark)')` when no `vscode-*` body class is present, and shows an Auto / Light / Dark switch that exists only in standalone mode. Because every `--vscode-*` reference has a literal fallback, the same CSS file works untouched in both hosts.

**Canvas background.** Dot grid, 20 px spacing, 1 px dots in `--mlv-canvas-dot`; the dots fade out below 0.4 zoom (tied to the LOD class) so an overview reads as a clean field.

---

## 4. Visual language

### 4.1 Node card — the atom

```
        ┌───────────────────────────────────────┐ ← 10px radius, --mlv-sh-1
 4px    │▌ ┌────┐  train_loader            ❗2 │ ← severity cluster, overhangs (+6,-6)
 stage ▶│▌ │ ▦  │  DataLoader · bs=128         │
 rail   │▌ └────┘  data.py:31                  │ ← 11px mono, --mlv-text-3
        │▌  [shuffle] [num_workers=4] [+2]     │ ← chips, max 3 then "+n"
        └───────────────────────────────────────┘
          216 × 56 | 72 | 88 px   ·   padding 10 12
```

- **Rail** — 4 px, full height, left edge, radius `10 0 0 10`, `--mlv-stage-<stage>`. This is the one place saturated colour appears, so scanning by stage works even for a node dragged out of its lane.
- **Icon** — a 16 px line-art glyph inside a 26×26 rounded-6 square filled `--mlv-stage-<stage>-tint`, stroked in the stage colour. One glyph per kind: dataset = stacked disks, dataloader = shuffle, split = fork, transform = wand, model = layered box, layer = layers, loss = target, optimizer = gauge, scheduler = trending line, train_loop = circular arrow, eval_loop = check-circle, metric = bar chart, checkpoint = disk, tracker = broadcast, predict = bolt, config = sliders, entrypoint = play, external = package, unknown = question mark.
- **Title** — 13 px / 600, `--mlv-text`, single line. Long qualified names truncate from the **middle** (`ResNetBl…forward`) so both ends stay readable.
- **Subtitle 1** (kind + key params) — 11.5 px / 450, `--mlv-text-2`, single line.
- **Subtitle 2** (location) — 11 px mono, `--mlv-text-3`, `file.py:line`; becomes an underlined link colour on card hover.
- **Chips** — 18 px tall, radius 4, 10.5 px / 500, background `--mlv-surface-2`, 1 px `--mlv-border`. Kinds: `param` neutral, `flag` stage-tinted, `shape` mono with a `⌗` prefix.
- **Widths** — 216 default; `model` / `entrypoint` / group cards 248; a `layer` node inside a dense model group may shrink to 176. Fixed widths are what make the layered layout read as engineered rather than ragged.

### 4.2 Node states (the eight-state machine)

| State | Treatment |
|---|---|
| **default** | `--mlv-sh-1`, `--mlv-surface` background, 1 px `--mlv-border` |
| **hover** | `--mlv-sh-2`, border `--mlv-border-strong`, `translateY(-1px)`, 120 ms |
| **selected** | 2 px ring `--mlv-accent` + 4 px halo `--mlv-accent/14`, `--mlv-sh-2`, title weight 650 |
| **focus-visible** (keyboard) | 2 px `--mlv-focus` ring with 2 px offset, drawn **outside** the selection ring so both are visible |
| **has-issues** | 1 px border in the highest severity colour at 55 % alpha; badge cluster top-right. **Node fill never changes** — a stage with 20 findings must not become a wall of red |
| **dimmed** (focus/hover trace) | `opacity:.22; filter:saturate(.3); pointer-events:none` |
| **filtered-out** | `opacity:.18`, no shadow, `pointer-events:none` |
| **stale** (files changed) | 1 px dashed border plus a small ⟳ glyph at 60 % |

Two orthogonal modifiers: **low confidence** (`confidence < 0.6`) → dashed 1 px border and 80 % opacity, with the inspector explaining what could not be resolved; **ghost** → §4.4.

`webview/dev/states.html` renders **every node kind in every state** side by side. It is the cheapest defence against five parallel agents drifting visually, and `states.test.ts` snapshots the class list per state.

### 4.3 Groups and lanes

- **Lane**: radius 14, 1 px border, 4 % stage tint, `--mlv-lane-pad` 20 px, sticky 11 px uppercase label with `--mlv-track-caps`, right-aligned issue cluster.
- **Group** (file / class / loop): 1 px **dashed** border in the stage hue at 40 % alpha, radius 12, tint stepped +3 % per nesting level, dash pattern tightening `6 4` → `4 3` → `2 3` with depth so nesting is legible without more colour. A 34 px header with a chevron (rotates 90° in 180 ms), stage icon, name at 12 px / 650, a `41` count chip and the badge cluster. Clicking the header selects the group (inspector shows an aggregate); clicking the chevron or pressing `Space` collapses.

### 4.4 Ghost nodes — showing the hole

When an absence rule fires (`MLV201`, `MLV202`, `MLV301`), the missing step is rendered **in its correct slot** as a ghost:

- 1.5 px **dashed** border in the severity colour at 70 %, transparent fill, no shadow.
- Label in `--mlv-text-2`: `zero_grad()`; subtitle in italic-weight 450: `missing`.
- The severity marker sits on it exactly as on a real node.
- Clicking it reveals the *enclosing construct* (the loop header), because there is no line to jump to.
- `aria-label`: *"Missing step: optimizer.zero_grad, train stage, 1 high issue."*

This generalises: every absence rule declares a ghost slot. Showing the hole is dramatically more explanatory than a sentence describing it, and it is the single most distinctive visual element in the product.

### 4.5 Edges

| Kind | Stroke | Dash | Arrow | Label |
|---|---|---|---|---|
| `data` | 1.5 px `--mlv-edge` | none | filled 8 px triangle | variable name in a pill, at zoom > 0.9 or on hover |
| `call` | 1.5 px `--mlv-edge` @ 70 % | `4 3` | open 8 px chevron | callee name on hover only |
| `control` | 1.5 px `--mlv-edge` @ 55 % | `1 4`, round caps | small open chevron | `next batch` / `next epoch` with a ↻ glyph on `back` |
| `config` | 1 px `--mlv-edge` @ 40 % | `2 4` | none | hidden until **Show config edges** is toggled |

- Orthogonal elbows with 8 px corner radii; edges never cross a node (routed through lane gutters).
- **Hover**: stroke → `--mlv-text-2`, width +0.5 px, label appears, and both endpoint nodes take a 1 px `--mlv-accent/40` ring — so you can see *what connects to what* without clicking.
- **Selected**: 2.5 px `--mlv-accent` with a `6 6` dash and an 800 ms linear `stroke-dashoffset` marching-ants animation showing flow direction. Disabled under reduced motion and above 200 nodes (a static double-width stroke instead).
- **Issue-bearing edge**: stroked in the severity colour at 80 %, with the severity glyph on a `--mlv-surface` disc at the path midpoint.
- **Merged edges** into a collapsed group: 2.5 px with a `×7` count pill at the midpoint; the dominant kind wins the dash style.
- No edge carries text below 0.9 zoom.

### 4.6 Multi-location connectors

On selecting an issue with `relatedLocs`, a **dotted connector with a small numbered badge** is drawn from the primary node to each related node, labelled with the role (`split site`, `final layer`). For `MLV101` this literally draws the line from `fit_transform` to `train_test_split` across the `preprocess` band — the leak becomes a picture rather than a sentence. The same `relatedLocs` data becomes `DiagnosticRelatedInformation` in the Problems panel for free.

---

## 5. Severity markers *(spec requirement 3, in full)*

Three glyphs, inline SVG, `vector-effect: non-scaling-stroke` so they stay crisp at any zoom. Rendered at 18 px (node badge), 14 px (group / lane header), 12 px (rail rows, inline in text), 10 px ring (minimap).

```
LOW      ⓘ   Filled CIRCLE, r = 7, fill --mlv-sev-low, with a white "i"
              (1.6px stem + 1.6px dot). The smallest, quietest mark —
              a note must never compete with the card's content.

MEDIUM   ⚠   Filled equilateral TRIANGLE, apex up, 2px corner radius,
              fill --mlv-sev-medium, with a DARK "!" (--mlv-sev-medium-ink,
              #3A2500) chosen for ≥4.5:1 against amber, plus a 1px darker
              outline so it survives on amber-ish backgrounds. This is the
              spec's "yellow warning triangle", literally.

HIGH     ❗  Filled OCTAGON (stop-sign silhouette), 18px across,
              fill --mlv-sev-high, with a white "!" and a 3px halo at 25%
              opacity. Octagon rather than circle so high stays distinct
              from low at 10px and in greyscale. This is the spec's
              "red exclamation mark".
```

### Placement and aggregation

- **On a node**: a cluster anchored top-right, `translate(6px, -6px)` so it **overhangs** the card — that is what makes it read as an annotation *on* the card rather than content *inside* it. The cluster is one pill: `[glyph] [count]`, height 20 px, radius 999, background `--mlv-surface`, 1 px border in the severity colour at 45 %, `--mlv-sh-1`.
  - One issue → glyph only, no count (an 18×18 disc).
  - Mixed severities → the **highest** glyph plus the **total** count; the pill's border takes the highest severity colour. The hover card and inspector break the mix down.
- **On a collapsed group or lane header**: up to three stacked glyphs with individual counts (`❗2  ⚠3  ⓘ1`) — at group level the breakdown is the useful information and the 248 px header has room.
- **On an edge**: the glyph on a 16 px `--mlv-surface` disc at the path midpoint, 1 px severity border.
- **In the minimap**: a 1.5 px ring in the highest severity colour, no glyph.
- **In the toolbar, status bar and filter chips**: glyph then count, always in that order.

### Non-negotiables

- **Severity is never conveyed by node fill.** Nodes stay neutral so the markers pop.
- **Shape alone is sufficient.** Verified by a greyscale screenshot test and a deuteranopia simulation, and structurally by `glyphs.test.ts` asserting the three `path` `d` attributes differ.
- Every badge is `role="img"` with `aria-label="{n} issues, highest severity {high|medium|low}"`.
- In high-contrast themes the fills become transparent, strokes go to 2 px `--vscode-contrastBorder`, and the glyph letter (`!` / `i`) is retained — shape + letter still separate all three.
- Optional setting **"Use patterns instead of fills"** adds a 2 px diagonal hatch to the medium triangle and a solid fill to high, for users who prefer texture.

---

## 6. Level of detail

Zoom is written **once per frame** to a single attribute on the pane wrapper. No component re-renders.

```ts
onViewportChange(({ zoom }) => {
  const lod = zoom < 0.5 ? 's' : zoom < 0.9 ? 'm' : 'l';
  if (lod !== lastLod) { pane.dataset.lod = (lastLod = lod); }
});
```

```css
[data-lod="s"] .mlv-node        { height: 28px; width: 140px; border-radius: 999px;
                                  box-shadow: none; }          /* perf */
[data-lod="s"] .mlv-node__sub,
[data-lod="s"] .mlv-node__chips,
[data-lod="s"] .mlv-node__loc   { display: none; }
[data-lod="s"] .mlv-node__title { font-size: var(--mlv-fs-12); }
[data-lod="s"] .mlv-edge-label  { display: none; }
[data-lod="s"] .mlv-canvas-dots { opacity: 0; }

[data-lod="m"] .mlv-node        { height: 52px; }
[data-lod="m"] .mlv-node__chips { display: none; }
```

| Zoom | Node renders as | Edges | Groups |
|---|---|---|---|
| `< 0.5` (`s`) | 140×28 pill: stage dot + title + severity glyph | 1 px, no labels | header name only, background tint |
| `0.5–0.9` (`m`) | 216×52: rail + icon + title + location | no labels | header + count |
| `> 0.9` (`l`) | full 216×72–88 card with chips | data-edge labels | full header with badges |

**The critical decision:** node *boxes* are laid out at LOD `l` dimensions **always**. A smaller rendering simply sits inside its reserved box, anchored top-left. Changing LOD therefore never triggers relayout, and zooming never reflows the picture. This is what makes the diagram feel stable rather than jittery.

---

## 7. Side rail

Three tabs, a 36 px tab strip, `Ctrl+1/2/3`.

### Issues (default)
- Sticky header: a text filter (`⌕ filter issues, code, file`), then a severity chip row `[❗ High 5] [⚠ Med 6] [ⓘ Low 4]` with live counts, then `Group by: Severity ▾ | Stage | File | Rule`.
- Rows are 56 px with 12 px vertical padding: severity glyph · rule code in 11 px mono `--mlv-text-3` · title 12.5 px / 550 · second line `node name · train.py:44` in 11 px mono. A `↗` open-code affordance appears on the right on hover. A `speculative`/`possible` row shows its confidence bucket as a small grey chip, which is how uncertainty reaches the user without a decimal.
- Expanding a row reveals the full `message`, a `why` line, and a **Fix hint** block with a left accent bar, plus **Go to** buttons for the primary loc and each named `relatedLoc` role.
- Click → select + centre the node (260 ms ease) + open the inspector. `Enter` on a focused row opens the code; `Ctrl+Enter` opens it and keeps rail focus.
- Row hover → the node pulses once (2 × 300 ms on its severity ring).
- Empty result: *"No issues match these filters · Clear filters"*.
- Virtualised above 200 rows.

### Inspector
Header (label, stage chip, framework, kind) · qualified name in mono, copyable · **Open in editor ↵** primary button · signature/summary · **Inputs** and **Outputs** as clickable edge chips with their `ValueTag`s · attrs table · **Issues** with message, why, fix hint and related locations · a **"why this stage?"** popover backed by `stageEvidence[]` · **Ask Claude about this node** (VS Code only, composes a prompt with the qualified name, `file:line` and rule codes).

### Outline
A nested tree mirroring `parent`, with severity glyphs on the right and collapse state synced bidirectionally with the canvas. Type-ahead jumps. **This is the screen-reader-complete path**: a user can work entirely here.

---

## 8. Search and command palette

`Ctrl/Cmd+K`, or `/` when the canvas has focus. A 640 × min(480, 60vh) centred dialog, radius 12, `--mlv-sh-3`, backdrop `--mlv-bg/60` with `backdrop-filter: blur(2px)`.

- One input. Empty state shows **Recent** (last 5 selections) and **Commands**.
- A subsequence fuzzy scorer with bonuses for word-boundary, camelCase-boundary and consecutive runs, across: node `label`, `qualname`, `fqn`, `sublabel`, `loc.file`, variable names, issue `code` and `title`, and command names. Results grouped: **Nodes**, **Issues**, **Files**, **Commands**.
- Node row: stage dot · icon · label with matched characters in `--mlv-accent` at weight 600 · severity glyph · right-aligned `train.py:31` in mono.
- Prefix operators: `>` commands only · `#` issues only (`#MLV201`, `#high`) · `@` files only · `:74` line jump within the current file.
- `↑/↓` navigate · `Enter` focus node · `Ctrl+Enter` open code · `Alt+Enter` focus mode · `Esc` restores the previous selection **and** viewport.
- Commands: Fit view · Collapse all · Expand all · Toggle config edges · Filter: only issues · Re-analyze · Export HTML · Toggle rail · Show keyboard shortcuts · Toggle reduced motion · Show speculative findings.

---

## 9. Keyboard model

Single source of truth in `a11y/keymap.ts`, rendered by the `?` sheet.

| Key | Action |
|---|---|
| `Ctrl/Cmd+K`, `/` | Command palette |
| `→` / `←` | First successor / predecessor along `data` edges (falls back to `call`, then `control`) |
| `↓` / `↑` | Next / previous sibling at the same dagre rank, in spatial order |
| `Enter` | Open the selected node's code |
| `Space` | Collapse/expand the group (or the selected node's parent group) |
| `F` / `Shift+F` | Focus mode / focus mode with re-layout |
| `e` / `Shift+E` | Cycle forward / back through the selected node's connections. Each becomes the selection, takes keyboard focus on its hit path, pulses a charge from outlet to inlet, and is announced (*"Connection: SmallCNN to criterion, logits"*). Only routes present in the current projection are reachable. |
| `s` / `Shift+S` | Scope the diagram to the selection (`unit:<qualname>`) / clear the scope |
| `[` / `]` | Step the scope depth down / up, within 0..2 |
| `Esc` | One dismissal per press, topmost first: **shortcut sheet → focus mode → scope → selection → blur the canvas** — `CONTRACTS.md` §11.13 freezes that order, `ui/appkeys.ts` writes it once, and nothing else may re-derive it. An open scope picker is a modal and swallows its own `Esc` before the cascade is reached, so it is not a rung of it. |
| `0` | Fit view · `+` / `-` zoom · `1`–`8` jump to stage lane |
| `Ctrl+B` | Toggle rail · `Ctrl+1/2/3` switch tabs |
| `n` / `p` | Next / previous issue by severity; selects and centres |
| `Ctrl+Shift+E` / `Ctrl+Shift+C` | Expand all / collapse all |
| `1` / `2` / `3` | Toggle high / medium / low filters (when the canvas has focus) |
| `Alt+M` | *(host)* Reveal the current editor symbol in the diagram |
| `Alt+Shift+M` | *(host)* Scope the diagram to the symbol the cursor is inside |
| `?` | Shortcut sheet |

---

## 10. Accessibility

- **Structure.** The canvas is `role="application"` with `aria-label="ML pipeline diagram"`, `aria-activedescendant="{selectedNodeId}"` and `tabindex="0"`. Each node is a `div role="button"` with a stable `id`, `tabindex="-1"`, and a full label:
  `"Optimizer Adam, objective stage, train.py line 34, 2 issues, highest severity high. 1 input, 1 output."`
- **Announcements.** An `aria-live="polite"` region announces selection changes, collapse/expand (*"Group models/resnet.py collapsed, 41 nodes hidden"*), filter changes, and analysis completion (*"Analysis complete: 38 nodes, 15 issues, 5 high"*).
- **Contrast.** All text ≥ 4.5:1, all UI/graphic boundaries ≥ 3:1, verified by `contrast.test.ts` walking every declared token pair in light, dark and high contrast. This is the mechanical defence against the amber-on-light trap.
- **Focus.** 2 px `--mlv-focus` ring with 2 px offset, `:focus-visible` only, never removed.
- **Hit targets** ≥ 24×24 (chips get padding to reach it).
- **Nothing hover-only.** Everything in a tooltip is also in the inspector.
- **Reduced motion** disables layout transitions, marching ants, the selection pulse and the palette scale-in (opacity only).
- **Linear alternative.** The Outline tab is a nested `<ul>` with the same labels and jump links — the complete non-visual path through the graph.

---

## 11. Motion

| Interaction | Property | Duration / easing |
|---|---|---|
| Node hover | `transform`, `box-shadow` | 120 ms `--mlv-ease` |
| Selection ring | `box-shadow` | 120 ms |
| Group chevron | `rotate` | 180 ms |
| Rail open/close | `transform: translateX`, `opacity` | 180 ms |
| Hover card | `opacity` 0→1, `translateY` 4→0 | 180 ms; 400 ms open delay, 120 ms close delay |
| Command palette | `opacity`, `scale` .98→1 | 140 ms |
| Collapse/expand relayout | node `transform` | 260 ms, staggered 0–60 ms by rank |
| Centre-on-node | viewport tween | 260 ms |
| Issue-row hover pulse | severity ring `opacity` | 2 × 300 ms |
| Selected edge | `stroke-dashoffset` | 800 ms linear, infinite |
| **Flow — one charge** (hover / focus / select one connection) | a travelling **dot with a halo** — three concentric circles moved by `<animateMotion>` along the route's own `d`, over a faint static wash of that same `d` (amended 2026-09-08, CONTRACTS 11.13.1; originally a 12 px `.mlv-edge__flow` dash) | 320 px/s, clamped to 380–2200 ms; a route over 360 px carries a second dot half a period behind |
| **Flow — a lineage stream** (hover a node) | a dash repeating along every lit, flow-eligible edge | 220 px/s; 34 / 96 / 24 px gaps for `data` / `call`+`control:enter` / `control:back`, staggered 90 ms per hop, capped at 6 hops |

Direction is never decided: every router emits `points` source → target, so animating along `d` is always **outlet → inlet**. Length is summed from those points — `getTotalLength()` is never called, so the tested path and the shipped path are the same path.

`.mlv-canvas` carries two attributes, one job each: `data-motion` (`full` | `reduced`, from `matchMedia`) and `data-flow` (`motion` | `static` | `off`). Under reduced motion, or above `FLOW_MAX_EDGES = 120` lit edges, the canvas flips to `static`: no element is built at all, and the connection is read instead from a direction chevron at its midpoint plus a hollow outlet dot and a filled inlet dot. Nothing is lost; nothing moves. The stylesheet repeats the guarantee (`@media (prefers-reduced-motion: reduce) { .mlv-edge__flow { display: none !important } }`) because the blanket clamp elsewhere *freezes* an animation rather than removing it, which would park a stub at every outlet.

The charge takes the edge's colour, and severity wins: `--mlv-flow-color` is the source node's stage hue on a clean edge and the severity hue on one carrying an issue, so the wrong tensor is the one you watch move into the loss. `config` edges never join a lineage stream — they pulse only when pointed at directly.

*Amended 2026-09-08 (CONTRACTS 11.13.1).* The single-connection charge is a **dot**, not a line. A brighter 12 px segment of a 3 px cable, inside a diagram made of 3 px cables, reads as a lit piece of wire rather than as something moving through one; the halo is what separates the charge from its own conductor. The soft edge is three stacked circle opacities — halo `r 9` at ~0.18, glow `r 5.5` at ~0.42, and a surface-filled core `r 2.6` ringed in `--mlv-flow-color` — and never an SVG filter, whose region would be re-rasterized every frame. The colour rule above governs the dot unchanged, so the severity connection still runs red. The lineage stream keeps its dash train: there the question is *how dense is the traffic on this hop*, which a repeating pattern answers at a glance and thirty separate dots do not.

All layout transitions are disabled above 200 nodes or under reduced motion — positions snap. Nothing loops or pulses without a user action, the flow layer included: it exists only while the pointer, the keyboard focus or the selection is on a connection.

---

## 12. Designed states

**Loading** *(only after 400 ms of work — avoid a flash)*. Skeleton graph: 9 ghost cards in a 3-rank arrangement, `--mlv-surface-2` fill, a 1200 ms shimmer sweep, connected by faint edges. Centred above: a 2 px **determinate** progress bar (240 px) and `Parsing 42 of 128 files…`, plus **Cancel**.

**Empty — no ML detected.** A centred 420 px column: a light line illustration of three connected nodes; heading *"No ML pipeline found"*; body *"MLView looks for PyTorch, scikit-learn, Keras/TensorFlow, HuggingFace and Lightning code."*; a **What MLView looks for** disclosure listing `nn.Module subclasses · Dataset / DataLoader · train_test_split · optimizers and losses · .fit() / .predict()`; and — crucially — **the top unresolved imports found in the workspace**, which doubles as a coverage bug report. Buttons: **Choose a folder…**, **Open the demo project**.

**Empty — filters.** In-canvas centred: *"No nodes match your filters"* + **Clear all filters**. Never a blank canvas.

**Partial parse errors.** The graph renders. A dismissible amber banner under the toolbar: *"⚠ 3 files could not be parsed"* with a **Details** disclosure listing `legacy/old.py — SyntaxError: invalid syntax (line 12)`, each clickable. The status bar keeps a persistent `⚠ 3` after dismissal.

**Partial understanding.** A distinct blue-tinted banner when any scope is `dynamic`: *"Some calls could not be resolved (config-driven or dynamic). 4 nodes are shown as unknown and confidence is reduced in 2 files."* with a **Details** list.

**Framework suppression chip.** *"Training loop handled by PyTorch Lightning — 7 rules not applicable"*, expandable to the list of codes. This is what stops a quiet diagram from reading as a broken tool.

**Hard error.** Full-canvas: red-tinted icon, *"Analysis failed"*, the first 6 lines of stderr in a mono scroll box, and **Copy details** · **Retry** · **Select Python Interpreter** (opens the `mlview.pythonPath` setting).

**Stale.** A 28 px amber bar: *"Files changed since this analysis · Re-analyze (⟳)"*; affected nodes take the dashed stale border. Selection and viewport survive re-analysis because node ids are content-addressed.

**Notebooks.** Status-bar chip: *"3 notebooks not analyzed"*, with a tooltip explaining `.ipynb` support is not in this version.

**Truncation.** *"Graph truncated at 400 nodes — 512 more not shown. Narrow the scope with --include, or collapse groups."*

**Toasts.** Bottom-centre, 320 px, max 3 stacked, 4 s auto-dismiss: `Copied train.py:44` · `Exported report.html` · `8 groups collapsed · Expand all`.

---

## 13. Click-to-code, both directions

**Diagram → code.** Click a node or an edge → `bridge.openLocation(loc)`.
- *VS Code*: `showTextDocument` with the range selected and `revealRange(InCenterIfOutsideViewport)`, then a 1200 ms fading decoration (`--mlv-accent` at 12 %) over the range so the eye lands on it. Node clicks open the definition range; **edge clicks open the call site**, which is what makes "click a connection" meaningful.
- *Standalone*: hand `vscode://file/{absFile}:{line}:{col+1}` to the OS through a hidden `<iframe>`; after 400 ms with no blur, fall back to copying `train.py:44` and showing a toast. The inspector also shows the `snippet`, so the report is useful with no editor at all.
  *Amended 2026-09-08 (CONTRACTS 11.17).* The report must never navigate **itself**. The original design said "navigate to `vscode://…`", and a hidden same-frame `<a>` click was the obvious reading of it — which, inside a sandboxed iframe, makes the browser replace the whole frame with *"This content is blocked. Contact the site owner to fix the issue."* So the launch is attempted only from a **top-level `file:` document**, and only through a throwaway iframe. Anywhere else — embedded, or served over `http(s)` — the click copies `train.py:44` and the toast carries an **Open in VS Code** link with `target="_blank"`, so a permissive host still jumps and a restrictive one merely drops the click.

**Code → diagram.** `Alt+M`. `locationIndex.ts` builds, at graph load, a per-file sorted interval array `[startLine, endLine, nodeId, span]`; the lookup picks the **narrowest** interval containing the cursor line, so `forward` wins over its enclosing class. Posts `reveal/node`; the webview selects, expands every collapsed ancestor, and centres with a 260 ms tween and one 300 ms ring pulse. With no containing node, the nearest node in the same file is selected and a toast says *"Nearest node: build_loaders"*.

---

## 14. Component inventory

`Canvas` · `Lane` · `NodeCard` (all kinds, memoized) · `GhostNode` · `GroupBox` · `EdgeLayer` (one `BaseEdge` with a `kind` prop) · `SeverityGlyph(size, severity)` · `SeverityBadge(cluster)` · `StageChip` · `Icon` (sprite of 22 symbols) · `HoverCard` (flip/shift positioning, 400/120 ms delays) · `Toolbar` · `ChipRow` · `Breadcrumb` · `StatusBar` · `MiniMap` · `Rail` + `IssuesTab` / `InspectorTab` / `OutlineTab` · `CommandPalette` + `fuzzy` · `FilterMenu` · `Toasts` · `EmptyState` · `LoadingState` · `ErrorState` · `Banner` · `ShortcutSheet` · `keymap` · `announcer` · `bridge`.

**View state** (persisted via `bridge.saveState`): `{ viewport:{x,y,zoom}, selection:{kind,id}|null, collapsed:string[], focus:{id,up,down}|null, filters:{severity[],stage[],framework[],file[],onlyIssues,showSpeculative,showConfigEdges}, rail:{open,tab,width}, lod }`.

**Build rules for the front-end agent:** no `innerHTML`, ever — build with `createElementNS` / `textContent`; no raw hex outside `tokens.css`; no external font, image or script; node boxes measured at full-detail size regardless of LOD; every interactive element focusable with a label.
