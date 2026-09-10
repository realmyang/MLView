/**
 * VIEW-08 — "changed only" as a PROJECTION, not a filter.
 *
 * The roadmap entry is explicit about why this is a feature and not a rewrite:
 * *"a filter chip row whose 'changed only' reuses the scope projection, because
 * a diff is just another projection"*. So it is exactly that — `core` is the set
 * of nodes the overlay says moved, `boundary` is one edge hop out of it, and
 * everything the scope projection already guarantees comes along unchanged:
 *
 *   - boundary stubs are drawn faded and carry NO severity badge, because their
 *     findings are outside the changed set and a badge you cannot open is a lie;
 *   - a ghost with no retained finding is pruned (11.2 step 7);
 *   - `nodeIds[0]` is rotated onto a core node, so every retained finding still
 *     has a card to sit on (11.30 F1-F3);
 *   - no output array is ever re-sorted (11.2.1).
 *
 * It also means the rail's scope line — *"3 of 15 findings shown · 12 outside
 * this scope"* — comes for free, which is the single most important honesty
 * property of the whole chip: a narrowed diagram must never read as a clean bill
 * of health.
 *
 * WHAT IT CANNOT DO. The projection can only keep what the HEAD document (plus
 * the resurrected ghosts) contains, so a changed node that `--max-nodes` capped
 * away, or that an outer scope already excluded, is simply not there to project
 * — `shown` vs `of` says so rather than pretending otherwise. And `unchanged` is
 * deliberately not part of the core: the boundary ring is how an unchanged
 * neighbour gets on screen, one hop and no further.
 *
 * Pure: no DOM, no clock.
 */

import { projectResolved } from '../scope/project.js';
import type { ScopeResolution } from '../scope/project.js';
import type { Scope } from '../scope/selector.js';
import type { DiffIndex } from './overlay.js';
import type { MLGraph, View } from '../types.js';

/** The pseudo-selector this projection reports in `view.scope`. */
export const CHANGED_SPEC = 'changed';

/** The frozen breadcrumb name for the diff projection. */
export const CHANGED_LABEL = 'Changed in this diff';

/** One hop: enough to see what a changed node is wired to, and no further. */
export const CHANGED_DEPTH = 1;

/**
 * Project `doc` down to the diff's changed set plus one hop.
 *
 * `doc` may itself already be a projection — "changed only" composes with a
 * scope rather than replacing it. Returns `null` when there is nothing to
 * project (no overlay entry survives in this document), because an empty diagram
 * is never the right answer to "show me what changed": the caller leaves the
 * chip off and says so.
 */
export function projectChanged(doc: MLGraph, diff: DiffIndex, depth = CHANGED_DEPTH): MLGraph | null {
  const present = new Set((doc.nodes || []).map((n) => n.id));
  const core: string[] = [];
  for (const id of diff.changedIds()) {
    if (present.has(id)) core.push(id);
  }
  if (!core.length) return null;

  const scope: Scope = { kind: 'diff', target: CHANGED_SPEC, depth, spec: CHANGED_SPEC };
  const resolution: ScopeResolution = {
    scope,
    anchors: core,
    core,
    ambiguous: false,
    warnings: [],
    empty: false,
  };
  const out = projectResolved(doc, scope, resolution, CHANGED_LABEL);
  restoreOuter(out, doc.view || null);
  return out;
}

/**
 * Put project-level truth back where a nested projection would have restated it.
 *
 * `projectResolved` computes `view.of` from the document it was handed, and when
 * that document is ALREADY a projection the honest denominator is the outer
 * one's — otherwise the breadcrumb would read "6 of 13" against a project of 54
 * and the rail would report a scope's findings as the project's. The outer
 * scope's identity (its selector, depth and anchors) is restored for the same
 * reason: the user is still inside `stage:train`, and the breadcrumb has to keep
 * saying so and keep copying a selector that parses.
 */
function restoreOuter(out: MLGraph, outer: View | null): void {
  const view = out.view;
  if (!view || !outer) return;
  view.scope = outer.scope;
  view.label = outer.label + ' · changed only';
  view.depth = outer.depth;
  view.resolvedTo = outer.resolvedTo;
  view.ambiguous = outer.ambiguous;
  view.of = { nodes: outer.of.nodes, edges: outer.of.edges, issues: { ...outer.of.issues } };
  const drawn = (out.nodes || []).length;
  const drawnEdges = (out.edges || []).length;
  view.hidden = {
    nodes: Math.max(0, view.of.nodes - drawn),
    edges: Math.max(0, view.of.edges - drawnEdges),
    inboundEdges: view.hidden.inboundEdges,
    outboundEdges: view.hidden.outboundEdges,
  };
}

/** True when the document on screen is the diff projection. */
export function isChangedView(graph: MLGraph | null): boolean {
  return !!(graph && graph.view && graph.view.scope === CHANGED_SPEC);
}
