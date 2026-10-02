// Viewer M3, roadmap step 14: MLView: Reveal in Diagram, the webview side. The host posts
// `reveal {kind, id}` (a step, a connection or a finding the reader chose in the editor) and moves
// the keyboard focus to the panel; the viewer selects the claim, brings it into view above the
// bottom sheet and clear of the phase index, shows it in the Selection tab and puts the keyboard on
// it. The older `revealNode` and `revealIssue` frames reach the same handlers.
//
// The fixtures are a small hand-made document and SYNTHETIC documents of the shapes of the two
// public shakedown artifacts (helpers.mjs). jsdom lays nothing out: the panel and canvas boxes are
// stubbed, the bottom sheet's share of the height as in phase-overview.test.mjs. The host is the
// test's recording bridge. None of this is a live VS Code check, a usability check or a review of
// what the claims say.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { loadBundle, recordingBridge, shapedWorkflow, VIT_SHAPE, WEBVIEW_ROOT, YOLO_SHAPE } from './helpers.mjs';

const CSS = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.css'), 'utf8');
const plain = (value) => (value === undefined ? undefined : JSON.parse(JSON.stringify(value)));

/** Two phases; a group `loop` with two steps; connections into and inside it; findings on steps and on a connection only. */
function smallDoc() {
  const ev = (id, line) => ({ id, file: 'train.py', line, endLine: line + 1, quote: 'x()' });
  return {
    workflowVersion: '1.0', title: 'Reveal fixture', producer: { kind: 'host-llm', host: 'codex', model: 'm' }, revision: { id: 'rv1' },
    request: { question: 'q', scope: 's' },
    phases: [{ id: 'data', label: 'Data' }, { id: 'fit', label: 'Fit' }],
    nodes: [
      { id: 'load', label: 'Load batches', phase: 'data', basis: 'observed', evidence: ['e1'] },
      { id: 'loop', label: 'Epoch loop', phase: 'fit', kind: 'group', basis: 'observed', evidence: [] },
      { id: 'step', label: 'Optimizer step', phase: 'fit', parent: 'loop', basis: 'inferred', evidence: ['e2'] },
      { id: 'zero', label: 'Zero grads', phase: 'fit', parent: 'loop', basis: 'observed', evidence: ['e3'] },
    ],
    edges: [
      { id: 'c-load-step', source: 'load', target: 'step', label: 'batches', basis: 'observed', evidence: ['e1'] },
      { id: 'c-step-zero', source: 'step', target: 'zero', label: 'then', basis: 'observed', evidence: ['e2'] },
    ],
    findings: [
      { id: 'f-two', title: 'Order risk', message: 'm', severity: 'high', nodeIds: ['load', 'zero'], basis: 'inferred', evidence: ['e3'] },
      { id: 'f-edge', title: 'Cast on batches', message: 'm', severity: 'medium', nodeIds: [], edgeIds: ['c-load-step'], basis: 'unresolved', evidence: ['e1'] },
    ],
    evidence: [ev('e1', 3), ev('e2', 9), ev('e3', 14)],
    coverage: { status: 'scoped', summary: 's', inspectedFiles: ['train.py'], limitations: [] },
  };
}

const RAIL_W = 360;
const SHEET_SHARE = 0.47;
/** The panel sizes the roadmap names: wide, and beside the code at about 900 and 541 px. */
const PANELS = [
  ['1440x900', { width: 1440, bodyH: 842 }],
  ['900x800', { width: 900, bodyH: 742 }],
  ['541x798', { width: 541, bodyH: 740 }],
];

/** Mount `document` in a panel `width` px wide whose body (between header and status bar) is `bodyH` px. */
async function mount(document, opts = {}) {
  const ctx = await loadBundle();
  const style = ctx.document.createElement('style');
  style.textContent = CSS;
  ctx.document.head.appendChild(style);
  ctx.document.body.classList.add('vscode-reduce-motion');
  const root = ctx.document.getElementById('mlview-root');
  let width = opts.width || 1440;
  const bodyH = opts.bodyH || 842;
  root.getBoundingClientRect = () => ({ x: 0, y: 0, top: 0, left: 0, width, height: bodyH + 58, right: width, bottom: bodyH + 58 });
  const bridge = recordingBridge(ctx.window, 'vscode');
  const app = ctx.MLView.mountWorkflow(root, document, bridge);
  const canvas = ctx.document.querySelector('.mlv-canvas');
  const rail = ctx.document.querySelector('.mlv-rail');
  const box = () => {
    const docked = rail.getAttribute('data-mode') !== 'sheet';
    const w = docked ? width - (rail.hidden ? 0 : RAIL_W) : width;
    const sheet = docked ? 0 : rail.getAttribute('data-expanded') === 'true' ? Math.round(bodyH * SHEET_SHARE) : 32;
    return { w, h: bodyH - sheet };
  };
  canvas.getBoundingClientRect = () => {
    const { w, h } = box();
    return { x: 0, y: 0, top: 0, left: 0, width: w, height: h, right: w, bottom: h };
  };
  ctx.window.dispatchEvent(new ctx.window.Event('resize'));
  app.view.fit();
  canvas.focus();
  return { ...ctx, root, bridge, app, canvas, rail, box };
}

const $ = (ctx, selector) => ctx.document.querySelector(selector);
const live = (ctx) => $(ctx, '.mlv-root > [aria-live]').textContent;
const toasts = (ctx) => Array.from(ctx.document.querySelectorAll('.mlv-toast'), (t) => t.textContent);
const selection = (ctx) => plain(ctx.app.getState().selection);
const reveal = (ctx, kind, id) => ctx.bridge.send({ v: 1, type: 'reveal', kind, id });
const press = (ctx, key, init = {}, target = ctx.document.activeElement || ctx.canvas) => {
  const event = new ctx.window.KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init });
  target.dispatchEvent(event);
  return event;
};
/** A world box on screen, at the current viewport. */
function onScreen(ctx, b) {
  const vp = ctx.app.getState().viewport;
  return { x: b.x * vp.zoom + vp.x, y: b.y * vp.zoom + vp.y, w: b.w * vp.zoom, h: b.h * vp.zoom };
}
const overlaps = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
/** Why the card `id` is not wholly on the canvas and clear of the phase index, or null. */
function offScreen(ctx, id) {
  const shown = ctx.app.index.visibleRepresentative(id, ctx.app.view.collapsed);
  const b = ctx.app.view.frameData.boxes.get(shown);
  if (!b) return `${id}: no box`;
  const s = onScreen(ctx, b);
  const { w, h } = ctx.box();
  if (!(s.x >= -0.5 && s.y >= -0.5 && s.x + s.w <= w + 0.5 && s.y + s.h <= h + 0.5)) return `${id}: card ${s.x.toFixed(0)},${s.y.toFixed(0)} ${s.w.toFixed(0)}x${s.h.toFixed(0)} outside the canvas ${w}x${h}`;
  const covered = ctx.app.view.viewport.covered();
  if (covered && overlaps(s, covered)) return `${id}: card under the phase index`;
  return null;
}

/* ── the frame ───────────────────────────────────────────────────────── */

test('a reveal frame selects the step, shows it in the Selection tab, and puts the keyboard on its card', async () => {
  const ctx = await mount(smallDoc());
  try {
    reveal(ctx, 'node', 'load');
    assert.deepEqual(selection(ctx), { kind: 'node', id: 'load' });
    assert.equal(ctx.app.getState().railTab, 'inspector', 'the claim is in the Selection tab');
    assert.equal(ctx.document.activeElement, ctx.app.view.nodeElement('load'), 'the keyboard is on the card');
    assert.match($(ctx, '.mlv-rail').textContent, /Load batches/);
    assert.equal(ctx.bridge.posted.some((m) => m.type === 'openLocation'), false, 'nothing is opened: the editor already shows the code');
    assert.equal(ctx.bridge.posted.some((m) => m.type === 'log'), false, 'a known frame');
    assert.equal(offScreen(ctx, 'load'), null);
    // The diagram's keys answer at once: Enter opens the step's quote beside, focus kept.
    press(ctx, 'Enter');
    const open = ctx.bridge.posted.filter((m) => m.type === 'openLocation').at(-1);
    assert.equal(open && open.evidenceId, 'e1');
    assert.notEqual(open.focus, true);
  } finally {
    ctx.app.destroy();
  }
});

test('VS Code\'s focus hand-over that leaves the page on <body> right after a reveal gets the keyboard back on the claim, for a moment only', async () => {
  const ctx = await mount(smallDoc());
  try {
    reveal(ctx, 'node', 'zero');
    const card = ctx.app.view.nodeElement('zero');
    assert.equal(ctx.document.activeElement, card);
    // The outer frame takes the focus (this page loses it), then gives it back to the window.
    card.blur();
    assert.equal(ctx.document.activeElement, ctx.document.body);
    ctx.window.dispatchEvent(new ctx.window.Event('focus'));
    assert.equal(ctx.document.activeElement, card, 'back on the revealed card');
    // A focus the reader moved elsewhere is left alone.
    const tab = ctx.document.querySelector('.mlv-rail__tab');
    tab.focus();
    ctx.window.dispatchEvent(new ctx.window.Event('focus'));
    assert.equal(ctx.document.activeElement, tab);
    // After the hold, a window focus changes nothing.
    await new Promise((done) => setTimeout(done, 1600));
    card.focus();
    card.blur();
    ctx.window.dispatchEvent(new ctx.window.Event('focus'));
    assert.equal(ctx.document.activeElement, ctx.document.body);
  } finally {
    ctx.app.destroy();
  }
});

test('a step inside a collapsed group: the group opens, the step is selected and its card has the keyboard', async () => {
  const ctx = await mount(smallDoc());
  try {
    ctx.app.view.toggleCollapse('loop');
    assert.ok(ctx.app.view.collapsed.has('loop'));
    assert.equal(ctx.app.view.nodeElement('step'), undefined, 'hidden in the collapsed group');
    reveal(ctx, 'node', 'step');
    assert.equal(ctx.app.view.collapsed.has('loop'), false, 'the group opened');
    assert.deepEqual(selection(ctx), { kind: 'node', id: 'step' });
    assert.equal(ctx.document.activeElement, ctx.app.view.nodeElement('step'));
    assert.equal(offScreen(ctx, 'step'), null);
  } finally {
    ctx.app.destroy();
  }
});

test('the edge case: a connection is selected with both its ends drawn and in view, and the keyboard is on it', async () => {
  const ctx = await mount(smallDoc());
  try {
    ctx.app.view.toggleCollapse('loop');
    reveal(ctx, 'edge', 'c-load-step');
    assert.deepEqual(selection(ctx), { kind: 'edge', id: 'c-load-step' });
    assert.equal(ctx.app.view.collapsed.has('loop'), false, 'the group around its target opened');
    assert.equal(ctx.app.getState().railTab, 'inspector');
    assert.match($(ctx, '.mlv-rail').textContent, /batches/);
    const hit = ctx.document.querySelector('.mlv-edge[data-edge-id="c-load-step"] .mlv-edge__hit');
    assert.ok(hit, 'the connection is drawn');
    assert.equal(ctx.document.activeElement, hit, 'the keyboard is on the connection');
    assert.equal(offScreen(ctx, 'load'), null, 'its source in view');
    assert.equal(offScreen(ctx, 'step'), null, 'its target in view');
  } finally {
    ctx.app.destroy();
  }
});

test('a finding is selected with every step it cites in view, and the keyboard on the canvas', async () => {
  const ctx = await mount(smallDoc());
  try {
    ctx.app.view.toggleCollapse('loop');
    reveal(ctx, 'issue', 'f-two');
    assert.deepEqual(selection(ctx), { kind: 'issue', id: 'f-two' });
    assert.equal(ctx.app.view.collapsed.has('loop'), false, 'the group around a cited step opened');
    assert.equal(ctx.document.activeElement, ctx.canvas);
    assert.equal(offScreen(ctx, 'load'), null);
    assert.equal(offScreen(ctx, 'zero'), null);
    // A finding that cites only a connection: its ends are drawn.
    reveal(ctx, 'issue', 'f-edge');
    assert.deepEqual(selection(ctx), { kind: 'issue', id: 'f-edge' });
  } finally {
    ctx.app.destroy();
  }
});

test('the older revealNode and revealIssue frames reach the same handlers', async () => {
  const ctx = await mount(smallDoc());
  try {
    ctx.bridge.send({ v: 1, type: 'revealNode', nodeId: 'zero', center: true });
    assert.deepEqual(selection(ctx), { kind: 'node', id: 'zero' });
    assert.equal(ctx.app.getState().railTab, 'inspector');
    ctx.bridge.send({ v: 1, type: 'revealIssue', issueId: 'f-edge' });
    assert.deepEqual(selection(ctx), { kind: 'issue', id: 'f-edge' });
  } finally {
    ctx.app.destroy();
  }
});

test('a malformed reveal changes nothing and is not logged as unknown; an id the revision lacks says so', async () => {
  const ctx = await mount(smallDoc());
  try {
    ctx.app.select({ kind: 'node', id: 'load' });
    const before = selection(ctx);
    for (const frame of [
      { v: 1, type: 'reveal', kind: 'node' },
      { v: 1, type: 'reveal', kind: 'node', id: '' },
      { v: 1, type: 'reveal', kind: 'node', id: 7 },
      { v: 1, type: 'reveal', kind: 'phase', id: 'data' },
      { v: 1, type: 'reveal', id: 'load' },
      { v: 2, type: 'reveal', kind: 'node', id: 'zero' },
      { v: 1, type: 'revealNode' },
      { v: 1, type: 'revealIssue', issueId: 3 },
    ]) ctx.bridge.send(frame);
    assert.deepEqual(selection(ctx), before);
    assert.equal(ctx.bridge.posted.some((m) => m.type === 'log'), false);
    reveal(ctx, 'node', 'gone');
    reveal(ctx, 'edge', 'gone');
    reveal(ctx, 'issue', 'gone');
    assert.deepEqual(selection(ctx), before, 'the selection is kept');
    assert.ok(toasts(ctx).includes('That claim is not in the revision shown here.'));
    assert.equal(live(ctx), 'That claim is not in the revision shown here.');
  } finally {
    ctx.app.destroy();
  }
});

test('the shortcut sheet, the Refine popover (its text kept) and the phase overview close first', async () => {
  const ctx = await mount(smallDoc());
  try {
    // The phase overview.
    ctx.app.toggleOverview();
    assert.equal(ctx.app.view.overviewOpen, true);
    reveal(ctx, 'node', 'zero');
    assert.equal(ctx.app.view.overviewOpen, false, 'the overview closed');
    assert.deepEqual(selection(ctx), { kind: 'node', id: 'zero' });
    assert.equal(ctx.document.activeElement, ctx.app.view.nodeElement('zero'));
    // The shortcut sheet.
    ctx.app.toggleShortcuts(true);
    assert.equal($(ctx, '.mlv-sheet').hidden, false);
    reveal(ctx, 'node', 'load');
    assert.equal($(ctx, '.mlv-sheet').hidden, true, 'the shortcut sheet closed');
    assert.equal(ctx.document.activeElement, ctx.app.view.nodeElement('load'));
    // The Refine… popover, with a custom request typed.
    $(ctx, '.mlv-workflow__refine').click();
    const composer = $(ctx, '.mlv-workflow__composer');
    assert.equal(composer.hidden, false);
    const intent = $(ctx, '.mlv-workflow__intent');
    intent.value = 'custom';
    intent.dispatchEvent(new ctx.window.Event('change'));
    $(ctx, '.mlv-workflow__custom').value = 'Check the cast';
    reveal(ctx, 'edge', 'c-step-zero');
    assert.equal(composer.hidden, true, 'the popover closed');
    assert.equal($(ctx, '.mlv-workflow__custom').value, 'Check the cast', 'its text is kept');
    assert.deepEqual(selection(ctx), { kind: 'edge', id: 'c-step-zero' });
  } finally {
    ctx.app.destroy();
  }
});

test('the shortcut sheet says how to come back from the code', async () => {
  const ctx = await mount(smallDoc());
  try {
    ctx.app.toggleShortcuts(true);
    assert.match($(ctx, '.mlv-sheet__note').textContent, /From the code: right-click a cited line in the editor and choose Reveal in Diagram to show the claim that cites it here\./);
  } finally {
    ctx.app.destroy();
  }
});

test('during the review walk, a reveal moves the walk to that claim without opening it', async () => {
  const ctx = await mount(smallDoc());
  try {
    assert.equal(ctx.app.walk.start('all'), true);
    const opensBefore = ctx.bridge.posted.filter((m) => m.type === 'openLocation').length;
    reveal(ctx, 'edge', 'c-step-zero');
    assert.equal(ctx.app.walk.active, true, 'the walk goes on');
    assert.deepEqual(plain(ctx.app.walk.current()), { kind: 'edge', id: 'c-step-zero' });
    assert.equal(ctx.bridge.posted.filter((m) => m.type === 'walk').at(-1).state, 'clear', 'the earlier highlight goes');
    await new Promise((done) => setTimeout(done, 200));
    assert.equal(ctx.bridge.posted.filter((m) => m.type === 'openLocation').length, opensBefore, 'nothing is opened');
  } finally {
    ctx.app.destroy();
  }
});

test('a side panel the reader hid opens to show the claim (as for the walk)', async () => {
  const ctx = await mount(smallDoc(), { width: 1440 });
  try {
    assert.equal(ctx.rail.getAttribute('data-mode'), 'docked');
    ctx.app.toggleRail();
    assert.equal(ctx.app.railOpen, false, 'the reader hid it');
    reveal(ctx, 'node', 'step');
    assert.equal(ctx.app.railOpen, true);
    assert.equal(ctx.app.getState().railTab, 'inspector');
    assert.equal(offScreen(ctx, 'step'), null, 'in view beside the opened panel');
  } finally {
    ctx.app.destroy();
  }
});

/* ── at the owner's widths ───────────────────────────────────────────── */

for (const [name, opts] of PANELS) {
  for (const [shapeName, shape] of [['vit-cc', VIT_SHAPE], ['yolov5-cc2', YOLO_SHAPE]]) {
    test(`at ${name}, the ${shapeName} shape: every step and connection revealed from the code is on the canvas, above the sheet and clear of the phase index`, async () => {
      const document = shapedWorkflow(shape);
      const ctx = await mount(document, { ...opts });
      const failures = [];
      try {
        const sheet = ctx.rail.getAttribute('data-mode') === 'sheet';
        assert.equal(sheet, opts.width < 1000, 'the bottom sheet below 1000 px');
        if (sheet) {
          ctx.app.collapseSheet(false);
          assert.equal(ctx.rail.getAttribute('data-expanded'), 'false', 'the sheet starts collapsed');
        }
        const startZoom = ctx.app.getState().viewport.zoom;
        let first = true;
        for (const node of document.nodes) {
          reveal(ctx, 'node', node.id);
          if (first && sheet) assert.equal(ctx.rail.getAttribute('data-expanded'), 'true', 'a collapsed sheet opens on the claim');
          if (first) assert.ok(ctx.app.getState().viewport.zoom >= startZoom, 'never zoomed out to show a step');
          first = false;
          const sel = selection(ctx);
          if (!sel || sel.id !== node.id) failures.push(`${node.id}: not selected`);
          if (ctx.document.activeElement !== ctx.app.view.nodeElement(node.id) && !ctx.app.index.isGroup(node.id)) failures.push(`${node.id}: not focused`);
          // A group's box frames its steps and can be larger than the canvas.
          if (!ctx.app.index.isGroup(node.id)) {
            const why = offScreen(ctx, node.id);
            if (why) failures.push(why);
          }
        }
        let both = 0;
        for (const edge of document.edges.slice(0, 40)) {
          reveal(ctx, 'edge', edge.id);
          const sel = selection(ctx);
          if (!sel || sel.kind !== 'edge' || sel.id !== edge.id) failures.push(`${edge.id}: not selected`);
          // The source card is always in view; the target too when both fit at the frame's floor zoom.
          // (A group's box frames its steps and can be larger than the canvas.)
          const card = (id) => !ctx.app.index.isGroup(ctx.app.index.visibleRepresentative(id, ctx.app.view.collapsed));
          const why = card(edge.source) ? offScreen(ctx, edge.source) : null;
          if (why) failures.push(`${edge.id} source ${why}`);
          const boxes = [edge.source, edge.target].map((id) => ctx.app.view.frameData.boxes.get(ctx.app.index.visibleRepresentative(id, ctx.app.view.collapsed)));
          const x = Math.min(...boxes.map((b) => b.x));
          const y = Math.min(...boxes.map((b) => b.y));
          const union = { x, y, w: Math.max(...boxes.map((b) => b.x + b.w)) - x, h: Math.max(...boxes.map((b) => b.y + b.h)) - y };
          if (card(edge.source) && card(edge.target) && ctx.app.view.viewport.fitsAt(union, 0.45)) {
            both++;
            const whyTarget = offScreen(ctx, edge.target);
            if (whyTarget) failures.push(`${edge.id} target ${whyTarget}`);
          }
          // The keyboard is on the connection, or on the canvas when it is drawn in a bundle.
          const hit = ctx.document.querySelector(`.mlv-edge[data-edge-id="${edge.id}"] .mlv-edge__hit`);
          if (ctx.document.activeElement !== (hit || ctx.canvas)) failures.push(`${edge.id}: not focused`);
        }
        assert.ok(both > 0, 'some connections fit whole');
        for (const finding of document.findings) {
          reveal(ctx, 'issue', finding.id);
          const sel = selection(ctx);
          if (!sel || sel.kind !== 'issue' || sel.id !== finding.id) failures.push(`${finding.id}: not selected`);
          if (finding.nodeIds.length) {
            const why = offScreen(ctx, finding.nodeIds[0]);
            if (why) failures.push(`${finding.id} first cited step ${why}`);
          }
        }
        assert.deepEqual(failures, [], failures.slice(0, 8).join('\n'));
      } finally {
        ctx.app.destroy();
      }
    });
  }
}
