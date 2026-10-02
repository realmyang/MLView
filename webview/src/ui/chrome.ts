/**
 * The header row and the status bar (viewer M2), plus the search box inside the header.
 *
 * One header row of about 36 px replaces the brand row, the 21-control toolbar, the phase chip row
 * and the authored header. In order:
 *
 *   title · provenance chip (host · revision) · search · severity toggles · "N not observed" ·
 *   ... menu · Refine…
 *
 * The row never wraps. How much of it shows depends on the panel's width (`headerLayout`):
 *
 *   full   >= 1200 px  everything; the "not observed" breakdown in brackets
 *   wide   >= 1000 px  the breakdown folds into the tooltip
 *   mid    >=  620 px  search becomes an icon that opens the field; the chip shows the revision only
 *   narrow  <  620 px  the title, the severity toggles, "not observed", ... and Refine… stay;
 *                      search and the revision move into the ... menu
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
  /** The provenance chip and the status bar's coverage item: the request and coverage details. */
  onDetails(): void;
  onZoom(dir: number): void;
  onToggleLegend(next: boolean): void;
  onToggleFlow(next: boolean): void;
  /** `collapsed`: the minimap's new state (VIEW-12: the keyboard's way to it). */
  onToggleMinimap(collapsed: boolean): void;
  onToggleRail(): void;
  onFitWhole(): void;
  onZoomToSelection(): void;
  onExport(action: 'svg' | 'png' | 'copy-svg'): void;
  onShortcuts(): void;
  /** The ... menu is opening: repaint, so its checkboxes and disabled items are current. */
  onMenuOpen(): void;
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
  minimapCollapsed: boolean;
  railOpen: boolean;
  /** The status bar's freshness item, or null before a document arrives. */
  freshness: FreshnessStatus | null;
  /** The host is checking a change on disk. */
  checking: boolean;
  /** Viewer M2: the claims in view that are not observed, by unit. */
  notObserved: NotObservedCounts;
  exceptionsOn: boolean;
  /** Whether the request and coverage details are open. */
  detailsOpen: boolean;
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
  private exceptionsBtn: HTMLButtonElement;
  private counts: HTMLElement;
  private coverage: HTMLButtonElement;
  private fresh: HTMLElement;
  private roving: RovingGroup | null = null;
  private cb: ChromeCallbacks;
  private layout: HeaderLayout = 'full';
  private searchOpen = false;
  private lastDetailsLabel = 'Request and coverage details';
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
    this.provenance.setAttribute('aria-haspopup', 'dialog');
    add(this.provenance, el('span', 'mlv-header__dot')).setAttribute('aria-hidden', 'true');
    this.provHost = add(this.provenance, el('span', 'mlv-header__host', ''));
    this.provRev = add(this.provenance, el('span', 'mlv-header__rev', ''));
    on(this.provenance, 'click', () => cb.onDetails());
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

    this.searchBtn = iconButton('mlv-btn mlv-btn--icon mlv-header__searchbtn', 'Search (Ctrl+K)');
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

    // Viewer M2: how many claims are not observed, by unit, as a toggle that fades the observed
    // ones (through fill and stroke only, so their text stays readable). Hidden when every claim
    // is observed: an "all observed" mark would read as a check result.
    this.exceptionsBtn = el('button', 'mlv-chip mlv-chip--btn mlv-chip--exceptions') as HTMLButtonElement;
    this.exceptionsBtn.type = 'button';
    this.exceptionsBtn.setAttribute('aria-pressed', 'false');
    this.exceptionsBtn.hidden = true;
    on(this.exceptionsBtn, 'click', () => cb.onToggleExceptions(this.exceptionsBtn.getAttribute('aria-pressed') !== 'true'));
    this.toolbar.appendChild(this.exceptionsBtn);

    this.more = new MoreMenu((id) => this.pick(id), () => cb.onMenuOpen());
    this.toolbar.appendChild(this.more.button);

    this.refineSlot = add(this.toolbar, el('span', 'mlv-header__refine'));

    // The status bar.
    this.status = el('footer', 'mlv-status');
    this.status.setAttribute('data-layout', this.layout);
    this.counts = add(this.status, el('span', 'mlv-status__counts', ''));
    this.coverage = el('button', 'mlv-status__coverage') as HTMLButtonElement;
    this.coverage.type = 'button';
    this.coverage.setAttribute('aria-haspopup', 'dialog');
    this.coverage.hidden = true;
    on(this.coverage, 'click', () => cb.onDetails());
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

  /** The tab stop after the Refine… button was rebuilt (`workflow.ts`). */
  syncRoving(): void {
    if (this.roving) this.roving.sync();
  }

  /** Viewer M2: the panel's width decides which controls the header keeps. */
  setWidth(width: number): HeaderLayout {
    const next = headerLayout(width);
    if (next !== this.layout) {
      this.layout = next;
      this.header.setAttribute('data-layout', next);
      this.status.setAttribute('data-layout', next);
      this.syncSearch();
      this.syncRoving();
    }
    return next;
  }

  get headerLayout(): HeaderLayout {
    return this.layout;
  }

  /** Open (or close) the search field; at the full and wide widths it is always shown. */
  setSearchOpen(open: boolean): void {
    this.searchOpen = open;
    this.syncSearch();
  }

  private syncSearch(): void {
    const collapsed = this.layout === 'mid' || this.layout === 'narrow';
    const open = !collapsed || this.searchOpen || !!this.searchInput.value;
    this.header.setAttribute('data-search', open ? 'open' : 'closed');
    this.searchBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
  }

  private pick(id: MoreItemId): void {
    const cb = this.cb;
    if (id === 'search') cb.onSearchOpen();
    else if (id === 'details') cb.onDetails();
    else if (id === 'legend') cb.onToggleLegend(!(this.state && this.state.legendOpen));
    else if (id === 'flow') cb.onToggleFlow(!(this.state && this.state.flowOn));
    else if (id === 'minimap') cb.onToggleMinimap(!(this.state && this.state.minimapCollapsed));
    else if (id === 'rail') cb.onToggleRail();
    else if (id === 'fit') cb.onFitWhole();
    else if (id === 'zoomsel') cb.onZoomToSelection();
    else if (id === 'shortcuts') cb.onShortcuts();
    else cb.onExport(id);
  }

  update(s: ChromeState): void {
    this.state = s;
    const doc = s.document;
    const g = s.graph;
    this.renderHeader(s, doc);

    const exceptions = s.notObserved;
    const exceptionTotal = exceptions.steps + exceptions.connections + exceptions.findings;
    this.exceptionsBtn.hidden = !g || exceptionTotal === 0;
    if (exceptionTotal > 0) {
      const text = notObservedText(exceptions);
      const open = text.indexOf(' (');
      clear(this.exceptionsBtn);
      this.exceptionsBtn.appendChild(uiIcon('notobserved', 14));
      add(this.exceptionsBtn, el('span', 'mlv-chip__lead', open > 0 ? text.slice(0, open) : text));
      if (open > 0) add(this.exceptionsBtn, el('span', 'mlv-chip__detail', text.slice(open)));
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
      b.hidden = !g || n === 0;
      // Viewer M2: the number names its unit in the tooltip and the accessible name.
      b.title = plural(n, sev + ' finding', sev + ' findings') + (active ? '. Press to hide them.' : ', hidden. Press to show them.');
      b.setAttribute('aria-label', b.title);
    }

    this.more.update({
      narrow: this.layout === 'narrow',
      detailsLabel: this.lastDetailsLabel,
      legendOpen: s.legendOpen,
      flowOn: s.flowOn,
      minimapShown: !s.minimapCollapsed,
      railOpen: s.railOpen,
      hasSelection: s.hasSelection,
      canExport: !!g,
    });
    this.syncSearch();
    this.renderStatus(s);
    if (this.roving) this.roving.sync();
  }

  private renderHeader(s: ChromeState, doc: WorkflowDocument | null): void {
    if (!doc) {
      this.title.textContent = '';
      this.title.removeAttribute('title');
      this.provenance.hidden = true;
      return;
    }
    this.title.textContent = doc.title;
    this.title.title = doc.title;
    this.provenance.hidden = false;
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
    this.provenance.title = 'Revision ' + doc.revision.id + ' by ' + host + model + '. ' + published + freshness + ' Open the request and coverage details.';
    this.provenance.setAttribute('aria-label', 'Revision ' + doc.revision.id + ', ' + host + freshness + ' Show the request and coverage details');
    this.provenance.setAttribute('aria-expanded', s.detailsOpen ? 'true' : 'false');
    this.lastDetailsLabel = 'Revision ' + doc.revision.id + ' · ' + host;
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
      this.coverage.textContent = coverageText(doc);
      const status = doc.coverage.status;
      const meaning = status === 'scoped'
        ? '"scoped": the assistant lists no remaining work within the stated scope.'
        : '"partial": the assistant lists work that remains.';
      this.coverage.title = 'Coverage as the assistant recorded it. ' + meaning + ' Open the request, coverage and limitations.';
      this.coverage.setAttribute('aria-expanded', s.detailsOpen ? 'true' : 'false');
    } else this.coverage.hidden = true;

    // Freshness: a warning icon and words only for changed or missing files; muted text otherwise.
    clear(this.fresh);
    const f = s.freshness;
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
