/**
 * VIEW-08, the viewer half — the READER of the diff overlay document.
 *
 * `mlview diff BASE.json HEAD.json` writes a SEPARATE document (CONTRACTS
 * §11.38): `kind: "mlview-diff"`, its own `diffVersion`, keyed on the same §0
 * stable node / edge / issue ids as the graph it describes. The graph schema did
 * not move, `contracts/graph.sample.json` is untouched, and an unscoped
 * `analyze` still emits exactly the bytes it always emitted — so this module can
 * only ever ADD decoration to a document that renders perfectly well without it.
 *
 * Three ways an overlay reaches the viewer, in the order they are consulted:
 *
 *   1. The `diffOverlay` host message (CONTRACTS §4, amended) — VS Code.
 *   2. `window.MLViewDiff` — a host that builds the page some other way.
 *   3. `<script type="application/json" id="mlview-diff">` beside
 *      `#mlview-graph` — the standalone report, and `dev/index.html`.
 *
 * THE WRITER OF (3) IS THE EMITTER, NOT THIS FILE, exactly as `ui/ruledocs.ts`
 * is the reader of `#mlview-rule-docs`. `emit/html_out.py` is analyzer-owned;
 * until it writes the block, a report carries no overlay and the viewer draws
 * the diagram it always drew. `dev/index.html` embeds a REAL overlay — the
 * output of `mlview diff` over a base/head pair — so the path is exercised end
 * to end today.
 *
 * NOTHING HERE THROWS. A missing, truncated, wrong-kind or half-typed overlay
 * degrades to "no overlay", which is invariant 1.1/6 applied to a second
 * document: a version skew must degrade, not crash.
 *
 * Pure apart from `readOverlay()`, which is the one function that touches the
 * document.
 */

import type { Loc } from '../types.js';

/** The four node / edge statuses (§11.38 B). */
export type DiffStatus = 'added' | 'removed' | 'changed' | 'unchanged';

/** The three finding statuses (§11.38 B6). */
export type DiffIssueStatus = 'new' | 'fixed' | 'persisting';

export const DIFF_KIND = 'mlview-diff';

/** The id of the `<script type="application/json">` block the emitter writes. */
export const DIFF_ELEMENT_ID = 'mlview-diff';

/** The global a host may assign instead of embedding the element. */
export const DIFF_GLOBAL = 'MLViewDiff';

const NODE_STATUSES: DiffStatus[] = ['added', 'removed', 'changed', 'unchanged'];
const ISSUE_STATUSES: DiffIssueStatus[] = ['new', 'fixed', 'persisting'];

/** `{file, line}` and nothing else — the overlay cites a place, not a range. */
export interface DiffLoc {
  file: string;
  line: number;
}

export interface DiffNodeEntry {
  id: string;
  status: DiffStatus;
  label: string;
  kind: string;
  level: string;
  stage: string;
  loc: DiffLoc | null;
  /** Field names that moved. Present only when `status` is `changed`. */
  changed: string[];
  /** §11.38 B2: the line moved and the meaning did not. A move is not a change. */
  moved: boolean;
}

export interface DiffEdgeEntry {
  id: string;
  status: DiffStatus;
  source: string;
  target: string;
  kind: string;
  label: string;
  changed: string[];
}

export interface DiffIssueEntry {
  id: string;
  status: DiffIssueStatus;
  code: string;
  severity: string;
  title: string;
  confidenceBucket: string;
  nodeIds: string[];
  loc: DiffLoc | null;
  changed: string[];
}

/**
 * §11.38 C. One honest reason an id might be missing that has nothing to do with
 * a change. NEVER elided by the renderer: a reader who saw "−16 nodes" and
 * concluded a refactor deleted them would have been misled by the tool.
 */
export interface DiffNote {
  kind: string;
  side: string;
  count: number;
  message: string;
}

/** What one side of the comparison was. Every field is optional but `root`. */
export interface DiffSide {
  root: string;
  generatedAt: string;
  analyzerVersion: string;
  schemaVersion: string;
  filesAnalyzed: number;
  nodes: number;
  edges: number;
  issues: number;
  truncated: boolean;
  view: string;
}

export interface DiffCounts {
  added: number;
  removed: number;
  changed: number;
  unchanged: number;
}

export interface DiffIssueCounts {
  new: number;
  fixed: number;
  persisting: number;
}

export interface DiffOverlay {
  kind: string;
  diffVersion: string;
  schemaVersion: string;
  base: DiffSide;
  head: DiffSide;
  nodes: DiffNodeEntry[];
  edges: DiffEdgeEntry[];
  issues: DiffIssueEntry[];
  notes: DiffNote[];
  /** The overlay's own headline, kept verbatim when it agrees with the arrays. */
  headline: string;
}

/* ── sanitising ────────────────────────────────────────────────────────── */

function str(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
}

function num(value: unknown, fallback = 0): number {
  return typeof value === 'number' && isFinite(value) ? value : fallback;
}

function strList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const out: string[] = [];
  for (const item of value) if (typeof item === 'string' && item) out.push(item);
  return out;
}

function loc(value: unknown): DiffLoc | null {
  if (!value || typeof value !== 'object') return null;
  const src = value as Record<string, unknown>;
  const file = str(src.file);
  if (!file) return null;
  return { file, line: Math.max(1, Math.round(num(src.line, 1))) };
}

function side(value: unknown): DiffSide {
  const src = (value && typeof value === 'object' ? value : {}) as Record<string, unknown>;
  return {
    root: str(src.root),
    generatedAt: str(src.generatedAt),
    analyzerVersion: str(src.analyzerVersion),
    schemaVersion: str(src.schemaVersion),
    filesAnalyzed: num(src.filesAnalyzed, -1),
    nodes: num(src.nodes, -1),
    edges: num(src.edges, -1),
    issues: num(src.issues, -1),
    truncated: src.truncated === true,
    view: str(src.view),
  };
}

function nodeEntry(value: unknown): DiffNodeEntry | null {
  if (!value || typeof value !== 'object') return null;
  const src = value as Record<string, unknown>;
  const id = str(src.id);
  const status = str(src.status) as DiffStatus;
  if (!id || NODE_STATUSES.indexOf(status) < 0) return null;
  return {
    id,
    status,
    label: str(src.label),
    kind: str(src.kind, 'unknown'),
    level: str(src.level, 'op'),
    stage: str(src.stage, 'unknown'),
    loc: loc(src.loc),
    changed: strList(src.changed),
    moved: src.moved === true,
  };
}

function edgeEntry(value: unknown): DiffEdgeEntry | null {
  if (!value || typeof value !== 'object') return null;
  const src = value as Record<string, unknown>;
  const id = str(src.id);
  const status = str(src.status) as DiffStatus;
  if (!id || NODE_STATUSES.indexOf(status) < 0) return null;
  return {
    id,
    status,
    source: str(src.source),
    target: str(src.target),
    kind: str(src.kind, 'unknown'),
    label: str(src.label),
    changed: strList(src.changed),
  };
}

function issueEntry(value: unknown): DiffIssueEntry | null {
  if (!value || typeof value !== 'object') return null;
  const src = value as Record<string, unknown>;
  const id = str(src.id);
  const status = str(src.status) as DiffIssueStatus;
  if (!id || ISSUE_STATUSES.indexOf(status) < 0) return null;
  return {
    id,
    status,
    code: str(src.code),
    severity: str(src.severity, 'low'),
    title: str(src.title),
    confidenceBucket: str(src.confidenceBucket),
    nodeIds: strList(src.nodeIds),
    loc: loc(src.loc),
    changed: strList(src.changed),
  };
}

function noteEntry(value: unknown): DiffNote | null {
  if (!value || typeof value !== 'object') return null;
  const src = value as Record<string, unknown>;
  const message = str(src.message);
  const kind = str(src.kind);
  if (!message && !kind) return null;
  return { kind: kind || 'note', side: str(src.side), count: num(src.count, 0), message };
}

/**
 * Coerce whatever arrived into something the renderer can draw, or `null`.
 *
 * The `kind` discriminator is checked FIRST and is not negotiable (§11.38 B): a
 * graph document handed to this function is rejected rather than half-read, and
 * so is a document from a `diffVersion` whose MAJOR number we do not know —
 * a minor bump is additive by the same rule the graph schema lives under.
 */
export function sanitizeOverlay(raw: unknown): DiffOverlay | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const src = raw as Record<string, unknown>;
  if (str(src.kind) !== DIFF_KIND) return null;
  const version = str(src.diffVersion, '1.0');
  if (version.split('.')[0] !== '1') return null;

  const nodes: DiffNodeEntry[] = [];
  for (const item of Array.isArray(src.nodes) ? src.nodes : []) {
    const entry = nodeEntry(item);
    if (entry) nodes.push(entry);
  }
  const edges: DiffEdgeEntry[] = [];
  for (const item of Array.isArray(src.edges) ? src.edges : []) {
    const entry = edgeEntry(item);
    if (entry) edges.push(entry);
  }
  const issues: DiffIssueEntry[] = [];
  for (const item of Array.isArray(src.issues) ? src.issues : []) {
    const entry = issueEntry(item);
    if (entry) issues.push(entry);
  }
  const notes: DiffNote[] = [];
  for (const item of Array.isArray(src.notes) ? src.notes : []) {
    const entry = noteEntry(item);
    if (entry) notes.push(entry);
  }
  // An overlay that names no node is an overlay with nothing to draw. It is not
  // an error and it is not a crash; it is simply not an overlay.
  if (!nodes.length && !issues.length) return null;

  const summary = (src.summary && typeof src.summary === 'object' ? src.summary : {}) as Record<string, unknown>;
  return {
    kind: DIFF_KIND,
    diffVersion: version,
    schemaVersion: str(src.schemaVersion, '1.0'),
    base: side(src.base),
    head: side(src.head),
    nodes,
    edges,
    issues,
    notes,
    headline: str(summary.headline),
  };
}

/* ── the index the renderer asks ───────────────────────────────────────── */

function emptyCounts(): DiffCounts {
  return { added: 0, removed: 0, changed: 0, unchanged: 0 };
}

/**
 * The overlay, indexed by id, plus the counts the banner states.
 *
 * THE COUNTS ARE COMPUTED FROM THE ARRAYS, not read off `summary`, because the
 * arrays are what is drawn: a banner reading "+26" over 25 drawn ledges would be
 * the one thing this feature must never do. When the document's own `summary`
 * disagrees, the difference is reported as an extra note rather than silently
 * preferred either way.
 */
export class DiffIndex {
  readonly overlay: DiffOverlay;
  readonly nodeById = new Map<string, DiffNodeEntry>();
  readonly edgeById = new Map<string, DiffEdgeEntry>();
  readonly issueById = new Map<string, DiffIssueEntry>();
  readonly nodeCounts: DiffCounts = emptyCounts();
  readonly edgeCounts: DiffCounts = emptyCounts();
  readonly issueCounts: DiffIssueCounts = { new: 0, fixed: 0, persisting: 0 };
  /** Every `removed` node entry, in overlay order — the ghosts drawn in place. */
  readonly removed: DiffNodeEntry[] = [];
  readonly notes: DiffNote[];

  constructor(overlay: DiffOverlay) {
    this.overlay = overlay;
    for (const entry of overlay.nodes) {
      this.nodeById.set(entry.id, entry);
      this.nodeCounts[entry.status]++;
      if (entry.status === 'removed') this.removed.push(entry);
    }
    for (const entry of overlay.edges) {
      this.edgeById.set(entry.id, entry);
      this.edgeCounts[entry.status]++;
    }
    for (const entry of overlay.issues) {
      this.issueById.set(entry.id, entry);
      this.issueCounts[entry.status]++;
    }
    this.notes = overlay.notes.slice();
    const stated = overlay.headline;
    if (stated && stated !== this.headline()) {
      this.notes.push({
        kind: 'counts-disagree',
        side: '',
        count: 0,
        message:
          'the overlay states "' + stated + '", and its own lists add up to "' + this.headline() +
          '". The lists are what is drawn, so the banner reports them.',
      });
    }
  }

  statusOf(nodeId: string): DiffStatus | null {
    const entry = this.nodeById.get(nodeId);
    return entry ? entry.status : null;
  }

  issueStatusOf(issueId: string): DiffIssueStatus | null {
    const entry = this.issueById.get(issueId);
    return entry ? entry.status : null;
  }

  /** True when this overlay has anything at all to say about the picture. */
  get interesting(): boolean {
    return (
      this.nodeCounts.added + this.nodeCounts.removed + this.nodeCounts.changed > 0 ||
      this.issueCounts.new + this.issueCounts.fixed > 0
    );
  }

  /**
   * The core of the "changed only" projection: added, removed and changed nodes,
   * in overlay order. `unchanged` is deliberately absent — a diff is another
   * projection, and its core is what moved.
   */
  changedIds(): string[] {
    const out: string[] = [];
    for (const entry of this.overlay.nodes) {
      if (entry.status !== 'unchanged') out.push(entry.id);
    }
    return out;
  }

  /**
   * `+N nodes · −N nodes · N new findings · N fixed` — §11.38's own wording, in
   * §11.38's own MINUS SIGN (U+2212, not a hyphen), composed from the arrays.
   */
  headline(): string {
    return (
      '+' + this.nodeCounts.added + ' nodes · −' + this.nodeCounts.removed + ' nodes · ' +
      this.issueCounts.new + ' new findings · ' + this.issueCounts.fixed + ' fixed'
    );
  }
}

/* ── reading one off the page ──────────────────────────────────────────── */

/**
 * The overlay this page carries, if any: the global first, then the element.
 *
 * Wrapped end to end — a host may seal its global object, and a truncated JSON
 * block must never take a report down over a decoration.
 */
export function readOverlay(): DiffIndex | null {
  let found: DiffOverlay | null = null;
  try {
    const g = typeof window !== 'undefined' ? (window as unknown as Record<string, unknown>) : null;
    if (g && g[DIFF_GLOBAL]) found = sanitizeOverlay(g[DIFF_GLOBAL]);
  } catch (_e) {
    /* a host may seal its global object */
  }
  if (!found) {
    try {
      const node = typeof document !== 'undefined' ? document.getElementById(DIFF_ELEMENT_ID) : null;
      const text = node ? node.textContent || '' : '';
      if (text.trim()) found = sanitizeOverlay(JSON.parse(text));
    } catch (_e) {
      /* a malformed sidecar must never take the report down */
    }
  }
  return found ? new DiffIndex(found) : null;
}

/** The same, from an already-parsed value. Returns null for anything unusable. */
export function indexOverlay(raw: unknown): DiffIndex | null {
  const overlay = sanitizeOverlay(raw);
  return overlay ? new DiffIndex(overlay) : null;
}

/**
 * Complete an overlay `{file, line}` into the six-field `Loc` `openLocation` is
 * contracted to carry, against `workspace.root` — the same completion
 * `app.ts` does for an answer citation, for the same reason: the overlay cites a
 * place to look, and the host needs a range to select.
 */
export function completeDiffLoc(at: DiffLoc, root: string): Loc {
  const base = (root || '').replace(/[\\/]+$/, '');
  return {
    file: at.file,
    absFile: base ? base + '/' + at.file : '',
    line: at.line,
    col: 0,
    endLine: at.line,
    endCol: 0,
  };
}
