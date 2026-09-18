/**
 * Top bar, chip row, banners and status bar — plus the search box.
 * Everything the user needs to know about the run before touching the canvas.
 */

import { add, button, clear, el, iconButton, on } from '../dom.js';
import { uiIcon } from '../icons.js';
import { severityGlyph, SEVERITY_ORDER } from '../markers.js';
import { RovingGroup } from './roving.js';
import { chromeBandHeight, stat } from './chromenotes.js';
import { renderBanners } from './chromebanners.js';
import { MAX_CHIPS, chipTitle, collectChips } from './chromechips.js';
import type { ChipSpec } from './chromechips.js';
import { suppressedSummary } from './suppress.js';
import { isSetAside } from '../types.js';
import type { Capabilities, Filters, MLGraph, Severity, Stage } from '../types.js';

export interface ChromeCallbacks {
  /** Retained for generic empty/error banner plumbing; authored views never show it. */
  onRefresh(): void;
  onQuery(q: string): void;
  onStage(stageId: string): void;
  onClearFilters(): void;
  onZoomToSelection(): void;
  onSearchKey(ev: KeyboardEvent): void;
  onToggleRail(): void;
  onSeverity(sev: Severity): void;
  onShowSuppressed(next: boolean): void;
  onFit(): void;
  onZoom(dir: number): void;
  onAction(id: string): void;
  onDismiss(key: string): void;
  /** Open the scope picker (FEATURES 3.7). */
  onScope(): void;
  /** Toggle the flow animation entirely off/on; persisted as ViewState.flow. */
  onToggleFlow(next: boolean): void;
  /** Open or close the legend (VIEW-10); persisted as ViewState.legendOpen. */
  onToggleLegend(next: boolean): void;
  /**
   * VIEW-12: the keyboard's minimap toggle. The panel itself is `aria-hidden`
   * and its chevron is pointer-only, so this button is the only accessible way
   * to collapse the overview — and it is before the canvas in DOM order,
   * instead of the tab stop after it that the chevron used to be.
   */
  onToggleMinimap(next: boolean): void;
  /** CI-ADOPT: "only changed" — drops findings attributed `existing`. */
  onChangedOnly(next: boolean): void;
}

export interface ChromeState {
  graph: MLGraph | null;
  hasSelection: boolean;
  filters: Filters;
  capabilities: Capabilities;
  stale: string[];
  error: { message: string; detail?: string; actions?: { id: string; label: string }[] } | null;
  dismissed: Set<string>;
  visibleCounts: { low: number; medium: number; high: number };
  dynamicNodes: number;
  /** The active scope's human label, or "Everything". */
  scopeLabel: string;
  scopeActive: boolean;
  flowOn: boolean;
  /** Whether the legend panel is open (VIEW-10). */
  legendOpen: boolean;
  /** Lanes actually drawn — under a scope the filter chips follow them. */
  laneIds: string[];
  /** Present in the FULL analysis, absent from THIS projection (11.4 F3). */
  outOfScopeStages: Stage[];
  /** Whether the minimap is collapsed, for the toolbar's toggle (VIEW-12). */
  minimapCollapsed: boolean;
}

let chromeSeq = 0;

export class Chrome {
  /**
   * The whole control strip as ONE `role="toolbar"` (VIEW-12).
   *
   * The toolbar row and the stage-filter row are two visual rows of the same
   * widget: leaving them as separate tab stops kept seven stage chips, four
   * theme chips and eleven buttons in the Tab order ahead of the canvas. Under
   * one roving group the strip costs one press, and the search input inside it
   * keeps the second.
   */
  readonly bar: HTMLElement;
  readonly toolbar: HTMLElement;
  readonly filterRow: HTMLElement;
  readonly chipRow: HTMLElement;
  /** The scrolling half of the chip row; the opener sits beside it. */
  private chipScroll!: HTMLElement;
  readonly banners: HTMLElement;
  readonly status: HTMLElement;
  readonly searchInput: HTMLInputElement;
  readonly results: HTMLElement;
  private statsEl: HTMLElement;
  private sevButtons = new Map<Severity, HTMLButtonElement>();
  private suppressedBtn: HTMLButtonElement;
  private zoomSelBtn: HTMLButtonElement;
  private rootLabel: HTMLElement;
  private scopeBtn: HTMLButtonElement;
  private flowBtn: HTMLButtonElement;
  private legendBtn: HTMLButtonElement;
  private minimapBtn: HTMLButtonElement;
  private roving: RovingGroup | null = null;
  /** Where the App mounts the scope breadcrumb: first element after the brand. */
  readonly scopeSlot: HTMLElement;
  /**
   * VIEW-07: where the App mounts the export menu's TRIGGER — beside Fit, which
   * is where the roadmap put it and where a reader looks for "give me this
   * picture". Only the trigger: the popup is mounted on the app root, so the
   * roving toolbar never takes its eight controls into the arrow-key order.
   */
  readonly exportSlot: HTMLElement;
  private cb: ChromeCallbacks;
  /** The folded chip descriptors of the current document (HOSTS-UX-CHIPWALL). */
  private chipSpecs: ChipSpec[] = [];
  /** Whether the reader has opened the folded tail of the chip row. */
  private chipsExpanded = false;

  constructor(cb: ChromeCallbacks) {
    this.cb = cb;
    const uid = 'mlv' + ++chromeSeq;
    this.bar = el('div', 'mlv-chromebar');
    this.bar.setAttribute('role', 'toolbar');
    this.bar.setAttribute('aria-label', 'Diagram controls');
    this.bar.setAttribute('aria-orientation', 'horizontal');
    this.toolbar = add(this.bar, el('div', 'mlv-toolbar'));

    // VIEW-12: the document's ONE `h1`, and it carries the workspace name —
    // which existed only in `<title>` and in the brand text, so heading
    // navigation started mid-document at a rail `h3`.
    const brand = add(this.toolbar, el('h1', 'mlv-brand'));
    add(brand, el('span', 'mlv-brand__name', 'MLView'));
    this.rootLabel = add(brand, el('span', 'mlv-brand__root', ''));

    this.scopeSlot = add(this.toolbar, el('div', 'mlv-toolbar__scope'));

    this.scopeBtn = el('button', 'mlv-btn mlv-btn--scope') as HTMLButtonElement;
    this.scopeBtn.type = 'button';
    this.scopeBtn.appendChild(uiIcon('scope', 13));
    add(this.scopeBtn, el('span', 'mlv-btn__label', 'Everything'));
    this.scopeBtn.title = 'Scope the diagram to one part of this codebase';
    this.scopeBtn.setAttribute('aria-haspopup', 'dialog');
    on(this.scopeBtn, 'click', () => cb.onScope());
    this.toolbar.appendChild(this.scopeBtn);

    const search = add(this.toolbar, el('div', 'mlv-search'));
    const label = add(search, el('label', 'mlv-sr', 'Search nodes and issues'));
    label.htmlFor = uid + '-search-input';
    this.searchInput = add(search, el('input', 'mlv-input')) as HTMLInputElement;
    this.searchInput.id = uid + '-search-input';
    this.searchInput.type = 'search';
    this.searchInput.placeholder = 'Search label, qualname, issue, MLV code…';
    this.searchInput.setAttribute('role', 'combobox');
    this.searchInput.setAttribute('aria-expanded', 'false');
    this.searchInput.setAttribute('aria-controls', uid + '-search-results');
    this.searchInput.autocomplete = 'off';
    this.results = add(search, el('ul', 'mlv-search__results'));
    this.results.id = uid + '-search-results';
    this.results.setAttribute('role', 'listbox');
    this.results.setAttribute('aria-label', 'Search results');
    this.results.hidden = true;
    on(this.searchInput, 'input', () => cb.onQuery(this.searchInput.value));
    on(this.searchInput, 'keydown', (ev: KeyboardEvent) => cb.onSearchKey(ev));

    this.statsEl = add(this.toolbar, el('div', 'mlv-stats'));

    add(this.toolbar, el('div', 'mlv-toolbar__spacer'));

    for (const sev of SEVERITY_ORDER) {
      const b = el('button', 'mlv-chip mlv-chip--btn') as HTMLButtonElement;
      b.type = 'button';
      b.setAttribute('aria-pressed', 'true');
      b.title = 'Toggle ' + sev + ' severity findings';
      b.setAttribute('data-severity', sev);
      b.appendChild(severityGlyph(sev, 13, ''));
      add(b, el('span', 'mlv-chip__count', '0'));
      on(b, 'click', () => cb.onSeverity(sev));
      this.sevButtons.set(sev, b);
      this.toolbar.appendChild(b);
    }

    // Rendered only when the graph actually holds suppressed findings, and
    // labelled with their count like the severity chips beside it (MLV-R2-W09).
    this.suppressedBtn = el('button', 'mlv-chip mlv-chip--btn') as HTMLButtonElement;
    this.suppressedBtn.type = 'button';
    this.suppressedBtn.textContent = 'suppressed';
    this.suppressedBtn.setAttribute('aria-pressed', 'false');
    this.suppressedBtn.hidden = true;
    this.suppressedBtn.title = 'Show suppressed findings';
    on(this.suppressedBtn, 'click', () => cb.onShowSuppressed(this.suppressedBtn.getAttribute('aria-pressed') !== 'true'));
    this.toolbar.appendChild(this.suppressedBtn);

    // A real aria-pressed toggle whose title names the CURRENT state, so the
    // one thing that moves on the canvas is one keystroke from being stopped.
    //
    // VIEW-10: it carries a VISIBLE text label, not only an aria-label. The
    // marquee feature of the product sat behind an unlabelled icon at tab stop
    // 5 with no binding and no hint that hovering anything did anything. The
    // label is hidden by CSS below 1280 px, where the toolbar has no room.
    this.flowBtn = el('button', 'mlv-btn mlv-btn--flow') as HTMLButtonElement;
    this.flowBtn.type = 'button';
    this.flowBtn.appendChild(uiIcon('flow'));
    add(this.flowBtn, el('span', 'mlv-btn__label', 'Flow'));
    this.flowBtn.setAttribute('aria-pressed', 'true');
    on(this.flowBtn, 'click', () => cb.onToggleFlow(this.flowBtn.getAttribute('aria-pressed') !== 'true'));
    this.toolbar.appendChild(this.flowBtn);

    // The legend, likewise labelled: a key nobody can find is not a key.
    this.legendBtn = el('button', 'mlv-btn mlv-btn--legend') as HTMLButtonElement;
    this.legendBtn.type = 'button';
    this.legendBtn.appendChild(uiIcon('legend'));
    add(this.legendBtn, el('span', 'mlv-btn__label', 'Legend'));
    this.legendBtn.setAttribute('aria-pressed', 'false');
    this.legendBtn.title = 'Show what every glyph, stroke and card state means';
    this.legendBtn.setAttribute('aria-label', this.legendBtn.title);
    on(this.legendBtn, 'click', () => cb.onToggleLegend(this.legendBtn.getAttribute('aria-pressed') !== 'true'));
    this.toolbar.appendChild(this.legendBtn);

    // The minimap's keyboard toggle (VIEW-12). `aria-pressed` reads "the
    // overview is shown", so it is pressed while the panel is EXPANDED.
    this.minimapBtn = el('button', 'mlv-btn mlv-btn--icon mlv-btn--minimap') as HTMLButtonElement;
    this.minimapBtn.type = 'button';
    this.minimapBtn.appendChild(uiIcon('minimap'));
    this.minimapBtn.setAttribute('aria-pressed', 'true');
    on(this.minimapBtn, 'click', () => cb.onToggleMinimap(this.minimapBtn.getAttribute('aria-pressed') === 'true'));
    this.toolbar.appendChild(this.minimapBtn);

    const zoomOut = iconButton('mlv-btn mlv-btn--icon', 'Zoom out');
    zoomOut.appendChild(uiIcon('minus'));
    on(zoomOut, 'click', () => cb.onZoom(-1));
    this.toolbar.appendChild(zoomOut);

    const zoomIn = iconButton('mlv-btn mlv-btn--icon', 'Zoom in');
    zoomIn.appendChild(uiIcon('plus'));
    on(zoomIn, 'click', () => cb.onZoom(1));
    this.toolbar.appendChild(zoomIn);

    const fit = iconButton('mlv-btn mlv-btn--icon', 'Fit to view');
    fit.appendChild(uiIcon('fit'));
    on(fit, 'click', () => cb.onFit());
    this.toolbar.appendChild(fit);

    this.exportSlot = add(this.toolbar, el('span', 'mlv-toolbar__exportslot'));

    this.zoomSelBtn = iconButton('mlv-btn mlv-btn--icon', 'Zoom to selection');
    this.zoomSelBtn.appendChild(uiIcon('target'));
    on(this.zoomSelBtn, 'click', () => cb.onZoomToSelection());
    this.toolbar.appendChild(this.zoomSelBtn);

    const rail = iconButton('mlv-btn mlv-btn--icon', 'Toggle side rail');
    rail.appendChild(uiIcon('rail'));
    on(rail, 'click', () => cb.onToggleRail());
    this.toolbar.appendChild(rail);

    this.filterRow = add(this.bar, el('div', 'mlv-filterrow'));
    // HOSTS-UX-CHIPWALL. The chip row is the strip's THIRD row, inside the same
    // `role="toolbar"` as the toolbar and the filter chips — not because it is
    // a row of controls (it is mostly static notes, as the filter row is mostly
    // labels) but because the cap it now carries needs ONE control to open the
    // folded tail, and a control between the search box and the canvas is a
    // fifth Tab press to the diagram. VIEW-12 allows four. Inside the roving
    // group that control costs nothing: the whole strip stays one tab stop, and
    // the arrow keys reach the opener exactly as they reach every stage chip.
    // The visual stack is unchanged — `.mlv-chromebar` is a flex column and the
    // row is appended last, which is where the app used to put it.
    this.chipRow = add(this.bar, el('div', 'mlv-chiprow'));
    // The chips SCROLL inside the row's bound; the opener does not. Measured on
    // yolov5 at 1600x1000: a 12vh row holds four of those sentence chips, so a
    // trailing opener was the one control the fold cannot do without and the
    // one thing below the fold. It is a sibling of the scroller, not a chip in
    // it, which is the only arrangement that cannot scroll away.
    this.chipScroll = add(this.chipRow, el('div', 'mlv-chiprow__chips'));
    this.banners = el('div', 'mlv-banners');
    this.status = el('div', 'mlv-status');

    // One roving group over both rows. Built last, so every control the strip
    // ships with is already in it; `update()` re-syncs it after the stage chips
    // are rebuilt.
    this.roving = new RovingGroup(this.bar);
  }

  destroy(): void {
    if (this.roving) this.roving.destroy();
    this.roving = null;
  }

  update(s: ChromeState): void {
    const g = s.graph;
    this.rootLabel.textContent = g ? g.workspace.root : '';
    if (g) this.rootLabel.title = g.workspace.root;

    clear(this.statsEl);
    if (g) {
      this.statsEl.appendChild(stat(String(g.nodes.length), g.nodes.length === 1 ? 'node' : 'nodes'));
      this.statsEl.appendChild(stat(String(g.edges.length), g.edges.length === 1 ? 'edge' : 'edges'));
    }

    for (const sev of SEVERITY_ORDER) {
      const b = this.sevButtons.get(sev)!;
      const active = s.filters.severities.indexOf(sev) >= 0;
      b.setAttribute('aria-pressed', active ? 'true' : 'false');
      const count = b.querySelector('.mlv-chip__count');
      if (count) count.textContent = String(s.visibleCounts[sev]);
    }
    // VW-04. The severity chips beside this button now net out BASELINED
    // findings as well as suppressed ones, exactly as the rail, the answer card
    // and `mlview issues` do — so this button has to say both, or the reader is
    // left with a total that does not add up. One wording, one helper: the rail
    // section head uses the same `suppressedSummary`.
    const setAside = g ? (g.issues || []).filter(isSetAside) : [];
    const baselined = setAside.filter((i) => i.baselined).length;
    const suppressed = setAside.length - baselined;
    const summary = suppressedSummary(suppressed, baselined);
    this.suppressedBtn.hidden = setAside.length === 0;
    this.suppressedBtn.textContent = summary;
    this.suppressedBtn.setAttribute('data-set-aside', String(setAside.length));
    this.suppressedBtn.title =
      (s.filters.showSuppressed ? 'Hide' : 'Show') + ' ' + summary +
      ' finding' + (setAside.length === 1 ? '' : 's') + ' — they are not in the counts above';
    this.suppressedBtn.setAttribute('aria-label', this.suppressedBtn.title);
    this.suppressedBtn.setAttribute('aria-pressed', s.filters.showSuppressed ? 'true' : 'false');

    const scopeLabelEl = this.scopeBtn.querySelector('.mlv-btn__label');
    if (scopeLabelEl) scopeLabelEl.textContent = s.scopeLabel;
    this.scopeBtn.setAttribute('aria-pressed', s.scopeActive ? 'true' : 'false');
    this.scopeBtn.setAttribute('aria-label', 'Scope diagram — currently ' + s.scopeLabel);
    this.flowBtn.setAttribute('aria-pressed', s.flowOn ? 'true' : 'false');
    this.flowBtn.title = 'Connection flow animation is ' + (s.flowOn ? 'on' : 'off') + ' — press A to toggle';
    this.flowBtn.setAttribute('aria-label', 'Connection flow animation is ' + (s.flowOn ? 'on' : 'off'));
    this.legendBtn.setAttribute('aria-pressed', s.legendOpen ? 'true' : 'false');
    const shown = !s.minimapCollapsed;
    this.minimapBtn.setAttribute('aria-pressed', shown ? 'true' : 'false');
    this.minimapBtn.title = 'Overview minimap is ' + (shown ? 'shown' : 'hidden');
    this.minimapBtn.setAttribute('aria-label', this.minimapBtn.title);

    this.zoomSelBtn.disabled = !s.hasSelection;

    this.renderStageFilters(s);
    this.renderChips(s);
    renderBanners(this.banners, s, this.cb);
    this.renderStatus(s);
    // The stage chip row was just rebuilt: put the strip's single tab stop back
    // (VIEW-12).
    if (this.roving) this.roving.sync();
  }

  /** Stage chips: every present band, toggleable. Empty selection means "all". */
  private renderStageFilters(s: ChromeState): void {
    clear(this.filterRow);
    const g = s.graph;
    if (!g) {
      this.filterRow.hidden = true;
      return;
    }
    const drawn = s.laneIds;
    const stages = (g.stages || []).filter(
      (st) => st.present && (!s.scopeActive || drawn.indexOf(st.id) >= 0),
    );
    if (!stages.length) {
      this.filterRow.hidden = true;
      return;
    }
    // CI-ADOPT: offered only when the run was actually attributed against a
    // base revision. An unattributed document must not grow a filter that can
    // only ever hide nothing.
    const attributed = (g.issues || []).some((i) => typeof i.change === 'string' && i.change);
    if (attributed) {
      const changed = el('button', 'mlv-chip mlv-chip--btn mlv-chip--changed') as HTMLButtonElement;
      changed.type = 'button';
      changed.textContent = 'only changed';
      changed.setAttribute('data-changed-filter', '1');
      const on_ = !!s.filters.changedOnly;
      changed.setAttribute('aria-pressed', on_ ? 'true' : 'false');
      changed.title = 'Show only findings on lines this change touched';
      changed.setAttribute('aria-label', changed.title);
      on(changed, 'click', () => this.cb.onChangedOnly(!s.filters.changedOnly));
      this.filterRow.appendChild(changed);
    }
    add(this.filterRow, el('span', 'mlv-chiprow__label', 'stages'));
    const active = s.filters.stages;
    for (const stage of stages) {
      const on_ = active.length === 0 || active.indexOf(stage.id) >= 0;
      const chip = el('button', 'mlv-chip mlv-chip--btn mlv-chip--stage') as HTMLButtonElement;
      chip.type = 'button';
      chip.setAttribute('data-stage', stage.id);
      chip.setAttribute('data-stage-filter', stage.id);
      chip.setAttribute('aria-pressed', on_ ? 'true' : 'false');
      chip.title = 'Show only the ' + (stage.label || stage.id) + ' stage';
      add(chip, el('span', '', stage.label || stage.id));
      on(chip, 'click', () => this.cb.onStage(stage.id));
      this.filterRow.appendChild(chip);
    }
    const dirty =
      active.length > 0 ||
      s.filters.severities.length < 3 ||
      s.filters.showSuppressed ||
      !!s.filters.changedOnly ||
      s.filters.query.length > 0;
    if (dirty) {
      const clearBtn = button('mlv-btn', 'Clear filters');
      on(clearBtn, 'click', () => this.cb.onClearFilters());
      this.filterRow.appendChild(clearBtn);
    }
    this.filterRow.hidden = false;
  }

  /**
   * The chip row, in three steps: COLLECT, FOLD, CAP (HOSTS-UX-CHIPWALL).
   *
   * It used to be one step — one chip per `graph.diagnostics` entry, appended
   * straight to the row. Measured on the pinned public corpus at 1600x1000,
   * that made `.mlv-chiprow` 2132 px tall on ultralytics/yolov5, 3765 px on
   * huggingface/pytorch-image-models — and `.mlv-canvas` 0 px on both, because
   * `.mlv-body` is the `flex: 1 1 auto; min-height: 0` item that absorbs
   * whatever the rows above it take. Seven of sixteen public repositories drew
   * a zero-pixel canvas that way, with every card in the DOM and none on
   * screen, while the toolbar went on reading `400 nodes · 813 edges`. Of
   * yolov5's 70 chips only 49 were distinct: one sentence was drawn 8 times
   * verbatim, and `analyzer/tests/fixtures` drew `1 value not traced` 36 times.
   *
   * Nothing is deleted here. A fold carries its count, the cap carries a chip
   * that lists the rest, every message stays on a `title`, the banners keep
   * their own copies of the coverage and parse diagnostics, and the status bar
   * still counts every one of them as "N notes".
   */
  private renderChips(s: ChromeState): void {
    this.chipSpecs = s.graph ? collectChips(s) : [];
    this.paintChips();
  }

  /** Draw `chipSpecs`, honouring the cap and the reader's expansion. */
  private paintChips(): void {
    clear(this.chipScroll);
    const opener = this.chipRow.querySelector('[data-chip-more]');
    if (opener && opener.parentNode) opener.parentNode.removeChild(opener);
    const specs = this.chipSpecs;
    if (!specs.length) {
      this.chipRow.hidden = true;
      return;
    }
    const hidden = Math.max(0, specs.length - MAX_CHIPS);
    const capped = hidden > 0 && !this.chipsExpanded;
    const shown = capped ? specs.slice(0, MAX_CHIPS) : specs;
    let label = '';
    for (const spec of shown) {
      if (spec.label && spec.label !== label) add(this.chipScroll, el('span', 'mlv-chiprow__label', spec.label));
      if (spec.label) label = spec.label;
      // TAB2-10. A chip is a label, and three diagnostic kinds carry a
      // SENTENCE. The text goes in its own element so the stylesheet can bound
      // it to one ellipsised line (`.mlv-chiprow .mlv-chip__text`, CHIP_TEXT_CH)
      // while the `×N` count beside it stays whole. Nothing is removed: the
      // element holds every character, so `textContent`, the exported HTML and
      // every screen reader still get the sentence, and the `title` below
      // carries it for a hover.
      const node = add(this.chipScroll, el('span', 'mlv-chip' + (spec.cls ? ' ' + spec.cls : '')));
      add(node, el('span', 'mlv-chip__text', spec.text));
      for (const attr of spec.attrs) node.setAttribute(attr[0], attr[1]);
      if (spec.count > 1) {
        const count = add(node, el('span', 'mlv-chip__count', '×' + spec.count));
        count.setAttribute('data-chip-fold', String(spec.count));
      }
      const title = chipTitle(spec);
      if (title) node.title = title;
    }
    if (hidden > 0) this.chipRow.appendChild(this.moreChip(hidden, capped));
    this.chipRow.hidden = false;
    // The row is inside the roving toolbar: a rebuilt row must hand the strip's
    // single tab stop back (VIEW-12), exactly as the stage chips do.
    if (this.roving) this.roving.sync();
  }

  /**
   * The one chip that stands for the rest — a real button, never a label.
   *
   * `aria-pressed` is deliberately NOT used: `.mlv-chip--btn[aria-pressed="false"]`
   * is struck through, which is right for a filter that is off and wrong for a
   * disclosure that is closed.
   */
  private moreChip(hidden: number, capped: boolean): HTMLButtonElement {
    const more = el('button', 'mlv-chip mlv-chip--btn mlv-chip--more') as HTMLButtonElement;
    more.type = 'button';
    more.textContent = capped ? '+' + hidden + ' more' : 'show fewer';
    more.setAttribute('data-chip-more', String(hidden));
    more.setAttribute('aria-expanded', capped ? 'false' : 'true');
    more.title = capped
      ? hidden + ' more note(s) about this run are folded away — press to list them all'
      : 'Fold the last ' + hidden + ' note(s) back behind one chip';
    more.setAttribute('aria-label', more.title);
    on(more, 'click', () => {
      this.chipsExpanded = !this.chipsExpanded;
      this.paintChips();
      // Keep the reader on the control they just pressed: `paintChips` rebuilt
      // the row, so the button they were on no longer exists.
      const next = this.chipRow.querySelector('[data-chip-more]') as HTMLElement | null;
      if (!next) return;
      try {
        next.focus();
      } catch (_e) {
        /* a host may have detached the row already */
      }
    });
    return more;
  }

  /**
   * HOSTS-UX-R2-06 — what the two bands above the canvas are taking, in CSS
   * pixels, read AFTER `update()` has drawn them.
   *
   * It counts what was actually drawn rather than re-deriving the banner
   * predicates, for the same reason 11.55 D2 gives about `drawnCount`: a second
   * copy of the rules is a second set of numbers to keep in step. The estimate
   * itself is `chromenotes.chromeBandHeight`, which has no DOM in it.
   */
  bandHeight(): number {
    const banners = this.banners.hidden ? 0 : this.banners.querySelectorAll('.mlv-banner').length;
    const chips = this.chipRow.hidden ? 0 : this.chipRow.querySelectorAll('.mlv-chip').length;
    return chromeBandHeight(banners, chips);
  }

  private renderStatus(s: ChromeState): void {
    clear(this.status);
    const g = s.graph;
    if (!g) {
      add(this.status, el('span', '', 'Waiting for a workflow…'));
      return;
    }
    add(this.status, el('span', '', g.nodes.length + ' nodes · ' + g.edges.length + ' edges'));
    const sev = add(this.status, el('span', 'mlv-stats'));
    for (const s2 of SEVERITY_ORDER) {
      const wrap = add(sev, el('span', 'mlv-stat'));
      wrap.appendChild(severityGlyph(s2, 11, s2 + ' severity'));
      add(wrap, el('span', 'mlv-stat__value', String(s.visibleCounts[s2])));
    }
    if (g.workspace.frameworks && g.workspace.frameworks.length) {
      add(this.status, el('span', '', g.workspace.frameworks.join(', ')));
    }
    add(this.status, el('span', '', 'schema ' + g.schemaVersion + ' · mlview ' + g.generator.version));
    const notes = (g.diagnostics || []).length;
    if (notes) add(this.status, el('span', '', notes + (notes === 1 ? ' note' : ' notes')));
  }
}
