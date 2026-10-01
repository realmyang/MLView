/**
 * The scope selector grammar (CONTRACTS 11.1): the strings the scope picker
 * writes and a saved `ViewState.scope` carries.
 *
 *   SPEC  := "all" | KIND ":" TARGET
 *   KIND  := "unit" | "stage" | "file" | "node" | "symbol"
 *   DEPTH := 0..2, a SEPARATE parameter — never packed into SPEC
 *
 * One `kind`, one `target`, split on the FIRST colon only, because a node id
 * contains one: `node:n:55662bceebd0`. No comma-unions, no `@depth` suffix, no
 * `~direction`, no `+pin`.
 *
 * Only the error CODE, the offending TERM and a sorted, <=10-entry candidate
 * list are contractual. This file began as a port of the retired analyzer's
 * selector grammar; the analyzer and its parity test were removed on
 * 2026-09-18, and so were its fixed `concern:` presets, which an authored
 * document's phases do not have.
 */

import type { MLGraph } from '../types.js';

/** The selector kinds. Extending this list extends the `bad_selector` candidate set too. */
export const SCOPE_KINDS = ['unit', 'stage', 'file', 'node'];

/** Everything a user may type in the kind slot — the `bad_selector` candidates. */
export const SCOPE_SPELLINGS = SCOPE_KINDS.concat(['symbol', 'all']).sort();

/** A point (`unit`, `node`) shows its interface; a region (`stage`, `file`) does not. */
const DEFAULT_DEPTH: Record<string, number> = {
  all: 0,
  unit: 1,
  node: 1,
  stage: 0,
  file: 0,
};

export const MAX_DEPTH = 2;

const DEPTHS = ['0', '1', '2'];

export type ScopeErrorCode =
  | 'bad_selector'
  | 'unknown_stage'
  | 'unknown_node'
  | 'unknown_file'
  | 'bad_depth';

export class ScopeError extends Error {
  readonly code: ScopeErrorCode;
  readonly term: string;
  /** Sorted, de-duplicated and capped at 10 HERE, so no call site can differ. */
  readonly candidates: string[];

  constructor(code: ScopeErrorCode, term: string, candidates: Iterable<string> = [], message?: string) {
    super(message || code + ': ' + term);
    this.name = 'ScopeError';
    this.code = code;
    this.term = term;
    this.candidates = candidateList(candidates);
  }
}

export interface Scope {
  kind: string;
  target: string;
  depth: number;
  /** The NORMALIZED "<kind>:<target>" string — what `view.scope` reports. */
  spec: string;
}

/** Sorted, de-duplicated and capped at 10 — the contract's candidate shape. */
export function candidateList(values: Iterable<string>): string[] {
  const known = new Set<string>();
  for (const v of values) known.add(String(v));
  const out = Array.from(known);
  out.sort();
  return out.slice(0, 10);
}

/**
 * ASCII-only case folding: `toLowerCase()` and Python's `str.lower()` disagree
 * outside ASCII, and the two ports must not.
 */
export function asciiLower(text: string): string {
  let out = '';
  for (let i = 0; i < text.length; i++) {
    const code = text.charCodeAt(i);
    out += code >= 65 && code <= 90 ? String.fromCharCode(code + 32) : text[i];
  }
  return out;
}

export function isAll(scope: Scope | null): boolean {
  return !scope || scope.kind === 'all';
}

export function formatScope(scope: Scope): string {
  return scope.kind === 'all' ? 'all' : scope.kind + ':' + scope.target;
}

/**
 * Parse and normalize. Raises `bad_selector` and `bad_depth`; `unknown_stage`,
 * `unknown_node` and `unknown_file` need the document and are raised by
 * `resolveScope`, and a `unit:` that resolves to
 * nothing is an EMPTY SCOPE, never an error.
 */
export function parseScope(spec: string | null | undefined, depth?: number | string | null): Scope {
  const raw = typeof spec === 'string' ? spec.trim() : '';
  if (!raw || asciiLower(raw) === 'all') {
    return { kind: 'all', target: '', depth: parseDepth(depth, 'all'), spec: 'all' };
  }
  const at = raw.indexOf(':');
  if (at < 0) throw new ScopeError('bad_selector', raw, SCOPE_SPELLINGS);
  let kind = asciiLower(raw.slice(0, at).trim());
  let target = raw.slice(at + 1).trim();
  // "symbol" is the word the user, the docs and every model reach for first.
  if (kind === 'symbol') kind = 'unit';
  if (SCOPE_KINDS.indexOf(kind) < 0) throw new ScopeError('bad_selector', raw.slice(0, at).trim(), SCOPE_SPELLINGS);
  if (!target && kind === 'unit') {
    // 11.1 spends `bad_selector` on "no `:`, or an unknown kind", and every
    // other kind has a code of its own for a target it cannot resolve. `unit:`
    // is the one kind whose unresolvable target is an EMPTY SCOPE rather than
    // an error — which would turn a typo into a silent zero-node document — so
    // its empty target is rejected here, with `term: ""`.
    //
    // `node:` and `file:` fall through to the resolver on purpose, because only
    // it can name this graph's node ids and files as the candidate list.
    throw new ScopeError('bad_selector', '', SCOPE_SPELLINGS);
  }
  // A Windows-style path spelling resolves.
  if (kind === 'file') target = target.replace(/\\/g, '/');
  // Stage ids are the document's authored phase ids; resolveScope has the
  // document and validates against them.
  return { kind, target, depth: parseDepth(depth, kind), spec: kind + ':' + target };
}

function parseDepth(depth: number | string | null | undefined, kind: string): number {
  if (depth === undefined || depth === null) return DEFAULT_DEPTH[kind] || 0;
  let value: number;
  if (typeof depth === 'string') {
    const text = depth.trim();
    if (!text) return DEFAULT_DEPTH[kind] || 0;
    if (!/^[+-]?[0-9]+$/.test(text)) throw new ScopeError('bad_depth', text, DEPTHS);
    value = Number(text);
  } else if (typeof depth === 'number') {
    value = depth;
  } else {
    throw new ScopeError('bad_depth', String(depth), DEPTHS);
  }
  if (!isFinite(value) || Math.floor(value) !== value) throw new ScopeError('bad_depth', String(depth), DEPTHS);
  if (value < 0 || value > MAX_DEPTH) throw new ScopeError('bad_depth', String(value), DEPTHS);
  return value;
}

/** The breadcrumb name for `view.label`. */
export function viewLabel(scope: Scope, graph: MLGraph, anchorLabels: string[]): string {
  if (scope.kind === 'stage') {
    const row = (graph.stages || []).filter((s) => s.id === scope.target)[0];
    return (row && row.label) || scope.target;
  }
  if (scope.kind === 'file') return scope.target;
  if (anchorLabels.length === 1) return anchorLabels[0] || scope.target;
  if (anchorLabels.length > 1) return scope.target + ' (' + anchorLabels.length + ' matches)';
  return scope.target;
}

/** The chrome's name for a scope that has not been projected yet. */
export function scopeLabel(scope: Scope | null, graph?: MLGraph | null): string {
  if (isAll(scope) || !scope) return 'Everything';
  if (!graph) return scope.target;
  const anchors = (graph.nodes || []).filter((n) => n.id === scope.target).map((n) => n.label);
  return viewLabel(scope, graph, anchors);
}
