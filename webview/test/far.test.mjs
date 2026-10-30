// The rules of a far connection in the review walk (`src/far.ts`), as pure functions.
//
// A far connection is one whose two end cards cannot both be shown. The walk keeps its source card
// and the start of its lit line, ends that line in a cap where it runs out of sight, and prints one
// line in the walk bar that names the other card. `far.ts` holds what decides all of that and
// touches no DOM, so it is compiled from the sources here and called directly:
//
//   - what is in view, and when a connection is far (`inView`, `farEnd`, `isFar`, `farGoal`);
//   - where a line leaves the canvas (`lineExit`) and where its cap sits (`capPoint`), on
//     hand-placed lines and on seeded random scenes against a slow search written out here;
//   - which way the other card lies and how far, in steps and in screens (`farWay`, `stepRanks`,
//     `stepsText`, `screensText`);
//   - how much of the line the walk keeps with the card (`leadChoices`, `leadBox`, `portStretch`);
//   - every word the bar's line, its tooltip, its accessible name and the live region say.
//
// The scenes are SYNTHETIC: rectangles and polylines placed by hand or by a seeded generator, in a
// canvas of the size the walk leaves of a 541 x 798 px panel (541 x 337 px, the phase index a pill
// in its lower right corner), and a document of seven steps written here, each passed to the rules
// as data. The viewer's own use of these rules is in far-walk.test.mjs.
import test from 'node:test';
import assert from 'node:assert/strict';
import { join } from 'node:path';
import { build } from 'esbuild';
import { lcg, WEBVIEW_ROOT } from './helpers.mjs';

/** The rules and what builds a document's index, as one ES module (nothing touches the DOM on import). */
const far = await build({
  stdin: {
    contents: [
      "export * from './far.ts';",
      "export { normalizeWorkflow } from './workflow.ts';",
      "export { GraphIndex } from './layout/model.ts';",
      "export { claimOrder } from './walk.ts';",
    ].join('\n'),
    resolveDir: join(WEBVIEW_ROOT, 'src'),
    loader: 'ts',
    sourcefile: 'far-entry.ts',
  },
  bundle: true,
  format: 'esm',
  platform: 'neutral',
  write: false,
  logLevel: 'silent',
}).then((result) => import('data:text/javascript;base64,' + Buffer.from(result.outputFiles[0].text).toString('base64')));

/** The walk's canvas in a 541 x 798 px panel, and the phase index's pill on it. */
const AREA = { w: 541, h: 337 };
const PILL = { x: 288, y: 297, w: 241, h: 28 };
/** The canvas as it is: world and canvas pixels are the same. */
const SAME = { x: 0, y: 0, zoom: 1 };
/** Reading size, nothing panned. */
const READING = { x: 0, y: 0, zoom: 0.9 };
/** A card as the layout draws one. */
const card = (id, x, y, extra = {}) => ({ id, x, y, w: 216, h: 72, ...extra });
const round = (p) => (p ? { x: Math.round(p.x * 10) / 10, y: Math.round(p.y * 10) / 10, vertical: p.vertical } : p);

/* ── what is in view, and when a connection is far ───────────────────── */

test('a card is in view when it is whole on the canvas and clear of the phase index, half a pixel of rounding allowed', () => {
  const { inView } = far;
  // 216 x 72 at 90% is 194.4 x 64.8 px.
  assert.equal(inView(card('a', 100, 60), READING, AREA, PILL), true);
  // Cut by each edge of the canvas in turn.
  assert.equal(inView(card('a', -10, 60), READING, AREA, PILL), false, 'left');
  assert.equal(inView(card('a', 100, -10), READING, AREA, PILL), false, 'top');
  assert.equal(inView(card('a', 400, 60), READING, AREA, PILL), false, 'right: 360 + 194.4 is past 541');
  assert.equal(inView(card('a', 100, 310), READING, AREA, PILL), false, 'bottom: 279 + 64.8 is past 337');
  // A card a least pan leaves exactly on the edge is in view; one a pixel further is not.
  const onEdge = { id: 'a', x: 0, y: 0, w: 194.4, h: 64.8 };
  assert.equal(inView(onEdge, { x: 541 - 194.4, y: 0, zoom: 1 }, AREA, null), true);
  assert.equal(inView(onEdge, { x: 541 - 194.4 + 0.5, y: 0, zoom: 1 }, AREA, null), true, 'half a pixel of rounding');
  assert.equal(inView(onEdge, { x: 541 - 194.4 + 0.6, y: 0, zoom: 1 }, AREA, null), false);
  assert.equal(inView(onEdge, { x: -0.5, y: -0.5, zoom: 1 }, AREA, null), true);
  assert.equal(inView(onEdge, { x: -0.6, y: 0, zoom: 1 }, AREA, null), false);
  // Under the phase index a card is out of view, though it is whole on the canvas.
  const low = { id: 'a', x: 300, y: 250, w: 194.4, h: 64.8 };
  assert.equal(inView(low, SAME, AREA, null), true);
  assert.equal(inView(low, SAME, AREA, PILL), false, 'its foot is under the pill');
  // Beside the index, and touching it, is clear of it.
  assert.equal(inView({ id: 'a', x: 288 - 194.4, y: 250, w: 194.4, h: 64.8 }, SAME, AREA, PILL), true);
  assert.equal(inView({ id: 'a', x: 300, y: 297 - 64.8, w: 194.4, h: 64.8 }, SAME, AREA, PILL), true);
});

test('a connection is far while one of its end cards is out of view at the zoom on screen; the bar goes to the end that is out of view, and with both out of view to the far card only while the source card is still partly on the canvas', () => {
  const { farEnd, farGoal, fitsCanvas, isFar, unionOf } = far;
  // Two cards in one column, 522 px apart: at reading size their union is 194 x 535 px.
  const source = card('load', 102, 60);
  const target = card('ckpt', 102, 582);
  const line = [{ x: 210, y: 132 }, { x: 210, y: 582 }];
  const ends = (vp, area = AREA, covered = PILL) => ({
    source: farEnd('source', 'load', source, line, vp, area, covered),
    target: farEnd('target', 'ckpt', target, line, vp, area, covered),
    keep: null,
  });
  const union = unionOf(source, target);
  assert.deepEqual(union, { x: 102, y: 60, w: 216, h: 594 });
  // The view on the source card, as a walk step leaves it.
  const atSource = ends(READING);
  assert.deepEqual([atSource.source.inView, atSource.target.inView], [true, false]);
  assert.deepEqual([atSource.source.drawnId, atSource.target.id, atSource.source.port], ['load', 'ckpt', false]);
  assert.equal(isFar(atSource), true);
  assert.equal(farGoal(atSource), 'target');
  // The view on the far card.
  const atTarget = ends({ x: 0, y: -470, zoom: 0.9 });
  assert.deepEqual([atTarget.source.inView, atTarget.target.inView], [false, true]);
  assert.equal(isFar(atTarget), true);
  assert.equal(farGoal(atTarget), 'source');
  // Between the two, neither card is whole: still far, and the bar goes back to the source.
  const between = ends({ x: 0, y: -250, zoom: 0.9 });
  assert.deepEqual([between.source.inView, between.target.inView], [false, false]);
  assert.deepEqual([between.source.onCanvas, between.target.onCanvas], [false, true], 'the far card is cut by the canvas\'s foot');
  assert.equal(farGoal(between), 'source');
  // Dragged 78 px from the step's picture: 24 px of the source card are cut off at the canvas's top
  // and the far card is still out of sight. The bar still goes to the far card, whether the walk
  // holds the source (a step) or no end (it came by a click), until the source card has left the
  // canvas. From the far end it is the way back that stays.
  const nudged = ends({ x: 0, y: -78, zoom: 0.9 });
  assert.deepEqual([nudged.source.inView, nudged.target.inView, nudged.source.onCanvas, nudged.target.onCanvas], [false, false, true, false]);
  assert.equal(farGoal(nudged), 'target');
  assert.equal(farGoal({ ...nudged, keep: 'source' }), 'target');
  assert.equal(farGoal({ ...nudged, keep: 'target' }), 'source');
  const gone = ends({ x: 0, y: -119, zoom: 0.9 });
  assert.deepEqual([gone.source.onCanvas, farGoal({ ...gone, keep: 'source' })], [false, 'source'], 'the source card is 0.2 px above the canvas');
  // The far card cut off after a look: neither is whole, and the bar goes back to the source.
  const cut = ends({ x: 0, y: -530, zoom: 0.9 });
  assert.deepEqual([cut.source.inView, cut.target.inView, cut.target.onCanvas, farGoal({ ...cut, keep: 'target' })], [false, false, true, 'source']);
  // The same two cards are both in view on the canvas of a 1440 x 900 px panel (1080 x 767 px), and
  // on this one once the view is at 49%: not far, and the bar has nowhere to go.
  assert.equal(fitsCanvas(union, AREA, 0.9, 0), false);
  assert.equal(fitsCanvas(union, { w: 1080, h: 767 }, 0.9, 0), true);
  const tall = ends({ x: 0, y: 100, zoom: 0.9 }, { w: 1080, h: 767 }, null);
  assert.deepEqual([tall.source.inView, tall.target.inView, isFar(tall), farGoal(tall)], [true, true, false, null]);
  // 45% is the least a walk step frames an inferred or unresolved connection at (FRAME_MIN_ZOOM).
  assert.equal(fitsCanvas(union, AREA, 0.45), true, '(337 - 48) / 594 is 0.49');
  const framed = ends({ x: 150, y: 0, zoom: 0.49 }, AREA, null);
  assert.deepEqual([framed.source.inView, framed.target.inView, isFar(framed)], [true, true, false]);
  // A card under the phase index is out of view, so the connection is far at a zoom that holds both.
  const under = ends({ x: 300, y: 0, zoom: 0.49 }, AREA, PILL);
  assert.deepEqual([under.source.inView, under.target.inView, farGoal(under)], [true, false, 'target']);
});

/* ── which way, and how far ──────────────────────────────────────────── */

test('the way to a card is one of eight, from the middle of the canvas; a diagonal only when the card is well off on both axes', () => {
  const { farWay } = far;
  // A point `sx` canvas widths right of the canvas's middle and `sy` heights below it.
  const at = (sx, sy) => farWay({ x: 270.5 + sx * 541, y: 168.5 + sy * 337, w: 0, h: 0 }, SAME, AREA);
  const ways = [
    [2, 0, 0, 'right'], [1, 1, 1, 'down and to the right'], [0, 2, 2, 'down'], [-1, 1, 3, 'down and to the left'],
    [-2, 0, 4, 'left'], [-1, -1, 5, 'up and to the left'], [0, -2, 6, 'up'], [1, -1, 7, 'up and to the right'],
  ];
  for (const [sx, sy, compass, words] of ways) {
    const way = at(sx, sy);
    assert.deepEqual([way.compass, way.words], [compass, words], sx + ', ' + sy);
    assert.equal(Math.round(way.screens * 1000) / 1000, Math.max(Math.abs(sx), Math.abs(sy)), 'screens: the larger of the two');
  }
  // A little to one side is not a diagonal: under half a screen, or under 0.4 of the other axis.
  assert.equal(at(0.3, 2).words, 'down');
  assert.equal(at(0.49, 0.9).words, 'down');
  assert.equal(at(0.6, 2).words, 'down', '0.6 is under 0.4 x 2');
  assert.equal(at(0.9, 2).words, 'down and to the right');
  assert.equal(at(-3, 0.6).words, 'left');
  assert.equal(at(-3, -1.3).words, 'up and to the left');
  // A screen is the canvas at the zoom on screen: at half the zoom the card is fewer screens away.
  const box = card('a', 1500, 60);
  const tenths = (way) => Math.round(way.screens * 10) / 10;
  const reading = farWay(box, READING, AREA);
  assert.deepEqual([reading.words, tenths(reading)], ['right', 2.2], '(1608 x 0.9 - 270.5) / 541');
  assert.equal(tenths(farWay(box, { x: 0, y: 0, zoom: 0.45 }, AREA)), 0.8);
  // Panning changes it; the walk bar prints the distance in steps for that reason.
  assert.equal(tenths(farWay(box, { x: -541, y: 0, zoom: 0.9 }, AREA)), 1.2);
});

/** Data (two steps), Fit (the group "Epoch loop" of two steps) and Save (two steps), listed Fit first. */
function lineDoc() {
  const step = (id, label, phase, extra = {}) => ({ id, label, phase, basis: 'observed', evidence: ['e1'], ...extra });
  const link = (id, source, target, extra = {}) => ({ id, source, target, label: id, basis: 'observed', evidence: ['e1'], ...extra });
  return {
    workflowVersion: '1.0', title: 'Far lines', producer: { kind: 'host-llm', host: 'codex', model: 'm' }, revision: { id: 'l1' },
    request: { question: 'q', scope: 's' },
    phases: [{ id: 'data', label: 'Data' }, { id: 'fit', label: 'Fit' }, { id: 'save', label: 'Save' }],
    nodes: [
      step('loop', 'Epoch loop', 'fit', { kind: 'group', evidence: [] }),
      step('fwd', 'Forward pass', 'fit', { parent: 'loop' }), step('upd', 'Optimizer step', 'fit', { parent: 'loop' }),
      step('load', 'Load batches', 'data'), step('aug', 'Augment', 'data'),
      step('ckpt', 'Write checkpoint', 'save'), step('eval', 'Evaluate', 'save'),
    ],
    edges: [
      link('c-load-ckpt', 'load', 'ckpt'), link('c-load-upd', 'load', 'upd'),
      link('c-aug-fwd', 'aug', 'fwd', { basis: 'inferred' }), link('c-aug-loop', 'aug', 'loop'),
      link('c-loop-eval', 'loop', 'eval'), link('c-fwd-upd', 'fwd', 'upd'),
      link('c-upd-ckpt', 'upd', 'ckpt', { basis: 'unresolved' }),
    ],
    findings: [],
    evidence: [{ id: 'e1', file: 'train.py', line: 3, endLine: 4, quote: 'x()' }],
    coverage: { status: 'scoped', summary: 's', inspectedFiles: ['train.py'], limitations: [] },
  };
}
const indexOf = (document) => new far.GraphIndex(far.normalizeWorkflow(document));

test('the distance in steps is the difference of two places in reading order: lanes in phase order, a group at the place of its first step; it is not the number of j presses', () => {
  const { claimOrder, stepRanks, stepsText } = far;
  const index = indexOf(lineDoc());
  const ranks = stepRanks(index);
  // The document lists Fit first; the reading order starts with the Data lane. The group holds no
  // place of its own: it stands where its first step does.
  assert.deepEqual(Array.from(ranks), [['load', 0], ['aug', 1], ['loop', 2], ['fwd', 2], ['upd', 3], ['ckpt', 4], ['eval', 5]]);
  const between = (a, b) => stepsText(ranks.get(b) - ranks.get(a));
  assert.equal(between('load', 'ckpt'), '4 steps later');
  assert.equal(between('ckpt', 'load'), '4 steps earlier');
  assert.equal(between('aug', 'fwd'), 'next step');
  assert.equal(between('fwd', 'aug'), 'previous step');
  assert.equal(between('aug', 'loop'), 'next step', 'to the group: to its first step');
  assert.equal(between('loop', 'eval'), '3 steps later');
  assert.equal(between('loop', 'fwd'), '', 'no difference, nothing to print');
  assert.deepEqual([stepsText(2), stepsText(-2), stepsText(0), stepsText(120)], ['2 steps later', '2 steps earlier', '', '120 steps later']);
  // The walk stops on connections and on the group too: from the step Load batches to the step
  // Write checkpoint is 12 presses of j, and 4 steps.
  const order = claimOrder(index).map((claim) => claim.kind + ':' + claim.id);
  assert.equal(order.indexOf('node:ckpt') - order.indexOf('node:load'), 12);
});

test('the distance in screens: one decimal under ten, whole numbers from ten, "1 screen" in the singular', () => {
  const { screensText } = far;
  const cases = [[0.04, '0 screens'], [0.6, '0.6 screens'], [0.96, '1 screen'], [1, '1 screen'], [1.04, '1 screen'], [1.06, '1.1 screens'], [2, '2 screens'],
    [3.25, '3.3 screens'], [9.94, '9.9 screens'], [9.95, '10 screens'], [9.96, '10 screens'], [11.2, '11 screens'], [11.5, '12 screens']];
  for (const [screens, text] of cases) assert.equal(screensText(screens), text, String(screens));
});

/* ── where the line leaves the canvas ────────────────────────────────── */

test('a line leaves the canvas where its last stretch in sight ends: through each of the four sides, and through a corner', () => {
  const { lineExit } = far;
  const exit = (points, toward = 'target', vp = SAME, covered = null, cards = []) => round(lineExit(points, vp, AREA, covered, toward, cards));
  assert.deepEqual(exit([{ x: 100, y: 100 }, { x: 800, y: 100 }]), { x: 541, y: 100, vertical: false }, 'the right side');
  assert.deepEqual(exit([{ x: 400, y: 100 }, { x: -300, y: 100 }]), { x: 0, y: 100, vertical: false }, 'the left side');
  assert.deepEqual(exit([{ x: 200, y: 200 }, { x: 200, y: -400 }]), { x: 200, y: 0, vertical: true }, 'the top');
  assert.deepEqual(exit([{ x: 200, y: 100 }, { x: 200, y: 900 }]), { x: 200, y: 337, vertical: true }, 'the bottom');
  // Through the lower right corner itself: the line (100, 100) to (982, 574) passes (541, 337).
  assert.deepEqual(exit([{ x: 100, y: 100 }, { x: 982, y: 574 }]), { x: 541, y: 337, vertical: false }, 'the corner');
  // A line that turns on the canvas's edge and runs out along it leaves at the corner too.
  assert.deepEqual(exit([{ x: 100, y: 100 }, { x: 541, y: 100 }, { x: 541, y: 900 }]), { x: 541, y: 337, vertical: true });
  // Towards the source it is the same line read from its other end.
  assert.deepEqual(exit([{ x: 800, y: 100 }, { x: 100, y: 100 }], 'source'), { x: 541, y: 100, vertical: false });
  assert.deepEqual(exit([{ x: 200, y: 900 }, { x: 200, y: 100 }], 'source'), { x: 200, y: 337, vertical: true });
  // The line is in world coordinates: at 90%, panned 60 px left, (300, 100) to (900, 100) is drawn
  // from (210, 90) to (750, 90).
  assert.deepEqual(exit([{ x: 300, y: 100 }, { x: 900, y: 100 }], 'target', { x: -60, y: 0, zoom: 0.9 }), { x: 541, y: 90, vertical: false });
  // A line that leaves, comes back and leaves again: where it leaves for good.
  assert.deepEqual(exit([{ x: 100, y: 100 }, { x: 700, y: 100 }, { x: 700, y: 200 }, { x: 300, y: 200 }, { x: 300, y: 600 }]), { x: 300, y: 337, vertical: true });
});

test('a line goes out of sight at the phase index and behind a card as it does at an edge; an end in sight has no exit, and neither has a line that is nowhere on the canvas', () => {
  const { lineExit } = far;
  const exit = (points, covered = null, cards = [], toward = 'target') => round(lineExit(points, SAME, AREA, covered, toward, cards));
  // The index's corner of the canvas: the pill, and the strips between it and the right and bottom edges.
  assert.deepEqual(exit([{ x: 100, y: 310 }, { x: 800, y: 310 }], PILL), { x: 287, y: 310, vertical: false }, 'a line that runs under the pill');
  assert.deepEqual(exit([{ x: 400, y: 100 }, { x: 400, y: 900 }], PILL), { x: 400, y: 296, vertical: true }, 'a line that runs down behind it');
  assert.deepEqual(exit([{ x: 100, y: 330 }, { x: 800, y: 330 }], PILL), { x: 287, y: 330, vertical: false }, 'the strip under the pill is its corner too');
  assert.deepEqual(exit([{ x: 535, y: 100 }, { x: 535, y: 900 }], PILL), { x: 535, y: 296, vertical: true }, 'and the strip to its right');
  // A neighbouring card that reaches the canvas's edge: the line is in sight up to a pixel inside
  // the card's border, where a connection's port is drawn.
  const neighbour = { x: 400, y: 60, w: 194, h: 65 };
  assert.deepEqual(exit([{ x: 50, y: 100 }, { x: 800, y: 100 }], null, [neighbour]), { x: 401, y: 100, vertical: false });
  // A card the line passes behind and comes out of: the line leaves at the edge after it.
  assert.deepEqual(exit([{ x: 50, y: 100 }, { x: 800, y: 100 }], null, [{ x: 200, y: 60, w: 194, h: 65 }]), { x: 541, y: 100, vertical: false });
  // That end of the line is in sight: nothing to mark.
  assert.equal(exit([{ x: 100, y: 100 }, { x: 400, y: 100 }]), null);
  assert.equal(exit([{ x: 800, y: 100 }, { x: 400, y: 100 }]), null, 'it comes in from outside and ends on the canvas');
  assert.notEqual(exit([{ x: 800, y: 100 }, { x: 400, y: 100 }], null, [], 'source'), null, 'towards its other end it leaves');
  // An end on its card's border is in sight; an end behind another card is not.
  assert.equal(exit([{ x: 100, y: 100 }, { x: 400, y: 100 }], null, [{ x: 400, y: 60, w: 100, h: 65 }]), null);
  assert.deepEqual(exit([{ x: 100, y: 100 }, { x: 450, y: 100 }], null, [{ x: 400, y: 60, w: 100, h: 65 }]), { x: 401, y: 100, vertical: false });
  // None of the line is on the canvas, or the line is no line.
  assert.equal(exit([{ x: 600, y: 100 }, { x: 900, y: 100 }]), null);
  assert.equal(exit([{ x: -50, y: -50 }, { x: -50, y: 900 }, { x: 900, y: 900 }]), null);
  assert.equal(exit([{ x: 100, y: 100 }]), null);
});

/* ── where the cap sits ──────────────────────────────────────────────── */

/** The rectangle a cap covers: 22 x 14 px along a horizontal stretch, 14 x 22 px along a vertical one. */
const capBox = (at) => (at.vertical ? { x: at.x - 7, y: at.y - 11, w: 14, h: 22 } : { x: at.x - 11, y: at.y - 7, w: 22, h: 14 });
const overlap = (a, b) => Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x) > 0 && Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y) > 0;

test('the cap sits on the line at the place nearest its exit where a whole cap fits: 2 px inside the canvas, 6 px off the phase index, off every card', () => {
  const { CAP_CARD_GAP, CAP_EDGE, CAP_GAP, CAP_LONG, CAP_SHORT, capPoint } = far;
  assert.deepEqual([CAP_LONG, CAP_SHORT, CAP_EDGE, CAP_GAP, CAP_CARD_GAP], [22, 14, 2, 6, 1]);
  const cap = (points, covered = null, cards = [], toward = 'target', vp = SAME) => round(capPoint(points, vp, AREA, covered, toward, cards));
  // Through an edge: the cap lies along the line, its far side 2 px inside that edge.
  assert.deepEqual(cap([{ x: 100, y: 100 }, { x: 800, y: 100 }]), { x: 528, y: 100, vertical: false }, 'right: 541 - 2 - 11');
  assert.deepEqual(cap([{ x: 400, y: 100 }, { x: -300, y: 100 }]), { x: 13, y: 100, vertical: false }, 'left');
  assert.deepEqual(cap([{ x: 200, y: 200 }, { x: 200, y: -400 }]), { x: 200, y: 13, vertical: true }, 'top: upright, 2 + 11');
  assert.deepEqual(cap([{ x: 200, y: 100 }, { x: 200, y: 900 }]), { x: 200, y: 324, vertical: true }, 'bottom: 337 - 2 - 11');
  // Under or behind the phase index: before it, 6 px clear.
  assert.deepEqual(cap([{ x: 100, y: 310 }, { x: 800, y: 310 }], PILL), { x: 270, y: 310, vertical: false }, 'left of the pill: 288 - 6 - 11 - 1');
  assert.deepEqual(cap([{ x: 400, y: 100 }, { x: 400, y: 900 }], PILL), { x: 400, y: 279, vertical: true }, 'above it: 297 - 6 - 11 - 1');
  // Behind a neighbouring card on its way out: before that card, a pixel clear.
  const neighbour = { x: 400, y: 60, w: 194, h: 65 };
  assert.deepEqual(cap([{ x: 50, y: 100 }, { x: 800, y: 100 }], null, [neighbour]), { x: 387, y: 100, vertical: false }, '400 - 1 - 11 - 1');
  // Out from behind a card with room for a cap before the edge: at the edge, where it leaves for good.
  assert.deepEqual(cap([{ x: 50, y: 100 }, { x: 800, y: 100 }], null, [{ x: 200, y: 60, w: 194, h: 65 }]), { x: 528, y: 100, vertical: false });
  // A stub between a card and the edge too short for a cap: on the stretch in sight before that card.
  assert.deepEqual(cap([{ x: 50, y: 100 }, { x: 800, y: 100 }], null, [{ x: 320, y: 60, w: 200, h: 65 }]), { x: 307, y: 100, vertical: false });
  // Leaves, comes back and leaves again: where it leaves for good.
  assert.deepEqual(cap([{ x: 100, y: 100 }, { x: 700, y: 100 }, { x: 700, y: 200 }, { x: 300, y: 200 }, { x: 300, y: 600 }]), { x: 300, y: 324, vertical: true });
  // Out along the canvas's very edge no whole cap fits on the line: at its end, moved the least distance inside.
  assert.deepEqual(cap([{ x: 100, y: 100 }, { x: 541, y: 100 }, { x: 541, y: 900 }]), { x: 532, y: 324, vertical: true }, '541 - 2 - 7, 337 - 2 - 11');
  // Towards the source, and on a line in world coordinates.
  assert.deepEqual(cap([{ x: 800, y: 100 }, { x: 100, y: 100 }], null, [], 'source'), { x: 528, y: 100, vertical: false });
  assert.deepEqual(cap([{ x: 300, y: 100 }, { x: 900, y: 100 }], null, [], 'target', { x: -60, y: 0, zoom: 0.9 }), { x: 528, y: 90, vertical: false });
  // No cap where that end of the line is in sight, or none of the line is.
  assert.equal(cap([{ x: 100, y: 100 }, { x: 400, y: 100 }]), null);
  assert.equal(cap([{ x: 600, y: 100 }, { x: 900, y: 100 }]), null);
  assert.equal(cap([{ x: 100, y: 100 }]), null);
});

/**
 * The canvases of the walk in panels of 541 x 798, 900 x 800, 1440 x 900 and 320 x 798 px, as
 * measured by capture.mjs (`canvasBox`) in a browser.
 */
const CANVASES = [{ w: 541, h: 337 }, { w: 900, h: 318 }, { w: 1080, h: 767 }, { w: 320, h: 311 }];

/**
 * One generated scene, in whole canvas pixels: a canvas, the phase index (none, its pill or its
 * panel of rows, 12 px inside the lower right corner), up to six cards of 194 x 65 px on and
 * around the canvas, and a line of two to six straight runs, each 30 px or longer, that starts on
 * the canvas and ends beyond one of its sides. The viewport is 100% or 50%, panned by whole pixels.
 */
function scene(seed) {
  const rand = lcg(seed);
  const int = (n) => Math.floor(rand() * n);
  const area = CANVASES[int(CANVASES.length)];
  const form = int(3);
  const indexW = Math.min(form === 2 ? 360 : 241, area.w - 24);
  const indexH = form === 2 ? 132 : 28;
  const covered = form === 0 ? null : { x: area.w - 12 - indexW, y: area.h - 12 - indexH, w: indexW, h: indexH };
  const cards = Array.from({ length: int(7) }, () => ({ x: int(area.w + 200) - 150, y: int(area.h + 100) - 60, w: 194, h: 65 }));
  const runs = 2 + int(5);
  let at = { x: 20 + int(area.w - 40), y: 10 + int(area.h - 20) };
  const points = [at];
  let horizontal = int(2) === 0;
  for (let i = 0; i < runs; i++) {
    const last = i === runs - 1;
    const span = horizontal ? area.w : area.h;
    const from = horizontal ? at.x : at.y;
    // The last run ends 40 to 440 px beyond a side; the others anywhere within 300 px of the canvas.
    let to = last ? (int(2) ? span + 40 + int(400) : -40 - int(400)) : int(span + 600) - 300;
    if (Math.abs(to - from) < 30) to = from + (to >= from ? 30 : -30);
    at = horizontal ? { x: to, y: at.y } : { x: at.x, y: to };
    points.push(at);
    horizontal = !horizontal;
  }
  const zoom = int(2) ? 1 : 0.5;
  const vp = { x: int(400) - 200, y: int(400) - 200, zoom };
  // The same line in world coordinates, for the viewport above.
  const world = points.map((p) => ({ x: (p.x - vp.x) / zoom, y: (p.y - vp.y) / zoom }));
  return { area, covered, cards, points, world, vp };
}

/**
 * The rule written out again, slowly: every whole pixel of the line in order, which of them are in
 * sight, and at which of them a whole cap fits. `fit` is the place nearest the line's exit where a
 * cap fits, when there is one within 40 px of it along the line; `any` is whether a cap fits
 * anywhere on the line in sight.
 */
function search({ area, covered, cards, points }) {
  const inside = (p, r) => p.x >= r.x && p.x <= r.x + r.w && p.y >= r.y && p.y <= r.y + r.h;
  const grown = (r, dx, dy) => ({ x: r.x - dx, y: r.y - dy, w: r.w + 2 * dx, h: r.h + 2 * dy });
  const corner = covered ? { x: covered.x, y: covered.y, w: area.w - covered.x, h: area.h - covered.y } : null;
  const seen = (p) => inside(p, { x: 0, y: 0, w: area.w, h: area.h }) && !(corner && inside(p, corner)) && !cards.some((c) => inside(p, grown(c, -1.5, -1.5)));
  const fits = (p) => {
    const half = p.vertical ? { x: 7, y: 11 } : { x: 11, y: 7 };
    return inside(p, { x: half.x + 2, y: half.y + 2, w: area.w - 2 * (half.x + 2), h: area.h - 2 * (half.y + 2) }) &&
      !(corner && inside(p, grown(corner, half.x + 6, half.y + 6))) && !cards.some((c) => inside(p, grown(c, half.x + 1, half.y + 1)));
  };
  const pixels = [];
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1];
    const b = points[i];
    const vertical = a.x === b.x;
    const length = Math.abs(b.x - a.x) + Math.abs(b.y - a.y);
    for (let k = 0; k <= length; k++) pixels.push({ x: a.x + Math.sign(b.x - a.x) * k, y: a.y + Math.sign(b.y - a.y) * k, vertical });
  }
  const end = pixels[pixels.length - 1];
  let exit = -1;
  for (let k = pixels.length - 1; k >= 0 && exit < 0; k--) if (seen(pixels[k])) exit = k;
  if (seen(end) || exit < 0) return { exit: null, fit: null, any: false };
  let fit = null;
  for (let k = exit; k >= 0 && k >= exit - 40 && seen(pixels[k]) && !fit; k--) if (fits(pixels[k])) fit = pixels[k];
  return { exit: pixels[exit], fit, any: pixels.some((p) => seen(p) && fits(p)) };
}

test('on 3,000 generated scenes the cap is never outside the canvas, over the phase index or over a card, and is the nearest fit to the exit that a slow search finds', () => {
  const { capPoint, lineExit } = far;
  const count = { scenes: 0, capped: 0, nearest: 0, roomElsewhere: 0, noRoom: 0, none: 0 };
  for (let seed = 1; seed <= 3000; seed++) {
    const s = scene(seed);
    const where = () => 'scene ' + seed + ': canvas ' + s.area.w + ' x ' + s.area.h + ', index ' + JSON.stringify(s.covered) + ', line ' + JSON.stringify(s.points) + ', cards ' + JSON.stringify(s.cards);
    const expected = search(s);
    const exit = lineExit(s.world, s.vp, s.area, s.covered, 'target', s.cards);
    const cap = capPoint(s.world, s.vp, s.area, s.covered, 'target', s.cards);
    count.scenes++;
    // Where the line leaves, and whether it does.
    assert.deepEqual(round(exit), expected.exit && round(expected.exit), where());
    if (!expected.exit) {
      assert.equal(cap, null, 'no cap without an exit; ' + where());
      count.none++;
      continue;
    }
    if (!cap) {
      // A line in sight with no cap: only where no whole cap fits anywhere on it.
      assert.equal(expected.any, false, 'a cap fits on this line and none was placed; ' + where());
      count.none++;
      continue;
    }
    count.capped++;
    const box = capBox(cap);
    // Inside the canvas by 2 px, whatever the line does.
    assert.ok(box.x >= 2 && box.y >= 2 && box.x + box.w <= s.area.w - 2 && box.y + box.h <= s.area.h - 2, 'a cap outside the canvas at ' + JSON.stringify(round(cap)) + '; ' + where());
    // Off the phase index and the strips beside it, by 6 px.
    if (s.covered) {
      const corner = { x: s.covered.x - 6, y: s.covered.y - 6, w: s.area.w, h: s.area.h };
      assert.equal(overlap(box, corner), false, 'a cap over the phase index at ' + JSON.stringify(round(cap)) + '; ' + where());
    }
    const onCard = s.cards.some((c) => overlap(box, { x: c.x + 0.5, y: c.y + 0.5, w: c.w - 1, h: c.h - 1 }));
    if (expected.fit) {
      // Room within 40 px of the exit: the cap is that place, on the line.
      assert.deepEqual(round(cap), round(expected.fit), where());
      count.nearest++;
    } else if (expected.any) count.roomElsewhere++;
    else count.noRoom++;
    // The cap is on no card: also where the line in sight has no room for one (a stub between a
    // card and the canvas's edge, shorter than a cap), where it goes at the stub's end or middle
    // only if that is clear of every card.
    assert.equal(onCard, false, 'a cap over a card at ' + JSON.stringify(round(cap)) + '; ' + where());
  }
  // Not vacuous: most scenes have a cap at the nearest fit; some lines have room only further
  // back, some have none, and some have no cap.
  assert.ok(count.capped >= 2500 && count.nearest >= 2000, JSON.stringify(count));
  assert.ok(count.roomElsewhere >= 100 && count.noRoom >= 20 && count.none >= 30, JSON.stringify(count));
});

test('a cap is never drawn over a card: a line with only a few pixels in sight between its card and the phase index, or the canvas edge, has none', () => {
  const { capPoint } = far;
  // Canvas pixels at zoom 1. A cap is 22 x 14 px along its line and keeps 2 px from the canvas's
  // edge, 6 px from the phase index and 1 px from a card.
  const vp = { x: 0, y: 0, zoom: 1 };

  // 270 x 74 px with the phase index over its lower half. The line leaves the foot of its card
  // 6 px above the index and runs down behind it: the only room for a cap is on the card.
  const short = { w: 270, h: 74 };
  const index = { x: 12, y: 36, w: 246, h: 28 };
  assert.equal(capPoint([{ x: 140, y: 30 }, { x: 140, y: 2000 }], vp, short, index, 'target', [{ x: 40, y: -60, w: 200, h: 90 }]), null);
  // With the card's foot above the canvas the same line has 36 px in sight and is capped on them.
  const higher = { x: 40, y: -100, w: 200, h: 90 };
  let at = capPoint([{ x: 140, y: -10 }, { x: 140, y: 2000 }], vp, short, index, 'target', [higher]);
  assert.ok(at && at.vertical && at.x === 140, JSON.stringify(at));
  assert.ok(!overlap(capBox(at), higher) && capBox(at).y >= 2 && capBox(at).y + 22 <= index.y - 6, JSON.stringify(at));

  // 270 x 285 px, no index in the way. The line leaves the right side of a card 12 px from the
  // canvas's edge: no cap fits beside the card.
  const narrow = { w: 270, h: 285 };
  const beside = { x: 58, y: 60, w: 200, h: 90 };
  assert.equal(capPoint([{ x: 258, y: 105 }, { x: 3000, y: 105 }], vp, narrow, null, 'target', [beside]), null);
  // 30 px beside the card are room enough.
  const left = { x: 40, y: 60, w: 200, h: 90 };
  at = capPoint([{ x: 240, y: 105 }, { x: 3000, y: 105 }], vp, narrow, null, 'target', [left]);
  assert.ok(at && !at.vertical && at.y === 105, JSON.stringify(at));
  assert.ok(!overlap(capBox(at), left) && capBox(at).x + 22 <= narrow.w - 2, JSON.stringify(at));
  // The same from the other end of the line.
  assert.equal(capPoint([{ x: 3000, y: 105 }, { x: 258, y: 105 }], vp, narrow, null, 'source', [beside]), null);

  // Two cards 20 px apart, the lower one running off the canvas's foot, and the line going down
  // from the upper one behind the lower: what is in sight of it is shorter than a cap, and a cap
  // at its middle would lie on a card.
  const above = { x: 100, y: 40, w: 200, h: 90 };
  const below = { x: 100, y: 150, w: 200, h: 400 };
  assert.equal(capPoint([{ x: 200, y: 130 }, { x: 200, y: 2000 }], vp, { w: 541, h: 337 }, null, 'target', [above, below]), null);
});

/* ── how much of the line the walk keeps with the card ───────────────── */

test('the walk keeps 80 px of an observed line with its card, and up to 240 px of an inferred or unresolved one, counted along the line in sight', () => {
  const { FAR_LEAD_PX, FAR_LEAD_UNCERTAIN_PX, leadBox, leadChoices } = far;
  assert.deepEqual([FAR_LEAD_PX, FAR_LEAD_UNCERTAIN_PX], [80, 240]);
  // Longest first: in sight, then as the line runs. An uncertain line gets three times as much,
  // or two thirds of the canvas's shorter side where that is less (337 x 0.66 is 222).
  assert.deepEqual(leadChoices(false, AREA), [{ px: 80, inSight: true }, { px: 80, inSight: false }]);
  assert.deepEqual(leadChoices(true, AREA), [{ px: 222, inSight: true }, { px: 80, inSight: true }, { px: 80, inSight: false }]);
  assert.deepEqual(leadChoices(true, { w: 1080, h: 767 }).map((lead) => lead.px), [240, 80, 80]);
  assert.deepEqual(leadChoices(true, { w: 270, h: 74 }).map((lead) => lead.px), [49, 80, 80]);

  const source = card('a', 100, 100);
  // The line leaves the card's right side and turns down after 40 px.
  const line = [{ x: 316, y: 136 }, { x: 356, y: 136 }, { x: 356, y: 600 }];
  const r = (box) => ({ x: Math.round(box.x * 10) / 10, y: Math.round(box.y * 10) / 10, w: Math.round(box.w * 10) / 10, h: Math.round(box.h * 10) / 10 });
  // 80 px at 100%: 40 px along and 40 px down, with the card.
  assert.deepEqual(r(leadBox(line, 'source', source, 80, 1)), { x: 100, y: 100, w: 256, h: 76 });
  // At 90% the same 80 px on screen is 88.9 px of the line; at 45%, 177.8 px.
  assert.deepEqual(r(leadBox(line, 'source', source, 80, 0.9)), { x: 100, y: 100, w: 256, h: 84.9 });
  assert.deepEqual(r(leadBox(line, 'source', source, 80, 0.45)), { x: 100, y: 100, w: 256, h: 173.8 });
  // The stretch alone, for an end too large for the canvas.
  assert.deepEqual(r(leadBox(line, 'source', source, 80, 1, { withCard: false })), { x: 316, y: 136, w: 40, h: 40 });
  // From the target card the line is read from its other end.
  const target = card('b', 248, 600);
  assert.deepEqual(r(leadBox(line, 'target', target, 80, 1)), { x: 248, y: 520, w: 216, h: 152 });
  // No lead, or no line: the card.
  assert.deepEqual(leadBox(line, 'source', source, 0, 1), source);
  assert.deepEqual(leadBox(null, 'source', source, 80, 1), source);
  assert.deepEqual(leadBox([{ x: 316, y: 136 }], 'source', source, 80, 1), source);

  // In sight: a stretch behind another card is taken into the box and not counted, so the reader
  // sees the line come out again. Here it runs 24 px, then 216 px behind a neighbour.
  const straight = [{ x: 316, y: 136 }, { x: 1200, y: 136 }];
  const neighbour = card('n', 340, 100);
  const asItRuns = leadBox(straight, 'source', source, 80, 1);
  assert.equal(asItRuns.x + asItRuns.w, 396, '80 px as the line runs ends behind the neighbour');
  const inSight = leadBox(straight, 'source', source, 80, 1, { behind: [neighbour] });
  // 24 px before the neighbour and 56 px after it, counted two pixels at a time.
  assert.ok(Math.abs(inSight.x + inSight.w - (556 + 56)) <= 2, 'ends ' + (inSight.x + inSight.w) + ', 56 px past the neighbour at 556');
});

test('an end too large for the canvas at reading size is in view by the place its line meets it; only a group is called one', () => {
  const { farEnd, farIdleText, inView, isFar, meetBox, portBox, portStretch } = far;
  // An open group of 1976 x 218 px, as the layout draws one around seven steps in a row. Its line
  // leaves its foot 988 px from its left edge and runs down.
  const group = { id: 'loop', x: 102, y: 248, w: 1976, h: 218, headerH: 34 };
  const line = [{ x: 1090, y: 466 }, { x: 1090, y: 534 }, { x: 210, y: 534 }, { x: 210, y: 582 }];
  // A card that fits has no such stretch.
  assert.equal(portStretch(line, 'source', card('a', 982, 394), 0.9, AREA), null);
  // The group does not fit at 90%: the first 80 px of its line at the zoom on screen stands for it.
  assert.deepEqual(portStretch(line, 'source', group, 1, AREA), { x: 1078, y: 466, w: 12, h: 68 });
  assert.deepEqual(portStretch(line, 'source', group, 0.5, AREA), { x: 998, y: 466, w: 92, h: 68 }, '160 px of the line at 50%');
  // What the walk reveals of it: that stretch with 24 px of room on screen.
  assert.deepEqual(portBox(line, 'source', group, 1, AREA), { x: 1054, y: 442, w: 60, h: 116 });
  assert.equal(portBox(line, 'source', card('a', 982, 394), 1, AREA), null);
  assert.equal(portStretch(null, 'source', group, 1, AREA), null, 'a line that is not drawn');
  // The same place of any card, also one that fits (what the walk shows of a group that fits the
  // canvas but leaves no room for its line): the 80 px of the line next to the card, with 24 px.
  assert.deepEqual(meetBox(line, 'source', group, 1), { x: 1054, y: 442, w: 60, h: 116 });
  assert.deepEqual(meetBox([{ x: 100, y: 0 }, { x: 100, y: 394 }], 'target', card('a', 982, 394), 1), { x: 76, y: 290, w: 48, h: 128 });
  assert.equal(meetBox(null, 'target', group, 1), null);
  // The group is "in view" when that stretch is, though its box runs off the canvas on both sides.
  const vp = { x: -800, y: -300, zoom: 1 };
  assert.equal(inView(group, vp, AREA, null), false);
  const end = farEnd('source', 'loop', group, line, vp, AREA, null);
  assert.deepEqual([end.inView, end.port, end.drawnId], [true, true, 'loop']);
  assert.equal(farEnd('source', 'loop', group, line, { x: 0, y: 0, zoom: 1 }, AREA, null).inView, false);
  // With its other end in view too the bar speaks of the line, not of two cards.
  const target = farEnd('target', 'ckpt', card('ckpt', 1000, 560), [{ x: 1090, y: 466 }, { x: 1090, y: 560 }], vp, AREA, null);
  assert.equal(target.inView, true);
  assert.equal(farIdleText({ source: end, target, keep: 'source' }), 'Line in view end to end');
  assert.equal(farIdleText({ source: { ...end, byLine: false, port: false }, target, keep: 'source' }), 'Both ends in view');
  assert.equal(farIdleText({ source: end, target: { ...target, inView: false }, keep: 'source' }), '', 'nothing while an end is out of view');
  assert.equal(isFar({ source: end, target, keep: 'source' }), false);
  // The same when it is the far card that is too large: a connection that ends at such a group.
  const wide = { w: 1080, h: 767 };
  const down = [{ x: 208, y: 132 }, { x: 208, y: 400 }];
  const from = farEnd('source', 'aug', card('aug', 100, 60), down, { x: 0, y: 0, zoom: 0.9 }, wide, null);
  const into = farEnd('target', 'loop', { id: 'loop', x: 102, y: 400, w: 1976, h: 900, headerH: 34 }, down, { x: 0, y: 0, zoom: 0.9 }, wide, null);
  assert.deepEqual([from.inView, from.byLine, into.inView, into.byLine, into.port], [true, false, true, true, true]);
  assert.equal(farIdleText({ source: from, target: into, keep: 'source' }), 'Line in view end to end');
  assert.equal(far.inViewAnnouncement({ source: from, target: into, keep: 'source' }), 'The line of this connection is in view end to end.');
  // On a canvas shorter than a card a step's card is too large as well: it is in view by its
  // stretch of line, and it is no group.
  const short = { w: 270, h: 53 };
  const step = card('opts', 102, 60);
  assert.notEqual(portStretch([{ x: 210, y: 132 }, { x: 210, y: 400 }], 'source', step, 0.9, short), null);
  assert.equal(farEnd('source', 'opts', step, [{ x: 210, y: 132 }, { x: 210, y: 400 }], { x: 0, y: -100, zoom: 0.9 }, short, null).port, false);
  // Two such cards side by side, 59 px apart, each cut off by the canvas: the line between them is
  // in view end to end, and the bar says that. It does not say that both cards are in view.
  const tiny = { w: 270, h: 74 };
  const left = card('best', -37, 20, { h: 103 });
  const right = card('save', 238, 20, { h: 103 });
  const between = [{ x: 179, y: 60 }, { x: 238, y: 60 }];
  const at = { x: 0, y: -18, zoom: 0.9 };
  const pair = { source: farEnd('source', 'best', left, between, at, tiny, null), target: farEnd('target', 'save', right, between, at, tiny, null), keep: null };
  assert.deepEqual([inView(left, at, tiny, null), inView(right, at, tiny, null)], [false, false], 'precondition: neither card is whole on the canvas');
  assert.deepEqual([pair.source.inView, pair.target.inView, pair.source.byLine, pair.target.byLine, pair.source.port], [true, true, true, true, false]);
  assert.equal(isFar(pair), false);
  assert.equal(farIdleText(pair), 'Line in view end to end');
  assert.equal(far.inViewAnnouncement(pair), 'The line of this connection is in view end to end.');
  assert.equal(far.inViewAnnouncement({ source: end, target, keep: 'source' }), 'The line of this connection is in view end to end.');
  // Two cards that fit the canvas and are whole on it.
  const whole = { source: farEnd('source', 'a', card('a', 20, 20), [{ x: 236, y: 56 }, { x: 290, y: 56 }], SAME, AREA, null), target: farEnd('target', 'b', card('b', 290, 20), [{ x: 236, y: 56 }, { x: 290, y: 56 }], SAME, AREA, null), keep: null };
  assert.deepEqual([whole.source.byLine, whole.target.byLine, farIdleText(whole), far.inViewAnnouncement(whole)], [false, false, 'Both ends in view', 'Both ends of this connection are in view.']);
});

test('"Line in view end to end" is said only of a line that is: with a stretch of it off the canvas or under the phase index the bar speaks of its two ends', () => {
  const { farEnd, farIdleText, lineInView } = far;
  // A line from a group larger than the canvas that leaves the canvas between its two ends: down
  // its left side, under the canvas's foot and back up to a step. Both of its ends are in view.
  const vp = { x: 0, y: 0, zoom: 1 };
  const group = { id: 'loop', x: 60, y: 20, w: 1976, h: 150, headerH: 34 };
  const step = card('sched', 60, 200, { h: 60 });
  const route = [{ x: 60, y: 120 }, { x: 30, y: 120 }, { x: 30, y: 420 }, { x: 160, y: 420 }, { x: 160, y: 260 }];
  const ends = (points, lineCut) => ({ source: farEnd('source', 'loop', group, points, vp, AREA, PILL), target: farEnd('target', 'sched', step, points, vp, AREA, PILL), keep: null, fits: true, together: false, lineCut });
  let shown = ends(route, !lineInView(route, vp, AREA, PILL));
  assert.deepEqual([shown.source.inView, shown.source.byLine, shown.target.inView, shown.lineCut], [true, true, true, true]);
  assert.equal(farIdleText(shown), 'Both ends of the line in view');
  assert.equal(far.inViewAnnouncement(shown), 'Both ends of the line of this connection are in view.');
  // The same two ends joined on the canvas.
  const direct = [{ x: 60, y: 120 }, { x: 30, y: 120 }, { x: 30, y: 230 }, { x: 60, y: 230 }];
  shown = ends(direct, !lineInView(direct, vp, AREA, PILL));
  assert.deepEqual([shown.source.inView, shown.target.inView, shown.lineCut], [true, true, false]);
  assert.equal(farIdleText(shown), 'Line in view end to end');
  assert.equal(far.inViewAnnouncement(shown), 'The line of this connection is in view end to end.');
  // Of two cards the bar says that both are in view, whatever their line does on the way.
  assert.equal(farIdleText({ ...shown, source: { ...shown.source, byLine: false, port: false }, lineCut: true }), 'Both ends in view');

  // On the canvas from end to end, half a pixel of rounding allowed at its edges.
  assert.equal(lineInView([{ x: 0, y: 10 }, { x: AREA.w, y: 10 }, { x: AREA.w, y: AREA.h }], vp, AREA, null), true);
  assert.equal(lineInView([{ x: -0.4, y: 10 }, { x: 100, y: 10 }], vp, AREA, null), true);
  assert.equal(lineInView([{ x: -1, y: 10 }, { x: 100, y: 10 }], vp, AREA, null), false);
  assert.equal(lineInView([{ x: 10, y: 10 }, { x: 10, y: AREA.h + 1 }, { x: 60, y: AREA.h + 1 }, { x: 60, y: 10 }], vp, AREA, null), false, 'a bend under the canvas\'s foot');
  // The viewport applies: the same line zoomed out, and panned off.
  assert.equal(lineInView([{ x: 10, y: 10 }, { x: 1000, y: 10 }], { x: 0, y: 0, zoom: 0.5 }, AREA, null), true);
  assert.equal(lineInView([{ x: 10, y: 10 }, { x: 1000, y: 10 }], { x: 60, y: 0, zoom: 0.5 }, AREA, null), false);
  // Under the phase index: a stretch that passes through it, between two ends that are clear of it.
  const through = [{ x: PILL.x - 40, y: PILL.y + 10 }, { x: PILL.x + 40, y: PILL.y + 10 }, { x: PILL.x + 40, y: PILL.y - 60 }];
  assert.equal(lineInView(through, vp, AREA, PILL), false);
  assert.equal(lineInView(through, vp, AREA, null), true);
  assert.equal(lineInView([{ x: PILL.x - 40, y: PILL.y + 10 }, { x: PILL.x + PILL.w + 5, y: PILL.y + 10 }], vp, AREA, PILL), false, 'straight through it');
  // Along its edge, or past its corner, is not under it.
  assert.equal(lineInView([{ x: PILL.x - 40, y: PILL.y }, { x: PILL.x + 100, y: PILL.y }], vp, AREA, PILL), true);
  assert.equal(lineInView([{ x: PILL.x - 30, y: PILL.y + 10 }, { x: PILL.x + 10, y: PILL.y - 30 }], vp, AREA, PILL), true);
  // A line that is not drawn is not in view.
  assert.equal(lineInView(null, vp, AREA, null), false);
  assert.equal(lineInView([{ x: 10, y: 10 }], vp, AREA, null), false);
});

/* ── what the walk bar's line says ───────────────────────────────────── */

/** How a line is drawn when it is lit in its phase tone and observed. */
const LIT = { tone: '2', severity: null, lit: true, basis: 'observed' };

/**
 * Both ends of connection `id` of `lineDoc`, its source card at `from` and its target card at `to`
 * (world coordinates), joined by one straight line, as a 541 x 337 px canvas shows them through `vp`.
 */
function endsOf(index, id, from, to, vp, drawnAs = {}) {
  const edge = index.edgeById.get(id);
  const source = card(drawnAs.source || edge.source, from.x, from.y);
  const target = card(drawnAs.target || edge.target, to.x, to.y);
  const line = [{ x: source.x + 108, y: source.y + 36 }, { x: target.x + 108, y: target.y + 36 }];
  return {
    source: far.farEnd('source', edge.source, source, line, vp, AREA, PILL),
    target: far.farEnd('target', edge.target, target, line, vp, AREA, PILL),
    keep: 'source',
  };
}
/** Everything said of a far line: what the bar prints, its accessible name, its tooltip and the walk's extra sentence. */
function said(line) {
  return { text: far.farLineText(line), name: far.farLineName(line), tooltip: far.farLineTitle(line), announcement: far.farAnnouncement(line) };
}

test('an observed far connection, its other card below, above, to the right and to the left: the words of the line, its name, its tooltip and the announcement', () => {
  const { farLine, stepRanks } = far;
  const index = indexOf(lineDoc());
  const ranks = stepRanks(index);
  const here = { x: 100, y: 60 };

  // Load batches (phase 1) to Write checkpoint (phase 3), 940 px straight down. The view on the source.
  let ends = endsOf(index, 'c-load-ckpt', here, { x: 100, y: 1000 }, READING);
  let line = farLine(index, 'c-load-ckpt', ends, ranks, LIT);
  assert.deepEqual([line.end, line.atFar, line.compass, line.way, line.screens, line.steps, line.basis, line.drawnBasis], ['target', false, 2, 'down', '2.3 screens', '4 steps later', undefined, undefined]);
  assert.deepEqual([line.tone, line.severity, line.lit], ['2', null, true], 'how its line is drawn, for the copy of the cap');
  assert.deepEqual(said(line), {
    text: { tag: '', verb: 'Go to', title: 'Write checkpoint', distance: '4 steps later', phase: 'phase 3' },
    name: 'Go to the far end: Write checkpoint, 4 steps later, off screen below, in phase 3, Save',
    tooltip: 'Write checkpoint. Phase 3, Save. About 2.3 screens down. Click, Enter or key o goes there; the same again comes back. The walk stays on this claim.',
    announcement: 'Its far end is out of view, 4 steps later, in phase 3, Save, about 2.3 screens down. o goes there and back.',
  });
  // The description adds to the name only what the name lacks: the screens and how the line is
  // used. The card's title and its phase, which the tooltip prints, are not said a second time.
  assert.equal(far.farLineDescription(line), 'About 2.3 screens down. Click, Enter or key o goes there; the same again comes back. The walk stays on this claim.');
  assert.doesNotMatch(far.farLineDescription(line), /Write checkpoint|Save|phase/i);
  // The same connection with the view on its far card: the line goes back, and the source is above.
  ends = endsOf(index, 'c-load-ckpt', here, { x: 100, y: 1000 }, { x: 0, y: -800, zoom: 0.9 });
  line = farLine(index, 'c-load-ckpt', ends, ranks, LIT);
  assert.deepEqual([line.end, line.atFar, line.compass, line.way, line.screens, line.steps], ['source', true, 6, 'up', '2.6 screens', '4 steps earlier']);
  assert.deepEqual(said(line), {
    text: { tag: '', verb: 'Back to', title: 'Load batches', distance: '4 steps earlier', phase: 'phase 1' },
    name: 'Back to the source: Load batches, 4 steps earlier, off screen above, in phase 1, Data',
    tooltip: 'Load batches. Phase 1, Data. About 2.6 screens up. Click, Enter or key o goes back. The walk stays on this claim.',
    announcement: 'Its source is out of view, 4 steps earlier, in phase 1, Data, about 2.6 screens up. o goes back.',
  });
  assert.equal(far.farLineDescription(line), 'About 2.6 screens up. Click, Enter or key o goes back. The walk stays on this claim.');
  assert.doesNotMatch(far.farLineDescription(line), /Load batches|Data|phase/i);

  // Forward pass to Optimizer step, both in phase 2, 1,400 px to the right: no phase to print.
  ends = endsOf(index, 'c-fwd-upd', here, { x: 1500, y: 60 }, READING);
  line = farLine(index, 'c-fwd-upd', ends, ranks, LIT);
  assert.deepEqual([line.end, line.atFar, line.compass, line.phase], ['target', false, 0, undefined]);
  assert.deepEqual(said(line), {
    text: { tag: '', verb: 'Go to', title: 'Optimizer step', distance: 'next step', phase: '' },
    name: 'Go to the far end: Optimizer step, next step, off screen to the right',
    tooltip: 'Optimizer step. About 2.2 screens right. Click, Enter or key o goes there; the same again comes back. The walk stays on this claim.',
    announcement: 'Its far end is out of view, next step, about 2.2 screens right. o goes there and back.',
  });
  ends = endsOf(index, 'c-fwd-upd', here, { x: 1500, y: 60 }, { x: -1250, y: 0, zoom: 0.9 });
  line = farLine(index, 'c-fwd-upd', ends, ranks, LIT);
  assert.deepEqual([line.end, line.atFar, line.compass], ['source', true, 4]);
  assert.deepEqual(said(line), {
    text: { tag: '', verb: 'Back to', title: 'Forward pass', distance: 'previous step', phase: '' },
    name: 'Back to the source: Forward pass, previous step, off screen to the left',
    tooltip: 'Forward pass. About 2.5 screens left. Click, Enter or key o goes back. The walk stays on this claim.',
    announcement: 'Its source is out of view, previous step, about 2.5 screens left. o goes back.',
  });

  // With both cards on the canvas there is no line: its place says so.
  ends = endsOf(index, 'c-load-ckpt', here, { x: 340, y: 60 }, READING);
  assert.deepEqual([ends.source.inView, ends.target.inView], [true, true]);
  assert.equal(farLine(index, 'c-load-ckpt', ends, ranks, LIT), null);
  assert.equal(far.farIdleText(ends), 'Both ends in view');
  // A step the ranks do not hold: the line prints the screens in place of the steps.
  line = farLine(index, 'c-load-ckpt', endsOf(index, 'c-load-ckpt', here, { x: 100, y: 1000 }, READING), new Map(), LIT);
  assert.equal(far.farLineText(line).distance, '2.3 screens');
  assert.equal(far.farAnnouncement(line), 'Its far end is out of view, in phase 3, Save, about 2.3 screens down. o goes there and back.');
});

test('two cards that fit the canvas together are not far apart: a source the reader moved out of view is a card to go to, and it is the way back from the far end only once a look has been there', () => {
  const { farLine, farLineText, fitsCanvas, stepRanks, unionOf } = far;
  const index = indexOf(lineDoc());
  const ranks = stepRanks(index);
  // Forward pass and Optimizer step side by side, 24 px apart: their union is 410 px wide at
  // reading size, on a canvas of 541 px.
  const from = { x: 100, y: 60 };
  const to = { x: 340, y: 60 };
  assert.equal(fitsCanvas(unionOf(card('fwd', from.x, from.y), card('upd', to.x, to.y)), AREA, 0.9, 0), true);
  const ends = (vp, keep, fits) => ({ ...endsOf(index, 'c-fwd-upd', from, to, vp), keep, fits });
  const where = (line) => [line.end, line.back, line.atFar, farLineText(line).verb];
  // As a step shows them: both in view, and no line.
  assert.equal(farLine(index, 'c-fwd-upd', ends(READING, null, true), ranks, LIT), null);

  // Panned 100 px to the left: the source card is cut off by 10 px and the far card is whole.
  const cut = { x: -100, y: 0, zoom: 0.9 };
  let shown = ends(cut, null, true);
  assert.deepEqual([shown.source.inView, shown.source.onCanvas, shown.target.inView], [false, true, true]);
  let line = farLine(index, 'c-fwd-upd', shown, ranks, LIT);
  assert.deepEqual(where(line), ['source', false, false, 'Go to']);
  assert.deepEqual(said(line), {
    text: { tag: '', verb: 'Go to', title: 'Forward pass', distance: 'previous step', phase: '' },
    name: 'Go to the source: Forward pass, previous step, partly in view to the left',
    tooltip: 'Forward pass. Click, Enter or key o goes there. The walk stays on this claim.',
    announcement: 'Its source is partly in view, previous step, to the left. o goes there.',
  });
  assert.equal(far.farLineDescription(line), 'Click, Enter or key o goes there. The walk stays on this claim.');
  // The same whichever end the view holds, but the far one: a step that kept the source, a look back at it.
  assert.deepEqual(where(farLine(index, 'c-fwd-upd', ends(cut, 'source', true), ranks, LIT)), ['source', false, false, 'Go to']);
  // Panned on until the source card has left the canvas: still a card to go to, and no far end.
  const gone = { x: -300, y: 0, zoom: 0.9 };
  shown = ends(gone, null, true);
  assert.deepEqual([shown.source.onCanvas, shown.target.inView], [false, true]);
  assert.deepEqual(where(farLine(index, 'c-fwd-upd', shown, ranks, LIT)), ['source', false, false, 'Go to']);
  // With neither card in view the line goes to the source first, as a card to go to.
  shown = ends({ x: -700, y: 0, zoom: 0.9 }, null, true);
  assert.deepEqual([shown.source.inView, shown.target.inView], [false, false]);
  assert.deepEqual(where(farLine(index, 'c-fwd-upd', shown, ranks, LIT)), ['source', false, false, 'Go to']);

  // After a look at the far end (key o, the line, a cap, an arrow) the same picture is the far
  // end, and the source the way back.
  line = farLine(index, 'c-fwd-upd', ends(cut, 'target', true), ranks, LIT);
  assert.deepEqual(where(line), ['source', true, true, 'Back to']);
  assert.equal(far.farLineName(line), 'Back to the source: Forward pass, previous step, partly in view to the left');
  assert.equal(far.farLineDescription(line), 'Click, Enter or key o goes back. The walk stays on this claim.');
  assert.equal(far.farAnnouncement(line), 'Its source is partly in view, previous step, to the left. o goes back.');
  // And so it is on two cards that do not fit the canvas together once the source card has left
  // the canvas, whatever the view holds.
  for (const keep of [null, 'source', 'target']) assert.deepEqual(where(farLine(index, 'c-fwd-upd', ends(gone, keep, false), ranks, LIT)), ['source', true, true, 'Back to'], String(keep));
  // While some of the source card is on the canvas (a notch of zoom or a few pixels of pan cut it
  // off) it is a card to go to on such a connection too, until a look has been to the far end.
  for (const keep of [null, 'source']) assert.deepEqual(where(farLine(index, 'c-fwd-upd', ends(cut, keep, false), ranks, LIT)), ['source', false, false, 'Go to'], String(keep));
  assert.deepEqual(where(farLine(index, 'c-fwd-upd', ends(cut, 'target', false), ranks, LIT)), ['source', true, true, 'Back to']);
  // The rule itself, for either end: the end the view holds, or the one in view of two cards that
  // do not fit once the other card has left the canvas.
  const { atEnd } = far;
  const farCut = { x: 150, y: 0, zoom: 0.9 };
  const farGone = { x: 250, y: 0, zoom: 0.9 };
  assert.deepEqual([ends(farCut, null, false).target.onCanvas, ends(farGone, null, false).target.onCanvas, ends(farGone, null, false).source.inView], [true, false, true]);
  for (const fits of [true, false]) {
    assert.equal(atEnd(ends(cut, 'target', fits), 'target'), true, 'held far end, fits ' + fits);
    assert.equal(atEnd(ends(farCut, 'source', fits), 'source'), true, 'held source, fits ' + fits);
    for (const keep of [null, 'source']) assert.equal(atEnd(ends(cut, keep, fits), 'target'), false, 'source cut off, ' + keep + ', fits ' + fits);
    for (const keep of [null, 'target']) assert.equal(atEnd(ends(farCut, keep, fits), 'source'), false, 'far card cut off, ' + keep + ', fits ' + fits);
    for (const keep of [null, 'source']) assert.equal(atEnd(ends(gone, keep, fits), 'target'), !fits, 'source gone, ' + keep + ', fits ' + fits);
    for (const keep of [null, 'target']) assert.equal(atEnd(ends(farGone, keep, fits), 'source'), !fits, 'far card gone, ' + keep + ', fits ' + fits);
  }

  // The far card moved out of view is named as on any connection.
  shown = ends({ x: 150, y: 0, zoom: 0.9 }, null, true);
  assert.deepEqual([shown.source.inView, shown.target.inView], [true, false]);
  line = farLine(index, 'c-fwd-upd', shown, ranks, LIT);
  assert.deepEqual(where(line), ['target', false, false, 'Go to']);
  assert.equal(far.farLineName(line), 'Go to the far end: Optimizer step, next step, partly in view to the right');
  assert.equal(far.farLineDescription(line), 'Click, Enter or key o goes there; the same again comes back. The walk stays on this claim.');
  // Where some pan shows both cards, pressing the line shows the two together: nothing is said of
  // a way back, by the tooltip or by the walk's announcement.
  line = farLine(index, 'c-fwd-upd', { ...shown, together: true }, ranks, LIT);
  assert.equal(far.farLineDescription(line), 'Click, Enter or key o goes there. The walk stays on this claim.');
  assert.equal(far.farAnnouncement(line), 'Its far end is partly in view, next step, to the right. o goes there.');
  // The same of a far card that has left the canvas: the screens are given, and no way back.
  line = farLine(index, 'c-fwd-upd', { ...ends({ x: 300, y: 0, zoom: 0.9 }, null, true), together: true }, ranks, LIT);
  assert.equal(far.farLineName(line), 'Go to the far end: Optimizer step, next step, off screen to the right');
  assert.equal(far.farLineDescription(line), 'About 0.8 screens right. Click, Enter or key o goes there. The walk stays on this claim.');
  assert.equal(far.farAnnouncement(line), 'Its far end is out of view, next step, about 0.8 screens right. o goes there.');
  // A source that is a group too large for the canvas at reading size, on a diagram zoomed out
  // until it fits: the place its line leaves it is a place to go to.
  assert.equal(farLineText({ ...line, end: 'source', port: true, back: false }).verb, 'Go to its start at');
  assert.equal(farLineText({ ...line, end: 'source', port: true, back: true }).verb, 'Back to its start at');
});

test('a card that is partly on the canvas lies beside the connection\'s other card: its way is taken from that card, and the line says "partly in view" on that side, with no screens', () => {
  const { farEnd, farLine, farWay, stepRanks } = far;
  const index = indexOf(lineDoc());
  const ranks = stepRanks(index);
  const vp = { x: 0, y: 0, zoom: 1 };
  const line = (source, target) => [{ x: source.x + source.w, y: source.y + 36 }, { x: target.x, y: target.y + 36 }];
  /** Both ends as `FarView.ends` gives them: the way of an end that is in sight and not in view is taken from the other card. */
  const endsOf = (source, target) => {
    const points = line(source, target);
    const s = farEnd('source', 'fwd', source, points, vp, AREA, PILL);
    const t = farEnd('target', 'upd', target, points, vp, AREA, PILL);
    const beside = (end, box, other, from) => (!end.inView && end.seen && other.onCanvas ? { ...end, way: farWay(box, vp, AREA, from) } : end);
    return { source: beside(s, source, t, target), target: beside(t, target, s, source), keep: null, fits: true, together: true, lineCut: false };
  };

  // Two neighbours in the top row of the canvas, the far one cut by 4 px at the canvas's right
  // edge. From the canvas's middle its centre is under half a screen off either way, and further
  // up than to the right: "up".
  let source = card('fwd', 85, 12);
  let target = card('upd', 329, 12);
  assert.deepEqual([farWay(target, vp, AREA).words, farWay(target, vp, AREA, source).words], ['up', 'right']);
  assert.equal(farWay(target, vp, AREA, source).screens, farWay(target, vp, AREA).screens, 'the screens are counted from the middle either way');
  let shown = endsOf(source, target);
  assert.deepEqual([shown.source.inView, shown.target.inView, shown.target.onCanvas], [true, false, true]);
  let said = farLine(index, 'c-fwd-upd', shown, ranks, LIT);
  assert.deepEqual([said.end, said.compass, said.way, said.partly], ['target', 0, 'right', true]);
  assert.equal(far.farLineName(said), 'Go to the far end: Optimizer step, next step, partly in view to the right');
  assert.equal(far.farLineTitle(said), 'Optimizer step. Click, Enter or key o goes there. The walk stays on this claim.');
  assert.equal(far.farAnnouncement(said), 'Its far end is partly in view, next step, to the right. o goes there.');

  // The far card whole on the canvas beside the source, its lower corner under the phase index.
  // From the canvas's middle it lies down; the reader sees it to the right of the source.
  source = card('fwd', 40, 232);
  target = card('upd', 284, 232);
  assert.deepEqual([target.y + target.h <= AREA.h, target.y + target.h - PILL.y], [true, 7], 'precondition: whole on the canvas, 7 px under the index');
  assert.deepEqual([farWay(target, vp, AREA).words, farWay(target, vp, AREA, source).words], ['down', 'right']);
  shown = endsOf(source, target);
  assert.deepEqual([shown.source.inView, shown.target.inView, shown.target.onCanvas], [true, false, true]);
  said = farLine(index, 'c-fwd-upd', shown, ranks, LIT);
  assert.deepEqual([said.compass, said.partly], [0, true]);
  assert.equal(far.farLineName(said), 'Go to the far end: Optimizer step, next step, partly in view to the right');

  // The source card cut off at the canvas's left edge, the far card in view: to the left.
  source = card('fwd', -10, 12);
  target = card('upd', 234, 12);
  said = farLine(index, 'c-fwd-upd', endsOf(source, target), ranks, LIT);
  assert.deepEqual([said.end, said.compass, said.partly], ['source', 4, true]);
  assert.equal(far.farLineName(said), 'Go to the source: Forward pass, previous step, partly in view to the left');
  // One card above the other: the way is up or down, whichever edge cuts the card.
  source = card('fwd', 330, 20);
  target = card('upd', 300, 150);
  assert.deepEqual([farWay(source, vp, AREA, target).words, farWay(target, vp, AREA, source).words], ['up', 'down']);

  // A card that has left the canvas is off screen, its way and its screens from the canvas's middle.
  source = card('fwd', 85, 12);
  target = card('upd', 600, 12);
  shown = endsOf(source, target);
  assert.deepEqual([shown.target.onCanvas, shown.target.way.words], [false, 'right']);
  said = farLine(index, 'c-fwd-upd', { ...shown, together: false }, ranks, LIT);
  assert.equal(said.partly, undefined);
  assert.equal(far.farLineName(said), 'Go to the far end: Optimizer step, next step, off screen to the right');
  assert.equal(far.farLineDescription(said), 'About 0.8 screens right. Click, Enter or key o goes there; the same again comes back. The walk stays on this claim.');
  // An open group larger than the canvas is named by the place its line meets it: never "partly in view".
  assert.equal(far.farLineName({ ...said, port: true, partly: undefined }), 'Go to its end at the group Optimizer step, next step, off screen to the right');
});

test('a card that lies wholly under the phase index is on the canvas and cannot be seen: the line says "off screen" and gives the screens, not "partly in view"', () => {
  const { farEnd, farLine, stepRanks } = far;
  const index = indexOf(lineDoc());
  const ranks = stepRanks(index);
  const vp = { x: 0, y: 0, zoom: 1 };
  // The phase index open as a list of 360 x 228 px, 12 px inside the canvas's lower right corner.
  const LIST = { x: 169, y: 97, w: 360, h: 228 };
  const source = card('fwd', 20, 12);
  const endsOf = (target, covered) => {
    const points = [{ x: source.x + 108, y: source.y + source.h }, { x: target.x + 108, y: target.y }];
    return { source: farEnd('source', 'fwd', source, points, vp, AREA, covered), target: farEnd('target', 'upd', target, points, vp, AREA, covered), keep: 'source', fits: true, together: false, lineCut: false };
  };
  const seen = (target, covered) => { const end = endsOf(target, covered).target; return [end.inView, end.onCanvas, end.seen]; };

  // The far card, 216 x 72 px, with the list over all of it.
  const under = card('upd', 250, 200);
  assert.deepEqual(seen(under, LIST), [false, true, false]);
  const line = farLine(index, 'c-fwd-upd', endsOf(under, LIST), ranks, LIT);
  assert.deepEqual([line.end, line.partly, line.way, line.screens], ['target', undefined, 'down', '0.2 screens']);
  assert.deepEqual(said(line), {
    text: { tag: '', verb: 'Go to', title: 'Optimizer step', distance: 'next step', phase: '' },
    name: 'Go to the far end: Optimizer step, next step, off screen below',
    tooltip: 'Optimizer step. About 0.2 screens down. Click, Enter or key o goes there; the same again comes back. The walk stays on this claim.',
    announcement: 'Its far end is out of view, next step, about 0.2 screens down. o goes there and back.',
  });
  // The same card with the index a pill under it, and with no index: whole in view.
  assert.deepEqual([seen(under, PILL), seen(under, null)], [[true, true, true], [true, true, true]]);

  // With some of the card clear of the list it is partly in view: 10 px of it above the list,
  // 10 px to its left, 6 px under its foot, and a card the canvas's right edge cuts, in the 12 px
  // beside the list.
  for (const [what, partly] of [['above', card('upd', 250, 87)], ['to the left', card('upd', 159, 200)], ['under its foot', card('upd', 250, 259)], ['past the right edge', card('upd', 330, 200)]]) {
    assert.deepEqual(seen(partly, LIST), [false, true, true], what);
    assert.equal(farLine(index, 'c-fwd-upd', endsOf(partly, LIST), ranks, LIT).partly, true, what);
  }
  // Half a pixel of rounding: a card whose top is 0.4 px above the list is under it.
  assert.deepEqual([seen(card('upd', 250, 96.6), LIST)[2], seen(card('upd', 250, 96.4), LIST)[2]], [false, true]);
  // A card that has left the canvas is neither.
  assert.deepEqual(seen(card('upd', 250, 400), LIST), [false, false, false]);
});

test('an inferred and an unresolved far connection are called that first, in the line, its name and its tooltip; an observed one on a line drawn dashed is not', () => {
  const { farLine, stepRanks } = far;
  const index = indexOf(lineDoc());
  const ranks = stepRanks(index);
  // Augment (phase 1) to Forward pass (phase 2), inferred: below and to the right.
  let line = farLine(index, 'c-aug-fwd', endsOf(index, 'c-aug-fwd', { x: 100, y: 60 }, { x: 900, y: 700 }, READING), ranks, { ...LIT, basis: 'inferred' });
  assert.deepEqual([line.basis, line.drawnBasis, line.compass], ['inferred', 'inferred', 1]);
  assert.deepEqual(said(line), {
    text: { tag: 'inferred', verb: 'Go to', title: 'Forward pass', distance: 'next step', phase: 'phase 2' },
    name: 'inferred connection. Go to the far end: Forward pass, next step, off screen below and to the right, in phase 2, Fit',
    tooltip: 'Inferred connection. Forward pass. Phase 2, Fit. About 1.5 screens down and to the right. Click, Enter or key o goes there; the same again comes back. The walk stays on this claim.',
    announcement: 'Its far end is out of view, next step, in phase 2, Fit, about 1.5 screens down and to the right. o goes there and back.',
  });
  // Optimizer step (phase 2) to Write checkpoint (phase 3), unresolved, seen from its far end: the
  // source is above and to the left.
  line = farLine(index, 'c-upd-ckpt', endsOf(index, 'c-upd-ckpt', { x: 100, y: 60 }, { x: 900, y: 700 }, { x: -640, y: -500, zoom: 0.9 }), ranks, { ...LIT, basis: 'unresolved' });
  assert.deepEqual([line.basis, line.drawnBasis, line.end, line.atFar, line.compass], ['unresolved', 'unresolved', 'source', true, 5]);
  assert.deepEqual(said(line), {
    text: { tag: '? unresolved', verb: 'Back to', title: 'Optimizer step', distance: 'previous step', phase: 'phase 2' },
    name: '? unresolved connection. Back to the source: Optimizer step, previous step, off screen above and to the left, in phase 2, Fit',
    tooltip: 'Unresolved connection. Optimizer step. Phase 2, Fit. About 1.7 screens up and to the left. Click, Enter or key o goes back. The walk stays on this claim.',
    announcement: 'Its source is out of view, previous step, in phase 2, Fit, about 1.7 screens up and to the left. o goes back.',
  });
  // An observed connection that shares its line with an inferred one: the copy of the cap takes
  // the line's dash (`drawnBasis`); no word calls the connection inferred.
  line = farLine(index, 'c-load-ckpt', endsOf(index, 'c-load-ckpt', { x: 100, y: 60 }, { x: 100, y: 1000 }, READING), ranks, { ...LIT, basis: 'inferred' });
  assert.deepEqual([line.basis, line.drawnBasis], [undefined, 'inferred']);
  assert.equal(far.farLineText(line).tag, '');
  assert.doesNotMatch(far.farLineName(line) + far.farLineTitle(line) + far.farAnnouncement(line), /inferred/i);
  assert.deepEqual([far.isUncertain('inferred'), far.isUncertain('unresolved'), far.isUncertain('observed'), far.isUncertain(null), far.isUncertain(undefined)], [true, true, false, false, false]);
});

test('a far end inside a folded group, and an end that is a group larger than the canvas: the line names the card the reader will find', () => {
  const { farLine, lookAnnouncement, stepRanks } = far;
  const index = indexOf(lineDoc());
  const ranks = stepRanks(index);
  // Load batches to Optimizer step, whose group the reader folded: the group's card is drawn for it.
  let ends = endsOf(index, 'c-load-upd', { x: 100, y: 60 }, { x: 100, y: 1000 }, READING, { target: 'loop' });
  assert.deepEqual([ends.target.id, ends.target.drawnId], ['upd', 'loop']);
  let line = farLine(index, 'c-load-upd', ends, ranks, LIT);
  assert.equal(line.folded, 'Epoch loop');
  assert.deepEqual(said(line), {
    text: { tag: '', verb: 'Go to folded group', title: 'Epoch loop', distance: '3 steps later', phase: 'phase 2' },
    name: 'Go to folded group Epoch loop, which holds the far end, Optimizer step, 3 steps later, off screen below, in phase 2, Fit',
    tooltip: 'Optimizer step (inside the folded group Epoch loop, which stays folded). Phase 2, Fit. About 2.3 screens down. Click, Enter or key o goes there; the same again comes back. The walk stays on this claim.',
    announcement: 'Its far end is out of view, 3 steps later, in phase 2, Fit, about 2.3 screens down, inside Epoch loop, which is folded. o goes there and back.',
  });
  assert.equal(lookAnnouncement(index, 'c-load-upd', ends, 'target'), 'Far end of this connection: Optimizer step, inside the folded group Epoch loop. o goes back to Load batches.');

  // Augment to the open group Epoch loop, too large for the canvas: the line goes to the place
  // the connection meets the group's border, since the group's name may be on the canvas already.
  const group = { id: 'loop', x: 102, y: 900, w: 1976, h: 218, headerH: 34 };
  const points = [{ x: 208, y: 132 }, { x: 208, y: 900 }];
  const toGroup = (vp) => ({
    source: far.farEnd('source', 'aug', card('aug', 100, 60), points, vp, AREA, PILL),
    target: far.farEnd('target', 'loop', group, points, vp, AREA, PILL),
    keep: 'source',
  });
  ends = toGroup(READING);
  assert.deepEqual([ends.target.port, ends.target.inView], [true, false]);
  line = farLine(index, 'c-aug-loop', ends, ranks, LIT);
  assert.equal(line.port, true);
  assert.deepEqual([far.farLineText(line).verb, far.farLineText(line).title], ['Go to its end at', 'Epoch loop']);
  assert.equal(far.farLineName(line), 'Go to its end at the group Epoch loop, next step, off screen below, in phase 2, Fit');
  // From the group, seen from the far card: back to the place the line leaves it.
  const out = [{ x: 1090, y: 1118 }, { x: 1090, y: 2000 }];
  const fromGroup = {
    source: far.farEnd('source', 'loop', group, out, { x: -700, y: -1700, zoom: 0.9 }, AREA, PILL),
    target: far.farEnd('target', 'eval', card('eval', 982, 2000), out, { x: -700, y: -1700, zoom: 0.9 }, AREA, PILL),
    keep: 'target',
  };
  assert.deepEqual([fromGroup.source.inView, fromGroup.target.inView], [false, true]);
  line = farLine(index, 'c-loop-eval', fromGroup, ranks, LIT);
  assert.deepEqual([far.farLineText(line).verb, far.farLineText(line).distance], ['Back to its start at', '3 steps earlier']);
  assert.equal(far.farLineName(line), 'Back to its start at the group Epoch loop, 3 steps earlier, off screen above, in phase 2, Fit');
});

test('an open group too large for the canvas is never "partly in view": with its card on the canvas and the place its line meets it off the canvas, the line says "off screen" and gives the screens to that place', () => {
  const { farEnd, farLine, stepRanks } = far;
  const index = indexOf(lineDoc());
  const ranks = stepRanks(index);
  // Augment to the open group Epoch loop, 1976 x 218 px, under it. The line runs to the right
  // above the group and meets its top 988 px from its left edge.
  const group = { id: 'loop', x: 102, y: 248, w: 1976, h: 218, headerH: 34 };
  const points = [{ x: 208, y: 132 }, { x: 208, y: 190 }, { x: 1090, y: 190 }, { x: 1090, y: 248 }];
  const ends = {
    source: farEnd('source', 'aug', card('aug', 100, 60), points, READING, AREA, PILL),
    target: farEnd('target', 'loop', group, points, READING, AREA, PILL),
    keep: 'source',
  };
  // At reading size the group's left end, with its header, is on the canvas under the source
  // card; the place the line meets it is 1.3 screens to the right of the canvas's middle.
  assert.deepEqual([ends.source.inView, ends.target.port, ends.target.inView, ends.target.onCanvas, ends.target.seen], [true, true, false, true, true]);
  const line = farLine(index, 'c-aug-loop', ends, ranks, LIT);
  assert.deepEqual([line.end, line.port, line.partly], ['target', true, undefined]);
  assert.deepEqual(said(line), {
    text: { tag: '', verb: 'Go to its end at', title: 'Epoch loop', distance: 'next step', phase: 'phase 2' },
    name: 'Go to its end at the group Epoch loop, next step, off screen to the right, in phase 2, Fit',
    tooltip: 'Epoch loop. Phase 2, Fit. About 1.3 screens right. Click, Enter or key o goes there; the same again comes back. The walk stays on this claim.',
    announcement: 'Its far end is out of view, next step, in phase 2, Fit, about 1.3 screens right. o goes there and back.',
  });
  // The same from the far card back to such a group, as the source.
  const out = [{ x: 1090, y: 248 }, { x: 1090, y: 190 }, { x: 208, y: 190 }, { x: 208, y: 132 }];
  const back = {
    source: farEnd('source', 'loop', group, out, READING, AREA, PILL),
    target: farEnd('target', 'eval', card('eval', 100, 60), out, READING, AREA, PILL),
    keep: 'target',
  };
  assert.deepEqual([back.target.inView, back.source.port, back.source.inView, back.source.seen], [true, true, false, true]);
  const way = farLine(index, 'c-loop-eval', back, ranks, LIT);
  assert.deepEqual([way.end, way.port, way.partly], ['source', true, undefined]);
  assert.match(far.farLineName(way), /^Back to its start at the group Epoch loop, .*, off screen to the right/);
  assert.doesNotMatch(far.farLineName(way) + far.farLineTitle(way) + far.farAnnouncement(way), /partly in view/);
});

/* ── what the live region says ───────────────────────────────────────── */

test('after a look the live region names the end the view is at and, at the far end, the way back; an arrow towards the end in view and key o on a near connection say so', () => {
  const { atEndAnnouncement, BOTH_ENDS_IN_VIEW, capTitle, lookAnnouncement } = far;
  const index = indexOf(lineDoc());
  const ends = (id) => endsOf(index, id, { x: 100, y: 60 }, { x: 100, y: 1000 }, READING);
  assert.equal(lookAnnouncement(index, 'c-load-ckpt', ends('c-load-ckpt'), 'target'), 'Far end of this connection: Write checkpoint. o goes back to Load batches.');
  assert.equal(lookAnnouncement(index, 'c-load-ckpt', ends('c-load-ckpt'), 'source'), 'Back at the source of this connection: Load batches.');
  // An inferred or unresolved connection is called that at both ends.
  assert.equal(lookAnnouncement(index, 'c-aug-fwd', ends('c-aug-fwd'), 'target'), 'Far end of this inferred connection: Forward pass. o goes back to Augment.');
  assert.equal(lookAnnouncement(index, 'c-aug-fwd', ends('c-aug-fwd'), 'source'), 'Back at the source of this inferred connection: Augment.');
  assert.equal(lookAnnouncement(index, 'c-upd-ckpt', ends('c-upd-ckpt'), 'target'), 'Far end of this unresolved connection: Write checkpoint. o goes back to Optimizer step.');
  assert.equal(lookAnnouncement(index, 'c-upd-ckpt', ends('c-upd-ckpt'), 'source'), 'Back at the source of this unresolved connection: Optimizer step.');
  assert.equal(atEndAnnouncement('source'), 'This is where the connection starts.');
  assert.equal(atEndAnnouncement('target'), 'This is the far end of the connection.');
  assert.equal(BOTH_ENDS_IN_VIEW, 'Both ends of this connection are in view.');
  // The cap's own tooltip: it carries no words on the canvas.
  assert.equal(capTitle('Write checkpoint', ends('c-load-ckpt').target.way), 'This connection continues to Write checkpoint, 2.3 screens down. Click, or key o, to go there.');
});
