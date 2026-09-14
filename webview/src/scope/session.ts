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
import { CHANGED_SPEC, projectChanged } from '../diff/changed.js';
import type { DiffIndex } from '../diff/overlay.js';
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
  /**
   * VIEW-08. The diff overlay, when one is loaded, and whether the reader has
   * asked for "changed only". They live HERE rather than in `App` because a diff
   * is another projection (11.38, ROADMAP VIEW-08) and this is the object that
   * owns projection: `reproject()` composes the two in one place, so a scope and
   * a diff can be on at once without either surface knowing about the other.
   */
  private diffIndex: DiffIndex | null = null;
  private changedOnlyOn = false;
  /** True when "changed only" was asked for but had nothing to project. */
  private changedEmpty = false;

  get full(): MLGraph | null {
    return this.fullGraph;
  }

  get diff(): DiffIndex | null {
    return this.diffIndex;
  }

  get changedOnly(): boolean {
    return this.changedOnlyOn;
  }

  /** True when the document on screen is narrowed to the diff's changed set. */
  get changedActive(): boolean {
    return this.changedOnlyOn && !!this.diffIndex && !this.changedEmpty;
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
   * Install or clear the diff overlay. NEVER re-analyses and never touches the
   * graph: the overlay is a sibling document (11.38 B). Clearing it also turns
   * "changed only" off, because a chip that narrows to a set nobody can see any
   * more is a chip that lies.
   */
  setDiff(diff: DiffIndex | null): void {
    this.diffIndex = diff;
    if (!diff) this.changedOnlyOn = false;
    this.reproject();
  }

  /**
   * Turn "changed only" on or off. Returns false when it was asked for and had
   * nothing to project — the caller says so instead of drawing an empty diagram.
   */
  setChangedOnly(next: boolean): boolean {
    this.changedOnlyOn = !!next && !!this.diffIndex;
    this.reproject();
    return !next || this.changedActive;
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
    this.changedEmpty = false;
    if (!full) {
      this.projected = null;
      return;
    }
    const scoped = !this.active || isAll(this.active) ? null : project(full, this.active);
    if (!this.changedOnlyOn || !this.diffIndex) {
      this.projected = scoped;
      return;
    }
    // VIEW-08: the diff projection composes ON TOP of the scope's, so the two
    // narrowings are one document rather than two competing ones.
    const narrowed = projectChanged(scoped || full, this.diffIndex);
    if (!narrowed) {
      // Asked for, and nothing to show. The scope (or the whole graph) stands,
      // and `changedActive` is false so the caller can say why.
      this.changedEmpty = true;
      this.projected = scoped;
      return;
    }
    this.projected = narrowed;
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
export function railScopeCounts(
  graph: MLGraph | null,
): { shown: number; hidden: number; total: number; where: string } | null {
  if (!graph || !graph.view) return null;
  const shown = (graph.issues || []).filter((i) => !i.suppressed).length;
  const of = graph.view.of.issues;
  const total = of.low + of.medium + of.high;
  // VIEW-08: the same line, with the right noun. "12 outside this scope" over a
  // diff projection would name a narrowing the reader never chose.
  const where = graph.view.scope === CHANGED_SPEC ? 'outside the changed set' : 'outside this scope';
  return { shown, hidden: Math.max(0, total - shown), total, where };
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
