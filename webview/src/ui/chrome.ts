/**
 * Top bar, chip row, banners and status bar — plus the search box.
 * Everything the user needs to know about the run before touching the canvas.
 */

import { add, button, clear, el, iconButton, on } from '../dom.js';
import { uiIcon } from '../icons.js';
import { severityGlyph, SEVERITY_ORDER } from '../markers.js';
import { RovingGroup } from './roving.js';
import {
  COVERAGE_KINDS,
  SPECIALLY_RENDERED,
  coverageChipText,
  coverageHeadline,
  describe,
  notebooksAnalyzedText,
  stat,
} from './chromenotes.js';
import { NOTEBOOK_ANALYZED, outOfOrderDiagnostics, outOfOrderHeadline } from '../notebook.js';
import { suppressedSummary } from './suppress.js';
import { isSetAside } from '../types.js';
import type { Capabilities, Filters, MLGraph, Severity, Stage } from '../types.js';

export interface ChromeCallbacks {
  onQuery(q: string): void;
  onStage(stageId: string): void;
  onClearFilters(): void;
  onZoomToSelection(): void;
  onSearchKey(ev: KeyboardEvent): void;
  onRefresh(): void;
  onExport(): void;
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
  readonly banners: HTMLElement;
  readonly status: HTMLElement;
  readonly searchInput: HTMLInputElement;
  readonly results: HTMLElement;
  private statsEl: HTMLElement;
  private sevButtons = new Map<Severity, HTMLButtonElement>();
  private refreshBtn: HTMLButtonElement;
  private exportBtn: HTMLButtonElement;
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

    this.refreshBtn = iconButton('mlv-btn mlv-btn--icon', 'Re-analyze workspace');
    this.refreshBtn.appendChild(uiIcon('refresh'));
    on(this.refreshBtn, 'click', () => cb.onRefresh());
    this.toolbar.appendChild(this.refreshBtn);

    this.exportBtn = iconButton('mlv-btn mlv-btn--icon', 'Export standalone HTML report');
    this.exportBtn.appendChild(uiIcon('export'));
    on(this.exportBtn, 'click', () => cb.onExport());
    this.toolbar.appendChild(this.exportBtn);

    const rail = iconButton('mlv-btn mlv-btn--icon', 'Toggle side rail');
    rail.appendChild(uiIcon('rail'));
    on(rail, 'click', () => cb.onToggleRail());
    this.toolbar.appendChild(rail);

    this.filterRow = add(this.bar, el('div', 'mlv-filterrow'));
    this.chipRow = el('div', 'mlv-chiprow');
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

    this.refreshBtn.hidden = !s.capabilities.canReanalyze;
    this.exportBtn.hidden = !s.capabilities.canExport;
    this.zoomSelBtn.disabled = !s.hasSelection;

    this.renderStageFilters(s);
    this.renderChips(s);
    this.renderBanners(s);
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

  private renderChips(s: ChromeState): void {
    clear(this.chipRow);
    const g = s.graph;
    if (!g) {
      this.chipRow.hidden = true;
      return;
    }
    let any = false;
    const absent = (g.stages || []).filter((st) => !st.present).map((st) => st.label || st.id);
    if (absent.length) {
      any = true;
      add(this.chipRow, el('span', 'mlv-chiprow__label', 'not detected'));
      for (const name of absent) add(this.chipRow, el('span', 'mlv-chip', name));
    }
    if (s.outOfScopeStages.length) {
      any = true;
      add(this.chipRow, el('span', 'mlv-chiprow__label', 'not in this scope'));
      for (const stage of s.outOfScopeStages) {
        const chip = add(this.chipRow, el('span', 'mlv-chip mlv-chip--outscope', stage.label || stage.id));
        chip.setAttribute('data-out-of-scope', stage.id);
      }
    }
    for (const d of g.diagnostics || []) {
      if (d.kind === 'notebook_skipped') {
        any = true;
        add(this.chipRow, el('span', 'mlv-chip', (d.count || 0) + ' notebooks not analyzed'));
      } else if (d.kind === NOTEBOOK_ANALYZED) {
        // NB. Without `--include-notebooks` this never appears, because the
        // diagnostic is never emitted.
        any = true;
        // VW-06: ONE diagnostic per notebook, and its `count` is that
        // notebook's code cells — so the chip is one notebook (the hook keeps
        // its name) and the cell count is its own attribute.
        const chip = add(this.chipRow, el('span', 'mlv-chip', notebooksAnalyzedText(d)));
        chip.setAttribute('data-notebooks-analyzed', '1');
        chip.setAttribute('data-notebook-cells', String(d.count || 0));
        chip.title = d.message;
      } else if (d.kind === 'framework_suppressed') {
        any = true;
        const text = d.message + (d.codes && d.codes.length ? ' (' + d.codes.join(', ') + ')' : '');
        add(this.chipRow, el('span', 'mlv-chip', text));
      } else if (d.kind === 'config_warning' || d.kind === 'config_unresolved') {
        // VW-08. These are SENTENCES, not chips — CI-ADOPT's baseline and
        // --changed-paths warnings carry absolute paths and an instruction, and
        // the `--changed-paths` one measured 1779 px wide at a 1600 px window,
        // running 191 px off the page with no scrollbar and no `title`, so the
        // instruction it exists to give ("Pass the diff itself, or
        // --changed-since <rev>") was the half that was cut. The full text is
        // now on the chip's tooltip, and `.mlv-chiprow .mlv-chip` wraps.
        any = true;
        const chip = add(this.chipRow, el('span', 'mlv-chip', d.message));
        chip.setAttribute('data-config-note', d.kind);
        chip.title = d.message;
      } else if (COVERAGE_KINDS.indexOf(d.kind) >= 0) {
        // COVERAGE: a chip that says the analysis was BLIND here, distinct from
        // the "not detected" row beside it, which says it looked and found none.
        any = true;
        const chip = add(this.chipRow, el('span', 'mlv-chip mlv-chip--coverage', coverageChipText(d)));
        chip.setAttribute('data-coverage', d.kind);
        chip.title = d.message;
      } else if (SPECIALLY_RENDERED.indexOf(d.kind) < 0) {
        // A kind this renderer has never heard of still says what it says
        // (invariant 1.1/6) rather than vanishing into the "N notes" count.
        any = true;
        const chip = add(this.chipRow, el('span', 'mlv-chip', d.message || d.kind));
        chip.setAttribute('data-diagnostic-kind', d.kind);
      }
    }
    if ((g.workspace.filesFailed || 0) > 0) {
      any = true;
      add(this.chipRow, el('span', 'mlv-chip', g.workspace.filesFailed + ' files failed to parse'));
    }
    this.chipRow.hidden = !any;
  }

  private renderBanners(s: ChromeState): void {
    clear(this.banners);
    const g = s.graph;
    let any = false;

    if (s.error) {
      any = true;
      const b = this.banner('error', 'Analysis failed — ' + s.error.message, s.error.detail);
      const actions = add(b, el('div', 'mlv-banner__actions'));
      for (const a of s.error.actions || []) {
        const btn = button('mlv-btn', a.label);
        on(btn, 'click', () => this.cb.onAction(a.id));
        actions.appendChild(btn);
      }
      const copy = button('mlv-btn', 'Copy details');
      on(copy, 'click', () => this.cb.onAction('mlview.copyErrorDetails'));
      actions.appendChild(copy);
      this.banners.appendChild(b);
    }

    if (s.stale.length && !s.dismissed.has('stale')) {
      any = true;
      const names = s.stale.slice(0, 3).join(', ') + (s.stale.length > 3 ? ' and ' + (s.stale.length - 3) + ' more' : '');
      const b = this.banner('warn', 'Files changed since this analysis: ' + names);
      const actions = add(b, el('div', 'mlv-banner__actions'));
      if (s.capabilities.canReanalyze) {
        const btn = button('mlv-btn mlv-btn--primary', 'Re-analyze');
        on(btn, 'click', () => this.cb.onRefresh());
        actions.appendChild(btn);
      }
      actions.appendChild(this.dismissButton('stale'));
      this.banners.appendChild(b);
    }

    if (g) {
      const parseErrors = (g.diagnostics || []).filter((d) => d.kind === 'parse_error');
      if (parseErrors.length && !s.dismissed.has('parse')) {
        any = true;
        const b = this.banner('warn', parseErrors.length + ' file(s) could not be parsed', describe(parseErrors));
        add(b, el('div', 'mlv-banner__actions')).appendChild(this.dismissButton('parse'));
        this.banners.appendChild(b);
      }

      // NB. ABOVE the coverage banner: a notebook last run out of order makes
      // the fit-before-split family unreliable, and that has to be read before
      // the findings it de-rates.
      const outOfOrder = outOfOrderDiagnostics(g.diagnostics || []);
      if (outOfOrder.length && !s.dismissed.has('notebook-order')) {
        any = true;
        const b = this.banner('warn', outOfOrderHeadline(outOfOrder), describe(outOfOrder));
        b.setAttribute('data-notebook-order-banner', String(outOfOrder.length));
        add(b, el('div', 'mlv-banner__actions')).appendChild(this.dismissButton('notebook-order'));
        this.banners.appendChild(b);
      }
      // COVERAGE. One banner for everything the run could NOT see, above the
      // "partial understanding" note, because "I did not look" outranks "I
      // looked and was unsure".
      const coverage = (g.diagnostics || []).filter((d) => COVERAGE_KINDS.indexOf(d.kind) >= 0);
      if (coverage.length && !s.dismissed.has('coverage')) {
        any = true;
        const b = this.banner('warn', coverageHeadline(coverage), describe(coverage));
        b.setAttribute('data-coverage-banner', String(coverage.length));
        add(b, el('div', 'mlv-banner__actions')).appendChild(this.dismissButton('coverage'));
        this.banners.appendChild(b);
      }

      const dynamicDiags = (g.diagnostics || []).filter((d) => d.kind === 'dynamic_scope');
      if ((dynamicDiags.length > 0 || s.dynamicNodes > 0) && !s.dismissed.has('dynamic')) {
        any = true;
        const detail = dynamicDiags.length ? describe(dynamicDiags) : undefined;
        const b = this.banner(
          'info',
          'Partial understanding: some calls could not be resolved (config-driven or dynamic). ' +
            s.dynamicNodes +
            ' node(s) are shown with reduced confidence.',
          detail,
        );
        add(b, el('div', 'mlv-banner__actions')).appendChild(this.dismissButton('dynamic'));
        this.banners.appendChild(b);
      }

      if (g.stats && g.stats.truncated && !s.dismissed.has('truncated')) {
        any = true;
        const b = this.banner(
          'warn',
          'Graph truncated at ' + g.nodes.length + ' nodes — narrow the scope with --include, or collapse groups.',
        );
        add(b, el('div', 'mlv-banner__actions')).appendChild(this.dismissButton('truncated'));
        this.banners.appendChild(b);
      }
    }

    this.banners.hidden = !any;
  }

  private banner(kind: string, text: string, detail?: string): HTMLElement {
    const b = el('div', 'mlv-banner mlv-banner--' + kind);
    b.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    const body = add(b, el('div', 'mlv-banner__text'));
    add(body, el('div', '', text));
    if (detail) add(body, el('pre', 'mlv-banner__detail', detail));
    return b;
  }

  private dismissButton(key: string): HTMLButtonElement {
    const btn = iconButton('mlv-btn mlv-btn--icon', 'Dismiss');
    btn.appendChild(uiIcon('close'));
    on(btn, 'click', () => this.cb.onDismiss(key));
    return btn;
  }

  private renderStatus(s: ChromeState): void {
    clear(this.status);
    const g = s.graph;
    if (!g) {
      add(this.status, el('span', '', 'Waiting for analysis…'));
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
