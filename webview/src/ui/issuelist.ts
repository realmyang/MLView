/**
 * The Findings panel: the severity sections, the rows and the empty states.
 *
 * The rail file owns the three tabs, the Inspector and the Outline; this one
 * owns everything under the Findings tab.
 */

import { add, button, clear, el, fileLine, locSpan, iconButton, on } from '../dom.js';
import { locSpoken } from '../notebook.js';
import { uiIcon } from '../icons.js';
import { severityGlyph, SEVERITY_ORDER, normalizeSeverity } from '../markers.js';
import { confidenceChip } from './evidence.js';
import { blindSpots, coverageHeadline } from './chromenotes.js';
import type { GraphIndex } from '../layout/model.js';
import { STALE_TEXT } from '../freshness.js';
import type { Issue, Loc, RelatedLoc, StaleReason } from '../types.js';

export interface IssueListCallbacks {
  /** A click or Space on a row: select the finding (viewer M1: never opens the source). */
  onSelectIssue(id: string): void;
  /** Enter on a row, or a double-click: select and open its first cited range; Alt moves focus. */
  onOpenIssue(id: string, focusEditor: boolean): void;
  /** An Open / Go to control; `focusEditor` for Alt+click or Alt+Enter. */
  onOpen(loc: Loc | RelatedLoc, focusEditor?: boolean): void;
  onClearFilters(): void;
  onClearScope(): void;
}

export interface IssueListState {
  index: GraphIndex | null;
  issues: Issue[];
  keep(issue: Issue): boolean;
  selectedIssueId: string | null;
  scope: { shown: number; hidden: number; total: number; where: string } | null;
  /** Viewer M1: why a cited file no longer matches the published revision, if it does not. */
  staleReason?(file: string): StaleReason | undefined;
}

/** The stale reasons among a finding's cited files (supporting and counter-evidence). */
export function issueStaleReasons(issue: Issue, staleReason: ((file: string) => StaleReason | undefined) | undefined): StaleReason[] {
  if (!staleReason) return [];
  const out: StaleReason[] = [];
  for (const loc of [issue.loc as Loc].concat(issue.relatedLocs || [])) {
    const reason = loc && loc.file ? staleReason(loc.file) : undefined;
    if (reason && out.indexOf(reason) < 0) out.push(reason);
  }
  return out;
}

/** "cites a changed file", "cites a missing file" or "cites changed or missing files". */
export function staleChipText(reasons: StaleReason[]): string {
  if (reasons.length === 1 && reasons[0] === 'changed') return 'cites a changed file';
  if (reasons.indexOf('changed') < 0) return reasons.length === 1 ? 'cites a missing file' : 'cites missing files';
  return 'cites changed or missing files';
}

/**
 * Viewer M1: a finding's `suggestion`, labelled "What to change" (the skill's own words for it),
 * or null when the author wrote none, so no label ever stands over nothing. The Inspector passes
 * `h5` so the label is a heading among the finding's other sections; the Findings list uses a
 * plain label inside the expanded row.
 */
export function suggestionBlock(issue: Issue, labelTag: 'h5' | 'div' = 'div'): HTMLElement | null {
  const text = (issue.fixHint || '').trim();
  if (!text) return null;
  const box = el('div', 'mlv-insp__fix');
  box.setAttribute('data-suggestion', issue.id);
  add(box, el(labelTag, 'mlv-insp__fix-label', 'What to change'));
  add(box, el('p', 'mlv-insp__fix-text', issue.fixHint));
  return box;
}

/**
 * An Open / Go to control (viewer M1). A click opens beside the panel with focus kept here;
 * Alt+click and Alt+Enter move focus to the editor. A quote whose file is stale gets a disabled
 * control that says why instead.
 */
export function wireOpenControl(control: HTMLButtonElement, loc: Loc | RelatedLoc, onOpen: (loc: Loc | RelatedLoc, focusEditor?: boolean) => void, staleReason?: StaleReason): void {
  if (staleReason) {
    control.disabled = true;
    control.classList.add('is-stale');
    control.setAttribute('data-stale', staleReason);
    const why = fileLine(loc) + ': ' + STALE_TEXT[staleReason] + '. Not opened.';
    control.title = why;
    control.setAttribute('aria-label', why);
    return;
  }
  on(control, 'click', (ev: MouseEvent) => {
    ev.stopPropagation();
    onOpen(loc, ev.altKey);
  });
  on(control, 'keydown', (ev: KeyboardEvent) => {
    if (ev.key !== 'Enter' || !ev.altKey) return;
    ev.preventDefault();
    ev.stopPropagation();
    onOpen(loc, true);
  });
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
  if (s.scope) panel.appendChild(scopeLine(s.scope, cb));
  if (!visible.length) {
    // Very different results, told apart: nothing was analysed, nothing was
    // recorded, the filters excluded everything, or the SCOPE excludes them
    // (MLV-R1-013, MLV-R2-W05, FEATURES 3.7). Getting these apart is what stops
    // a scope from reading as a clean bill of health.
    if (s.scope && s.scope.hidden > 0) panel.appendChild(scopeEmptyState(s.scope, cb));
    else if (s.issues.length) panel.appendChild(filteredEmptyState(cb));
    else if ((s.index.graph.nodes || []).length === 0) panel.appendChild(nothingAnalyzedState(s));
    else if (s.index.graph.schemaVersion === 'workflow-view/1') panel.appendChild(noFindingsRecordedState(s));
    else panel.appendChild(cleanState(s));
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
    section.appendChild(flatList(group, sev, s, cb));
  }
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
  const stale = issueStaleReasons(issue, s.staleReason);
  if (stale.length) {
    row.classList.add('is-stale');
    row.setAttribute('data-stale', stale.join(' '));
    row.setAttribute('aria-label', row.getAttribute('aria-label') + ', ' + staleChipText(stale) + ' since publishing');
  }
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
  if (stale.length) meta.appendChild(staleChip(stale));
  on(row, 'click', () => cb.onSelectIssue(issue.id));
  li.appendChild(row);

  // A sibling of the option, never a child of it (MLV-R2-W03).
  if (issue.loc.file) {
    const open = iconButton('mlv-btn mlv-btn--icon mlv-issue__open', 'Open ' + fileLine(issue.loc));
    open.appendChild(uiIcon('open', 12));
    wireOpenControl(open, issue.loc, cb.onOpen, s.staleReason ? s.staleReason(issue.loc.file) : undefined);
    li.appendChild(open);
  }

  // The selected row expands in place with the message, the why line, the fix
  // hint and a Go to button per location — the most valuable content in the
  // product used to be unreachable from the Issues tab entirely (MLV-R1-006).
  if (selected) li.appendChild(issueDetail(issue, s, cb));
  return li;
}

/** A finding's freshness chip: an icon and words, so it never relies on colour alone. */
function staleChip(reasons: StaleReason[]): HTMLElement {
  const chip = el('span', 'mlv-chip mlv-chip--stale');
  chip.appendChild(uiIcon('warning', 11));
  add(chip, el('span', '', staleChipText(reasons)));
  chip.setAttribute('data-stale', reasons.join(' '));
  chip.title = 'A file this finding cites no longer matches the published revision. Its jump is blocked.';
  return chip;
}

/** The expanded body of a selected issue row. */
function issueDetail(issue: Issue, s: IssueListState, cb: IssueListCallbacks): HTMLElement {
  const box = el('div', 'mlv-issue__detail');
  box.setAttribute('data-issue-detail', issue.id);
  if (issue.message) add(box, el('p', 'mlv-insp__line', issue.message));
  if (issue.why) add(box, el('p', 'mlv-insp__line mlv-insp__why', issue.why));
  const suggestion = suggestionBlock(issue);
  if (suggestion) box.appendChild(suggestion);
  const actions = add(box, el('div', 'mlv-issue__goto'));
  if (issue.loc.file) {
    const primary = button('mlv-btn', 'Go to ' + fileLine(issue.loc));
    wireOpenControl(primary, issue.loc, cb.onOpen, s.staleReason ? s.staleReason(issue.loc.file) : undefined);
    actions.appendChild(primary);
  }
  for (const rel of issue.relatedLocs || []) {
    const label = 'Go to ' + (rel.message || rel.role.replace(/_/g, ' ')) + ' — ' + fileLine(rel);
    const b = button('mlv-btn', label);
    wireOpenControl(b, rel, cb.onOpen, s.staleReason ? s.staleReason(rel.file) : undefined);
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
    else if (ev.key === 'Enter') {
      // Viewer M1: Enter opens the finding's first cited range beside the panel (Alt+Enter moves
      // focus to the editor); Space only selects.
      if (ev.ctrlKey || ev.metaKey || ev.shiftKey) return;
      ev.preventDefault();
      const id = option.getAttribute('data-issue-id');
      if (id) cb.onOpenIssue(id, ev.altKey);
      return;
    } else if (ev.key === ' ') {
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
  add(box, el('div', '', 'No findings match these filters.'));
  const clearBtn = button('mlv-btn', 'Clear filters');
  on(clearBtn, 'click', () => cb.onClearFilters());
  box.appendChild(clearBtn);
  return box;
}
