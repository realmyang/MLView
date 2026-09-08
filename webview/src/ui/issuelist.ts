/**
 * The Issues panel: the group-by control, the severity sections, the rows and
 * the four empty states.
 *
 * Split out of `ui/rail.ts` when RAIL-GROUP and MLV-P6 landed — the rail file
 * owns the three tabs, the Inspector and the Outline, and this one owns
 * everything under the Issues tab.
 */

import { add, button, clear, el, fileLine, iconButton, on } from '../dom.js';
import { uiIcon } from '../icons.js';
import { severityGlyph, SEVERITY_ORDER, normalizeSeverity } from '../markers.js';
import { appendTrustSections, confidenceChip } from './evidence.js';
import { defaultExpanded, groupIssues, needsHeader, occurrenceText, RAIL_GROUP_LABEL, RAIL_GROUP_MODES } from './railgroup.js';
import type { IssueGroup } from './railgroup.js';
import type { GraphIndex } from '../layout/model.js';
import type { Issue, Loc, RailGroupBy, RelatedLoc } from '../types.js';

export interface IssueListCallbacks {
  onSelectIssue(id: string): void;
  onOpen(loc: Loc | RelatedLoc): void;
  onClearFilters(): void;
  onClearScope(): void;
  onGroupBy(mode: RailGroupBy): void;
  onToggleGroup(key: string): void;
}

export interface IssueListState {
  index: GraphIndex | null;
  issues: Issue[];
  keep(issue: Issue): boolean;
  selectedIssueId: string | null;
  scope: { shown: number; hidden: number; total: number } | null;
  groupBy: RailGroupBy;
  /** Group keys the user has opened. Session-local; only the mode persists. */
  expanded: Set<string>;
}

export function renderIssuePanel(panel: HTMLElement, s: IssueListState, cb: IssueListCallbacks): void {
  clear(panel);
  if (!s.index) {
    add(panel, el('div', 'mlv-empty-note', 'No analysis loaded yet.'));
    return;
  }
  const visible = s.issues.filter(s.keep);
  if (s.scope) panel.appendChild(scopeLine(s.scope, cb));
  // The control is offered whenever the DOCUMENT has findings, so switching
  // back out of a grouping that filtered to nothing is always one click away.
  if (s.issues.length) panel.appendChild(groupControl(s, cb));
  if (!visible.length) {
    // FOUR very different results, told apart: nothing was analysed, nothing
    // was wrong, the filters excluded everything, or the SCOPE excludes them
    // (MLV-R1-013, MLV-R2-W05, FEATURES 3.7). Getting these apart is what stops
    // a scope from reading as a clean bill of health.
    if (s.scope && s.scope.hidden > 0) panel.appendChild(scopeEmptyState(s.scope, cb));
    else if (s.issues.length) panel.appendChild(filteredEmptyState(cb));
    else if ((s.index.graph.nodes || []).length === 0) panel.appendChild(nothingAnalyzedState(s));
    else panel.appendChild(cleanState(s));
    return;
  }
  for (const sev of SEVERITY_ORDER) {
    const group = visible.filter((i) => normalizeSeverity(i.severity) === sev);
    if (!group.length) continue;
    const section = add(panel, el('section', 'mlv-rail__section'));
    section.setAttribute('data-severity-section', sev);
    const heading = add(section, el('h3', 'mlv-rail__heading'));
    heading.appendChild(severityGlyph(sev, 12, ''));
    add(heading, el('span', '', sev + ' · ' + group.length));
    if (s.groupBy === 'none') section.appendChild(flatList(group, sev, s, cb));
    else renderGroups(section, group, sev, s, cb);
  }
}

/* ── the group-by control ──────────────────────────────────────────────── */

/**
 * "Group by: none | rule | file" — the first in-rail control there has ever
 * been. An enumeration of every button, select and input inside `.mlv-rail`
 * found exactly three tabs and a per-row "Open".
 */
function groupControl(s: IssueListState, cb: IssueListCallbacks): HTMLElement {
  const box = el('div', 'mlv-rail__groupby');
  box.setAttribute('role', 'group');
  box.setAttribute('aria-label', 'Group findings');
  box.setAttribute('data-group-by', s.groupBy);
  add(box, el('span', 'mlv-rail__groupby-label', 'Group by'));
  for (const mode of RAIL_GROUP_MODES) {
    const active = s.groupBy === mode;
    const b = el('button', 'mlv-chip mlv-chip--btn mlv-rail__groupby-btn', RAIL_GROUP_LABEL[mode]) as HTMLButtonElement;
    b.type = 'button';
    b.setAttribute('data-group-mode', mode);
    b.setAttribute('aria-pressed', active ? 'true' : 'false');
    b.title = 'Group findings by ' + RAIL_GROUP_LABEL[mode].toLowerCase();
    on(b, 'click', () => cb.onGroupBy(mode));
    box.appendChild(b);
  }
  return box;
}

/* ── lists ─────────────────────────────────────────────────────────────── */

function flatList(issues: Issue[], sev: string, s: IssueListState, cb: IssueListCallbacks, label?: string): HTMLElement {
  const list = el('ul', 'mlv-issues');
  list.setAttribute('role', 'listbox');
  list.setAttribute('aria-label', label || sev + ' severity issues');
  for (const issue of issues) list.appendChild(issueRow(issue, s, cb));
  wireListbox(list, cb);
  return list;
}

function renderGroups(section: HTMLElement, issues: Issue[], sev: string, s: IssueListState, cb: IssueListCallbacks): void {
  const groups = groupIssues(issues, s.groupBy);
  const singles: Issue[] = [];
  for (const group of groups) {
    if (!needsHeader(group)) {
      // One occurrence is not a group: it renders exactly as it does flat, so
      // the 15-finding demo rail does not sprout twelve one-row twisties.
      singles.push(group.issues[0]);
      continue;
    }
    section.appendChild(groupBlock(group, sev, s, cb));
  }
  if (singles.length) section.appendChild(flatList(singles, sev, s, cb, sev + ' severity issues, ungrouped'));
}

function groupBlock(group: IssueGroup, sev: string, s: IssueListState, cb: IssueListCallbacks): HTMLElement {
  // Grouping happens INSIDE each severity band, so one file can head a group in
  // two bands at once. The expansion key carries the band; `data-group-key`
  // stays the semantic one, because that is the name the user reads.
  const toggleKey = sev + '/' + group.key;
  const open = isExpanded(group, toggleKey, s);
  const box = el('div', 'mlv-railgroup');
  box.setAttribute('data-group-key', group.key);
  box.setAttribute('data-group-count', String(group.issues.length));
  if (open) box.classList.add('is-open');

  const head = el('button', 'mlv-railgroup__head') as HTMLButtonElement;
  head.type = 'button';
  head.setAttribute('aria-expanded', open ? 'true' : 'false');
  head.setAttribute('data-group-toggle', toggleKey);
  head.appendChild(uiIcon('chevron', 12));
  head.appendChild(severityGlyph(sev, 12, ''));
  const text = add(head, el('span', 'mlv-railgroup__text'));
  add(text, el('span', 'mlv-railgroup__title', group.title));
  if (group.subtitle) add(text, el('span', 'mlv-railgroup__sub', group.subtitle));
  const meta = add(head, el('span', 'mlv-railgroup__meta'));
  const count = add(meta, el('span', 'mlv-railgroup__count', occurrenceText(group, s.groupBy)));
  count.setAttribute('data-group-occurrences', String(group.issues.length));
  if (group.worstBucket) {
    const chip = add(meta, el('span', 'mlv-chip mlv-chip--conf mlv-chip--conf-' + group.worstBucket, group.worstBucket));
    chip.title = 'Lowest confidence in this group: ' + group.worstBucket;
  }
  head.setAttribute(
    'aria-label',
    group.title + ' — ' + occurrenceText(group, s.groupBy) + (group.subtitle ? ' — ' + group.subtitle : ''),
  );
  on(head, 'click', () => cb.onToggleGroup(toggleKey));
  box.appendChild(head);

  if (open) box.appendChild(flatList(group.issues, sev, s, cb, group.title + ' occurrences'));
  return box;
}

/**
 * Open when the user opened it, when it is small enough that folding saves
 * nothing, or when it holds the selection — a selected finding must never be
 * hidden behind a twisty the user did not close.
 */
function isExpanded(group: IssueGroup, toggleKey: string, s: IssueListState): boolean {
  if (s.expanded.has(toggleKey)) return true;
  if (s.selectedIssueId && group.issues.some((i) => i.id === s.selectedIssueId)) return true;
  return defaultExpanded(group) && !s.expanded.has('!' + toggleKey);
}

/* ── one row ───────────────────────────────────────────────────────────── */

function issueRow(issue: Issue, s: IssueListState, cb: IssueListCallbacks): HTMLElement {
  const selected = s.selectedIssueId === issue.id;
  const li = el('li', 'mlv-issues__item');
  li.setAttribute('role', 'presentation');
  // A div, not a <button>: `role="option"` may not contain a focusable
  // descendant, and the "open in editor" control beside it is a real button
  // (the same reasoning nodes.ts already applies to the group header).
  const row = el('div', 'mlv-issue');
  row.setAttribute('role', 'option');
  row.tabIndex = -1;
  row.setAttribute('data-issue-id', issue.id);
  row.setAttribute('aria-selected', selected ? 'true' : 'false');
  row.setAttribute(
    'aria-label',
    issue.code + ' ' + issue.severity + ' severity, ' + issue.title + ', ' + fileLine(issue.loc) + ', confidence ' + issue.confidenceBucket,
  );
  if (selected) row.classList.add('is-selected');
  if (issue.suppressed) row.classList.add('is-suppressed');
  row.appendChild(severityGlyph(issue.severity, 14, ''));
  const text = add(row, el('div', 'mlv-issue__text'));
  add(text, el('div', 'mlv-issue__title', issue.title));
  const meta = add(text, el('div', 'mlv-issue__meta'));
  add(meta, el('span', '', issue.code));
  add(meta, el('span', '', fileLine(issue.loc)));
  // MLV-P6: on EVERY row, styled by bucket. Drawing it only for `possible` and
  // `speculative` made `certain` and `likely` look identical — the distinction a
  // reviewer most needs — and made a missing chip ambiguous between "sure" and
  // "the renderer forgot".
  meta.appendChild(confidenceChip(issue));
  if (issue.suppressed) add(meta, el('span', 'mlv-chip', 'suppressed'));
  on(row, 'click', () => cb.onSelectIssue(issue.id));
  li.appendChild(row);

  // A sibling of the option, never a child of it (MLV-R2-W03).
  const open = iconButton('mlv-btn mlv-btn--icon mlv-issue__open', 'Open ' + fileLine(issue.loc));
  open.appendChild(uiIcon('open', 12));
  on(open, 'click', (ev: Event) => {
    ev.stopPropagation();
    cb.onOpen(issue.loc);
  });
  li.appendChild(open);

  // The selected row expands in place with the message, the why line, the fix
  // hint and a Go to button per location — the most valuable content in the
  // product used to be unreachable from the Issues tab entirely (MLV-R1-006).
  if (selected) li.appendChild(issueDetail(issue, cb));
  return li;
}

/** The expanded body of a selected issue row. */
function issueDetail(issue: Issue, cb: IssueListCallbacks): HTMLElement {
  const box = el('div', 'mlv-issue__detail');
  box.setAttribute('data-issue-detail', issue.id);
  if (issue.message) add(box, el('p', 'mlv-insp__line', issue.message));
  if (issue.why) add(box, el('p', 'mlv-insp__line mlv-insp__why', issue.why));
  if (issue.fixHint) add(box, el('div', 'mlv-insp__fix', issue.fixHint));
  // MLV-P6: the evidence checklist and the rule card, both as disclosures.
  appendTrustSections(box, issue);
  const actions = add(box, el('div', 'mlv-issue__goto'));
  const primary = button('mlv-btn', 'Go to ' + fileLine(issue.loc));
  on(primary, 'click', (ev: Event) => {
    ev.stopPropagation();
    cb.onOpen(issue.loc);
  });
  actions.appendChild(primary);
  for (const rel of issue.relatedLocs || []) {
    const label = 'Go to ' + (rel.message || rel.role.replace(/_/g, ' ')) + ' — ' + fileLine(rel);
    const b = button('mlv-btn', label);
    on(b, 'click', (ev: Event) => {
      ev.stopPropagation();
      cb.onOpen(rel);
    });
    actions.appendChild(b);
  }
  return box;
}

/**
 * The listbox is one composite widget with ONE tab stop: the selected option,
 * or the first. Arrow keys move the focus inside it. Before this the row was a
 * real <button> with a second <button> nested in it, which is invalid HTML,
 * illegal under `role="option"`, and cost two Tab presses per finding
 * (MLV-R2-W03).
 */
function wireListbox(list: HTMLElement, cb: IssueListCallbacks): void {
  const options = () => Array.prototype.slice.call(list.querySelectorAll('[role="option"]')) as HTMLElement[];
  const all = options();
  const active = all.filter((o) => o.getAttribute('aria-selected') === 'true')[0] || all[0] || null;
  for (const option of all) option.tabIndex = option === active ? 0 : -1;

  on(list, 'keydown', (ev: KeyboardEvent) => {
    const target = ev.target as HTMLElement | null;
    if (!target || typeof target.closest !== 'function') return;
    const option = target.closest('[role="option"]') as HTMLElement | null;
    if (!option || !list.contains(option)) return;
    const items = options();
    const at = items.indexOf(option);
    let next: HTMLElement | null = null;
    if (ev.key === 'ArrowDown') next = items[Math.min(items.length - 1, at + 1)];
    else if (ev.key === 'ArrowUp') next = items[Math.max(0, at - 1)];
    else if (ev.key === 'Home') next = items[0];
    else if (ev.key === 'End') next = items[items.length - 1];
    else if (ev.key === 'Enter' || ev.key === ' ') {
      ev.preventDefault();
      const id = option.getAttribute('data-issue-id');
      if (id) cb.onSelectIssue(id);
      return;
    } else return;
    ev.preventDefault();
    if (!next) return;
    for (const item of items) item.tabIndex = item === next ? 0 : -1;
    next.focus();
  });
}

/* ── the four zeros ────────────────────────────────────────────────────── */

/** The zero-issue result: good news, stated as good news. */
function cleanState(s: IssueListState): HTMLElement {
  const box = el('div', 'mlv-clean');
  box.setAttribute('role', 'status');
  box.appendChild(uiIcon('check', 20));
  add(box, el('div', 'mlv-clean__title', 'No issues found'));
  const index = s.index;
  if (index) {
    const nodes = (index.graph.nodes || []).length;
    const stages = (index.graph.stages || []).filter((st) => st.present).length;
    add(
      box,
      el(
        'div',
        'mlv-clean__detail',
        nodes + (nodes === 1 ? ' node' : ' nodes') + ' across ' + stages + (stages === 1 ? ' stage' : ' stages') + ' checked — nothing to flag.',
      ),
    );
  }
  return box;
}

/**
 * Nothing was analysed at all. The canvas already says "No ML pipeline found";
 * a rail that answers "No issues found" beside it reads as a clean bill of
 * health for a run that never looked at anything (MLV-R2-W05).
 */
function nothingAnalyzedState(s: IssueListState): HTMLElement {
  const box = el('div', 'mlv-empty-note');
  box.setAttribute('role', 'status');
  add(box, el('div', 'mlv-clean__title', 'Nothing analyzed'));
  const graph = s.index ? s.index.graph : null;
  const diags = graph ? graph.diagnostics || [] : [];
  const files = graph ? graph.workspace.filesAnalyzed : 0;
  add(
    box,
    el(
      'div',
      'mlv-clean__detail',
      'No ML pipeline was found, so there is nothing to flag. ' + files + (files === 1 ? ' file' : ' files') + ' analyzed.',
    ),
  );
  if (diags.length) {
    const list = add(box, el('ul', 'mlv-state__list'));
    for (const d of diags.slice(0, 5)) {
      add(list, el('li', '', (d.file ? d.file + ': ' : '') + d.kind + ' — ' + d.message));
    }
  }
  return box;
}

/** "3 of 15 findings shown · 12 outside this scope — Show all". */
function scopeLine(scope: { shown: number; hidden: number; total: number }, cb: IssueListCallbacks): HTMLElement {
  const box = el('div', 'mlv-rail__scopeline');
  box.setAttribute('role', 'status');
  box.setAttribute('data-scope-line', '1');
  add(
    box,
    el(
      'span',
      '',
      scope.shown + ' of ' + scope.total + (scope.total === 1 ? ' finding' : ' findings') + ' shown · ' + scope.hidden + ' outside this scope',
    ),
  );
  const all = button('mlv-link mlv-link--inline', 'Show all', 'Clear the scope. Filters are separate.');
  on(all, 'click', () => cb.onClearScope());
  box.appendChild(all);
  return box;
}

/** The fourth empty state: in scope, but nothing is wrong HERE. */
function scopeEmptyState(scope: { hidden: number; total: number }, cb: IssueListCallbacks): HTMLElement {
  const box = el('div', 'mlv-empty-note');
  box.setAttribute('role', 'status');
  box.setAttribute('data-scope-empty-rail', '1');
  add(box, el('div', 'mlv-clean__title', 'No findings in this scope'));
  add(box, el('div', 'mlv-clean__detail', scope.hidden + ' elsewhere in this project.'));
  const all = button('mlv-btn', 'Show all');
  on(all, 'click', () => cb.onClearScope());
  box.appendChild(all);
  return box;
}

/** The filters excluded everything: say so, and offer the way back. */
function filteredEmptyState(cb: IssueListCallbacks): HTMLElement {
  const box = el('div', 'mlv-empty-note');
  add(box, el('div', '', 'No issues match these filters.'));
  const clearBtn = button('mlv-btn', 'Clear filters');
  on(clearBtn, 'click', () => cb.onClearFilters());
  box.appendChild(clearBtn);
  return box;
}
