/**
 * The side rail: Issues, Inspector and Outline.
 *
 * The Outline tab is the screen-reader-complete path through the graph — a real
 * nested tree with the same labels and jump targets as the canvas.
 */

import { add, button, clear, el, fileLine, on } from '../dom.js';
import { cellRef, locTitle } from '../notebook.js';
import { severityGlyph } from '../markers.js';
import { appendTrustSections, confidenceChip } from './evidence.js';
import { renderIssuePanel } from './issuelist.js';
import { renderOutlineTree } from './outline.js';
import { appendSuppressActions, stateChip } from './suppress.js';
import { appendFixSection, hasFix } from './fixes.js';
import { alternativeCount, isAlternatives, resolvedConfig } from '../config/resolved.js';
import type { DiffIndex } from '../diff/overlay.js';
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
  /** MLV-P10: copy `# mlview: ignore[CODE]` through the host's clipboard. */
  onCopyIgnore(code: string): void;
  /** MLV-P10: ask the host to turn this rule off for the workspace. */
  onDisableRule(code: string): void;
  /** H5: ask the host to apply `Issue.fix`, or copy it where it cannot. */
  onApplyFix(issueId: string): void;
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
  /** `keep` without the suppression and baseline tests (MLV-P10). */
  keepBase(issue: Issue): boolean;
  /**
   * Present only under a scope. `total` is PROJECT-LEVEL: the rail must always
   * be able to say how many findings live outside the current view, or a scope
   * reads as a clean bill of health (FEATURES 3.7).
   */
  scope: { shown: number; hidden: number; total: number; where: string } | null;
  /** How the Issues tab groups its rows (RAIL-GROUP). */
  groupBy: RailGroupBy;
  /** VIEW-08: the diff overlay, when one is loaded. */
  diff: DiffIndex | null;
  /** H5: true in a host that can actually make an edit. */
  canApplyFix: boolean;
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
    this.root.setAttribute('aria-labelledby', uid + '-rail-heading');
    // VIEW-12: the rail's own h2, so the three panel h3s hang off something
    // instead of preceding the document's only h2s.
    const railHeading = add(this.root, el('h2', 'mlv-sr', 'Findings and details'));
    railHeading.id = uid + '-rail-heading';

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
      keepBase: s.keepBase,
      selectedIssueId: s.selectedIssueId,
      scope: s.scope,
      groupBy: s.groupBy,
      expanded: this.expanded,
      diff: s.diff,
      canApplyFix: s.canApplyFix,
    }, {
      onSelectIssue: (id) => this.cb.onSelectIssue(id),
      onOpen: (loc) => this.cb.onOpen(loc),
      onClearFilters: () => this.cb.onClearFilters(),
      onClearScope: () => this.cb.onClearScope(),
      onGroupBy: (mode) => this.cb.onGroupBy(mode),
      onToggleGroup: (key) => this.toggleGroup(key),
      onCopyIgnore: (code) => this.cb.onCopyIgnore(code),
      onDisableRule: (code) => this.cb.onDisableRule(code),
      onApplyFix: (id) => this.cb.onApplyFix(id),
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
    add(panel, el('h3', 'mlv-sr', 'Inspector'));
    const node = s.selectedNode;
    if (!node || !s.index) {
      add(panel, el('div', 'mlv-empty-note', 'Select a node to inspect it.'));
      return;
    }
    // h4 under the panel's h3 (VIEW-12): this used to be an `h2` inside a
    // document whose first heading was an `h3`.
    add(panel, el('h4', 'mlv-insp__title', node.label || node.qualname));
    const meta = add(panel, el('div', 'mlv-insp__meta'));
    const stageChip = add(meta, el('span', 'mlv-chip mlv-chip--stage', node.stage));
    stageChip.setAttribute('data-stage', node.stage);
    add(meta, el('span', 'mlv-chip', node.kind));
    add(meta, el('span', 'mlv-chip', node.level));
    if (node.framework) add(meta, el('span', 'mlv-chip', node.framework));
    add(meta, el('span', 'mlv-chip', node.confidenceBucket));
    // VIEW-08: a resurrected ghost is a REMOVED node, not a missing step.
    if (node.ghost) add(meta, el('span', 'mlv-chip', 'missing step'));
    if (node.dynamic) add(meta, el('span', 'mlv-chip', 'dynamic scope'));
    if (node.diffStatus && node.diffStatus !== 'unchanged') {
      const chip = stateChip(
        meta,
        'mlv-chip--diff mlv-chip--diff-' + node.diffStatus,
        node.diffStatus,
        (node.diffChanged || []).length
          ? 'Changed against the earlier analysis: ' + (node.diffChanged || []).join(', ')
          : 'Against the earlier analysis',
      );
      chip.setAttribute('data-diff-chip', node.diffStatus);
    }

    add(panel, el('div', 'mlv-insp__fqn', node.fqn || node.qualname));

    const actions = add(panel, el('div', 'mlv-insp__actions'));
    const openBtn = button('mlv-btn mlv-btn--primary', 'Open ' + fileLine(node.loc));
    // NB. The button says the cell; its hover says the flat line the host is
    // actually sent, so the two never look like a contradiction.
    const nbCell = cellRef(node.loc);
    if (nbCell) {
      openBtn.setAttribute('data-cell', String(nbCell.cell));
      openBtn.title = locTitle(node.loc);
    }
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

    // ANA-10. The resolved value, and — where the analyzer could not choose —
    // ALL N alternatives, named. The card has room for three; this is where the
    // rest live, and where "not resolved" gets its reason.
    this.renderResolvedConfig(panel, node);

    // VIEW-08. A removed node has no attributes, ports or evidence to show, so
    // say what it IS rather than drawing four empty sections under it.
    if (node.diffStatus === 'removed') {
      add(
        panel,
        el(
          'div',
          'mlv-empty-note',
          'This node is in the EARLIER analysis and not in this one. It is drawn from the diff overlay alone, so it carries no findings, ports or evidence here.',
        ),
      );
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
        const box = this.inspectorIssue(issue, s);
        if (s.selectedIssueId === issue.id) box.classList.add('is-selected');
        panel.appendChild(box);
      }
    }
  }

  /**
   * ANA-10 — "where does this value come from", answered in the Inspector.
   *
   * The one-of-N case is a TABLE and not a sentence on purpose: the analyzer
   * resolved a `getattr` registry to several candidate symbols and genuinely
   * does not know which one runs, so the honest rendering names all of them and
   * says which is which. It used to draw two `unknown` boxes.
   */
  private renderResolvedConfig(panel: HTMLElement, node: MLNode): void {
    const info = resolvedConfig(node);
    if (!info) return;
    panel.appendChild(this.heading('Resolved value'));
    const table = add(panel, el('table', 'mlv-table mlv-table--config'));
    table.setAttribute('data-config-table', '1');
    const tbody = add(table, el('tbody'));
    if (isAlternatives(info)) {
      const head = add(tbody, el('tr'));
      add(head, el('th', '', 'one of'));
      add(head, el('td', '', String(alternativeCount(info))));
      for (const name of info.alternatives) {
        const tr = add(tbody, el('tr'));
        tr.setAttribute('data-config-alternative', name);
        add(tr, el('th', '', '·'));
        add(tr, el('td', 'mlv-mono', name));
      }
    } else if (info.unresolved) {
      const tr = add(tbody, el('tr'));
      add(tr, el('th', '', 'value'));
      add(tr, el('td', '', 'not resolved' + (info.reason ? ' — ' + info.reason : '')));
    } else {
      const tr = add(tbody, el('tr'));
      add(tr, el('th', '', 'value'));
      add(tr, el('td', 'mlv-mono', info.value));
    }
    if (info.from) {
      const tr = add(tbody, el('tr'));
      add(tr, el('th', '', isAlternatives(info) ? 'defined in' : 'read from'));
      add(tr, el('td', '', info.from));
    }
    if (isAlternatives(info)) {
      add(
        panel,
        el(
          'div',
          'mlv-empty-note mlv-insp__altnote',
          'MLView could not tell which of these runs — the name is chosen at run time — so it drew one node for all ' +
            alternativeCount(info) + ' rather than guessing.',
        ),
      );
    }
  }

  private inspectorIssue(issue: Issue, s: RailState): HTMLElement {
    const box = el('div', 'mlv-insp__issue');
    box.setAttribute('data-issue-id', issue.id);
    const head = add(box, el('div', 'mlv-insp__issue-head'));
    head.appendChild(severityGlyph(issue.severity, 14, ''));
    add(head, el('span', 'mlv-mono', issue.code));
    add(head, el('span', '', issue.title));
    head.appendChild(confidenceChip(issue));
    if (issue.suppressed) stateChip(head, 'mlv-chip--suppressed', 'suppressed');
    if (issue.baselined) stateChip(head, 'mlv-chip--baselined', 'baselined');
    // VIEW-08: how this finding stands against the earlier analysis.
    const diffStatus = s.diff ? s.diff.issueStatusOf(issue.id) : null;
    if (diffStatus === 'new' || diffStatus === 'persisting') {
      stateChip(
        head,
        'mlv-chip--diff mlv-chip--diff-' + diffStatus,
        diffStatus === 'new' ? 'new vs base' : 'still there',
        diffStatus === 'new'
          ? 'The earlier analysis did not report this finding'
          : 'Both analyses report this finding',
      ).setAttribute('data-diff-issue', diffStatus);
    }
    add(box, el('p', 'mlv-insp__line', issue.message));
    add(box, el('p', 'mlv-insp__line', issue.why));
    add(box, el('div', 'mlv-insp__fix', issue.fixHint));
    // H5. The Inspector is where a reader who has just read the evidence decides
    // what to do, so the computed edit — its title, its safety and the snippet —
    // goes here in full, above the two suppression actions.
    if (hasFix(issue)) {
      appendFixSection(box, issue, { onApplyFix: (id) => this.cb.onApplyFix(id) }, { canApply: s.canApplyFix });
    }
    // MLV-P6: the same two disclosures the rail row carries, so "why should I
    // believe this" is answerable from whichever surface the user is on.
    appendTrustSections(box, issue);
    // MLV-P10: and the same two actions, spelled out rather than icon-only —
    // the Inspector has the room, and this is where a reader who has just read
    // the evidence decides the finding is a false positive.
    const actions = add(box, el('div', 'mlv-insp__suppress'));
    appendSuppressActions(actions, issue.code, {
      onCopyIgnore: (code) => this.cb.onCopyIgnore(code),
      onDisableRule: (code) => this.cb.onDisableRule(code),
    });
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

  /** An Inspector subsection, one level under the node's own h4 (VIEW-12). */
  private heading(text: string): HTMLElement {
    const h = el('h5', 'mlv-rail__heading');
    h.textContent = text;
    return h;
  }

  private renderOutline(s: RailState): void {
    const panel = this.panels.get('outline')!;
    clear(panel);
    add(panel, el('h3', 'mlv-sr', 'Outline'));
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
