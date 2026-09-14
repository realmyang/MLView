/**
 * The scope selector grammar (CONTRACTS 11.1), ported so the viewer, the
 * standalone report and the analyzer all accept the same strings.
 *
 *   SPEC  := "all" | KIND ":" TARGET
 *   KIND  := "unit" | "stage" | "file" | "concern" | "node" | "symbol" | "pipeline"
 *   DEPTH := 0..2, a SEPARATE parameter — never packed into SPEC
 *
 * One `kind`, one `target`, split on the FIRST colon only, because a node id
 * contains one: `node:n:55662bceebd0`. No comma-unions, no `@depth` suffix, no
 * `~direction`, no `+pin`.
 *
 * Only the error CODE, the offending TERM and a sorted, <=10-entry candidate
 * list are contractual — the prose is free, so nobody maintains two English
 * strings in two languages. Everything else in this file is a line-for-line port
 * of `analyzer/src/mlview/core/project.py`, and the parity gate
 * (`test/scope_parity.test.mjs`) is what keeps it one.
 */

import type { MLGraph } from '../types.js';

/**
 * MLV-P12 (CONTRACTS 11.47 B2) adds `pipeline`. Extending this list extends the
 * `bad_selector` candidate set, `SCOPE_SPELLINGS`, `mlview.api.SCOPE_KINDS`, the
 * MCP `mlview_graph` prose and `analyze --list-scopes` all at once, per §11.16 —
 * which is exactly why the roadmap made HEALTH-02's fuzzer a precondition.
 */
export const SCOPE_KINDS = ['unit', 'stage', 'file', 'concern', 'node', 'pipeline'];

export const STAGE_IDS = ['config', 'data', 'preprocess', 'model', 'objective', 'train', 'eval', 'deliver'];

/** FROZEN. The four presets PARTITION all eight stages: none unreachable, none shared. */
export const CONCERNS: Record<string, string[]> = {
  config: ['config'],
  data: ['data', 'preprocess'],
  optimization: ['model', 'objective', 'train'],
  evaluation: ['eval', 'deliver'],
};

/** Resolved BEFORE validation, so two spellings produce identical documents. */
export const CONCERN_ALIASES: Record<string, string> = {
  setup: 'config',
  preprocessing: 'data',
  dataset: 'data',
  training: 'optimization',
  inference: 'evaluation',
  eval: 'evaluation',
};

export const CONCERN_NAMES = ['config', 'data', 'evaluation', 'optimization'];

/** FROZEN breadcrumb names for the four concerns. Both ports must agree. */
export const CONCERN_LABELS: Record<string, string> = {
  config: 'Configuration',
  data: 'Data & preprocessing',
  optimization: 'Model & optimization',
  evaluation: 'Evaluation & inference',
};

/** Everything a user may type in the kind slot — the `bad_selector` candidates. */
export const SCOPE_SPELLINGS = SCOPE_KINDS.concat(['symbol', 'all']).sort();

/** A point (`unit`, `node`) shows its interface; a region (`stage`, `file`, `concern`) does not. */
const DEFAULT_DEPTH: Record<string, number> = {
  all: 0,
  unit: 1,
  node: 1,
  stage: 0,
  file: 0,
  concern: 0,
  // 11.47 B: a pipeline is already a REGION and its relation already carries
  // containment, so a ring around it is mostly other pipelines.
  pipeline: 0,
};

export const MAX_DEPTH = 2;

const DEPTHS = ['0', '1', '2'];

export type ScopeErrorCode =
  | 'bad_selector'
  | 'unknown_stage'
  | 'unknown_concern'
  | 'unknown_node'
  | 'unknown_file'
  /** MLV-P12 (11.47 B1): candidates are `workspace.entrypoints`, sorted. */
  | 'unknown_pipeline'
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
 * Parse and normalize. Raises `bad_selector`, `unknown_stage`,
 * `unknown_concern` and `bad_depth`; `unknown_node` and `unknown_file` need the
 * document and are raised by `resolveScope`, and a `unit:` that resolves to
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
    // This used to reject an empty target for EVERY kind, which was a silent
    // divergence from `core/selectors.py` that no frozen case covered:
    // `node:`, `file:` and now `pipeline:` fall through to the resolver on
    // purpose, because only it can name this graph's node ids, analyzed files
    // and entrypoints as the contract's candidate list (11.47 B1).
    throw new ScopeError('bad_selector', '', SCOPE_SPELLINGS);
  }
  // 11.47 B: a pipeline target is an entrypoint PATH, normalized exactly as a
  // `file:` target is, so a Windows-style spelling resolves.
  if (kind === 'file' || kind === 'pipeline') target = target.replace(/\\/g, '/');
  if (kind === 'concern') {
    // The alias resolves BEFORE validation, so `concern:inference` and
    // `concern:evaluation` produce byte-identical documents.
    target = CONCERN_ALIASES[target] || target;
    if (!CONCERNS[target]) throw new ScopeError('unknown_concern', target, CONCERN_NAMES);
  }
  if (kind === 'stage' && STAGE_IDS.indexOf(target) < 0) throw new ScopeError('unknown_stage', target, STAGE_IDS);
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

/**
 * The FROZEN breadcrumb name for `view.label`. Both ports must agree on it
 * byte-for-byte: the parity gate deep-compares the whole `view` object.
 */
export function viewLabel(scope: Scope, graph: MLGraph, anchorLabels: string[]): string {
  if (scope.kind === 'stage') {
    const row = (graph.stages || []).filter((s) => s.id === scope.target)[0];
    return (row && row.label) || scope.target;
  }
  if (scope.kind === 'concern') return CONCERN_LABELS[scope.target] || scope.target;
  // 11.47 B: `view.scope` reports the CANONICAL entrypoint path, and the
  // breadcrumb names the same string — a pipeline is the script you ran.
  if (scope.kind === 'file' || scope.kind === 'pipeline') return scope.target;
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
