/**
 * `path:line` search (VIEW-09a).
 *
 * `train.py:29` is the exact string the CLI prints, the Problems panel shows
 * and a stack trace carries. Pasting it into the search box used to find the
 * ISSUE at that line and never the NODE, because `file + ':' + line` is only
 * ever assembled for a hit's display `meta` and was never scored. This module
 * parses that token and resolves it against the graph's own `loc` spans, so a
 * location pasted from any host lands on a card.
 *
 * Pure functions over a `GraphIndex`; no DOM, no ranking heuristics beyond the
 * two documented rules (narrowest containing span, then nearest start line).
 */

import type { GraphIndex } from './layout/model.js';
import type { MLNode } from './types.js';

export interface ParsedLocation {
  /** The path as typed — a bare name, a suffix, or a full workspace path. */
  path: string;
  /** 1-based, or null when the query named a file with no line. */
  line: number | null;
}

/**
 * A file-ish token: at least one character, no whitespace, and a short
 * extension. Deliberately narrow — `MLV101` and `train_test_split` must keep
 * behaving as plain substring queries (amendment A6), and `1.0` must not be
 * read as a file.
 */
const FILE_TOKEN = /^[^\s:*?"<>|]+\.[A-Za-z][A-Za-z0-9_]{0,7}$/;

/**
 * Parse `train.py:29`, `src/train.py:29:4` or `train.py`.
 *
 * A trailing `:col` is accepted and ignored: the CLI prints `file:line:col` in
 * some formats and a user pasting it means the same place.
 */
export function parseLocationQuery(query: string): ParsedLocation | null {
  const q = (query || '').trim();
  if (!q) return null;
  const withLine = /^(.+?):(\d+)(?::\d+)?$/.exec(q);
  if (withLine) {
    const path = withLine[1].trim();
    const line = Number(withLine[2]);
    if (!FILE_TOKEN.test(path) || !isFinite(line) || line < 1) return null;
    return { path: normalizePath(path), line };
  }
  if (!FILE_TOKEN.test(q)) return null;
  return { path: normalizePath(q), line: null };
}

/** Windows separators and a leading `./` never survive into a comparison. */
export function normalizePath(path: string): string {
  let out = path.split('\\').join('/');
  while (out.indexOf('./') === 0) out = out.slice(2);
  return out;
}

/**
 * True when `file` names the same file as the typed `path`: either they are
 * equal, or `path` is a whole trailing SEGMENT run of `file`. `n.py` therefore
 * never matches `train.py`, which a bare `endsWith` would.
 */
export function pathMatches(file: string, path: string): boolean {
  const f = normalizePath(file);
  if (f === path) return true;
  return f.length > path.length && f.slice(f.length - path.length - 1) === '/' + path;
}

export interface LocationMatch {
  node: MLNode;
  /** True when the node's own span contains the line. */
  contains: boolean;
  /** Lines between the line and the node's span; 0 when it is inside. */
  distance: number;
  /** The span's height, the tie-break that picks the NARROWEST container. */
  span: number;
}

/**
 * The node a pasted location means.
 *
 * Rule 1 — the narrowest node whose `[line, endLine]` span contains the line.
 * Rule 2 — when nothing contains it (a line between two statements, or a line
 * the analyzer produced no node for), the nearest node in the same file, so the
 * paste still lands somewhere honest rather than reporting "No matches".
 *
 * Ties break on document order, like every other ranked list in the viewer
 * (CONTRACTS section 0: same input, same bytes).
 */
export function locationHit(index: GraphIndex, parsed: ParsedLocation): LocationMatch | null {
  const nodes = index.graph.nodes || [];
  let best: LocationMatch | null = null;
  for (const node of nodes) {
    if (!node.loc || !pathMatches(node.loc.file, parsed.path)) continue;
    const start = node.loc.line;
    const end = Math.max(start, node.loc.endLine || start);
    const span = end - start;
    let contains: boolean;
    let distance: number;
    if (parsed.line === null) {
      // A bare file name means "the top of this file": the earliest node wins.
      contains = false;
      distance = start;
    } else {
      contains = parsed.line >= start && parsed.line <= end;
      distance = contains ? 0 : parsed.line < start ? start - parsed.line : parsed.line - end;
    }
    const candidate: LocationMatch = { node, contains, distance, span };
    if (!best || better(candidate, best)) best = candidate;
  }
  return best;
}

/** Containment first, then the narrowest span, then the nearest, then order. */
function better(a: LocationMatch, b: LocationMatch): boolean {
  if (a.contains !== b.contains) return a.contains;
  if (a.contains) return a.span < b.span;
  return a.distance < b.distance;
}
