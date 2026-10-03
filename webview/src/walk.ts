/**
 * The review walk's claims (viewer M3, roadmap step 11): every step, connection and finding of the
 * displayed revision once, in the canvas's drawn order, and the filters over them. Pure: no DOM,
 * no App, nothing called; everything here is the authored ids, the authored basis and the host's
 * stale files.
 *
 * ORDER (spec-reading §4.2). The lanes in phase order; in each lane its steps as the canvas draws
 * their boxes and the Outline lists them: document order, a group before the steps it contains,
 * depth first. Each step is followed by its outgoing connections in document order, then by the
 * findings whose first cited step (in this order) it is, in document order. The design gives no
 * place to a finding that cites no step (one that cites only connections, or the workflow as a
 * whole), so those come LAST, in document order. A connection whose source step the document
 * lacks also comes last; validation refuses such a document, and the walk still visits every
 * claim exactly once.
 */

import { allElsewhere } from './freshness.js';
import { authoredCell } from './notebook.js';
import type { GraphIndex } from './layout/model.js';
import type { Loc, Sel, StaleReason } from './types.js';

/** A claim is a step (node), a connection (edge) or a finding (issue), named by its authored id. */
export type Claim = Sel;

/** The walk's filters, in the order the walk bar offers them. */
export type WalkFilter = 'notObserved' | 'findings' | 'changed' | 'all';
export const WALK_FILTERS: readonly WalkFilter[] = ['notObserved', 'findings', 'changed', 'all'];

/**
 * The walk bar's words for each filter. All names its unit ("All claims 79"), as the other
 * filters' words already do (M3 review, A11Y-M3-8).
 */
export const FILTER_LABEL: Record<WalkFilter, string> = {
  notObserved: 'Not observed',
  findings: 'Findings',
  changed: 'Changed files',
  all: 'All claims',
};

/** "Not observed, 7 claims", or "All 79 claims": a filter with its count and the count's unit. */
export function filterCountText(filter: WalkFilter, n: number): string {
  const unit = n === 1 ? ' claim' : ' claims';
  return filter === 'all' ? 'All ' + n + unit : FILTER_LABEL[filter] + ', ' + n + unit;
}

/** What the live region says for the filter (nothing for All: every claim is in it). */
const FILTER_SPOKEN: Record<WalkFilter, string> = {
  notObserved: 'not observed',
  findings: 'findings',
  changed: 'changed files',
  all: '',
};

/**
 * The basis the header's "not observed" chip counts (`notObservedCounts`): inferred or unresolved.
 * One predicate for both, so the walk's Not observed filter and the header can never disagree.
 */
export function isNotObserved(basis: string | undefined): boolean {
  return !!basis && basis !== 'observed';
}

export function sameClaim(a: Claim | null | undefined, b: Claim | null | undefined): boolean {
  return !!a && !!b && a.kind === b.kind && a.id === b.id;
}

/** Every claim once, in the drawn order (see the file comment). */
export function claimOrder(index: GraphIndex): Claim[] {
  const out: Claim[] = [];
  const nodeAt = new Map<string, number>();
  const nodes: string[] = [];
  const visit = (id: string): void => {
    if (nodeAt.has(id) || !index.nodeById.has(id)) return;
    nodeAt.set(id, nodes.length);
    nodes.push(id);
    for (const child of index.laneChildren(id)) visit(child);
  };
  for (const lane of index.lanes) for (const root of index.roots(lane.id)) visit(root);
  // A step the drawn hierarchy did not reach (none can, today) still gets its turn.
  for (const node of index.graph.nodes || []) visit(node.id);

  // Each finding goes after its first cited step in this order; one that cites no step goes last.
  const homed = new Map<string, string[]>();
  const homeless: string[] = [];
  for (const issue of index.graph.issues || []) {
    let home: string | null = null;
    for (const id of issue.nodeIds || []) {
      const at = nodeAt.get(id);
      if (at !== undefined && (home === null || at < (nodeAt.get(home) as number))) home = id;
    }
    if (home === null) homeless.push(issue.id);
    else {
      const list = homed.get(home);
      if (list) list.push(issue.id);
      else homed.set(home, [issue.id]);
    }
  }

  const seenEdges = new Set<string>();
  const seenIssues = new Set<string>();
  const pushIssue = (id: string): void => {
    if (seenIssues.has(id)) return;
    seenIssues.add(id);
    out.push({ kind: 'issue', id });
  };
  for (const id of nodes) {
    out.push({ kind: 'node', id });
    for (const edge of index.outEdges.get(id) || []) {
      if (seenEdges.has(edge.id)) continue;
      seenEdges.add(edge.id);
      out.push({ kind: 'edge', id: edge.id });
    }
    for (const issueId of homed.get(id) || []) pushIssue(issueId);
  }
  for (const edge of index.graph.edges || []) {
    if (seenEdges.has(edge.id)) continue;
    seenEdges.add(edge.id);
    out.push({ kind: 'edge', id: edge.id });
  }
  for (const id of homeless) pushIssue(id);
  return out;
}

/** The claim's authored basis. */
export function claimBasis(index: GraphIndex, claim: Claim): string | undefined {
  if (claim.kind === 'node') return index.nodeById.get(claim.id)?.basis;
  if (claim.kind === 'edge') return index.edgeById.get(claim.id)?.basis;
  return index.issueById.get(claim.id)?.basis;
}

/**
 * The claim's quotes, in the order its Selection pane numbers them: a step's or connection's own
 * evidence; a finding's supporting evidence, then its counter-evidence.
 */
export function claimLocs(index: GraphIndex, claim: Claim): Loc[] {
  if (claim.kind === 'node') return index.nodeById.get(claim.id)?.evidenceLocs || [];
  if (claim.kind === 'edge') return index.edgeById.get(claim.id)?.evidenceLocs || [];
  return index.issueById.get(claim.id)?.relatedLocs || [];
}

/**
 * Whether the Changed files filter is offered: the host reports stale files and not every one is
 * only in another folder (the root hint's case, where nothing changed and the notice says which
 * folder to add). In a mix, a file in another folder counts as missing, as the status bar says.
 */
export function changedOffered(reasons: readonly StaleReason[]): boolean {
  return reasons.length > 0 && !allElsewhere(reasons);
}

export type StaleTest = (file: string) => boolean;

/** Whether `claim` belongs to `filter`. */
export function inFilter(filter: WalkFilter, index: GraphIndex, claim: Claim, isStale: StaleTest): boolean {
  if (filter === 'all') return true;
  if (filter === 'findings') return claim.kind === 'issue';
  if (filter === 'notObserved') return isNotObserved(claimBasis(index, claim));
  return claimLocs(index, claim).some((loc) => !!loc.file && isStale(loc.file));
}

/** The claims of `filter`, in the walk's order. */
export function filterClaims(order: readonly Claim[], filter: WalkFilter, index: GraphIndex, isStale: StaleTest): Claim[] {
  return order.filter((claim) => inFilter(filter, index, claim, isStale));
}

/** How many claims each filter holds. */
export function filterCounts(order: readonly Claim[], index: GraphIndex, isStale: StaleTest): Record<WalkFilter, number> {
  const counts: Record<WalkFilter, number> = { notObserved: 0, findings: 0, changed: 0, all: 0 };
  for (const claim of order) for (const filter of WALK_FILTERS) if (inFilter(filter, index, claim, isStale)) counts[filter]++;
  return counts;
}

/**
 * The filters the walk bar offers: All always; the others only when they hold a claim (as the
 * header hides "not observed" when nothing is), and Changed files only while it is offered at all.
 */
export function offeredFilters(counts: Record<WalkFilter, number>, changed: boolean): WalkFilter[] {
  return WALK_FILTERS.filter((filter) => filter === 'all' || (counts[filter] > 0 && (filter !== 'changed' || changed)));
}

/**
 * Where a walk over `list` starts or continues for `anchor`: the anchor itself when the list holds
 * it; else the first claim after it in the drawn order; else (nothing comes after it) the list's
 * last claim. No anchor: the first claim. -1 for an empty list.
 */
export function positionFor(list: readonly Claim[], anchor: Claim | null | undefined, order: readonly Claim[]): number {
  if (!list.length) return -1;
  if (!anchor) return 0;
  const exact = list.findIndex((claim) => sameClaim(claim, anchor));
  if (exact >= 0) return exact;
  const rank = new Map<string, number>();
  order.forEach((claim, i) => rank.set(claim.kind + ':' + claim.id, i));
  const at = rank.get(anchor.kind + ':' + anchor.id);
  if (at === undefined) return 0;
  const after = list.findIndex((claim) => (rank.get(claim.kind + ':' + claim.id) ?? -1) > at);
  return after >= 0 ? after : list.length - 1;
}

/** "Step", "Group", "Connection" or "Finding": what the claim is, in the viewer's words. */
export function claimNoun(index: GraphIndex, claim: Claim): string {
  if (claim.kind === 'node') return index.isGroup(claim.id) ? 'Group' : 'Step';
  return claim.kind === 'edge' ? 'Connection' : 'Finding';
}

function endsOf(index: GraphIndex, claim: Claim): { from: string; to: string } | null {
  const edge = index.edgeById.get(claim.id);
  if (!edge) return null;
  const from = index.nodeById.get(edge.source);
  const to = index.nodeById.get(edge.target);
  return { from: from ? from.label || from.id : edge.source, to: to ? to.label || to.id : edge.target };
}

/** The claim's authored title: a step's label, a connection's label (or its ends), a finding's F label and title. */
export function claimTitle(index: GraphIndex, claim: Claim): string {
  if (claim.kind === 'node') {
    const node = index.nodeById.get(claim.id);
    return node ? node.label || node.id : claim.id;
  }
  if (claim.kind === 'edge') {
    const edge = index.edgeById.get(claim.id);
    const ends = endsOf(index, claim);
    if (!edge || !ends) return claim.id;
    return (edge.label ? edge.label + ' · ' : '') + ends.from + ' → ' + ends.to;
  }
  const issue = index.issueById.get(claim.id);
  return issue ? (issue.short ? issue.short + ' ' : '') + issue.title : claim.id;
}

/** The same title for the live region: a connection reads "label, from A to B", never an arrow. */
function spokenTitle(index: GraphIndex, claim: Claim): string {
  if (claim.kind !== 'edge') return claimTitle(index, claim);
  const edge = index.edgeById.get(claim.id);
  const ends = endsOf(index, claim);
  if (!edge || !ends) return claim.id;
  return (edge.label ? edge.label + ', ' : '') + 'from ' + ends.from + ' to ' + ends.to;
}

/**
 * The live region's line for one step of the walk: "Claim 3 of 16, not observed: Step Load
 * batches, inferred." The basis is said only when it is not observed; the filter only when it is
 * not All.
 */
export function walkAnnouncement(position: number, total: number, filter: WalkFilter, index: GraphIndex, claim: Claim): string {
  const basis = claimBasis(index, claim);
  const said = FILTER_SPOKEN[filter];
  return 'Claim ' + (position + 1) + ' of ' + total + (said ? ', ' + said : '') + ': ' +
    claimNoun(index, claim) + ' ' + spokenTitle(index, claim) + (isNotObserved(basis) ? ', ' + basis : '') + '.';
}

/** "train.py · lines 12–14", or "nb.ipynb · cell 24 · lines 1–3" (the cell counted from 0, as recorded). */
export function walkLocText(loc: Loc): string {
  const end = loc.endLine && loc.endLine > loc.line ? loc.endLine : loc.line;
  const lines = end > loc.line ? 'lines ' + loc.line + '–' + end : 'line ' + loc.line;
  const cell = authoredCell(loc);
  return loc.file + (cell ? ' · cell ' + cell.cell : '') + ' · ' + lines;
}

/**
 * What the editor beside shows for the walk's current claim, as far as the viewer knows: nothing
 * to open (`none`: the claim cites no lines), no way to open (`unavailable`: the host cannot open
 * source), not asked yet (`idle`: restored, or the walk followed a click; Enter opens), asked
 * (`opening`), shown and highlighted (`done`, the host said so), not opened (`blocked`, with the
 * host's reason, or the viewer's own for a file the host already reported stale) or `failed`.
 */
export type WalkOpenState = 'none' | 'unavailable' | 'idle' | 'opening' | 'done' | 'blocked' | 'failed';

export interface WalkOpenStatus {
  state: WalkOpenState;
  /**
   * `opening` and `done`: the open asked VS Code to move the keyboard focus to the editor
   * (Alt+Enter, Alt+click). Absent when the focus stays on the diagram (M3 review, A11Y-M3-3).
   */
  focusEditor?: boolean;
  /** The quote the editor is asked for (absent for `none` and `unavailable`). */
  loc?: Loc;
  /** `blocked` and `failed`: the sentence to show, with the reason and that nothing was opened. */
  message?: string;
  /** The quote's place among the claim's quotes (0-based), and how many there are. */
  quote: number;
  quotes: number;
}

/** "(quote 2 of 3)" when the claim has more than one quote. */
function quoteOf(s: WalkOpenStatus): string {
  return s.quotes > 1 ? ' (quote ' + (s.quote + 1) + ' of ' + s.quotes + ')' : '';
}

/**
 * The walk bar's editor line: "In the editor beside: train.py · lines 12–14, highlighted. Focus
 * stays here." It claims only what the host answered (VW-10): `opening` says it was asked, and a
 * blocked open says why nothing was opened. An open that moved the focus (Alt+Enter) says so.
 */
export function walkEditorText(s: WalkOpenStatus): string {
  const where = s.loc ? walkLocText(s.loc) + quoteOf(s) : '';
  switch (s.state) {
    case 'none': return 'This claim cites no lines, so nothing is opened for it.';
    case 'unavailable': return 'This view cannot open source files.';
    case 'idle': return 'Enter shows ' + where + ' in the editor beside.';
    case 'opening': return 'Opening in the editor beside: ' + where + '…';
    case 'done': return 'In the editor beside: ' + where + ', highlighted. ' + (s.focusEditor ? 'Focus moved to the editor.' : 'Focus stays here.');
    default: return (s.quotes > 1 ? 'Quote ' + (s.quote + 1) + ' of ' + s.quotes + ': ' : '') + (s.message || 'Not opened.');
  }
}

/** The short line under the walk's quote in the Selection pane. */
export function walkQuoteText(s: WalkOpenStatus): string {
  switch (s.state) {
    case 'idle': return 'Enter shows these lines in the editor beside.';
    case 'opening': return 'Opening in the editor beside…';
    case 'done': return s.focusEditor ? 'In the editor beside, highlighted; the focus moved there.' : 'In the editor beside, highlighted.';
    case 'blocked':
    case 'failed': return s.message || 'Not opened.';
    default: return '';
  }
}

/**
 * What the live region says for an open the host did not do: its message as it is when it already
 * says nothing was opened ("…; not opened."), else with "Not opened: " or "Failed: " before it, so
 * no announcement says "not opened" twice (M3 review, A11Y-M3-8).
 */
export function walkResultAnnouncement(outcome: 'blocked' | 'failed', message: string): string {
  if (/\bnot opened\b/i.test(message)) return message;
  return (outcome === 'blocked' ? 'Not opened: ' : 'Failed: ') + message;
}
