/**
 * The side rail: Issues, Inspector and Outline.
 *
 * The Outline tab is the screen-reader-complete path through the graph — a real
 * nested tree with the same labels and jump targets as the canvas.
 */

import { add, button, clear, el, fileLine, on } from '../dom.js';
import { severityGlyph } from '../markers.js';
import { appendTrustSections, confidenceChip } from './evidence.js';
import { renderIssuePanel } from './issuelist.js';
import { renderOutlineTree } from './outline.js';
import type { Issue, Loc, MLNode, RailGroupBy, RailTab, RelatedLoc } from '../types.js';
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
  /** The Issues rail's "Group by" control; persisted as ViewState.railGroupBy. */
  onGroupBy(mode: RailGroupBy): void;
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
  /** How the Issues tab groups its rows (RAIL-GROUP). */
  groupBy: RailGroupBy;
}

let railSeq = 0;

export class Rail {
  readonly root: HTMLElement;
  private tabs = new Map<RailTab, HTMLButtonElement>();
  private panels = new Map<RailTab, HTMLElement>();
  private cb: RailCallbacks;
  /**
   * Which rule / file groups the user has opened. Session-local by design: only
   * the MODE is persisted (§11.9's pattern), because a group set is derived from
   * a document that the next analysis may not contain.
   */
  private expanded = new Set<string>();
  private lastState: RailState | null = null;

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
    this.lastState = s;
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
    renderIssuePanel(this.panels.get('issues')!, {
      index: s.index,
      issues: s.issues,
      keep: s.keep,
      selectedIssueId: s.selectedIssueId,
      scope: s.scope,
      groupBy: s.groupBy,
      expanded: this.expanded,
    }, {
      onSelectIssue: (id) => this.cb.onSelectIssue(id),
      onOpen: (loc) => this.cb.onOpen(loc),
      onClearFilters: () => this.cb.onClearFilters(),
      onClearScope: () => this.cb.onClearScope(),
      onGroupBy: (mode) => this.cb.onGroupBy(mode),
      onToggleGroup: (key) => this.toggleGroup(key),
    });
  }

  /**
   * Expand or collapse one rule / file group. A group that is open BY DEFAULT
   * (fewer than three occurrences) is closed by remembering its negation, so the
   * two states are both reachable without persisting a whole open-set.
   */
  private toggleGroup(key: string): void {
    const negated = '!' + key;
    if (this.expanded.has(key)) {
      this.expanded.delete(key);
      this.expanded.add(negated);
    } else if (this.expanded.has(negated)) {
      this.expanded.delete(negated);
      this.expanded.add(key);
    } else {
      this.expanded.add(key);
    }
    if (this.lastState) this.renderIssues(this.lastState);
    // The panel's DOM was just replaced, so the header the user activated went
    // with it. Put the focus back on its replacement, exactly as `captureFocus`
    // does for a row -- a keyboard user must not be dumped on <body> for
    // opening a group.
    const back = this.root.querySelector('[data-group-toggle="' + key + '"]') as HTMLElement | null;
    if (back) {
      try {
        back.focus();
      } catch (_e) {
        /* a host may have detached the panel already */
      }
    }
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
    head.appendChild(confidenceChip(issue));
    add(box, el('p', 'mlv-insp__line', issue.message));
    add(box, el('p', 'mlv-insp__line', issue.why));
    add(box, el('div', 'mlv-insp__fix', issue.fixHint));
    // MLV-P6: the same two disclosures the rail row carries, so "why should I
    // believe this" is answerable from whichever surface the user is on.
    appendTrustSections(box, issue);
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
