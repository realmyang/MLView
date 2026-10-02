// Campaign 3 viewer fixes: the authored header, the canvas floor, the rail and minimap rules,
// refit and reveal, single-truncation titles, authored kind glyphs and the edge-kind vocabulary.
//
// jsdom performs no layout, so the header regression is asserted as DOM state (collapsed by
// default, the disclosure's behaviour) plus the shipped CSS constraints that make the canvas
// survive a contract-maximum header. The real-Chromium measurement of the same fix is a
// separate script run outside the gate (the Campaign 3 viewer-fix notes record it); none of this
// is a claim about how a human reads the diagram.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { WEBVIEW_ROOT, loadBundle, recordingBridge, rendererRegressionWorkflow } from './helpers.mjs';

/** The legacy question-mark glyph; no authored node may draw it. */
const QUESTION_GLYPH_PREFIX = 'M8 2.2A5.8 5.8 0 1 0 8 13.8 5.8 5.8 0 0 0 8 2.2ZM6.2 6.3';

const words = (n, seed) => {
  let s = '';
  for (let i = 0; s.length < n; i++) s += (i ? ' ' : '') + seed + i;
  return s.slice(0, n);
};

function doc(overrides = {}) {
  return {
    workflowVersion: '1.0', title: 'Layout fixture',
    producer: { kind: 'host-llm', host: 'claude-code', model: 'fixture-model' }, revision: { id: 'r1' },
    request: { question: 'How does the loop update state?', scope: 'src/', entrypoints: ['src/train.py'], configuration: 'defaults' },
    phases: [{ id: 'prep', label: 'Prepare' }, { id: 'loop', label: 'Loop' }],
    nodes: [
      { id: 'a', label: 'Read the records', phase: 'prep', kind: 'data', basis: 'observed', evidence: ['e1'] },
      { id: 'b', label: 'Update weights', phase: 'loop', kind: 'optimizer', basis: 'inferred', evidence: ['e1'] },
    ],
    edges: [{ id: 'ab', source: 'a', target: 'b', label: 'batches', kind: 'data', basis: 'observed', evidence: ['e1'] }],
    findings: [{ id: 'f1', title: 'Late reduction', message: 'm', severity: 'medium', nodeIds: ['b'], edgeIds: [], basis: 'inferred', evidence: ['e1'] }],
    evidence: [{ id: 'e1', file: 'src/train.py', line: 1, endLine: 1, quote: 'x' }],
    coverage: { status: 'partial', summary: 'Core path', inspectedFiles: ['src/train.py'], limitations: ['Launcher not read.'] },
    ...overrides,
  };
}

/** Every header-visible string at its contract maximum (contracts/workflow.schema.json). */
function contractMaxHeader() {
  return doc({
    title: words(200, 'Title'),
    producer: { kind: 'host-llm', host: 'claude-code', model: 'M'.repeat(200) },
    revision: { id: 'r' + 'x'.repeat(127) },
    request: {
      question: words(4000, 'question'), scope: words(2000, 'scope'),
      entrypoints: Array.from({ length: 100 }, (_, i) => `src/${'d'.repeat(480)}/entry${i}.py`),
      configuration: words(2000, 'config'),
    },
    phases: Array.from({ length: 100 }, (_, i) => ({ id: `p${i}`, label: words(200, `phase${i}w`) })).concat([{ id: 'prep', label: 'Prepare' }, { id: 'loop', label: 'Loop' }]),
    coverage: { status: 'partial', summary: words(4000, 'summary'), inspectedFiles: ['src/train.py'], limitations: Array.from({ length: 500 }, (_, i) => words(2000, `lim${i}w`)) },
  });
}

async function mount(document, opts = {}) {
  const ctx = await loadBundle();
  const root = ctx.document.getElementById('mlview-root');
  if (opts.rootWidth) root.getBoundingClientRect = () => ({ x: 0, y: 0, top: 0, left: 0, width: opts.rootWidth(), height: 798, right: opts.rootWidth(), bottom: 798 });
  const bridge = recordingBridge(ctx.window, 'vscode');
  const app = ctx.MLView.mountWorkflow(root, document, bridge);
  return { ...ctx, root, bridge, app };
}

function sizeCanvas(ctx, size) {
  const canvas = ctx.document.querySelector('.mlv-canvas');
  canvas.getBoundingClientRect = () => ({ x: 0, y: 0, top: 0, left: 0, width: size.w, height: size.h, right: size.w, bottom: size.h });
}

const resize = (ctx) => ctx.window.dispatchEvent(new ctx.window.Event('resize'));

/** Declarations the built stylesheet applies to `selector`, merged across every rule that lists it. */
function declarationsFor(css, selector) {
  const out = {};
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m;
  while ((m = re.exec(css))) {
    const selectors = m[1].split(',').map((s) => s.trim());
    if (!selectors.includes(selector)) continue;
    for (const decl of m[2].split(';')) {
      const i = decl.indexOf(':');
      if (i > 0) out[decl.slice(0, i).trim()] = decl.slice(i + 1).trim();
    }
  }
  return out;
}

/* ── issue 1: the header (viewer M2: one row; the request details open over the diagram) ── */

test('About holds every authored word of the request and coverage; the header row holds none of it', async () => {
  const ctx = await mount(doc());
  // Viewer M2: a new revision opens on About, in the rail; the details panel that opened over the
  // diagram from the header is gone.
  assert.equal(ctx.document.querySelector('.mlv-workflow__details'), null);
  const about = ctx.document.querySelector('.mlv-rail__panel:not([hidden]) .mlv-about');
  assert.ok(about, 'the About tab is shown');
  const chip = ctx.document.querySelector('.mlv-header__prov');
  assert.equal(chip.getAttribute('aria-haspopup'), null, 'the chip switches a tab; it opens no popup');
  assert.equal(chip.getAttribute('aria-expanded'), null);
  // The header row carries the title (whole on hover) and host · revision, nothing else of the request.
  const title = ctx.document.querySelector('.mlv-header__title');
  assert.equal(title.tagName, 'H1');
  assert.equal(title.textContent, 'Layout fixture');
  assert.equal(title.title, 'Layout fixture', 'the whole title is on hover');
  assert.equal(chip.textContent, 'claude-code · r1');
  assert.doesNotMatch(ctx.document.querySelector('.mlv-header').textContent, /How does the loop update state/);
  // About, in order: Asked, What the model traced, Coverage, Scope, Run configuration, Cited files, Provenance.
  assert.deepEqual(Array.from(about.querySelectorAll('[data-about]'), (section) => section.getAttribute('data-about')),
    ['asked', 'traced', 'coverage', 'scope', 'config', 'files', 'provenance']);
  assert.equal(about.querySelector('.mlv-about__question').textContent, 'How does the loop update state?');
  assert.equal(about.querySelector('.mlv-about__more'), null, 'a short question is not clamped');
  assert.equal(about.querySelector('[data-about="traced"]').textContent, 'What the model tracedCore path');
  assert.match(about.querySelector('[data-about="coverage"]').textContent, /Partial: the assistant lists work that remains within the scope\./);
  assert.match(about.querySelector('[data-about="coverage"]').textContent, /1 coverage limitation \(apply to every claim\)Launcher not read\./);
  assert.match(about.querySelector('[data-about="scope"]').textContent, /src\/Entrypoints: src\/train\.py/);
  assert.equal(about.querySelector('[data-about="config"] .mlv-about__config').textContent, 'defaults');
  assert.deepEqual(Array.from(about.querySelectorAll('.mlv-about__file'), (li) => li.getAttribute('data-file')), ['src/train.py']);
  assert.equal(about.querySelector('.mlv-about__file .mlv-quote__fresh').textContent, 'not checked', 'no hashes were published');
  assert.equal(about.querySelector('[data-about="provenance"] .mlv-about__meta').textContent,
    'claude-code · fixture-model · revision r1 · published without source hashes');
  assert.equal(about.querySelector('.mlv-about__trust').textContent, 'Model-authored; MLView checks citations, not the interpretation.');
  ctx.app.destroy();
});

test('the provenance chip, the coverage item and the ... menu open About; a keyboard activation moves the focus into it', async () => {
  const ctx = await mount(doc());
  const shown = () => ctx.app.getState().railTab;
  const panel = () => ctx.document.querySelector('.mlv-rail__panel:not([hidden])');
  const chip = () => ctx.document.querySelector('.mlv-header__prov');
  ctx.app.setRailTab('issues');
  // A pointer click (detail 1) switches the tab and leaves the focus where it was.
  chip().focus();
  chip().dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true, detail: 1 }));
  assert.equal(shown(), 'about');
  assert.equal(ctx.document.activeElement, chip(), 'a pointer click does not move the focus');
  assert.match(ctx.document.querySelector('[aria-live="polite"]').textContent, /About this revision shown/);
  // A keyboard activation (Enter or Space: a click with no detail) moves the focus into About.
  ctx.app.setRailTab('issues');
  chip().click();
  assert.equal(shown(), 'about');
  assert.equal(ctx.document.activeElement, panel(), 'the focus moves into the About panel');
  // The status bar's coverage item is the other way in.
  ctx.app.setRailTab('outline');
  const coverage = ctx.document.querySelector('.mlv-status__coverage');
  assert.equal(coverage.textContent, 'Coverage: partial · 1 limitation');
  assert.equal(coverage.getAttribute('aria-haspopup'), null);
  coverage.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true, detail: 1 }));
  assert.equal(shown(), 'about');
  // A rail the reader hid opens for it.
  ctx.app.toggleRail();
  assert.equal(ctx.document.querySelector('.mlv-rail').hidden, true);
  coverage.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true, detail: 1 }));
  assert.equal(ctx.document.querySelector('.mlv-rail').hidden, false);
  // A re-posted revision keeps the reader's tab; a new revision opens on About again.
  ctx.app.setRailTab('outline');
  ctx.bridge.send({ v: 1, type: 'workflow', document: doc() });
  assert.equal(shown(), 'outline', 'the same revision keeps the tab');
  ctx.bridge.send({ v: 1, type: 'workflow', document: doc({ revision: { id: 'r2', parent: 'r1' } }) });
  assert.equal(shown(), 'about', 'a new revision opens on About');
  assert.match(panel().querySelector('[data-about="provenance"]').textContent, /revision r2 \(after r1\)/);
  ctx.app.destroy();
});

test('a contract-maximum document keeps the header to its one row with every word in the DOM', async () => {
  const max = contractMaxHeader();
  const ctx = await mount(max);
  const header = ctx.document.querySelector('.mlv-header');
  const panel = ctx.document.querySelector('.mlv-about');
  assert.equal(header.querySelector('.mlv-header__title').title, max.title);
  assert.equal(header.querySelector('.mlv-header__title').textContent, max.title, 'the CSS ellipsis cuts it, not the DOM');
  assert.match(header.querySelector('.mlv-header__prov').title, new RegExp('by claude-code \\(' + 'M'.repeat(200) + '\\)'));
  // About holds every word: the question is clamped with Show all, the limitations listed once.
  const question = panel.querySelector('.mlv-about__question');
  assert.equal(question.textContent.length, 4000);
  assert.equal(question.getAttribute('data-clamped'), 'true');
  const more = panel.querySelector('.mlv-about__more');
  assert.equal(more.textContent, 'Show all');
  assert.equal(more.getAttribute('aria-controls'), question.id);
  more.click();
  assert.equal(question.getAttribute('data-clamped'), 'false');
  assert.equal(more.textContent, 'Show less');
  assert.equal(more.getAttribute('aria-expanded'), 'true');
  assert.equal(panel.querySelectorAll('.mlv-about__limitations li').length, 500);
  assert.equal(panel.querySelectorAll('[data-about="config"] .mlv-about__kv').length, 0, 'plain words, no k=v tokens');
  assert.equal(ctx.document.querySelector('.mlv-status__coverage').textContent, 'Coverage: partial · 500 limitations');
  // The header holds no request text and no phase chip row, whatever the document's size.
  assert.doesNotMatch(header.textContent, /question0|scope0|summary0|lim0w|phase0w/);
  assert.equal(ctx.document.querySelector('.mlv-filterrow, .mlv-chiprow'), null);
  ctx.app.destroy();
});

test('the shipped CSS keeps the header to one row, stacks the bottom sheet under the canvas, and gives the canvas a floor', async () => {
  const css = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.css'), 'utf8');
  const header = declarationsFor(css, '.mlv-header');
  assert.equal(header.flex, 'none', 'the header never grows or shrinks');
  assert.equal(header.height, 'var(--mlv-header-h)');
  assert.equal(header['white-space'], 'nowrap', 'one row: nothing wraps');
  assert.equal(declarationsFor(css, '.mlv-header__bar')['flex-wrap'] || 'nowrap', 'nowrap');
  assert.match(css, /--mlv-header-h:\s*36px/, 'about 36 px');
  assert.match(css, /--mlv-status-h:\s*22px/, 'and the status bar about 22 px');
  const title = declarationsFor(css, '.mlv-header__title');
  assert.equal(title['text-overflow'], 'ellipsis', 'the title gives up its width first, with an ellipsis');
  assert.equal(title['white-space'], 'nowrap');
  assert.equal(title.overflow, 'hidden');
  const section = declarationsFor(css, '.mlv-workflow');
  assert.equal(section.height, '0', 'the Refine… anchor adds no height under the header');
  assert.equal(css.includes('.mlv-workflow__details'), false, 'the details panel is gone (About replaced it)');
  assert.equal(css.includes('.mlv-scrim'), false, 'no drawer, so no scrim');
  // The canvas floor (issue 1), unchanged: the body under the header keeps at least this much.
  const body = declarationsFor(css, '.mlv-root--workflow>.mlv-body');
  assert.equal(body.flex, '1 1 0', 'basis 0: the body takes the free space');
  assert.match(body['min-height'] || '', /^min\(320px,\s*50vh\)$/, 'the body keeps at least 320 px (half a short panel)');
  // Viewer M2: the bottom sheet shares that body with the canvas. Stacked under it (never over
  // it), at most what leaves the canvas min(240px, 45%), 32 px when collapsed.
  assert.equal(declarationsFor(css, '.mlv-body[data-rail=sheet]')['flex-direction'], 'column');
  const sheet = declarationsFor(css, '.mlv-rail[data-mode=sheet]');
  assert.match(sheet.flex || '', /^0 0 calc\(var\(--mlv-sheet-fraction,\s*\.47\)\s*\*\s*100%\)$/);
  assert.equal(sheet.position, undefined, 'in the flow, not an overlay');
  assert.match(sheet['max-height'] || '', /^calc\(100% - min\(240px,\s*45%\)\)$/, 'the canvas keeps min(240px, 45%) above an open sheet');
  assert.equal(declarationsFor(css, '.mlv-rail[data-mode=sheet][data-expanded=false]')['flex-basis'], '32px');
  // The 900 px drawer media rule is gone: nothing positions the rail over the canvas.
  assert.doesNotMatch(css, /@media[^{]*max-width:\s*900px[^{]*\{[^}]*\.mlv-rail\{[^}]*position:\s*absolute/);
  const banner = declarationsFor(css, '#mlview-authored-error');
  assert.match(banner['max-height'] || '', /vh$/);
  assert.equal(declarationsFor(css, '.mlv-minimap.is-short').display, 'none');
});

/* ── issue 6: rail, minimap, refit, reveal, default collapse ─────────── */

test('below 1260 px the rail is a bottom sheet: its tab strip until a selection or the reader opens it', async () => {
  let width = 541;
  const ctx = await mount(doc(), { rootWidth: () => width });
  const rail = ctx.document.querySelector('.mlv-rail');
  const body = ctx.document.querySelector('.mlv-body');
  const panels = () => Array.from(rail.querySelectorAll('.mlv-rail__panel')).filter((panel) => !panel.hidden).length;
  assert.equal(rail.hidden, false, 'the tab strip is always there');
  assert.equal(rail.getAttribute('data-mode'), 'sheet');
  assert.equal(body.getAttribute('data-rail'), 'sheet', 'the body stacks the sheet under the canvas');
  assert.equal(rail.getAttribute('data-expanded'), 'false', 'collapsed: a 32 px tab strip');
  assert.equal(panels(), 0);
  assert.equal(rail.querySelector('.mlv-sr').textContent, 'Bottom panel', 'a labelled region');
  assert.equal(rail.getAttribute('role'), null, 'not a dialog');
  width = 1382;
  resize(ctx);
  assert.equal(rail.getAttribute('data-mode'), 'docked', 'a panel wide enough docks it');
  assert.equal(rail.hidden, false);
  assert.equal(panels(), 1);
  assert.equal(rail.style.width, '360px', 'the docked width');
  width = 1259;
  resize(ctx);
  assert.equal(rail.getAttribute('data-mode'), 'sheet', '1259 - 360 leaves the canvas under 900 px');
  assert.equal(rail.getAttribute('data-expanded'), 'false');
  assert.equal(rail.style.width, '', 'the sheet spans the panel');
  width = 1260;
  resize(ctx);
  assert.equal(rail.getAttribute('data-mode'), 'docked', '1260 - 360 = 900: docked');
  width = 1086;
  resize(ctx);
  // Viewer M2: the rail toggle is in the ... menu (and `b` since the live fix), named for the mode.
  ctx.document.querySelector('.mlv-btn--more').click();
  const item = ctx.document.querySelector('[data-more-item="rail"]');
  assert.equal(item.querySelector('.mlv-moremenu__label').textContent, 'Bottom panel');
  assert.equal(item.getAttribute('aria-checked'), 'false');
  item.click();
  assert.equal(rail.getAttribute('data-expanded'), 'true', 'the reader opened it');
  assert.equal(panels(), 1);
  width = 541;
  resize(ctx);
  assert.equal(rail.getAttribute('data-expanded'), 'true', 'after an explicit choice the width rule no longer decides');
  ctx.app.destroy();
});

test('working in the rail keeps it: a narrower panel after following evidence opens it as the sheet', async () => {
  let width = 1382;
  const ctx = await mount(doc(), { rootWidth: () => width });
  const rail = ctx.document.querySelector('.mlv-rail');
  assert.equal(rail.hidden, false);
  rail.dispatchEvent(new ctx.window.Event('pointerdown', { bubbles: true }));
  width = 691;
  resize(ctx);
  assert.equal(rail.getAttribute('data-mode'), 'sheet');
  assert.equal(rail.getAttribute('data-expanded'), 'true', 'the split beside the source must not take the finding away');
  ctx.app.destroy();
});

test('selecting a finding opens a collapsed sheet', async () => {
  const ctx = await mount(doc(), { rootWidth: () => 541 });
  const rail = ctx.document.querySelector('.mlv-rail');
  assert.equal(rail.getAttribute('data-expanded'), 'false');
  ctx.app.focusIssue('f1');
  assert.equal(rail.getAttribute('data-expanded'), 'true');
  assert.equal(ctx.app.getState().selection.id, 'f1');
  assert.equal(ctx.app.getState().railTab, 'inspector', 'on the Selection tab');
  ctx.app.destroy();
});

test('an unmeasurable root leaves the rail open (jsdom, detached mounts)', async () => {
  const ctx = await mount(doc());
  assert.equal(ctx.document.querySelector('.mlv-rail').hidden, false);
  ctx.app.destroy();
});

test('the minimap is not drawn over a canvas under 350 px tall', async () => {
  const ctx = await mount(rendererRegressionWorkflow(48));
  const minimap = ctx.document.querySelector('.mlv-minimap');
  assert.equal(minimap.classList.contains('is-short'), false);
  sizeCanvas(ctx, { w: 900, h: 300 });
  resize(ctx);
  assert.equal(minimap.classList.contains('is-short'), true);
  sizeCanvas(ctx, { w: 900, h: 500 });
  resize(ctx);
  assert.equal(minimap.classList.contains('is-short'), false);
  ctx.app.destroy();
});

test('a large resize refits a viewport nobody moved, and never one the reader moved', async () => {
  // Viewer M2: the refit re-runs the readable view. At 541x420 phase 1 of this fixture (646x390)
  // fits at 0.763, so it is fitted; at 1382x600 it would fit at 1.4, so it opens at 0.9.
  const ctx = await mount(rendererRegressionWorkflow(48));
  sizeCanvas(ctx, { w: 541, h: 420 });
  ctx.app.view.fit();
  const narrow = ctx.app.getState().viewport.zoom;
  assert.ok(narrow >= 0.75 && narrow < 0.9, `phase 1 fitted (${narrow})`);
  sizeCanvas(ctx, { w: 541, h: 410 });
  resize(ctx);
  assert.equal(ctx.app.getState().viewport.zoom, narrow, 'a 10 px settle keeps the picture');
  sizeCanvas(ctx, { w: 1382, h: 600 });
  resize(ctx);
  const wide = ctx.app.getState().viewport.zoom;
  assert.ok(wide > narrow, `widening refits (${narrow} -> ${wide})`);
  assert.equal(wide, 0.9, 'READABLE_ZOOM');
  ctx.document.querySelector('button[aria-label="Zoom in"]').click();
  const zoomed = ctx.app.getState().viewport.zoom;
  sizeCanvas(ctx, { w: 541, h: 450 });
  resize(ctx);
  assert.equal(ctx.app.getState().viewport.zoom, zoomed, 'a reader-set zoom is never refitted');
  ctx.app.destroy();
});

test('key 0 re-runs the readable view for the canvas it has now; "Fit the whole diagram" fits the whole', async () => {
  // Viewer M2. Before, one control ("Fit to view", and key 0) re-ran the first paint, or fitted the
  // whole document once the reader had zoomed out below 50 % (HOSTS-UX-FITZOOM). Key 0 is now the
  // readable view from any zoom, and the menu item is named for the whole-document fit.
  const ctx = await mount(rendererRegressionWorkflow(48));
  const canvas = ctx.document.querySelector('.mlv-canvas');
  const press = (key) => canvas.dispatchEvent(new ctx.window.KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }));
  // Viewer M2: the whole-diagram fit is an item of the header's ... menu.
  const fitWhole = () => {
    ctx.document.querySelector('.mlv-btn--more').click();
    return ctx.document.querySelector('[data-more-item="fit"]');
  };
  assert.equal(ctx.document.querySelector('button[aria-label="Fit to view"]'), null, 'the old name is gone');
  assert.equal(ctx.document.querySelector('[data-more-item="fit"] .mlv-moremenu__label').textContent, 'Fit the whole diagram');
  sizeCanvas(ctx, { w: 400, h: 300 });
  ctx.app.view.fit();
  assert.equal(ctx.app.getState().viewport.zoom, 0.9, 'phase 1 does not fit at 0.75 here, so it opens at READABLE_ZOOM');
  for (let i = 0; i < 8; i++) ctx.document.querySelector('button[aria-label="Zoom out"]').click();
  assert.ok(ctx.app.getState().viewport.zoom < 0.5);
  press('0');
  assert.equal(ctx.app.getState().viewport.zoom, 0.9, 'key 0 from below the old floor reads again');
  sizeCanvas(ctx, { w: 1382, h: 431 });
  press('0');
  const widened = ctx.app.getState().viewport;
  assert.equal(widened.zoom, 0.9, 'after widening, key 0 re-runs the plan for the new size and never zooms out');
  assert.equal(widened.x, (1382 - ctx.app.view.frameData.width * 0.9) / 2, 'a document narrower than the canvas is centred');
  fitWhole().click();
  const whole = ctx.app.getState().viewport.zoom;
  assert.equal(whole, 0.15, 'the whole 3464 px tall fixture in a 431 px canvas fits at the zoom floor');
  press('0');
  assert.equal(ctx.app.getState().viewport.zoom, 0.9);
  ctx.app.destroy();
});

test('a finding or rail item selected below the detail threshold zooms to its target', async () => {
  const ctx = await mount(rendererRegressionWorkflow(48));
  ctx.app.view.viewport.set({ zoom: 0.2 });
  ctx.app.focusIssue('finding-a');
  assert.equal(ctx.app.getState().viewport.zoom, 0.9, 'READABLE_ZOOM');
  // Above the threshold the zoom is left alone and the target is only centred.
  ctx.app.view.viewport.set({ zoom: 0.7 });
  ctx.app.focusIssue('finding-b');
  assert.equal(ctx.app.getState().viewport.zoom, 0.7);
  // An Outline row is a rail item too.
  ctx.app.view.viewport.set({ zoom: 0.25 });
  ctx.app.setRailTab('outline');
  const row = ctx.document.querySelector('[data-outline-id="node-12"] .mlv-outline__row') || ctx.document.querySelector('[data-outline-id] .mlv-outline__row');
  row.click();
  assert.ok(ctx.app.getState().viewport.zoom >= 0.62, 'the outline selection is readable');
  ctx.app.destroy();
});

/* ── Campaign 3 review VL-1, viewer M2: reveal above the bottom sheet; self-loops ── */

/**
 * jsdom lays nothing out, so the canvas box is given: the body's height, less the sheet's 32 px
 * strip when collapsed or its share (47 %) when open, as the shipped CSS stacks them.
 */
function sizeCanvasOverSheet(ctx, w, bodyH) {
  const rail = ctx.document.querySelector('.mlv-rail');
  const canvas = ctx.document.querySelector('.mlv-canvas');
  canvas.getBoundingClientRect = () => {
    const sheet = rail.getAttribute('data-mode') !== 'sheet' ? 0 : rail.getAttribute('data-expanded') === 'true' ? Math.round(bodyH * 0.47) : 32;
    const h = bodyH - sheet;
    return { x: 0, y: 0, top: 0, left: 0, width: w, height: h, right: w, bottom: h };
  };
  return () => canvas.getBoundingClientRect();
}

/** The target card's box on screen, from the viewport and the laid-out frame. */
function screenBox(ctx, id) {
  const vp = ctx.app.getState().viewport;
  const box = ctx.app.view.frameData.boxes.get(id);
  return { left: box.x * vp.zoom + vp.x, right: (box.x + box.w) * vp.zoom + vp.x, top: box.y * vp.zoom + vp.y, bottom: (box.y + box.h) * vp.zoom + vp.y };
}

const inside = (box, area) => box.left >= 0 && box.top >= 0 && box.right <= area.width && box.bottom <= area.height;

test('at 541 px a finding opens the sheet and frames every cited card in the canvas above it', async () => {
  // MEASURED live before viewer M2: at 541 px the drawer covered x 181-541 of the canvas and the
  // target sat at x 173-368, 4 % visible.
  const ctx = await mount(rendererRegressionWorkflow(48), { rootWidth: () => 541 });
  const area = sizeCanvasOverSheet(ctx, 541, 740);
  ctx.app.view.viewport.set({ zoom: 0.2 });
  ctx.app.focusIssue('finding-a');
  assert.equal(ctx.document.querySelector('.mlv-rail').getAttribute('data-expanded'), 'true', 'the finding opened the sheet');
  assert.equal(area().height, 740 - 348, 'the canvas is the part above the sheet');
  const issue = ctx.app.index.issueById.get('finding-a');
  for (const id of issue.nodeIds) {
    const card = screenBox(ctx, ctx.app.index.visibleRepresentative(id, new Set()) || id);
    assert.ok(inside(card, area()), `${id} (${card.left.toFixed(0)}-${card.right.toFixed(0)}, ${card.top.toFixed(0)}-${card.bottom.toFixed(0)}) is above the sheet`);
  }
  assert.ok(ctx.app.getState().viewport.zoom >= 0.45, 'and readable');
  // Escape on the canvas collapses the sheet; the selection stays.
  const canvas = ctx.document.querySelector('.mlv-canvas');
  canvas.dispatchEvent(new ctx.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
  assert.equal(ctx.document.querySelector('.mlv-rail').getAttribute('data-expanded'), 'false');
  assert.equal(ctx.app.getState().selection.id, 'finding-a', 'the selection stays');
  ctx.app.destroy();
});

test('opening and collapsing the sheet never refits; the selected card stays visible above it', async () => {
  const ctx = await mount(rendererRegressionWorkflow(48), { rootWidth: () => 900 });
  const area = sizeCanvasOverSheet(ctx, 900, 742);
  ctx.app.view.fit();
  const fitted = ctx.app.getState().viewport;
  // A card low in the canvas: where the open sheet will be.
  const id = 'node-8';
  const box = ctx.app.view.frameData.boxes.get(id);
  ctx.app.view.viewport.set({ x: 450 - (box.x + box.w / 2) * fitted.zoom, y: 680 - (box.y + box.h) * fitted.zoom });
  const zoom = ctx.app.getState().viewport.zoom;
  const card = ctx.document.querySelector(`.mlv-node[data-node-id="${id}"]`);
  card.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true }));
  assert.equal(ctx.app.getState().selection.id, id);
  assert.equal(ctx.document.querySelector('.mlv-rail').getAttribute('data-expanded'), 'true', 'a click opens the sheet');
  assert.equal(ctx.app.getState().viewport.zoom, zoom, 'no refit: the zoom is kept');
  assert.ok(inside(screenBox(ctx, id), area()), 'the card moved up into the canvas left above the sheet');
  // Two columns in a 900 px sheet: the claim on the left, the evidence on the right.
  const pane = ctx.document.querySelector('.mlv-rail__panel:not([hidden]) .mlv-sel');
  assert.equal(pane.getAttribute('data-columns'), '2');
  assert.ok(pane.querySelector('.mlv-sel__col--claim .mlv-insp__title'));
  assert.ok(pane.querySelector('.mlv-sel__col--evidence [data-section="quotes"]'));
  assert.ok(pane.querySelector('.mlv-sel__col--evidence .mlv-insp__actions'));
  // Collapsing keeps the picture too.
  const before = ctx.app.getState().viewport;
  ctx.app.collapseSheet(false);
  assert.deepEqual(ctx.app.getState().viewport, before, 'collapsing moves nothing');
  ctx.app.destroy();
});

test('docked, the whole canvas is the visible area', async () => {
  const ctx = await mount(rendererRegressionWorkflow(48), { rootWidth: () => 1382 });
  sizeCanvas(ctx, { w: 1022, h: 600 });
  assert.equal(ctx.document.querySelector('.mlv-rail').getAttribute('data-mode'), 'docked');
  const area = ctx.app.view.viewport.visibleArea();
  assert.deepEqual([area.w, area.h], [1022, 600]);
  ctx.app.destroy();
});

test('a selected target stays in view when a split turns the docked rail into the sheet under it', async () => {
  // MEASURED live before viewer M2: finding selected at 1382 px (rail docked), evidence followed,
  // panel 691 px: the chosen rail became the drawer at x 331-691 and the target was 0 % visible.
  let width = 1382;
  const ctx = await mount(rendererRegressionWorkflow(48), { rootWidth: () => width });
  let canvasW = 1022;
  const rail = ctx.document.querySelector('.mlv-rail');
  const canvas = ctx.document.querySelector('.mlv-canvas');
  canvas.getBoundingClientRect = () => {
    const h = rail.getAttribute('data-mode') === 'sheet' ? (rail.getAttribute('data-expanded') === 'true' ? 600 - 282 : 568) : 600;
    return { x: 0, y: 0, top: 0, left: 0, width: canvasW, height: h, right: canvasW, bottom: h };
  };
  ctx.app.focusIssue('finding-b');
  const primary = ctx.app.index.issueById.get('finding-b').nodeIds[0];
  // Put the target low on the docked canvas, where the sheet will be.
  const box = ctx.app.view.frameData.boxes.get(primary);
  const zoom = ctx.app.getState().viewport.zoom;
  ctx.app.view.viewport.set({ x: 500 - (box.x + box.w) * zoom, y: 560 - (box.y + box.h) * zoom });
  const before = screenBox(ctx, primary);
  assert.ok(before.top >= 318 && before.bottom <= 600, 'in view on the docked canvas, under where the sheet will be');
  width = 691;
  canvasW = 691;
  resize(ctx);
  assert.equal(rail.getAttribute('data-mode'), 'sheet');
  assert.equal(rail.getAttribute('data-expanded'), 'true', 'the finding the reader chose stays open');
  const after = screenBox(ctx, primary);
  assert.ok(inside(after, canvas.getBoundingClientRect()), `re-centred above the sheet (${after.top.toFixed(0)}-${after.bottom.toFixed(0)})`);
  assert.equal(ctx.app.getState().viewport.zoom, zoom, 'at the same zoom');
  // A target the reader had already moved out of view is left where it is.
  ctx.app.view.viewport.set({ x: -5000 });
  const moved = ctx.app.getState().viewport.x;
  width = 600;
  canvasW = 600;
  resize(ctx);
  assert.equal(ctx.app.getState().viewport.x, moved);
  ctx.app.destroy();
});

test('an authored self-edge is drawn as a loop on its card; one hidden in a folded group is not', async () => {
  // Shakedown issue 11 and its review: the contract accepts a self-edge (kind "loop" draws no
  // helper warning), but the canvas skipped every edge whose ends were the same node.
  const document = doc({
    nodes: [
      { id: 'a', label: 'Read the records', phase: 'prep', kind: 'data', basis: 'observed', evidence: ['e1'] },
      { id: 'g', label: 'Epochs', phase: 'loop', kind: 'loop', basis: 'observed', evidence: [] },
      { id: 'b', label: 'Update weights', phase: 'loop', parent: 'g', kind: 'optimizer', basis: 'inferred', evidence: ['e1'] },
    ],
    edges: [
      { id: 'ab', source: 'a', target: 'b', label: 'batches', kind: 'data', basis: 'observed', evidence: ['e1'] },
      { id: 'bb', source: 'b', target: 'b', label: 'next batch', kind: 'loop', basis: 'observed', evidence: ['e1'] },
      { id: 'bb2', source: 'b', target: 'b', label: 'retry', kind: 'control', basis: 'observed', evidence: ['e1'] },
    ],
  });
  const ctx = await mount(document);
  const drawn = () => [...ctx.document.querySelectorAll('.mlv-edge[data-edge-id]')].map((e) => e.getAttribute('data-edge-id')).sort();
  assert.deepEqual(drawn(), ['ab', 'bb', 'bb2']);
  const loop = ctx.document.querySelector('.mlv-edge[data-edge-id="bb"] .mlv-edge__path');
  assert.match(loop.getAttribute('d'), /^M /, 'a real path');
  assert.equal(ctx.document.querySelector('.mlv-edge[data-edge-id="bb"]').getAttribute('data-edge-kind'), 'loop');
  const box = ctx.app.view.frameData.boxes.get('b');
  const [x0, y0] = loop.getAttribute('d').slice(2).split(' ').map(Number);
  assert.equal(x0, box.x + box.w, 'it leaves the card\'s right face');
  const other = ctx.document.querySelector('.mlv-edge[data-edge-id="bb2"] .mlv-edge__path').getAttribute('d');
  assert.notEqual(other, loop.getAttribute('d'), 'a second self-edge nests outside the first');
  ctx.app.view.toggleCollapse('g');
  assert.deepEqual(drawn(), ['ab'], 'folded into its group, the loop is inside the card it folded into');
  ctx.app.destroy();
});

test('an edge-only finding reveals its connection', async () => {
  const document = doc({ findings: [{ id: 'fe', title: 'Edge finding', message: 'm', severity: 'low', nodeIds: [], edgeIds: ['ab'], basis: 'inferred', evidence: ['e1'] }] });
  const ctx = await mount(document);
  ctx.app.view.viewport.set({ zoom: 0.2 });
  ctx.app.focusIssue('fe');
  assert.ok(ctx.app.getState().viewport.zoom >= 0.62);
  ctx.app.destroy();
});

test('an authored group that holds a finding target is never folded by the size rule', async () => {
  const phases = [{ id: 'p', label: 'P' }];
  const nodes = [
    { id: 'loop', label: 'Main loop', phase: 'p', kind: 'group', basis: 'observed', evidence: [] },
    { id: 'side', label: 'Side work', phase: 'p', kind: 'group', basis: 'observed', evidence: [] },
  ];
  for (let i = 0; i < 14; i++) nodes.push({ id: `l${i}`, label: `Loop step ${i}`, phase: 'p', parent: 'loop', basis: 'observed', evidence: ['e1'] });
  for (let i = 0; i < 14; i++) nodes.push({ id: `s${i}`, label: `Side step ${i}`, phase: 'p', parent: 'side', basis: 'observed', evidence: ['e1'] });
  const document = doc({ phases, nodes, edges: [], findings: [{ id: 'f', title: 'T', message: 'm', severity: 'high', nodeIds: ['l7'], edgeIds: [], basis: 'inferred', evidence: ['e1'] }] });
  const ctx = await mount(document);
  assert.deepEqual([...ctx.app.getState().collapsed], ['side'], 'only the group without a finding target folds');
  assert.ok(ctx.document.querySelector('[data-node-id="l7"]'), 'the finding target is drawn at first paint');
  ctx.app.destroy();
});

/* ── issue 14: titles and glyphs ──────────────────────────────────────── */

test('an authored title is truncated once: whole label in the DOM, wrapped to the reserved lines', async () => {
  const label = 'Alpha beta gamma delta epsilon zeta eta theta iota kappa';
  const document = doc();
  document.nodes[1].label = label;
  const ctx = await mount(document);
  const card = ctx.document.querySelector('[data-node-id="b"]');
  const title = card.querySelector('.mlv-node__title');
  assert.equal(title.textContent, label, 'no middle ellipsis in the DOM');
  assert.ok(title.classList.contains('mlv-node__title--wrap'));
  assert.equal(title.getAttribute('data-lines'), '3');
  const short = ctx.document.querySelector('[data-node-id="a"]');
  assert.equal(short.querySelector('.mlv-node__title').getAttribute('data-lines'), '1');
  const css = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.css'), 'utf8');
  for (const n of ['2', '3']) {
    assert.equal(declarationsFor(css, `.mlv-node__title--wrap[data-lines="${n}"]`)['-webkit-line-clamp'], n, 'the clamp matches the reserved lines');
  }
  // Viewer M2: the compact level's clamp (two lines, three for a three-line title, counter-scaled
  // to the card's box) moved to readable-view.test.mjs, which reads screen and print rules apart.

  assert.equal(parseFloat(card.style.height) - parseFloat(short.style.height), 36, 'two extra 18 px title lines are reserved');
  // The SVG export draws the same lines.
  ctx.document.querySelector('.mlv-btn--more').click();
  ctx.document.querySelector('[data-export-action="svg"]').click();
  const frame = ctx.bridge.posted.findLast((item) => item.type === 'exportFile' && item.kind === 'svg');
  const svg = Buffer.from(frame.base64, 'base64').toString('utf8');
  for (const line of ['Alpha beta gamma delta', 'epsilon zeta eta theta', 'iota kappa']) assert.match(svg, new RegExp('>' + line + '<'));
  ctx.app.destroy();
});

test('authored kinds draw mapped glyphs, never the question mark; uncertainty follows basis unresolved', async () => {
  const kinds = { k1: 'preprocessing', k2: 'transform', k3: 'Configuration', k4: 'config', k5: 'eval', k6: 'evaluation', k7: 'objective', k8: 'loss', k9: 'data-source', k10: 'dataset', k11: 'something-new', k12: 'operation', k13: 'checkpoint', k14: 'scheduler', k15: 'state_update', k16: 'state' };
  const nodes = Object.entries(kinds).map(([id, kind]) => ({ id, label: id, phase: 'prep', kind, basis: id === 'k11' ? 'unresolved' : 'observed', evidence: ['e1'] }));
  nodes.push({ id: 'g', label: 'Group', phase: 'loop', kind: 'group', basis: 'observed', evidence: [] });
  nodes.push({ id: 'gc', label: 'Child', phase: 'loop', parent: 'g', basis: 'observed', evidence: ['e1'] });
  const ctx = await mount(doc({ nodes, edges: [], findings: [] }));
  const glyph = (id) => ctx.document.querySelector(`[data-node-id="${id}"] .mlv-icon path`).getAttribute('d');
  for (const id of [...Object.keys(kinds), 'g', 'gc']) assert.ok(!glyph(id).startsWith(QUESTION_GLYPH_PREFIX), `${id} (${kinds[id] || 'no kind'}) must not draw the question mark`);
  assert.equal(glyph('k1'), glyph('k2'), 'preprocessing draws the transform glyph');
  assert.equal(glyph('k3'), glyph('k4'), 'Configuration is config');
  assert.equal(glyph('k5'), glyph('k6'), 'eval is evaluation');
  assert.equal(glyph('k7'), glyph('k8'), 'objective is loss');
  assert.equal(glyph('k9'), glyph('k10'), 'data-source is a dataset');
  assert.equal(glyph('k15'), glyph('k16'), 'state_update is state');
  assert.notEqual(glyph('k13'), glyph('k14'), 'checkpoint and scheduler keep their own glyphs');
  assert.equal(glyph('k11'), glyph('gc'), 'an unfamiliar or absent kind draws the same neutral glyph');
  assert.notEqual(glyph('k11'), glyph('k12'));
  assert.equal(ctx.document.querySelector('[data-node-id="k11"]').getAttribute('data-basis'), 'unresolved');
  assert.equal(ctx.document.querySelector('[data-node-id="k12"]').getAttribute('data-basis'), 'observed');
  // Viewer M2: the uncertainty treatment is a dotted outline plus a "? unresolved" tag on the
  // unresolved card only; the observed card carries no basis mark at all.
  assert.equal(ctx.document.querySelector('[data-node-id="k11"] .mlv-basis-tag').textContent, '? unresolved');
  assert.equal(ctx.document.querySelector('[data-node-id="k12"] .mlv-basis-tag'), null);
  const css = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.css'), 'utf8');
  assert.match(declarationsFor(css, '.mlv-node[data-basis=unresolved]:after')['border-style'] || '', /dotted/);
  assert.match(declarationsFor(css, '.mlv-node[data-basis=inferred]:after').border || '', /dashed/);
  ctx.app.destroy();
});

/* ── issue 9: edge kinds ──────────────────────────────────────────────── */

test('edge kind synonyms are drawn as the styled kinds; other kinds keep their authored text', async () => {
  const spellings = { e1: 'dataflow', e2: 'Data flow', e3: 'flow', e4: 'control-flow', e5: 'conditional-call', e6: 'state-update', e7: 'gradient', e8: 'ownership', e9: 'configuration flow', e10: 'loop', e11: 'output', e12: 'construction', e13: undefined, e14: 'call' };
  const ids = Object.keys(spellings);
  const nodes = ids.flatMap((id) => [
    { id: id + 's', label: id + ' source', phase: 'prep', basis: 'observed', evidence: ['e1'] },
    { id: id + 't', label: id + ' target', phase: 'loop', basis: 'observed', evidence: ['e1'] },
  ]);
  const edges = ids.map((id) => ({ id, source: id + 's', target: id + 't', label: id + ' label', basis: 'observed', evidence: ['e1'], ...(spellings[id] ? { kind: spellings[id] } : {}) }));
  const ctx = await mount(doc({ nodes, edges, findings: [] }));
  const expected = { e1: 'data', e2: 'data', e3: 'data', e4: 'control', e5: 'control', e6: 'state', e7: 'state', e8: 'state', e9: 'config', e10: 'loop', e11: 'output', e12: 'unknown', e13: 'unknown', e14: 'call' };
  for (const id of ids) {
    const g = ctx.document.querySelector(`.mlv-edge[data-edge-id="${id}"]`);
    assert.ok(g.classList.contains('mlv-edge--' + expected[id]), `${id} (${spellings[id]}) is drawn as ${expected[id]}`);
  }
  assert.equal(ctx.document.querySelector('.mlv-edge[data-edge-id="e12"]').getAttribute('data-edge-kind'), 'construction');
  assert.doesNotMatch(ctx.document.querySelector('.mlv-edge[data-edge-id="e13"] .mlv-edge__hit').getAttribute('aria-label'), /unknown/);
  // The inspector names what the author wrote.
  const chip = (id) => {
    ctx.app.select({ kind: 'edge', id }, { tab: 'inspector' });
    return ctx.document.querySelector('.mlv-insp__edgekind').textContent;
  };
  assert.equal(chip('e1'), 'data · authored as dataflow');
  assert.equal(chip('e12'), 'construction');
  assert.equal(chip('e13'), 'kind not specified');
  assert.equal(chip('e14'), 'call');
  // Viewer M2: the line no longer shows the kind (its dash shows the basis), so the legend has no
  // per-kind strokes. It lists the kinds this diagram uses, in words, with how many of each.
  const legend = ctx.document.querySelector('.mlv-legend');
  for (const kind of ['state', 'loop', 'output', 'unknown']) assert.equal(legend.querySelector(`[data-legend-row="edge:${kind}"]`), null, kind + ' has no stroke row');
  const kinds = legend.querySelector('[data-legend-row="edge:kinds"]');
  assert.match(kinds.nextElementSibling.textContent, /Connections in this diagram, by kind: /);
  assert.match(kinds.nextElementSibling.textContent, /construction 1/);
  assert.match(kinds.nextElementSibling.textContent, /1 connection has no kind\./);
  // One filled arrowhead for every connection.
  assert.equal(ctx.document.querySelectorAll('marker').length, 1);
  assert.ok(ctx.document.querySelector('#mlv-arrow'));
  for (const id of ids) assert.equal(ctx.document.querySelector(`.mlv-edge[data-edge-id="${id}"] .mlv-edge__path`).getAttribute('marker-end'), 'url(#mlv-arrow)');
  const css = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.css'), 'utf8');
  assert.match(declarationsFor(css, '.mlv-arrow').fill || '', /var\(--mlv-edge\)/);
  ctx.app.destroy();
});

