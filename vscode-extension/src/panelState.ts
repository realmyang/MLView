/**
 * The two pieces of panel bookkeeping that are pure enough to test on their own:
 *
 *   1. `DeferredMessages` — the pre-handshake queue. `MlviewPanel.createOrShow` returns as soon
 *      as `webview.html` is assigned, long before the webview has booted, so anything posted
 *      straight after it lands ahead of the `ready` handshake and is lost. `onReady` rebuilds
 *      `init`, `restoreState`, `graph`, `stale` and the theme from the host's own state, so only
 *      the one-shot events need holding: a `revealNode` (Alt+M with the panel closed), a
 *      `revealIssue`, and the analysis spinner/banner.
 *   2. `preserveFromState` — the `ViewState` fields a `graph` message may carry back as
 *      `preserve` (CONTRACTS.md §4), so a re-analysis does not reset the viewport.
 */

import type { HostToUi, HostToUiType, Sel, ViewState, Viewport } from './protocol';

/** What `graph`'s `preserve` may carry (CONTRACTS.md §4). */
export interface PreserveState {
  viewport?: Viewport;
  selection?: Sel;
  collapsed?: string[];
}

/** Messages that must survive the pre-handshake window; everything else `onReady` rebuilds. */
const DEFERRABLE: ReadonlySet<HostToUiType> = new Set<HostToUiType>([
  'revealNode',
  'revealIssue',
  'analysisStarted',
  'analysisFailed',
  'setScope'
]);

/**
 * A reveal is only meaningful once a graph is on screen: `App.focusNode` needs the index. A
 * `setScope` is the same shape of thing — the viewer projects the document it is holding, so a
 * scope posted by `Alt+Shift+M` with the panel closed must arrive AFTER the graph it scopes.
 */
const NEEDS_GRAPH: ReadonlySet<HostToUiType> = new Set<HostToUiType>([
  'revealNode',
  'revealIssue',
  'setScope'
]);

/** A queue this long means something is wrong; keep the newest and drop the rest. */
const MAX_DEFERRED = 8;

export class DeferredMessages {
  private readonly queue: HostToUi[] = [];
  /** True once the webview has said `ready`. */
  private handshaken = false;
  /** True once a graph has reached a booted webview, so a node id can be resolved. */
  private graphDelivered = false;

  /** A `ready` handshake. A reload remounts the viewer, so the graph gate closes again. */
  onReady(): void {
    this.handshaken = true;
    this.graphDelivered = false;
  }

  /** A graph reached a booted webview; reveals may now be delivered. */
  onGraphDelivered(): void {
    if (this.handshaken) {
      this.graphDelivered = true;
    }
  }

  shouldDefer(type: HostToUiType): boolean {
    return DEFERRABLE.has(type) && !this.canDeliver(type);
  }

  canDeliver(type: HostToUiType): boolean {
    if (!this.handshaken) {
      return false;
    }
    return NEEDS_GRAPH.has(type) ? this.graphDelivered : true;
  }

  add(message: HostToUi): void {
    // Latest wins per type: two Alt+M presses before the webview boots reveal the second node.
    for (let i = this.queue.length - 1; i >= 0; i -= 1) {
      const entry = this.queue[i];
      if (entry && entry.type === message.type) {
        this.queue.splice(i, 1);
      }
    }
    this.queue.push(message);
    while (this.queue.length > MAX_DEFERRED) {
      this.queue.shift();
    }
  }

  /** Forget a queued message whose run has concluded (a graph or a failure arrived for it). */
  drop(type: HostToUiType, requestId?: string): void {
    for (let i = this.queue.length - 1; i >= 0; i -= 1) {
      const entry = this.queue[i];
      if (!entry || entry.type !== type) {
        continue;
      }
      const id = (entry as { requestId?: string }).requestId;
      if (requestId === undefined || id === requestId) {
        this.queue.splice(i, 1);
      }
    }
  }

  /** Everything the webview can now act on, in the order it was posted, removed from the queue. */
  take(): HostToUi[] {
    const ready = this.queue.filter((m) => this.canDeliver(m.type));
    for (const message of ready) {
      const at = this.queue.indexOf(message);
      if (at >= 0) {
        this.queue.splice(at, 1);
      }
    }
    return ready;
  }

  get pending(): readonly HostToUi[] {
    return this.queue;
  }
}

function isFinitePoint(value: unknown): value is Viewport {
  if (typeof value !== 'object' || value === null) {
    return false;
  }
  const raw = value as Record<string, unknown>;
  return ['x', 'y', 'zoom'].every((key) => Number.isFinite(raw[key]));
}

function isSelection(value: unknown): value is Sel {
  if (typeof value !== 'object' || value === null) {
    return false;
  }
  const raw = value as Record<string, unknown>;
  return typeof raw['id'] === 'string' && typeof raw['kind'] === 'string';
}

/** The `ViewState` fields the `graph` message is allowed to carry back as `preserve`. */
export function preserveFromState(state: ViewState | unknown): PreserveState | undefined {
  if (typeof state !== 'object' || state === null) {
    return undefined;
  }
  const raw = state as Record<string, unknown>;
  const out: PreserveState = {};
  const viewport = raw['viewport'];
  if (isFinitePoint(viewport)) {
    out.viewport = { x: viewport.x, y: viewport.y, zoom: viewport.zoom };
  }
  const selection = raw['selection'];
  if (isSelection(selection)) {
    out.selection = { kind: selection.kind, id: selection.id };
  }
  const collapsed = raw['collapsed'];
  if (Array.isArray(collapsed)) {
    out.collapsed = collapsed.filter((id): id is string => typeof id === 'string');
  }
  return out.viewport || out.selection || out.collapsed ? out : undefined;
}
