/**
 * The side rail: Issues, Inspector and Outline.
 *
 * The Outline tab is the screen-reader-complete path through the graph — a real
 * nested tree with the same labels and jump targets as the canvas.
 */

import { add, button, clear, el, fileLine, iconButton, on } from '../dom.js';
import { uiIcon } from '../icons.js';
import { severityGlyph, SEVERITY_ORDER, normalizeSeverity } from '../markers.js';
import { renderOutlineTree } from './outline.js';
import type { Issue, Loc, MLNode, RailTab, RelatedLoc } from '../types.js';
import type { GraphIndex } from '../layout/model.js';

export interface RailCallbacks {
  onTab(tab: RailTab): void;
  onClearFilters(): void;
  onSelectIssue(id: string): void;
  onSelectNode(id: string): void;
  onOpen(loc: Loc | RelatedLoc): void;
  onResize(width: number): void;
  onToggleRail(): void;
  onAsk(nodeId: string): void;
  /** The Outline's lane rows jump to a stage. */
  onSelectLane(laneId: string): void;
  /** Left/Right in the Outline collapses the same group the canvas draws. */
  onToggleCollapse(nodeId: string): void;
  /** "Show all" — clears the scope. Filters are a separate control. */
  onClearScope(): void;
  /** Inspector: scope the diagram to the selected unit or step. */
  onScopeToNode(nodeId: string): void;
}

export interface RailState {
  index: GraphIndex | null;
  canAskAssistant: boolean;
  tab: RailTab;
  issues: Issue[];
  selectedNode: MLNode | null;
  selectedIssueId: string | null;
  /** The canvas's collapsed groups — the Outline mirrors them (MLV-R2-W08). */
  collapsed: Set<string>;
  keep(issue: Issue): boolean;
  /**
   * Present only under a scope. `total` is PROJECT-LEVEL: the rail must always
   * be able to say how many findings live outside the current view, or a scope
   * reads as a clean bill of health (FEATURES 3.7).
   */
  scope: { shown: number; hidden: number; total: number } | null;
}

let railSeq = 0;

export class Rail {
  readonly root: HTMLElement;
  private tabs = new Map<RailTab, HTMLButtonElement>();
  private panels = new Map<RailTab, HTMLElement>();
  private cb: RailCallbacks;

  constructor(cb: RailCallbacks) {
    this.cb = cb;
    const uid = 'mlv' + ++railSeq;
    this.root = el('aside', 'mlv-rail');
    this.root.setAttribute('aria-label', 'MLView details');

    const grip = add(this.root, el('div', 'mlv-rail__grip'));
    grip.setAttribute('role', 'separator');
    grip.setAttribute('aria-orientation', 'vertical');
    grip.setAttribute('aria-label', 'Resize side rail');
    grip.tabIndex = 0;
    this.wireResize(grip);

    const strip = add(this.root, el('div', 'mlv-rail__tabs'));
    strip.setAttribute('role', 'tablist');
    const defs: { id: RailTab; label: string }[] = [
      { id: 'issues', label: 'Issues' },
      { id: 'inspector', label: 'Inspector' },
      { id: 'outline', label: 'Outline' },
    ];
    for (const d of defs) {
      const b = el('button', 'mlv-rail__tab', d.label) as HTMLButtonElement;
      b.type = 'button';
      b.id = uid + '-tab-' + d.id;
      b.setAttribute('role', 'tab');
      b.setAttribute('aria-controls', uid + '-panel-' + d.id);
      b.setAttribute('aria-selected', 'false');
      on(b, 'click', () => cb.onTab(d.id));
      strip.appendChild(b);
      this.tabs.set(d.id, b);

      const panel = el('div', 'mlv-rail__panel');
      panel.id = uid + '-panel-' + d.id;
      panel.setAttribute('role', 'tabpanel');
      panel.setAttribute('aria-labelledby', b.id);
      panel.tabIndex = 0;
      panel.hidden = true;
      this.root.appendChild(panel);
      this.panels.set(d.id, panel);
    }
  }

  private wireResize(grip: HTMLElement): void {
    let startX = 0;
    let startW = 0;
    const move = (ev: PointerEvent) => {
      const next = startW + (startX - ev.clientX);
      this.cb.onResize(next);
    };
    const up = () => {
      document.removeEventListener('pointermove', move as EventListener);
      document.removeEventListener('pointerup', up);
    };
    on(grip, 'pointerdown', (ev: PointerEvent) => {
      startX = ev.clientX;
      startW = this.root.getBoundingClientRect().width || 360;
      document.addEventListener('pointermove', move as EventListener);
      document.addEventListener('pointerup', up);
      ev.preventDefault();
    });
    on(grip, 'keydown', (ev: KeyboardEvent) => {
      const cur = this.root.getBoundingClientRect().width || 360;
      if (ev.key === 'ArrowLeft') this.cb.onResize(cur + 16);
      else if (ev.key === 'ArrowRight') this.cb.onResize(cur - 16);
      else return;
      ev.preventDefault();
    });
  }

  update(s: RailState): void {
    // Every render replaces the panel's DOM, so a row the user is standing on
    // would take the keyboard focus down with it. Put it back on the same row.
    const restoreFocus = this.captureFocus();
    for (const [id, tab] of this.tabs) {
      const active = id === s.tab;
      tab.setAttribute('aria-selected', active ? 'true' : 'false');
      tab.tabIndex = active ? 0 : -1;
      const panel = this.panels.get(id)!;
      panel.hidden = !active;
    }
    this.renderIssues(s);
    this.renderInspector(s);
    this.renderOutline(s);
    restoreFocus();
  }

  /**
   * Remember which row owns the focus, by id, and hand back a function that
   * finds that row again in the freshly built DOM.
   */
  private captureFocus(): () => void {
    const active =
      typeof document !== 'undefined' ? (document.activeElement as HTMLElement | null) : null;
    if (!active || typeof active.closest !== 'function' || !this.root.contains(active)) {
      return () => undefined;
    }
    const owner = active.closest('[data-issue-id][role="option"], [data-outline-id], [data-outline-lane]');
    if (!owner) return () => undefined;
    const attr = owner.hasAttribute('data-issue-id')
      ? 'data-issue-id'
      : owner.hasAttribute('data-outline-id')
        ? 'data-outline-id'
        : 'data-outline-lane';
    const value = owner.getAttribute(attr) || '';
    return () => {
      const next = this.root.querySelector('[' + attr + '="' + value + '"]') as HTMLElement | null;
      if (!next) return;
      // Moving the tab stop with the focus keeps the roving tabindex honest.
      const composite = next.closest('[role="tree"], [role="listbox"]');
      if (composite) {
        const peers = composite.querySelectorAll('[role="treeitem"], [role="option"]');
        for (let i = 0; i < peers.length; i++) (peers[i] as HTMLElement).tabIndex = -1;
      }
      next.tabIndex = 0;
      try {
        next.focus();
      } catch (_e) {
        /* a host may have detached the panel already */
      }
    };
  }

  private renderIssues(s: RailState): void {
    const panel = this.panels.get('issues')!;
    clear(panel);
    if (!s.index) {
      add(panel, el('div', 'mlv-empty-note', 'No analysis loaded yet.'));
      return;
    }
    const visible = s.issues.filter(s.keep);
    if (s.scope) panel.appendChild(this.scopeLine(s.scope));
    if (!visible.length) {
      // FOUR very different results, told apart: nothing was analysed, nothing
      // was wrong, the filters excluded everything, or the SCOPE excludes them
      // (MLV-R1-013, MLV-R2-W05, FEATURES 3.7). Getting these apart is what
      // stops a scope from reading as a clean bill of health.
      if (s.scope && s.scope.hidden > 0) panel.appendChild(this.scopeEmptyState(s.scope));
      else if (s.issues.length) panel.appendChild(this.filteredEmptyState());
      else if ((s.index.graph.nodes || []).length === 0) panel.appendChild(this.nothingAnalyzedState(s));
      else panel.appendChild(this.cleanState(s));
      return;
    }
    for (const sev of SEVERITY_ORDER) {
      const group = visible.filter((i) => normalizeSeverity(i.severity) === sev);
      if (!group.length) continue;
      const section = add(panel, el('section', 'mlv-rail__section'));
      const heading = add(section, el('h3', 'mlv-rail__heading'));
      heading.appendChild(severityGlyph(sev, 12, ''));
      add(heading, el('span', '', sev + ' · ' + group.length));
      const list = add(section, el('ul', 'mlv-issues'));
      list.setAttribute('role', 'listbox');
      list.setAttribute('aria-label', sev + ' severity issues');
      for (const issue of group) list.appendChild(this.issueRow(issue, s));
      this.wireListbox(list);
    }
  }

  /**
   * The listbox is one composite widget with ONE tab stop: the selected option,
   * or the first. Arrow keys move the focus inside it. Before this the row was a
   * real <button> with a second <button> nested in it, which is invalid HTML,
   * illegal under `role="option"`, and cost two Tab presses per finding
   * (MLV-R2-W03).
   */
  private wireListbox(list: HTMLElement): void {
    const options = () => Array.prototype.slice.call(list.querySelectorAll('[role="option"]')) as HTMLElement[];
    const all = options();
    let active = all.filter((o) => o.getAttribute('aria-selected') === 'true')[0] || all[0] || null;
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
        if (id) this.cb.onSelectIssue(id);
        return;
      } else return;
      ev.preventDefault();
      if (!next) return;
      for (const item of items) item.tabIndex = item === next ? 0 : -1;
      active = next;
      next.focus();
    });
  }

  /** The zero-issue result: good news, stated as good news. */
  private cleanState(s: RailState): HTMLElement {
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
  private nothingAnalyzedState(s: RailState): HTMLElement {
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
        'No ML pipeline was found, so there is nothing to flag. ' +
          files +
          (files === 1 ? ' file' : ' files') +
          ' analyzed.',
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
  private scopeLine(scope: { shown: number; hidden: number; total: number }): HTMLElement {
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
    on(all, 'click', () => this.cb.onClearScope());
    box.appendChild(all);
    return box;
  }

  /** The fourth empty state: in scope, but nothing is wrong HERE. */
  private scopeEmptyState(scope: { hidden: number; total: number }): HTMLElement {
    const box = el('div', 'mlv-empty-note');
    box.setAttribute('role', 'status');
    box.setAttribute('data-scope-empty-rail', '1');
    add(box, el('div', 'mlv-clean__title', 'No findings in this scope'));
    add(box, el('div', 'mlv-clean__detail', scope.hidden + ' elsewhere in this project.'));
    const all = button('mlv-btn', 'Show all');
    on(all, 'click', () => this.cb.onClearScope());
    box.appendChild(all);
    return box;
  }

  /** The filters excluded everything: say so, and offer the way back. */
  private filteredEmptyState(): HTMLElement {
    const box = el('div', 'mlv-empty-note');
    add(box, el('div', '', 'No issues match these filters.'));
    const clear = button('mlv-btn', 'Clear filters');
    on(clear, 'click', () => this.cb.onClearFilters());
    box.appendChild(clear);
    return box;
  }

  private issueRow(issue: Issue, s: RailState): HTMLElement {
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
    // The bucket chip is the flag for DOUBT (UX_DESIGN section 7). Printing it on
    // every certain finding drains the signal from the rows that need it.
    if (issue.confidenceBucket === 'possible' || issue.confidenceBucket === 'speculative') {
      add(meta, el('span', 'mlv-chip', issue.confidenceBucket));
    }
    if (issue.suppressed) add(meta, el('span', 'mlv-chip', 'suppressed'));
    on(row, 'click', () => this.cb.onSelectIssue(issue.id));
    li.appendChild(row);

    // A sibling of the option, never a child of it (MLV-R2-W03).
    const open = iconButton('mlv-btn mlv-btn--icon mlv-issue__open', 'Open ' + fileLine(issue.loc));
    open.appendChild(uiIcon('open', 12));
    on(open, 'click', (ev: Event) => {
      ev.stopPropagation();
      this.cb.onOpen(issue.loc);
    });
    li.appendChild(open);

    // The selected row expands in place with the message, the why line, the fix
    // hint and a Go to button per location — the most valuable content in the
    // product used to be unreachable from the Issues tab entirely (MLV-R1-006).
    if (selected) li.appendChild(this.issueDetail(issue));
    return li;
  }

  /** The expanded body of a selected issue row. */
  private issueDetail(issue: Issue): HTMLElement {
    const box = el('div', 'mlv-issue__detail');
    box.setAttribute('data-issue-detail', issue.id);
    if (issue.message) add(box, el('p', 'mlv-insp__line', issue.message));
    if (issue.why) add(box, el('p', 'mlv-insp__line mlv-insp__why', issue.why));
    if (issue.fixHint) add(box, el('div', 'mlv-insp__fix', issue.fixHint));
    const actions = add(box, el('div', 'mlv-issue__goto'));
    const primary = button('mlv-btn', 'Go to ' + fileLine(issue.loc));
    on(primary, 'click', (ev: Event) => {
      ev.stopPropagation();
      this.cb.onOpen(issue.loc);
    });
    actions.appendChild(primary);
    for (const rel of issue.relatedLocs || []) {
      const label = 'Go to ' + (rel.message || rel.role.replace(/_/g, ' ')) + ' — ' + fileLine(rel);
      const b = button('mlv-btn', label);
      on(b, 'click', (ev: Event) => {
        ev.stopPropagation();
        this.cb.onOpen(rel);
      });
      actions.appendChild(b);
    }
    return box;
  }

  private renderInspector(s: RailState): void {
    const panel = this.panels.get('inspector')!;
    clear(panel);
    const node = s.selectedNode;
    if (!node || !s.index) {
      add(panel, el('div', 'mlv-empty-note', 'Select a node to inspect it.'));
      return;
    }
    add(panel, el('h2', 'mlv-insp__title', node.label || node.qualname));
    const meta = add(panel, el('div', 'mlv-insp__meta'));
    const stageChip = add(meta, el('span', 'mlv-chip mlv-chip--stage', node.stage));
    stageChip.setAttribute('data-stage', node.stage);
    add(meta, el('span', 'mlv-chip', node.kind));
    add(meta, el('span', 'mlv-chip', node.level));
    if (node.framework) add(meta, el('span', 'mlv-chip', node.framework));
    add(meta, el('span', 'mlv-chip', node.confidenceBucket));
    if (node.ghost) add(meta, el('span', 'mlv-chip', 'missing step'));
    if (node.dynamic) add(meta, el('span', 'mlv-chip', 'dynamic scope'));

    add(panel, el('div', 'mlv-insp__fqn', node.fqn || node.qualname));

    const actions = add(panel, el('div', 'mlv-insp__actions'));
    const openBtn = button('mlv-btn mlv-btn--primary', 'Open ' + fileLine(node.loc));
    on(openBtn, 'click', () => this.cb.onOpen(node.loc));
    actions.appendChild(openBtn);
    if (s.canAskAssistant) {
      const ask = button('mlv-btn', 'Ask about this node');
      on(ask, 'click', () => this.cb.onAsk(node.id));
      actions.appendChild(ask);
    }
    // "unit" for a definition, "step" for a call-site op: the word has to match
    // what the user is looking at, or the button reads as a different feature.
    const scopeWord = node.level === 'unit' || node.level === 'stage' ? 'unit' : 'step';
    const scopeBtn = button('mlv-btn mlv-btn--scope-node', 'Scope to this ' + scopeWord);
    scopeBtn.setAttribute('data-scope-node', node.id);
    on(scopeBtn, 'click', () => this.cb.onScopeToNode(node.id));
    actions.appendChild(scopeBtn);

    if (node.loc.snippet) {
      const pre = add(panel, el('pre', 'mlv-banner__detail', node.loc.snippet));
      pre.style.marginTop = 'var(--mlv-s4)';
    }

    const attrKeys = Object.keys(node.attrs || {});
    if (attrKeys.length) {
      panel.appendChild(this.heading('Attributes'));
      const table = add(panel, el('table', 'mlv-table'));
      const tbody = add(table, el('tbody'));
      for (const k of attrKeys) {
        const tr = add(tbody, el('tr'));
        add(tr, el('th', '', k));
        add(tr, el('td', '', node.attrs[k]));
      }
    }

    if ((node.consumes || []).length || (node.produces || []).length) {
      panel.appendChild(this.heading('Ports'));
      const table = add(panel, el('table', 'mlv-table'));
      const tbody = add(table, el('tbody'));
      for (const p of node.consumes || []) {
        const tr = add(tbody, el('tr'));
        add(tr, el('th', '', 'in · ' + p.name));
        add(tr, el('td', '', (p.tags || []).join(', ')));
      }
      for (const p of node.produces || []) {
        const tr = add(tbody, el('tr'));
        add(tr, el('th', '', 'out · ' + p.name));
        add(tr, el('td', '', (p.tags || []).join(', ')));
      }
    }

    if ((node.stageEvidence || []).length) {
      panel.appendChild(this.heading('Why this stage'));
      const table = add(panel, el('table', 'mlv-table'));
      const tbody = add(table, el('tbody'));
      for (const e of node.stageEvidence) {
        const tr = add(tbody, el('tr'));
        add(tr, el('th', '', e.kind));
        add(tr, el('td', '', e.detail));
      }
    }

    const issues = s.index.issuesOf(node.id, s.keep);
    if (issues.length) {
      panel.appendChild(this.heading('Issues'));
      for (const issue of issues) {
        const box = this.inspectorIssue(issue);
        if (s.selectedIssueId === issue.id) box.classList.add('is-selected');
        panel.appendChild(box);
      }
    }
  }

  private inspectorIssue(issue: Issue): HTMLElement {
    const box = el('div', 'mlv-insp__issue');
    box.setAttribute('data-issue-id', issue.id);
    const head = add(box, el('div', 'mlv-insp__issue-head'));
    head.appendChild(severityGlyph(issue.severity, 14, ''));
    add(head, el('span', 'mlv-mono', issue.code));
    add(head, el('span', '', issue.title));
    add(box, el('p', 'mlv-insp__line', issue.message));
    add(box, el('p', 'mlv-insp__line', issue.why));
    add(box, el('div', 'mlv-insp__fix', issue.fixHint));
    if ((issue.relatedLocs || []).length) {
      const list = add(box, el('ul', 'mlv-insp__related'));
      for (const rel of issue.relatedLocs) {
        const li = add(list, el('li'));
        const link = el('button', 'mlv-link', (rel.message || rel.role) + ' — ' + fileLine(rel));
        link.type = 'button';
        on(link, 'click', () => this.cb.onOpen(rel));
        li.appendChild(link);
      }
    }
    return box;
  }

  private heading(text: string): HTMLElement {
    const h = el('h3', 'mlv-rail__heading');
    h.textContent = text;
    return h;
  }

  private renderOutline(s: RailState): void {
    const panel = this.panels.get('outline')!;
    clear(panel);
    const index = s.index;
    if (!index) {
      add(panel, el('div', 'mlv-empty-note', 'No analysis loaded yet.'));
      return;
    }
    renderOutlineTree(
      panel,
      {
        index,
        keep: s.keep,
        selectedNodeId: s.selectedNode ? s.selectedNode.id : null,
        collapsed: s.collapsed,
      },
      {
        onSelectNode: (id) => this.cb.onSelectNode(id),
        onSelectLane: (laneId) => this.cb.onSelectLane(laneId),
        onToggleCollapse: (id) => this.cb.onToggleCollapse(id),
      },
    );
  }
}
