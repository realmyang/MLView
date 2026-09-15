'use strict';
/**
 * Feature 2, host side: the cursor -> `unit:` selector resolution and the two scope commands
 * (CONTRACTS.md §11.7, §11.11).
 *
 * The fixture is a REAL analyzer run over `samples/vision_pipeline`, so `findEnclosingUnit` is
 * asserted against the shape the analyzer actually emits rather than a hand-written graph.
 * Regenerate it — in a commit of its own, because a graph-content change can move the
 * assertions below — with:
 *
 *   python vscode-extension/tools/make_scope_fixture.py
 *
 * NOT with the bare CLI. The raw document embeds `workspace.root` and an `absFile` on every
 * node, edge, issue, related location and fix edit, so a hand-run writes ~164 copies of the
 * runner's own home directory into a public repository. The script runs the same CLI and then
 * rewrites every path under this checkout to the neutral `/home/mlview/MLView` the committed
 * fixture uses, refusing to write if one real path survives. `--check` regenerates in a
 * temporary directory and byte-compares instead of writing; `test/fixture.test.js` runs both
 * halves of that guarantee, so this recipe cannot rot and the fixture cannot go stale.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { api, vscode } = require('./harness.js');

const {
  buildLocationIndex,
  findNodeAtLine,
  findEnclosingUnit,
  scopeToSymbol,
  clearScope,
  unitScopeSpec,
  scopeChrome,
  activeScopeFrom,
  PANEL_TITLE,
  isUiToHost,
  isHostToUi
} = api;

const FIXTURE = path.join(__dirname, 'fixtures', 'vision_pipeline.graph.json');
const graph = JSON.parse(fs.readFileSync(FIXTURE, 'utf8'));
const ROOT = graph.workspace.root;

/** A stand-in for `MlviewPanel` that records exactly what the command posted. */
function stubPanel() {
  return {
    posted: [],
    postSetScope(spec, depth) {
      this.posted.push({
        v: 1,
        type: 'setScope',
        spec,
        ...(typeof depth === 'number' ? { depth } : {})
      });
    },
    postRevealNode() {
      throw new Error('a scope command must never reveal a node');
    },
    postGraph() {
      throw new Error('a scope command must never re-render a graph');
    }
  };
}

function deps(panel, overrides = {}) {
  return {
    log: { trace() {}, debug() {}, info() {}, warn() {}, error() {}, show() {} },
    getGraph: () => graph,
    getIndex: () => buildLocationIndex(graph),
    ensurePanel: async () => panel,
    getPanel: () => panel,
    ensureGraph: async () => {
      throw new Error('the graph was already loaded; ensureGraph must not run an analysis');
    },
    ...overrides
  };
}

function setCursor(file, editorLine) {
  vscode.window.activeTextEditor = {
    document: { uri: vscode.Uri.file(`${ROOT}/${file}`), languageId: 'python', fileName: file },
    selection: { active: { line: editorLine, character: 0 } }
  };
}

test.afterEach(() => {
  vscode.window.activeTextEditor = undefined;
});

// ---------------------------------------------------------------- findEnclosingUnit

test('the index carries the parent and qualname the climb needs', () => {
  const index = buildLocationIndex(graph);
  const loop = [...index.nodes.values()].find((n) => n.qualname === 'train.validate.batch_loop');
  assert.ok(loop, 'the sample has a batch loop inside validate()');
  assert.equal(loop.level, 'unit');
  const parent = index.nodes.get(loop.parent);
  assert.ok(parent, 'parent must be an id that resolves inside the index');
  assert.equal(parent.qualname, 'train.validate');
});

test('train.py:44 resolves to validate() even though the narrowest node is its batch loop', () => {
  const index = buildLocationIndex(graph);

  // What the reveal path sees: the NARROWEST containing node, which is the loop.
  const raw = findNodeAtLine(index, 'train.py', 44);
  assert.ok(raw && raw.exact);
  assert.equal(index.nodes.get(raw.nodeId).qualname, 'train.validate.batch_loop');

  // What a scope needs: the enclosing unit.
  const unit = findEnclosingUnit(index, 'train.py', 44);
  assert.ok(unit, 'line 44 is inside validate()');
  assert.equal(unit.qualname, 'train.validate');
  assert.equal(unit.label, 'validate()');
  assert.equal(unit.fromNodeId, raw.nodeId, 'the climb starts at the findNodeAtLine hit');
  assert.equal(unitScopeSpec(unit.qualname), 'unit:train.validate');
});

test('a lane root stands for itself, and an op climbs to the unit that contains it', () => {
  const index = buildLocationIndex(graph);

  // Line 42 (`correct = 0`) is inside validate() but inside none of its children.
  const self = findEnclosingUnit(index, 'train.py', 42);
  assert.equal(self.qualname, 'train.validate');
  assert.equal(self.fromNodeId, self.nodeId, 'nothing to climb to; the hit is already a unit');

  // Line 19 (`device = ...`) is an op inside train().
  const fromOp = findEnclosingUnit(index, 'train.py', 19);
  assert.equal(fromOp.qualname, 'train.train');
  assert.notEqual(fromOp.fromNodeId, fromOp.nodeId, 'an op is never its own scope');
  assert.ok(['unit', 'stage'].includes(fromOp.level));
});

test('a cursor inside no node resolves to nothing — a scope is never guessed', () => {
  const index = buildLocationIndex(graph);
  // Line 1 is the import block: `findNodeAtLine` falls back to the NEAREST node there.
  const nearest = findNodeAtLine(index, 'train.py', 1);
  assert.ok(nearest && nearest.exact === false, 'the reveal path guesses here');
  assert.equal(findEnclosingUnit(index, 'train.py', 1), null, 'the scope path must not');
  assert.equal(findEnclosingUnit(index, 'not_a_file.py', 12), null);
});

test('the climb is forward-slash and case tolerant, like every other lookup', () => {
  const index = buildLocationIndex(graph);
  assert.equal(findEnclosingUnit(index, 'TRAIN.PY', 44).qualname, 'train.validate');
  assert.equal(findEnclosingUnit(index, '.\\train.py', 44).qualname, 'train.validate');
});

// ---------------------------------------------------------------- the two commands

test('mlview.scopeToSymbol posts setScope with the enclosing unit selector', async () => {
  const panel = stubPanel();
  setCursor('train.py', 43); // 0-based editor line 43 == graph line 44
  await scopeToSymbol(deps(panel));
  assert.deepEqual(panel.posted, [{ v: 1, type: 'setScope', spec: 'unit:train.validate' }]);
  assert.ok(isHostToUi(panel.posted[0]), 'the posted message is a known host -> ui message');
});

test('mlview.clearScope posts a null spec', async () => {
  const panel = stubPanel();
  await clearScope(deps(panel));
  assert.deepEqual(panel.posted, [{ v: 1, type: 'setScope', spec: null }]);
});

test('mlview.clearScope with no diagram open is a no-op and never opens a panel', async () => {
  const panel = stubPanel();
  let opened = 0;
  const before = vscode.__recorded.messages.length;
  await clearScope(
    deps(panel, {
      getPanel: () => undefined,
      ensurePanel: async () => {
        opened += 1;
        return panel;
      }
    })
  );
  assert.equal(opened, 0, 'clearing a scope must never create the diagram panel');
  assert.deepEqual(panel.posted, [], 'nothing to clear, so nothing is posted');
  assert.equal(vscode.__recorded.messages.length, before, 'and no toast either');
});

test('mlview.scopeToSymbol still opens the panel: it has something to show', async () => {
  const panel = stubPanel();
  let opened = 0;
  setCursor('train.py', 43);
  await scopeToSymbol(
    deps(panel, {
      getPanel: () => undefined,
      ensurePanel: async () => {
        opened += 1;
        return panel;
      }
    })
  );
  assert.equal(opened, 1);
  assert.deepEqual(panel.posted, [{ v: 1, type: 'setScope', spec: 'unit:train.validate' }]);
});

test('a cursor in no node shows the "no node here" toast and posts nothing', async () => {
  const panel = stubPanel();
  const before = vscode.__recorded.messages.length;
  setCursor('train.py', 0);
  await scopeToSymbol(deps(panel));
  assert.deepEqual(panel.posted, [], 'no scope may be posted for a guess');
  const said = vscode.__recorded.messages.slice(before);
  assert.equal(said.length, 1);
  assert.equal(said[0][0], 'info');
  assert.match(said[0][1], /no diagram node was found in train\.py/);
});

test('with no editor open the command explains itself instead of scoping', async () => {
  const panel = stubPanel();
  vscode.window.activeTextEditor = undefined;
  const before = vscode.__recorded.messages.length;
  await scopeToSymbol(deps(panel));
  assert.deepEqual(panel.posted, []);
  assert.equal(vscode.__recorded.messages.length, before + 1);
});

test('scoping analyses nothing: an absent graph goes through ensureGraph, never a re-run', async () => {
  const panel = stubPanel();
  let analyses = 0;
  setCursor('train.py', 43);
  await scopeToSymbol(
    deps(panel, {
      getGraph: () => undefined,
      ensureGraph: async () => {
        analyses += 1;
        return graph;
      }
    })
  );
  assert.equal(analyses, 1, 'exactly one analysis, and only because there was no graph at all');
  assert.deepEqual(panel.posted, [{ v: 1, type: 'setScope', spec: 'unit:train.validate' }]);
});

// ---------------------------------------------------------------- the panel chrome

test('the title and description formatter (CONTRACTS.md §11.11)', () => {
  const scoped = scopeChrome({ spec: 'unit:train.validate', label: 'validate()', nodes: 4, of: 45 });
  assert.equal(scoped.title, 'MLView — validate()');
  assert.ok(scoped.title.includes('—'), 'the codebase em dash, not a hyphen');
  assert.equal(scoped.description, '4 of 45 nodes');

  const cleared = scopeChrome({ spec: null, label: 'Everything', nodes: 45, of: 45 });
  assert.equal(cleared.title, PANEL_TITLE);
  assert.equal(cleared.description, '45 of 45 nodes');

  // A viewer that sends a spec but no label still gets a titled panel.
  assert.equal(
    scopeChrome({ spec: 'stage:train', label: '', nodes: 9, of: 45 }).title,
    'MLView — stage:train'
  );
});

test('scopeChanged is a well-formed ui -> host message', () => {
  assert.ok(
    isUiToHost({ v: 1, type: 'scopeChanged', spec: 'unit:train.validate', label: 'validate()', nodes: 4, of: 45 })
  );
  assert.ok(isUiToHost({ v: 1, type: 'scopeChanged', spec: null, label: 'Everything', nodes: 45, of: 45 }));
});

// ---------------------------------------------------------------- R2H-06: the exported scope

/**
 * The panel remembers what the viewer says it is drawing so `MLView: Export HTML Report`
 * writes THAT diagram. `scopeChanged` (§11.7) carries no depth, so the depth is recovered from
 * the viewer's own saved `ViewState.scope` (§11.9) - and only when it describes the same
 * selector, because a stale depth would silently export a different projection.
 */
test('the exported scope is the viewer selector, with the depth only when it matches', () => {
  assert.equal(activeScopeFrom(null, undefined), undefined, 'an unscoped panel exports nothing');
  assert.equal(
    activeScopeFrom(null, { scope: { spec: 'concern:evaluation', depth: 2 } }),
    undefined,
    'a cleared scope wins over a saved state that has not caught up'
  );
  assert.deepEqual(
    activeScopeFrom('unit:train.validate', undefined),
    { spec: 'unit:train.validate' },
    'no state yet: no depth, so the CLI applies the same per-kind default the viewer does'
  );
  assert.deepEqual(
    activeScopeFrom('concern:evaluation', { scope: { spec: 'concern:evaluation', depth: 2 } }),
    { spec: 'concern:evaluation', depth: 2 }
  );
  assert.deepEqual(
    activeScopeFrom('concern:evaluation', { scope: { spec: 'stage:train', depth: 2 } }),
    { spec: 'concern:evaluation' },
    'a depth belonging to another selector must never be exported'
  );
  assert.deepEqual(
    activeScopeFrom('concern:evaluation', { scope: { spec: 'concern:evaluation', depth: 9 } }),
    { spec: 'concern:evaluation' },
    'depth is 0..2 (§11.5); anything else is dropped rather than passed to the CLI'
  );
  assert.deepEqual(
    activeScopeFrom('concern:evaluation', { scope: { spec: 'concern:evaluation', depth: '1' } }),
    { spec: 'concern:evaluation' },
    'a non-numeric depth from a restored state is dropped'
  );
  assert.deepEqual(activeScopeFrom('stage:train', {}), { spec: 'stage:train' });
});
