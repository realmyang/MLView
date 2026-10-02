/**
 * The Selection tab (viewer M2): the claim first, then what backs it.
 *
 * A step's pane, in reading order:
 *
 *   eyebrow (phase number and label · kind · parent group) · title · a basis sentence (inferred or
 *   unresolved only) · the full authored detail · findings on this step, with What to change ·
 *   numbered quotes with line numbers, a freshness badge each and Open · "Comes from" and "Feeds"
 *   as sentences · Challenge and Refine… · one limitations link
 *
 * A group's pane (viewer M2 review, M2R-6) reads like a step's, for what the group stands for: the
 * findings of every step inside it (what its badge counts), the steps it contains, and the
 * connections that cross its edge.
 *
 * A connection's pane: its label, from → to, its kind in words, its basis, its findings, its quotes.
 * A finding's pane: severity, F-label and id, title, description, What to change, the steps and
 * connections it cites, and its quotes (supporting and counter-evidence).
 *
 * In the bottom sheet at 620 px and wider the pane has two columns: the claim, its findings and its
 * connections on the left; the quotes and the actions on the right (`columns: 2`). The DOM is built
 * in the order it is shown, so a screen reader hears what a sighted reader sees.
 *
 * Everything here is authored text or derived mechanically from authored ids and the host's hash
 * check: nothing is categorised, scored or called. The panel never says a claim is right.
 */

import { add, button, el, fileLine, on } from '../dom.js';
import { authoredCell, locTitle } from '../notebook.js';
import { severityGlyph } from '../markers.js';
import { basisChip } from './evidence.js';
import { stampPhase } from '../render/phase.js';
import { basisTag, detailSpoken } from '../render/nodes.js';
import { edgeKindText } from '../render/edges.js';
import { issueStaleReasons, staleChipText, suggestionBlock, wireOpenControl } from './issuelist.js';
import { allElsewhere, staleQuotes, STALE_TEXT } from '../freshness.js';
import { uiIcon } from '../icons.js';
import { walkQuoteText } from '../walk.js';
import type { WalkOpenStatus } from '../walk.js';
import type { GraphIndex } from '../layout/model.js';
import type { Issue, Loc, MLEdge, MLNode, RelatedLoc, Sel, StaleReason, WorkflowDocument } from '../types.js';

/**
 * Viewer M1: what a matching quote does and does not show (automation-bias research: readers take
 * a citation as support unless told otherwise). Shown once per pane, under the quotes heading.
 */
export const EVIDENCE_CAPTION =
  'A matching quote shows these lines exist unchanged since publishing. Whether they support the claim is for you to judge.';

export interface SelectionPaneState {
  index: GraphIndex;
  keep(issue: Issue): boolean;
  node: MLNode | null;
  edge: MLEdge | null;
  issue: Issue | null;
  /** Two in the bottom sheet at 620 px and wider (claim | evidence), else one. */
  columns: 1 | 2;
  /** The displayed revision: its published hashes decide "unchanged" against "not checked". */
  document: WorkflowDocument | null;
  staleReason?(file: string): StaleReason | undefined;
  /**
   * Viewer M3: while the review walk shows this claim, which of its quotes the walk asked the
   * editor for, and what became of it (`applyWalkMark`).
   */
  walk?: WalkMark | null;
}

/** Viewer M3: the review walk's quote in the pane and what the editor beside shows for it. */
export interface WalkMark {
  quote: number;
  status: WalkOpenStatus;
}

export interface SelectionPaneCallbacks {
  /** Open a cited range beside the panel; `focusEditor` (Alt) moves focus to the editor. */
  onOpen(loc: Loc | RelatedLoc, focusEditor?: boolean): void;
  onShowNode(id: string): void;
  onShowEdge(id: string): void;
  onShowIssue(id: string): void;
  onChallenge(): void;
  onRefine(): void;
  onShowLimitations(): void;
}

const plural = (n: number, one: string, many: string): string => n + ' ' + (n === 1 ? one : many);

/**
 * Viewer M1: a short sentence for the two bases that need one, after a tag naming the basis.
 * `observed` gets nothing: the common case carries no mark (viewer M2).
 */
export function basisSentence(basis: string | undefined, noun: 'step' | 'group' | 'connection' | 'finding'): string {
  if (basis === 'inferred') return 'Reasoned from the cited code and stated assumptions; the quotes do not show all of it directly.';
  if (basis === 'unresolved') return 'The evidence does not settle this claim. It does not mean the ' + noun + ' is missing.';
  return '';
}

/** Build the pane for the current selection into `panel` (already cleared). */
export function renderSelectionPane(panel: HTMLElement, s: SelectionPaneState, cb: SelectionPaneCallbacks): void {
  const root = add(panel, el('div', 'mlv-sel'));
  root.setAttribute('data-columns', String(s.columns));
  if (s.issue) {
    root.setAttribute('data-kind', 'finding');
    issuePane(root, s.issue, s, cb);
  } else if (s.edge) {
    root.setAttribute('data-kind', 'connection');
    edgePane(root, s.edge, s, cb);
  } else if (s.node) {
    root.setAttribute('data-kind', s.index.isGroup(s.node.id) ? 'group' : 'step');
    nodePane(root, s.node, s, cb);
  } else {
    add(root, el('p', 'mlv-empty-note', 'Select a step, a connection or a finding to read its claim beside its evidence.'));
  }
  applyWalkMark(panel, s.walk || null);
}

/**
 * Viewer M3: mark the review walk's quote in the pane under `container`: a left rule on that quote
 * (`.mlv-quote.is-walk`, `data-walk-status`) and one line under it saying what the editor beside
 * shows: opening, highlighted, or why it was not opened (the host's reason). Any older mark goes.
 * Updated in place when the host answers, so the pane keeps its scroll and focus. `reveal` (the
 * walk moved to another quote of the same claim, `[` or `]`) scrolls the pane the least distance
 * that shows the marked quote, at once (no smooth scroll, so reduced motion needs nothing more).
 */
export function applyWalkMark(container: HTMLElement | null, mark: WalkMark | null, reveal = false): void {
  if (!container) return;
  for (const old of Array.from(container.querySelectorAll('.mlv-quote.is-walk'))) {
    old.classList.remove('is-walk');
    old.removeAttribute('data-walk-status');
    const line = old.querySelector('.mlv-quote__walk');
    if (line) line.remove();
  }
  if (!mark) return;
  const quotes = container.querySelectorAll('.mlv-sel .mlv-insp__source-evidence > .mlv-quote');
  const li = quotes[mark.quote] as HTMLElement | undefined;
  if (!li) return;
  li.classList.add('is-walk');
  li.setAttribute('data-walk-status', mark.status.state);
  const text = walkQuoteText(mark.status);
  if (text) {
    const line = el('p', 'mlv-quote__walk');
    if (mark.status.state === 'blocked' || mark.status.state === 'failed') line.appendChild(uiIcon('warning', 12));
    add(line, el('span', '', text));
    const head = li.querySelector('.mlv-quote__head');
    if (head && head.nextSibling) li.insertBefore(line, head.nextSibling);
    else li.appendChild(line);
  }
  if (reveal && typeof li.scrollIntoView === 'function') li.scrollIntoView({ block: 'nearest' });
}

/** The claim column and the evidence column; one container when the pane has one column. */
function columns(root: HTMLElement, s: SelectionPaneState): { claim: HTMLElement; evidence: HTMLElement } {
  if (s.columns === 1) return { claim: root, evidence: root };
  const claim = add(root, el('div', 'mlv-sel__col mlv-sel__col--claim'));
  const evidence = add(root, el('div', 'mlv-sel__col mlv-sel__col--evidence'));
  return { claim, evidence };
}

/* ── a step ───────────────────────────────────────────────────────────── */

function nodePane(root: HTMLElement, node: MLNode, s: SelectionPaneState, cb: SelectionPaneCallbacks): void {
  const index = s.index;
  const group = index.isGroup(node.id);
  const noun = group ? 'group' : 'step';
  const { claim, evidence } = columns(root, s);
  // Eyebrow: phase number and label · kind · parent group. Never the phase id (it stays on
  // `data-stage`), never the adapter's `unknown` kind.
  const eyebrow = add(claim, el('p', 'mlv-insp__eyebrow'));
  const phaseAt = index.phaseIndexOf(node.stage);
  const phaseLabel = node.phaseLabel || stageLabel(index, node.stage);
  const phase = add(eyebrow, el('span', 'mlv-insp__phase'));
  phase.setAttribute('data-stage', node.stage);
  stampPhase(phase, phaseAt);
  add(phase, el('span', 'mlv-insp__phasedot')).setAttribute('aria-hidden', 'true');
  add(phase, el('span', '', (phaseAt + 1) + ' · ' + phaseLabel));
  phase.title = 'Phase ' + (phaseAt + 1) + ': ' + phaseLabel;
  if (node.kind && node.kind !== 'unknown') eyebrowPart(eyebrow, 'mlv-insp__kind', node.kind);
  const parentId = index.parentOf.get(node.id);
  const parent = parentId ? index.nodeById.get(parentId) : undefined;
  if (parent) eyebrowPart(eyebrow, 'mlv-insp__parent', 'in ' + (parent.label || parent.id));

  add(claim, el('h4', 'mlv-insp__title', node.label || node.qualname));
  appendBasis(claim, node.basis, noun);
  // Viewer M1: the claim itself, in full, before anything else.
  if (node.detail) add(claim, el('p', 'mlv-insp__detail', node.detail));

  // A group stands for its steps: their findings (what its badge counts, each once), and the steps.
  if (group) {
    appendFindings(claim, index.subtreeIssues(node.id, s.keep), 'Findings in this group', s, cb);
    appendMembers(claim, node, s, cb);
  } else appendFindings(claim, index.issuesOf(node.id, s.keep), 'Findings on this step', s, cb);
  const flow = () => (group ? appendGroupFlow(claim, node, s, cb) : appendFlow(claim, node, s, cb));
  if (s.columns === 1) {
    appendQuotes(evidence, node.evidenceLocs || [], s, cb, noun);
    flow();
  } else {
    flow();
    appendQuotes(evidence, node.evidenceLocs || [], s, cb, noun);
  }
  appendActions(evidence, cb);
  appendLimitations(evidence, s, cb);
}

/* ── a connection ─────────────────────────────────────────────────────── */

function edgePane(root: HTMLElement, edge: MLEdge, s: SelectionPaneState, cb: SelectionPaneCallbacks): void {
  const index = s.index;
  const { claim, evidence } = columns(root, s);
  const eyebrow = add(claim, el('p', 'mlv-insp__eyebrow'));
  add(eyebrow, el('span', '', 'Connection'));
  // Issue 9: the authored kind word, never the adapter's `unknown`; a normalised synonym names
  // what the author wrote as well. Viewer M2: the line no longer shows the kind, so it is said here.
  const kind = eyebrowPart(eyebrow, 'mlv-insp__edgekind', edgeKindText(edge.kind) + (edge.authoredKind ? ' · authored as ' + edge.authoredKind : ''));
  kind.setAttribute('data-edge-kind', edge.kind);
  kind.title = 'Kind of connection, as the author named it';

  add(claim, el('h4', 'mlv-insp__title', edge.label || 'Connection'));
  const source = index.nodeById.get(edge.source);
  const target = index.nodeById.get(edge.target);
  // From → to, each end a link to its step: the one thing the title does not say.
  const ends = add(claim, el('p', 'mlv-insp__ends'));
  ends.appendChild(stepLink(edge.source, source, cb));
  ends.appendChild(document.createTextNode(' → '));
  ends.appendChild(stepLink(edge.target, target, cb));
  appendBasis(claim, edge.basis, 'connection');
  // The connection's hover card lists these too; this is the keyboard's and the screen reader's way.
  appendFindings(claim, index.issuesOfEdge(edge.id, s.keep), 'Findings on this connection', s, cb);
  appendQuotes(evidence, edge.evidenceLocs || [], s, cb, 'connection');
  appendActions(evidence, cb);
  appendLimitations(evidence, s, cb);
}

/* ── a finding ────────────────────────────────────────────────────────── */

function issuePane(root: HTMLElement, issue: Issue, s: SelectionPaneState, cb: SelectionPaneCallbacks): void {
  const index = s.index;
  const { claim, evidence } = columns(root, s);
  // Eyebrow: severity, the short label the badges print and the real id Refine uses. The title is
  // the heading below, once.
  const eyebrow = add(claim, el('div', 'mlv-insp__eyebrow mlv-insp__issue-head'));
  eyebrow.setAttribute('data-issue-id', issue.id);
  eyebrow.appendChild(severityGlyph(issue.severity, 14, ''));
  add(eyebrow, el('span', 'mlv-insp__severity', capitalise(issue.severity) + ' finding'));
  if (issue.short) {
    const short = add(eyebrow, el('span', 'mlv-insp__short', issue.short));
    short.title = issue.short + ' is this finding\'s number in this revision; its id is ' + issue.code + '.';
  }
  add(eyebrow, el('span', 'mlv-mono', issue.code));
  const chip = basisChip(issue);
  if (chip) eyebrow.appendChild(chip);

  add(claim, el('h4', 'mlv-insp__title', issue.title));
  appendBasis(claim, issue.basis, 'finding');
  if (issue.message) add(claim, el('p', 'mlv-insp__detail mlv-insp__message', issue.message));
  const suggestion = suggestionBlock(issue, 'h5');
  if (suggestion) claim.appendChild(suggestion);

  // The steps and connections it cites. Selecting the finding framed all of them on the canvas.
  const cited = add(claim, el('section', 'mlv-insp__section mlv-insp__cited'));
  cited.setAttribute('data-section', 'cited');
  const steps = issue.nodeIds.filter((id) => index.nodeById.has(id));
  const edges = issue.edgeIds.filter((id) => index.edgeById.has(id));
  if (!steps.length && !edges.length) {
    add(cited, el('p', 'mlv-insp__note', 'This finding cites no step or connection: it is about the workflow as a whole.'));
  }
  if (steps.length) {
    cited.appendChild(heading('Cited steps', plural(steps.length, 'step', 'steps')));
    const list = add(cited, el('ul', 'mlv-insp__links'));
    for (const id of steps) {
      const node = index.nodeById.get(id)!;
      const li = add(list, el('li'));
      li.appendChild(stepLink(id, node, cb));
      const phaseLabel = node.phaseLabel || stageLabel(index, node.stage);
      add(li, el('span', 'mlv-insp__aside', ' · ' + (index.phaseIndexOf(node.stage) + 1) + ' · ' + phaseLabel));
    }
  }
  if (edges.length) {
    cited.appendChild(heading('Cited connections', plural(edges.length, 'connection', 'connections')));
    const list = add(cited, el('ul', 'mlv-insp__links'));
    for (const id of edges) {
      const edge = index.edgeById.get(id)!;
      const li = add(list, el('li'));
      const link = button('mlv-link mlv-insp__flow-edge', edge.label || 'connection', 'Select the connection ' + connectionName(index, edge));
      link.setAttribute('data-edge-id', edge.id);
      on(link, 'click', () => cb.onShowEdge(edge.id));
      li.appendChild(link);
      add(li, el('span', 'mlv-insp__aside', ' · ' + endsText(index, edge)));
    }
  }

  // Its quotes: the supporting evidence, then any counter-evidence, numbered as one list.
  const related = issue.relatedLocs || [];
  appendQuoteList(evidence, related, s, cb, {
    noun: 'finding',
    role: (loc) => (loc as RelatedLoc).role || 'Supporting evidence',
    staleNote: () => {
      const stale = issueStaleReasons(issue, s.staleReason);
      if (!stale.length) return '';
      return allElsewhere(stale)
        ? 'This finding ' + staleChipText(stale) + '; those jumps are blocked. The notice above says which folder to add.'
        : 'This finding ' + staleChipText(stale) + ' since publishing; those jumps are blocked.';
    },
  });
  appendActions(evidence, cb);
  appendLimitations(evidence, s, cb);
}

/* ── parts ────────────────────────────────────────────────────────────── */

/** " · part" inside an eyebrow. */
function eyebrowPart(eyebrow: HTMLElement, cls: string, text: string): HTMLElement {
  add(eyebrow, el('span', 'mlv-insp__sep', ' · ')).setAttribute('aria-hidden', 'true');
  return add(eyebrow, el('span', cls, text));
}

/**
 * The basis once, for an exception only: its tag word, then what it means. A finding's pane names
 * its basis in the eyebrow's chip already, so its sentence has no tag.
 */
function appendBasis(parent: HTMLElement, basis: string | undefined, noun: 'step' | 'group' | 'connection' | 'finding'): void {
  const sentence = basisSentence(basis, noun);
  if (!sentence) return;
  const p = add(parent, el('p', 'mlv-insp__basis'));
  p.setAttribute('data-basis', basis || '');
  const tag = noun === 'finding' ? null : basisTag(basis, noun);
  if (tag) {
    // The pane's tag is read out (the canvas's is aria-hidden: the card's name says it).
    tag.removeAttribute('aria-hidden');
    tag.removeAttribute('title');
    p.appendChild(tag);
    p.appendChild(document.createTextNode(' '));
  }
  add(p, el('span', '', sentence));
}

/** A section heading with its count, which names its unit. */
function heading(text: string, count?: string): HTMLElement {
  const h = el('h5', 'mlv-rail__heading');
  add(h, el('span', 'mlv-rail__headtext', text));
  if (count) add(h, el('span', 'mlv-rail__count', count));
  return h;
}

/** The findings on a step or connection: each with its message and What to change. */
function appendFindings(parent: HTMLElement, issues: Issue[], title: string, s: SelectionPaneState, cb: SelectionPaneCallbacks): void {
  if (!issues.length) return;
  const section = add(parent, el('section', 'mlv-insp__section'));
  section.setAttribute('data-section', 'findings');
  section.appendChild(heading(title, plural(issues.length, 'finding', 'findings')));
  for (const issue of issues) {
    const box = add(section, el('div', 'mlv-insp__issue'));
    box.setAttribute('data-issue-id', issue.id);
    const head = add(box, el('div', 'mlv-insp__issue-head'));
    head.appendChild(severityGlyph(issue.severity, 14, ''));
    if (issue.short) {
      const short = add(head, el('span', 'mlv-insp__short', issue.short));
      short.title = issue.short + ' is this finding\'s number in this revision; its id is ' + issue.code + '.';
    }
    // The title selects the finding: its own pane has its quotes and every step it cites.
    const title = button('mlv-link mlv-insp__issue-title', issue.title, 'Select finding ' + (issue.short ? issue.short + ', ' : '') + issue.title);
    on(title, 'click', () => cb.onShowIssue(issue.id));
    head.appendChild(title);
    const chip = basisChip(issue);
    if (chip) head.appendChild(chip);
    // Viewer M2 live fix: the real id on its own muted line under the title. Set beside the title
    // in a 360 px rail it had a column a few letters wide and broke letter by letter
    // ("f-plot-/not-/random").
    add(box, el('p', 'mlv-insp__issue-id mlv-mono', issue.code));
    if (issue.message) add(box, el('p', 'mlv-insp__line', issue.message));
    const suggestion = suggestionBlock(issue, 'h6');
    if (suggestion) box.appendChild(suggestion);
    const stale = issueStaleReasons(issue, s.staleReason);
    if (stale.length) {
      box.classList.add('is-stale');
      const note = add(box, el('p', 'mlv-insp__stale-note'));
      note.appendChild(uiIcon('warning', 12));
      add(note, el('span', '', 'This finding ' + staleChipText(stale) + (allElsewhere(stale) ? '.' : ' since publishing.')));
    }
  }
}

/** A step's, group's or connection's quotes, with the previous / next walk M1 added. */
function appendQuotes(parent: HTMLElement, locations: Loc[], s: SelectionPaneState, cb: SelectionPaneCallbacks, noun: 'step' | 'group' | 'connection'): void {
  appendQuoteList(parent, locations, s, cb, {
    noun,
    nav: true,
    staleNote: () => {
      const reasonOf = (loc: Loc): StaleReason | undefined => (s.staleReason && loc.file ? s.staleReason(loc.file) : undefined);
      const quotes = staleQuotes(locations, (file) => !!(s.staleReason && s.staleReason(file)));
      if (!quotes.stale) return '';
      // Viewer M1: what the marks below mean, in words, before the list. Nothing in MLView checks
      // a claim, so the note says what the reader can do, not that a check was skipped (COPY-2).
      const reasons = locations.map(reasonOf).filter((reason): reason is StaleReason => !!reason);
      const count = quotes.stale + ' of ' + quotes.total + (quotes.total === 1 ? ' quote cites ' : ' quotes cite ');
      return allElsewhere(reasons)
        ? count + 'a file that is not under the workspace root but is unchanged in another folder; those jumps are blocked. The notice above says which folder to add.'
        : count + 'a file that changed or went missing since publishing; those jumps are blocked. To compare the claim with the code as it is now, ask the assistant for a fresh revision.';
    },
  });
}

interface QuoteListOptions {
  noun: 'step' | 'group' | 'connection' | 'finding';
  /** The previous / next buttons (a step's and a connection's own evidence). */
  nav?: boolean;
  /** A label per quote (a finding's supporting or counter-evidence). */
  role?(loc: Loc | RelatedLoc): string;
  staleNote(): string;
}

/** The numbered quotes: heading with count, the trust caption, the stale note, then each quote. */
function appendQuoteList(parent: HTMLElement, locations: (Loc | RelatedLoc)[], s: SelectionPaneState, cb: SelectionPaneCallbacks, o: QuoteListOptions): void {
  const section = add(parent, el('section', 'mlv-insp__section mlv-insp__quotes'));
  section.setAttribute('data-section', 'quotes');
  if (!locations.length) {
    section.appendChild(heading('Source evidence', 'no quotes'));
    add(section, el('p', 'mlv-empty-note mlv-insp__no-evidence',
      'No source evidence was authored for this ' + o.noun + '. Its basis and the coverage limitations describe what remains uncertain.'));
    return;
  }
  section.appendChild(heading('Source evidence', plural(locations.length, 'quote', 'quotes')));
  add(section, el('p', 'mlv-insp__caption', EVIDENCE_CAPTION));
  const note = o.staleNote();
  if (note) {
    const p = add(section, el('p', 'mlv-insp__stale-note'));
    p.appendChild(uiIcon('warning', 12));
    add(p, el('span', '', note));
  }
  let active = 0;
  let update = (): void => undefined;
  if (o.nav && locations.length > 1) {
    const nav = add(section, el('div', 'mlv-insp__evidence-nav'));
    const previous = button('mlv-btn', 'Previous evidence');
    const next = button('mlv-btn', 'Next evidence');
    update = () => {
      previous.disabled = active === 0;
      next.disabled = active === locations.length - 1;
      previous.title = previous.disabled ? 'This is the first evidence item' : 'Open the previous evidence item';
      next.title = next.disabled ? 'This is the last evidence item' : 'Open the next evidence item';
    };
    on(previous, 'click', () => { if (active > 0) cb.onOpen(locations[--active]); update(); });
    on(next, 'click', () => { if (active < locations.length - 1) cb.onOpen(locations[++active]); update(); });
    nav.append(previous, next);
    update();
  }
  const list = add(section, el('ol', 'mlv-insp__related mlv-insp__source-evidence'));
  locations.forEach((loc, i) => {
    // The evidence id is on the Open control (what a test or the host's reply names), not the row.
    const li = add(list, el('li', 'mlv-quote'));
    const reason = s.staleReason && loc.file ? s.staleReason(loc.file) : undefined;
    if (reason) {
      li.classList.add('is-stale');
      li.setAttribute('data-stale', reason);
    }
    const head = add(li, el('div', 'mlv-quote__head'));
    add(head, el('span', 'mlv-quote__num', String(i + 1))).setAttribute('aria-hidden', 'true');
    const where = add(head, el('span', 'mlv-quote__loc'));
    add(where, el('span', 'mlv-quote__file', loc.file));
    add(where, el('span', 'mlv-quote__at', rangeTail(loc)));
    if (locTitle(loc)) where.title = locTitle(loc);
    if (o.role) add(head, el('span', 'mlv-quote__role', o.role(loc)));
    head.appendChild(freshnessBadge(loc, reason, s));
    const open = button('mlv-link mlv-quote__open', 'Open', 'Open ' + fileLine(loc));
    open.setAttribute('data-evidence-id', loc.evidenceId || '');
    if (!reason) open.title = 'Open ' + fileLine(loc) + ' beside the diagram and highlight the cited lines; focus stays here (Alt+click moves it).';
    // VIEWUI-8: an authored notebook citation names its zero-based cell.
    if (locTitle(loc) && !reason) open.title = locTitle(loc);
    wireOpenControl(open, loc, (target, focusEditor) => {
      active = i;
      update();
      cb.onOpen(target, focusEditor);
    }, reason);
    head.appendChild(open);
    if (loc.snippet) li.appendChild(quoteText(loc));
  });
}

/** ", line 3" or ", lines 10–12" after the file (and " › cell 34" for a notebook, counted from 0). */
function rangeTail(loc: Loc | RelatedLoc): string {
  const authored = authoredCell(loc);
  const cell = authored ? ' › cell ' + authored.cell : '';
  const end = loc.endLine && loc.endLine > loc.line ? loc.endLine : loc.line;
  return cell + (end > loc.line ? ', lines ' + loc.line + '–' + end : ', line ' + loc.line);
}

/**
 * A quote's freshness: why it is stale (a warning icon and words), or muted "unchanged" when the
 * published hashes cover its file and the host found it unchanged, or muted "not checked" when no
 * hash covers it. Never a green mark: colour is for problems only.
 */
function freshnessBadge(loc: Loc | RelatedLoc, reason: StaleReason | undefined, s: SelectionPaneState): HTMLElement {
  if (reason) {
    const badge = el('span', 'mlv-quote__fresh mlv-insp__stale');
    badge.setAttribute('data-fresh', 'stale');
    badge.setAttribute('data-stale', reason);
    badge.appendChild(uiIcon('warning', 12));
    add(badge, el('span', '', STALE_TEXT[reason]));
    return badge;
  }
  const hashed = !!(s.document && s.document.verification && loc.file && Object.prototype.hasOwnProperty.call(s.document.verification.files || {}, loc.file));
  const badge = el('span', 'mlv-quote__fresh is-muted', hashed ? 'unchanged' : 'not checked');
  badge.setAttribute('data-fresh', hashed ? 'unchanged' : 'unchecked');
  badge.title = hashed
    ? 'Unchanged means these exact lines still exist as quoted. It does not mean they support the claim.'
    : 'This revision has no published hash for this file, so MLView cannot tell whether it changed.';
  return badge;
}

/** The quote, verbatim, one line per row with its source line number. */
function quoteText(loc: Loc | RelatedLoc): HTMLElement {
  const pre = el('pre', 'mlv-quote__text');
  const lines = String(loc.snippet || '').split('\n');
  lines.forEach((line, k) => {
    const row = add(pre, el('span', 'mlv-quote__line'));
    add(row, el('span', 'mlv-quote__ln', String(loc.line + k))).setAttribute('aria-hidden', 'true');
    add(row, el('span', 'mlv-quote__code', line));
    if (k < lines.length - 1) pre.appendChild(document.createTextNode('\n'));
  });
  return pre;
}

/**
 * "Comes from" and "Feeds", one sentence per connection, from the authored edges: the other step
 * and the connection's label are links (select them), and an exception says its basis in words.
 */
function appendFlow(parent: HTMLElement, node: MLNode, s: SelectionPaneState, cb: SelectionPaneCallbacks): void {
  const index = s.index;
  const incoming = index.inEdges.get(node.id) || [];
  const outgoing = index.outEdges.get(node.id) || [];
  if (!incoming.length && !outgoing.length) return;
  const section = add(parent, el('section', 'mlv-insp__section mlv-insp__flow'));
  section.setAttribute('data-section', 'connections');
  section.appendChild(heading('Connections', plural(incoming.length + outgoing.length, 'connection', 'connections')));
  const list = add(section, el('ul', 'mlv-insp__sentences'));
  const sentence = (edge: MLEdge, direction: 'in' | 'out') => {
    const li = add(list, el('li'));
    li.setAttribute('data-direction', direction);
    const otherId = direction === 'in' ? edge.source : edge.target;
    if (otherId === node.id) {
      add(li, el('span', '', 'Loops back to this step'));
    } else {
      add(li, el('span', '', direction === 'in' ? 'Comes from ' : 'Feeds '));
      li.appendChild(stepLink(otherId, index.nodeById.get(otherId), cb));
    }
    add(li, el('span', '', ': '));
    const link = button('mlv-link mlv-insp__flow-edge', edge.label || 'an unlabelled connection', 'Select the connection ' + connectionName(index, edge));
    link.setAttribute('data-edge-id', edge.id);
    on(link, 'click', () => cb.onShowEdge(edge.id));
    li.appendChild(link);
    const basis = edge.basis === 'inferred' ? ' (inferred, not observed)' : edge.basis === 'unresolved' ? ' (unresolved)' : '';
    add(li, el('span', basis ? 'mlv-insp__flow-basis' : '', basis + '.'));
  };
  for (const edge of incoming) sentence(edge, 'in');
  // A self-edge is in both lists; say it once.
  for (const edge of outgoing) if (edge.source !== edge.target) sentence(edge, 'out');
}

/** The steps a group contains (its direct members), each a link that selects it. */
function appendMembers(parent: HTMLElement, node: MLNode, s: SelectionPaneState, cb: SelectionPaneCallbacks): void {
  const index = s.index;
  const members = index.laneChildren(node.id).filter((id) => index.nodeById.has(id));
  if (!members.length) return;
  const section = add(parent, el('section', 'mlv-insp__section'));
  section.setAttribute('data-section', 'members');
  section.appendChild(heading('Steps in this group', plural(members.length, 'step', 'steps')));
  const list = add(section, el('ul', 'mlv-insp__links'));
  for (const id of members) {
    const li = add(list, el('li'));
    li.appendChild(stepLink(id, index.nodeById.get(id), cb));
    const inner = index.descendantCount(id);
    if (inner) add(li, el('span', 'mlv-insp__aside', ' · group of ' + plural(inner, 'step', 'steps')));
  }
}

/**
 * A group's connections: the ones that cross its edge, as "Comes from" and "Feeds" sentences that
 * also name the step inside (they are what a collapsed group's card draws). Connections between
 * two steps inside the group are the steps' own.
 */
function appendGroupFlow(parent: HTMLElement, node: MLNode, s: SelectionPaneState, cb: SelectionPaneCallbacks): void {
  const index = s.index;
  const inside = new Set<string>();
  const walk = (id: string) => {
    inside.add(id);
    for (const child of index.laneChildren(id)) walk(child);
  };
  walk(node.id);
  const incoming: MLEdge[] = [];
  const outgoing: MLEdge[] = [];
  for (const edge of index.graph.edges) {
    const from = inside.has(edge.source);
    const to = inside.has(edge.target);
    if (from && to) {
      // The group's own loop is a connection of the group; any other is between its steps.
      if (edge.source === node.id && edge.target === node.id) incoming.push(edge);
      continue;
    }
    if (to) incoming.push(edge);
    else if (from) outgoing.push(edge);
  }
  if (!incoming.length && !outgoing.length) return;
  const section = add(parent, el('section', 'mlv-insp__section mlv-insp__flow'));
  section.setAttribute('data-section', 'connections');
  section.appendChild(heading('Connections across its edge', plural(incoming.length + outgoing.length, 'connection', 'connections')));
  const list = add(section, el('ul', 'mlv-insp__sentences'));
  const sentence = (edge: MLEdge, direction: 'in' | 'out') => {
    const li = add(list, el('li'));
    li.setAttribute('data-direction', direction);
    const otherId = direction === 'in' ? edge.source : edge.target;
    const innerId = direction === 'in' ? edge.target : edge.source;
    if (otherId === node.id && innerId === node.id) {
      add(li, el('span', '', 'Loops back to this group'));
    } else {
      add(li, el('span', '', direction === 'in' ? 'Comes from ' : 'Feeds '));
      li.appendChild(stepLink(otherId, index.nodeById.get(otherId), cb));
      if (innerId !== node.id) {
        add(li, el('span', '', direction === 'in' ? ' into ' : ' from '));
        li.appendChild(stepLink(innerId, index.nodeById.get(innerId), cb));
      }
    }
    add(li, el('span', '', ': '));
    const link = button('mlv-link mlv-insp__flow-edge', edge.label || 'an unlabelled connection', 'Select the connection ' + connectionName(index, edge));
    link.setAttribute('data-edge-id', edge.id);
    on(link, 'click', () => cb.onShowEdge(edge.id));
    li.appendChild(link);
    const basis = edge.basis === 'inferred' ? ' (inferred, not observed)' : edge.basis === 'unresolved' ? ' (unresolved)' : '';
    add(li, el('span', basis ? 'mlv-insp__flow-basis' : '', basis + '.'));
  };
  for (const edge of incoming) sentence(edge, 'in');
  for (const edge of outgoing) sentence(edge, 'out');
}

function appendActions(parent: HTMLElement, cb: SelectionPaneCallbacks): void {
  const actions = add(parent, el('div', 'mlv-insp__actions'));
  const challenge = button('mlv-btn mlv-insp__challenge', 'Challenge this claim', 'Copy a prompt that asks your assistant to check this claim against the code. MLView calls no model.');
  on(challenge, 'click', () => cb.onChallenge());
  const refine = button('mlv-btn mlv-insp__refine', 'Refine…', 'Copy a refinement prompt about this selection. MLView calls no model.');
  on(refine, 'click', () => cb.onRefine());
  actions.append(challenge, refine);
}

/**
 * Viewer M1: the document-wide limitations are listed once, in About; every pane says how many
 * apply and links there.
 */
function appendLimitations(parent: HTMLElement, s: SelectionPaneState, cb: SelectionPaneCallbacks): void {
  const count = (s.index.graph.diagnostics || []).filter((item) => item.kind === 'workflow_limitation').length;
  if (!count) return;
  const line = add(parent, el('p', 'mlv-insp__limits'));
  line.setAttribute('data-limitations', String(count));
  add(line, el('span', '', (count === 1 ? '1 document-wide limitation applies' : count + ' document-wide limitations apply') + ' to every claim. '));
  const show = button('mlv-link mlv-link--inline mlv-insp__limits-show', count === 1 ? 'Read it in About' : 'Read them in About');
  show.setAttribute('aria-label', count === 1 ? 'Read the document-wide limitation in About' : 'Read the ' + count + ' document-wide limitations in About');
  on(show, 'click', () => cb.onShowLimitations());
  line.appendChild(show);
}

/** A step named by its label, as a link that selects it. */
function stepLink(id: string, node: MLNode | undefined, cb: SelectionPaneCallbacks): HTMLButtonElement {
  const label = node ? node.label || node.id : id;
  const link = button('mlv-link mlv-insp__flow-step', label, 'Select the step ' + label);
  link.setAttribute('data-node-id', id);
  on(link, 'click', () => cb.onShowNode(id));
  return link;
}

function endsText(index: GraphIndex, edge: MLEdge): string {
  const source = index.nodeById.get(edge.source);
  const target = index.nodeById.get(edge.target);
  return (source ? source.label : edge.source) + ' → ' + (target ? target.label : edge.target);
}

function connectionName(index: GraphIndex, edge: MLEdge): string {
  return (edge.label ? edge.label + ', ' : '') + 'from ' + endsText(index, edge).replace(' → ', ' to ');
}

/** A phase's label from the graph's stage list, or its id when it has none. */
function stageLabel(index: GraphIndex, id: string): string {
  const stage = (index.graph.stages || []).find((item) => item.id === id);
  return (stage && stage.label) || id;
}

function capitalise(word: string): string {
  return word ? word[0].toUpperCase() + word.slice(1) : word;
}

/**
 * Viewer M2: what the live region says about a new selection while VS Code's screen-reader
 * optimisation is on: the claim first. The title, the basis when it is not observed, and the first
 * sentence of what the author wrote (a step's detail, a finding's message).
 */
export function selectionAnnouncement(index: GraphIndex, sel: Sel): string {
  const basisWords = (basis: string | undefined) => (basis === 'inferred' ? ' Inferred, not observed.' : basis === 'unresolved' ? ' Unresolved.' : '');
  if (sel.kind === 'node') {
    const node = index.nodeById.get(sel.id);
    if (!node) return '';
    const first = node.detail ? ' ' + detailSpoken(node.detail) : '';
    return 'Step: ' + (node.label || node.id) + '.' + basisWords(node.basis) + first;
  }
  if (sel.kind === 'edge') {
    const edge = index.edgeById.get(sel.id);
    if (!edge) return '';
    return 'Connection: ' + (edge.label ? edge.label + ', ' : '') + 'from ' + endsText(index, edge).replace(' → ', ' to ') + '.' + basisWords(edge.basis);
  }
  const issue = index.issueById.get(sel.id);
  if (!issue) return '';
  const first = issue.message ? ' ' + detailSpoken(issue.message) : '';
  return 'Finding ' + (issue.short ? issue.short + ', ' : '') + issue.severity + ' severity: ' + issue.title + '.' + basisWords(issue.basis) + first;
}
