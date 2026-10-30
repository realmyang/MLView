// The headers that the separation pass (`layout/separate.ts`) reads a run against.
//
// A moved run may not newly lie along a lane or group header, nor for longer within 4 px under a
// header's lower edge (`stripsOf`). The pass does not read every header of the drawing for every
// offset that a run or its neighbour tries; that work would grow with every lane and group. It
// picks out, once for each cable, the headers a horizontal run of the cable can reach
// (`headersNear`: a run stays within 40 px of where it was routed), and reads those. The drawing
// must be the one that reading every header would give.
//
// Checked here, on one hand-made cable: a header within reach of a run refuses a move, also among
// thousands that are out of reach, by its strip and by its lower edge; a header out of reach, or
// in reach but not over the run, changes nothing. The scene is SYNTHETIC. Whole drawings are held
// by the digests of `geometry-golden.test.mjs` and by the header cases of
// `exception-tracks.test.mjs`.
import test from 'node:test';
import assert from 'node:assert/strict';
import { join } from 'node:path';
import { build } from 'esbuild';
import { WEBVIEW_ROOT } from './helpers.mjs';

/** The pass as one ES module, compiled from the sources (nothing touches the DOM on import). */
const { separateExceptions } = await build({
  stdin: {
    contents: "export { separateExceptions } from './layout/separate.ts';",
    resolveDir: join(WEBVIEW_ROOT, 'src'),
    loader: 'ts',
    sourcefile: 'separate-headers-entry.ts',
  },
  bundle: true,
  format: 'esm',
  platform: 'neutral',
  write: false,
  logLevel: 'silent',
}).then((result) => import('data:text/javascript;base64,' + Buffer.from(result.outputFiles[0].text).toString('base64')));

const pt = (x, y) => ({ x, y });
const env = (headers) => ({ boxes: new Map(), hits: () => 0, cardsRead: () => 0, headers, outlines: [], bandsLeft: 0, width: 1e7, height: 1e7 });

test('a header a run can reach still refuses a move, among thousands it cannot reach, and one out of reach changes nothing', () => {
  // One uncertain cable of five runs, its ends on no card (so they stay), the first run at y = 300
  // and the last at y = 900; its middle run, at y = 600 over x 1100..1300, lies on a stack of fixed
  // strokes 2 px apart that reaches `reach` px either side, so the nearest clear places are 8 px
  // past the stack's two ends, and of two that cost the same the upper one is taken.
  const cable = () => [{ source: 's', target: 't', points: [pt(1000, 300), pt(1100, 300), pt(1100, 600), pt(1300, 600), pt(1300, 900), pt(1400, 900)] }];
  const stack = (reach) => {
    const out = [];
    for (let d = -reach; d <= reach; d += 2) out.push([pt(1150, 600 + d), pt(1250, 600 + d)]);
    return out;
  };
  const middleAt = (reach, headers) => {
    const moving = cable();
    const out = separateExceptions(env(headers), stack(reach), moving);
    assert.deepEqual([out[0][0], out[0][5]], [pt(1000, 300), pt(1400, 900)], 'the ends stay');
    assert.equal(out[0][2].y, out[0][3].y);
    return out[0][2].y;
  };
  const strip = (y, h, x = 1150) => ({ x, y, w: 100, h });
  // Headers 4,400 px and more below the middle run, 2,000 of them, 30 px apart.
  const far = (n) => Array.from({ length: n }, (_, i) => strip(5000 + 30 * i, 20));

  // The stack reaches 18 px: the run goes 26 px up, to y = 574.
  assert.equal(middleAt(18, []), 574);
  // A header strip over y 560..580 holds that place, 20 px from where the run was routed: refused, so 26 px down.
  assert.equal(middleAt(18, [strip(560, 20)]), 626);
  // The same strip among 2,000 headers out of reach, in the middle of the list.
  assert.equal(middleAt(18, [...far(1000), strip(560, 20), ...far(1000)]), 626);
  assert.equal(middleAt(18, far(2000)), 574);
  // A tall strip that starts 200 px above the run and ends in its reach.
  assert.equal(middleAt(18, [strip(400, 180)]), 626);
  // A strip the run cannot reach (y 500..520), and one in reach that is not over the run (x 1400..1500).
  assert.equal(middleAt(18, [strip(500, 20)]), 574);
  assert.equal(middleAt(18, [strip(560, 20, 1400)]), 574);

  // The stack reaches 32 px: the run goes the whole 40 px up, to y = 560. A header whose lower
  // edge is at y = 558, 42 px from where the run was routed, has it within 4 px under that edge.
  assert.equal(middleAt(32, []), 560);
  assert.equal(middleAt(32, [strip(538, 20)]), 640);
  assert.equal(middleAt(32, [...far(1000), strip(538, 20), ...far(1000)]), 640);
  // 10 px under the edge is clear of it.
  assert.equal(middleAt(32, [strip(530, 20)]), 560);
});
