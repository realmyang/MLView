/** Adapter from the host-LLM contract to the renderer's private view model. */
import { add, clear, el, on } from './dom.js';
import { emptyCounts } from './markers.js';
import type { App } from './app.js';
import type { Issue, Loc, MLGraph, WorkflowDocument, WorkflowEvidence } from './types.js';

function evidenceLoc(evidence: Map<string, WorkflowEvidence>, ids: string[], root = ''): Loc {
  const item = ids.map((id) => evidence.get(id)).find(Boolean);
  if (!item) return { file: '', absFile: '', line: 1, col: 0, endLine: 1, endCol: 0 };
  const abs = /^(?:[A-Za-z]:[\\/]|\/)/.test(item.file) ? item.file : root ? root.replace(/[\\/]$/, '') + '/' + item.file : '';
  return { file: item.file, absFile: abs, line: item.line, col: 0, endLine: item.endLine, endCol: 0, snippet: item.quote, cell: item.cell, evidenceId: item.id };
}

/** Validate the discriminant and produce a complete internal graph view. */
export function normalizeWorkflow(document: WorkflowDocument): MLGraph {
  if (!document || document.workflowVersion !== '1.0') throw new Error('MLView.mountWorkflow: workflowVersion must be 1.0');
  const evidence = new Map((document.evidence || []).map((item) => [item.id, item]));
  const issueIds = new Map<string, string[]>();
  for (const finding of document.findings || []) for (const id of finding.nodeIds || []) {
    const list = issueIds.get(id) || []; list.push(finding.id); issueIds.set(id, list);
  }
  const nodes = (document.nodes || []).map((node) => {
    return {
      id: node.id, kind: node.kind || 'unknown', level: node.parent ? 'op' : 'unit', stage: node.phase,
      label: node.label, sublabel: node.detail || node.basis, qualname: node.label, loc: evidenceLoc(evidence, node.evidence),
      parent: node.parent || null, attrs: { basis: node.basis }, produces: [], consumes: [], ghost: node.basis === 'unresolved',
      dynamic: false, confidence: 1, confidenceBucket: node.basis, basis: node.basis,
      evidenceLocs: node.evidence.map((id) => evidenceLoc(evidence, [id])).filter((loc) => !!loc.file),
      issueIds: issueIds.get(node.id) || [], collapsedByDefault: false, stageEvidence: [],
    };
  });
  const edges = (document.edges || []).map((edge) => ({
    id: edge.id, kind: edge.kind || 'unknown', source: edge.source, target: edge.target,
    label: edge.label + ' · ' + edge.basis,
    loc: evidenceLoc(evidence, edge.evidence), tags: [edge.basis], confidence: 1, basis: edge.basis,
    evidenceLocs: edge.evidence.map((id) => evidenceLoc(evidence, [id])).filter((loc) => !!loc.file),
    issueIds: (document.findings || []).filter((f) => (f.edgeIds || []).includes(edge.id)).map((f) => f.id),
  }));
  const issues: Issue[] = (document.findings || []).map((finding) => {
    const loc = evidenceLoc(evidence, finding.evidence);
    const related = (finding.evidence || []).slice(1).map((id) => ({ item: evidence.get(id), role: 'Supporting evidence' }))
      .concat((finding.counterEvidence || []).map((id) => ({ item: evidence.get(id), role: 'Counter-evidence' })))
      .filter((x): x is { item: WorkflowEvidence; role: string } => !!x.item)
      .map(({ item, role }) => ({ ...evidenceLoc(evidence, [item.id]), role }));
    return {
      id: finding.id, code: finding.id, ruleVersion: 0, severity: finding.severity,
      confidence: 1, confidenceBucket: finding.basis, basis: finding.basis, title: finding.title,
      message: finding.message, why: finding.message, fixHint: finding.suggestion || '', loc, relatedLocs: related,
      nodeIds: finding.nodeIds || [], edgeIds: finding.edgeIds || [], stage: nodes.find((n) => finding.nodeIds.includes(n.id))?.stage || '',
      frameworks: [], tags: [finding.basis], evidence: [], suppressed: false, docs: '',
    };
  });
  const stages = (document.phases || []).map((phase, order) => {
    const phaseIssues = issues.filter((issue) => issue.stage === phase.id);
    const counts = emptyCounts(); for (const issue of phaseIssues) counts[issue.severity as 'low' | 'medium' | 'high']++;
    return { id: phase.id, label: phase.label, order, present: true, nodeCount: nodes.filter((n) => n.stage === phase.id).length,
      issueCounts: counts, maxSeverity: (['high','medium','low'] as const).find((s) => counts[s]) || null };
  });
  return {
    schemaVersion: 'workflow-view/1',
    generator: { name: document.producer.host, version: document.producer.model || 'unspecified model', rendererSha: document.revision.id, generatedAt: document.verification?.publishedAt || '' },
    workspace: { root: document.title, entrypoints: document.request.entrypoints || [], filesAnalyzed: document.coverage.inspectedFiles.length, filesFailed: 0, notebooksSkipped: 0, frameworks: [] },
    stages, nodes, edges, issues,
    diagnostics: document.coverage.limitations.map((message) => ({ kind: 'workflow_limitation', message })),
    stats: { nodes: nodes.length, edges: edges.length, issues: issues.reduce((c, i) => { c[i.severity as 'low'|'medium'|'high']++; return c; }, emptyCounts()), durationMs: 0, truncated: document.coverage.status === 'partial' },
  };
}

/** Add authored provenance and coverage above the existing diagram surface. */
export function decorateWorkflow(app: App, document: WorkflowDocument): void {
  app.root.classList.add('mlv-root--workflow');
  app.root.setAttribute('data-workflow-revision', document.revision.id);
  let panel = app.root.querySelector<HTMLElement>('.mlv-workflow');
  if (!panel) { panel = el('section', 'mlv-workflow'); app.root.insertBefore(panel, app.root.querySelector('.mlv-body')); }
  clear(panel);
  const heading = add(panel, el('div', 'mlv-workflow__heading'));
  add(heading, el('h2', 'mlv-workflow__title', document.title));
  add(heading, el('span', 'mlv-chip', document.producer.host + (document.producer.model ? ' · ' + document.producer.model : '')));
  add(heading, el('span', 'mlv-chip', 'revision ' + document.revision.id));
  const verification = document.verification
    ? 'Source snapshot · ' + Object.keys(document.verification.files || {}).length + ' files · ' + document.verification.publishedAt
    : 'Draft · source freshness not verified';
  const verificationChip = add(heading, el('span', 'mlv-chip mlv-workflow__verification', verification));
  verificationChip.title = document.verification
    ? 'File hashes record source freshness; they do not verify the model-authored interpretation.'
    : 'No source hashes were published with this revision.';
  const refine = el('button', 'mlv-btn mlv-workflow__refine', 'Refine') as HTMLButtonElement;
  refine.type = 'button';
  refine.title = 'Continue this workflow analysis in the active assistant';
  on(refine, 'click', () => app.bridge.post({ v: 1, type: 'refineWorkflow', revisionId: document.revision.id, question: document.request.question, scope: document.request.scope }));
  heading.appendChild(refine);
  add(panel, el('p', 'mlv-workflow__question', document.request.question));
  const meta = add(panel, el('div', 'mlv-workflow__meta'));
  add(meta, el('span', '', 'Scope: ' + document.request.scope));
  add(meta, el('span', 'mlv-workflow__coverage mlv-workflow__coverage--' + document.coverage.status, document.coverage.status + ' · ' + document.coverage.summary));
  if (document.coverage.limitations.length) {
    const details = add(panel, el('details', 'mlv-workflow__limitations')) as HTMLDetailsElement;
    add(details, el('summary', '', document.coverage.limitations.length + ' coverage limitation' + (document.coverage.limitations.length === 1 ? '' : 's')));
    const list = add(details, el('ul'));
    for (const limitation of document.coverage.limitations) add(list, el('li', '', limitation));
  }
  const issueTab = app.root.querySelector<HTMLElement>('[role="tab"][aria-controls$="-panel-issues"]');
  if (issueTab) issueTab.textContent = 'Findings';
}
