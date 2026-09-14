/**
 * MLV-P12 — the pipeline relation (CONTRACTS 11.47 A), ported line for line from
 * `analyzer/src/mlview/core/pipelines.py`.
 *
 * A research repo with ten training scripts renders as one graph at 22 % zoom.
 * The analyzer already knows there are ten entrypoints; what nobody could say
 * was *"the exp03 pipeline"*, which is the unit a practitioner thinks in. A
 * pipeline is therefore ANOTHER PROJECTION — one new selector kind, one optional
 * root block, no new mode — and this module computes the relation it projects
 * over.
 *
 * The relation, verbatim from 11.47 A:
 *
 *   A1  seeds(E) = the nodes whose `loc.file == E`, in DOCUMENT order.
 *   A2  adjacency = every `data` or `call` edge, in both directions, UNION the
 *       containment relation `parent` <-> child, in both directions. `config`
 *       and `control` edges are deliberately excluded: a shared `config.py` is
 *       precisely the module that would merge ten independent training scripts
 *       into one component, which is the failure mode the item exists to avoid.
 *   A3  reach(E) = the closure of seeds(E) under A2, which INCLUDES BUT DOES NOT
 *       EXPAND THROUGH a node that belongs to another entrypoint's own file.
 *       Without that one clause an undirected closure is the whole connected
 *       component whichever seed it starts from — ten training scripts sharing
 *       one `utils.py` would be one pipeline and the feature would answer
 *       nothing. A node another entrypoint also reaches is SHARED for E, unless
 *       it is one of E's OWN seeds, which are never taken away from it. A node
 *       in no reach at all is UNREACHED, which is a finding about the workspace
 *       rather than an error.
 *   A4  every set is materialised in DOCUMENT order, never in set-iteration
 *       order — the same determinism rule the projection lives by (11.2.1).
 *
 * **Both ports compute this; neither trusts the emitted `pipelines[]` block.**
 * The block is a menu the analyzer wrote for a chooser; the projection is
 * computed here, so a stale or absent block can never change what is drawn.
 * `pipelineDrift()` is the one place the two are compared, and it REPORTS a
 * disagreement rather than resolving it.
 *
 * Pure: no DOM, no clock, no set-iteration-order leak.
 */

import { ScopeError, asciiLower } from './selector.js';
import type { ScopeResolution } from './project.js';
import type { Scope } from './selector.js';
import type { IssueCounts, MLGraph, MLNode, Severity } from '../types.js';

/** One row of the chooser and of the scope picker's Pipelines section. */
export interface PipelineRow {
  /** The canonical `workspace.entrypoints` path — what `pipeline:` takes. */
  entrypoint: string;
  /** `|reach(E)|`. */
  nodeCount: number;
  /** Reachable from this entrypoint and no other — the projection's `core`. */
  exclusiveCount: number;
  /** Reachable from another entrypoint too — drawn as `context` (11.47 C). */
  sharedCount: number;
  /** Non-suppressed findings with at least one anchor in `reach(E)`. */
  issueCounts: IssueCounts;
}

const SEVERITIES: Severity[] = ['high', 'medium', 'low'];

/** The relation over one document. Built once, asked many times. */
export class PipelineIndex {
  /** `workspace.entrypoints`, in the analyzer's ranked order (11.47 D). */
  readonly entrypoints: string[];
  /** entrypoint -> reach(E), in document order. */
  private readonly reachOf = new Map<string, string[]>();
  /** Nodes reached by two or more entrypoints. */
  readonly shared: Set<string>;
  /** node id -> the entrypoint whose file it lives in, for the SEEDS only. */
  private readonly owner = new Map<string, string>();
  /** Nodes in no reach at all, in document order. */
  readonly unreached: string[];
  private readonly graph: MLGraph;

  constructor(graph: MLGraph) {
    this.graph = graph;
    const nodes = graph.nodes || [];
    const adjacency = buildAdjacency(graph);
    const entrypoints = (graph.workspace && graph.workspace.entrypoints) || [];
    this.entrypoints = entrypoints.slice();
    this.shared = new Set<string>();
    if (!this.entrypoints.length || !nodes.length) {
      this.unreached = nodes.map((n) => n.id);
      return;
    }

    // The seeds of every entrypoint, claimed first-come in entrypoint order.
    for (const entry of this.entrypoints) {
      for (const id of seedIds(nodes, entry)) {
        if (!this.owner.has(id)) this.owner.set(id, entry);
      }
    }

    const hits = new Map<string, number>();
    for (const entry of this.entrypoints) {
      const reached = closure(seedIds(nodes, entry), adjacency, entry, this.owner);
      if (!reached.size) {
        this.reachOf.set(entry, []);
        continue;
      }
      // A4: back to DOCUMENT order. A set is a membership test, never an order.
      const ordered = nodes.filter((n) => reached.has(n.id)).map((n) => n.id);
      this.reachOf.set(entry, ordered);
      for (const id of ordered) hits.set(id, (hits.get(id) || 0) + 1);
    }
    const unreached: string[] = [];
    for (const node of nodes) {
      const count = hits.get(node.id) || 0;
      if (count > 1) this.shared.add(node.id);
      else if (count === 0) unreached.push(node.id);
    }
    this.unreached = unreached;
  }

  /**
   * Shared FOR this entrypoint: another entrypoint reaches it too, and it is
   * not one of this entrypoint's own seeds — a script's own statements are
   * never taken away from it and handed to a neighbour as context.
   */
  private sharedFor(entrypoint: string, id: string): boolean {
    return this.shared.has(id) && this.owner.get(id) !== entrypoint;
  }

  /** `reach(E)` in document order, or `[]` for an entrypoint we do not have. */
  reach(entrypoint: string): string[] {
    return this.reachOf.get(entrypoint) || [];
  }

  /** A1: the nodes whose file IS the entrypoint, in document order. */
  seeds(entrypoint: string): string[] {
    return (this.graph.nodes || [])
      .filter((n) => fileOf(n) === entrypoint)
      .map((n) => n.id);
  }

  /** `core` for 11.47 C: reachable from here and not shared away. */
  exclusive(entrypoint: string): string[] {
    return this.reach(entrypoint).filter((id) => !this.sharedFor(entrypoint, id));
  }

  /** `forced context` for 11.47 C: reachable from here AND from elsewhere. */
  sharedWith(entrypoint: string): string[] {
    return this.reach(entrypoint).filter((id) => this.sharedFor(entrypoint, id));
  }

  /**
   * The chooser's rows, in `workspace.entrypoints` order — which 11.47 D says is
   * already ranked most-likely-first, so this never re-sorts.
   *
   * Entrypoints whose reach is EMPTY are dropped: 11.47 D emits the block "only
   * when the document has two or more non-empty pipelines", and a menu row that
   * draws nothing is a row that reads as a bug.
   */
  rows(): PipelineRow[] {
    const out: PipelineRow[] = [];
    for (const entry of this.entrypoints) {
      const reached = this.reach(entry);
      if (!reached.length) continue;
      // `sharedWith`, exactly as `pipelines_block` uses `context_of`: the row's
      // `sharedCount` is what THIS view would draw as context, so a script's own
      // statements — which another entrypoint may well reach — are never counted
      // against it. `exclusiveCount + sharedCount == nodeCount` either way; only
      // the split moves, and it moves to match the projection.
      const shared = this.sharedWith(entry).length;
      out.push({
        entrypoint: entry,
        nodeCount: reached.length,
        exclusiveCount: reached.length - shared,
        sharedCount: shared,
        issueCounts: countIssues(this.graph, new Set(reached)),
      });
    }
    return out;
  }
}

/** The only edge kinds that join a pipeline (11.47 A2). */
export const PIPELINE_EDGE_KINDS = ['data', 'call'];

/**
 * A2. `data` and `call` edges both ways, plus `parent` <-> child both ways.
 *
 * A link to an id the document does not contain, and a self-link, are both
 * dropped — exactly as `_adjacency` in `core/pipelines.py` drops them, so a
 * malformed document cannot make the two ports disagree about a reach.
 */
function buildAdjacency(graph: MLGraph): Map<string, string[]> {
  const known = new Set<string>((graph.nodes || []).map((n) => n.id));
  const adjacency = new Map<string, string[]>();
  const link = (a: string, b: string): void => {
    if (!a || !b || a === b || !known.has(a) || !known.has(b)) return;
    push(adjacency, a, b);
    push(adjacency, b, a);
  };
  for (const edge of graph.edges || []) {
    if (PIPELINE_EDGE_KINDS.indexOf(edge.kind) < 0) continue;
    link(edge.source, edge.target);
  }
  for (const node of graph.nodes || []) {
    link(node.id, node.parent || '');
  }
  return adjacency;
}

function push(map: Map<string, string[]>, key: string, value: string): void {
  const list = map.get(key);
  if (list) list.push(value);
  else map.set(key, [value]);
}

function seedIds(nodes: MLNode[], entrypoint: string): string[] {
  return nodes.filter((n) => fileOf(n) === entrypoint).map((n) => n.id);
}

/**
 * A3: the closure, cycle-guarded and bounded by the node set.
 *
 * The one clause that makes a pipeline a pipeline: a node that belongs to
 * ANOTHER entrypoint's own file is KEPT — it really is reachable from here — but
 * the walk does not expand through it. Without it an undirected closure is the
 * whole connected component whichever seed it starts from, and ten training
 * scripts sharing one `utils.py` are one pipeline.
 */
function closure(
  seeds: string[],
  adjacency: Map<string, string[]>,
  entrypoint: string,
  owner: Map<string, string>,
): Set<string> {
  const seen = new Set<string>();
  const stack = seeds.slice();
  while (stack.length) {
    const current = stack.pop() as string;
    if (seen.has(current)) continue;
    seen.add(current);
    const held = owner.get(current);
    if (held !== undefined && held !== entrypoint) continue; // keep, but stop
    for (const next of adjacency.get(current) || []) {
      if (!seen.has(next)) stack.push(next);
    }
  }
  return seen;
}

function fileOf(node: MLNode): string {
  return (node.loc && node.loc.file) || '';
}

function basename(path: string): string {
  const at = path.lastIndexOf('/');
  return at < 0 ? path : path.slice(at + 1);
}

/** 11.47 D: non-suppressed findings with at least one anchor in the set. */
function countIssues(graph: MLGraph, ids: Set<string>): IssueCounts {
  const counts: IssueCounts = { low: 0, medium: 0, high: 0 };
  for (const issue of graph.issues || []) {
    if (issue.suppressed) continue;
    if (!(issue.nodeIds || []).some((id) => ids.has(id))) continue;
    const severity = issue.severity as Severity;
    if (counts[severity] !== undefined) counts[severity]++;
  }
  return counts;
}

/** The highest severity among a row's findings, for the picker's `data-sev`. */
export function rowSeverity(row: PipelineRow): Severity | null {
  return SEVERITIES.filter((s) => row.issueCounts[s] > 0)[0] || null;
}

/**
 * Resolve a `pipeline:` target to a canonical `workspace.entrypoints` path.
 *
 * 11.47 B, in order, first match winning: exact path; bare basename when the
 * target contains no `/`; then the same two ASCII-case-folded, which emits the
 * same `config_warning` a case-folded `file:` does. Anything else raises
 * `unknown_pipeline` with the sorted entrypoints as candidates — including the
 * EMPTY target, which falls through the grammar to here because only the
 * document knows what the entrypoints are.
 */
export function resolveEntrypoint(
  entrypoints: string[],
  target: string,
): { entrypoint: string; warnings: string[] } {
  const bare = target.indexOf('/') < 0;
  for (const entry of entrypoints) {
    if (entry === target) return { entrypoint: entry, warnings: [] };
  }
  if (bare && target) {
    for (const entry of entrypoints) {
      if (basename(entry) === target) return { entrypoint: entry, warnings: [] };
    }
  }
  const want = asciiLower(target);
  const folded = (name: string): string[] => [
    'scope pipeline:' + target + ' matched case-insensitively; the canonical spelling is ' + name,
  ];
  if (target) {
    for (const entry of entrypoints) {
      if (asciiLower(entry) === want) return { entrypoint: entry, warnings: folded(entry) };
    }
    if (bare) {
      for (const entry of entrypoints) {
        if (asciiLower(basename(entry)) === want) return { entrypoint: entry, warnings: folded(entry) };
      }
    }
  }
  throw new ScopeError('unknown_pipeline', target, entrypoints);
}

/**
 * 11.47 C1 — the scope note, which exists to say what the view is NOT showing.
 *
 * Prose is free (11.2 step 10) and this is deliberately three numbers rather
 * than a sentence about one: a pipeline view that quietly dropped a shared
 * `data/` module, or that showed 40 of 300 nodes because 260 belong to no
 * pipeline at all, must not read as a clean bill of health.
 */
export function pipelineNote(
  index: PipelineIndex,
  entrypoint: string,
  totalNodes: number,
): string {
  const reached = index.reach(entrypoint).length;
  const shared = index.sharedWith(entrypoint).length;
  return (
    'pipeline:' + entrypoint + ' reaches ' + reached + ' of ' + totalNodes + ' node(s): ' + shared +
    ' shared with another entrypoint and drawn as context rather than claimed by this pipeline, and ' +
    index.unreached.length + ' node(s) of the whole graph belong to no pipeline at all. ' +
    'Only data and call edges join a pipeline — a config-only dependency is not shown here.'
  );
}

/**
 * Does the emitted `pipelines[]` block agree with the relation computed here?
 *
 * 11.47 A says neither port trusts the block, so nothing DEPENDS on this — but a
 * silent disagreement between the menu and the diagram is exactly the class of
 * bug this product cannot afford, so the chooser states it when it happens.
 * Returns null when there is nothing to say.
 */
export function pipelineDrift(graph: MLGraph, rows: PipelineRow[]): string | null {
  const block = (graph as { pipelines?: unknown }).pipelines;
  if (!Array.isArray(block)) return null;
  const emitted = block
    .map((row) => (row && typeof row === 'object' ? String((row as { entrypoint?: unknown }).entrypoint || '') : ''))
    .filter((name) => !!name);
  const computed = rows.map((r) => r.entrypoint);
  if (emitted.length === computed.length && emitted.every((name, i) => name === computed[i])) return null;
  return (
    'This document lists ' + emitted.length + ' pipeline(s) and the relation computed here finds ' +
    computed.length + '. The diagram follows the computed one; the difference usually means the ' +
    'document was capped or scoped after its block was written.'
  );
}

/**
 * MLV-P12 (11.47 B and C) — resolve one `pipeline:` selector into the shape
 * `scope/project.ts` step 2 hands to steps 3-11.
 *
 * It lives HERE rather than in `project.ts` because it is 11.47's rule, not
 * 11.2's: it replaces step 2 outright, it is the only caller of the relation
 * above, and `project.ts` was over the file-size bar with it inside.
 *
 * It replaces step 2 rather than extending it. `core` is what this entrypoint
 * reaches AND NOBODY ELSE DOES; what two entrypoints both reach becomes FORCED
 * CONTEXT, so a shared `data/` module is drawn as the frame it is rather than
 * claimed by whichever pipeline the reader happened to open. `anchors` stay the
 * SEEDS — the nodes actually written in the entrypoint file — because that is
 * what `view.resolvedTo` is for: "what did this selector name", not "what did it
 * pull in".
 */
export function resolvePipelineScope(
  graph: MLGraph,
  scope: Scope,
  nodes: MLNode[],
  warnings: string[],
): ScopeResolution {
  const entrypoints = (graph.workspace && graph.workspace.entrypoints) || [];
  const found = resolveEntrypoint(entrypoints, scope.target);
  for (const w of found.warnings) warnings.push(w);
  const index = new PipelineIndex(graph);
  const core = index.exclusive(found.entrypoint);
  const forcedContext = index.sharedWith(found.entrypoint);
  const anchors = index.seeds(found.entrypoint);
  // 11.47 C1. The note exists so a view that drew 40 of 300 nodes can never read
  // as a clean bill of health, and the two numbers that say so — how much is
  // shared, and how much belongs to no pipeline at all — are knowable only here.
  // It is appended only when the scope resolved to something, because an EMPTY
  // scope already gets 11.2 step 10's own "matched no nodes" note and two notes
  // about the same nothing is one too many. `core/project.py` gates it the same
  // way, on the same condition.
  if (anchors.length) warnings.push(pipelineNote(index, found.entrypoint, nodes.length));
  return {
    // The scope handed in, NOT a canonicalized copy: `view.scope` reports what
    // the user typed, exactly as `file:` does, and `core/project.py` builds its
    // `ScopeResolution` from `scope` too. Only the RELATION uses the canonical
    // entrypoint, which is what makes `pipeline:TRAIN.PY` draw the same nodes.
    scope,
    anchors,
    core,
    ambiguous: false,
    warnings,
    // 11.47 B: an entrypoint that resolves but whose file contributed no node —
    // it was capped away, or projected away — is an EMPTY SCOPE, not an error,
    // exactly as `unit:` is. `empty` is `not anchors` for every kind.
    empty: !anchors.length,
    forcedContext,
  };
}
