/**
 * VIEW-07 — export the diagram.
 *
 * The item ships a SECOND RENDERER, and its mandatory mitigation is that the
 * two cannot drift: `render/plan.ts` decides what is drawn, `render/scene.ts`
 * turns that into DOM and `export/svg.ts` turns the same object into SVG. The
 * gate that makes it stick is the first test below — one `<g data-node-id>` per
 * drawn box, one `<path data-edge-id>` per routed edge, and every `d` byte-
 * identical to the route the layout produced.
 *
 * Everything else here is the promise the export makes to whoever opens the
 * file: it is well-formed XML, it references NOTHING (no `url(`, no
 * `foreignObject`, no webfont, no `http` outside the namespace declaration), it
 * carries the stage colours as literals, and its regions mean what they say.
 *
 * The demo figures — 54 cards, 51 edges — are asserted against
 * `.mlview/graph.json` when `scripts/e2e` has produced it, and derived from the
 * frozen `contracts/graph.sample.json` always, so a clean checkout still gates.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile, stat } from 'node:fs/promises';
import { join } from 'node:path';
import { loadBundle, readSample, REPO_ROOT, DIST_CSS_DEV } from './helpers.mjs';

const sample = await readSample();
const devCss = await readFile(DIST_CSS_DEV, 'utf8');

const DEMO_PATH = join(REPO_ROOT, '.mlview', 'graph.json');
const demo = await readJson(DEMO_PATH);

async function readJson(path) {
  try {
    await stat(path);
    return JSON.parse(await readFile(path, 'utf8'));
  } catch (_e) {
    return null;
  }
}

let shared = null;
async function bundle() {
  if (!shared) shared = await loadBundle();
  return shared;
}

async function mount(graph = sample, opts = {}) {
  const ctx = await loadBundle();
  const posted = [];
  const bridge = {
    host: opts.host || 'vscode',
    theme: 'light',
    capabilities: { canOpenSource: true, canReanalyze: true, canExport: true, canAskAssistant: false },
    post: (m) => posted.push(m),
    onMessage: () => () => undefined,
    saveState: () => undefined,
    loadState: () => null,
  };
  const root = ctx.document.getElementById('mlview-root');
  if (opts.attrScope) root.setAttribute('data-mlview-scope', opts.attrScope);
  const app = ctx.MLView.mount(root, graph, bridge);
  return { ...ctx, app, posted, root };
}

const click = (ctx, el) => el.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true }));
const key = (ctx, el, k) => el.dispatchEvent(new ctx.window.KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true }));

/** Every `<g …>` that carries a `data-node-id`, and its id. */
function nodeGroups(svg) {
  const out = [];
  const re = /<g\b([^>]*)>/g;
  let m;
  while ((m = re.exec(svg)) !== null) {
    const id = /\bdata-node-id="([^"]*)"/.exec(m[1]);
    if (id) out.push(id[1]);
  }
  return out;
}

/** Every `<path …>` that carries a `data-edge-id`, with its id and its `d`. */
function edgePaths(svg) {
  const out = [];
  const re = /<path\b([^>]*)\/>/g;
  let m;
  while ((m = re.exec(svg)) !== null) {
    const id = /\bdata-edge-id="([^"]*)"/.exec(m[1]);
    if (!id) continue;
    const d = /\bd="([^"]*)"/.exec(m[1]);
    out.push({ id: id[1], d: d ? d[1] : '' });
  }
  return out;
}

const unescapeXml = (s) =>
  s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&amp;/g, '&');

/* ── the mandated gate ─────────────────────────────────────────────────── */

async function assertOneToOne(graph, label) {
  const ctx = await bundle();
  const layout = ctx.MLView.__internal.layout(graph, []);
  const result = ctx.MLView.__internal.exportDiagram.build(graph, { region: 'diagram' });

  const groups = nodeGroups(result.svg);
  const boxIds = layout.nodes.map((n) => n.id);
  assert.equal(
    groups.length,
    boxIds.length,
    label + ': ' + groups.length + ' <g data-node-id> for ' + boxIds.length + ' drawn boxes',
  );
  // `.join` rather than deepEqual: `layout` comes out of the jsdom realm, and a
  // cross-realm Array fails deepStrictEqual on its prototype alone.
  assert.equal(
    groups.slice().sort().join('|'),
    Array.from(boxIds).sort().join('|'),
    label + ': the SAME boxes, not merely as many',
  );
  assert.equal(new Set(groups).size, groups.length, label + ': no box is drawn twice');

  const paths = edgePaths(result.svg);
  const routeIds = layout.edges.map((e) => e.id);
  assert.equal(
    paths.length,
    routeIds.length,
    label + ': ' + paths.length + ' <path data-edge-id> for ' + routeIds.length + ' routed edges',
  );
  assert.equal(paths.map((p) => p.id).join('|'), Array.from(routeIds).join('|'), label + ': in the routing order, one for one');

  // The routed geometry is carried VERBATIM — the whole point of driving both
  // renderers from one plan. A single re-derived curve here would be a drift.
  const byId = new Map(layout.edges.map((e) => [e.id, e.d]));
  for (const path of paths) {
    assert.equal(unescapeXml(path.d), byId.get(path.id), label + ': route ' + path.id + ' was re-drawn, not reused');
  }

  // Merged routes carry every document edge they stand for, so nothing is lost.
  const covered = new Set(result.edgeDocIds);
  const drawable = graph.edges.filter((e) => covered.has(e.id));
  assert.equal(covered.size, result.edgeDocIds.length, label + ': no document edge is claimed twice');
  return { layout, result, covered, drawable };
}

test('one <g> per drawn node and one path per routed edge (VIEW-07)', async () => {
  const { layout, result } = await assertOneToOne(sample, 'graph.sample.json');
  // `contracts/graph.sample.json` is the hand-authored 12-node / 14-edge
  // fixture (never regenerated, CONTRACTS 11.19) — small, but it is the one
  // document every gate in this repo can rely on existing.
  assert.equal(layout.nodes.length, sample.nodes.length, 'every node in the frozen sample is drawn');
  assert.ok(layout.nodes.length >= 12, 'the frozen sample is the 12-node fixture: ' + layout.nodes.length + ' boxes');
  assert.equal(result.nodeIds.length, layout.nodes.length);
  assert.equal(result.edgeIds.length, layout.edges.length);
});

test('the demo SVG carries all 54 cards and all 51 edges (VIEW-07)', { skip: !demo && 'run scripts/e2e first — no .mlview/graph.json' }, async () => {
  const { result, covered } = await assertOneToOne(demo, '.mlview/graph.json');
  // The re-baselined demo is 54 nodes / 51 edges (CONTRACTS 11.19 as amended by
  // ROADMAP REV-06; the brief's "52" predates the removed backwards edge).
  assert.equal(demo.nodes.length, 54, 'the demo document is the re-baselined one');
  assert.equal(demo.edges.length, 51, 'and carries 51 edges');
  assert.equal(result.nodeIds.length, 54, 'all 54 cards are in the SVG: ' + result.nodeIds.length);
  assert.equal(covered.size, 51, 'and every one of the 51 document edges: ' + covered.size);
  for (const edge of demo.edges) assert.ok(covered.has(edge.id), 'edge ' + edge.id + ' reached the SVG');
});

test('the exported SVG is well-formed XML (VIEW-07)', async () => {
  const ctx = await bundle();
  const result = ctx.MLView.__internal.exportDiagram.build(sample, { region: 'diagram' });
  const doc = new ctx.window.DOMParser().parseFromString(result.svg, 'image/svg+xml');
  assert.equal(doc.querySelector('parsererror'), null, 'a consumer has to be able to parse it');
  assert.equal(doc.documentElement.tagName.toLowerCase(), 'svg');
  assert.equal(doc.querySelectorAll('g[data-node-id]').length, result.nodeIds.length, 'counted through a real parser too');
  assert.equal(doc.querySelectorAll('path[data-edge-id]').length, result.edgeIds.length);
  assert.ok(doc.querySelector('title'), 'and it names itself');
});

/* ── no external references ────────────────────────────────────────────── */

test('the SVG references nothing outside itself (VIEW-07)', async () => {
  const ctx = await bundle();
  const svg = ctx.MLView.__internal.exportDiagram.build(sample, { region: 'diagram' }).svg;
  assert.equal(svg.indexOf('url('), -1, 'no url() — so no marker, clip-path, gradient or filter reference');
  assert.equal(svg.indexOf('foreignObject'), -1, 'no foreignObject: fragile across consumers, and the item forbids it');
  assert.equal(svg.indexOf('xlink'), -1, 'no xlink:href');
  assert.equal(svg.indexOf('<image'), -1, 'no raster embedded by reference');
  assert.equal(svg.indexOf('<use'), -1, 'no <use> reference');
  assert.equal(svg.indexOf('<script'), -1, 'an exported picture never carries script');
  assert.equal(svg.indexOf('@import'), -1);
  assert.equal(svg.indexOf('@font-face'), -1, 'a generic stack, never an embedded webfont');

  // The ONLY http in the file is the namespace declaration a standalone SVG
  // cannot legally omit. Every other occurrence would be a fetch.
  const hits = [];
  let at = svg.indexOf('http');
  while (at >= 0) {
    hits.push(svg.slice(Math.max(0, at - 8), at + 34));
    at = svg.indexOf('http', at + 1);
  }
  assert.equal(hits.length, 1, 'exactly one http occurrence: ' + hits.join(' | '));
  assert.ok(/xmlns="http/.test(hits[0]), 'and it is the xmlns declaration: ' + hits[0]);
});

test('the SVG uses a generic font stack and literal colours (VIEW-07)', async () => {
  const ctx = await bundle();
  const internal = ctx.MLView.__internal.exportDiagram;
  const svg = internal.build(sample, { region: 'diagram' }).svg;
  assert.ok(svg.indexOf('ui-sans-serif') > 0 && svg.indexOf('sans-serif') > 0, 'the sans stack ends in a generic');
  assert.ok(svg.indexOf('ui-monospace') > 0 && svg.indexOf('monospace') > 0, 'and so does the mono stack');
  assert.equal(svg.indexOf('var(--'), -1, 'no unresolved custom property survived into the file');
  assert.equal(svg.indexOf('color-mix('), -1, 'and no color-mix() a consumer would have to compute');
  assert.equal(svg.indexOf('currentColor'), -1, 'every paint is stated, none inherited from a stylesheet we did not ship');
});

test('the SVG carries the stage colours of every lane it drew (VIEW-07)', async () => {
  const ctx = await bundle();
  const internal = ctx.MLView.__internal.exportDiagram;
  const light = internal.palettes.light;
  const result = internal.build(sample, { region: 'diagram' });
  const FIELD = {
    config: 'stageConfig',
    data: 'stageData',
    preprocess: 'stagePreprocess',
    model: 'stageModel',
    objective: 'stageObjective',
    train: 'stageTrain',
    eval: 'stageEval',
    deliver: 'stageDeliver',
  };
  const drawn = new Set(result.laneIds);
  assert.ok(drawn.size >= 6, 'the sample draws most of the eight lanes: ' + result.laneIds.join(', '));
  for (const laneId of drawn) {
    const colour = light[FIELD[laneId]] || light.stageUnknown;
    assert.ok(result.svg.indexOf(colour) > 0, 'lane ' + laneId + ' put its literal ' + colour + ' in the file');
    assert.ok(result.stageColors.indexOf(colour) >= 0, 'and the result reports it');
  }
  // Dark is a different set of literals, so the export follows the theme.
  const dark = internal.build(sample, { region: 'diagram', theme: 'dark' });
  assert.ok(dark.svg.indexOf(internal.palettes.dark.stageModel) > 0, 'the dark export uses the dark model hue');
  assert.equal(dark.svg.indexOf(light.bg), -1, 'and not the light background');
});

/* ── the three regions ─────────────────────────────────────────────────── */

test('current view / whole diagram / current scope crop differently (VIEW-07)', async () => {
  const ctx = await bundle();
  const internal = ctx.MLView.__internal.exportDiagram;
  assert.equal(Array.from(internal.regions).map((r) => r.id).join(','), 'view,diagram,scope', 'all three are offered');

  const whole = internal.build(sample, { region: 'diagram' });
  const layout = ctx.MLView.__internal.layout(sample, []);
  assert.equal(whole.width, layout.width, 'the whole diagram is the whole world');
  assert.equal(whole.height, layout.height);

  const view = internal.build(sample, { region: 'view', viewRect: { x: 0, y: 0, w: 640, h: 420 } });
  assert.ok(view.width <= 640 && view.height <= 420, 'the view region is the viewport rectangle');
  assert.ok(
    view.nodeIds.length > 0 && view.nodeIds.length < whole.nodeIds.length,
    'and it really drops what is off screen: ' + view.nodeIds.length + ' of ' + whole.nodeIds.length,
  );
  for (const id of view.nodeIds) assert.ok(whole.nodeIds.indexOf(id) >= 0, 'a cropped export invents nothing');
});

test('the scope region is the CORE bounding box of a projection (VIEW-07)', async () => {
  const ctx = await bundle();
  const internal = ctx.MLView.__internal.exportDiagram;
  const api = ctx.MLView.__internal.scope;
  const graph = api.project(sample, api.parseScope('concern:evaluation', 1));
  const cores = graph.nodes.filter((n) => n.viewRole === 'core');
  assert.ok(cores.length > 0, 'the projection has a core to export');

  const scoped = internal.build(graph, { region: 'scope', scopeLabel: 'evaluation' });
  const whole = internal.build(graph, { region: 'diagram' });
  assert.ok(scoped.width <= whole.width && scoped.height <= whole.height, 'the scope never exceeds the projection');
  for (const node of cores) {
    assert.ok(scoped.nodeIds.indexOf(node.id) >= 0, 'core node ' + node.id + ' is inside the scope crop');
  }

  // With no projection there is no core, so the offer degrades to the whole
  // diagram rather than exporting an empty rectangle.
  const unscoped = internal.build(sample, { region: 'scope' });
  assert.equal(unscoped.width, whole.width === 0 ? 0 : internal.build(sample, { region: 'diagram' }).width);
});

test('the export file name says the workspace, the scope and the region (VIEW-07)', async () => {
  const ctx = await bundle();
  const internal = ctx.MLView.__internal.exportDiagram;
  const request = {
    graph: sample,
    regionKind: 'diagram',
    scopeLabel: 'evaluate()',
    plan: null,
    palette: internal.palettes.light,
    theme: 'light',
    viewRect: { x: 0, y: 0, w: 1, h: 1 },
  };
  const name = internal.fileName(request, 'svg');
  assert.ok(/^mlview-[a-z0-9._-]+-evaluate-diagram\.svg$/.test(name), name);
  assert.equal(name.indexOf('('), -1, 'nothing a shell or a filesystem would object to');
  assert.equal(internal.fileName({ ...request, scopeLabel: null, regionKind: 'view' }, 'png').slice(-8), 'view.png');
});

/* ── VIEW-03 parity: a decluttered-away label stays away ───────────────── */

test('the SVG draws exactly the labels VIEW-03 planned (VIEW-07)', async () => {
  const ctx = await bundle();
  const plan = ctx.MLView.__internal.labels.plan(sample, []);
  // `always` is VIEW-03's own word for "painted without a pointer on it", which
  // is exactly the set `styles/edge.css` reveals at full LOD.
  const expected = plan.labels.filter((l) => !l.hidden && l.always && l.text).length;
  const result = ctx.MLView.__internal.exportDiagram.build(sample, { region: 'diagram' });
  assert.equal(result.labels, expected, 'planned ' + expected + ' visible labels, drew ' + result.labels);
  assert.ok(expected > 0, 'the sample really does label its edges');
  for (const label of plan.labels) {
    if (!label.hidden) continue;
    // A hidden label must not reappear in the export — the declutter pass is a
    // property of the picture, not of the DOM renderer.
    assert.ok(
      result.svg.indexOf('>' + label.text + '</text>') < 0 || plan.labels.some((l) => !l.hidden && l.text === label.text),
      'hidden label "' + label.text + '" stayed hidden',
    );
  }
});

/* ── the palette is the stylesheet's, not a second opinion ─────────────── */

test('every export palette entry matches styles/tokens.css (VIEW-07)', async () => {
  const ctx = await bundle();
  const internal = ctx.MLView.__internal.exportDiagram;
  const css = stripComments(devCss);
  const blocks = {
    light: blockAfter(css, ':root,\n.mlv-root[data-theme="light"] {'),
    dark: blockAfter(css, 'body.vscode-dark,\n:root[data-theme="dark"],\n.mlv-root[data-theme="dark"] {'),
    hc: blockAfter(css, ':root[data-theme="hc"],\n.mlv-root[data-theme="hc"] {'),
  };
  for (const theme of ['light', 'dark', 'hc']) {
    assert.ok(blocks[theme], 'found the ' + theme + ' token block');
  }
  const declared = {
    light: declarations(blocks.light),
    dark: declarations(blocks.dark),
    hc: declarations(blocks.hc),
  };
  let checked = 0;
  for (const theme of ['light', 'dark', 'hc']) {
    const palette = internal.palettes[theme];
    for (const field of Object.keys(internal.paletteTokens)) {
      const token = internal.paletteTokens[field];
      // A theme block that does not redeclare a token inherits the light one,
      // which is exactly how EXPORT_PALETTES is built.
      const raw = resolveAlias(declared, theme, token);
      const literal = lastHex(raw);
      assert.ok(literal, theme + ' ' + token + ' has no literal fallback: ' + raw);
      assert.equal(
        palette[field].toUpperCase(),
        literal.toUpperCase(),
        theme + ' ' + token + ': palette says ' + palette[field] + ', tokens.css says ' + literal,
      );
      checked++;
    }
    for (const field of Object.keys(internal.tintTokens)) {
      const token = internal.tintTokens[field];
      const raw = resolveAlias(declared, theme, token);
      assert.equal(Number(raw), palette[field], theme + ' ' + token);
      checked++;
    }
  }
  assert.equal(checked, 87, 'the drift gate covers all 29 tokens in all three themes: ' + checked + ' checks');
});

function stripComments(css) {
  return css.replace(/\/\*[\s\S]*?\*\//g, '');
}

function blockAfter(css, selector) {
  const at = css.indexOf(selector);
  if (at < 0) return null;
  const start = at + selector.length;
  const end = css.indexOf('\n}', start);
  return end < 0 ? null : css.slice(start, end);
}

function declarations(block) {
  const out = {};
  const re = /(--[a-z0-9-]+)\s*:\s*([^;]+);/g;
  let m;
  while ((m = re.exec(block)) !== null) out[m[1]] = m[2].trim();
  return out;
}

/**
 * A token's declaration in one theme: its own, else the light one it inherits.
 * High contrast writes `--mlv-fg-boundary: var(--mlv-text)`, so a token may
 * alias another token in the same block, and the alias is followed once.
 */
function resolveAlias(declared, theme, token, depth = 0) {
  const raw = declared[theme][token] !== undefined ? declared[theme][token] : declared.light[token];
  const alias = /^var\((--mlv-[a-z0-9-]+)\)$/.exec(String(raw || '').trim());
  if (alias && depth < 4) return resolveAlias(declared, theme, alias[1], depth + 1);
  return raw;
}

function lastHex(value) {
  const hits = String(value || '').match(/#[0-9A-Fa-f]{3,8}/g);
  return hits ? hits[hits.length - 1] : null;
}

/* ── the print stylesheet ──────────────────────────────────────────────── */

test('the print stylesheet hides the chrome and releases the transform (VIEW-07)', () => {
  const at = devCss.indexOf('@media print');
  assert.ok(at > 0, 'there is a @media print block at all — there was none before VIEW-07');
  const block = devCss.slice(at, devCss.indexOf('\n}\n', devCss.lastIndexOf('break-inside')));
  const flat = block.replace(/\s+/g, ' ');

  for (const cls of ['.mlv-chromebar', '.mlv-rail', '.mlv-minimap', '.mlv-zoom', '.mlv-statehost', '.mlv-legend', '.mlv-exportmenu']) {
    assert.ok(flat.indexOf(cls + ',') >= 0 || flat.indexOf(cls + ' {') >= 0, cls + ' is not hidden for print');
  }
  assert.ok(/\.mlv-exportmenu,?[^{]*\{[^}]*display: none !important/.test(flat) || /display: none !important/.test(flat), 'the hide rule is !important');

  // The transform is what made Ctrl+P print the viewport at the current zoom.
  assert.ok(/\.mlv-world \{[^}]*transform: none !important/.test(flat), '.mlv-world must release its transform');
  assert.ok(/\.mlv-world \{[^}]*position: static !important/.test(flat), 'and contribute its height to the page');
  // ...and the clipping chain that kept the world inside one screen.
  assert.ok(/overflow: visible !important/.test(flat), 'the canvas must stop clipping');
  assert.ok(/height: auto !important/.test(flat), 'and stop being one viewport tall');
  assert.ok(/print-color-adjust: exact/.test(flat), 'lane washes and stage rails are meaning, not decoration');
  assert.ok(devCss.indexOf('@page') > 0, 'a page margin is declared');
});

/* ── the menu ──────────────────────────────────────────────────────────── */

test('the export menu sits beside Fit and opens as a real menu (VIEW-07)', async () => {
  const ctx = await mount();
  const button = ctx.document.querySelector('.mlv-btn--exportmenu');
  assert.ok(button, 'the trigger exists');
  const fit = Array.from(ctx.document.querySelectorAll('.mlv-toolbar .mlv-btn')).find(
    (b) => (b.getAttribute('aria-label') || '') === 'Fit to view',
  );
  assert.ok(fit, 'so does Fit');
  assert.ok(
    fit.compareDocumentPosition(button) & ctx.window.Node.DOCUMENT_POSITION_FOLLOWING,
    'and the export trigger comes right after it',
  );
  assert.equal(button.getAttribute('aria-haspopup'), 'menu');
  assert.equal(button.getAttribute('aria-expanded'), 'false');

  const panel = ctx.document.getElementById(button.getAttribute('aria-controls'));
  assert.ok(panel, 'aria-controls resolves');
  assert.equal(panel.getAttribute('role'), 'menu');
  assert.ok(panel.hidden, 'closed to begin with');
  // The popup must NOT be inside the roving toolbar (VIEW-12): eight more
  // controls under the toolbar's arrow keys is the flattening it exists to undo.
  assert.equal(panel.closest('[role="toolbar"]'), null, 'the panel lives outside the toolbar');

  click(ctx, button);
  assert.equal(button.getAttribute('aria-expanded'), 'true');
  assert.equal(panel.hidden, false);
  const regions = Array.from(panel.querySelectorAll('[role="menuitemradio"]'));
  assert.deepEqual(regions.map((r) => r.getAttribute('data-export-region')), ['view', 'diagram', 'scope']);
  assert.equal(regions.filter((r) => r.getAttribute('aria-checked') === 'true').length, 1, 'exactly one region is checked');
  const actions = Array.from(panel.querySelectorAll('[role="menuitem"]'));
  assert.deepEqual(
    actions.map((a) => a.getAttribute('data-export-action')),
    ['svg', 'png', 'copy-png', 'copy-svg', 'print'],
  );

  key(ctx, actions[0], 'Escape');
  assert.equal(panel.hidden, true, 'Escape closes it');
  assert.equal(button.getAttribute('aria-expanded'), 'false');
  ctx.app.destroy();
});

test('"Current scope" is offered only while something is scoped (VIEW-07)', async () => {
  const plain = await mount();
  const scopeItem = plain.document.querySelector('[data-export-region="scope"]');
  assert.equal(scopeItem.disabled, true, 'nothing is scoped, so the scope region is not offered');
  assert.equal(scopeItem.getAttribute('aria-disabled'), 'true');
  assert.ok(scopeItem.title.indexOf('Nothing is scoped') === 0, scopeItem.title);
  plain.app.destroy();

  const scoped = await mount(sample, { attrScope: 'concern:evaluation' });
  const item = scoped.document.querySelector('[data-export-region="scope"]');
  assert.equal(item.disabled, false, 'a projection turns it on');
  scoped.app.destroy();
});

/* ── the bytes leave through exportFile ────────────────────────────────── */

test('Save SVG posts exportFile with the picture in it (VIEW-07)', async () => {
  const ctx = await mount();
  const button = ctx.document.querySelector('.mlv-btn--exportmenu');
  click(ctx, button);
  click(ctx, ctx.document.querySelector('[data-export-action="svg"]'));

  const msg = ctx.posted.filter((m) => m.type === 'exportFile').pop();
  assert.ok(msg, 'the host was asked to save something: ' + ctx.posted.map((m) => m.type).join(', '));
  assert.equal(msg.v, 1);
  assert.equal(msg.kind, 'svg');
  assert.ok(/\.svg$/.test(msg.name), msg.name);
  assert.ok(typeof msg.base64 === 'string' && msg.base64.length > 100, 'and handed it bytes');
  // Both field spellings, always, and always equal — see the INTEROP NOTE on
  // `UiToHost.exportFile`: the host-side amendment validates `data` /
  // `suggestedName` and rejects a frame without them.
  assert.equal(msg.data, msg.base64, 'data === base64');
  assert.equal(msg.suggestedName, msg.name, 'suggestedName === name');
  assert.equal(msg.scope, 'all', "the region in the host's vocabulary: diagram is `all`");
  assert.ok(/^[A-Za-z0-9+/]+={0,2}$/.test(msg.data), 'pure base64, no whitespace and no data: prefix');
  assert.equal(msg.data.length % 4, 0, 'and a length the host validator accepts');

  const svg = Buffer.from(msg.base64, 'base64').toString('utf8');
  assert.ok(svg.indexOf('<svg') > 0, 'which decode to an SVG document');
  const layout = ctx.MLView.__internal.layout(sample, []);
  assert.equal(nodeGroups(svg).length, layout.nodes.length, 'carrying every drawn card');
  assert.equal(edgePaths(svg).length, layout.edges.length, 'and every routed edge');
  assert.equal(ctx.document.querySelector('.mlv-exportmenu').hidden, true, 'the menu closed behind the gesture');
  ctx.app.destroy();
});

test('the standalone bridge answers exportFile with a download (VIEW-07)', async () => {
  const ctx = await loadBundle();
  const clicks = [];
  const navigations = [];
  // jsdom 26 ships no `URL.createObjectURL`; every real host does, so this
  // closes a jsdom gap rather than a product gap (the same reasoning as the
  // `structuredClone` shim in helpers.mjs).
  let objectUrls = 0;
  if (typeof ctx.window.URL.createObjectURL !== 'function') {
    ctx.window.URL.createObjectURL = () => 'blob:mlview.test/' + ++objectUrls;
    ctx.window.URL.revokeObjectURL = () => undefined;
  }
  const proto = ctx.window.HTMLAnchorElement.prototype;
  const realClick = proto.click;
  proto.click = function patched() {
    const href = this.getAttribute('href') || '';
    if (this.hasAttribute('download')) {
      clicks.push({ href, name: this.getAttribute('download') });
      return undefined;
    }
    navigations.push(href);
    return realClick.apply(this, arguments);
  };
  try {
    const bridge = ctx.MLView.bridges.standalone({ theme: 'light' });
    const base64 = Buffer.from('<svg xmlns="test"/>', 'utf8').toString('base64');
    bridge.post({ v: 1, type: 'exportFile', kind: 'svg', name: 'mlview-demo-diagram.svg', base64 });
    assert.equal(clicks.length, 1, 'one download was started');
    assert.equal(clicks[0].name, 'mlview-demo-diagram.svg', 'under the name the viewer asked for');
    assert.ok(/^blob:/.test(clicks[0].href), 'from an object URL of local bytes: ' + clicks[0].href);
    assert.equal(navigations.length, 0, 'and the document was never navigated (11.17)');
    assert.equal(ctx.document.querySelectorAll('a[download]').length, 0, 'the anchor did not survive the call');
  } finally {
    proto.click = realClick;
  }
});

test('bridges.ts still cannot navigate, and the one anchor click is fenced (VIEW-07, 11.17)', async () => {
  const src = await readFile(join(REPO_ROOT, 'webview', 'src', 'export', 'download.ts'), 'utf8');
  const code = src.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/(^|\s)\/\/[^\n]*/g, ' ');
  assert.equal(code.indexOf('location.href'), -1, 'the download module may not navigate either');
  assert.equal(code.indexOf('window.open'), -1);
  assert.ok(code.indexOf("'download' in anchor") > 0, 'it refuses to click an anchor that would navigate instead');
  assert.ok(code.indexOf('createObjectURL') > 0, 'and only ever points at local bytes');
});

/* ── PNG ───────────────────────────────────────────────────────────────── */

test('the PNG is drawn from the SVG at 2x, and says so when it cannot be (VIEW-07)', async () => {
  const ctx = await mount();
  assert.equal(ctx.MLView.__internal.exportDiagram.pngScale, 2, 'the item asks for 2x');
  click(ctx, ctx.document.querySelector('.mlv-btn--exportmenu'));
  click(ctx, ctx.document.querySelector('[data-export-action="png"]'));
  await new Promise((r) => setTimeout(r, 60));
  // jsdom has no canvas, which is exactly the degradation this asserts: no
  // message claiming a file, and a toast that says why.
  assert.equal(ctx.posted.filter((m) => m.type === 'exportFile' && m.kind === 'png').length, 0, 'no PNG was claimed');
  const toast = ctx.document.querySelector('.mlv-toast');
  assert.ok(toast && toast.textContent.indexOf('Could not draw the PNG') >= 0, toast ? toast.textContent : 'no toast');
  ctx.app.destroy();
});

test('the host can ask for a picture with requestExport (VIEW-07)', async () => {
  const ctx = await loadBundle();
  const posted = [];
  let listener = null;
  const bridge = {
    host: 'vscode',
    theme: 'light',
    capabilities: { canOpenSource: true, canReanalyze: true, canExport: true, canAskAssistant: false },
    post: (m) => posted.push(m),
    onMessage: (cb) => {
      listener = cb;
      return () => undefined;
    },
    saveState: () => undefined,
    loadState: () => null,
  };
  const app = ctx.MLView.mount(ctx.document.getElementById('mlview-root'), sample, bridge);

  // The host's `mlview.exportSvg` command, asking for the current view.
  listener({ v: 1, type: 'requestExport', kind: 'svg', scope: 'view' });
  const first = posted.filter((m) => m.type === 'exportFile').pop();
  assert.ok(first, 'the viewer answered: ' + posted.map((m) => m.type).join(', '));
  assert.equal(first.scope, 'view', 'and echoed the region it was asked for');
  assert.equal(
    ctx.document.querySelector('[data-export-region="view"]').getAttribute('aria-checked'),
    'true',
    'the menu now shows the region the command chose',
  );

  // `all` is the host's word for the whole diagram.
  listener({ v: 1, type: 'requestExport', kind: 'svg', scope: 'all' });
  const second = posted.filter((m) => m.type === 'exportFile').pop();
  assert.equal(second.scope, 'all');
  const whole = Buffer.from(second.data, 'base64').toString('utf8');
  const cropped = Buffer.from(first.data, 'base64').toString('utf8');
  assert.ok(nodeGroups(whole).length >= nodeGroups(cropped).length, 'and it really is the bigger picture');

  // A frame the viewer has never heard of is still logged and ignored (§4).
  const before = posted.length;
  listener({ v: 1, type: 'somethingElse' });
  assert.ok(posted.length > before && posted[posted.length - 1].type === 'log', 'unknown types still degrade');
  app.destroy();
});

/* ── VW-03: the menu is operable from the keyboard ─────────────────────── */

/**
 * The menu-button pattern was implemented correctly in isolation and then lost
 * every key to the toolbar around it. The trigger is one item of the chrome's
 * roving `role="toolbar"`, whose keydown listener sits on the CONTAINER: it
 * read ArrowDown as "next toolbar button", called preventDefault +
 * stopPropagation and moved focus. The menu's own handler called
 * preventDefault but not stopPropagation, so the roving group ran afterwards
 * and won — ArrowDown opened the menu and put focus on "Toggle side rail",
 * outside it. Enter opened it and left focus on the trigger, and since every
 * item is `tabIndex = -1` (as `role="menu"` requires) Tab went straight to the
 * canvas: no item was reachable at all. Escape only worked from inside the
 * panel, so the 268 x 478 px popup sat over the diagram until someone reached
 * for the mouse.
 */
test('the export menu opens, walks and closes from the keyboard alone (VW-03)', async () => {
  const ctx = await mount();
  const button = ctx.document.querySelector('.mlv-btn--exportmenu');
  const panel = ctx.document.getElementById(button.getAttribute('aria-controls'));
  assert.ok(button.closest('[role="toolbar"]'), 'the trigger really is inside the roving toolbar');

  // ArrowDown opens it and lands INSIDE it — the roving group never sees the key.
  button.focus();
  key(ctx, button, 'ArrowDown');
  assert.equal(button.getAttribute('aria-expanded'), 'true', 'ArrowDown opens the menu');
  assert.equal(panel.hidden, false);
  const first = ctx.document.activeElement;
  assert.ok(
    panel.contains(first),
    'focus is in the menu, not on the next toolbar item: ' + (first && first.getAttribute('aria-label')),
  );

  // ArrowDown walks to "Save SVG" without leaving the menu.
  const seen = [];
  for (let i = 0; i < 8; i++) {
    const at = ctx.document.activeElement;
    seen.push(at.getAttribute('data-export-region') || at.getAttribute('data-export-action'));
    if (at.getAttribute('data-export-action') === 'svg') break;
    key(ctx, at, 'ArrowDown');
    assert.ok(panel.contains(ctx.document.activeElement), 'still inside the menu after ' + seen.join(' -> '));
  }
  assert.equal(ctx.document.activeElement.getAttribute('data-export-action'), 'svg', 'reached Save SVG: ' + seen.join(' -> '));

  // Escape closes it and gives the trigger its focus back.
  key(ctx, ctx.document.activeElement, 'Escape');
  assert.equal(panel.hidden, true, 'Escape from inside closes it');
  assert.equal(ctx.document.activeElement, button, 'and focus returns to the trigger');
  assert.equal(button.getAttribute('aria-expanded'), 'false');
  ctx.app.destroy();
});

test('every open gesture puts focus on the first item, and Escape closes from the trigger (VW-03)', async () => {
  const ctx = await mount();
  const button = ctx.document.querySelector('.mlv-btn--exportmenu');
  const panel = ctx.document.getElementById(button.getAttribute('aria-controls'));

  // Enter and Space activate a <button> as a click, which is the gesture that
  // used to open the menu and leave the reader with nothing to Tab to.
  button.focus();
  click(ctx, button);
  assert.equal(panel.hidden, false);
  assert.ok(panel.contains(ctx.document.activeElement), 'the click gesture focuses item 0 too');

  // ...and Escape works with focus back on the trigger, where the panel's own
  // handler can never see it.
  button.focus();
  key(ctx, button, 'Escape');
  assert.equal(panel.hidden, true, 'Escape from the trigger closes the menu');
  assert.equal(button.getAttribute('aria-expanded'), 'false');
  ctx.app.destroy();
});

/* ── VW-05: the export carries the theme the reader chose ──────────────── */

/**
 * `ThemeController.choose()` — the handler behind the standalone report's Auto
 * / Light / Dark / High contrast chips — applied the theme and told nobody, so
 * `App.theme` kept its construction value for the life of the session and every
 * exported SVG was stamped `data-mlview-theme="light"`. The palette followed
 * (it is read off the live custom properties) but `const hc = theme === 'hc'`
 * did not, so the high-contrast rendering — outlined severity glyphs instead of
 * filled ones — was unreachable from the standalone report.
 */
async function exportedSvg(ctx) {
  click(ctx, ctx.document.querySelector('.mlv-btn--exportmenu'));
  click(ctx, ctx.document.querySelector('[data-export-action="svg"]'));
  const msg = ctx.posted.filter((m) => m.type === 'exportFile' && m.kind === 'svg').pop();
  assert.ok(msg, 'the export ran');
  return Buffer.from(msg.base64, 'base64').toString('utf8');
}

test('the standalone theme switch reaches the export (VW-05)', async () => {
  const ctx = await mount(sample, { host: 'standalone' });
  const chip = (kind) => ctx.document.querySelector('[data-theme-option="' + kind + '"]');
  assert.ok(chip('hc'), 'the standalone report offers the four theme chips');

  // The one shape only `severityGlyphMarkup` emits: a scaled glyph group whose
  // shape path is outlined instead of filled (`styles/node.css` does the same).
  const outlinedGlyph = /<g transform="translate\([^)]*\) scale\([^)]*\)"><path d="[^"]*" fill="none"/;
  const light = await exportedSvg(ctx);
  assert.ok(/data-mlview-theme="light"/.test(light), 'the default export says light');
  assert.equal(outlinedGlyph.test(light), false, 'and fills its severity glyphs');

  click(ctx, chip('dark'));
  assert.equal(ctx.root.getAttribute('data-theme'), 'dark');
  const dark = await exportedSvg(ctx);
  assert.ok(/data-mlview-theme="dark"/.test(dark), 'a dark export says dark');

  click(ctx, chip('hc'));
  assert.equal(ctx.root.getAttribute('data-theme'), 'hc');
  const hc = await exportedSvg(ctx);
  assert.ok(/data-mlview-theme="hc"/.test(hc), 'a high-contrast export says hc');
  assert.ok(outlinedGlyph.test(hc), 'and draws the severity glyphs outlined, as the theme does');
  ctx.app.destroy();
});
