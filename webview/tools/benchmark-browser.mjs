import { BENCHMARK_SIZES, benchmarkFeatures, benchmarkWorkflow } from './benchmark-model.mjs';

const results = document.getElementById('results');
const status = document.getElementById('status');
const runButton = document.getElementById('run');
const copyButton = document.getElementById('copy');
const metadataElement = document.getElementById('metadata');
const jsonElement = document.getElementById('json');
let report = null;

const paint = () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
async function measured(action) {
  const start = performance.now();
  const value = action();
  await paint();
  return { ms: performance.now() - start, value };
}
function bridge() {
  const posted = [];
  let listener;
  return { host: 'vscode', theme: 'light', capabilities: { canOpenSource: true, canReanalyze: false, canExport: true, canAskAssistant: false }, posted,
    post(message) { posted.push(message); }, onMessage(callback) { listener = callback; return () => { listener = undefined; }; }, send(message) { listener?.(message); }, saveState() {}, loadState() { return null; } };
}
function cell(row, value) { const td = document.createElement('td'); td.textContent = value; row.appendChild(td); }
function representedIds(host) { return new Set([...host.querySelectorAll('[data-node-id]')].map((element) => element.getAttribute('data-node-id'))); }
function assertNodes(host, fixture, stage) {
  const ids = representedIds(host);
  if (ids.size !== fixture.nodes.length) throw new Error(`${stage}: represented ${ids.size}/${fixture.nodes.length} node IDs`);
  for (const node of fixture.nodes) if (!ids.has(node.id)) throw new Error(`${stage}: missing ${node.id}`);
}

async function run(size) {
  const host = document.getElementById('host');
  const fixture = benchmarkWorkflow(size);
  const wire = bridge();
  const mount = await measured(() => window.MLView.mountWorkflow(host, fixture, wire));
  const app = mount.value;
  assertNodes(host, fixture, 'mount');
  const select = await measured(() => app.focusNode(`node-${Math.floor(size / 2)}`, { center: false, pulse: false }));
  const target = fixture.nodes.find((node) => node.parent);
  const scope = await measured(() => app.setScope(`unit:${target.label}`, { depth: 1 }));
  if (app.getScope().nodes !== 5) throw new Error(`scope: expected 5 nodes, got ${app.getScope().nodes}`);
  const reset = await measured(() => app.setScope(null));
  if (app.getScope().nodes !== size) throw new Error(`reset: expected ${size} nodes, got ${app.getScope().nodes}`);
  assertNodes(host, fixture, 'reset');
  const postedBefore = wire.posted.length;
  const exportSvg = await measured(() => wire.send({ v: 1, type: 'requestExport', kind: 'svg', scope: 'all' }));
  const exported = wire.posted.slice(postedBefore).find((message) => message.type === 'exportFile' && message.kind === 'svg');
  if (!exported?.base64) throw new Error('export: no SVG exportFile payload');
  const update = benchmarkWorkflow(size, 'synthetic-r2');
  const changed = await measured(() => app.setWorkflow(update));
  assertNodes(host, update, 'update');
  const elements = host.querySelectorAll('*').length;
  const liveHeapAfterUpdateMiB = performance.memory ? performance.memory.usedJSHeapSize / 1048576 : null;
  const dispose = await measured(() => app.destroy());
  if (host.childElementCount) throw new Error(`dispose: ${host.childElementCount} rendered children remain`);
  return { size, features: benchmarkFeatures(fixture), mount: mount.ms, select: select.ms, scope: scope.ms, reset: reset.ms, exportSvg: exportSvg.ms, update: changed.ms, dispose: dispose.ms, elements,
    exportBytes: Math.floor(exported.base64.length * 3 / 4), liveHeapAfterUpdateMiB };
}

runButton.addEventListener('click', async () => {
  runButton.disabled = true; copyButton.disabled = true; results.textContent = ''; jsonElement.value = ''; status.textContent = 'Running…';
  const metadata = {
    generatedAt: new Date().toISOString(),
    browser: navigator.userAgent,
    viewportCssPixels: { width: innerWidth, height: innerHeight, devicePixelRatio },
    diagramViewportCssPixels: { width: document.getElementById('host').clientWidth, height: document.getElementById('host').clientHeight },
    timing: 'Frame-inclusive elapsed through two requestAnimationFrame callbacks; this does not guarantee that browser paint completed.',
    heap: performance.memory ? 'Browser live JS heap sampled immediately after revision update; not total or peak memory.' : 'performance.memory unavailable in this browser.',
  };
  metadataElement.textContent = JSON.stringify(metadata, null, 2);
  document.getElementById('host').scrollIntoView({ block: 'start' });
  await paint();
  const samples = [];
  try {
    for (const size of BENCHMARK_SIZES) {
      status.textContent = `Running ${size} nodes…`;
      const sample = await run(size);
      samples.push(sample);
      const row = document.createElement('tr');
      [sample.size, sample.mount, sample.select, sample.scope, sample.reset, sample.exportSvg, sample.update, sample.dispose, sample.elements, sample.liveHeapAfterUpdateMiB]
        .forEach((value, index) => cell(row, index > 0 && index < 8 ? value.toFixed(1) : value === null ? 'unavailable' : String(Math.round(value))));
      results.appendChild(row);
    }
    report = { metadata, samples };
    jsonElement.value = JSON.stringify(report, null, 2);
    copyButton.disabled = false;
    status.textContent = 'Complete. Times are frame-inclusive through two animation-frame callbacks; paint completion is not guaranteed.';
  } catch (error) { status.textContent = String(error?.stack || error); }
  finally { runButton.disabled = false; }
});

copyButton.addEventListener('click', async () => {
  if (!report) return;
  await navigator.clipboard.writeText(JSON.stringify(report, null, 2));
  status.textContent = 'Benchmark JSON copied.';
});
