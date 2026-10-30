// Geometry golden for the routed layout.
//
// The renderer-regression test compares node positions within one run; this
// file pins the ABSOLUTE picture: every lane band, card and group box, every
// routed connection and bundle path, and every edge label position, for the
// renderer-regression fixture expanded and with every group collapsed. The
// digest of each picture is recorded below and must stay the same after any
// change, so a routing or layout edit that moves anything fails here.
//
// A digest is recorded again only when a change to the layout or the routing
// is meant, from the value that the failing run prints; a digest that changes
// for any other reason shows a fault. The fixture puts both kinds of route
// into the pictures. Half of its connections are inferred and most of those
// skip lanes: each one joins no trunk and takes a channel track of its own,
// `EXCEPTION_TRACK_STEP` px from the next and inside the innermost observed
// trunk, and `layout/separate.ts` moves its other runs off the strokes they
// would share. The tracks are reserved from the document's connections and not
// from what is folded, so the channel is equally wide in both pictures.
//
// Numbers are rounded to 0.1 before hashing. Layout reads no DOM measurement,
// so its numbers in jsdom are those a page gets. A digest that differs between
// Node versions or systems is a difference to find, not a reason for a digest
// per platform.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { loadBundle, recordingBridge, rendererRegressionWorkflow, routedGeometry } from './helpers.mjs';

const GOLDEN = {
  expanded: '3c67fb04973d89055fead9bbbf3419088f2b9522f57df70ef091884562edc944',
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
