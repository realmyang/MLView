// Deterministic, synthetic WorkflowDocuments for renderer performance work.
// These fixtures exercise shape and scale only. They make no semantic claims
// about a real program and must not be used as evaluation examples.

export const BENCHMARK_SIZES = Object.freeze([100, 500, 1000, 2000]);

export function benchmarkWorkflow(nodeCount, revision = 'synthetic-r1') {
  if (!Number.isInteger(nodeCount) || nodeCount < 20) throw new Error('nodeCount must be an integer >= 20');
  const phases = Array.from({ length: 8 }, (_, i) => ({ id: `phase-${i}`, label: `Synthetic phase ${i}` }));
  const groupCount = Math.max(2, Math.floor(nodeCount / 20));
  const nodes = [];
  for (let i = 0; i < groupCount; i++) {
    nodes.push({
      id: `group-${i}`,
      label: `Synthetic group ${i}`,
      phase: phases[i % phases.length].id,
      basis: 'unresolved',
      evidence: [],
    });
  }
  for (let i = groupCount; i < nodeCount; i++) {
    const long = i % 7 === 0 ? ' with a deliberately long label segment repeated for clipping and layout pressure' : '';
    nodes.push({
      id: `node-${i}`,
      label: `Synthetic operation ${i}${long}`,
      phase: phases[i % phases.length].id,
      parent: i < groupCount * 4 ? `group-${i % groupCount}` : undefined,
      basis: i % 9 === 0 ? 'inferred' : 'observed',
      evidence: [`evidence-${i}`],
    });
  }
  const edges = [];
  for (let i = 1; i < nodeCount; i++) {
    edges.push({
      id: `edge-${i}`,
      source: nodes[i - 1].id,
      target: nodes[i].id,
      label: i % 11 === 0 ? `synthetic transfer ${i} with a long edge label` : `transfer ${i}`,
      kind: i % 5 === 0 ? 'control' : 'data',
      basis: i >= groupCount ? 'observed' : 'unresolved',
      evidence: i >= groupCount ? [`evidence-${i}`] : [],
    });
    if (i > 10 && i % 19 === 0) {
      edges.push({
        id: `cycle-${i}`,
        source: nodes[i].id,
        target: nodes[i - 9].id,
        label: `synthetic cycle ${i}`,
        kind: 'control',
        basis: i >= groupCount ? 'inferred' : 'unresolved',
        evidence: i >= groupCount ? [`evidence-${i}`] : [],
      });
    }
  }
  const evidence = [];
  for (let i = groupCount; i < nodeCount; i++) {
    evidence.push({ id: `evidence-${i}`, file: `synthetic/module-${i % 32}.py`, line: i + 1, endLine: i + 1, quote: `synthetic_operation_${i}()` });
  }
  const findings = [];
  for (let i = groupCount; i < nodeCount; i += 10) {
    findings.push({
      id: `finding-${i}`,
      title: `Synthetic finding ${i}`,
      message: `Synthetic renderer-load finding attached to node ${i}; no semantic claim.`,
      severity: ['low', 'medium', 'high'][i % 3],
      nodeIds: [`node-${i}`],
      edgeIds: i ? [`edge-${i}`] : [],
      basis: 'unresolved',
      evidence: [`evidence-${i}`],
      counterEvidence: [],
    });
  }
  return {
    workflowVersion: '1.0',
    title: `Synthetic renderer benchmark (${nodeCount} nodes)`,
    producer: { kind: 'host-llm', host: 'unknown' },
    revision: { id: revision },
    request: { question: 'Exercise renderer scale without semantic interpretation.', scope: 'synthetic benchmark', entrypoints: ['synthetic/entry.py'], configuration: `nodes=${nodeCount}` },
    phases,
    nodes,
    edges,
    findings,
    evidence,
    coverage: { status: 'partial', summary: 'Synthetic shape coverage only; no target program was analyzed.', inspectedFiles: [], limitations: ['Synthetic benchmark data has no semantic meaning.'] },
  };
}

export function benchmarkFeatures(document) {
  return {
    nodes: document.nodes.length,
    edges: document.edges.length,
    groups: document.nodes.filter((node) => !node.parent && node.id.startsWith('group-')).length,
    nested: document.nodes.filter((node) => node.parent).length,
    cycles: document.edges.filter((edge) => edge.id.startsWith('cycle-')).length,
    longLabels: document.nodes.filter((node) => node.label.length > 60).length,
    findings: document.findings.length,
    evidence: document.evidence.length,
  };
}
