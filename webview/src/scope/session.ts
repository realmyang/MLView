/**
 * The scope session: the FULL document, the active selector, and the projected
 * document the renderer actually draws.
 *
 * The viewer holds the whole graph and re-projects LOCALLY. A scope change never
 * posts `requestRefresh` and never touches the analyzer, which is what makes it
 * instant and what makes the standalone report — which has no host at all —
 * behave identically to the webview (FEATURES 5.1).
 *
 * Nothing here touches the DOM, so it is also the object the tests drive.
 */

import { ScopeError, formatScope, isAll, parseScope } from './selector.js';
import type { Scope } from './selector.js';
import { project } from './project.js';
import type { MLGraph, ScopeSummary } from '../types.js';

export interface ScopeSetResult {
  ok: boolean;
  /** Present when the selector was rejected; the caller toasts and moves on. */
  error?: ScopeError;
  /** True when the selector is valid but resolved to nothing (still applied). */
  empty?: boolean;
}

export class ScopeSession {
  private fullGraph: MLGraph | null = null;
  private projected: MLGraph | null = null;
  private active: Scope | null = null;

  get full(): MLGraph | null {
    return this.fullGraph;
  }

  get scope(): Scope | null {
    return this.active;
  }

  get spec(): string | null {
    return this.active && !isAll(this.active) ? formatScope(this.active) : null;
  }

  get depth(): number {
    return this.active ? this.active.depth : 0;
  }

  /** The document to render: the projection when scoped, the full graph else. */
  get document(): MLGraph | null {
    return this.projected || this.fullGraph;
  }

  setGraph(graph: MLGraph): void {
    this.fullGraph = graph;
    this.reproject();
  }

  /**
   * Apply a selector. NEVER throws: an unresolvable spec leaves the previous
   * view standing and hands the error back for a toast (CONTRACTS 11.8).
   */
  set(spec: string | null, depth?: number): ScopeSetResult {
    if (spec === null || spec === undefined || spec === '' || spec === 'all') {
      this.active = null;
      this.reproject();
      return { ok: true };
    }
    let parsed: Scope;
    try {
      parsed = parseScope(spec, depth === undefined ? null : depth);
    } catch (e) {
      return { ok: false, error: e as ScopeError };
    }
    const previous = this.active;
    this.active = parsed;
    try {
      this.reproject();
    } catch (e) {
      this.active = previous;
      this.reproject();
      return { ok: false, error: e as ScopeError };
    }
    const view = this.projected ? this.projected.view : null;
    return { ok: true, empty: !!(view && view.empty) };
  }

  /** `[` and `]`: one hop in or out, keeping the selector. */
  stepDepth(delta: number): ScopeSetResult {
    if (!this.active || isAll(this.active)) return { ok: false };
    const next = this.active.depth + delta;
    if (next < 0 || next > 2) return { ok: false };
    return this.set(formatScope(this.active), next);
  }

  /**
   * Re-resolve the active scope against a NEW document. Returns true when the
   * scope no longer matches anything and was dropped, so the caller can toast
   * "Scope no longer matches — cleared" (CONTRACTS 11.9).
   */
  reresolve(): boolean {
    if (!this.active || !this.fullGraph) return false;
    try {
      this.reproject();
    } catch (_e) {
      this.active = null;
      this.reproject();
      return true;
    }
    const view = this.projected ? this.projected.view : null;
    if (view && view.empty) {
      this.active = null;
      this.reproject();
      return true;
    }
    return false;
  }

  summary(): ScopeSummary {
    const full = this.fullGraph;
    const doc = this.document;
    const total = full ? full.nodes.length : 0;
    if (!this.active || isAll(this.active) || !doc || !doc.view) {
      return { spec: null, label: 'Everything', depth: 0, nodes: total, of: total };
    }
    return {
      spec: doc.view.scope,
      label: doc.view.label,
      depth: doc.view.depth,
      nodes: doc.nodes.length,
      of: doc.view.of.nodes,
    };
  }

  private reproject(): void {
    const full = this.fullGraph;
    if (!full) {
      this.projected = null;
      return;
    }
    if (!this.active || isAll(this.active)) {
      this.projected = null;
      return;
    }
    this.projected = project(full, this.active);
  }
}

/**
 * Has anything the HOST displays about the scope moved? Both the selector and
 * the counts matter: `4 of 45` beside a diagram drawing `6 of 61` is as stale a
 * panel description as a title naming a unit that no longer exists
 * (CONTRACTS 11.11).
 */
export function sameScope(a: ScopeSummary, b: ScopeSummary): boolean {
  return a.spec === b.spec && a.label === b.label && a.depth === b.depth && a.nodes === b.nodes && a.of === b.of;
}

/**
 * "3 of 15 findings shown · 12 outside this scope" — the rail's scope line.
 * `total` is PROJECT-LEVEL truth (`view.of`), so a scope can never be read as a
 * clean bill of health. Null when the document is not a projection.
 */
export function railScopeCounts(graph: MLGraph | null): { shown: number; hidden: number; total: number } | null {
  if (!graph || !graph.view) return null;
  const shown = (graph.issues || []).filter((i) => !i.suppressed).length;
  const of = graph.view.of.issues;
  const total = of.low + of.medium + of.high;
  return { shown, hidden: Math.max(0, total - shown), total };
}

/**
 * The collapse set is held against the FULL id space and filtered at projection
 * time, so collapsing inside a scope and then clearing it does not lose the
 * collapse (FEATURES 3.5). This merges what the canvas currently draws back
 * into that full set, leaving ids outside the projection untouched.
 */
export function mergeCollapsed(full: string[], inView: string[], drawn: Set<string>): string[] {
  const visible = new Set(inView);
  const outside = full.filter((id) => !visible.has(id));
  return outside.concat(Array.from(drawn)).sort();
}
