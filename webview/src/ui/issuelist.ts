/**
 * The Findings panel: the severity sections, the rows and the empty states.
 *
 * The rail file owns the four tabs (the Selection, About and Outline panes are their own files);
 * this one owns everything under the Findings tab.
 */

import { add, button, clear, el, fileLine, locSpan, iconButton, on } from '../dom.js';
import { locSpoken } from '../notebook.js';
import { uiIcon } from '../icons.js';
import { severityGlyph, SEVERITY_ORDER, normalizeSeverity } from '../markers.js';
import { basisChip } from './evidence.js';
import { basisSpoken } from '../render/edges.js';
import type { GraphIndex } from '../layout/model.js';
import { allElsewhere, STALE_TEXT } from '../freshness.js';
import type { Issue, Loc, RelatedLoc, StaleReason } from '../types.js';
import { changeOf, changeSentence, changeSpoken, changeTagText } from '../revisiondiff.js';
import type { RevisionDiff } from '../revisiondiff.js';

export interface IssueListCallbacks {
  /**
   * A click or Space on a row: select the finding (never opens the source). A click
   * passes its event, so the second click of a double-click can open the finding.
   */
  onSelectIssue(id: string, ev?: MouseEvent): void;
  /** Enter on a row, or a double-click: select and open its first cited range; Alt moves focus. */
  onOpenIssue(id: string, focusEditor: boolean): void;
  /** An Open / Go to control; `focusEditor` for Alt+click or Alt+Enter. */
  onOpen(loc: Loc | RelatedLoc, focusEditor?: boolean): void;
  onClearFilters(): void;
}

export interface IssueListState {
  index: GraphIndex | null;
  issues: Issue[];
  keep(issue: Issue): boolean;
  selectedIssueId: string | null;
  /** Why a cited file no longer matches the published revision, if it does not. */
  staleReason?(file: string): StaleReason | undefined;
  /**
   * What changed since the revision this panel showed before; a finding added
   * or changed there carries a "new" or "changed" tag, said in its row's name.
   */
  changes?: RevisionDiff | null;
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

/**
 * "cites a changed file", "cites a missing file" or "cites changed or missing files"; "cites a file
 * in another folder" when the host found every one unchanged elsewhere (the host's root hint).
 */
export function staleChipText(reasons: StaleReason[]): string {
  if (allElsewhere(reasons)) return 'cites a file in another folder';
  if (reasons.length === 1 && reasons[0] === 'changed') return 'cites a changed file';
  if (reasons.indexOf('changed') < 0) return reasons.length === 1 ? 'cites a missing file' : 'cites missing files';
  return 'cites changed or missing files';
}

/**
 * A finding's `suggestion`, labelled "What to change", or null when the author wrote none,
 * so no label ever stands over nothing. The Selection pane passes
 * `h5` so the label is a heading among the finding's other sections; the Findings list uses a
 * plain label inside the expanded row. A finding listed under a step in the Selection pane
 * passes `h6` (it sits under that finding's section heading).
 */
export function suggestionBlock(issue: Issue, labelTag: 'h5' | 'h6' | 'div' = 'div'): HTMLElement | null {
  const text = (issue.fixHint || '').trim();
  if (!text) return null;
  const box = el('div', 'mlv-insp__fix');
  box.setAttribute('data-suggestion', issue.id);
  add(box, el(labelTag, 'mlv-insp__fix-label', 'What to change'));
  add(box, el('p', 'mlv-insp__fix-text', issue.fixHint));
  return box;
}

/**
 * An Open / Go to control. A click opens beside the panel with focus kept here;
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
  // The panel's own heading, so the outline reads h1 -> h2 -> h3 -> h4
  // top-down instead of starting at a rail `h3` above the two `h2`s. Visually
  // hidden: the tab strip already names the panel on screen.
  add(panel, el('h3', 'mlv-sr', 'Findings'));
  if (!s.index) {
    add(panel, el('div', 'mlv-empty-note', 'No workflow loaded yet.'));
    return;
  }
  const visible = s.issues.filter(s.keep);
  if (!visible.length) {
    // Different results, told apart: there are no steps, nothing was recorded,
    // or the filters excluded everything.
    if (s.issues.length) panel.appendChild(filteredEmptyState(cb));
    else if ((s.index.graph.nodes || []).length === 0) panel.appendChild(noStepsState(s));
    else panel.appendChild(noFindingsRecordedState(s));
    return;
  }
  for (const sev of SEVERITY_ORDER) {
    const group = visible.filter((i) => normalizeSeverity(i.severity) === sev);
    if (!group.length) continue;
    const section = add(panel, el('section', 'mlv-rail__section'));
    section.setAttribute('data-severity-section', sev);
    // h4 under the panel's h3.
    const heading = add(section, el('h4', 'mlv-rail__heading'));
    heading.appendChild(severityGlyph(sev, 12, ''));
    // The count names its unit.
    add(heading, el('span', '', sev + ' · ' + group.length + (group.length === 1 ? ' finding' : ' findings')));
    section.appendChild(flatList(group, sev, s, cb));
  }
}

/* ── Lists ─────────────────────────────────────────────────────────────── */

function flatList(issues: Issue[], sev: string, s: IssueListState, cb: IssueListCallbacks, label?: string): HTMLElement {
  const list = el('ul', 'mlv-issues');
  list.setAttribute('role', 'listbox');
  list.setAttribute('aria-label', label || sev + ' severity findings');
  for (const issue of issues) list.appendChild(issueRow(issue, s, cb));
  wireListbox(list, cb);
  return list;
}

/* ── One row ───────────────────────────────────────────────────────────── */

function issueRow(issue: Issue, s: IssueListState, cb: IssueListCallbacks): HTMLElement {
  const selected = s.selectedIssueId === issue.id;
  const li = el('li', 'mlv-issues__item');
  li.setAttribute('role', 'presentation');
  // A div, not a <button>: `role="option"` may not contain a focusable
  // descendant, and the "open in editor" control beside it is a real button
  // (render/nodes.ts makes the group header a div for the same reason).
  const row = el('div', 'mlv-issue');
  row.setAttribute('role', 'option');
  row.tabIndex = -1;
  row.setAttribute('data-issue-id', issue.id);
  row.setAttribute('aria-selected', selected ? 'true' : 'false');
  row.setAttribute(
    'aria-label',
    (issue.short ? issue.short + ', ' : '') + issue.code + ' ' + issue.severity + ' severity, ' + issue.title +
      (issue.loc.file ? ', ' + locSpoken(issue.loc) : '') +
      // The basis only when it is not observed, as on the canvas.
      basisSpoken(issue.basis),
  );
  if (selected) row.classList.add('is-selected');
  const stale = issueStaleReasons(issue, s.staleReason);
  if (stale.length) {
    row.classList.add('is-stale');
    row.setAttribute('data-stale', stale.join(' '));
    row.setAttribute('aria-label', row.getAttribute('aria-label') + ', ' + staleChipText(stale) + (allElsewhere(stale) ? '' : ' since publishing'));
  }
  row.appendChild(severityGlyph(issue.severity, 14, ''));
  // The short label the canvas badges print; the real id stays in the meta line.
  if (issue.short) add(row, el('span', 'mlv-issue__short', issue.short));
  const text = add(row, el('div', 'mlv-issue__text'));
  add(text, el('div', 'mlv-issue__title', issue.title));
  const meta = add(text, el('div', 'mlv-issue__meta'));
  add(meta, el('span', '', issue.code));
  if (issue.loc.file) meta.appendChild(locSpan('', issue.loc));
  // Only the exceptions are marked, as on the canvas; the legend
  // says an unmarked claim is observed.
  const chip = basisChip(issue);
  if (chip) meta.appendChild(chip);
  if (stale.length) meta.appendChild(staleChip(stale));
  // Added or changed since the revision this panel showed before.
  const change = changeOf(s.changes, 'issue', issue.id);
  if (change && s.changes) {
    row.setAttribute('aria-label', row.getAttribute('aria-label') + ', ' + changeSpoken(change));
    const tag = add(meta, el('span', 'mlv-rev-tag mlv-rev-tag--row', changeTagText(change)));
    tag.setAttribute('data-change', change.status);
    tag.setAttribute('aria-hidden', 'true');
    tag.title = changeSentence(change, s.changes.since);
  }
  on(row, 'click', (ev: MouseEvent) => cb.onSelectIssue(issue.id, ev));
  li.appendChild(row);

  // A sibling of the option, never a child of it.
  if (issue.loc.file) {
    const open = iconButton('mlv-btn mlv-btn--icon mlv-issue__open', 'Open ' + fileLine(issue.loc));
    open.appendChild(uiIcon('open', 12));
    wireOpenControl(open, issue.loc, cb.onOpen, s.staleReason ? s.staleReason(issue.loc.file) : undefined);
    li.appendChild(open);
  }

  // The selected row expands in place with the message, the suggestion and a
  // Go to button per location, so what a finding says and where it points can
  // be read and reached from the Findings tab.
  if (selected) li.appendChild(issueDetail(issue, s, cb));
  return li;
}

/** A finding's freshness chip: an icon and words, so it never relies on colour alone. */
function staleChip(reasons: StaleReason[]): HTMLElement {
  const chip = el('span', 'mlv-chip mlv-chip--stale');
  chip.appendChild(uiIcon('warning', 11));
  add(chip, el('span', '', staleChipText(reasons)));
  chip.setAttribute('data-stale', reasons.join(' '));
  chip.title = allElsewhere(reasons)
    ? 'A file this finding cites is not under the workspace root; it is unchanged in another folder, which the notice above names. Its jump is blocked.'
    : 'A file this finding cites no longer matches the published revision. Its jump is blocked.';
  return chip;
}

/** The expanded body of a selected finding row. */
function issueDetail(issue: Issue, s: IssueListState, cb: IssueListCallbacks): HTMLElement {
  const box = el('div', 'mlv-issue__detail');
  box.setAttribute('data-issue-detail', issue.id);
  if (issue.message) add(box, el('p', 'mlv-insp__line', issue.message));
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
 * or the first. Arrow keys move the focus inside it. The row is not a <button>
 * with a second <button> nested in it: that is invalid HTML, illegal under
 * `role="option"`, and would cost two Tab presses per finding.
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
      // Enter opens the finding's first cited range beside the panel (Alt+Enter moves
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

/* ── The four zeros ────────────────────────────────────────────────────── */

/**
 * Zero findings in an authored revision means only that the
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
        (limits ? '; ' + limits + (limits === 1 ? ' limitation' : ' limitations') + ' listed in About' : '') +
        '. This is not a check result.',
    ),
  );
  return box;
}

/**
 * A workflow with no steps. The canvas says "No workflow steps" (ui/states.ts);
 * a rail that answered "No issues found" beside it would read as a clean bill
 * of health for a diagram that shows nothing.
 */
function noStepsState(s: IssueListState): HTMLElement {
  const box = el('div', 'mlv-empty-note');
  box.setAttribute('role', 'status');
  add(box, el('div', 'mlv-clean__title', 'No steps'));
  const graph = s.index ? s.index.graph : null;
  const diags = graph ? graph.diagnostics || [] : [];
  const files = graph ? graph.workspace.filesInspected : 0;
  add(
    box,
    el(
      'div',
      'mlv-clean__detail',
      'This diagram has no steps, so there is nothing to flag. The author inspected ' + files + (files === 1 ? ' file' : ' files') + '.',
    ),
  );
  if (diags.length) {
    const list = add(box, el('ul', 'mlv-state__list'));
    for (const d of diags.slice(0, 5)) {
      add(list, el('li', '', d.kind + ' — ' + d.message));
    }
  }
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
