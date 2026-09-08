/**
 * Search: a plain case-insensitive substring match over node label / qualname /
 * fqn / sublabel / file / variable and issue title / code / message
 * (amendment A6 trims the fuzzy palette to exactly this).
 */

import type { GraphIndex } from './layout/model.js';

export interface SearchHit {
  kind: 'node' | 'issue';
  id: string;
  label: string;
  meta: string;
  stage: string;
  severity?: string;
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

export function searchGraph(index: GraphIndex, query: string, limit = 40): SearchHit[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
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
  return kept.map((s) => s.hit);
}

/** Deterministic: score first, then the document's own order (CONTRACTS section 0). */
function byRelevance(list: Scored[]): void {
  list.sort((a, b) => a.score - b.score || a.at - b.at);
}
