/**
 * The rail: About · Findings (n) · Selection · Outline (viewer M2).
 *
 * It is docked beside the canvas when the canvas keeps at least `RAIL_MIN_CANVAS_W` (app.ts), and
 * a bottom sheet under the canvas otherwise: a 32 px tab strip when collapsed, about half the
 * height when open, with a drag handle, a collapse chevron and Escape to collapse. The sheet is a
 * non-modal region with its own heading, never a dialog: the canvas above it keeps working.
 *
 * Only the visible tab is built. The Outline tab is the screen-reader-complete path through the
 * graph: a real nested tree with the same labels and jump targets as the canvas.
 */

import { add, clear, el, on } from '../dom.js';
import { uiIcon } from '../icons.js';
import { renderIssuePanel } from './issuelist.js';
import { renderOutlineTree } from './outline.js';
import type { RelationMode } from './outline.js';
import { renderSelectionPane } from './selection.js';
import type { WalkMark } from './selection.js';
import { renderAboutPane } from './about.js';
import type { Issue, Loc, MLEdge, MLNode, RailTab, RelatedLoc, StaleReason, WorkflowDocument } from '../types.js';
import type { ChangeKind, RevisionDiff } from '../revisiondiff.js';
import type { GraphIndex } from '../layout/model.js';

export interface RailCallbacks {
  onTab(tab: RailTab): void;
  onClearFilters(): void;
  /**
   * Viewer M1: a click selects; Enter and a double-click open (see `onOpenIssue`, `onOpenNode`).
   * `ev` is the pointer click, which arms the App's double-click opener (ui/doubleclick.ts).
   */
  onSelectIssue(id: string, ev?: MouseEvent): void;
  onOpenIssue(id: string, focusEditor: boolean): void;
  onSelectNode(id: string, ev?: MouseEvent): void;
  onOpenNode(id: string, focusEditor: boolean): void;
  onSelectEdge(id: string): void;
  /** Viewer M2: the Selection pane's links: a step, a connection, a finding. */
  onShowNode(id: string): void;
  onShowEdge(id: string): void;
  onShowIssue(id: string): void;
  onChallenge(): void;
  onRefine(): void;
  /** Open a cited range beside the panel; `focusEditor` (Alt) moves focus to the editor. */
  onOpen(loc: Loc | RelatedLoc, focusEditor?: boolean): void;
  /** The docked rail's grip: a new width. */
  onResize(width: number): void;
  /** The Outline's lane rows jump to a stage. */
  onSelectLane(laneId: string): void;
  /** Left/Right in the Outline collapses the same group the canvas draws. */
  onToggleCollapse(nodeId: string): void;
  /** Viewer M2: open About at the document-wide limitations, which are listed there once. */
  onShowLimitations(): void;
  /** Viewer M4: About's Changes links select the step, connection or finding. */
  onShowChange(kind: ChangeKind, id: string): void;
  /** Viewer M4: About's Changes section starts the walk on "Changed in this revision". */
  onReviewChanges(): void;
  /** Viewer M2, the bottom sheet: the chevron or a click on the handle opens or collapses it. */
  onSheetToggle(): void;
  /** Escape inside the open sheet: collapse it and give the focus back to the canvas. */
  onSheetCollapse(): void;
  /** The handle was dragged (or moved with the arrow keys) to this share of the body height. */
  onSheetResize(fraction: number): void;
  sheetFraction(): number;
  /**
   * Viewer M2 review (M2R-10): the largest share the open sheet can take, which the stylesheet's
   * canvas floor (`min(240px, 45%)`) caps below 0.75 on a short panel.
   */
  sheetFractionMax(): number;
  /** The height the sheet shares with the canvas, for the drag. */
  bodyHeight(): number;
}

export interface RailState {
  index: GraphIndex | null;
  tab: RailTab;
  issues: Issue[];
  selectedNode: MLNode | null;
  selectedEdge: MLEdge | null;
  selectedIssueId: string | null;
  selectedIssue: Issue | null;
  /** The canvas's collapsed groups — the Outline mirrors them (MLV-R2-W08). */
  collapsed: Set<string>;
  keep(issue: Issue): boolean;
  /** Viewer M1: why a cited file no longer matches the published revision, if it does not. */
  staleReason?(file: string): StaleReason | undefined;
  /** Viewer M2: the displayed revision, for About and for the quotes' freshness. */
  document: WorkflowDocument | null;
  /** Viewer M2: the Selection pane's columns (two in a sheet at least 620 px wide). */
  columns: 1 | 2;
  /** Viewer M3: the review walk's quote mark for the Selection pane, while it shows the walk's claim. */
  walk?: WalkMark | null;
  /**
   * Viewer M4 (step 16): what changed since the revision this panel showed before (About lists it;
   * the Selection pane, the Outline and the Findings list tag what was added or changed), or null.
   */
  changes?: RevisionDiff | null;
  /** Viewer M4: the revision this panel showed before, when the displayed one does not follow it. */
  replaced?: string | null;
}

/** The tabs, in order. The Selection tab keeps the id `inspector` (saved view states use it). */
const TABS: { id: RailTab; label: string; heading: string }[] = [
  { id: 'about', label: 'About', heading: 'About this revision' },
  { id: 'issues', label: 'Findings', heading: 'Findings' },
  { id: 'inspector', label: 'Selection', heading: 'Selection' },
  { id: 'outline', label: 'Outline', heading: 'Outline' },
];

/** The handle's arrow keys move the open sheet by this share of the height. */
const SHEET_STEP = 0.05;
/** A drag that ends below this share of the height collapses the sheet. */
const SHEET_COLLAPSE_BELOW = 0.15;

let railSeq = 0;

export class Rail {
  readonly root: HTMLElement;
  private tabs = new Map<RailTab, HTMLButtonElement>();
  private counts = new Map<RailTab, HTMLElement>();
  private panels = new Map<RailTab, HTMLElement>();
  private cb: RailCallbacks;
  private heading: HTMLElement;
  private grip: HTMLElement;
  private chevron: HTMLButtonElement;
  private relationMode: RelationMode = 'outgoing';
  private relationNodeId: string | null = null;
  private current: RailTab = 'about';
  private mode: 'docked' | 'sheet' = 'docked';
  private open = true;
  /**
   * The claim the Selection pane was last built for (kind, id and revision). A new claim starts the
   * pane at its top, so its title shows: the pane is one scroller kept across claims, and it used to
   * keep the offset of the claim before (M3 live check, W1).
   */
  private selectionKey = '';

  constructor(cb: RailCallbacks) {
    this.cb = cb;
    const uid = 'mlv' + ++railSeq;
    this.root = el('aside', 'mlv-rail');
    this.root.id = uid + '-rail';
    this.root.setAttribute('data-mode', 'docked');
    this.root.setAttribute('aria-labelledby', uid + '-rail-heading');
    // VIEW-12: the rail's own h2, so the panel h3s hang off something. Viewer M2: it names where
    // the panel is, so a screen reader can tell the side panel from the bottom one.
    this.heading = add(this.root, el('h2', 'mlv-sr', 'Side panel'));
    this.heading.id = uid + '-rail-heading';

    this.grip = add(this.root, el('div', 'mlv-rail__grip'));
    this.grip.setAttribute('role', 'separator');
    this.grip.setAttribute('aria-orientation', 'vertical');
    this.grip.setAttribute('aria-label', 'Resize side panel');
    this.grip.tabIndex = 0;
    this.wireGrip(this.grip);

    const bar = add(this.root, el('div', 'mlv-rail__bar'));
    const strip = add(bar, el('div', 'mlv-rail__tabs'));
    strip.setAttribute('role', 'tablist');
    strip.setAttribute('aria-label', 'Panel');
    for (let tabIndex = 0; tabIndex < TABS.length; tabIndex++) {
      const d = TABS[tabIndex];
      const b = el('button', 'mlv-rail__tab') as HTMLButtonElement;
      add(b, el('span', 'mlv-rail__tablabel', d.label));
      if (d.id === 'issues') {
        // "Findings (3)": the count is the tab's own unit; the title spells it out.
        const count = add(b, el('span', 'mlv-rail__tabcount'));
        this.counts.set(d.id, count);
      }
      b.type = 'button';
      b.id = uid + '-tab-' + d.id;
      b.setAttribute('role', 'tab');
      b.setAttribute('data-tab', d.id);
      b.setAttribute('aria-controls', uid + '-panel-' + d.id);
      b.setAttribute('aria-selected', 'false');
      on(b, 'click', () => cb.onTab(d.id));
      on(b, 'keydown', (ev: KeyboardEvent) => {
        let nextIndex: number;
        if (ev.key === 'ArrowRight') nextIndex = (tabIndex + 1) % TABS.length;
        else if (ev.key === 'ArrowLeft') nextIndex = (tabIndex + TABS.length - 1) % TABS.length;
        else if (ev.key === 'Home') nextIndex = 0;
        else if (ev.key === 'End') nextIndex = TABS.length - 1;
        else return;
        ev.preventDefault();
        const next = TABS[nextIndex].id;
        cb.onTab(next);
        this.tabs.get(next)?.focus();
      });
      strip.appendChild(b);
      this.tabs.set(d.id, b);

      const panel = el('div', 'mlv-rail__panel');
      panel.id = uid + '-panel-' + d.id;
      panel.setAttribute('role', 'tabpanel');
      panel.setAttribute('aria-labelledby', b.id);
      panel.setAttribute('data-tab', d.id);
      panel.tabIndex = 0;
      panel.hidden = true;
      this.root.appendChild(panel);
      this.panels.set(d.id, panel);
    }

    // The sheet's collapse chevron, at the end of its tab strip. Hidden while docked.
    this.chevron = add(bar, el('button', 'mlv-btn mlv-btn--icon mlv-rail__chevron')) as HTMLButtonElement;
    this.chevron.type = 'button';
    this.chevron.setAttribute('aria-controls', this.root.id);
    this.chevron.appendChild(uiIcon('chevron', 14));
    this.chevron.hidden = true;
    on(this.chevron, 'click', () => cb.onSheetToggle());

    // Escape inside the open sheet collapses it (the canvas gets the focus back). A control that
    // answers Escape itself (a search field, a tree) marks the event handled first.
    on(this.root, 'keydown', (ev: KeyboardEvent) => {
      if (ev.key !== 'Escape' || ev.defaultPrevented || this.mode !== 'sheet' || !this.open) return;
      ev.preventDefault();
      ev.stopPropagation();
      cb.onSheetCollapse();
    });
    this.applyShape();
  }

  /** Docked beside the canvas, or a bottom sheet under it, with the open sheet's share of the height. */
  setMode(mode: 'docked' | 'sheet', fraction: number): void {
    this.mode = mode;
    this.root.setAttribute('data-mode', mode);
    const body = this.root.parentElement;
    if (body) body.setAttribute('data-rail', mode);
    // The docked width is an inline style (App.setRailWidth); the sheet spans the panel.
    if (mode === 'sheet') this.root.style.width = '';
    this.setSheetFraction(fraction);
    this.applyShape();
  }

  /** Docked: shown or hidden. Sheet: open, or collapsed to its tab strip. */
  setOpen(open: boolean): void {
    this.open = open;
    this.applyShape();
  }

  /**
   * The open sheet's height, as a share of the height it shares with the canvas. The handle reports
   * the height the stylesheet draws: no more than the canvas floor leaves (viewer M2 review, M2R-10).
   */
  setSheetFraction(fraction: number): void {
    this.root.style.setProperty('--mlv-sheet-fraction', String(fraction));
    if (this.mode === 'sheet') {
      const max = this.cb.sheetFractionMax();
      const percent = Math.round(Math.min(fraction, max) * 100);
      this.grip.setAttribute('aria-valuemax', String(Math.round(max * 100)));
      this.grip.setAttribute('aria-valuenow', String(percent));
      this.grip.setAttribute('aria-valuetext', this.open ? percent + ' percent of the height' : 'collapsed');
    }
  }

  /** Move the keyboard focus to a tab (`t`, and `App.showRailTab` in the sheet). */
  focusTab(tab: RailTab): void {
    const button = this.tabs.get(tab);
    if (!button) return;
    try {
      button.focus();
    } catch (_e) {
      /* a host may have detached the rail already */
    }
  }

  /** The panel of the tab on show. */
  activePanel(): HTMLElement {
    return this.panels.get(this.current)!;
  }

  /**
   * About's coverage limitations, opened and scrolled into view; the element to focus (their
   * summary), or the About panel when the revision lists none.
   */
  revealLimitations(): HTMLElement {
    const panel = this.panels.get('about')!;
    const details = panel.querySelector<HTMLDetailsElement>('.mlv-about__limitations');
    if (!details) return panel;
    details.open = true;
    const summary = details.querySelector<HTMLElement>('summary') || details;
    if (typeof details.scrollIntoView === 'function') {
      try {
        details.scrollIntoView({ block: 'nearest' });
      } catch (_e) {
        /* an older engine without the options argument */
      }
    }
    return summary;
  }

  /** Shown, hidden, open or collapsed: which parts of the rail are on screen. */
  private applyShape(): void {
    const sheet = this.mode === 'sheet';
    this.root.hidden = !sheet && !this.open;
    if (sheet) this.root.setAttribute('data-expanded', this.open ? 'true' : 'false');
    else this.root.removeAttribute('data-expanded');
    this.heading.textContent = sheet ? 'Bottom panel' : 'Side panel';
    // The grip resizes the docked rail's width, and the sheet's height (it is the sheet's handle).
    this.grip.setAttribute('aria-orientation', sheet ? 'horizontal' : 'vertical');
    this.grip.setAttribute('aria-label', sheet ? 'Resize the bottom panel' : 'Resize side panel');
    if (sheet) {
      this.grip.setAttribute('aria-valuemin', '25');
      this.setSheetFraction(this.cb.sheetFraction());
    } else {
      for (const name of ['aria-valuemin', 'aria-valuemax', 'aria-valuenow', 'aria-valuetext']) this.grip.removeAttribute(name);
    }
    this.chevron.hidden = !sheet;
    this.chevron.setAttribute('aria-expanded', this.open ? 'true' : 'false');
    const label = this.open ? 'Collapse the bottom panel (Escape)' : 'Expand the bottom panel';
    this.chevron.setAttribute('aria-label', label);
    this.chevron.title = label;
    for (const [id, panel] of this.panels) panel.hidden = id !== this.current || (sheet && !this.open);
  }

  private wireGrip(grip: HTMLElement): void {
    // Docked: drag left or right to set the width. Sheet: drag up or down to set the height; a
    // press without a drag opens or collapses it.
    let startX = 0;
    let startY = 0;
    let startW = 0;
    let startFraction = 0;
    let bodyH = 0;
    let dragged = false;
    let sheetDrag = false;
    let wasOpen = true;
    let last = 0;
    /** The open height before the drag, which a drag that ends collapsed keeps for next time. */
    let restore = 0;
    const move = (ev: PointerEvent) => {
      if (!sheetDrag) {
        this.cb.onResize(startW + (startX - ev.clientX));
        return;
      }
      const dy = startY - ev.clientY;
      if (!dragged && Math.abs(dy) < 4) return;
      if (!dragged) {
        dragged = true;
        // Dragging a collapsed sheet's handle up opens it at the height it is dragged to.
        if (!wasOpen && dy > 0) this.cb.onSheetToggle();
      }
      last = startFraction + dy / bodyH;
      if (this.open) this.cb.onSheetResize(last);
    };
    const up = () => {
      document.removeEventListener('pointermove', move as EventListener);
      document.removeEventListener('pointerup', up);
      if (!sheetDrag) return;
      if (!dragged) this.cb.onSheetToggle();
      else if (this.open && last < SHEET_COLLAPSE_BELOW) {
        // Viewer M2 review (M2R-10): collapsed by dragging down, the sheet reopens at the height it
        // had before the drag, not at the 25% floor the drag was clamped to on its way down.
        this.cb.onSheetToggle();
        this.cb.onSheetResize(restore);
      }
    };
    on(grip, 'pointerdown', (ev: PointerEvent) => {
      sheetDrag = this.mode === 'sheet';
      startX = ev.clientX;
      startY = ev.clientY;
      startW = this.root.getBoundingClientRect().width || 360;
      bodyH = Math.max(1, this.cb.bodyHeight());
      wasOpen = this.open;
      restore = this.cb.sheetFraction();
      startFraction = wasOpen ? Math.min(restore, this.cb.sheetFractionMax()) : 32 / bodyH;
      last = startFraction;
      dragged = false;
      document.addEventListener('pointermove', move as EventListener);
      document.addEventListener('pointerup', up);
      ev.preventDefault();
    });
    on(grip, 'keydown', (ev: KeyboardEvent) => {
      if (this.mode === 'sheet') {
        if (ev.key === 'Enter' || ev.key === ' ') this.cb.onSheetToggle();
        else if (ev.key === 'ArrowUp' || ev.key === 'ArrowDown') {
          const up = ev.key === 'ArrowUp';
          if (!this.open) {
            if (up) this.cb.onSheetToggle();
          } else {
            this.cb.onSheetResize(this.cb.sheetFraction() + (up ? SHEET_STEP : -SHEET_STEP));
          }
        } else return;
        ev.preventDefault();
        return;
      }
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
    this.current = s.tab;
    for (const [id, tab] of this.tabs) {
      const active = id === s.tab;
      tab.setAttribute('aria-selected', active ? 'true' : 'false');
      tab.tabIndex = active ? 0 : -1;
    }
    const count = this.counts.get('issues');
    if (count) {
      const n = s.issues.length;
      count.textContent = s.index ? ' (' + n + ')' : '';
      const tab = this.tabs.get('issues')!;
      tab.title = s.index ? n + (n === 1 ? ' finding' : ' findings') + ' in this revision' : '';
      if (s.index) tab.setAttribute('aria-label', 'Findings, ' + n + (n === 1 ? ' finding' : ' findings'));
      else tab.removeAttribute('aria-label');
    }
    this.applyShape();
    // Only the tab on show is built; the others are emptied, so nothing hidden goes stale.
    for (const [id, panel] of this.panels) if (id !== s.tab) clear(panel);
    if (s.tab === 'about') this.renderAbout(s);
    else if (s.tab === 'issues') this.renderIssues(s);
    else if (s.tab === 'outline') this.renderOutline(s);
    else this.renderSelection(s);
    restoreFocus();
  }

  /**
   * Remember which row owns the focus, by id, and hand back a function that
   * finds that row again in the freshly built DOM. Focus inside a panel that has no such row (a
   * link in the Selection pane that selected something else) lands on the panel itself, so it
   * never drops to the page.
   */
  private captureFocus(): () => void {
    const active =
      typeof document !== 'undefined' ? (document.activeElement as HTMLElement | null) : null;
    if (!active || typeof active.closest !== 'function' || !this.root.contains(active)) {
      return () => undefined;
    }
    const inPanel = active.closest('[role="tabpanel"]') as HTMLElement | null;
    const fallback = () => {
      if (!inPanel || active.isConnected) return;
      const doc = this.root.ownerDocument;
      if (doc.activeElement && doc.activeElement !== doc.body) return;
      const panel = this.panels.get(this.current);
      if (!panel || panel.hidden) return;
      try {
        panel.focus();
      } catch (_e) {
        /* a host may have detached the panel already */
      }
    };
    const owner = active.closest('[data-issue-id][role="option"], [data-outline-id], [data-outline-lane], [data-relation-id]');
    if (!owner) return fallback;
    const attr = owner.hasAttribute('data-issue-id')
      ? 'data-issue-id'
      : owner.hasAttribute('data-outline-id')
        ? 'data-outline-id'
        : owner.hasAttribute('data-outline-lane')
          ? 'data-outline-lane'
          : 'data-relation-id';
    const value = owner.getAttribute(attr) || '';
    return () => {
      const next = this.root.querySelector('[' + attr + '="' + value + '"]') as HTMLElement | null;
      if (!next) {
        fallback();
        return;
      }
      const panel = next.closest('[role="tabpanel"]') as HTMLElement | null;
      if (panel?.hidden) return;
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

  private renderAbout(s: RailState): void {
    const panel = this.panels.get('about')!;
    clear(panel);
    add(panel, el('h3', 'mlv-sr', TABS[0].heading));
    renderAboutPane(panel, {
      document: s.index ? s.document : null,
      staleReason: s.staleReason,
      changes: s.changes || null,
      replaced: s.replaced || null,
      index: s.index,
      onShowChange: (kind, id) => this.cb.onShowChange(kind, id),
      onReviewChanges: () => this.cb.onReviewChanges(),
    });
  }

  private renderIssues(s: RailState): void {
    renderIssuePanel(this.panels.get('issues')!, {
      index: s.index,
      issues: s.issues,
      keep: s.keep,
      selectedIssueId: s.selectedIssueId,
      staleReason: s.staleReason,
      changes: s.changes || null,
    }, {
      onSelectIssue: (id, ev) => this.cb.onSelectIssue(id, ev),
      onOpenIssue: (id, focusEditor) => this.cb.onOpenIssue(id, focusEditor),
      onOpen: (loc, focusEditor) => this.cb.onOpen(loc, focusEditor),
      onClearFilters: () => this.cb.onClearFilters(),
    });
  }

  private renderSelection(s: RailState): void {
    const panel = this.panels.get('inspector')!;
    clear(panel);
    add(panel, el('h3', 'mlv-sr', 'Selection'));
    if (!s.index) {
      add(panel, el('div', 'mlv-empty-note', 'No workflow loaded yet.'));
      return;
    }
    renderSelectionPane(panel, {
      index: s.index,
      keep: s.keep,
      node: s.selectedNode,
      edge: s.selectedEdge,
      issue: s.selectedIssue,
      columns: s.columns,
      document: s.document,
      staleReason: s.staleReason,
      walk: s.walk || null,
      changes: s.changes || null,
    }, {
      onOpen: (loc, focusEditor) => this.cb.onOpen(loc, focusEditor),
      onShowNode: (id) => this.cb.onShowNode(id),
      onShowEdge: (id) => this.cb.onShowEdge(id),
      onShowIssue: (id) => this.cb.onShowIssue(id),
      onChallenge: () => this.cb.onChallenge(),
      onRefine: () => this.cb.onRefine(),
      onShowLimitations: () => this.cb.onShowLimitations(),
    });
    // The same claim built again (a host answer, a freshness change, a resize) keeps the reader's
    // place; another claim starts at the top. The walk then brings its quote into view.
    const claim = s.selectedIssue ? 'issue:' + s.selectedIssue.id : s.selectedEdge ? 'edge:' + s.selectedEdge.id : s.selectedNode ? 'node:' + s.selectedNode.id : '';
    const key = claim + '@' + (s.document && s.document.revision ? s.document.revision.id : '');
    if (key !== this.selectionKey) {
      this.selectionKey = key;
      panel.scrollTop = 0;
    }
  }

  private renderOutline(s: RailState): void {
    const panel = this.panels.get('outline')!;
    clear(panel);
    add(panel, el('h3', 'mlv-sr', 'Outline'));
    const index = s.index;
    if (!index) {
      add(panel, el('div', 'mlv-empty-note', 'No workflow loaded yet.'));
      return;
    }
    if (s.selectedNode) this.relationNodeId = s.selectedNode.id;
    const relationNodeId = this.relationNodeId && index.nodeById.has(this.relationNodeId)
      ? this.relationNodeId
      : null;
    renderOutlineTree(
      panel,
      {
        index,
        keep: s.keep,
        selectedNodeId: s.selectedNode ? s.selectedNode.id : relationNodeId,
        collapsed: s.collapsed,
        relationMode: this.relationMode,
        changes: s.changes || null,
      },
      {
        onSelectNode: (id, ev) => this.cb.onSelectNode(id, ev),
        onOpenNode: (id, focusEditor) => this.cb.onOpenNode(id, focusEditor),
        onSelectEdge: (id) => this.cb.onSelectEdge(id),
        onRelationMode: (mode) => { this.relationMode = mode; },
        onSelectLane: (laneId) => this.cb.onSelectLane(laneId),
        onToggleCollapse: (id) => this.cb.onToggleCollapse(id),
      },
    );
  }
}
