/**
 * The side rail: Issues, Inspector and Outline.
 *
 * The Outline tab is the screen-reader-complete path through the graph — a real
 * nested tree with the same labels and jump targets as the canvas.
 */

import { add, button, clear, el, fileLine, on } from '../dom.js';
import { locTitle } from '../notebook.js';
import { severityGlyph } from '../markers.js';
import { basisChip } from './evidence.js';
import { issueStaleReasons, renderIssuePanel, staleChipText, suggestionBlock, wireOpenControl } from './issuelist.js';
import { allElsewhere, staleQuotes, STALE_TEXT } from '../freshness.js';
import { uiIcon } from '../icons.js';
import { renderOutlineTree } from './outline.js';
import type { RelationMode } from './outline.js';
import { edgeKindText } from '../render/edges.js';
import type { Issue, Loc, MLEdge, MLNode, RailTab, RelatedLoc, StaleReason } from '../types.js';
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
  onChallenge(): void;
  /** Open a cited range beside the panel; `focusEditor` (Alt) moves focus to the editor. */
  onOpen(loc: Loc | RelatedLoc, focusEditor?: boolean): void;
  onResize(width: number): void;
  onToggleRail(): void;
  /** The Outline's lane rows jump to a stage. */
  onSelectLane(laneId: string): void;
  /** Left/Right in the Outline collapses the same group the canvas draws. */
  onToggleCollapse(nodeId: string): void;
  /** "Show all" — clears the scope. Filters are a separate control. */
  onClearScope(): void;
  /** Inspector: scope the diagram to the selected unit or step. */
  onScopeToNode(nodeId: string): void;
  /** Viewer M1: open the header's Details at the document-wide limitations, which are listed there once. */
  onShowLimitations(): void;
}

/**
 * Viewer M1: what a matching quote does and does not show (automation-bias research: readers
 * take a citation as support unless told otherwise). Shown once per Inspector, under the
 * evidence heading.
 */
const EVIDENCE_CAPTION =
  'A matching quote shows these lines exist unchanged since publishing. Whether they support the claim is for you to judge.';

/**
 * Viewer M1: a short sentence for the two bases that need one. `observed` needs no explanation.
 * Worded like the legend's basis rows (ui/legend.ts).
 */
function basisNote(basis: string | undefined, noun: 'step' | 'connection'): string {
  if (basis === 'inferred') return 'Reasoned from the cited code and stated assumptions; the quotes do not show all of it directly.';
  if (basis === 'unresolved') return 'The evidence does not settle this claim. It does not mean the ' + noun + ' is missing.';
  return '';
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
  /**
   * Present only under a scope. `total` is PROJECT-LEVEL: the rail must always
   * be able to say how many findings live outside the current view, or a scope
   * reads as a clean bill of health (FEATURES 3.7).
   */
  scope: { shown: number; hidden: number; total: number; where: string } | null;
  /** Viewer M1: why a cited file no longer matches the published revision, if it does not. */
  staleReason?(file: string): StaleReason | undefined;
}

let railSeq = 0;

export class Rail {
  readonly root: HTMLElement;
  private tabs = new Map<RailTab, HTMLButtonElement>();
  private panels = new Map<RailTab, HTMLElement>();
  private cb: RailCallbacks;
  private relationMode: RelationMode = 'outgoing';
  private relationNodeId: string | null = null;

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
    for (let tabIndex = 0; tabIndex < defs.length; tabIndex++) {
      const d = defs[tabIndex];
      const b = el('button', 'mlv-rail__tab', d.label) as HTMLButtonElement;
      b.type = 'button';
      b.id = uid + '-tab-' + d.id;
      b.setAttribute('role', 'tab');
      b.setAttribute('aria-controls', uid + '-panel-' + d.id);
      b.setAttribute('aria-selected', 'false');
      on(b, 'click', () => cb.onTab(d.id));
      on(b, 'keydown', (ev: KeyboardEvent) => {
        let nextIndex: number;
        if (ev.key === 'ArrowRight') nextIndex = (tabIndex + 1) % defs.length;
        else if (ev.key === 'ArrowLeft') nextIndex = (tabIndex + defs.length - 1) % defs.length;
        else if (ev.key === 'Home') nextIndex = 0;
        else if (ev.key === 'End') nextIndex = defs.length - 1;
        else return;
        ev.preventDefault();
        const next = defs[nextIndex].id;
        cb.onTab(next);
        this.tabs.get(next)?.focus();
      });
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
    const owner = active.closest('[data-issue-id][role="option"], [data-outline-id], [data-outline-lane], [data-relation-id]');
    if (!owner) return () => undefined;
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
      if (!next) return;
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

  private renderIssues(s: RailState): void {
    renderIssuePanel(this.panels.get('issues')!, {
      index: s.index,
      issues: s.issues,
      keep: s.keep,
      selectedIssueId: s.selectedIssueId,
      scope: s.scope,
      staleReason: s.staleReason,
    }, {
      onSelectIssue: (id, ev) => this.cb.onSelectIssue(id, ev),
      onOpenIssue: (id, focusEditor) => this.cb.onOpenIssue(id, focusEditor),
      onOpen: (loc, focusEditor) => this.cb.onOpen(loc, focusEditor),
      onClearFilters: () => this.cb.onClearFilters(),
      onClearScope: () => this.cb.onClearScope(),
    });
  }

  private renderInspector(s: RailState): void {
    const panel = this.panels.get('inspector')!;
    clear(panel);
    add(panel, el('h3', 'mlv-sr', 'Inspector'));
    const node = s.selectedNode;
    if (s.selectedEdge && s.index) {
      this.renderEdgeInspector(panel, s.selectedEdge, s.index, s);
      return;
    }
    if (s.selectedIssue && s.index) {
      add(panel, el('h4', 'mlv-insp__title', s.selectedIssue.title));
      panel.appendChild(this.inspectorIssue(s.selectedIssue, s, true));
      this.appendChallenge(panel);
      this.renderWorkflowLimitations(panel, s.index);
      return;
    }
    if (!node || !s.index) {
      add(panel, el('div', 'mlv-empty-note', 'Select a node to inspect it.'));
      return;
    }
    // h4 under the panel's h3 (VIEW-12): this used to be an `h2` inside a
    // document whose first heading was an `h3`.
    const title = node.label || node.qualname;
    add(panel, el('h4', 'mlv-insp__title', title));
    const meta = add(panel, el('div', 'mlv-insp__meta'));
    // Viewer M1: the phase's authored label, never its id (the id stays on `data-stage`).
    const phase = node.phaseLabel || stageLabel(s.index, node.stage);
    const stageChip = add(meta, el('span', 'mlv-chip mlv-chip--stage', phase));
    stageChip.setAttribute('data-stage', node.stage);
    stageChip.title = 'Phase: ' + phase;
    // VIEWUI-14: an absent kind reads as `unknown` and the level is the
    // adapter's `unit`/`op`, neither of which the author wrote.
    if (node.kind && node.kind !== 'unknown') add(meta, el('span', 'mlv-chip', node.kind));
    // Viewer M1: the basis once.
    const basisChip = add(meta, el('span', 'mlv-chip mlv-insp__basis-chip', node.basis ? 'basis · ' + node.basis : ''));
    if (node.basis) basisChip.setAttribute('data-basis', node.basis);
    this.appendBasisNote(panel, node.basis, 'step');
    // Viewer M1: the claim itself, in full, before anything else. It was only in the hover card.
    if (node.detail) add(panel, el('p', 'mlv-insp__detail', node.detail));

    const actions = add(panel, el('div', 'mlv-insp__actions'));
    // "unit" for a top-level step, "step" for a child: the word has to match
    // what the user is looking at, or the button reads as a different feature.
    const scopeWord = node.level === 'unit' ? 'unit' : 'step';
    const scopeBtn = button('mlv-btn mlv-btn--scope-node', 'Scope to this ' + scopeWord);
    scopeBtn.setAttribute('data-scope-node', node.id);
    on(scopeBtn, 'click', () => this.cb.onScopeToNode(node.id));
    actions.appendChild(scopeBtn);
    this.appendChallenge(actions);

    // Viewer M1: claim, then the findings on this step (with what to change), then the evidence.
    this.appendIssues(panel, s.index.issuesOf(node.id, s.keep), s);
    this.renderEvidenceLocations(panel, node.evidenceLocs || [], s);
    this.renderWorkflowLimitations(panel, s.index);
  }

  /** Viewer M1: one sentence under the meta row for an inferred or unresolved claim; nothing for observed. */
  private appendBasisNote(panel: HTMLElement, basis: string | undefined, noun: 'step' | 'connection'): void {
    const note = basisNote(basis, noun);
    if (!note) return;
    const p = add(panel, el('p', 'mlv-insp__basis', note));
    p.setAttribute('data-basis', basis || '');
  }

  private appendIssues(panel: HTMLElement, issues: Issue[], s: RailState): void {
    if (!issues.length) return;
    panel.appendChild(this.heading('Findings'));
    for (const issue of issues) {
      const box = this.inspectorIssue(issue, s);
      if (s.selectedIssueId === issue.id) box.classList.add('is-selected');
      panel.appendChild(box);
    }
  }

  private renderEdgeInspector(panel: HTMLElement, edge: MLEdge, index: GraphIndex, s: RailState): void {
    // The label as authored; the basis chip below says the basis once.
    add(panel, el('h4', 'mlv-insp__title', edge.label || edgeKindText(edge.kind) || 'Connection'));
    const source = index.nodeById.get(edge.source);
    const target = index.nodeById.get(edge.target);
    const meta = add(panel, el('div', 'mlv-insp__meta'));
    // Issue 9: the authored kind word, never the adapter's `unknown`; a
    // normalised synonym names what the author wrote as well.
    const kindChip = add(meta, el('span', 'mlv-chip mlv-insp__edgekind', edgeKindText(edge.kind) + (edge.authoredKind ? ' · authored as ' + edge.authoredKind : '')));
    kindChip.setAttribute('data-edge-kind', edge.kind);
    if (edge.basis) {
      const basisChip = add(meta, el('span', 'mlv-chip mlv-chip--basis mlv-insp__basis-chip', 'basis · ' + edge.basis));
      basisChip.setAttribute('data-basis', edge.basis);
    }
    // Where it runs from and to: the one thing the title does not say.
    add(panel, el('div', 'mlv-insp__fqn mlv-insp__ends', (source?.label || edge.source) + ' → ' + (target?.label || edge.target)));
    this.appendBasisNote(panel, edge.basis, 'connection');
    const actions = add(panel, el('div', 'mlv-insp__actions'));
    this.appendChallenge(actions);
    // The connection's hover card lists these too; this is the keyboard's and
    // the screen reader's way to them, as the Findings block is for a step.
    this.appendIssues(panel, index.issuesOfEdge(edge.id, s.keep), s);
    this.renderEvidenceLocations(panel, edge.evidenceLocs || [], s);
    this.renderWorkflowLimitations(panel, index);
  }

  /**
   * Viewer M1: the document-wide limitations are listed once, in the header's Details. Every
   * Inspector repeated all of them (7 of 7 on a connection); now it says how many apply and
   * links to them.
   */
  private renderWorkflowLimitations(panel: HTMLElement, index: GraphIndex): void {
    const count = (index.graph.diagnostics || []).filter((item) => item.kind === 'workflow_limitation').length;
    if (!count) return;
    const line = add(panel, el('p', 'mlv-insp__limits'));
    line.setAttribute('data-limitations', String(count));
    const words = count === 1 ? '1 document-wide limitation applies.' : count + ' document-wide limitations apply.';
    add(line, el('span', '', words + ' '));
    const show = button('mlv-link mlv-link--inline mlv-insp__limits-show', 'Show', 'Show the coverage limitations in the header Details');
    show.setAttribute('aria-label', count === 1 ? 'Show the document-wide limitation' : 'Show the ' + count + ' document-wide limitations');
    on(show, 'click', () => this.cb.onShowLimitations());
    line.appendChild(show);
  }

  private renderEvidenceLocations(panel: HTMLElement, locations: Loc[], s: RailState): void {
    if (!locations.length) {
      add(panel, el('div', 'mlv-empty-note mlv-insp__no-evidence', 'No source evidence was authored for this item. Its basis and coverage limitations describe what remains uncertain.'));
      return;
    }
    panel.appendChild(this.heading('Source evidence'));
    this.appendEvidenceCaption(panel);
    const reasonOf = (loc: Loc): StaleReason | undefined => (s.staleReason && loc.file ? s.staleReason(loc.file) : undefined);
    const quotes = staleQuotes(locations, (file) => !!(s.staleReason && s.staleReason(file)));
    if (quotes.stale) {
      // Viewer M1: what the marks below mean, in words, before the list. Nothing in MLView checks
      // a claim, so the note says what the reader can do, not that a check was skipped (COPY-2).
      const reasons = locations.map(reasonOf).filter((reason): reason is StaleReason => !!reason);
      const count = quotes.stale + ' of ' + quotes.total + (quotes.total === 1 ? ' quote cites ' : ' quotes cite ');
      const note = add(panel, el('p', 'mlv-insp__stale-note'));
      note.appendChild(uiIcon('warning', 12));
      add(note, el('span', '', allElsewhere(reasons)
        ? count + 'a file that is not under the workspace root but is unchanged in another folder; those jumps are blocked. The notice above says which folder to add.'
        : count + 'a file that changed or went missing since publishing; those jumps are blocked. To compare the claim with the code as it is now, ask the assistant for a fresh revision.'));
    }
    const nav = add(panel, el('div', 'mlv-insp__evidence-nav'));
    const previous = button('mlv-btn', 'Previous evidence');
    const next = button('mlv-btn', 'Next evidence');
    let active = 0;
    const update = () => {
      previous.disabled = active === 0;
      next.disabled = active === locations.length - 1;
      previous.title = previous.disabled ? 'This is the first evidence item' : 'Open the previous evidence item';
      next.title = next.disabled ? 'This is the last evidence item' : 'Open the next evidence item';
    };
    on(previous, 'click', () => { if (active > 0) this.cb.onOpen(locations[--active]); update(); });
    on(next, 'click', () => { if (active < locations.length - 1) this.cb.onOpen(locations[++active]); update(); });
    nav.append(previous, next);
    update();
    const list = add(panel, el('ul', 'mlv-insp__related mlv-insp__source-evidence'));
    for (const loc of locations) {
      const li = add(list, el('li'));
      const reason = reasonOf(loc);
      const openBtn = button('mlv-link', 'Open ' + fileLine(loc));
      openBtn.setAttribute('data-evidence-id', loc.evidenceId || '');
      if (loc.cell !== undefined && locTitle(loc)) {
        // VIEWUI-8: an authored notebook citation names its zero-based cell.
        openBtn.title = locTitle(loc);
      }
      if (reason) {
        li.classList.add('is-stale');
        li.setAttribute('data-stale', reason);
      }
      wireOpenControl(openBtn, loc, (target, focusEditor) => {
        active = locations.indexOf(loc);
        update();
        this.cb.onOpen(target, focusEditor);
      }, reason);
      li.appendChild(openBtn);
      if (reason) li.appendChild(staleBadge(reason));
      if (loc.snippet) add(li, el('pre', 'mlv-banner__detail', loc.snippet));
    }
  }

  /** Viewer M1: the one-line caption under the evidence heading (see `EVIDENCE_CAPTION`). */
  private appendEvidenceCaption(parent: HTMLElement): void {
    add(parent, el('p', 'mlv-insp__caption', EVIDENCE_CAPTION));
  }

  private appendChallenge(parent: HTMLElement): void {
    const challenge = button('mlv-btn mlv-insp__challenge', 'Challenge this claim');
    on(challenge, 'click', () => this.cb.onChallenge());
    parent.appendChild(challenge);
  }

  /**
   * One finding. `standalone` is the finding's own Inspector, where its evidence heading carries
   * the caption; inside a step's or connection's Inspector the step's own evidence carries it.
   */
  private inspectorIssue(issue: Issue, s: RailState, standalone = false): HTMLElement {
    const box = el('div', 'mlv-insp__issue');
    box.setAttribute('data-issue-id', issue.id);
    const head = add(box, el('div', 'mlv-insp__issue-head'));
    head.appendChild(severityGlyph(issue.severity, 14, ''));
    add(head, el('span', 'mlv-mono', issue.code));
    add(head, el('span', '', issue.title));
    head.appendChild(basisChip(issue));
    add(box, el('p', 'mlv-insp__line', issue.message));
    // Viewer M1: the author's suggestion, labelled as the skill words it. An analyzer-era rule
    // hid it, under a "Suggested check" heading that stayed visible over nothing.
    const suggestion = suggestionBlock(issue, 'h5');
    if (suggestion) box.appendChild(suggestion);
    if ((issue.relatedLocs || []).length) {
      box.appendChild(this.heading('Evidence review'));
      if (standalone) this.appendEvidenceCaption(box);
      const stale = issueStaleReasons(issue, s.staleReason);
      if (stale.length) {
        box.classList.add('is-stale');
        const note = add(box, el('p', 'mlv-insp__stale-note'));
        note.appendChild(uiIcon('warning', 12));
        add(note, el('span', '', allElsewhere(stale)
          ? 'This finding ' + staleChipText(stale) + '; those jumps are blocked. The notice above says which folder to add.'
          : 'This finding ' + staleChipText(stale) + ' since publishing; those jumps are blocked.'));
      }
      const list = add(box, el('ul', 'mlv-insp__related'));
      for (const rel of issue.relatedLocs) {
        const li = add(list, el('li'));
        const reason = s.staleReason && rel.file ? s.staleReason(rel.file) : undefined;
        const link = el('button', 'mlv-link', (rel.message || rel.role) + ' — ' + fileLine(rel)) as HTMLButtonElement;
        link.type = 'button';
        link.setAttribute('data-evidence-id', rel.evidenceId || '');
        if (reason) {
          li.classList.add('is-stale');
          li.setAttribute('data-stale', reason);
        }
        wireOpenControl(link, rel, (target, focusEditor) => this.cb.onOpen(target, focusEditor), reason);
        li.appendChild(link);
        if (reason) li.appendChild(staleBadge(reason));
        if (rel.snippet) add(li, el('pre', 'mlv-banner__detail', rel.snippet));
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

/** A phase's label from the graph's stage list, or its id when it has none. */
function stageLabel(index: GraphIndex, id: string): string {
  const stage = (index.graph.stages || []).find((item) => item.id === id);
  return (stage && stage.label) || id;
}

/** Why a quote cannot be opened, as an icon and words beside its disabled link (viewer M1). */
function staleBadge(reason: StaleReason): HTMLElement {
  const badge = el('span', 'mlv-insp__stale');
  badge.setAttribute('data-stale', reason);
  badge.appendChild(uiIcon('warning', 12));
  add(badge, el('span', '', STALE_TEXT[reason]));
  return badge;
}
