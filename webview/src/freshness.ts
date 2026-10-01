/**
 * Freshness in place (viewer M1): which cited files changed or went missing since the displayed
 * revision was published, as the host reports them in its `stale` frame.
 *
 * Everything here is derived from the host's hash check and the authored evidence ids: a file is
 * stale or it is not. Nothing says the claim is right or wrong, and nothing is shown when every
 * file is unchanged (colour and marks are for problems only).
 */

import type { Loc, StaleFile, StaleReason, WorkflowDocument } from './types.js';

const REASONS: readonly StaleReason[] = ['changed', 'missing', 'unreadable', 'too-large'];
/** At most this many files are kept from one frame (the contract tracks at most 2000). */
const MAX_FILES = 2000;

/** How a quote whose file is stale reads, in the reader's words. */
export const STALE_TEXT: Record<StaleReason, string> = {
  changed: 'changed since publishing',
  missing: 'file missing',
  unreadable: 'file unreadable',
  'too-large': 'file too large to check',
};

/** The host's list, kept only where it is well formed: a path, a known reason, each path once. */
export function sanitizeStaleFiles(value: unknown): StaleFile[] {
  if (!Array.isArray(value)) return [];
  const out: StaleFile[] = [];
  const seen = new Set<string>();
  for (const item of value) {
    if (out.length >= MAX_FILES) break;
    if (!item || typeof item !== 'object') continue;
    const path = (item as { path?: unknown }).path;
    const reason = (item as { reason?: unknown }).reason;
    if (typeof path !== 'string' || !path || path.length > 500 || seen.has(path)) continue;
    if (typeof reason !== 'string' || REASONS.indexOf(reason as StaleReason) < 0) continue;
    seen.add(path);
    out.push({ path, reason: reason as StaleReason });
  }
  return out;
}

/** The stale files of the displayed revision, by workspace-relative path. */
export class FreshnessState {
  private reasons = new Map<string, StaleReason>();
  /** The host is checking a change on disk; the marks shown are the last ones it reported. */
  checking = false;

  /** Replace the set. True when it changed. */
  set(files: StaleFile[]): boolean {
    const next = new Map(files.map((file) => [file.path, file.reason] as [string, StaleReason]));
    let same = next.size === this.reasons.size;
    if (same) for (const [path, reason] of next) if (this.reasons.get(path) !== reason) same = false;
    this.reasons = next;
    return !same;
  }

  reasonOf(file: string | undefined): StaleReason | undefined {
    return file ? this.reasons.get(file) : undefined;
  }

  get size(): number {
    return this.reasons.size;
  }

  paths(): string[] {
    return Array.from(this.reasons.keys());
  }

  list(): StaleFile[] {
    return Array.from(this.reasons, ([path, reason]) => ({ path, reason }));
  }
}

/** How many of these quotes cite a stale file. */
export function staleQuotes(locs: readonly Pick<Loc, 'file'>[] | undefined, isStale: (file: string) => boolean): { stale: number; total: number } {
  const list = locs || [];
  let stale = 0;
  for (const loc of list) if (loc.file && isStale(loc.file)) stale++;
  return { stale, total: list.length };
}

/** "changed", "missing", or "changed or missing" for a mix (unreadable and too large count as missing). */
function reasonWord(reasons: StaleReason[]): string {
  const set = new Set(reasons);
  if (set.size === 1 && set.has('changed')) return 'changed';
  if (!set.has('changed')) return 'missing';
  return 'changed or missing';
}

/**
 * The status bar's freshness item, or null when every file is unchanged (nothing is shown then).
 * Counts cited files (distinct `evidence[].file`) apart from files that were only inspected.
 */
export function freshnessSummary(document: WorkflowDocument | null, state: FreshnessState): { text: string; title: string } | null {
  if (!document || state.size === 0) return null;
  const cited = Array.from(new Set((document.evidence || []).map((item) => item.file)));
  const citedStale = cited.filter((file) => state.reasonOf(file));
  const other = state.paths().filter((file) => cited.indexOf(file) < 0);
  const word = reasonWord(state.list().map((file) => file.reason));
  let text: string;
  if (citedStale.length) {
    text = citedStale.length + ' of ' + cited.length + ' cited files ' + word;
    if (other.length) text += ' · ' + other.length + ' inspected';
  } else {
    text = other.length + ' inspected ' + (other.length === 1 ? 'file' : 'files') + ' ' + word;
  }
  const lines = state.list().slice(0, 20).map((file) => file.path + ' — ' + STALE_TEXT[file.reason]);
  if (state.size > 20) lines.push('and ' + (state.size - 20) + ' more');
  const title = 'Source files that no longer match the published revision. Jumps into them are blocked.\n' + lines.join('\n');
  return { text, title };
}
