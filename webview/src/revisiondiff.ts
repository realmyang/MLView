/**
 * Changes since the previous revision (viewer M4, roadmap step 16). Pure: no DOM, no App, nothing
 * called; two authored documents in, the steps, connections and findings added, removed or changed
 * out.
 *
 * The artifact keeps no history beyond `revision.parent`, so the host can only hand the viewer a
 * revision this panel itself showed before (the `workflow` frame's `previous`, sent only when the
 * displayed revision names it as its parent). This compares the two by id:
 *
 *   - added: the id is in the new revision only; removed: in the old one only. An item whose id
 *     changed is therefore one removed and one added; the About section says so.
 *   - changed: the same id, and one of these authored fields differs:
 *       steps        label, detail, basis, phase (a move to another phase), group (`parent`),
 *                    kind, evidence
 *       connections  from (`source`), to (`target`), label, kind, basis, evidence
 *       findings     title, description (`message`), severity, basis, what to change
 *                    (`suggestion`), cited steps (`nodeIds`), cited connections (`edgeIds`),
 *                    evidence, counter-evidence
 *   - evidence is compared by what each referenced record cites (file, lines, notebook cell and
 *     quote), as a multiset, never by its ids: a quote whose text changed under the same id is a
 *     change, an evidence id renamed with the same file, lines and quote is not, and neither is a
 *     reordering. Cited steps and connections compare as sets; the order of the document's own
 *     lists is never a change.
 *   - phases (viewer M4 review, M4R-4): a step moved when its phase is another phase. A phase is
 *     the same phase in both revisions when it keeps its id, or, when its id is gone, when exactly
 *     one new phase has its label and an id the old revision did not use. So a phase renamed under
 *     the same id moves none of its steps; it is listed once, in `phases` (old and new label). A
 *     phase id renamed with the same label changes nothing the reader sees, and is not listed.
 *
 * Nothing here judges a change: the words are added, removed and changed, never fixed, wrong,
 * better or worse. What the comparison leaves out (the request, the summary, coverage, phases
 * added or removed on their own, the title) is not compared.
 */

import type { WorkflowDocument, WorkflowEvidence } from './types.js';

export type ChangeStatus = 'added' | 'removed' | 'changed';
/** The claim kinds, named as the viewer's selection names them. */
export type ChangeKind = 'node' | 'edge' | 'issue';

export interface ItemChange {
  kind: ChangeKind;
  id: string;
  status: ChangeStatus;
  /** For `changed`: the fields that differ, in the viewer's words ("label", "evidence"), in a fixed order. */
  fields: string[];
  /**
   * What the item is called in the revision it is in (the new one, or the old one for a removed
   * item): a step's label, a connection's label with its ends ("produces · Fit → Weights"), a
   * finding's title.
   */
  title: string;
}

export interface ChangeGroup {
  added: ItemChange[];
  removed: ItemChange[];
  changed: ItemChange[];
}

/** Viewer M4 review (M4R-4): a phase whose label changed under the same id. */
export interface PhaseRename {
  id: string;
  /** The label in the revision this panel showed before. */
  from: string;
  /** The label now. */
  to: string;
}

export interface RevisionDiff {
  /** The revision compared with (the one this panel showed before). */
  since: string;
  /** The revision shown now. */
  revision: string;
  steps: ChangeGroup;
  connections: ChangeGroup;
  findings: ChangeGroup;
  /** Phases renamed under the same id, in the new revision's order; their steps did not move. */
  phases: PhaseRename[];
  /** Every added or changed item, keyed `kind:id` (removed items have nothing to mark). */
  marks: Map<string, ItemChange>;
}

/** The key `RevisionDiff.marks` uses. */
export function changeKey(kind: ChangeKind, id: string): string {
  return kind + ':' + id;
}

/** The added or changed mark of a claim, or undefined. */
export function changeOf(diff: RevisionDiff | null | undefined, kind: ChangeKind, id: string): ItemChange | undefined {
  return diff ? diff.marks.get(changeKey(kind, id)) : undefined;
}

/** How many items were added, removed or changed in all three groups. */
export function changeTotal(diff: RevisionDiff): number {
  let n = 0;
  for (const group of [diff.steps, diff.connections, diff.findings]) n += group.added.length + group.removed.length + group.changed.length;
  return n;
}

/** How many claims were added or changed (what the walk's "Changed in this revision" holds). */
export function markedTotal(diff: RevisionDiff | null | undefined): number {
  return diff ? diff.marks.size : 0;
}

/* ── reading a document defensively (the host validated it; a frame is still data) ─────────── */

type Rec = Record<string, unknown>;

function list(value: unknown): Rec[] {
  return Array.isArray(value) ? value.filter((item): item is Rec => !!item && typeof item === 'object' && !Array.isArray(item)) : [];
}

function str(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

/** Text compared as the reader sees it: surrounding whitespace is not a change. */
function text(value: unknown): string {
  return str(value).trim();
}

function ids(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

/** First record per id, in document order. */
function byId(items: Rec[]): Map<string, Rec> {
  const out = new Map<string, Rec>();
  for (const item of items) {
    const id = str(item.id);
    if (id && !out.has(id)) out.set(id, item);
  }
  return out;
}

interface Doc {
  nodes: Map<string, Rec>;
  edges: Map<string, Rec>;
  findings: Map<string, Rec>;
  evidence: Map<string, WorkflowEvidence>;
  /** Phase id to its label, in document order. */
  phases: Map<string, string>;
  /**
   * A step's phase as one identity across the two revisions (`matchPhases`): the new revision's
   * phase id; in the old revision, the id of the new phase it matches, else its own id marked old.
   */
  phaseKey: (id: string) => string;
}

function readDoc(document: WorkflowDocument): Doc {
  const d = (document || {}) as unknown as Rec;
  const evidence = new Map<string, WorkflowEvidence>();
  for (const item of list(d.evidence)) {
    const id = str(item.id);
    if (id && !evidence.has(id)) evidence.set(id, item as unknown as WorkflowEvidence);
  }
  const phases = new Map<string, string>();
  for (const phase of list(d.phases)) {
    const id = str(phase.id);
    if (id && !phases.has(id)) phases.set(id, str(phase.label));
  }
  return { nodes: byId(list(d.nodes)), edges: byId(list(d.edges)), findings: byId(list(d.findings)), evidence, phases, phaseKey: (id) => id };
}

/**
 * Viewer M4 review (M4R-4): match the old revision's phases to the new one's (see the module
 * comment), so a step is "changed: phase" only when it moved, and list the phases renamed under the
 * same id.
 */
function matchPhases(prev: Doc, next: Doc): PhaseRename[] {
  const byLabel = new Map<string, string[]>();
  for (const [id, label] of next.phases) {
    if (prev.phases.has(id)) continue;
    const key = label.trim();
    byLabel.set(key, (byLabel.get(key) || []).concat(id));
  }
  const map = new Map<string, string>();
  for (const [id, label] of prev.phases) {
    if (next.phases.has(id)) map.set(id, id);
    else {
      const same = byLabel.get(label.trim()) || [];
      if (same.length === 1) map.set(id, same[0]);
    }
  }
  // The \u0000 prefix keeps an unmatched old id from equalling a new id spelled the same way.
  prev.phaseKey = (id) => map.get(id) ?? (next.phases.has(id) ? '\u0000old\u0000' + id : id);
  next.phaseKey = (id) => id;
  const renames: PhaseRename[] = [];
  for (const [id, to] of next.phases) {
    const from = prev.phases.get(id);
    if (from !== undefined && from.trim() !== to.trim()) renames.push({ id, from: from.trim(), to: to.trim() });
  }
  return renames;
}

/** What one evidence record cites, as one string (a record the document lacks is named by its id). */
function evidenceSignature(doc: Doc, id: string): string {
  const item = doc.evidence.get(id);
  if (!item) return '\u0000missing\u0000' + id;
  const cell = typeof item.cell === 'number' ? String(item.cell) : '';
  return [str(item.file), String(item.line), String(item.endLine), cell, str(item.quote)].join('\u0000');
}

/** The evidence a list of ids cites, as a sorted multiset. */
function evidenceSet(doc: Doc, value: unknown): string {
  return ids(value).map((id) => evidenceSignature(doc, id)).sort().join('\u0001');
}

function idSet(value: unknown): string {
  return Array.from(new Set(ids(value))).sort().join('\u0001');
}

/** A step's phase, as one identity across the two revisions (`matchPhases`). */
function phaseOf(doc: Doc, node: Rec): string {
  return doc.phaseKey(str(node.phase));
}

function labelOf(node: Rec | undefined, fallback: string): string {
  if (!node) return fallback;
  return text(node.label) || str(node.id) || fallback;
}

function nodeTitle(node: Rec): string {
  return labelOf(node, str(node.id));
}

function edgeTitle(doc: Doc, edge: Rec): string {
  const from = labelOf(doc.nodes.get(str(edge.source)), str(edge.source));
  const to = labelOf(doc.nodes.get(str(edge.target)), str(edge.target));
  const label = text(edge.label);
  return (label ? label + ' · ' : '') + from + ' → ' + to;
}

function findingTitle(finding: Rec): string {
  return text(finding.title) || str(finding.id);
}

/* ── the fields compared ─────────────────────────────────────────────── */

type Field = [word: string, read: (doc: Doc, item: Rec) => string];

const STEP_FIELDS: Field[] = [
  ['label', (_d, n) => text(n.label)],
  ['detail', (_d, n) => text(n.detail)],
  ['basis', (_d, n) => str(n.basis)],
  ['phase', (d, n) => phaseOf(d, n)],
  ['group', (_d, n) => str(n.parent)],
  ['kind', (_d, n) => text(n.kind)],
  ['evidence', (d, n) => evidenceSet(d, n.evidence)],
];

const CONNECTION_FIELDS: Field[] = [
  ['from', (_d, e) => str(e.source)],
  ['to', (_d, e) => str(e.target)],
  ['label', (_d, e) => text(e.label)],
  ['kind', (_d, e) => text(e.kind)],
  ['basis', (_d, e) => str(e.basis)],
  ['evidence', (d, e) => evidenceSet(d, e.evidence)],
];

const FINDING_FIELDS: Field[] = [
  ['title', (_d, f) => text(f.title)],
  ['description', (_d, f) => text(f.message)],
  ['severity', (_d, f) => str(f.severity)],
  ['basis', (_d, f) => str(f.basis)],
  ['what to change', (_d, f) => text(f.suggestion)],
  ['cited steps', (_d, f) => idSet(f.nodeIds)],
  ['cited connections', (_d, f) => idSet(f.edgeIds)],
  ['evidence', (d, f) => evidenceSet(d, f.evidence)],
  ['counter-evidence', (d, f) => evidenceSet(d, f.counterEvidence)],
];

function compareGroup(
  kind: ChangeKind,
  before: Map<string, Rec>,
  after: Map<string, Rec>,
  prev: Doc,
  next: Doc,
  fields: Field[],
  title: (doc: Doc, item: Rec) => string,
): ChangeGroup {
  const out: ChangeGroup = { added: [], removed: [], changed: [] };
  for (const [id, item] of after) {
    const old = before.get(id);
    if (!old) {
      out.added.push({ kind, id, status: 'added', fields: [], title: title(next, item) });
      continue;
    }
    const differ = fields.filter(([, read]) => read(prev, old) !== read(next, item)).map(([word]) => word);
    if (differ.length) out.changed.push({ kind, id, status: 'changed', fields: differ, title: title(next, item) });
  }
  for (const [id, item] of before) {
    if (!after.has(id)) out.removed.push({ kind, id, status: 'removed', fields: [], title: title(prev, item) });
  }
  return out;
}

/**
 * Compare the revision this panel showed before (`prev`) with the one it shows now (`next`), by
 * id. Added and changed items come in the new revision's document order, removed items in the old
 * one's.
 */
export function revisionDiff(prev: WorkflowDocument, next: WorkflowDocument): RevisionDiff {
  const a = readDoc(prev);
  const b = readDoc(next);
  const phases = matchPhases(a, b);
  const steps = compareGroup('node', a.nodes, b.nodes, a, b, STEP_FIELDS, (_d, n) => nodeTitle(n));
  const connections = compareGroup('edge', a.edges, b.edges, a, b, CONNECTION_FIELDS, edgeTitle);
  const findings = compareGroup('issue', a.findings, b.findings, a, b, FINDING_FIELDS, (_d, f) => findingTitle(f));
  const marks = new Map<string, ItemChange>();
  for (const group of [steps, connections, findings]) for (const item of group.added.concat(group.changed)) marks.set(changeKey(item.kind, item.id), item);
  const revisionId = (doc: WorkflowDocument): string => (doc && doc.revision && typeof doc.revision.id === 'string' ? doc.revision.id : '');
  return { since: revisionId(prev), revision: revisionId(next), steps, connections, findings, phases, marks };
}

/* ── words ───────────────────────────────────────────────────────────── */

/** "label", "label and evidence", "label, detail and evidence". */
export function fieldList(fields: readonly string[]): string {
  if (fields.length <= 1) return fields.join('');
  return fields.slice(0, -1).join(', ') + ' and ' + fields[fields.length - 1];
}

/** The tag a changed or added claim carries: "new" or "changed". */
export function changeTagText(change: Pick<ItemChange, 'status'>): string {
  return change.status === 'added' ? 'new' : change.status === 'changed' ? 'changed' : 'removed';
}

/** What a screen reader hears for the tag: "new in this revision", "changed in this revision: label and evidence". */
export function changeSpoken(change: Pick<ItemChange, 'status' | 'fields'>): string {
  if (change.status === 'added') return 'new in this revision';
  return 'changed in this revision' + (change.fields.length ? ': ' + fieldList(change.fields) : '');
}

/** The tag's tooltip and the Selection pane's line: "New since revision r1." or "Changed since revision r1: label and evidence." */
export function changeSentence(change: Pick<ItemChange, 'status' | 'fields'>, since: string): string {
  if (change.status === 'added') return 'New since revision ' + since + '.';
  return 'Changed since revision ' + since + (change.fields.length ? ': ' + fieldList(change.fields) : '') + '.';
}

/**
 * The comparison a `workflow` frame carries, as the viewer trusts it: `previous` only when it is a
 * 1.0 document whose id is the new document's `revision.parent` (and not the new id itself);
 * `replaced` only as a revision id string when there is no `previous`. Anything else is ignored.
 */
export interface WorkflowComparison {
  previous?: WorkflowDocument;
  replaced?: string;
}

/** The longest revision id the viewer accepts from a frame (the contract's id pattern is shorter). */
const MAX_REVISION_ID = 200;

export function sanitizeComparison(document: WorkflowDocument | null | undefined, value: { previous?: unknown; replaced?: unknown } | null | undefined): WorkflowComparison {
  if (!value || typeof value !== 'object' || !document || !document.revision) return {};
  const parent = document.revision.parent;
  const own = document.revision.id;
  const previous = value.previous as WorkflowDocument | undefined;
  if (
    previous && typeof previous === 'object' && !Array.isArray(previous) && previous.workflowVersion === '1.0' &&
    previous.revision && typeof previous.revision.id === 'string' && typeof parent === 'string' &&
    previous.revision.id === parent && previous.revision.id !== own
  ) return { previous };
  const replaced = value.replaced;
  if (typeof replaced === 'string' && replaced && replaced.length <= MAX_REVISION_ID && replaced !== own && replaced !== parent) return { replaced };
  return {};
}
