// Geometry golden for the routed layout (RENDER-12).
//
// The renderer-regression test compares node positions within one run; this
// file pins the ABSOLUTE picture: every lane band, card and group box, every
// routed connection and bundle path, and every edge label position, for the
// renderer-regression fixture expanded and with every group collapsed. The
// digest was recorded from the e7d175f bundle before the RENDER-2 routing
// change, so a routing or layout edit that moves anything fails here.
//
// Re-recorded once, deliberately, in viewer M2 (2026-10-02): the projection no
// longer gives every card a `basis=<basis>` chip row (each expanded card lost
// 26 px, which also changes how ranks wrap) and edge labels no longer end in
// " · <basis>". Collapsed groups keep their count chip row, so only the labels
// moved in the collapsed picture.
//
// Re-recorded once more, deliberately, in stage 0a of the canvas re-layout
// (2026-10-04, requirement R7): an inferred or unresolved connection no longer
// joins a trunk. Each one that skips a lane takes a channel track of its own,
// 8 px apart and inside the innermost observed trunk, and `layout/separate.ts`
// moves its other runs off the strokes they shared. Half of this fixture's
// connections are inferred and most skip lanes, so in both pictures the channel
// widens by 144 px (27 tracks; the reservation does not depend on folds) and
// every box moves right by that much. The inferred routes take new paths, the
// observed routes that shared a trunk or a channel slot with them re-splay or
// change slot, the other observed routes move right with the boxes, and labels
// follow their routes. Any other change here is a regression.
//
// Numbers are rounded to 0.1 before hashing. Layout uses no DOM text
// measurement, so jsdom reproduces the browser geometry. If CI on another Node
// or OS disagrees, investigate the difference before adding per-platform
// digests.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { loadBundle, recordingBridge, rendererRegressionWorkflow, routedGeometry } from './helpers.mjs';

const GOLDEN = {
  expanded: '7c2b86f2b323f3db12b97c066c179e272f36ce27ad5586cd47cd73aa5efb7440',
  collapsed: '7d855c35bbb6baf57dd869170e46197ce937938d84193ca4e8da57f7a7f50920',
};

const digest = (geometry) => createHash('sha256').update(JSON.stringify(geometry)).digest('hex');

async function mounted() {
  const ctx = await loadBundle();
  const bridge = recordingBridge(ctx.window, 'vscode');
  const app = ctx.MLView.mountWorkflow(ctx.document.getElementById('mlview-root'), rendererRegressionWorkflow(), bridge);
  return { ...ctx, bridge, app };
}

function collapse(ctx, ids) {
  ctx.bridge.send({ v: 1, type: 'restoreState', state: { collapsed: ids } });
}

test('routed geometry of the expanded renderer-regression fixture matches the golden', async () => {
  const ctx = await mounted();
  collapse(ctx, []);
  const geometry = routedGeometry(ctx.document);
  assert.equal(geometry.boxes.filter((b) => b[0] === 'node' || b[0] === 'group').length, 48);
  assert.ok(geometry.routes.length >= 40);
  assert.equal(digest(geometry), GOLDEN.expanded, 'expanded geometry changed: ' + digest(geometry));
  ctx.app.destroy();
});

test('routed geometry of the all-collapsed renderer-regression fixture matches the golden', async () => {
  const ctx = await mounted();
  const groups = Array.from({ length: 8 }, (_, i) => `node-${i}`);
  collapse(ctx, groups);
  assert.deepEqual(ctx.app.getState().collapsed.slice().sort(), groups.slice().sort());
  const geometry = routedGeometry(ctx.document);
  assert.equal(geometry.boxes.filter((b) => b[0] === 'node' || b[0] === 'group').length, 8);
  assert.equal(digest(geometry), GOLDEN.collapsed, 'collapsed geometry changed: ' + digest(geometry));
  ctx.app.destroy();
});
