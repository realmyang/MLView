import assert from 'node:assert/strict';
import test from 'node:test';
import { benchmarkFeatures, benchmarkWorkflow, BENCHMARK_SIZES } from '../tools/benchmark-model.mjs';
import { loadBundle, recordingBridge } from './helpers.mjs';

test('benchmark fixtures are deterministic and include all scale features', () => {
  assert.deepEqual(BENCHMARK_SIZES, [100, 500, 1000, 2000]);
  for (const size of BENCHMARK_SIZES) {
    const first = benchmarkWorkflow(size);
    assert.deepEqual(first, benchmarkWorkflow(size));
    assert.equal(first.nodes.length, size);
    assert.equal(first.coverage.status, 'partial');
    assert.match(first.coverage.limitations[0], /no semantic meaning/);
    const features = benchmarkFeatures(first);
    for (const key of ['groups', 'nested', 'cycles', 'longLabels', 'findings', 'evidence']) assert.ok(features[key] > 0, `${size}: ${key}`);
  }
});

test('100-node benchmark mount represents every authored node and disposes cleanly', async () => {
  const { dom, window, document, MLView } = await loadBundle();
  const root = document.getElementById('mlview-root');
  const fixture = benchmarkWorkflow(100);
  const app = MLView.mountWorkflow(root, fixture, recordingBridge(window));
  const ids = new Set([...root.querySelectorAll('[data-node-id]')].map((element) => element.getAttribute('data-node-id')));
  assert.equal(ids.size, fixture.nodes.length);
  for (const node of fixture.nodes) assert.ok(ids.has(node.id), node.id);
  app.destroy();
  assert.equal(root.childElementCount, 0);
  dom.window.close();
});
