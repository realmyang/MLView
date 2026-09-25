/** Adapter from the host-LLM contract to the renderer's private view model. */
import { add, clear, el, on } from './dom.js';
import { emptyCounts } from './markers.js';
import type { App } from './app.js';
import type { ActionResult, ComposerState, Issue, Loc, MLGraph, RefineIntent, WorkflowDocument, WorkflowEvidence } from './types.js';

/**
 * An authored evidence item as a renderer `Loc`. Evidence paths are always
 * workspace-relative (the contract rejects absolute and drive-qualified
 * paths) and the host resolves them, so `absFile` is always empty.
 */
function evidenceLoc(evidence: Map<string, WorkflowEvidence>, ids: string[]): Loc {
  const item = ids.map((id) => evidence.get(id)).find(Boolean);
  if (!item) return { file: '', absFile: '', line: 1, col: 0, endLine: 1, endCol: 0 };
  return { file: item.file, absFile: '', line: item.line, col: 0, endLine: item.endLine, endCol: 0, snippet: item.quote, cell: item.cell, evidenceId: item.id };
}

/** `generator.version` when the producer named no model. */
export const UNSPECIFIED_MODEL = 'unspecified model';

/** Validate the discriminant and produce a complete internal graph view. */
export function normalizeWorkflow(document: WorkflowDocument): MLGraph {
  if (!document || document.workflowVersion !== '1.0') throw new Error('MLView.mountWorkflow: workflowVersion must be 1.0');
  const evidence = new Map((document.evidence || []).map((item) => [item.id, item]));
  const issueIds = new Map<string, string[]>();
  const edgeIssueIds = new Map<string, string[]>();
  for (const finding of document.findings || []) for (const id of finding.nodeIds || []) {
    const list = issueIds.get(id) || []; list.push(finding.id); issueIds.set(id, list);
  }
  for (const finding of document.findings || []) for (const id of finding.edgeIds || []) {
    const list = edgeIssueIds.get(id) || []; list.push(finding.id); edgeIssueIds.set(id, list);
  }
  const nodes = (document.nodes || []).map((node) => {
    return {
      id: node.id, kind: node.kind || 'unknown', level: node.parent ? 'op' : 'unit', stage: node.phase,
      label: node.label, sublabel: node.detail || node.basis, qualname: node.label, loc: evidenceLoc(evidence, node.evidence),
      // `unresolved` is an authored epistemic basis: the step may exist while
      // its behavior or connection remains uncertain. Ghost cards belong to a
      // legacy absence/diff treatment and would falsely imply a missing step.
      parent: node.parent || null, attrs: { basis: node.basis }, produces: [], consumes: [], ghost: false,
      // WorkflowDocument records an evidence basis, not a calibrated numeric
      // probability. NaN keeps shared renderer math type-safe without inventing
      // a percentage that the authored contract cannot support.
      dynamic: false, confidence: Number.NaN, confidenceBucket: node.basis, basis: node.basis, authored: true,
      evidenceLocs: node.evidence.map((id) => evidenceLoc(evidence, [id])).filter((loc) => !!loc.file),
      issueIds: issueIds.get(node.id) || [], collapsedByDefault: false, stageEvidence: [],
    };
  });
  const edges = (document.edges || []).map((edge) => ({
    id: edge.id, kind: edge.kind || 'unknown', source: edge.source, target: edge.target,
    label: edge.label + ' · ' + edge.basis,
    loc: evidenceLoc(evidence, edge.evidence), tags: [edge.basis], confidence: Number.NaN, basis: edge.basis,
    evidenceLocs: edge.evidence.map((id) => evidenceLoc(evidence, [id])).filter((loc) => !!loc.file),
    issueIds: edgeIssueIds.get(edge.id) || [],
  }));
  const issues: Issue[] = (document.findings || []).map((finding) => {
    const loc = evidenceLoc(evidence, finding.evidence);
    const related = (finding.evidence || []).map((id) => ({ item: evidence.get(id), role: 'Supporting evidence' }))
      .concat((finding.counterEvidence || []).map((id) => ({ item: evidence.get(id), role: 'Counter-evidence' })))
      .filter((x): x is { item: WorkflowEvidence; role: string } => !!x.item)
      .map(({ item, role }) => ({ ...evidenceLoc(evidence, [item.id]), role }));
    return {
      id: finding.id, code: finding.id, ruleVersion: 0, severity: finding.severity,
      confidence: Number.NaN, confidenceBucket: finding.basis, basis: finding.basis, title: finding.title,
      // `why` stays empty: the expanded row already prints `message`, and a
      // second copy of the same sentence is noise (VIEWUI-14).
      message: finding.message, why: '', fixHint: finding.suggestion || '', loc, relatedLocs: related,
      nodeIds: finding.nodeIds || [], edgeIds: finding.edgeIds || [], stage: nodes.find((n) => finding.nodeIds.includes(n.id))?.stage || '',
      frameworks: [], tags: [finding.basis], evidence: [], suppressed: false, docs: '',
    };
  });
  const nodesByStage = new Map<string, number>();
  const issuesByStage = new Map<string, ReturnType<typeof emptyCounts>>();
  for (const node of nodes) nodesByStage.set(node.stage, (nodesByStage.get(node.stage) || 0) + 1);
  for (const issue of issues) {
    const counts = issuesByStage.get(issue.stage) || emptyCounts();
    counts[issue.severity as 'low' | 'medium' | 'high']++;
    issuesByStage.set(issue.stage, counts);
  }
  const stages = (document.phases || []).map((phase, order) => {
    const counts = issuesByStage.get(phase.id) || emptyCounts();
    return { id: phase.id, label: phase.label, order, present: true, nodeCount: nodesByStage.get(phase.id) || 0,
      issueCounts: counts, maxSeverity: (['high','medium','low'] as const).find((s) => counts[s]) || null };
  });
  return {
    schemaVersion: 'workflow-view/1',
    generator: { name: document.producer.host, version: document.producer.model || UNSPECIFIED_MODEL, rendererSha: document.revision.id, generatedAt: document.verification?.publishedAt || '' },
    workspace: { root: document.title, entrypoints: document.request.entrypoints || [], filesAnalyzed: document.coverage.inspectedFiles.length, filesFailed: 0, notebooksSkipped: 0, frameworks: [] },
    stages, nodes, edges, issues,
    diagnostics: document.coverage.limitations.map((message) => ({ kind: 'workflow_limitation', message })),
    // Authored partial coverage means the model intentionally inspected a
    // bounded portion of the workflow. It is surfaced by the authored
    // coverage panel above, and is distinct from the legacy analyzer's node
    // cap, which alone owns stats.truncated and its truncation banner.
    stats: { nodes: nodes.length, edges: edges.length, issues: issues.reduce((c, i) => { c[i.severity as 'low'|'medium'|'high']++; return c; }, emptyCounts()), durationMs: 0, truncated: false },
    authoredCoverage: { status: document.coverage.status, limitations: document.coverage.limitations.length },
  };
}

/** The five intents, in menu order; `custom` opens the free-text field. */
const INTENTS: [RefineIntent, string][] = [['explain', 'Explain'], ['expand', 'Expand'], ['challenge', 'Challenge'], ['trace', 'Trace'], ['custom', 'Custom…']];

type ComposerSelection = { kind: 'node' | 'edge' | 'issue'; id: string } | undefined;

/** What an open or closed composer holds, captured before a rebuild (VIEWUI-4). */
interface ComposerSnapshot {
  revision: string | null;
  open: boolean;
  intent: string;
  custom: string;
  status: string;
  focus: 'refine' | 'intent' | 'custom' | 'submit' | null;
  selection: ComposerSelection;
}

/**
 * The composer as `ViewState.composer`: undefined at its default (closed,
 * Explain, no text), per the "absent at default" rule, or when no authored
 * composer is mounted.
 */
export function composerViewState(root: HTMLElement): ComposerState | undefined {
  const panel = root.querySelector<HTMLElement>('.mlv-workflow');
  const snapshot = panel ? captureComposer(panel) : null;
  if (!snapshot) return undefined;
  const intent = sanitizeIntent(snapshot.intent);
  if (!snapshot.open && intent === 'explain' && !snapshot.custom) return undefined;
  return { open: snapshot.open, intent, custom: snapshot.custom };
}

const sanitizeIntent = (value: unknown): RefineIntent => INTENTS.find(([intent]) => intent === value)?.[0] ?? 'explain';

/** A restored `ViewState.composer`, validated field by field (saved state comes from the webview's storage). */
export function sanitizeComposer(value: unknown): ComposerState | null {
  if (!value || typeof value !== 'object') return null;
  const record = value as Record<string, unknown>;
  return {
    open: record.open === true,
    intent: sanitizeIntent(record.intent),
    custom: typeof record.custom === 'string' ? record.custom.slice(0, 500) : '',
  };
}

function captureComposer(panel: HTMLElement): ComposerSnapshot | null {
  const composer = panel.querySelector<HTMLFormElement>('.mlv-workflow__composer');
  const intent = panel.querySelector<HTMLSelectElement>('.mlv-workflow__intent');
  const custom = panel.querySelector<HTMLInputElement>('.mlv-workflow__custom');
  const refine = panel.querySelector<HTMLButtonElement>('.mlv-workflow__refine');
  const status = panel.querySelector<HTMLElement>('.mlv-workflow__status');
  if (!composer || !intent || !custom) return null;
  const active = panel.ownerDocument.activeElement;
  let focus: ComposerSnapshot['focus'] = null;
  if (active && active === refine) focus = 'refine';
  else if (active && composer.contains(active)) focus = active === intent ? 'intent' : active === custom ? 'custom' : 'submit';
  const kind = composer.getAttribute('data-selection-kind');
  const id = composer.getAttribute('data-selection-id');
  return {
    revision: panel.getAttribute('data-revision'),
    open: !composer.hidden,
    intent: intent.value,
    custom: custom.value,
    status: status ? status.textContent || '' : '',
    focus,
    selection: (kind === 'node' || kind === 'edge' || kind === 'issue') && id ? { kind, id } : undefined,
  };
}

/**
 * The host's answer to a copied refinement prompt (§1e). The composer is
 * looked up again here because a same-revision refresh may have rebuilt it
 * while the host was working.
 */
function onRefineResult(app: App, result: ActionResult): void {
  const composer = app.root.querySelector<HTMLFormElement>('.mlv-workflow__composer');
  const refine = app.root.querySelector<HTMLButtonElement>('.mlv-workflow__refine');
  const custom = app.root.querySelector<HTMLInputElement>('.mlv-workflow__custom');
  const status = app.root.querySelector<HTMLElement>('.mlv-workflow__status');
  if (!composer || !refine || !custom || !status) return;
  if (result.outcome === 'done') {
    composer.hidden = true;
    refine.setAttribute('aria-expanded', 'false');
    custom.value = '';
    status.textContent = '';
    refine.focus();
    app.saveSoon();
    return;
  }
  composer.hidden = false;
  refine.setAttribute('aria-expanded', 'true');
  status.textContent = result.message || 'The refinement prompt was not copied.';
  app.saveSoon();
}

/**
 * Add authored provenance and coverage above the existing diagram surface.
 * `restored` is the composer a remounted viewer saved for this same revision.
 */
export function decorateWorkflow(app: App, document: WorkflowDocument, restored?: ComposerState | null): void {
  app.root.classList.add('mlv-root--workflow');
  app.root.setAttribute('data-workflow-revision', document.revision.id);
  let panel = app.root.querySelector<HTMLElement>('.mlv-workflow');
  if (!panel) { panel = el('section', 'mlv-workflow'); app.root.insertBefore(panel, app.root.querySelector('.mlv-body')); }
  // VIEWUI-4: a re-posted or refreshed revision must not wipe an open composer
  // or the request the reader is typing, so its state survives the rebuild.
  // A remounted viewer has no composer to capture: it restores the one saved
  // with its state for this same revision (a new revision id was never saved).
  const captured = captureComposer(panel);
  const prior: ComposerSnapshot | null = captured
    ?? (restored ? { revision: document.revision.id, open: restored.open, intent: restored.intent, custom: restored.custom, status: '', focus: null, selection: undefined } : null);
  const fromRestore = !captured && !!restored;
  clear(panel);
  panel.setAttribute('data-revision', document.revision.id);
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
  refine.setAttribute('aria-expanded', 'false');
  heading.appendChild(refine);
  const composer = add(panel, el('form', 'mlv-workflow__composer')) as HTMLFormElement;
  composer.hidden = true;
  const selected = add(composer, el('span', 'mlv-workflow__selection'));
  const intent = add(composer, el('select', 'mlv-input mlv-workflow__intent')) as HTMLSelectElement;
  intent.setAttribute('aria-label', 'Refinement intent');
  for (const [value, label] of INTENTS) {
    const option = intent.ownerDocument.createElement('option'); option.value = value; option.textContent = label; intent.appendChild(option);
  }
  const custom = add(composer, el('input', 'mlv-input mlv-workflow__custom')) as HTMLInputElement;
  custom.type = 'text'; custom.maxLength = 500; custom.placeholder = 'What should the assistant refine?'; custom.setAttribute('aria-label', 'Custom refinement intent'); custom.hidden = true;
  const submit = add(composer, el('button', 'mlv-btn', 'Copy prompt')) as HTMLButtonElement; submit.type = 'submit';
  // Why the host did not copy the prompt, when it did not (§1e).
  const status = add(composer, el('span', 'mlv-workflow__status'));
  status.setAttribute('role', 'status');
  const selection = (): ComposerSelection => app.selection ? { kind: app.selection.kind, id: app.selection.id } : undefined;
  let selectedContext: ComposerSelection;
  const showSelection = (value: ComposerSelection) => {
    selectedContext = value;
    selected.textContent = value ? value.kind + ': ' + value.id : 'Whole diagram';
    if (value) {
      composer.setAttribute('data-selection-kind', value.kind);
      composer.setAttribute('data-selection-id', value.id);
    } else {
      composer.removeAttribute('data-selection-kind');
      composer.removeAttribute('data-selection-id');
    }
  };
  const refreshSelection = () => showSelection(selection());
  on(refine, 'click', () => {
    composer.hidden = !composer.hidden;
    refine.setAttribute('aria-expanded', composer.hidden ? 'false' : 'true');
    if (!composer.hidden) { refreshSelection(); intent.focus(); }
    app.saveSoon();
  });
  on(intent, 'change', () => { custom.hidden = intent.value !== 'custom'; if (!custom.hidden) custom.focus(); app.saveSoon(); });
  // The typed request survives a webview recreation (the panel does not retain its context when hidden).
  on(custom, 'input', () => app.saveSoon());
  on(composer, 'submit', (event) => {
    event.preventDefault();
    const chosen = intent.value as RefineIntent;
    const text = custom.value.trim();
    if (chosen === 'custom' && !text) { custom.focus(); return; }
    status.textContent = '';
    // §1e: an explicit intent, plus `customText` only for `custom`. The host
    // answers with one `actionResult`; the composer closes only on `done`.
    const message: { v: 1; type: 'refineWorkflow'; revisionId: string; intent: RefineIntent; customText?: string; selection?: ComposerSelection } =
      { v: 1, type: 'refineWorkflow', revisionId: document.revision.id, intent: chosen };
    if (chosen === 'custom') message.customText = text;
    if (selectedContext) message.selection = selectedContext;
    app.postRequest(message, (result) => onRefineResult(app, result));
  });
  if (prior) {
    if (INTENTS.some(([value]) => value === prior.intent)) intent.value = prior.intent;
    custom.value = prior.custom;
    custom.hidden = intent.value !== 'custom';
    // The host's last answer describes the revision it was given; a new
    // revision starts with no stale refusal on screen.
    status.textContent = prior.revision === document.revision.id ? prior.status : '';
    if (prior.open) {
      composer.hidden = false;
      refine.setAttribute('aria-expanded', 'true');
      // Same revision: the reader's captured selection still resolves. A new
      // revision re-captures from `app.selection`, which the projection has
      // already cleared if the revision removed it (VIEWUI-15).
      if (prior.revision === document.revision.id && !fromRestore) showSelection(prior.selection);
      else refreshSelection();
    }
    if (prior.focus === 'refine') refine.focus();
    else if (prior.focus === 'intent' && !composer.hidden) intent.focus();
    else if (prior.focus === 'custom' && !composer.hidden && !custom.hidden) custom.focus();
    else if (prior.focus === 'submit' && !composer.hidden) submit.focus();
  }
  add(panel, el('p', 'mlv-workflow__question', document.request.question));
  const meta = add(panel, el('div', 'mlv-workflow__meta'));
  add(meta, el('span', '', 'Scope: ' + document.request.scope));
  add(meta, el('span', '', 'Entrypoints: ' + (document.request.entrypoints?.join(', ') || 'not specified')));
  add(meta, el('span', '', 'Configuration: ' + (document.request.configuration || 'not specified')));
  add(meta, el('span', 'mlv-workflow__coverage mlv-workflow__coverage--' + document.coverage.status, document.coverage.status + ' · ' + document.coverage.summary));
  if (document.coverage.limitations.length) {
    const details = add(panel, el('details', 'mlv-workflow__limitations')) as HTMLDetailsElement;
    add(details, el('summary', '', document.coverage.limitations.length + ' coverage limitation' + (document.coverage.limitations.length === 1 ? '' : 's')));
    const list = add(details, el('ul'));
    for (const limitation of document.coverage.limitations) add(list, el('li', '', limitation));
  }
  const issueTab = app.root.querySelector<HTMLElement>('[role="tab"][aria-controls$="-panel-issues"]');
  if (issueTab) issueTab.textContent = 'Findings';
  const search = app.root.querySelector<HTMLInputElement>('.mlv-search input[type="search"]');
  if (search) {
    search.placeholder = 'Search steps, findings, IDs, or cited text…';
    const label = search.id
      ? app.root.querySelector<HTMLLabelElement>('label[for="' + search.id + '"]')
      : null;
    if (label) label.textContent = 'Search steps, findings, IDs, or cited text';
  }
}
