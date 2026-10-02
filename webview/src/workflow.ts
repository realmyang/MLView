/** Adapter from the host-LLM contract to the renderer's private view model. */
import { add, clear, el, on } from './dom.js';
import { restoreFocus, trapTab } from './ui/focustrap.js';
import { emptyCounts } from './markers.js';
import { normalizeEdgeKind } from './render/edges.js';
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

/**
 * Viewer M2: a finding's short label, `F1` for the first finding in the document. The owner
 * accepted that these renumber between revisions; the real id stays in tooltips, the Selection pane
 * and the Refine and Challenge prompts.
 */
export function findingLabel(position: number): string {
  return 'F' + (position + 1);
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
  const phaseLabels = new Map((document.phases || []).map((phase) => [phase.id, phase.label]));
  const nodes = (document.nodes || []).map((node) => {
    return {
      // Viewer M1: what the Selection pane and the accessible name read.
      ...(typeof node.detail === 'string' && node.detail.trim() ? { detail: node.detail } : {}),
      ...(phaseLabels.has(node.phase) ? { phaseLabel: phaseLabels.get(node.phase) } : {}),
      id: node.id, kind: node.kind || 'unknown', level: node.parent ? 'op' : 'unit', stage: node.phase,
      // Viewer M2: the card's second line is the authored detail, never the basis, and the card
      // has no `basis=…` chip row. The basis is drawn only where it is not `observed`
      // (render/nodes.ts), so the common case carries no mark.
      label: node.label, sublabel: node.detail || '', qualname: node.label, loc: evidenceLoc(evidence, node.evidence),
      // `unresolved` is an authored epistemic basis: the step may exist while
      // its behavior or connection remains uncertain, so it never reads as missing.
      parent: node.parent || null, basis: node.basis,
      evidenceLocs: node.evidence.map((id) => evidenceLoc(evidence, [id])).filter((loc) => !!loc.file),
      issueIds: issueIds.get(node.id) || [],
    };
  });
  const edges = (document.edges || []).map((edge) => ({
    // Issue 9: common synonyms are drawn as the styled kind they mean; any
    // other authored word is kept as written and shown as written.
    id: edge.id, kind: normalizeEdgeKind(edge.kind), source: edge.source, target: edge.target,
    ...(edge.kind && normalizeEdgeKind(edge.kind) !== edge.kind.trim() ? { authoredKind: edge.kind } : {}),
    // Viewer M2: the label as authored. The basis is drawn by the stroke (render/edges.ts), not
    // appended to the text.
    label: edge.label,
    loc: evidenceLoc(evidence, edge.evidence), basis: edge.basis,
    evidenceLocs: edge.evidence.map((id) => evidenceLoc(evidence, [id])).filter((loc) => !!loc.file),
    issueIds: edgeIssueIds.get(edge.id) || [],
  }));
  const issues: Issue[] = (document.findings || []).map((finding, position) => {
    const loc = evidenceLoc(evidence, finding.evidence);
    const related = (finding.evidence || []).map((id) => ({ item: evidence.get(id), role: 'Supporting evidence' }))
      .concat((finding.counterEvidence || []).map((id) => ({ item: evidence.get(id), role: 'Counter-evidence' })))
      .filter((x): x is { item: WorkflowEvidence; role: string } => !!x.item)
      .map(({ item, role }) => ({ ...evidenceLoc(evidence, [item.id]), role }));
    return {
      id: finding.id, code: finding.id, short: findingLabel(position), severity: finding.severity, basis: finding.basis, title: finding.title,
      message: finding.message, fixHint: finding.suggestion || '', loc, relatedLocs: related,
      nodeIds: finding.nodeIds || [], edgeIds: finding.edgeIds || [], stage: nodes.find((n) => finding.nodeIds.includes(n.id))?.stage || '',
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
    workspace: { root: document.title, entrypoints: document.request.entrypoints || [], filesAnalyzed: document.coverage.inspectedFiles.length },
    stages, nodes, edges, issues,
    diagnostics: document.coverage.limitations.map((message) => ({ kind: 'workflow_limitation', message })),
    // Authored partial coverage means the model intentionally inspected a
    // bounded portion of the workflow; the header says so.
    stats: { nodes: nodes.length, edges: edges.length, issues: issues.reduce((c, i) => { c[i.severity as 'low'|'medium'|'high']++; return c; }, emptyCounts()), durationMs: 0 },
    authoredCoverage: { status: document.coverage.status, limitations: document.coverage.limitations.length },
  };
}

/** The five intents, in menu order; `custom` opens the free-text field. */
const INTENTS: [RefineIntent, string][] = [['explain', 'Explain'], ['expand', 'Expand'], ['challenge', 'Challenge'], ['trace', 'Trace'], ['custom', 'Custom…']];

type ComposerSelection = { kind: 'node' | 'edge' | 'issue'; id: string } | undefined;

/**
 * What an open or closed composer holds, captured before a rebuild (VIEWUI-4).
 * The host's last answer is not kept: every rebuild follows a `workflow` frame,
 * and a refusal describes the state before it (LINEAGE2-1).
 */
interface ComposerSnapshot {
  revision: string | null;
  open: boolean;
  intent: string;
  custom: string;
  focus: 'refine' | 'intent' | 'custom' | 'submit' | null;
  selection: ComposerSelection;
}

/**
 * The composer as `ViewState.composer`: undefined at its default (closed,
 * Explain, no text), per the "absent at default" rule, or when no authored
 * composer is mounted.
 */
export function composerViewState(root: HTMLElement): ComposerState | undefined {
  const snapshot = captureComposer(root);
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

function captureComposer(root: HTMLElement): ComposerSnapshot | null {
  const panel = root.querySelector<HTMLElement>('.mlv-workflow');
  const composer = root.querySelector<HTMLFormElement>('.mlv-workflow__composer');
  const intent = root.querySelector<HTMLSelectElement>('.mlv-workflow__intent');
  const custom = root.querySelector<HTMLInputElement>('.mlv-workflow__custom');
  const refine = root.querySelector<HTMLButtonElement>('.mlv-workflow__refine');
  if (!panel || !composer || !intent || !custom) return null;
  const active = root.ownerDocument.activeElement;
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
    focus,
    selection: (kind === 'node' || kind === 'edge' || kind === 'issue') && id ? { kind, id } : undefined,
  };
}

/**
 * Banner codes under which a refusal about the artifact file may still hold:
 * the reload has not settled (`checking`), or the file is still missing,
 * unreadable, malformed or without a valid revision id (`invalid` also covers
 * that last case).
 */
const FILE_STATE_CODES = new Set(['checking', 'missing', 'unreadable', 'parse', 'invalid']);

/**
 * A new host banner (LINEAGE2-1). Once it shows none of the file-state codes,
 * the artifact file is readable again, so the composer's last refusal (for
 * example "the artifact file is missing") no longer holds and is cleared. A
 * repaired file that holds the displayed revision again brings no `workflow`
 * frame, so the banner is the only signal.
 */
export function onWorkflowStatus(app: App, codes: readonly string[] | undefined): void {
  if (!codes || codes.some((code) => FILE_STATE_CODES.has(code))) return;
  const status = app.root.querySelector<HTMLElement>('.mlv-workflow__status');
  if (!status || !status.textContent) return;
  status.textContent = '';
  app.saveSoon();
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
    const opener = composerOpeners.get(composer) || null;
    composerOpeners.delete(composer);
    restoreFocus(opener, refine);
    app.saveSoon();
    return;
  }
  composer.hidden = false;
  refine.setAttribute('aria-expanded', 'true');
  status.textContent = result.message || 'The refinement prompt was not copied.';
  app.saveSoon();
}

/**
 * Viewer M2: what had the focus when the Refine… popover opened (the Refine… button, or the
 * Selection pane's Challenge or Refine… button); closing gives it back.
 */
const composerOpeners = new WeakMap<HTMLElement, HTMLElement>();

/** The composer names its target by its authored label; the id stays on `data-selection-id` and in the prompt. */
function selectionLabel(app: App, value: ComposerSelection): string {
  if (!value) return 'Whole diagram';
  const index = app.index;
  if (value.kind === 'node') {
    const node = index ? index.nodeById.get(value.id) : undefined;
    return 'Step: ' + (node ? node.label || node.id : value.id);
  }
  if (value.kind === 'edge') {
    const edge = index ? index.edgeById.get(value.id) : undefined;
    if (!edge) return 'Connection: ' + value.id;
    const from = index!.nodeById.get(edge.source);
    const to = index!.nodeById.get(edge.target);
    return 'Connection: ' + (edge.label || (from ? from.label : edge.source) + ' → ' + (to ? to.label : edge.target));
  }
  const issue = index ? index.issueById.get(value.id) : undefined;
  return 'Finding: ' + (issue ? (issue.short ? issue.short + ' · ' : '') + issue.title : value.id);
}

/**
 * The authored layer over the diagram: the Refine… popover under the one-row header, plus the
 * Refine… button the header shows. `restored` is the composer a remounted viewer saved for this
 * same revision. The title and the provenance chip are the header's own (`ui/chrome.ts` reads the
 * document). Viewer M2: the request and coverage details that also opened here are the About tab
 * now (`ui/about.ts`).
 */
export function decorateWorkflow(app: App, document: WorkflowDocument, restored?: ComposerState | null): void {
  app.root.classList.add('mlv-root--workflow');
  app.root.setAttribute('data-workflow-revision', document.revision.id);
  let panel = app.root.querySelector<HTMLElement>('.mlv-workflow');
  if (!panel) {
    panel = el('section', 'mlv-workflow');
    const header = app.chrome.header;
    app.root.insertBefore(panel, header.nextSibling);
  }
  // VIEWUI-4: a re-posted or refreshed revision must not wipe an open composer
  // or the request the reader is typing, so its state survives the rebuild.
  // A remounted viewer has no composer to capture: it restores the one saved
  // with its state for this same revision (a new revision id was never saved).
  const captured = captureComposer(app.root);
  const prior: ComposerSnapshot | null = captured
    ?? (restored ? { revision: document.revision.id, open: restored.open, intent: restored.intent, custom: restored.custom, focus: null, selection: undefined } : null);
  const fromRestore = !captured && !!restored;
  const oldComposer = panel.querySelector<HTMLElement>('.mlv-workflow__composer');
  const opener = oldComposer ? composerOpeners.get(oldComposer) || null : null;
  clear(panel);
  panel.setAttribute('data-revision', document.revision.id);
  panel.setAttribute('aria-label', 'Refinement');

  const refine = el('button', 'mlv-btn mlv-btn--primary mlv-workflow__refine', 'Refine…') as HTMLButtonElement;
  refine.type = 'button';
  refine.title = 'Copy a refinement prompt for your assistant about the selection or the whole diagram. MLView calls no model.';
  refine.setAttribute('aria-expanded', 'false');
  refine.setAttribute('aria-haspopup', 'dialog');
  const slot = app.chrome.refineSlot;
  clear(slot);
  slot.appendChild(refine);
  app.chrome.syncRoving();

  const composer = add(panel, el('form', 'mlv-workflow__composer')) as HTMLFormElement;
  composer.hidden = true;
  // Viewer M2: a modal popover: Tab stays inside it, Escape closes it and gives the focus back.
  composer.setAttribute('role', 'dialog');
  composer.setAttribute('aria-modal', 'true');
  composer.setAttribute('aria-label', 'Refine');
  if (opener) composerOpeners.set(composer, opener);
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
  add(composer, el('p', 'mlv-workflow__hint', 'Copies a prompt for your assistant to paste. MLView calls no model.'));
  const selection = (): ComposerSelection => app.selection ? { kind: app.selection.kind, id: app.selection.id } : undefined;
  let selectedContext: ComposerSelection;
  const showSelection = (value: ComposerSelection) => {
    selectedContext = value;
    selected.textContent = selectionLabel(app, value);
    if (value) {
      selected.title = value.kind + ' id: ' + value.id;
      composer.setAttribute('data-selection-kind', value.kind);
      composer.setAttribute('data-selection-id', value.id);
    } else {
      selected.removeAttribute('title');
      composer.removeAttribute('data-selection-kind');
      composer.removeAttribute('data-selection-id');
    }
  };
  const refreshSelection = () => showSelection(selection());
  on(refine, 'click', () => {
    if (composer.hidden) {
      // Remember who opened it; a Challenge button presses Refine… for itself.
      const active = refine.ownerDocument.activeElement as HTMLElement | null;
      if (active && !composer.contains(active) && active !== refine.ownerDocument.body) composerOpeners.set(composer, active);
      else composerOpeners.delete(composer);
    }
    composer.hidden = !composer.hidden;
    refine.setAttribute('aria-expanded', composer.hidden ? 'false' : 'true');
    if (!composer.hidden) { refreshSelection(); intent.focus(); }
    app.saveSoon();
  });
  // Escape inside the popover closes it and gives the focus back to whatever opened it; Tab and
  // Shift+Tab cycle inside it.
  on(composer, 'keydown', (ev: KeyboardEvent) => {
    if (trapTab(composer, ev)) {
      ev.stopPropagation();
      return;
    }
    if (ev.key !== 'Escape') return;
    ev.preventDefault();
    ev.stopPropagation();
    closeComposer(app, true);
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
    // The status starts empty: the host's last answer described the state
    // before this `workflow` frame, even for the same revision id (a refusal
    // about a missing or unreadable file no longer holds once the file is
    // read again; LINEAGE1-5, LINEAGE2-1).
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
}

/** Whether the Refine… popover is open. */
export function composerOpen(app: App): boolean {
  const composer = app.root.querySelector<HTMLFormElement>('.mlv-workflow__composer');
  return !!composer && !composer.hidden;
}

/**
 * Close the Refine… popover (Escape); the typed text and intent stay for next time. With
 * `giveFocusBack` the focus returns to what opened it (viewer M2), else to Refine….
 */
export function closeComposer(app: App, giveFocusBack = false): boolean {
  const composer = app.root.querySelector<HTMLFormElement>('.mlv-workflow__composer');
  const refine = app.root.querySelector<HTMLButtonElement>('.mlv-workflow__refine');
  if (!composer || composer.hidden) return false;
  composer.hidden = true;
  const opener = composerOpeners.get(composer) || null;
  composerOpeners.delete(composer);
  if (refine) refine.setAttribute('aria-expanded', 'false');
  if (giveFocusBack) restoreFocus(opener, refine);
  app.saveSoon();
  return true;
}
