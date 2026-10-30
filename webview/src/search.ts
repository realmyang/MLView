/**
 * Search: a plain case-insensitive substring match over node label / qualname /
 * id / sublabel / kind / cited files and quotes, and over finding id / title /
 * message / phase / file.
 */

import { locationHit, parseLocationQuery } from './searchloc.js';
import { locLabel } from './notebook.js';
import type { GraphIndex } from './layout/model.js';

export interface SearchHit {
  kind: 'node' | 'issue';
  id: string;
  label: string;
  meta: string;
  stage: string;
  severity?: string;
  /**
   * Set on the hit a `path:line` query resolved to. The result list
   * puts it first and labels it, so a location pasted from a stack trace or a
   * terminal reads as a jump rather than a coincidence.
   */
  location?: { path: string; line: number | null; exact: boolean };
}

/**
 * What a search actually found, as opposed to what fits.
 *
 * `hits` is what the list renders and `total` is what matched; when they
 * differ (`truncated`) the box says "showing 40 of 187" instead of cutting the
 * list in silence.
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
    // The stable id and every cited file and quote are searchable,
    // so the handles the refinement workflow uses can be found.
    const fields = [node.id, node.label, node.qualname, node.sublabel, node.loc.file, node.kind];
    for (const loc of node.evidenceLocs || []) fields.push(loc.file, loc.snippet);
    const score = fieldScore(fields, q);
    if (score < 0) continue;
    nodeHits.push({
      score,
      at: i,
      hit: {
        kind: 'node',
        id: node.id,
        label: node.label || node.qualname,
        // A step with no evidence has no location: no fake `:1`.
        meta: node.loc.file ? locLabel(node.loc) : '',
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
        // The title first, after the finding's short label (the id stays searchable).
        label: (issue.short ? issue.short + ' · ' : '') + issue.title,
        meta: issue.loc.file ? locLabel(issue.loc) : '',
        stage: issue.stage,
        severity: issue.severity,
      },
    });
  }

  // Both kinds get a reserved share of the budget, and each is ranked before it
  // is cut. One cut of the steps followed by the findings would keep the
  // document's order instead of the ranking, and a query that matched `limit`
  // steps would show no finding at all.
  byRelevance(nodeHits);
  byRelevance(issueHits);
  const share = Math.floor(limit / 2);
  const issueTake = Math.min(issueHits.length, Math.max(share, limit - nodeHits.length));
  const nodeTake = Math.min(nodeHits.length, limit - issueTake);
  const kept = nodeHits.slice(0, nodeTake).concat(issueHits.slice(0, issueTake));
  byRelevance(kept);
  const hits = kept.map((s) => s.hit);

  // The location hit is put first AFTER ranking, and only for a query carrying
  // an explicit `:line` that also RESOLVES, so every other query keeps its
  // ranked list unchanged.
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
 * The node a `path:line` query means, as a hit to put first — or null when the
 * query carries no line number, is not a location at all, or names a file this
 * graph has no node in.
 *
 * The LINE is required. `parseLocationQuery` also accepts a bare `train.py`,
 * and putting its hit first would reorder a plain substring query that the box
 * answers by relevance: `train.py` would begin with the step nearest the top of
 * the file, not with the best match. A location pasted from a stack trace or a
 * terminal carries its line (`file:line`).
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
    meta: locLabel(node.loc),
    stage: node.stage,
    location: { path: parsed.path, line: parsed.line, exact: match.contains },
  };
}

/**
 * The list form: the ordered hits and nothing else, with the same ranking and
 * budget as `searchGraphDetailed`.
 */
export function searchGraph(index: GraphIndex, query: string, limit = 40): SearchHit[] {
  return searchGraphDetailed(index, query, limit).hits;
}

/** Deterministic: score first, then the document's own order. */
function byRelevance(list: Scored[]): void {
  list.sort((a, b) => a.score - b.score || a.at - b.at);
}
