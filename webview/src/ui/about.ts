/**
 * The About tab (viewer M2): the revision's authored request and coverage, and nothing else.
 *
 *   Changes since <id>     viewer M4 (step 16), only after a new revision replaced the one this
 *                          panel showed: the steps, connections and findings added, removed or
 *                          changed, by id (`revisiondiff.ts`); or one line saying why none are listed
 *   Asked                  `request.question`, clamped, with Show all
 *   What the model traced  `coverage.summary`, split into paragraphs at its own run-in heads
 *                          ("Data:", "Model:" …), only when it has at least three; else as written
 *   Coverage               the status in plain words, then the limitations, listed once
 *   Scope                  `request.scope` and the entrypoints
 *   Run configuration      `request.configuration`, with its `k=v` tokens in monospace
 *   Cited files            every file the evidence cites, with its freshness
 *   Provenance             host, model, revision and publication time, and what MLView checks
 *
 * It replaces the request and coverage details that opened over the diagram from the header. The
 * split is typography over the author's own words: no sentence is added, reworded, sorted or
 * classified, and a summary without three heads is shown as one paragraph.
 */

import { add, button, el, on } from '../dom.js';
import { uiIcon } from '../icons.js';
import { STALE_TEXT } from '../freshness.js';
import { changeTagText, fieldList, markedTotal } from '../revisiondiff.js';
import type { ChangeGroup, ChangeKind, ItemChange, RevisionDiff } from '../revisiondiff.js';
import type { GraphIndex } from '../layout/model.js';
import type { StaleReason, WorkflowDocument } from '../types.js';

export interface AboutPaneState {
  document: WorkflowDocument | null;
  staleReason?(file: string): StaleReason | undefined;
  /**
   * Viewer M4 (step 16): the changes since the revision this panel showed before (the host sent it
   * because the displayed revision names it as its parent), or null.
   */
  changes?: RevisionDiff | null;
  /** Viewer M4: the revision this panel showed before, when the displayed one does not follow it. */
  replaced?: string | null;
  /** The displayed revision's index: the F-labels of added and changed findings. */
  index?: GraphIndex | null;
  /** A link in Changes: select that step, connection or finding. */
  onShowChange?(kind: ChangeKind, id: string): void;
  /** Changes' Review button: walk the claims added or changed in this revision. */
  onReviewChanges?(): void;
}

/** A question longer than this many characters (or lines) starts clamped, with Show all. */
export const ASKED_CLAMP_CHARS = 280;
export const ASKED_CLAMP_LINES = 4;

/** A summary is split only when it has at least this many run-in heads of its own. */
export const MIN_RUN_IN_HEADS = 3;

/**
 * A run-in head: a capitalised phrase of at most six words and 48 characters, then a colon and a
 * space, at the start of the summary or right after the end of a sentence (or a line break).
 */
const RUN_IN_HEAD = /(^|[.!?]["')\]]?\s+|\n\s*)([A-Z][A-Za-z0-9&/(),' -]{0,47}?):\s+/g;

export interface SummaryParagraph {
  /** The run-in head without its colon, or '' for the text before the first head. */
  head: string;
  text: string;
}

/**
 * The summary as paragraphs at its own run-in heads, or one paragraph (head '') when it has fewer
 * than MIN_RUN_IN_HEADS. Pure, so a test can state it; every character of the summary is kept
 * (the heads and the text between them, trimmed at the paragraph breaks).
 */
export function splitSummary(summary: string): SummaryParagraph[] {
  const text = String(summary || '');
  const heads: { at: number; textAt: number; head: string }[] = [];
  RUN_IN_HEAD.lastIndex = 0;
  for (let m = RUN_IN_HEAD.exec(text); m; m = RUN_IN_HEAD.exec(text)) {
    const head = m[2].trim();
    const words = head.split(/\s+/).filter(Boolean).length;
    if (words > 6) continue;
    const at = m.index + m[1].length;
    heads.push({ at, textAt: m.index + m[0].length, head });
  }
  if (heads.length < MIN_RUN_IN_HEADS) return [{ head: '', text: text.trim() }];
  const out: SummaryParagraph[] = [];
  const lead = text.slice(0, heads[0].at).trim();
  if (lead) out.push({ head: '', text: lead });
  heads.forEach((h, i) => {
    const end = i + 1 < heads.length ? heads[i + 1].at : text.length;
    out.push({ head: h.head, text: text.slice(h.textAt, end).trim() });
  });
  return out;
}

/** `k=v` tokens of a run configuration: a name, `=`, and a value up to a space, comma or semicolon. */
const KV_TOKEN = /[A-Za-z_][\w.-]*=[^\s,;]+/g;

/** The configuration as text and `k=v` runs, in order; every character kept. */
export function configurationRuns(configuration: string): { text: string; kv: boolean }[] {
  const out: { text: string; kv: boolean }[] = [];
  let last = 0;
  KV_TOKEN.lastIndex = 0;
  for (let m = KV_TOKEN.exec(configuration); m; m = KV_TOKEN.exec(configuration)) {
    let token = m[0];
    // A sentence's own closing period or bracket is not part of the value.
    const trail = /[.)\]]+$/.exec(token);
    if (trail && !/[([]/.test(token.slice(token.indexOf('=')))) token = token.slice(0, token.length - trail[0].length);
    if (m.index > last) out.push({ text: configuration.slice(last, m.index), kv: false });
    out.push({ text: token, kv: true });
    last = m.index + token.length;
    KV_TOKEN.lastIndex = last;
  }
  if (last < configuration.length) out.push({ text: configuration.slice(last), kv: false });
  return out;
}

/** The coverage status in plain words. */
export function coverageWords(status: string): string {
  if (status === 'scoped') return 'Scoped: the assistant lists no remaining work within the stated scope. Outside that scope nothing is claimed.';
  if (status === 'partial') return 'Partial: the assistant lists work that remains within the scope.';
  return 'Coverage: ' + status + '.';
}

let aboutSeq = 0;

/** Build the About pane into `panel` (already cleared). */
export function renderAboutPane(panel: HTMLElement, s: AboutPaneState): void {
  const doc = s.document;
  if (!doc) {
    add(panel, el('p', 'mlv-empty-note', 'No workflow loaded yet.'));
    return;
  }
  const uid = 'mlv-about' + ++aboutSeq;
  const root = add(panel, el('div', 'mlv-about'));
  root.setAttribute('data-revision', doc.revision.id);

  // Viewer M4: what changed since the revision this panel showed before, first.
  if (s.changes) changesSection(root, s.changes, s);
  else if (s.replaced) notFollowingSection(root, doc, s.replaced);

  // Asked.
  const asked = section(root, 'asked', 'Asked');
  const question = add(asked, el('p', 'mlv-about__question mlv-workflow__question', doc.request.question));
  question.id = uid + '-question';
  const long = doc.request.question.length > ASKED_CLAMP_CHARS || doc.request.question.split('\n').length > ASKED_CLAMP_LINES;
  if (long) {
    question.setAttribute('data-clamped', 'true');
    const more = button('mlv-link mlv-about__more', 'Show all', 'Show the whole question');
    more.setAttribute('aria-expanded', 'false');
    more.setAttribute('aria-controls', question.id);
    on(more, 'click', () => {
      const clamped = question.getAttribute('data-clamped') === 'true';
      question.setAttribute('data-clamped', clamped ? 'false' : 'true');
      more.textContent = clamped ? 'Show less' : 'Show all';
      more.setAttribute('aria-expanded', clamped ? 'true' : 'false');
      more.setAttribute('aria-label', clamped ? 'Show less of the question' : 'Show the whole question');
    });
    asked.appendChild(more);
  }

  // What the model traced: the author's summary, split at its own run-in heads.
  const traced = section(root, 'traced', 'What the model traced');
  const paragraphs = splitSummary(doc.coverage.summary);
  traced.setAttribute('data-paragraphs', String(paragraphs.length));
  for (const p of paragraphs) {
    const para = add(traced, el('p', 'mlv-about__para'));
    if (p.head) {
      add(para, el('strong', 'mlv-about__lead', p.head + ':'));
      para.appendChild(document.createTextNode(' '));
    }
    para.appendChild(document.createTextNode(p.text));
  }

  // Coverage in plain words, with the limitations listed once (the Selection pane links here).
  const coverage = section(root, 'coverage', 'Coverage');
  const status = add(coverage, el('p', 'mlv-about__status mlv-workflow__coverage', coverageWords(doc.coverage.status)));
  status.setAttribute('data-status', doc.coverage.status);
  const limitations = doc.coverage.limitations;
  if (limitations.length) {
    const details = add(coverage, el('details', 'mlv-about__limitations mlv-workflow__limitations')) as HTMLDetailsElement;
    details.open = true;
    const n = limitations.length;
    add(details, el('summary', '', n + (n === 1 ? ' coverage limitation' : ' coverage limitations') + ' (apply to every claim)'));
    const list = add(details, el('ul'));
    for (const limitation of limitations) add(list, el('li', '', limitation));
  } else {
    add(coverage, el('p', 'mlv-about__note', 'The assistant listed no coverage limitations.'));
  }

  // Scope.
  const scope = section(root, 'scope', 'Scope');
  add(scope, el('p', 'mlv-about__text', doc.request.scope));
  const entrypoints = doc.request.entrypoints && doc.request.entrypoints.length ? doc.request.entrypoints.join(', ') : 'not specified';
  add(scope, el('p', 'mlv-about__meta', 'Entrypoints: ' + entrypoints));

  // Run configuration, with its k=v tokens in monospace.
  const config = section(root, 'config', 'Run configuration');
  const configText = doc.request.configuration;
  if (configText) {
    const p = add(config, el('p', 'mlv-about__text mlv-about__config'));
    for (const run of configurationRuns(configText)) {
      if (run.kv) add(p, el('code', 'mlv-about__kv', run.text));
      else p.appendChild(document.createTextNode(run.text));
    }
  } else {
    add(config, el('p', 'mlv-about__meta', 'Configuration: not specified.'));
  }

  // The cited files, each with its freshness (colour only for a problem).
  const files = section(root, 'files', 'Cited files');
  const cited: string[] = [];
  for (const item of doc.evidence || []) if (cited.indexOf(item.file) < 0) cited.push(item.file);
  if (!cited.length) {
    add(files, el('p', 'mlv-about__note', 'No file is cited.'));
  } else {
    const head = files.querySelector('.mlv-rail__heading');
    if (head) add(head, el('span', 'mlv-rail__count', cited.length + (cited.length === 1 ? ' file' : ' files')));
    const list = add(files, el('ul', 'mlv-about__files'));
    const hashes = doc.verification ? doc.verification.files || {} : null;
    for (const file of cited) {
      const li = add(list, el('li', 'mlv-about__file'));
      li.setAttribute('data-file', file);
      add(li, el('span', 'mlv-about__path', file)).title = file;
      const reason = s.staleReason ? s.staleReason(file) : undefined;
      if (reason) {
        const badge = add(li, el('span', 'mlv-quote__fresh mlv-insp__stale'));
        badge.setAttribute('data-fresh', 'stale');
        badge.setAttribute('data-stale', reason);
        badge.appendChild(uiIcon('warning', 12));
        add(badge, el('span', '', STALE_TEXT[reason]));
      } else {
        const hashed = !!hashes && Object.prototype.hasOwnProperty.call(hashes, file);
        const badge = add(li, el('span', 'mlv-quote__fresh is-muted', hashed ? 'unchanged' : 'not checked'));
        badge.setAttribute('data-fresh', hashed ? 'unchanged' : 'unchecked');
      }
    }
    add(files, el('p', 'mlv-about__note', 'Unchanged means the quoted lines still exist as published. It does not mean they support the claims.'));
  }

  // Provenance.
  const provenance = section(root, 'provenance', 'Provenance');
  const bits = [doc.producer.host, doc.producer.model || 'model not named', 'revision ' + doc.revision.id + (doc.revision.parent ? ' (after ' + doc.revision.parent + ')' : '')];
  bits.push(doc.verification ? 'published ' + doc.verification.publishedAt : 'published without source hashes');
  add(provenance, el('p', 'mlv-about__meta', bits.join(' · ')));
  // Viewer M4: a revision with a parent this panel never showed has no Changes section; say why.
  if (doc.revision.parent && !s.changes && !s.replaced) {
    const note = add(provenance, el('p', 'mlv-about__note mlv-about__unseen', 'This panel did not show revision ' + doc.revision.parent + ', so no changes since it are listed.'));
    note.setAttribute('data-about-note', 'parent-not-shown');
  }
  add(provenance, el('p', 'mlv-about__trust mlv-workflow__provenance', 'Model-authored; MLView checks citations, not the interpretation.'));
}

/* ── viewer M4 (step 16): Changes since <parent> ─────────────────────── */

/** What the Changes section says about its own reach. */
export const CHANGES_SCOPE =
  'Steps, connections and findings are matched by id, so one whose id changed is listed as removed and added. ' +
  'This covers only revisions this panel has shown; closing the panel, reloading the window or restarting extensions forgets it.';

const GROUPS: { key: 'steps' | 'connections' | 'findings'; title: string; noun: string }[] = [
  { key: 'steps', title: 'Steps', noun: 'step' },
  { key: 'connections', title: 'Connections', noun: 'connection' },
  { key: 'findings', title: 'Findings', noun: 'finding' },
];

/** "1 added · 2 changed", or "none added, removed or changed". */
export function changeCountText(group: ChangeGroup): string {
  const parts: string[] = [];
  if (group.added.length) parts.push(group.added.length + ' added');
  if (group.changed.length) parts.push(group.changed.length + ' changed');
  if (group.removed.length) parts.push(group.removed.length + ' removed');
  return parts.length ? parts.join(' · ') : 'none added, removed or changed';
}

function changesSection(root: HTMLElement, diff: RevisionDiff, s: AboutPaneState): void {
  const box = section(root, 'changes', 'Changes since ');
  box.setAttribute('data-since', diff.since);
  // The revision id as written: ids are case-sensitive, and the heading's capitals would change it.
  const headText = box.querySelector('.mlv-rail__headtext');
  if (headText) add(headText, el('span', 'mlv-about__revid', diff.since));
  add(box, el('p', 'mlv-about__note', 'Compared with revision ' + diff.since + ', which this panel showed before this one. ' + CHANGES_SCOPE));
  const marked = markedTotal(diff);
  const total = GROUPS.reduce((n, g) => n + diff[g.key].added.length + diff[g.key].changed.length + diff[g.key].removed.length, 0);
  if (!total) {
    add(box, el('p', 'mlv-about__text', 'No step, connection or finding was added, removed or changed.'));
    return;
  }
  if (marked && s.onReviewChanges) {
    const review = button('mlv-link mlv-about__review', 'Review the ' + marked + (marked === 1 ? ' added or changed claim' : ' added and changed claims'),
      'Walk the claims added or changed in this revision, in the diagram\'s order (the walk\'s "Changed in this revision" filter)');
    on(review, 'click', () => s.onReviewChanges && s.onReviewChanges());
    add(box, el('p', 'mlv-about__text')).appendChild(review);
  }
  for (const g of GROUPS) {
    const group = diff[g.key];
    const block = add(box, el('div', 'mlv-about__changegroup'));
    block.setAttribute('data-change-group', g.key);
    const h = add(block, el('h5', 'mlv-rail__heading mlv-about__subhead'));
    add(h, el('span', 'mlv-rail__headtext', g.title));
    add(h, el('span', 'mlv-rail__count', changeCountText(group)));
    const items = group.added.concat(group.changed, group.removed);
    if (!items.length) continue;
    const list = add(block, el('ul', 'mlv-about__changes'));
    for (const item of items) list.appendChild(changeRow(item, g.noun, s));
  }
}

/** One added, changed or removed item: its tag in words, then a link to it (removed: text only). */
function changeRow(item: ItemChange, noun: string, s: AboutPaneState): HTMLElement {
  const li = el('li', 'mlv-about__change');
  li.setAttribute('data-change', item.status);
  li.setAttribute('data-change-kind', item.kind);
  li.setAttribute('data-change-id', item.id);
  const tag = add(li, el('span', 'mlv-rev-tag', changeTagText(item)));
  tag.setAttribute('data-change', item.status);
  li.appendChild(document.createTextNode(' '));
  if (item.status === 'removed') {
    // No ghost on the diagram: the item is gone, so it is named here, as text, with its id.
    add(li, el('span', 'mlv-about__changegone', item.title));
    add(li, el('span', 'mlv-about__changeid mlv-mono', ' ' + item.id));
    return li;
  }
  const issue = item.kind === 'issue' && s.index ? s.index.issueById.get(item.id) : undefined;
  const text = (issue && issue.short ? issue.short + ' · ' : '') + item.title;
  const link = button('mlv-link mlv-about__changelink', text, 'Select the ' + noun + ' ' + item.title);
  on(link, 'click', () => s.onShowChange && s.onShowChange(item.kind, item.id));
  li.appendChild(link);
  if (item.status === 'changed' && item.fields.length) add(li, el('span', 'mlv-about__changefields', ' · ' + fieldList(item.fields)));
  return li;
}

/** A new revision that does not follow the one this panel showed: no comparison, and why. */
function notFollowingSection(root: HTMLElement, doc: WorkflowDocument, replaced: string): void {
  const box = section(root, 'changes', 'Changes');
  box.setAttribute('data-replaced', replaced);
  const parent = doc.revision.parent;
  add(box, el('p', 'mlv-about__note',
    'No changes are listed: revision ' + doc.revision.id + ' does not follow revision ' + replaced + ', which this panel showed before it' +
      (parent ? ' (its parent is ' + parent + ').' : ' (it names no parent).') +
      ' Changes are listed only against the revision this panel showed just before.'));
}

function section(root: HTMLElement, id: string, title: string): HTMLElement {
  const box = add(root, el('section', 'mlv-about__section'));
  box.setAttribute('data-about', id);
  const h = add(box, el('h4', 'mlv-rail__heading'));
  add(h, el('span', 'mlv-rail__headtext', title));
  return box;
}
