/**
 * The Issues panel: the group-by control, the severity sections, the rows and
 * the four empty states.
 *
 * Split out of `ui/rail.ts` when RAIL-GROUP and MLV-P6 landed — the rail file
 * owns the three tabs, the Inspector and the Outline, and this one owns
 * everything under the Issues tab.
 */

import { add, button, clear, el, fileLine, locSpan, iconButton, on } from '../dom.js';
import { locSpoken } from '../notebook.js';
import { uiIcon } from '../icons.js';
import { severityGlyph, SEVERITY_ORDER, normalizeSeverity } from '../markers.js';
import { appendTrustSections, confidenceChip } from './evidence.js';
import { defaultExpanded, groupIssues, groupModesFor, needsHeader, occurrenceText, RAIL_GROUP_LABEL } from './railgroup.js';
import { appendSuppressActions, stateChip, suppressedSummary } from './suppress.js';
import { appendFixSection, fixMarker, hasFix } from './fixes.js';
import { blindSpots, coverageHeadline } from './chromenotes.js';
import type { IssueGroup } from './railgroup.js';
import type { GraphIndex } from '../layout/model.js';
import type { DiffIndex, DiffIssueEntry } from '../diff/overlay.js';
import { isKnownIssueChange, isSetAside } from '../types.js';
import type { Issue, Loc, RailGroupBy, RelatedLoc } from '../types.js';

export interface IssueListCallbacks {
  onSelectIssue(id: string): void;
  onOpen(loc: Loc | RelatedLoc): void;
  onClearFilters(): void;
  onClearScope(): void;
  onGroupBy(mode: RailGroupBy): void;
  onToggleGroup(key: string): void;
  /** MLV-P10: copy `# mlview: ignore[CODE]` through the host's clipboard. */
  onCopyIgnore(code: string): void;
  /** MLV-P10: post `suppressRule` for this code. */
  onDisableRule(code: string): void;
  /** H5: ask the host to apply `Issue.fix`, or copy it where it cannot. */
  onApplyFix(issueId: string): void;
}

export interface IssueListState {
  index: GraphIndex | null;
  issues: Issue[];
  keep(issue: Issue): boolean;
  selectedIssueId: string | null;
  scope: { shown: number; hidden: number; total: number; where: string } | null;
  groupBy: RailGroupBy;
  /** Group keys the user has opened. Session-local; only the mode persists. */
  expanded: Set<string>;
  /** VIEW-08: the diff overlay, when one is loaded. Null is the normal case. */
  diff: DiffIndex | null;
  /** H5: true in a host that can actually make an edit (VS Code). */
  canApplyFix: boolean;
  /**
   * Everything `keep` tests EXCEPT suppression and baselining (MLV-P10). The
   * collapsed "N suppressed" section is an audit trail of what was set aside,
   * so it must still honour the severity chips, the stage chips and a host's
   * `setFilter` codes — otherwise a finding the user filtered away reappears
   * there.
   */
  keepBase(issue: Issue): boolean;
}

export function renderIssuePanel(panel: HTMLElement, s: IssueListState, cb: IssueListCallbacks): void {
  clear(panel);
  // VIEW-12: the panel's own heading, so the outline reads h1 -> h2 -> h3 -> h4
  // top-down instead of starting at a rail `h3` above the two `h2`s. Visually
  // hidden: the tab strip already names the panel on screen.
  add(panel, el('h3', 'mlv-sr', 'Findings'));
  if (!s.index) {
    add(panel, el('div', 'mlv-empty-note', 'No workflow loaded yet.'));
    return;
  }
  const visible = s.issues.filter(s.keep);
  // MLV-P10 + CI-ADOPT: what suppression and the baseline set aside, minus
  // anything the ordinary filters would have removed anyway.
  const setAside = s.issues.filter((i) => isSetAside(i) && !s.keep(i) && s.keepBase(i));
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
    // A FIFTH zero (MLV-P10): every finding was silenced. "No issues match
    // these filters" would be false — no filter is doing it — and "No issues
    // found" would be a clean bill of health over N suppressions.
    else if (setAside.length && s.issues.every((i) => !s.keepBase(i) || isSetAside(i))) {
      panel.appendChild(allSuppressedState(setAside.length));
    } else if (s.issues.length) panel.appendChild(filteredEmptyState(cb));
    else if ((s.index.graph.nodes || []).length === 0) panel.appendChild(nothingAnalyzedState(s));
    else if (s.index.graph.schemaVersion === 'workflow-view/1') panel.appendChild(noFindingsRecordedState(s));
    else panel.appendChild(cleanState(s));
    // "No issues found" over a document where three findings were silenced is
    // not a clean bill of health, so the section is drawn here too (MLV-P10).
    if (setAside.length) panel.appendChild(suppressedSection(setAside, s, cb));
    // VIEW-08: and "no issues" over a diff that fixed fifteen is the BEST news
    // this product ever delivers. It belongs on the zero screen most of all.
    const fixedHere = fixedEntries(s);
    if (fixedHere.length) panel.appendChild(fixedSection(fixedHere, s, cb));
    return;
  }
  for (const sev of SEVERITY_ORDER) {
    const group = visible.filter((i) => normalizeSeverity(i.severity) === sev);
    if (!group.length) continue;
    const section = add(panel, el('section', 'mlv-rail__section'));
    section.setAttribute('data-severity-section', sev);
    // h4 under the panel's h3 (VIEW-12).
    const heading = add(section, el('h4', 'mlv-rail__heading'));
    heading.appendChild(severityGlyph(sev, 12, ''));
    add(heading, el('span', '', sev + ' · ' + group.length));
    if (s.groupBy === 'none') section.appendChild(flatList(group, sev, s, cb));
    else renderGroups(section, group, sev, s, cb);
  }
  if (setAside.length) panel.appendChild(suppressedSection(setAside, s, cb));
  const fixed = fixedEntries(s);
  if (fixed.length) panel.appendChild(fixedSection(fixed, s, cb));
}

/* ── the collapsed "N fixed by this change" section (VIEW-08) ──────────── */

/** The overlay's `fixed` findings — the ones the BASE document had. */
function fixedEntries(s: IssueListState): DiffIssueEntry[] {
  if (!s.diff) return [];
  const out: DiffIssueEntry[] = [];
  for (const entry of s.diff.overlay.issues) {
    if (entry.status === 'fixed') out.push(entry);
  }
  return out;
}

/**
 * What this change FIXED, folded away but present.
 *
 * These rows are not findings in this document — by definition, they are gone —
 * so they are read-only: no severity filter applies to them, no suppression
 * action makes sense, and there is no "Go to", because the location they carry
 * is a line in the OLDER analysis and this page has no source for it. The header
 * says exactly that, so nobody reads an inert row as a broken button.
 */
function fixedSection(rows: DiffIssueEntry[], s: IssueListState, cb: IssueListCallbacks): HTMLElement {
  const box = el('section', 'mlv-rail__section mlv-rail__fixed');
  box.setAttribute('data-fixed-section', String(rows.length));
  const open = s.expanded.has('diff-fixed');
  if (open) box.classList.add('is-open');
  const head = el('button', 'mlv-railgroup__head mlv-rail__fixed-head') as HTMLButtonElement;
  head.type = 'button';
  head.setAttribute('aria-expanded', open ? 'true' : 'false');
  head.setAttribute('data-group-toggle', 'diff-fixed');
  head.appendChild(uiIcon('chevron', 12));
  const label = rows.length + (rows.length === 1 ? ' finding fixed' : ' findings fixed') + ' by this change';
  add(head, el('span', 'mlv-railgroup__title', label));
  head.setAttribute('aria-label', label + ' — reported by the earlier analysis and not by this one');
  on(head, 'click', () => cb.onToggleGroup('diff-fixed'));
  box.appendChild(head);
  if (!open) return box;
  add(
    box,
    el(
      'div',
      'mlv-empty-note mlv-rail__fixed-note',
      'These are findings the EARLIER analysis reported. They are not in this document, so there is nothing here to open or suppress.',
    ),
  );
  const list = add(box, el('ul', 'mlv-issues mlv-issues--readonly'));
  list.setAttribute('aria-label', 'Findings fixed by this change');
  for (const entry of rows) {
    const li = add(list, el('li', 'mlv-issues__item'));
    const row = add(li, el('div', 'mlv-issue is-fixed'));
    row.setAttribute('data-fixed-issue', entry.id);
    row.appendChild(severityGlyph(entry.severity, 14, ''));
    const text = add(row, el('div', 'mlv-issue__text'));
    add(text, el('div', 'mlv-issue__title', entry.title || entry.code));
    const meta = add(text, el('div', 'mlv-issue__meta'));
    add(meta, el('span', '', entry.code));
    if (entry.loc) add(meta, el('span', '', entry.loc.file + ':' + entry.loc.line));
    stateChip(meta, 'mlv-chip--diff mlv-chip--diff-fixed', 'fixed', 'Reported by the earlier analysis and not by this one');
  }
  return box;
}

/* ── the collapsed "N suppressed" section (MLV-P10, CI-ADOPT) ──────────── */

/**
 * Everything suppression and the baseline set aside, folded away but present.
 *
 * A suppression that is invisible is not auditable — that is the whole reason
 * this section exists — and CI-ADOPT's baselined findings arrive through the
 * same door, "marked, not deleted", each row carrying the chip that says which
 * of the two it was.
 */
function suppressedSection(rows: Issue[], s: IssueListState, cb: IssueListCallbacks): HTMLElement {
  const box = el('section', 'mlv-rail__section mlv-rail__suppressed');
  box.setAttribute('data-suppressed-section', String(rows.length));
  const open = s.expanded.has('suppressed');
  if (open) box.classList.add('is-open');
  let baselined = 0;
  for (const issue of rows) if (issue.baselined) baselined++;
  const head = el('button', 'mlv-railgroup__head mlv-rail__suppressed-head') as HTMLButtonElement;
  head.type = 'button';
  head.setAttribute('aria-expanded', open ? 'true' : 'false');
  head.setAttribute('data-group-toggle', 'suppressed');
  head.setAttribute('data-suppressed-toggle', String(rows.length));
  head.appendChild(uiIcon('chevron', 12));
  add(head, el('span', 'mlv-railgroup__title', suppressedSummary(rows.length - baselined, baselined)));
  head.setAttribute('aria-label', suppressedSummary(rows.length - baselined, baselined) + ' — findings hidden from the list above');
  on(head, 'click', () => cb.onToggleGroup('suppressed'));
  box.appendChild(head);
  if (open) box.appendChild(flatList(rows, 'suppressed', s, cb, 'Suppressed findings'));
  return box;
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
  for (const mode of groupModesFor(s.index?.graph.schemaVersion)) {
    const active = s.groupBy === mode;
    const label = RAIL_GROUP_LABEL[mode];
    const b = el('button', 'mlv-chip mlv-chip--btn mlv-rail__groupby-btn', label) as HTMLButtonElement;
    b.type = 'button';
    b.setAttribute('data-group-mode', mode);
    b.setAttribute('aria-pressed', active ? 'true' : 'false');
    b.title = 'Group findings by ' + label.toLowerCase();
    on(b, 'click', () => cb.onGroupBy(mode));
    box.appendChild(b);
  }
  return box;
}

/* ── lists ─────────────────────────────────────────────────────────────── */

function flatList(issues: Issue[], sev: string, s: IssueListState, cb: IssueListCallbacks, label?: string): HTMLElement {
  const list = el('ul', 'mlv-issues');
  list.setAttribute('role', 'listbox');
  list.setAttribute('aria-label', label || sev + ' severity findings');
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
  if (singles.length) section.appendChild(flatList(singles, sev, s, cb, sev + ' severity findings, ungrouped'));
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
    chip.title = (s.index?.graph.schemaVersion === 'workflow-view/1' ? 'Weakest basis in this group: ' : 'Lowest confidence in this group: ') + group.worstBucket;
  }
  head.setAttribute(
    'aria-label',
    group.title + ' — ' + occurrenceText(group, s.groupBy) + (group.subtitle ? ' — ' + group.subtitle : ''),
  );
  on(head, 'click', () => cb.onToggleGroup(toggleKey));

  // MLV-P10: the same two actions on the GROUP header, so a whole class is
  // silenced in one gesture — the case the 111-row list actually needs. Only
  // under `rule` grouping: a file group's key is a path, and "disable this
  // rule" over eleven different codes would be a lie about what it does.
  if (s.groupBy === 'rule' && s.index?.graph.schemaVersion !== 'workflow-view/1') {
    const bar = add(box, el('div', 'mlv-railgroup__bar'));
    bar.appendChild(head);
    const n = group.issues.length;
    appendSuppressActions(bar, group.key, cb, {
      compact: true,
      subject: 'all ' + n + ' ' + group.key + (n === 1 ? ' finding' : ' findings'),
    });
  } else {
    box.appendChild(head);
  }

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
    issue.code + ' ' + issue.severity + ' severity, ' + issue.title +
      (issue.loc.file ? ', ' + locSpoken(issue.loc) : '') +
      (issue.basis ? ', basis ' + issue.basis : ', confidence ' + issue.confidenceBucket),
  );
  if (selected) row.classList.add('is-selected');
  if (issue.suppressed) row.classList.add('is-suppressed');
  row.appendChild(severityGlyph(issue.severity, 14, ''));
  const text = add(row, el('div', 'mlv-issue__text'));
  add(text, el('div', 'mlv-issue__title', issue.title));
  const meta = add(text, el('div', 'mlv-issue__meta'));
  add(meta, el('span', '', issue.code));
  if (issue.loc.file) meta.appendChild(locSpan('', issue.loc));
  // MLV-P6: on EVERY row, styled by bucket. Drawing it only for `possible` and
  // `speculative` made `certain` and `likely` look identical — the distinction a
  // reviewer most needs — and made a missing chip ambiguous between "sure" and
  // "the renderer forgot".
  meta.appendChild(confidenceChip(issue));
  if (issue.suppressed) stateChip(meta, 'mlv-chip--suppressed', 'suppressed', 'Silenced by a comment or by .mlview.toml');
  // CI-ADOPT: baselined is MARKED, never deleted.
  if (issue.baselined) stateChip(meta, 'mlv-chip--baselined', 'baselined', 'Already in the baseline file, so it does not fail the build');
  // VIEW-08: how this finding stands against the BASE analysis. Worded "vs base"
  // so it can never be misread as CI-ADOPT's `new` chip below, which is about
  // git hunks in one analysis rather than two analyses.
  const diffStatus = s.diff ? s.diff.issueStatusOf(issue.id) : null;
  if (diffStatus === 'new' || diffStatus === 'persisting') {
    stateChip(
      meta,
      'mlv-chip--diff mlv-chip--diff-' + diffStatus,
      diffStatus === 'new' ? 'new vs base' : 'still there',
      diffStatus === 'new'
        ? 'The earlier analysis did not report this finding'
        : 'Both analyses report this finding',
    ).setAttribute('data-diff-issue', diffStatus);
  }
  // H5: the marker, beside the confidence chip the fix was gated on.
  const marker = fixMarker(issue);
  if (marker) meta.appendChild(marker);
  // CI-ADOPT: new / touched / existing, when the run was attributed at all.
  if (isKnownIssueChange(issue.change)) {
    stateChip(meta, 'mlv-chip--change mlv-chip--change-' + issue.change, issue.change as string, changeTitle(issue.change as string)).setAttribute(
      'data-change',
      issue.change as string,
    );
  }
  on(row, 'click', () => cb.onSelectIssue(issue.id));
  li.appendChild(row);

  // A sibling of the option, never a child of it (MLV-R2-W03).
  if (issue.loc.file) {
    const open = iconButton('mlv-btn mlv-btn--icon mlv-issue__open', 'Open ' + fileLine(issue.loc));
    open.appendChild(uiIcon('open', 12));
    on(open, 'click', (ev: Event) => {
      ev.stopPropagation();
      cb.onOpen(issue.loc);
    });
    li.appendChild(open);
  }

  // MLV-P10: on EVERY row, siblings of the option like "Open" is — never
  // children of it, because `role="option"` may not contain a focusable
  // descendant (MLV-R2-W03).
  if (s.index?.graph.schemaVersion !== 'workflow-view/1') {
    appendSuppressActions(li, issue.code, cb, { compact: true });
  }

  // The selected row expands in place with the message, the why line, the fix
  // hint and a Go to button per location — the most valuable content in the
  // product used to be unreachable from the Issues tab entirely (MLV-R1-006).
  if (selected) li.appendChild(issueDetail(issue, s, cb));
  return li;
}

/** What each CI-ADOPT attribution means, in the reader's words. */
function changeTitle(change: string): string {
  if (change === 'new') return 'On a line this change added';
  if (change === 'touched') return 'In a file this change touched, outside the added lines';
  return 'Already there before this change';
}

/** The expanded body of a selected issue row. */
function issueDetail(issue: Issue, s: IssueListState, cb: IssueListCallbacks): HTMLElement {
  const box = el('div', 'mlv-issue__detail');
  box.setAttribute('data-issue-detail', issue.id);
  if (issue.message) add(box, el('p', 'mlv-insp__line', issue.message));
  if (issue.why) add(box, el('p', 'mlv-insp__line mlv-insp__why', issue.why));
  if (issue.fixHint) add(box, el('div', 'mlv-insp__fix', issue.fixHint));
  // H5: the prose hint stays — it is what all 36 rules carry — and the computed
  // edit goes UNDER it, so the reader sees the advice before the diff of it.
  if (s.index?.graph.schemaVersion !== 'workflow-view/1') {
    if (hasFix(issue)) appendFixSection(box, issue, cb, { canApply: s.canApplyFix });
    appendTrustSections(box, issue);
  }
  const actions = add(box, el('div', 'mlv-issue__goto'));
  if (issue.loc.file) {
    const primary = button('mlv-btn', 'Go to ' + fileLine(issue.loc));
    on(primary, 'click', (ev: Event) => {
      ev.stopPropagation();
      cb.onOpen(issue.loc);
    });
    actions.appendChild(primary);
  }
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

/**
 * The zero-issue result: good news, stated as good news — and only when it IS
 * good news.
 *
 * HOSTS-UX-CLEANSTATE. The standing criterion is *never look clean when you
 * were blind*, and this was the last surface breaking it. On `karpathy/nanoGPT`
 * the same document carries `untagged_dataflow` x2, `unresolved_callee` and
 * `notebook_skipped`; the two banners say so, the answer card's verdict says so
 * (11.60 A2), and the Issues rail — the panel a reviewer reads first — said
 * *"No issues found · 213 nodes across 8 stages checked — nothing to flag."*
 * with nothing beside it.
 *
 * The caveat is the SAME sentence the coverage banner draws, from the same
 * function, over the wider set `blindSpots()` selects: two surfaces agreeing
 * because they call one thing, rather than because someone kept them in step.
 * A document with no coverage diagnostic at all is untouched — an unqualified
 * clean result is still allowed to be an unqualified clean result.
 */
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
    const blind = blindSpots(index.graph.diagnostics || []);
    if (blind.length) {
      const caveat = add(box, el('div', 'mlv-clean__caveat', coverageHeadline(blind)));
      caveat.setAttribute('data-clean-coverage', String(blind.length));
    }
  }
  return box;
}

/**
 * VIEWUI-1. Zero findings in an authored revision means only that the
 * assistant wrote none, which is common for "explain this pipeline"
 * questions. MLView checked nothing, so this state never says "checked",
 * "nothing to flag" or "no issues found": it names the coverage instead.
 */
function noFindingsRecordedState(s: IssueListState): HTMLElement {
  const box = el('div', 'mlv-empty-note mlv-nofindings');
  box.setAttribute('role', 'status');
  add(box, el('div', 'mlv-clean__title', 'No findings recorded in this revision'));
  const coverage = s.index ? s.index.graph.authoredCoverage : undefined;
  const status = coverage ? coverage.status : 'unknown';
  const limits = coverage ? coverage.limitations : 0;
  add(
    box,
    el(
      'div',
      'mlv-clean__detail',
      'The assistant recorded no findings. Coverage: ' + status +
        (limits ? '; ' + limits + (limits === 1 ? ' limitation' : ' limitations') + ' listed above' : '') +
        '. This is not a check result.',
    ),
  );
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
function scopeLine(scope: { shown: number; hidden: number; total: number; where: string }, cb: IssueListCallbacks): HTMLElement {
  const box = el('div', 'mlv-rail__scopeline');
  box.setAttribute('role', 'status');
  box.setAttribute('data-scope-line', '1');
  add(
    box,
    el(
      'span',
      '',
      scope.shown + ' of ' + scope.total + (scope.total === 1 ? ' finding' : ' findings') + ' shown · ' + scope.hidden + ' ' +
        (scope.where || 'outside this scope'),
    ),
  );
  const all = button('mlv-link mlv-link--inline', 'Show all', 'Clear the scope. Filters are separate.');
  on(all, 'click', () => cb.onClearScope());
  box.appendChild(all);
  return box;
}

/** The fourth empty state: in scope, but nothing is wrong HERE. */
function scopeEmptyState(scope: { hidden: number; total: number; where: string }, cb: IssueListCallbacks): HTMLElement {
  const box = el('div', 'mlv-empty-note');
  box.setAttribute('role', 'status');
  box.setAttribute('data-scope-empty-rail', '1');
  // VIEW-08: "in this scope" would name a narrowing the reader never chose when
  // the narrowing is the diff's own.
  const where = scope.where === 'outside the changed set' ? 'in the changed set' : 'in this scope';
  add(box, el('div', 'mlv-clean__title', 'No findings ' + where));
  add(box, el('div', 'mlv-clean__detail', scope.hidden + ' elsewhere in this project.'));
  const all = button('mlv-btn', 'Show all');
  on(all, 'click', () => cb.onClearScope());
  box.appendChild(all);
  return box;
}

/** Everything there was, suppressed. Stated as suppression, not as silence. */
function allSuppressedState(count: number): HTMLElement {
  const box = el('div', 'mlv-empty-note');
  box.setAttribute('role', 'status');
  box.setAttribute('data-all-suppressed', String(count));
  add(box, el('div', 'mlv-clean__title', 'No unsuppressed findings'));
  add(
    box,
    el(
      'div',
      'mlv-clean__detail',
      count + (count === 1 ? ' finding is' : ' findings are') + ' silenced by a comment, by .mlview.toml or by the baseline — listed below.',
    ),
  );
  return box;
}

/** The filters excluded everything: say so, and offer the way back. */
function filteredEmptyState(cb: IssueListCallbacks): HTMLElement {
  const box = el('div', 'mlv-empty-note');
  add(box, el('div', '', 'No findings match these filters.'));
  const clearBtn = button('mlv-btn', 'Clear filters');
  on(clearBtn, 'click', () => cb.onClearFilters());
  box.appendChild(clearBtn);
  return box;
}
