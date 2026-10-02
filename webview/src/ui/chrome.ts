/**
 * The header row and the status bar (viewer M2), plus the search box inside the header.
 *
 * One header row of about 36 px replaces the brand row, the 21-control toolbar, the phase chip row
 * and the authored header. In order:
 *
 *   title · provenance chip (host · revision) · search · severity toggles · "N not observed" ·
 *   Review (viewer M3) · ... menu · Refine…
 *
 * The row never wraps. How much of it shows depends on the panel's width (`headerLayout`):
 *
 *   full   >= 1200 px  everything; "7 not observed (3 steps, 4 connections)"
 *   wide   >= 1000 px  the breakdown folds into the tooltip; "7 claims not observed"
 *   mid    >=  620 px  search becomes an icon that opens the field; the chip shows the revision only
 *   narrow  <  620 px  the title, the severity toggles, "not observed", ... and Refine… stay;
 *                      search and the revision move into the ... menu
 *
 * Every count on the row names its unit on screen (the owner's rule): the severity toggles are
 * followed by the word "findings", and "not observed" says "claims" or its breakdown.
 *
 * Viewer M2 review (M2R-2, A11Y-8): how wide the controls are depends on the document (two-digit
 * counts, three severities) and on whether the search field is open, so the layout alone could
 * not keep Refine… inside the panel. After every change `fitRow` measures the row and, while it
 * overflows, folds in this order: the revision chip and, since viewer M3, the Review button (About
 * and Review stay in the ... menu, and `r` starts the walk), the "not observed" toggle (into the
 * ... menu, with its count and units), then the title (kept for screen readers) and, only while
 * the search field is open at mid or narrow widths, the severity toggles (back when it closes). The roving tab stop is re-derived after each fold. A layout engine is
 * needed to measure; jsdom folds nothing.
 *
 * The status bar (about 22 px) carries the step and connection counts, the coverage status with the
 * limitation count, the source freshness (muted when every cited file is unchanged, a warning only
 * for changed or missing files) and the zoom with its two buttons. Nothing is counted twice.
 */

import { add, clear, el, iconButton, on } from '../dom.js';
import { uiIcon } from '../icons.js';
import { severityGlyph, SEVERITY_ORDER } from '../markers.js';
import { RovingGroup } from './roving.js';
import { MoreMenu } from './moremenu.js';
import { keyLabel } from './platform.js';
import type { MoreItemId } from './moremenu.js';
import type { FreshnessStatus } from '../freshness.js';
import type { Filters, MLGraph, Severity, WorkflowDocument } from '../types.js';

export type HeaderLayout = 'narrow' | 'mid' | 'wide' | 'full';

/** The panel widths (CSS px) at which the header changes shape. 541 px is the measured beside-the-code panel. */
export const HEADER_BREAKPOINTS = { mid: 620, wide: 1000, full: 1200 } as const;

/** The header's shape at this panel width. An unmeasurable width (jsdom, a detached mount) gets the full row. */
export function headerLayout(width: number): HeaderLayout {
  if (!(width > 0)) return 'full';
  if (width < HEADER_BREAKPOINTS.mid) return 'narrow';
  if (width < HEADER_BREAKPOINTS.wide) return 'mid';
  if (width < HEADER_BREAKPOINTS.full) return 'wide';
  return 'full';
}

export interface ChromeCallbacks {
  onQuery(q: string): void;
  onSearchKey(ev: KeyboardEvent): void;
  /** The search icon or the menu's Search: open the field and focus it. */
  onSearchOpen(): void;
  onSeverity(sev: Severity): void;
  /** Viewer M2: fade the observed claims so the inferred and unresolved ones stand out. */
  onToggleExceptions(next: boolean): void;
  /**
   * Viewer M2: the provenance chip, the status bar's coverage item and the ... menu's About item
   * open the About tab. `byKeyboard`: the control was activated from the keyboard (a click event
   * with no pointer detail), so the focus moves into About; a pointer click leaves it.
   */
  onAbout(byKeyboard: boolean): void;
  onZoom(dir: number): void;
  onToggleLegend(next: boolean): void;
  onToggleFlow(next: boolean): void;
  /** Viewer M3: show or hide the phase index (it replaced the minimap). */
  onTogglePhaseIndex(shown: boolean): void;
  /** Viewer M3: open the phase overview (Shift+0), or close it. */
  onOverview(): void;
  onToggleRail(): void;
  onFitWhole(): void;
  onZoomToSelection(): void;
  onExport(action: 'svg' | 'png' | 'copy-svg'): void;
  onShortcuts(): void;
  /** The ... menu is opening: repaint, so its checkboxes and disabled items are current. */
  onMenuOpen(): void;
  /** Viewer M3: the Review button or the ... menu's item: start the review walk, or end it. */
  onReview(): void;
}

export interface ChromeState {
  graph: MLGraph | null;
  document: WorkflowDocument | null;
  hasSelection: boolean;
  filters: Filters;
  /** Every finding in view by severity, whatever the toggles hide, so a toggle never hides its own count. */
  visibleCounts: { low: number; medium: number; high: number };
  flowOn: boolean;
  legendOpen: boolean;
  /** Viewer M3: the reader has not hidden the phase index. */
  phaseIndexShown: boolean;
  /** Why the phase index is not drawn (fewer than two phases), or null when it is (the ... menu says it). */
  phaseIndexUnavailable: string | null;
  /** Viewer M3: the phase overview is open. */
  overviewOpen: boolean;
  railOpen: boolean;
  /** The status bar's freshness item, or null before a document arrives. */
  freshness: FreshnessStatus | null;
  /** The host is checking a change on disk. */
  checking: boolean;
  /** Viewer M2: the claims in view that are not observed, by unit. */
  notObserved: NotObservedCounts;
  exceptionsOn: boolean;
  /** Viewer M2: the rail is docked beside the canvas or a bottom sheet under it (the menu names it). */
  railMode: 'docked' | 'sheet';
  /** Viewer M3: the review walk is running (Review is pressed). */
  walking: boolean;
}

/** Viewer M2: inferred or unresolved claims, counted by what they are. */
export interface NotObservedCounts {
  steps: number;
  connections: number;
  findings: number;
}

const plural = (n: number, one: string, many: string): string => n + ' ' + (n === 1 ? one : many);

/**
 * "7 not observed (3 connections, 4 findings)" — the count with its unit and its breakdown,
 * omitting a part that is zero. Every claim the author marked inferred or unresolved counts once.
 */
export function notObservedText(c: NotObservedCounts): string {
  const total = c.steps + c.connections + c.findings;
  const parts: string[] = [];
  if (c.steps) parts.push(plural(c.steps, 'step', 'steps'));
  if (c.connections) parts.push(plural(c.connections, 'connection', 'connections'));
  if (c.findings) parts.push(plural(c.findings, 'finding', 'findings'));
  return total + ' not observed (' + parts.join(', ') + ')';
}

/** "Coverage: scoped · 6 limitations" — the authored status, and the limitations counted with their unit. */
export function coverageText(document: WorkflowDocument): string {
  const n = document.coverage.limitations.length;
  return 'Coverage: ' + document.coverage.status + (n ? ' · ' + plural(n, 'limitation', 'limitations') : '');
}

/**
 * How far `fitRow` may fold the row: the revision chip and the Review button (viewer M3), then "not
 * observed", then the title; and, only while the search field is open, the severity toggles (they
 * come back when it closes).
 */
export const HEADER_FIT_MAX = 4;

/** "7 claims not observed": the lead the chip shows where its breakdown is not on screen. */
export function notObservedLead(c: NotObservedCounts): string {
  const total = c.steps + c.connections + c.findings;
  return total + (total === 1 ? ' claim' : ' claims') + ' not observed';
}

let chromeSeq = 0;

export class Chrome {
  /** The header row: the title, the provenance chip and the toolbar. */
  readonly header: HTMLElement;
  /** The header's controls: ONE `role="toolbar"` tab stop (VIEW-12); the search input keeps its own. */
  readonly toolbar: HTMLElement;
  readonly status: HTMLElement;
  readonly searchInput: HTMLInputElement;
  readonly results: HTMLElement;
  /** Where `workflow.ts` puts the Refine… button, which it rebuilds with the composer. */
  readonly refineSlot: HTMLElement;
  /** The ... menu; its panel goes on the app root (see `MoreMenu`). */
  readonly more: MoreMenu;
  private title: HTMLElement;
  private provenance: HTMLButtonElement;
  private provHost: HTMLElement;
  private provRev: HTMLElement;
  private search: HTMLElement;
  private searchBtn: HTMLButtonElement;
  private sevButtons = new Map<Severity, HTMLButtonElement>();
  /** The word after the severity toggles, "findings": the unit their numbers count. */
  private sevUnit: HTMLElement;
  private exceptionsBtn: HTMLButtonElement;
  /** Viewer M3: starts or ends the review walk; folds with the revision chip. */
  private reviewBtn: HTMLButtonElement;
  private counts: HTMLElement;
  private coverage: HTMLButtonElement;
  private fresh: HTMLElement;
  private roving: RovingGroup | null = null;
  private cb: ChromeCallbacks;
  private layout: HeaderLayout = 'full';
  /** The last width `setWidth` saw: a resize inside one layout still changes what fits. */
  private width = 0;
  /** How much `fitRow` folded the row (0 to HEADER_FIT_MAX). */
  private fitLevel = 0;
  /** A document is shown (the revision chip has something to say). */
  private hasDocument = false;
  /** There are claims that are not observed, so the "not observed" toggle exists. */
  private hasExceptions = false;
  /** The severities that have findings in view, so a toggle (a severity with none has none). */
  private sevShown = new Set<Severity>();
  private searchOpen = false;
  private lastAboutLabel = 'About this revision';
  /** The state of the last update, which the ... menu's toggles flip. */
  private state: ChromeState | null = null;

  /** `zoomBar` is the canvas view's zoom readout (`.mlv-zoom`); the status bar adopts it. */
  constructor(cb: ChromeCallbacks, zoomBar: HTMLElement) {
    this.cb = cb;
    const uid = 'mlv' + ++chromeSeq;

    this.header = el('header', 'mlv-header');
    this.header.setAttribute('data-layout', this.layout);
    // VIEW-12: the document's ONE h1 is the authored title, ellipsised; the whole title is on hover.
    this.title = add(this.header, el('h1', 'mlv-header__title', ''));

    this.toolbar = add(this.header, el('div', 'mlv-header__bar'));
    this.toolbar.setAttribute('role', 'toolbar');
    this.toolbar.setAttribute('aria-label', 'Diagram controls');
    this.toolbar.setAttribute('aria-orientation', 'horizontal');

    // Provenance: host · revision. Its dot turns amber only when a cited file is stale.
    this.provenance = el('button', 'mlv-chip mlv-header__prov') as HTMLButtonElement;
    this.provenance.type = 'button';
    add(this.provenance, el('span', 'mlv-header__dot')).setAttribute('aria-hidden', 'true');
    this.provHost = add(this.provenance, el('span', 'mlv-header__host', ''));
    this.provRev = add(this.provenance, el('span', 'mlv-header__rev', ''));
    on(this.provenance, 'click', (ev: MouseEvent) => cb.onAbout(ev.detail === 0));
    this.toolbar.appendChild(this.provenance);

    add(this.toolbar, el('span', 'mlv-header__spacer'));

    this.search = add(this.toolbar, el('div', 'mlv-search'));
    const glyph = add(this.search, uiIcon('search', 14));
    glyph.setAttribute('class', 'mlv-uicon mlv-search__glyph');
    const label = add(this.search, el('label', 'mlv-sr', 'Search steps, findings, IDs, or cited text'));
    label.htmlFor = uid + '-search-input';
    this.searchInput = add(this.search, el('input', 'mlv-input')) as HTMLInputElement;
    this.searchInput.id = uid + '-search-input';
    this.searchInput.type = 'search';
    this.searchInput.placeholder = 'Search steps and findings';
    this.searchInput.setAttribute('role', 'combobox');
    this.searchInput.setAttribute('aria-expanded', 'false');
    this.searchInput.setAttribute('aria-controls', uid + '-search-results');
    this.searchInput.autocomplete = 'off';
    this.results = add(this.search, el('ul', 'mlv-search__results'));
    this.results.id = uid + '-search-results';
    this.results.setAttribute('role', 'listbox');
    this.results.setAttribute('aria-label', 'Search results');
    this.results.hidden = true;
    on(this.searchInput, 'input', () => cb.onQuery(this.searchInput.value));
    on(this.searchInput, 'keydown', (ev: KeyboardEvent) => cb.onSearchKey(ev));
    // A collapsed field that opened for a query closes again when it is left empty.
    on(this.searchInput, 'blur', () => {
      if (!this.searchInput.value) this.setSearchOpen(false);
    });

    // Viewer M2 live fix: the find key for the platform (⌘F on macOS); it said Ctrl+K.
    this.searchBtn = iconButton('mlv-btn mlv-btn--icon mlv-header__searchbtn', 'Search (' + keyLabel('Mod+F') + ')');
    this.searchBtn.appendChild(uiIcon('search', 16));
    this.searchBtn.setAttribute('aria-controls', this.searchInput.id);
    on(this.searchBtn, 'click', () => cb.onSearchOpen());
    this.toolbar.appendChild(this.searchBtn);

    // The severity toggles, each counted once (the status bar no longer repeats them).
    for (const sev of SEVERITY_ORDER) {
      const b = el('button', 'mlv-chip mlv-chip--btn mlv-chip--sev') as HTMLButtonElement;
      b.type = 'button';
      b.setAttribute('aria-pressed', 'true');
      b.setAttribute('data-severity', sev);
      b.appendChild(severityGlyph(sev, 14, ''));
      add(b, el('span', 'mlv-chip__count', '0'));
      on(b, 'click', () => cb.onSeverity(sev));
      this.sevButtons.set(sev, b);
      this.toolbar.appendChild(b);
    }
    // Viewer M2 review (M2-INT-2): the unit of the toggles' numbers, on screen at every width. Each
    // toggle's own name already says it ("2 medium findings"), so this word is not read again.
    this.sevUnit = add(this.toolbar, el('span', 'mlv-header__unit', 'findings'));
    this.sevUnit.setAttribute('aria-hidden', 'true');
    this.sevUnit.hidden = true;

    // Viewer M2: how many claims are not observed, by unit, as a toggle that fades the observed
    // ones (through fill and stroke only, so their text stays readable). Hidden when every claim
    // is observed: an "all observed" mark would read as a check result.
    this.exceptionsBtn = el('button', 'mlv-chip mlv-chip--btn mlv-chip--exceptions') as HTMLButtonElement;
    this.exceptionsBtn.type = 'button';
    this.exceptionsBtn.setAttribute('aria-pressed', 'false');
    this.exceptionsBtn.hidden = true;
    on(this.exceptionsBtn, 'click', () => cb.onToggleExceptions(this.exceptionsBtn.getAttribute('aria-pressed') !== 'true'));
    this.toolbar.appendChild(this.exceptionsBtn);

    // Viewer M3: the review walk. A toggle: pressed while the walk runs. Like the revision chip it
    // is left out below 620 px and folds first when the row is short (the ... menu always has it,
    // and `r` starts it anywhere).
    this.reviewBtn = el('button', 'mlv-btn mlv-header__review') as HTMLButtonElement;
    this.reviewBtn.type = 'button';
    this.reviewBtn.setAttribute('aria-pressed', 'false');
    this.reviewBtn.appendChild(uiIcon('review', 14));
    add(this.reviewBtn, el('span', 'mlv-header__reviewlabel', 'Review'));
    this.reviewBtn.hidden = true;
    on(this.reviewBtn, 'click', () => cb.onReview());
    this.toolbar.appendChild(this.reviewBtn);

    this.more = new MoreMenu((id, byKeyboard) => this.pick(id, byKeyboard), () => cb.onMenuOpen());
    this.toolbar.appendChild(this.more.button);

    this.refineSlot = add(this.toolbar, el('span', 'mlv-header__refine'));

    // The status bar.
    this.status = el('footer', 'mlv-status');
    this.status.setAttribute('data-layout', this.layout);
    this.counts = add(this.status, el('span', 'mlv-status__counts', ''));
    this.coverage = el('button', 'mlv-status__coverage') as HTMLButtonElement;
    this.coverage.type = 'button';
    this.coverage.hidden = true;
    on(this.coverage, 'click', (ev: MouseEvent) => cb.onAbout(ev.detail === 0));
    this.status.appendChild(this.coverage);
    add(this.status, el('span', 'mlv-status__spacer'));
    this.fresh = add(this.status, el('span', 'mlv-status__freshness'));
    // The zoom: − 90% + (the readout is the canvas view's; the buttons are the status bar's).
    const zoomOut = iconButton('mlv-btn mlv-btn--icon mlv-zoom__btn', 'Zoom out');
    zoomOut.appendChild(uiIcon('minus', 12));
    on(zoomOut, 'click', () => cb.onZoom(-1));
    const zoomIn = iconButton('mlv-btn mlv-btn--icon mlv-zoom__btn', 'Zoom in');
    zoomIn.appendChild(uiIcon('plus', 12));
    on(zoomIn, 'click', () => cb.onZoom(1));
    zoomBar.insertBefore(zoomOut, zoomBar.firstChild);
    zoomBar.appendChild(zoomIn);
    this.status.appendChild(zoomBar);

    this.roving = new RovingGroup(this.toolbar);
  }

  destroy(): void {
    if (this.roving) this.roving.destroy();
    this.roving = null;
    this.more.destroy();
  }

  /** The Refine… button was rebuilt (`workflow.ts`): measure the row again and re-derive the tab stop. */
  syncRoving(): void {
    this.fitRow();
  }

  /**
   * Viewer M2: the panel's width decides which controls the header keeps. Viewer M2 review: any
   * change of width, even inside one layout, measures the row again (`fitRow`).
   */
  setWidth(width: number): HeaderLayout {
    const next = headerLayout(width);
    const changed = next !== this.layout;
    if (changed) {
      this.layout = next;
      this.header.setAttribute('data-layout', next);
      this.status.setAttribute('data-layout', next);
      this.syncSearch();
    }
    if (changed || width !== this.width) {
      this.width = width;
      this.fitRow();
    }
    return next;
  }

  /** How much the row is folded to fit (0: nothing beyond what the layout hides). */
  get headerFit(): number {
    return this.fitLevel;
  }

  get headerLayout(): HeaderLayout {
    return this.layout;
  }

  /**
   * Open (or close) the search field; at the full and wide widths it is always shown. The row is
   * measured again (an open field needs room) and the tab stop re-derived (the icon goes).
   */
  setSearchOpen(open: boolean): void {
    this.searchOpen = open;
    this.syncSearch();
    this.fitRow();
  }

  private syncSearch(): void {
    const collapsed = this.layout === 'mid' || this.layout === 'narrow';
    const open = !collapsed || this.searchOpen || !!this.searchInput.value;
    this.header.setAttribute('data-search', open ? 'open' : 'closed');
    this.searchBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
    this.syncControls();
  }

  /**
   * Viewer M2 review (M2R-1): the `hidden` attribute on every control the current shape leaves
   * out, so the roving tab stop, the ... menu and a test agree with what the stylesheet draws. The
   * revision chip: no document, below 620 px, or folded. The search icon: only at `mid` with the
   * field closed. "Not observed": nothing to count, or folded. Viewer M3: Review goes with the
   * revision chip (below 620 px, or folded), so the 541 px row keeps the M2 controls; the ... menu
   * always has it.
   */
  private syncControls(): void {
    this.provenance.hidden = !this.hasDocument || this.layout === 'narrow' || this.fitLevel >= 1;
    const searchFolded = (this.layout === 'mid' || this.layout === 'narrow') && this.header.getAttribute('data-search') !== 'open';
    this.searchBtn.hidden = !(this.layout === 'mid' && searchFolded);
    this.exceptionsBtn.hidden = !this.hasExceptions || this.fitLevel >= 2;
    this.reviewBtn.hidden = !this.hasDocument || this.layout === 'narrow' || this.fitLevel >= 1;
    for (const [sev, b] of this.sevButtons) b.hidden = !this.sevShown.has(sev) || this.fitLevel >= 4;
    this.sevUnit.hidden = this.sevShown.size === 0 || this.fitLevel >= 4;
    this.header.setAttribute('data-fit', String(this.fitLevel));
  }

  /**
   * Viewer M2 review (M2R-2, A11Y-8): fold the row until it fits the panel. Each step is measured
   * in place (the header's scroll width against its own width); nothing is painted in between, so
   * the folding never shows. Without a layout engine (jsdom, a detached root) nothing is folded.
   * Then the ... menu and the roving tab stop follow what is on the row.
   */
  private fitRow(): void {
    this.fitLevel = 0;
    this.syncControls();
    const width = this.header.clientWidth;
    // The severity toggles are never folded away while the field is closed: the menu has no copy.
    const max = this.header.getAttribute('data-search') === 'open' && (this.layout === 'mid' || this.layout === 'narrow') ? HEADER_FIT_MAX : HEADER_FIT_MAX - 1;
    if (width > 0) {
      while (this.fitLevel < max && this.header.scrollWidth > this.header.clientWidth) {
        this.fitLevel++;
        this.syncControls();
      }
    }
    this.updateMenu();
    if (this.roving) this.roving.sync();
  }

  /** The ... menu's items for the current state and what the row folded into it. */
  private updateMenu(): void {
    const s = this.state;
    if (!s) return;
    const exceptions = s.notObserved;
    const folded = this.hasExceptions && this.fitLevel >= 2;
    this.more.update({
      folded: {
        search: this.layout === 'narrow',
        about: this.layout === 'narrow' || this.fitLevel >= 1,
        exceptions: folded,
      },
      aboutLabel: this.lastAboutLabel,
      exceptionsLabel: this.hasExceptions ? notObservedText(exceptions) : '',
      exceptionsOn: s.exceptionsOn,
      legendOpen: s.legendOpen,
      flowOn: s.flowOn,
      phaseIndexShown: s.phaseIndexShown,
      phaseIndexUnavailable: s.phaseIndexUnavailable,
      overviewOpen: s.overviewOpen,
      railOpen: s.railOpen,
      walking: s.walking,
      railMode: s.railMode,
      hasSelection: s.hasSelection,
      canExport: !!s.graph,
    });
  }

  private pick(id: MoreItemId, byKeyboard: boolean): void {
    const cb = this.cb;
    if (id === 'search') cb.onSearchOpen();
    else if (id === 'about') cb.onAbout(byKeyboard);
    else if (id === 'exceptions') cb.onToggleExceptions(!(this.state && this.state.exceptionsOn));
    else if (id === 'legend') cb.onToggleLegend(!(this.state && this.state.legendOpen));
    else if (id === 'flow') cb.onToggleFlow(!(this.state && this.state.flowOn));
    else if (id === 'phaseindex') cb.onTogglePhaseIndex(!(this.state && this.state.phaseIndexShown));
    else if (id === 'overview') cb.onOverview();
    else if (id === 'rail') cb.onToggleRail();
    else if (id === 'fit') cb.onFitWhole();
    else if (id === 'zoomsel') cb.onZoomToSelection();
    else if (id === 'shortcuts') cb.onShortcuts();
    else if (id === 'review') cb.onReview();
    else cb.onExport(id);
  }

  update(s: ChromeState): void {
    this.state = s;
    const doc = s.document;
    const g = s.graph;
    this.renderHeader(s, doc);

    const exceptions = s.notObserved;
    const exceptionTotal = exceptions.steps + exceptions.connections + exceptions.findings;
    this.hasExceptions = !!g && exceptionTotal > 0;
    if (exceptionTotal > 0) {
      const text = notObservedText(exceptions);
      const open = text.indexOf(' (');
      clear(this.exceptionsBtn);
      this.exceptionsBtn.appendChild(uiIcon('notobserved', 14));
      // Viewer M2 review (M2-INT-2, A11Y-5): the count names its unit on screen at every width,
      // the owner's rule. The full row has room for the breakdown; a narrower one says "claims".
      if (this.layout === 'full' && open > 0) {
        add(this.exceptionsBtn, el('span', 'mlv-chip__lead', text.slice(0, open)));
        add(this.exceptionsBtn, el('span', 'mlv-chip__detail', text.slice(open)));
      } else {
        add(this.exceptionsBtn, el('span', 'mlv-chip__lead', notObservedLead(exceptions)));
      }
      this.exceptionsBtn.setAttribute('aria-label', text);
      this.exceptionsBtn.setAttribute('aria-pressed', s.exceptionsOn ? 'true' : 'false');
      this.exceptionsBtn.title = text + (s.exceptionsOn
        ? '. The observed claims are faded; press to show them again.'
        : '. Press to fade the observed claims so these stand out.');
    }

    for (const sev of SEVERITY_ORDER) {
      const b = this.sevButtons.get(sev)!;
      const active = s.filters.severities.indexOf(sev) >= 0;
      const n = s.visibleCounts[sev];
      b.setAttribute('aria-pressed', active ? 'true' : 'false');
      const count = b.querySelector('.mlv-chip__count');
      if (count) count.textContent = String(n);
      // A toggle for a severity with no findings would filter nothing; it is not drawn.
      if (g && n > 0) this.sevShown.add(sev);
      else this.sevShown.delete(sev);
      // Viewer M2: the number names its unit in the tooltip and the accessible name.
      b.title = plural(n, sev + ' finding', sev + ' findings') + (active ? '. Press to hide them.' : ', hidden. Press to show them.');
      b.setAttribute('aria-label', b.title);
    }
    // The unit after the toggles: "finding" only when the one number shown is 1.
    const shown = SEVERITY_ORDER.filter((sev) => this.sevShown.has(sev));
    this.sevUnit.textContent = shown.length === 1 && s.visibleCounts[shown[0]] === 1 ? 'finding' : 'findings';

    this.reviewBtn.setAttribute('aria-pressed', s.walking ? 'true' : 'false');
    this.reviewBtn.title = s.walking
      ? 'End the review walk (Escape). It remembers its place for this revision.'
      : 'Review the claims one by one (R): each is selected here and its cited lines are opened and highlighted in the editor beside. Focus stays here.';
    this.reviewBtn.setAttribute('aria-label', s.walking ? 'Review walk running; press to end it' : 'Review the claims');

    this.syncSearch();
    this.renderStatus(s);
    this.fitRow();
  }

  private renderHeader(s: ChromeState, doc: WorkflowDocument | null): void {
    if (!doc) {
      this.title.textContent = '';
      this.title.removeAttribute('title');
      this.hasDocument = false;
      return;
    }
    this.title.textContent = doc.title;
    this.title.title = doc.title;
    this.hasDocument = true;
    const host = doc.producer.host;
    const model = doc.producer.model ? ' (' + doc.producer.model + ')' : '';
    this.provHost.textContent = host + ' · ';
    this.provRev.textContent = doc.revision.id;
    const stale = !!s.freshness && s.freshness.state === 'stale';
    this.provenance.setAttribute('data-stale', stale ? 'true' : 'false');
    const published = doc.verification
      ? 'Published ' + doc.verification.publishedAt + ' with hashes of ' + plural(Object.keys(doc.verification.files || {}).length, 'file', 'files') + '.'
      : 'Published without source hashes.';
    const freshness = stale && s.freshness ? ' ' + s.freshness.text + '.' : '';
    this.provenance.title = 'Revision ' + doc.revision.id + ' by ' + host + model + '. ' + published + freshness + ' Show About: the request, coverage and provenance.';
    this.provenance.setAttribute('aria-label', 'Revision ' + doc.revision.id + ', ' + host + '.' + freshness + ' Show About this revision');
    this.lastAboutLabel = 'About revision ' + doc.revision.id + ' · ' + host;
  }

  private renderStatus(s: ChromeState): void {
    const g = s.graph;
    const doc = s.document;
    if (!g) {
      this.counts.textContent = 'Waiting for a workflow…';
      this.coverage.hidden = true;
      clear(this.fresh);
      return;
    }
    // Viewer M2: every count names its unit, and each is shown once.
    this.counts.textContent = plural(g.nodes.length, 'step', 'steps') + ' · ' + plural(g.edges.length, 'connection', 'connections');
    if (doc) {
      this.coverage.hidden = false;
      // Viewer M2 review (M2R-11): beside the code the item drops its "Coverage:" lead, so the
      // limitations keep their count and unit next to a stale-file warning; its name keeps it all.
      const full = coverageText(doc);
      this.coverage.textContent = this.layout === 'narrow' ? full.replace(/^Coverage: /, '') : full;
      this.coverage.setAttribute('aria-label', full);
      const status = doc.coverage.status;
      const meaning = status === 'scoped'
        ? '"scoped": the assistant lists no remaining work within the stated scope.'
        : '"partial": the assistant lists work that remains.';
      this.coverage.title = 'Coverage as the assistant recorded it. ' + meaning + ' Show About, where the limitations are listed.';
    } else this.coverage.hidden = true;

    // Freshness: a warning icon and words only for changed or missing files; muted text otherwise.
    clear(this.fresh);
    const f = s.freshness;
    // Viewer M2 review (M2R-11): a warning keeps its width; the coverage item gives way instead.
    this.fresh.setAttribute('data-stale', f && f.state === 'stale' ? 'true' : 'false');
    if (f && f.state === 'stale') {
      const item = add(this.fresh, el('span', 'mlv-status__fresh is-warn'));
      item.appendChild(uiIcon('warning', 12));
      add(item, el('span', '', f.text));
      item.title = f.title;
      item.setAttribute('data-freshness', 'stale');
    }
    if (s.checking) {
      const item = add(this.fresh, el('span', 'mlv-status__fresh is-checking', 'Checking source freshness…'));
      item.setAttribute('data-freshness', 'checking');
    } else if (f && f.state !== 'stale') {
      const item = add(this.fresh, el('span', 'mlv-status__fresh is-muted', f.text));
      item.title = f.title;
      item.setAttribute('data-freshness', f.state);
    }
  }
}
