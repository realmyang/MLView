#!/usr/bin/env node
import { performance } from 'node:perf_hooks';
import { benchmarkFeatures, benchmarkWorkflow, BENCHMARK_SIZES } from './benchmark-model.mjs';
import { loadBundle, recordingBridge } from '../test/helpers.mjs';

const requested = process.argv.slice(2).filter((x) => /^\d+$/.test(x)).map(Number);
const sizes = requested.length ? requested : BENCHMARK_SIZES;
const rounds = Math.max(1, Number(process.env.MLVIEW_BENCH_ROUNDS || 1));

function elapsed(action) {
  const start = performance.now();
  const value = action();
  return { ms: performance.now() - start, value };
}

function memory() {
  const value = process.memoryUsage();
  return { heapUsedMiB: value.heapUsed / 1048576, heapTotalMiB: value.heapTotal / 1048576, rssMiB: value.rss / 1048576 };
}

function representedIds(root) {
  return new Set([...root.querySelectorAll('[data-node-id]')].map((element) => element.getAttribute('data-node-id')));
}

async function runOne(size) {
  if (globalThis.gc) globalThis.gc();
  const before = memory();
  const { dom, window, document, MLView } = await loadBundle();
  const root = document.getElementById('mlview-root');
  const bridge = recordingBridge(window);
  const fixture = benchmarkWorkflow(size);
  const mount = elapsed(() => MLView.mountWorkflow(root, fixture, bridge));
  const app = mount.value;
  const ids = representedIds(root);
  if (ids.size !== size) throw new Error(`hidden truncation: represented ${ids.size}/${size} node IDs`);
  for (const node of fixture.nodes) if (!ids.has(node.id)) throw new Error(`hidden truncation: missing ${node.id}`);
  const select = elapsed(() => app.focusNode(`node-${Math.max(Math.floor(size / 2), Math.floor(size / 20))}`, { center: false, pulse: false }));
  const scopeTarget = fixture.nodes.find((node) => node.parent) || fixture.nodes.at(-1);
  const scope = elapsed(() => app.setScope(`unit:${scopeTarget.label}`, { depth: 1 }));
  const scoped = app.getScope();
  const reset = elapsed(() => app.setScope(null));
  const postedBefore = bridge.posted.length;
  const exportSvg = elapsed(() => bridge.send({ v: 1, type: 'requestExport', kind: 'svg', scope: 'all' }));
  const exportMessage = bridge.posted.slice(postedBefore).find((message) => message.type === 'exportFile');
  if (!exportMessage || !exportMessage.base64) throw new Error('SVG export did not produce an exportFile payload');
  const updated = benchmarkWorkflow(size, 'synthetic-r2');
  updated.nodes.at(-1).label += ' updated';
  const update = elapsed(() => app.setWorkflow(updated));
  const domElements = root.querySelectorAll('*').length;
  const afterUpdate = memory();
  const dispose = elapsed(() => app.destroy());
  if (root.childElementCount !== 0) throw new Error('dispose left rendered children behind');
  dom.window.close();
  if (globalThis.gc) globalThis.gc();
  const afterDispose = memory();
  return {
    size,
    features: benchmarkFeatures(fixture),
    timingsMs: { mount: mount.ms, select: select.ms, scope: scope.ms, reset: reset.ms, exportSvg: exportSvg.ms, update: update.ms, dispose: dispose.ms },
    scopeNodes: scoped.nodes,
    domElements,
    exportBytes: Math.floor(exportMessage.base64.length * 3 / 4),
    memoryMiB: { before, afterUpdate, afterDispose },
  };
}

const samples = [];
for (const size of sizes) for (let round = 1; round <= rounds; round++) samples.push({ round, ...(await runOne(size)) });
process.stdout.write(JSON.stringify({
  metadata: {
    generatedAt: new Date().toISOString(),
    runtime: `Node ${process.version}`,
    platform: `${process.platform}/${process.arch}`,
    engine: 'jsdom synchronous DOM; excludes browser style/layout/paint and VS Code webview overhead',
    gcExposed: !!globalThis.gc,
    rounds,
  },
  samples,
}, null, 2) + '\n');
