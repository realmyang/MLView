/**
 * Cross-host scope handshake — the REAL viewer bundle against the REAL extension.
 *
 * Every other test of CONTRACTS §11.7 stands on one side of the wire: the viewer
 * suite posts `scopeChanged` into a recording bridge, and the extension suite
 * feeds a hand-written `scopeChanged` into a mocked webview. Nothing proved that
 * the object one side WRITES is the object the other side READS — the classic
 * place a field name drifts (`spec` vs `scope`, §11.7's whole reason for existing).
 *
 * So: mount `webview/dist/mlview.js` in jsdom, hand it the `setScope` message the
 * extension actually posts, take the `scopeChanged` it answers with, and put that
 * object through the extension's own `parseUiToHost` and `scopeChrome`.
 *
 *   node test/crosshost.mjs [path/to/graph.json]
 *
 * Exits 0 when every check passes, 1 otherwise, and 0 with a SKIP line when the
 * extension's test bundle has not been built (`npm run pretest` in
 * vscode-extension) — this script is an integration gate, not a build step.
 */

import { readFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { JSDOM, VirtualConsole } from 'jsdom';

const HERE = dirname(fileURLToPath(import.meta.url));
const WEBVIEW_ROOT = resolve(join(HERE, '..'));
const REPO_ROOT = resolve(join(WEBVIEW_ROOT, '..'));
const EXT_ROOT = join(REPO_ROOT, 'vscode-extension');
const HARNESS = join(EXT_ROOT, 'test', 'harness.js');
const EXT_BUNDLE = join(EXT_ROOT, 'out', 'test-entry.cjs');

const out = (line) => process.stdout.write(line + '\n');

if (!existsSync(EXT_BUNDLE) || !existsSync(HARNESS)) {
  out('CROSS-HOST CHECK SKIPPED -- vscode-extension/out/test-entry.cjs is not built');
  process.exit(0);
}

const positional = process.argv.slice(2).filter((a) => a.indexOf('--') !== 0);
const graphPath = positional[0] ? resolve(positional[0]) : join(REPO_ROOT, '.mlview', 'graph.json');

const failures = [];
function check(ok, label, detail) {
  out((ok ? '  PASS  ' : '  FAIL  ') + label.padEnd(56) + (detail === undefined ? '' : detail));
  if (!ok) failures.push(label + ' -- ' + detail);
}

/* -- the extension, loaded through its own vscode-mocking harness -------- */

const require = createRequire(import.meta.url);
const ext = require(HARNESS).api;

/* -- the viewer, loaded as the webview and the report load it ------------ */

const graph = JSON.parse(await readFile(graphPath, 'utf8'));
const js = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.js'), 'utf8');

const virtualConsole = new VirtualConsole();
virtualConsole.on('jsdomError', () => undefined);
const dom = new JSDOM('<!doctype html><html><head></head><body><div id="mlview-root"></div></body></html>', {
  runScripts: 'dangerously',
  pretendToBeVisual: true,
  url: 'https://mlview.test/',
  virtualConsole,
});
const { window } = dom;
if (typeof window.structuredClone !== 'function') window.structuredClone = (v) => JSON.parse(JSON.stringify(v));
window.matchMedia = (q) => ({
  media: q,
  matches: false,
  addEventListener() {},
  removeEventListener() {},
  addListener() {},
  removeListener() {},
  onchange: null,
  dispatchEvent: () => false,
});
const script = window.document.createElement('script');
script.textContent = js;
window.document.head.appendChild(script);

const posted = [];
let toViewer = null;
const bridge = {
  host: 'vscode',
  theme: 'light',
  capabilities: { canOpenSource: true, canReanalyze: true, canExport: true, canAskAssistant: false },
  post: (m) => posted.push(m),
  onMessage: (fn) => {
    toViewer = fn;
    return () => undefined;
  },
  saveState() {},
  loadState: () => null,
};

out('MLView cross-host scope handshake -- viewer bundle x extension bundle');
out('  graph: ' + graphPath + '  (' + graph.nodes.length + ' nodes)');
out('');

const app = window.MLView.mount(window.document.getElementById('mlview-root'), graph, bridge);
check(typeof toViewer === 'function', 'the viewer subscribed to host messages', typeof toViewer);

/* -- the unit the extension's own command would resolve ------------------ */
// Pick it the way a user does: put the cursor inside a real unit and let
// findEnclosingUnit say what that is. Nothing here is hard-coded to one sample.
const index = ext.buildLocationIndex(graph);
const unitNode = graph.nodes.find(
  (n) => n.level === 'unit' && n.loc && graph.nodes.some((c) => c.parent === n.id),
);
check(!!unitNode, 'the graph offers a scopable unit', unitNode ? unitNode.qualname : 'none');
const unit = ext.findEnclosingUnit(index, unitNode.loc.file, unitNode.loc.line);
check(!!unit, 'findEnclosingUnit resolves the cursor', unit ? unit.qualname : 'null');
const spec = ext.unitScopeSpec(unit.qualname);

/* -- host -> viewer ------------------------------------------------------ */
posted.length = 0;
toViewer({ v: 1, type: 'setScope', spec });

const changed = posted.filter((m) => m.type === 'scopeChanged');
check(changed.length === 1, 'the viewer answers with exactly one scopeChanged', JSON.stringify(changed.map((m) => m.spec)));
check(
  posted.every((m) => m.type !== 'requestRefresh'),
  'a scope NEVER triggers a re-analysis (CONTRACTS 11.8)',
  posted.map((m) => m.type).join(', ') || 'nothing else posted',
);

/* -- viewer -> host, through the extension's own parser ------------------ */
const msg = changed[0];
const parsed = ext.parseUiToHost(msg);
check(parsed.ok === true, 'the extension parser accepts the viewer object', parsed.ok ? 'ok' : parsed.reason + ': ' + parsed.detail);
check(parsed.ok && parsed.msg.type === 'scopeChanged', 'it classifies as scopeChanged', parsed.ok ? parsed.msg.type : '');
check(msg.spec === spec, 'the selector field is `spec` and round-trips', String(msg.spec));
check(typeof msg.label === 'string' && msg.label.length > 0, 'label is a non-empty string', JSON.stringify(msg.label));
check(msg.of === graph.nodes.length, '`of` is the PROJECT total, not the projection', msg.nodes + ' of ' + msg.of);
check(msg.nodes > 0 && msg.nodes <= msg.of, '`nodes` is the projection size', msg.nodes + ' of ' + msg.of);

const chrome = ext.scopeChrome(msg);
check(chrome.title === 'MLView — ' + msg.label, 'the panel title the host would set', JSON.stringify(chrome.title));
check(chrome.description === msg.nodes + ' of ' + msg.of + ' nodes', 'the panel description', JSON.stringify(chrome.description));

/* -- clearing ------------------------------------------------------------ */
posted.length = 0;
toViewer({ v: 1, type: 'setScope', spec: null });
const cleared = posted.filter((m) => m.type === 'scopeChanged');
check(cleared.length === 1, 'clearing answers exactly once', JSON.stringify(cleared.map((m) => m.spec)));
check(!!cleared[0] && cleared[0].spec === null, 'a cleared scope posts spec: null', String(cleared[0] && cleared[0].spec));
check(!!cleared[0] && cleared[0].label === 'Everything', 'and label "Everything" (CONTRACTS 11.7)', String(cleared[0] && cleared[0].label));
check(!!cleared[0] && cleared[0].nodes === cleared[0].of, 'and nodes === of', cleared[0] ? cleared[0].nodes + ' / ' + cleared[0].of : '');
check(!!cleared[0] && ext.scopeChrome(cleared[0]).title === ext.PANEL_TITLE, 'the panel title goes back', cleared[0] ? ext.scopeChrome(cleared[0]).title : '');

/* -- an unresolvable spec is a no-op, never a throw ---------------------- */
let threw = null;
try {
  toViewer({ v: 1, type: 'setScope', spec: 'unit:DefinitelyNotHere' });
} catch (e) {
  threw = String(e);
}
check(threw === null, 'an empty scope never throws out of the handler', threw || 'clean');

/* -- and the viewer still agrees with itself ----------------------------- */
app.setScope(spec);
const s = app.getScope();
check(s.spec === spec && s.of === graph.nodes.length, 'getScope() agrees with the message it posted', JSON.stringify(s));


/* -- review round 2: what a RE-ANALYSIS tells the host -------------------- */
// The panel title and description have exactly one writer, `onScopeChanged`
// (CONTRACTS 11.11). A new document can move the scope with no user gesture —
// it is re-resolved, and dropped when it now matches nothing — and the viewer
// used to keep that to itself, so the tab went on reading `MLView — validate()`
// over a whole-workspace diagram (R2H-01 / R2-REG-02).
app.setScope(spec);
posted.length = 0;
const dropped = { ...graph };
// Every node the selector could resolve to. `unit:` tiers 3-5 cannot match a
// DOTTED target, so removing the exact qualname is enough to make it resolve to
// nothing — which is the "the function was renamed" case, exactly.
const goneIds = new Set(
  graph.nodes
    .filter((n) => n.qualname === unit.qualname || (n.qualname || '').indexOf(unit.qualname + '.') === 0)
    .map((n) => n.id),
);
dropped.nodes = graph.nodes.filter((n) => !goneIds.has(n.id));
dropped.edges = graph.edges.filter((e) => !goneIds.has(e.source) && !goneIds.has(e.target));
dropped.issues = (graph.issues || []).filter((i) => (i.nodeIds || []).every((id) => !goneIds.has(id)));
const liveIssues = new Set(dropped.issues.map((i) => i.id));
dropped.nodes = dropped.nodes.map((n) => ({ ...n, issueIds: (n.issueIds || []).filter((id) => liveIssues.has(id)) }));
toViewer({ v: 1, type: 'graph', graph: dropped, preserve: {} });

const afterGraph = posted.filter((m) => m.type === 'scopeChanged');
check(afterGraph.length === 1, 'a re-analysis that drops the scope posts scopeChanged', JSON.stringify(afterGraph.map((m) => m.spec)));
check(!!afterGraph[0] && afterGraph[0].spec === null, 'and it posts spec: null (CONTRACTS 11.7)', String(afterGraph[0] && afterGraph[0].spec));
check(
  !!afterGraph[0] && ext.scopeChrome(afterGraph[0]).title === ext.PANEL_TITLE,
  'so the panel title stops naming a unit that is gone',
  afterGraph[0] ? ext.scopeChrome(afterGraph[0]).title : '',
);
check(app.getScope().spec === null, 'and the viewer agrees the scope is gone', JSON.stringify(app.getScope()));

/* -- review round 2: the host's real mount order -------------------------- */
// `panel.ts` mounts the viewer with NO graph and `extension.ts` posts
// init -> restoreState -> graph, so both restore routes ran before any document
// existed and `ViewState.scope` — alone among every field — was discarded (R2H-03).
app.destroy();
const second = window.document.createElement('div');
second.id = 'mlview-root-2';
window.document.body.appendChild(second);
posted.length = 0;
const late = window.MLView.mount(second, null, bridge);
toViewer({ v: 1, type: 'restoreState', state: { scope: { spec, depth: 1 } } });
check(late.getScope().spec === null, 'a scope restored before the graph waits', JSON.stringify(late.getScope().spec));
toViewer({ v: 1, type: 'graph', graph, preserve: {} });
check(late.getScope().spec === spec, 'and lands when the document arrives', JSON.stringify(late.getScope().spec));
const restored = posted.filter((m) => m.type === 'scopeChanged');
check(restored.length === 1, 'the host hears about it exactly once', JSON.stringify(restored.map((m) => m.spec)));
check(
  !!restored[0] && ext.scopeChrome(restored[0]).title === 'MLView — ' + restored[0].label,
  'and the panel comes back with its scope in the tab',
  restored[0] ? ext.scopeChrome(restored[0]).title : '',
);

out('');
if (failures.length) {
  out('CROSS-HOST CHECK FAILED -- ' + failures.length + ' assertion(s)');
  for (const f of failures) out('  ' + f);
  process.exit(1);
}
out('CROSS-HOST CHECK OK -- every assertion passed');
