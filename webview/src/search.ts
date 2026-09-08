/**
 * Search: a plain case-insensitive substring match over node label / qualname /
 * fqn / sublabel / file / variable and issue title / code / message
 * (amendment A6 trims the fuzzy palette to exactly this).
 */

import { locationHit, parseLocationQuery } from './searchloc.js';
import type { GraphIndex } from './layout/model.js';

export interface SearchHit {
  kind: 'node' | 'issue';
  id: string;
  label: string;
  meta: string;
  stage: string;
  severity?: string;
  /**
   * Set on the hit a `path:line` query resolved to (VIEW-09a). The result list
   * pins it first and labels it, so a location pasted from the CLI, the
   * Problems panel or a stack trace reads as a jump rather than a coincidence.
   */
  location?: { path: string; line: number | null; exact: boolean };
}

/**
 * What a search actually found, as opposed to what fits (VIEW-09b).
 *
 * `shown` is what the list renders and `total` is what matched; when they
 * differ the box says "showing 40 of 187" instead of cutting the list in
 * silence, which is a correctness bug in a search box.
 */
export interface SearchResult {
  hits: SearchHit[];
  /** Matches of both kinds, before the budget. */
  total: number;
  totalNodes: number;
  totalIssues: number;
  /** The budget that produced `hits`. */
  limit: number;
  truncated: boolean;
}

interface Scored {
  hit: SearchHit;
  score: number;
  at: number;
}

/** Lower is better: a prefix match beats a substring, a short field beats a long one. */
function fieldScore(fields: (string | undefined)[], q: string): number {
  let score = -1;
  for (const f of fields) {
    if (!f) continue;
    const at = f.toLowerCase().indexOf(q);
    if (at < 0) continue;
    const s = (at === 0 ? 0 : 1) + f.length / 1000;
    if (score < 0 || s < score) score = s;
  }
  return score;
}

export function searchGraphDetailed(index: GraphIndex, query: string, limit = 40): SearchResult {
  const q = query.trim().toLowerCase();
  if (!q) return { hits: [], total: 0, totalNodes: 0, totalIssues: 0, limit, truncated: false };
  const nodeHits: Scored[] = [];
  const issueHits: Scored[] = [];

  const nodes = index.graph.nodes || [];
  for (let i = 0; i < nodes.length; i++) {
    const node = nodes[i];
    const score = fieldScore([node.label, node.qualname, node.fqn, node.sublabel, node.loc.file, node.var, node.kind], q);
    if (score < 0) continue;
    nodeHits.push({
      score,
      at: i,
      hit: {
        kind: 'node',
        id: node.id,
        label: node.label || node.qualname,
        meta: node.loc.file + ':' + node.loc.line,
        stage: node.stage,
      },
    });
  }

  const issues = index.graph.issues || [];
  for (let i = 0; i < issues.length; i++) {
    const issue = issues[i];
    const score = fieldScore([issue.code, issue.title, issue.message, issue.stage, issue.loc.file], q);
    if (score < 0) continue;
    issueHits.push({
      score,
      at: i,
      hit: {
        kind: 'issue',
        id: issue.id,
        label: issue.code + ' · ' + issue.title,
        meta: issue.loc.file + ':' + issue.loc.line,
        stage: issue.stage,
        severity: issue.severity,
      },
    });
  }

  // Two independent bugs used to live in the old `hits.slice(0, limit)`: the
  // computed relevance was thrown away (results came out in raw graph order), and
  // because nodes were concatenated BEFORE issues, any query matching 40+ nodes
  // silently dropped every issue hit — from the box that advertises "issue, MLV
  // code" (MLV-R2-W06). Both kinds now get a reserved share of the budget, and
  // each is ranked before it is cut.
  byRelevance(nodeHits);
  byRelevance(issueHits);
  const share = Math.floor(limit / 2);
  const issueTake = Math.min(issueHits.length, Math.max(share, limit - nodeHits.length));
  const nodeTake = Math.min(nodeHits.length, limit - issueTake);
  const kept = nodeHits.slice(0, nodeTake).concat(issueHits.slice(0, issueTake));
  byRelevance(kept);
  const hits = kept.map((s) => s.hit);

  // VIEW-09a. The pin is added AFTER ranking, and only for a query carrying an
  // explicit `:line` that also RESOLVES — so every query that returned hits
  // before this item returns the identical ordered list, which is the third
  // clause of its acceptance.
  const pinned = locationPin(index, query);
  if (pinned) {
    const at = hits.findIndex((h) => h.kind === 'node' && h.id === pinned.id);
    if (at >= 0) hits.splice(at, 1);
    hits.unshift(pinned);
    if (hits.length > limit) hits.length = limit;
  }

  return {
    hits,
    total: nodeHits.length + issueHits.length,
    totalNodes: nodeHits.length,
    totalIssues: issueHits.length,
    limit,
    truncated: nodeHits.length + issueHits.length > hits.length,
  };
}

/**
 * The node a `path:line` query means, as a pinnable hit — or null when the
 * query carries no line number, is not a location at all, or names a file this
 * graph has no node in.
 *
 * The LINE is required. `parseLocationQuery` also accepts a bare `train.py`,
 * and pinning that reordered a plain substring query the box had always
 * answered by relevance: `train.py` began with *"validate() train.py:11 —
 * nearest to first in file"*, a row that ranked tenth before, silently breaking
 * VIEW-09a's own "every query that returns hits today returns the identical
 * ordered list" (TB-05). A pasted location — the thing this item exists to
 * make navigable — always carries its line, because `file:line` is what the
 * CLI prints, what the Problems panel shows and what a stack trace carries.
 */
function locationPin(index: GraphIndex, query: string): SearchHit | null {
  const parsed = parseLocationQuery(query);
  if (!parsed || parsed.line === null) return null;
  const match = locationHit(index, parsed);
  if (!match) return null;
  const node = match.node;
  return {
    kind: 'node',
    id: node.id,
    label: node.label || node.qualname,
    meta: node.loc.file + ':' + node.loc.line,
    stage: node.stage,
    location: { path: parsed.path, line: parsed.line, exact: match.contains },
  };
}

/**
 * The frozen list form: the ordered hits and nothing else. Kept because it is
 * the shape `__internal.searchGraph` publishes and the shape every existing
 * caller and test uses.
 */
export function searchGraph(index: GraphIndex, query: string, limit = 40): SearchHit[] {
  return searchGraphDetailed(index, query, limit).hits;
}

/** Deterministic: score first, then the document's own order (CONTRACTS section 0). */
function byRelevance(list: Scored[]): void {
  list.sort((a, b) => a.score - b.score || a.at - b.at);
}
