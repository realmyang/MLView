/**
 * The review walk (viewer M3, roadmap step 11): claim by claim through the displayed revision,
 * each claim selected and revealed on the canvas, read in the Selection pane, and its cited lines
 * shown and highlighted in the editor beside while the keyboard stays on the diagram.
 *
 * What it does on each step:
 *   - the canvas selects the claim and brings it into view above the bottom sheet;
 *   - the Selection pane shows it (a collapsed sheet opens);
 *   - about 150 ms after the reader stops moving (`WALK_OPEN_DEBOUNCE_MS`) it asks the host to open
 *     the claim's current quote beside the panel (`openLocation` with `walk: true`, a `seq` that
 *     rises with every numbered open of this page, and a request id), focus kept here. The host
 *     answers once: done, blocked (the reason, nothing opened, no notification), cancelled (a later
 *     open overtook it) or failed. Only the answer to the latest open is shown. A claim with
 *     nothing to open sends `walk: clear`, so the editor never keeps an earlier claim's highlight;
 *   - a live region announces "Claim 3 of 16, not observed: Step …, inferred.".
 *
 * Owner decisions (M3): each step opens AUTOMATICALLY with preserveFocus; the walk records NO
 * verdict and no "checked" mark, only its place, per revision, in the webview's saved view state
 * (`ViewState.walk`). Nothing is written to evals or decisions. Opening, filtering and walking
 * never call a model.
 */

import { locationFrame } from './actions.js';
import { applyWalkMark } from '../ui/selection.js';
import {
  changedOffered,
  claimBasis,
  claimLocs,
  claimOrder,
  FILTER_LABEL,
  filterClaims,
  filterCounts,
  isNotObserved,
  offeredFilters,
  positionFor,
  sameClaim,
  walkAnnouncement,
  walkLocText,
  WALK_FILTERS,
} from '../walk.js';
import { STALE_TEXT } from '../freshness.js';
import type { App } from '../app.js';
import type { GraphIndex } from '../layout/model.js';
import type { Claim, WalkFilter, WalkOpenStatus } from '../walk.js';
import type { ActionResult, Loc, Sel, WalkViewState } from '../types.js';

/** The pause after the last step before the walk asks the host to open the cited lines. */
export const WALK_OPEN_DEBOUNCE_MS = 150;

/** A saved quote index is never trusted past this (a claim cites at most 100 evidence ids). */
const MAX_QUOTE = 100;

/** A saved walk, validated field by field (saved state comes from the webview's storage). */
export function sanitizeWalk(value: unknown): WalkViewState | null {
  if (!value || typeof value !== 'object') return null;
  const record = value as Record<string, unknown>;
  const filter = typeof record.filter === 'string' && (WALK_FILTERS as readonly string[]).indexOf(record.filter) >= 0 ? (record.filter as WalkFilter) : null;
  const claim = record.claim as { kind?: unknown; id?: unknown } | null | undefined;
  if (!filter || !claim || typeof claim !== 'object') return null;
  if ((claim.kind !== 'node' && claim.kind !== 'edge' && claim.kind !== 'issue') || typeof claim.id !== 'string' || !claim.id) return null;
  const out: WalkViewState = { filter, claim: { kind: claim.kind, id: claim.id } };
  const quote = record.quote;
  if (typeof quote === 'number' && Number.isInteger(quote) && quote > 0 && quote < MAX_QUOTE) out.quote = quote;
  if (record.active === true) out.active = true;
  return out;
}

export class ReviewWalk {
  /** The walk is running: the bar is shown and the walk keys answer. */
  active = false;
  filter: WalkFilter = 'notObserved';
  /** The claims of `filter`, in the drawn order, and the walk's place among them. */
  list: Claim[] = [];
  position = -1;
  /** The current claim's quote the editor is asked for. */
  quote = 0;
  status: WalkOpenStatus = { state: 'none', quote: 0, quotes: 0 };

  private app: App;
  private order: Claim[] = [];
  private orderIndex: GraphIndex | null = null;
  /** Every numbered open of this page; the host drops one that is not above the last it saw. */
  private seq = 0;
  /** The `seq` of the walk's latest open: only its answer is shown. */
  private latestSeq = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  /** The place the walk resumes from, for `revision` (kept after the walk ends). */
  private remembered: { revision: string; state: WalkViewState } | null = null;
  /** A remount's saved place, applied by the first document of the revision it was saved for. */
  private restored: { revision: string; state: WalkViewState } | null = null;
  /** While the walk itself selects, the App's selection hook must not treat it as the reader's move. */
  selecting = false;

  constructor(app: App) {
    this.app = app;
  }

  /* ── the claims ────────────────────────────────────────────────────── */

  private index(): GraphIndex | null {
    return this.app.index;
  }

  /** The drawn order for the current document, computed once per index. */
  claims(): Claim[] {
    const index = this.index();
    if (!index) return [];
    if (index !== this.orderIndex) {
      this.order = claimOrder(index);
      this.orderIndex = index;
    }
    return this.order;
  }

  private isStale = (file: string): boolean => !!this.app.freshness.reasonOf(file);

  changedOffered(): boolean {
    return changedOffered(this.app.freshness.list().map((file) => file.reason));
  }

  counts(): Record<WalkFilter, number> {
    const index = this.index();
    if (!index) return { notObserved: 0, findings: 0, changed: 0, all: 0 };
    return filterCounts(this.claims(), index, this.isStale);
  }

  offered(): WalkFilter[] {
    return offeredFilters(this.counts(), this.changedOffered());
  }

  private listFor(filter: WalkFilter): Claim[] {
    const index = this.index();
    return index ? filterClaims(this.claims(), filter, index, this.isStale) : [];
  }

  /** The claim the walk is on, or null. */
  current(): Claim | null {
    return this.position >= 0 && this.position < this.list.length ? this.list[this.position] : null;
  }

  private currentLocs(): Loc[] {
    const index = this.index();
    const claim = this.current();
    return index && claim ? claimLocs(index, claim) : [];
  }

  /* ── starting, stepping, ending ────────────────────────────────────── */

  /**
   * Start the walk, or carry on with it (`r`, Review, the ⋯ menu; `u` asks for Not observed and the
   * stale notice for Changed files). Without a filter it resumes the place remembered for this
   * revision, else starts on Not observed (All when no claim is marked inferred or unresolved).
   * A filter asked for that holds no claim is said, and nothing starts. True when it runs.
   */
  start(filter?: WalkFilter): boolean {
    const index = this.index();
    if (!index) return false;
    const offered = this.offered();
    const saved = this.remembered && this.remembered.revision === this.app.workflowRevision ? this.remembered.state : null;
    let next: WalkFilter;
    if (filter) {
      if (offered.indexOf(filter) < 0) {
        this.app.announce(filter === 'notObserved'
          ? 'No claim is marked inferred or unresolved in this revision.'
          : filter === 'changed' ? 'No claim cites a file that changed or went missing.' : 'No claims to walk with that filter.');
        return false;
      }
      next = filter;
    } else {
      next = saved && offered.indexOf(saved.filter) >= 0 ? saved.filter : offered.indexOf('notObserved') >= 0 ? 'notObserved' : 'all';
    }
    const list = this.listFor(next);
    if (!list.length) {
      this.app.announce('This revision has no claims to walk.');
      return false;
    }
    const wasActive = this.active;
    // The walk reads each claim in the Selection pane: a docked rail the reader hid is shown again.
    if (!wasActive) this.app.openRailForWalk();
    this.filter = next;
    this.list = list;
    const anchor = saved ? saved.claim : null;
    this.position = Math.max(0, positionFor(list, anchor, this.claims()));
    this.quote = saved && sameClaim(saved.claim, this.current()) ? Math.min(saved.quote || 0, Math.max(0, this.currentLocs().length - 1)) : 0;
    this.active = true;
    if (!wasActive) this.app.onWalkShown(true);
    this.show(true);
    return true;
  }

  /** End the walk (Escape, Exit, Review again). Its place is kept for this revision. */
  stop(announce = true): boolean {
    if (!this.active) return false;
    this.active = false;
    this.cancelTimer();
    this.app.bridge.post({ v: 1, type: 'walk', state: 'end' });
    this.remember();
    this.app.onWalkShown(false);
    if (announce) this.app.announce('Review ended. r resumes it here.');
    this.app.saveSoon();
    return true;
  }

  toggle(): void {
    if (this.active) this.stop();
    else this.start();
  }

  /** j / k, ↓ / ↑: the next or previous claim. At either end the walk stays and says so. */
  step(delta: number): boolean {
    if (!this.active || !this.list.length) return false;
    const next = Math.max(0, Math.min(this.list.length - 1, this.position + delta));
    if (next === this.position) {
      this.app.announce(delta > 0
        ? 'Claim ' + this.list.length + ' of ' + this.list.length + ' is the last one.'
        : 'Claim 1 of ' + this.list.length + ' is the first one.');
      return true;
    }
    this.position = next;
    this.quote = 0;
    this.show(true);
    return true;
  }

  /** [ and ]: the current claim's previous or next quote, opened beside the panel. */
  stepQuote(delta: number): boolean {
    if (!this.active) return false;
    const locs = this.currentLocs();
    if (locs.length < 2) {
      this.app.announce(locs.length ? 'This claim has one quote.' : 'This claim cites no lines.');
      return true;
    }
    const next = Math.max(0, Math.min(locs.length - 1, this.quote + delta));
    if (next === this.quote) {
      this.app.announce(delta > 0 ? 'Quote ' + locs.length + ' of ' + locs.length + ' is the last one.' : 'Quote 1 of ' + locs.length + ' is the first one.');
      return true;
    }
    this.quote = next;
    this.app.announce('Quote ' + (next + 1) + ' of ' + locs.length + ': ' + walkLocText(locs[next]) + '.');
    this.scheduleOpen();
    this.remember();
    // The pane brings the marked quote into view (live: a second quote sat below the fold).
    this.render(true);
    this.app.saveSoon();
    return true;
  }

  /**
   * `u` / `U` (not observed) and, while walking, `n` / `p` (findings): the next or previous claim of
   * that kind after the current one in the drawn order, wrapping as `n` and `p` always have. The
   * filter stays when it holds that claim; otherwise it becomes Not observed or Findings. `u`
   * starts the walk when it is not running.
   */
  jump(kind: 'notObserved' | 'findings', backwards: boolean): boolean {
    const index = this.index();
    if (!index) return false;
    const filter: WalkFilter = kind;
    if (!this.active) return this.start(filter);
    const order = this.claims();
    const matches = (claim: Claim): boolean => (kind === 'findings' ? claim.kind === 'issue' : isNotObserved(claimBasis(index, claim)));
    const here = order.findIndex((claim) => sameClaim(claim, this.current()));
    let target: Claim | null = null;
    for (let step = 1; step <= order.length; step++) {
      const at = ((here < 0 ? (backwards ? 0 : -1) : here) + (backwards ? -step : step) + order.length * 2) % order.length;
      if (matches(order[at])) {
        target = order[at];
        break;
      }
    }
    if (!target) {
      this.app.announce(kind === 'findings' ? 'This revision has no findings.' : 'No claim is marked inferred or unresolved in this revision.');
      return true;
    }
    if (!this.list.some((claim) => sameClaim(claim, target))) {
      this.filter = filter;
      this.list = this.listFor(filter);
    }
    this.position = Math.max(0, this.list.findIndex((claim) => sameClaim(claim, target)));
    this.quote = 0;
    this.show(true);
    return true;
  }

  /** A filter chosen in the bar. The walk keeps its claim when the new filter holds it. */
  setFilter(filter: WalkFilter): void {
    if (!this.active || this.offered().indexOf(filter) < 0) return;
    const before = this.current();
    this.filter = filter;
    this.list = this.listFor(filter);
    this.position = Math.max(0, positionFor(this.list, before, this.claims()));
    const same = sameClaim(before, this.current());
    if (!same) this.quote = 0;
    this.show(!same);
    this.app.announce(FILTER_LABEL[filter] + ': ' + this.list.length + (this.list.length === 1 ? ' claim. ' : ' claims. ') + this.announcement());
  }

  /** Enter (and an Open link of the current claim): open the current quote again, now. */
  reopen(focusEditor: boolean): boolean {
    if (!this.active || !this.current()) return false;
    this.cancelTimer();
    this.sendOpen(focusEditor);
    return true;
  }

  /**
   * An Open link in the Selection pane while the walk shows that claim: the walk opens it as its
   * own quote (no notification when it is blocked; the reason goes to the bar and the pane).
   */
  openQuote(loc: Loc, focusEditor: boolean): boolean {
    if (!this.active || !loc.evidenceId) return false;
    const at = this.currentLocs().findIndex((item) => item.evidenceId === loc.evidenceId);
    if (at < 0) return false;
    this.quote = at;
    this.cancelTimer();
    this.sendOpen(focusEditor);
    this.remember();
    return true;
  }

  /**
   * The reader selected something else (a click, an arrow, a search hit, a link) while walking.
   * When the walk's list holds it, the walk follows: its place moves there, nothing is opened (a
   * click selects only; Enter opens), and any highlight of the claim it left is cleared.
   */
  followSelection(sel: Sel | null): void {
    if (!this.active || this.selecting || !sel) return;
    const at = this.list.findIndex((claim) => sameClaim(claim, sel));
    if (at < 0 || at === this.position) return;
    this.position = at;
    this.quote = 0;
    this.cancelTimer();
    this.app.bridge.post({ v: 1, type: 'walk', state: 'clear' });
    this.status = this.statusFor('idle');
    this.remember();
    this.render();
  }

  /* ── host answers and document changes ─────────────────────────────── */

  /** A new document (`setWorkflow`). Another revision ends the walk and starts fresh. */
  onDocument(revisionChanged: boolean): void {
    const revision = this.app.workflowRevision;
    if (revisionChanged) {
      if (this.active) this.stop(false);
      this.remembered = null;
      this.list = [];
      this.position = -1;
    }
    // A remount brings the saved place back for the revision it was saved with.
    const restored = this.restored;
    this.restored = null;
    if (restored && restored.revision === revision && !this.remembered) {
      this.remembered = { revision, state: restored.state };
      if (restored.state.active) this.resume();
      return;
    }
    if (!this.active) return;
    // The same revision again (a refresh): the claims are the same; keep the place.
    const before = this.current();
    this.list = this.listFor(this.filter);
    this.position = Math.max(0, positionFor(this.list, before, this.claims()));
    this.render();
  }

  /**
   * A remounted page brings back a walk that was running: the bar and the selection, without
   * asking the host to open anything (it still shows the last open); Enter opens it again.
   */
  private resume(): void {
    const saved = this.remembered ? this.remembered.state : null;
    if (!saved) return;
    const offered = this.offered();
    this.filter = offered.indexOf(saved.filter) >= 0 ? saved.filter : 'all';
    this.list = this.listFor(this.filter);
    if (!this.list.length) return;
    this.position = Math.max(0, positionFor(this.list, saved.claim, this.claims()));
    this.quote = sameClaim(saved.claim, this.current()) ? Math.min(saved.quote || 0, Math.max(0, this.currentLocs().length - 1)) : 0;
    this.active = true;
    this.app.onWalkShown(true);
    this.show(false);
  }

  /** The host's stale files changed: the Changed files filter follows; the walk keeps its claim. */
  onStale(): void {
    if (!this.active) return;
    if (this.offered().indexOf(this.filter) < 0) this.filter = 'all';
    const before = this.current();
    this.list = this.listFor(this.filter);
    this.position = Math.max(0, positionFor(this.list, before, this.claims()));
    this.render();
  }

  private onResult(result: ActionResult, seq: number): void {
    if (!this.active || seq !== this.latestSeq || result.outcome === 'cancelled') return;
    if (result.outcome === 'done') this.status = this.statusFor('done');
    else {
      const message = result.message || (result.outcome === 'blocked' ? 'Not opened.' : 'VS Code could not show the file.');
      this.status = this.statusFor(result.outcome, message);
      this.app.announce((result.outcome === 'blocked' ? 'Not opened: ' : 'Failed: ') + message);
    }
    this.render();
  }

  /* ── opening ───────────────────────────────────────────────────────── */

  private cancelTimer(): void {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
  }

  private statusFor(state: WalkOpenStatus['state'], message?: string): WalkOpenStatus {
    const locs = this.currentLocs();
    const quote = Math.min(this.quote, Math.max(0, locs.length - 1));
    const out: WalkOpenStatus = { state, quote, quotes: locs.length };
    if (locs[quote] && state !== 'none' && state !== 'unavailable') out.loc = locs[quote];
    if (message) out.message = message;
    return out;
  }

  /**
   * The viewer's own reason for a quote whose file the host already reported stale, shown at once;
   * the host's answer (it never opens such a file) replaces it when it comes.
   */
  private localBlock(loc: Loc): string | null {
    const reason = loc.evidenceId ? this.app.freshness.reasonOf(loc.file) : undefined;
    if (!reason) return null;
    return loc.file + ': ' + STALE_TEXT[reason] + '; not opened.';
  }

  /** After the pause, ask the host for the current quote (or, with none, to clear the highlight). */
  private scheduleOpen(): void {
    this.cancelTimer();
    const locs = this.currentLocs();
    const loc = locs[Math.min(this.quote, locs.length - 1)];
    if (!locs.length || !loc) this.status = this.statusFor('none');
    else if (!this.app.caps.canOpenSource) this.status = this.statusFor('unavailable');
    else {
      const local = this.localBlock(loc);
      this.status = local ? this.statusFor('blocked', local) : this.statusFor('opening');
    }
    if (this.status.state === 'unavailable') return;
    this.timer = setTimeout(() => {
      this.timer = null;
      this.sendOpen(false);
    }, WALK_OPEN_DEBOUNCE_MS);
  }

  /** Waiting to ask the host (tests flush it instead of sleeping). */
  get pendingOpen(): boolean {
    return this.timer !== null;
  }

  /** Send the pending open now (Enter does; a test may). */
  flushOpen(): void {
    if (this.timer === null) return;
    this.cancelTimer();
    this.sendOpen(false);
  }

  private sendOpen(focusEditor: boolean): void {
    if (!this.active) return;
    const locs = this.currentLocs();
    const loc = locs[Math.min(this.quote, locs.length - 1)];
    if (!loc) {
      this.app.bridge.post({ v: 1, type: 'walk', state: 'clear' });
      this.status = this.statusFor('none');
      this.render();
      return;
    }
    if (!this.app.caps.canOpenSource) {
      this.status = this.statusFor('unavailable');
      this.render();
      return;
    }
    const seq = ++this.seq;
    this.latestSeq = seq;
    // VS Code may tear down a hidden webview when the active editor changes: save first, as every
    // open does (app/actions.ts).
    this.remember();
    this.app.bridge.saveState(this.app.getState());
    const frame = locationFrame(loc);
    frame.walk = true;
    frame.seq = seq;
    if (focusEditor) frame.focus = true;
    this.app.postRequest(frame, (result) => this.onResult(result, seq));
    const local = this.localBlock(loc);
    this.status = local ? this.statusFor('blocked', local) : this.statusFor('opening');
    this.render();
  }

  /* ── showing ───────────────────────────────────────────────────────── */

  /** Select and reveal the current claim, announce it, and (`open`) schedule its open. */
  private show(open: boolean): void {
    const claim = this.current();
    if (!claim) return;
    this.selecting = true;
    try {
      this.app.showWalkClaim(claim);
    } finally {
      this.selecting = false;
    }
    if (open) this.scheduleOpen();
    else this.status = this.statusFor(this.currentLocs().length ? (this.app.caps.canOpenSource ? 'idle' : 'unavailable') : 'none');
    this.remember();
    this.render();
    this.app.announce(this.announcement());
    this.app.saveSoon();
  }

  private announcement(): string {
    const index = this.index();
    const claim = this.current();
    return index && claim ? walkAnnouncement(this.position, this.list.length, this.filter, index, claim) : '';
  }

  /** Repaint the bar, the header's Review state and the pane's quote mark (`reveal`: scroll to it). */
  render(reveal = false): void {
    this.app.renderWalkBar();
    applyWalkMark(this.app.rail.root, this.paneMark(), reveal);
  }

  /** The Selection pane's mark for the walk's quote, while the pane shows the walk's claim. */
  paneMark(): { quote: number; status: WalkOpenStatus } | null {
    if (!this.active) return null;
    const claim = this.current();
    if (!claim || !sameClaim(claim, this.app.selection)) return null;
    return { quote: this.status.quote, status: this.status };
  }

  /* ── saved place ───────────────────────────────────────────────────── */

  private remember(): void {
    const revision = this.app.workflowRevision;
    const claim = this.current();
    if (!revision || !claim) return;
    const state: WalkViewState = { filter: this.filter, claim: { kind: claim.kind, id: claim.id } };
    if (this.quote > 0) state.quote = this.quote;
    if (this.active) state.active = true;
    this.remembered = { revision, state };
  }

  /** `ViewState.walk`: the place for the displayed revision, or undefined before the first walk. */
  viewState(): WalkViewState | undefined {
    const revision = this.app.workflowRevision;
    if (!this.remembered || !revision || this.remembered.revision !== revision) return undefined;
    const state: WalkViewState = { ...this.remembered.state, claim: { ...this.remembered.state.claim } };
    if (this.active) state.active = true;
    else delete state.active;
    return state;
  }

  /** A remount's saved walk, for the revision it was saved with (applied by `onDocument`). */
  restore(revision: string, value: unknown): void {
    const state = sanitizeWalk(value);
    this.restored = state ? { revision, state } : null;
  }

  destroy(): void {
    this.cancelTimer();
  }
}
