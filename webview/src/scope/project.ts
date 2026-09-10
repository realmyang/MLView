/**
 * `project(D, scope) -> D'` — the scoped view (CONTRACTS 11.2, normative).
 *
 * A scope is a PURE PROJECTION of the finished whole-workspace document. It is
 * never a smaller set of files handed to the parser and never a smaller audit:
 * the analyzer always walked the whole workspace, so cross-file resolution and
 * workspace-wide rules keep working, and this filters the already-sorted arrays
 * and re-derives the aggregates.
 *
 * THE ORDERING INVARIANT (11.2.1) — and the reason parity with the Python
 * implementation is affordable: every step only REMOVES elements from arrays
 * that are already canonically sorted, and only FILTERS the nodeIds / edgeIds /
 * issueIds lists. NO OUTPUT ARRAY IS EVER RE-SORTED, so `nodes`, `edges` and
 * `issues` in D' are subsequences of D's in the same relative order. The single
 * non-filter operation in the whole algorithm is the stable rotation in step 6.
 * A PORT THAT SORTS ANYTHING IS WRONG, even when its output happens to match.
 *
 * This file is a line-for-line port of `analyzer/src/mlview/core/project.py`;
 * `webview/test/scope_parity.test.mjs` deep-compares the two over the frozen
 * `contracts/graph.sample.json` on every case of `contracts/scope.cases.json`.
 *
 * Pure: no DOM, no clock, no randomness, no set-iteration-order leak.
 */

import { CONCERNS, ScopeError, asciiLower, isAll, viewLabel } from './selector.js';
import type { Scope } from './selector.js';
import type { Diagnostic, Issue, IssueCounts, MLEdge, MLGraph, MLNode, Severity, Stage, View, ViewAnchor, ViewRole } from '../types.js';

const SEVERITIES: Severity[] = ['high', 'medium', 'low'];
const MAX_PRUNE_ROUNDS = 8;

export interface ScopeResolution {
  scope: Scope;
  /** Node ids the selector resolved to, in DOCUMENT order. */
  anchors: string[];
  /** The anchors plus, for `unit:`, their descendant closure. Document order. */
  core: string[];
  ambiguous: boolean;
  /** `config_warning` messages to append to `diagnostics`. */
  warnings: string[];
  empty: boolean;
}

/* ── step 1: resolve the anchors ─────────────────────────────────────── */

function lastSegment(qualname: string): string {
  const at = qualname.lastIndexOf('.');
  return at < 0 ? qualname : qualname.slice(at + 1);
}

function basename(path: string): string {
  const at = path.lastIndexOf('/');
  return at < 0 ? path : path.slice(at + 1);
}

function fileOf(node: MLNode): string {
  return (node.loc && node.loc.file) || '';
}

/**
 * The five `unit:` tiers, in order; the FIRST NON-EMPTY tier wins and every node
 * in it is an anchor. Tier 3 is what makes `unit:train` mean the function
 * `train.train` (a whole subtree) rather than also dragging in the unrelated
 * `model.train()` op node `train.train.train`.
 */
function unitTiers(nodes: MLNode[], target: string, fold: boolean): MLNode[][] {
  const f = (value: string): string => (fold ? asciiLower(value) : value);
  const want = f(target);
  const wantCall = f(target + '()');
  const eq = (value: string | undefined, expected: string): boolean => !!value && f(value) === expected;
  const definition = (n: MLNode): boolean => n.level === 'stage' || n.level === 'unit';
  return [
    nodes.filter((n) => eq(n.qualname, want)),
    nodes.filter((n) => eq(n.fqn, want)),
    nodes.filter((n) => eq(lastSegment(n.qualname || ''), want) && definition(n)),
    nodes.filter((n) => eq(lastSegment(n.qualname || ''), want)),
    nodes.filter((n) => eq(n.label, want) || eq(n.label, wantCall)),
  ];
}

function resolveUnit(nodes: MLNode[], target: string): { anchors: MLNode[]; warnings: string[] } {
  const warnings: string[] = [];
  const text = target.length > 2 && target.slice(-2) === '()' ? target.slice(0, -2) : target;
  // The tools hand back node ids; a human types a qualname. Both must work, or
  // somebody has to translate.
  if (text.indexOf('n:') === 0) {
    const exact = nodes.filter((n) => n.id === text);
    if (exact.length) return { anchors: exact, warnings };
  }
  for (const tier of unitTiers(nodes, text, false)) {
    if (tier.length) return { anchors: tier, warnings };
  }
  for (const tier of unitTiers(nodes, text, true)) {
    if (!tier.length) continue;
    const spellings = unique(tier.map((n) => n.qualname || '')).slice(0, 5);
    warnings.push('scope unit:' + text + ' matched case-insensitively; the canonical spelling is ' + spellings.join(', '));
    return { anchors: tier, warnings };
  }
  return { anchors: [], warnings };
}

/** Exact path, then bare basename, then the same two case-insensitively. */
function resolveFile(nodes: MLNode[], target: string): { anchors: MLNode[]; warnings: string[] } {
  const bare = target.indexOf('/') < 0;
  const exact = nodes.filter((n) => fileOf(n) === target);
  if (exact.length) return { anchors: exact, warnings: [] };
  if (bare) {
    const byBase = nodes.filter((n) => basename(fileOf(n)) === target);
    if (byBase.length) return { anchors: byBase, warnings: [] };
  }
  const want = asciiLower(target);
  let folded = nodes.filter((n) => asciiLower(fileOf(n)) === want);
  if (!folded.length && bare) folded = nodes.filter((n) => asciiLower(basename(fileOf(n))) === want);
  if (folded.length) {
    const spellings = unique(folded.map(fileOf)).slice(0, 5);
    return {
      anchors: folded,
      warnings: ['scope file:' + target + ' matched case-insensitively; the canonical spelling is ' + spellings.join(', ')],
    };
  }
  throw new ScopeError('unknown_file', target, nodes.map(fileOf).filter((f) => !!f));
}

/** Anchors and core for `scope`, in document order. No projection. */
export function resolveScope(graph: MLGraph, scope: Scope): ScopeResolution {
  const nodes = (graph.nodes || []).slice();
  const warnings: string[] = [];
  if (scope.kind === 'all') {
    const ids = nodes.map((n) => n.id);
    return { scope, anchors: ids, core: ids, ambiguous: false, warnings, empty: !ids.length };
  }

  let anchors: MLNode[];
  if (scope.kind === 'stage') {
    anchors = nodes.filter((n) => n.stage === scope.target);
  } else if (scope.kind === 'concern') {
    const wanted = CONCERNS[scope.target] || [];
    anchors = nodes.filter((n) => wanted.indexOf(n.stage) >= 0);
  } else if (scope.kind === 'file') {
    const found = resolveFile(nodes, scope.target);
    anchors = found.anchors;
    for (const w of found.warnings) warnings.push(w);
  } else if (scope.kind === 'node') {
    anchors = nodes.filter((n) => n.id === scope.target);
    if (!anchors.length) throw new ScopeError('unknown_node', scope.target, nodes.map((n) => n.id));
  } else {
    const found = resolveUnit(nodes, scope.target);
    anchors = found.anchors;
    for (const w of found.warnings) warnings.push(w);
  }

  const anchorIds = anchors.map((n) => n.id);
  // Ambiguity is REPORTED, never silently narrowed to a "best" pick.
  const ambiguous = scope.kind === 'unit' && anchorIds.length > 1;
  if (ambiguous) {
    const names = unique(anchors.map((n) => n.qualname || n.id));
    warnings.push('scope unit:' + scope.target + ' is ambiguous: ' + anchorIds.length + ' nodes match. Use one of: ' + names.join(', '));
  }
  // Step 2: `unit:` means a whole DEFINITION, so the descendant closure comes
  // with it. `stage:` / `file:` / `concern:` already denote a set, and a closure
  // would drag in nodes that are by definition outside it.
  const core = scope.kind === 'unit' && anchorIds.length ? withDescendants(nodes, anchorIds) : anchorIds.slice();
  return { scope, anchors: anchorIds, core, ambiguous, warnings, empty: !anchorIds.length };
}

/** Seeds plus their transitive `parent` descendants, in document order. */
function withDescendants(nodes: MLNode[], seeds: string[]): string[] {
  const children = new Map<string, string[]>();
  for (const node of nodes) {
    if (!node.parent) continue;
    const list = children.get(node.parent);
    if (list) list.push(node.id);
    else children.set(node.parent, [node.id]);
  }
  const keep = new Set<string>();
  const stack = seeds.slice();
  while (stack.length) {
    const current = stack.pop() as string;
    if (keep.has(current)) continue; // cycle-guarded
    keep.add(current);
    for (const child of children.get(current) || []) stack.push(child);
  }
  // Back to DOCUMENT order: a set is a membership test, never an ordering.
  return nodes.filter((n) => keep.has(n.id)).map((n) => n.id);
}

/* ── the projection ──────────────────────────────────────────────────── */

export function project(graph: MLGraph, scope: Scope): MLGraph {
  if (isAll(scope)) {
    // `view` is emitted only by a REAL projection: its absence is what tells a
    // consumer "this document describes the entire analyzed workspace".
    const out = clone(graph) as MLGraph;
    delete out.view;
    for (const node of out.nodes || []) delete node.viewRole;
    return out;
  }
  return projectResolved(graph, scope, resolveScope(graph, scope));
}

/**
 * Steps 3-11 of 11.2, over an ALREADY-RESOLVED core set.
 *
 * `project()` is the only caller that resolves a selector; this half takes the
 * anchors as given, which is what lets VIEW-08's "changed only" be a projection
 * rather than a second rendering path. A diff IS another projection — core = the
 * nodes the overlay says moved, boundary = one hop — and every property the
 * scope projection already guarantees (boundary stubs carry no badge, ghosts
 * with no retained finding are pruned, `nodeIds[0]` is rotated to a core node,
 * no output array is ever re-sorted) comes with it for free.
 *
 * `labelOverride` exists because `viewLabel` is the FROZEN breadcrumb naming for
 * the six selector kinds and the parity gate deep-compares it against the Python
 * port; a caller outside the grammar names its own view instead of teaching that
 * function a seventh case.
 *
 * `project()`'s behaviour is byte-for-byte what it was — this is an extraction,
 * not a change, and `test/scope_parity.test.mjs` is what says so.
 */
export function projectResolved(
  graph: MLGraph,
  scope: Scope,
  resolution: ScopeResolution,
  labelOverride?: string,
): MLGraph {
  const nodes = graph.nodes || [];
  const edges = graph.edges || [];
  const issues = graph.issues || [];
  const byId = new Map<string, MLNode>();
  for (const node of nodes) byId.set(node.id, node);

  const core = new Set(resolution.core);

  // Steps 3-4: boundary rings, then the ancestor closure.
  const boundary = boundaryRing(edges, core, scope.depth);
  const context = ancestorClosure(byId, union(core, boundary));
  let kept = union(union(core, boundary), context);

  let keptEdges = edges.filter((e) => kept.has(e.source) && kept.has(e.target));
  const coreEdgeIds = new Set(keptEdges.filter((e) => core.has(e.source) && core.has(e.target)).map((e) => e.id));

  // CONTRACTS 11.30 F1-F2: `retainIssues` may PROMOTE a retaining edge's source
  // into an issue's `nodeIds`, so it needs the kept edges by id and hands back
  // the promotions the reverse link is built from.
  const edgesById = new Map<string, MLEdge>(keptEdges.map((e) => [e.id, e]));
  const retention = retainIssues(issues, core, kept, new Set(keptEdges.map((e) => e.id)), coreEdgeIds, edgesById);
  let retained = retention.retained;
  const promoted = retention.promoted;
  const pruned = pruneGhosts(retained, kept, keptEdges, byId);
  retained = pruned.retained;
  kept = pruned.kept;
  keptEdges = pruned.keptEdges;

  const liveIssueIds = new Set(retained.map((i) => i.id));

  // Step 8: document order, one role each, findings filtered to the retained.
  const outNodes: MLNode[] = [];
  for (const node of nodes) {
    if (!kept.has(node.id)) continue;
    const copied = clone(node) as MLNode;
    copied.issueIds = (node.issueIds || []).filter((id) => liveIssueIds.has(id));
    for (const issueId of promoted.get(node.id) || []) {
      // 11.30 F2: a promoted anchor keeps the node <-> issue link two-way.
      if (liveIssueIds.has(issueId) && copied.issueIds.indexOf(issueId) < 0) copied.issueIds.push(issueId);
    }
    copied.viewRole = (core.has(node.id) ? 'core' : boundary.has(node.id) ? 'boundary' : 'context') as ViewRole;
    outNodes.push(copied);
  }
  const outEdges: MLEdge[] = keptEdges.map((edge) => {
    const copied = clone(edge) as MLEdge;
    copied.issueIds = (edge.issueIds || []).filter((id) => liveIssueIds.has(id));
    return copied;
  });

  const counts = { core: 0, boundary: 0, context: 0 };
  for (const node of outNodes) counts[node.viewRole as ViewRole]++;
  return assemble(graph, scope, resolution, outNodes, outEdges, retained, counts, kept, labelOverride);
}

/** `depth` BFS rings over `edges[]` in both directions. Containment is not a hop. */
function boundaryRing(edges: MLEdge[], core: Set<string>, depth: number): Set<string> {
  const boundary = new Set<string>();
  if (depth <= 0 || core.size === 0) return boundary;
  const adjacency = new Map<string, Set<string>>();
  for (const edge of edges) {
    link(adjacency, edge.source, edge.target);
    link(adjacency, edge.target, edge.source);
  }
  const seen = new Set(core);
  let frontier = Array.from(core);
  for (let ring = 0; ring < depth; ring++) {
    const next: string[] = [];
    for (const id of frontier) {
      for (const other of adjacency.get(id) || []) {
        if (seen.has(other)) continue;
        seen.add(other);
        boundary.add(other);
        next.push(other);
      }
    }
    if (!next.length) break;
    frontier = next;
  }
  return boundary;
}

/**
 * The transitive `parent` chain of `seeds`, minus anything already kept. A
 * context ancestor whose only descendants are boundary stubs is KEPT: it is the
 * frame around drawn cards, and dropping it would re-orphan them.
 */
function ancestorClosure(byId: Map<string, MLNode>, seeds: Set<string>): Set<string> {
  const context = new Set<string>();
  for (const id of seeds) {
    const start = byId.get(id);
    let current = start ? start.parent : null;
    let guard = 0;
    while (current && guard < 64) {
      if (seeds.has(current) || context.has(current)) break;
      context.add(current);
      const node = byId.get(current);
      current = node ? node.parent : null;
      guard++;
    }
  }
  return context;
}

/** Step 6: retention through `core` only, then filter + stable rotation. */
function retainIssues(
  issues: Issue[],
  core: Set<string>,
  kept: Set<string>,
  keptEdgeIds: Set<string>,
  coreEdgeIds: Set<string>,
  edgesById: Map<string, MLEdge>,
): { retained: Issue[]; promoted: Map<string, string[]> } {
  const out: Issue[] = [];
  const promoted = new Map<string, string[]>();
  for (const issue of issues) {
    const nodeIds = issue.nodeIds || [];
    const edgeIds = issue.edgeIds || [];
    const throughNode = nodeIds.some((n) => core.has(n));
    const throughEdge = edgeIds.some((e) => coreEdgeIds.has(e));
    if (!throughNode && !throughEdge) continue;
    const copied = clone(issue) as Issue;
    let liveNodes = nodeIds.filter((n) => kept.has(n));
    const liveEdges = edgeIds.filter((e) => keptEdgeIds.has(e));
    if (!liveNodes.length) {
      // CONTRACTS 11.30 F1/F3, and the branch the differential fuzzer found the
      // two ports disagreeing on: an issue retained through the EDGE rule whose
      // every cited node fell outside `kept` would end with `nodeIds: []`, which
      // breaks invariant 1.1.3 and leaves the renderer nowhere to draw a badge.
      // Promote the retaining edge's `source` -- a `core` node by construction,
      // so a legal `nodeIds[0]` needing no rotation -- and drop the issue if it
      // was not retained through a live core edge after all.
      const retaining = liveEdges.filter((e) => coreEdgeIds.has(e))[0];
      if (retaining === undefined) continue;
      liveNodes = [(edgesById.get(retaining) as MLEdge).source];
      const already = promoted.get(liveNodes[0]);
      if (already) already.push(issue.id);
      else promoted.set(liveNodes[0], [issue.id]);
    }
    copied.nodeIds = rotateToCore(liveNodes, core);
    copied.edgeIds = liveEdges;
    out.push(copied);
  }
  return { retained: out, promoted };
}

/**
 * The one non-filter operation in the algorithm, specified as a ROTATION
 * precisely so both languages produce the same list: it keeps invariant 1.1.3
 * true AND puts the badge on a real card instead of a faded boundary stub.
 */
function rotateToCore(nodeIds: string[], core: Set<string>): string[] {
  if (!nodeIds.length || core.has(nodeIds[0])) return nodeIds;
  for (let i = 0; i < nodeIds.length; i++) {
    if (core.has(nodeIds[i])) return nodeIds.slice(i).concat(nodeIds.slice(0, i));
  }
  return nodeIds;
}

/**
 * Step 7: a kept ghost with no retained issue is dropped, and so is an issue
 * whose `nodeIds` emptied out. Two rounds converge (a ghost is never the parent
 * of a non-ghost); the loop is bounded so a malformed document cannot spin.
 */
function pruneGhosts(
  retained: Issue[],
  kept: Set<string>,
  keptEdges: MLEdge[],
  byId: Map<string, MLNode>,
): { retained: Issue[]; kept: Set<string>; keptEdges: MLEdge[] } {
  for (let round = 0; round < MAX_PRUNE_ROUNDS; round++) {
    const live = new Set(retained.map((i) => i.id));
    const doomed = new Set<string>();
    for (const id of kept) {
      const node = byId.get(id);
      if (!node || !node.ghost) continue;
      if ((node.issueIds || []).some((i) => live.has(i))) continue;
      doomed.add(id);
    }
    if (!doomed.size) break;
    const next = new Set<string>();
    for (const id of kept) {
      if (!doomed.has(id)) next.add(id);
    }
    kept = next;
    keptEdges = keptEdges.filter((e) => kept.has(e.source) && kept.has(e.target));
    const edgeIds = new Set(keptEdges.map((e) => e.id));
    const survivors: Issue[] = [];
    for (const issue of retained) {
      issue.nodeIds = issue.nodeIds.filter((n) => kept.has(n));
      issue.edgeIds = issue.edgeIds.filter((e) => edgeIds.has(e));
      if (issue.nodeIds.length) survivors.push(issue);
    }
    retained = survivors;
  }
  return { retained, kept, keptEdges };
}

function issueCounts(issues: Issue[], stage?: string): IssueCounts {
  const counts: IssueCounts = { low: 0, medium: 0, high: 0 };
  for (const issue of issues) {
    if (issue.suppressed) continue;
    if (stage !== undefined && issue.stage !== stage) continue;
    const severity = issue.severity as Severity;
    if (counts[severity] !== undefined) counts[severity]++;
  }
  return counts;
}

function maxSeverity(counts: IssueCounts): Severity | null {
  return SEVERITIES.filter((s) => counts[s] > 0)[0] || null;
}

/** Steps 9-11: aggregates, carried-verbatim fields, then `view` last. */
function assemble(
  graph: MLGraph,
  scope: Scope,
  resolution: ScopeResolution,
  outNodes: MLNode[],
  outEdges: MLEdge[],
  retained: Issue[],
  counts: { core: number; boundary: number; context: number },
  kept: Set<string>,
  labelOverride?: string,
): MLGraph {
  const byStage = new Map<string, number>();
  for (const node of outNodes) byStage.set(node.stage, (byStage.get(node.stage) || 0) + 1);
  const stages: Stage[] = (graph.stages || []).map((row) => {
    const copied = clone(row) as Stage;
    const stageCounts = issueCounts(retained, row.id);
    copied.nodeCount = byStage.get(row.id) || 0;
    copied.issueCounts = stageCounts;
    copied.maxSeverity = maxSeverity(stageCounts);
    copied.present = row.present; // project-level truth, carried through
    return copied;
  });

  const stats = clone(graph.stats || {}) as MLGraph['stats'];
  stats.nodes = outNodes.length;
  stats.edges = outEdges.length;
  stats.issues = issueCounts(retained);
  stats.suppressed = retained.filter((i) => i.suppressed).length;

  const allNodes = graph.nodes || [];
  const allEdges = graph.edges || [];
  const anchorIds = new Set(resolution.anchors);
  const anchorNodes = allNodes.filter((n) => anchorIds.has(n.id));
  let inbound = 0;
  let outbound = 0;
  for (const edge of allEdges) {
    const s = kept.has(edge.source);
    const t = kept.has(edge.target);
    if (t && !s) inbound++;
    if (s && !t) outbound++;
  }
  const ofIssues = graph.stats && graph.stats.issues ? graph.stats.issues : issueCounts(graph.issues || []);
  const anchors: ViewAnchor[] = anchorNodes.map((n) => ({
    id: n.id,
    qualname: n.qualname || '',
    label: n.label || '',
    file: (n.loc && n.loc.file) || '',
    line: (n.loc && n.loc.line) || 1,
  }));
  const view: View = {
    scope: scope.spec,
    label: labelOverride || viewLabel(scope, graph, anchorNodes.map((n) => n.label || '')),
    depth: scope.depth,
    counts: { core: counts.core, boundary: counts.boundary, context: counts.context },
    of: {
      nodes: allNodes.length,
      edges: allEdges.length,
      issues: { low: ofIssues.low || 0, medium: ofIssues.medium || 0, high: ofIssues.high || 0 },
    },
    hidden: {
      nodes: allNodes.length - outNodes.length,
      edges: allEdges.length - outEdges.length,
      inboundEdges: inbound,
      outboundEdges: outbound,
    },
    resolvedTo: anchors,
    ambiguous: !!resolution.ambiguous,
    empty: !!resolution.empty,
  };

  // Step 10: a projection NEVER restates project-level truth. `workspace`,
  // `generator` and `diagnostics` all describe the analysis, which really was
  // whole-workspace. Scope notes are appended, then the array is re-sorted by
  // its existing key.
  const diagnostics: Diagnostic[] = (graph.diagnostics || []).map((d) => clone(d) as Diagnostic);
  for (const message of resolution.warnings) diagnostics.push({ kind: 'config_warning', message });
  if (resolution.empty) {
    diagnostics.push({
      kind: 'config_warning',
      message:
        'scope ' + scope.spec + ' matched no nodes; the whole graph has ' + allNodes.length +
        ' node(s). This is a finding, not an error.',
    });
  }
  if (graph.stats && graph.stats.truncated) {
    // --max-nodes runs BEFORE projection and is not re-applied (11.2.2).
    diagnostics.push({
      kind: 'truncated',
      message: 'the graph was capped by --max-nodes BEFORE this scope was applied; view.of reports the pre-projection totals.',
    });
  }
  diagnostics.sort(diagnosticOrder);

  const out: MLGraph = clone(graph) as MLGraph;
  out.stages = stages;
  out.nodes = outNodes;
  out.edges = outEdges;
  out.issues = retained;
  out.diagnostics = diagnostics;
  out.stats = stats;
  delete out.view;
  out.view = view; // always the LAST key
  return out;
}

/** The analyzer's own key: (kind, file, line, message). Nothing else re-sorts. */
function diagnosticOrder(a: Diagnostic, b: Diagnostic): number {
  return (
    cmp(a.kind || '', b.kind || '') ||
    cmp(a.file || '', b.file || '') ||
    (a.line || 0) - (b.line || 0) ||
    cmp(a.message || '', b.message || '')
  );
}

function cmp(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

function unique(values: string[]): string[] {
  const seen = new Set<string>();
  for (const v of values) seen.add(v);
  const out = Array.from(seen);
  out.sort();
  return out;
}

function union(a: Set<string>, b: Set<string>): Set<string> {
  const out = new Set<string>(a);
  for (const v of b) out.add(v);
  return out;
}

function link(map: Map<string, Set<string>>, key: string, value: string): void {
  const set = map.get(key);
  if (set) set.add(value);
  else map.set(key, new Set([value]));
}

/** Structural deep copy — no `structuredClone` (absent in jsdom), no JSON round trip. */
function clone<T>(value: T): T {
  if (value === null || typeof value !== 'object') return value;
  if (Array.isArray(value)) return value.map((v) => clone(v)) as unknown as T;
  const out: Record<string, unknown> = {};
  for (const key of Object.keys(value as Record<string, unknown>)) {
    out[key] = clone((value as Record<string, unknown>)[key]);
  }
  return out as unknown as T;
}
