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
// moved in the collapsed picture. Any other change here is a regression.
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
  expanded: '6f29f6b84c02cef2dd2761ba1ab9511be6dd425b6eac49d0dd2584c01f90eb44',
  collapsed: 'bfb42d2c0bfc77aa2f7e6a35006a9b94ddd32b092a20c0739db946df0bf8c4a6',
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
