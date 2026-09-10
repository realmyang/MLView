/**
 * The model-facing digests. Every payload handed to a language model — the chat participant's
 * summaries and all three language-model tools — is capped at 4 KB (CONTRACTS.md §5), with the
 * full graph left on disk / in the panel.
 *
 * The cap is enforced by construction: build, measure, shed detail, measure again. `fitToBudget`
 * always returns something under the limit, even for a graph with hundreds of issues.
 */

import { coverageFor } from './coverage';
import { countIssues, type IssueCounts, type MLGraph, type Severity } from './graph';
import { selectIssues, truncate, type IssueFilter } from './issues';
import { notebookCounts } from './notebooks';

export const DIGEST_LIMIT_BYTES = 4096;

export interface LaneDigest {
  stage: string;
  label: string;
  nodeCount: number;
  maxSeverity: Severity | null;
}

export interface TopIssueDigest {
  code: string;
  severity: Severity;
  confidenceBucket: string;
  title: string;
  file: string;
  line: number;
}

export interface AnalyzeDigest {
  schemaVersion: string;
  root: string;
  filesAnalyzed: number;
  filesFailed: number;
  notebooksSkipped: number;
  /** NB: `.ipynb` files actually read, when `mlview.includeNotebooks` was on. */
  notebooksAnalyzed: number;
  frameworks: string[];
  stats: { nodes: number; edges: number; issues: IssueCounts };
  lanes: LaneDigest[];
  topIssues: TopIssueDigest[];
  truncated: boolean;
  /**
   * COVERAGE: the analyzer's `single_file_analysis` / `untagged_dataflow` caveats, verbatim.
   * A model that is handed a finding count and nothing else reports a clean file; this is the
   * sentence that stops it, and it is why the shedding ladder drops it last of all.
   */
  coverage: string[];
  /** True when this digest itself had to shed detail to fit the 4 KB budget. */
  digestTruncated: boolean;
  graphPath?: string;
  reportPath?: string;
}

export interface RelatedDigest {
  role: string;
  file: string;
  line: number;
}

export interface IssueDigestRow {
  id: string;
  code: string;
  severity: Severity;
  confidenceBucket: string;
  title: string;
  message: string;
  fixHint: string;
  file: string;
  line: number;
  related: RelatedDigest[];
}

export interface IssuesDigest {
  countBySeverity: IssueCounts;
  suppressedCount: number;
  issues: IssueDigestRow[];
  /** COVERAGE: see `AnalyzeDigest.coverage`. An empty issue list is not a clean file. */
  coverage: string[];
  digestTruncated: boolean;
}

export function jsonBytes(value: unknown): number {
  return Buffer.byteLength(JSON.stringify(value) ?? '', 'utf8');
}

/**
 * Shrink `value` until it serializes to at most `limit` bytes, by repeatedly applying `shed`.
 * `shed` returns false when there is nothing left to remove; the last resort is the caller's
 * responsibility to keep the skeleton small enough to always fit.
 */
export function fitToBudget<T>(value: T, limit: number, shed: (v: T) => boolean): T {
  let guard = 0;
  while (jsonBytes(value) > limit && guard < 2000) {
    guard += 1;
    if (!shed(value)) {
      break;
    }
  }
  return value;
}

export interface AnalyzeDigestOptions extends IssueFilter {
  limitBytes?: number;
  graphPath?: string;
  reportPath?: string;
  maxTopIssues?: number;
}

export function buildAnalyzeDigest(graph: MLGraph, opts: AnalyzeDigestOptions = {}): AnalyzeDigest {
  const limit = opts.limitBytes ?? DIGEST_LIMIT_BYTES;
  const maxTop = opts.maxTopIssues ?? 10;
  const issues = selectIssues(graph, opts);
  const digest: AnalyzeDigest = {
    schemaVersion: graph.schemaVersion,
    root: graph.workspace.root,
    filesAnalyzed: graph.workspace.filesAnalyzed,
    filesFailed: graph.workspace.filesFailed,
    notebooksSkipped: graph.workspace.notebooksSkipped,
    notebooksAnalyzed: notebookCounts(graph).analyzed,
    frameworks: graph.workspace.frameworks.slice(0, 8),
    stats: {
      nodes: graph.stats.nodes,
      edges: graph.stats.edges,
      issues: graph.stats.issues ?? countIssues(graph.issues)
    },
    lanes: graph.stages
      .filter((stage) => stage.present || stage.nodeCount > 0)
      .map((stage) => ({
        stage: String(stage.id),
        label: stage.label,
        nodeCount: stage.nodeCount,
        maxSeverity: stage.maxSeverity
      })),
    topIssues: issues.slice(0, maxTop).map((issue) => ({
      code: issue.code,
      severity: issue.severity,
      confidenceBucket: String(issue.confidenceBucket),
      title: truncate(issue.title, 90),
      file: issue.loc.file,
      line: issue.loc.line
    })),
    truncated: graph.stats.truncated === true,
    coverage: coverageFor(graph),
    digestTruncated: false,
    ...(opts.graphPath ? { graphPath: opts.graphPath } : {}),
    ...(opts.reportPath ? { reportPath: opts.reportPath } : {})
  };

  return fitToBudget(digest, limit, (d) => {
    if (d.topIssues.length > 1) {
      d.topIssues.pop();
      d.digestTruncated = true;
      return true;
    }
    if (d.topIssues.length === 1) {
      const only = d.topIssues[0];
      if (only && only.title.length > 30) {
        only.title = truncate(only.title, 30);
        d.digestTruncated = true;
        return true;
      }
      d.topIssues.pop();
      d.digestTruncated = true;
      return true;
    }
    if (d.lanes.length > 0) {
      d.lanes.pop();
      d.digestTruncated = true;
      return true;
    }
    if (d.root.length > 40) {
      d.root = `…${d.root.slice(-39)}`;
      d.digestTruncated = true;
      return true;
    }
    if (d.coverage.length > 0) {
      // Last resort only: a payload that cannot hold one more sentence is already useless,
      // but the budget is a hard contract and something has to give.
      d.coverage.pop();
      d.digestTruncated = true;
      return true;
    }
    return false;
  });
}

export interface IssuesDigestOptions extends IssueFilter {
  limitBytes?: number;
  limit?: number;
}

export function buildIssuesDigest(graph: MLGraph, opts: IssuesDigestOptions = {}): IssuesDigest {
  const limitBytes = opts.limitBytes ?? DIGEST_LIMIT_BYTES;
  const rowLimit = opts.limit ?? 12;
  const selected = selectIssues(graph, opts);
  const digest: IssuesDigest = {
    countBySeverity: countIssues(graph.issues),
    suppressedCount: graph.issues.filter((i) => i.suppressed).length,
    coverage: coverageFor(graph),
    issues: selected.slice(0, rowLimit).map((issue) => ({
      id: issue.id,
      code: issue.code,
      severity: issue.severity,
      confidenceBucket: String(issue.confidenceBucket),
      title: truncate(issue.title, 80),
      message: truncate(issue.message, 180),
      fixHint: truncate(issue.fixHint, 140),
      file: issue.loc.file,
      line: issue.loc.line,
      related: issue.relatedLocs.slice(0, 3).map((rel) => ({
        role: rel.role,
        file: rel.file,
        line: rel.line
      }))
    })),
    digestTruncated: selected.length > rowLimit
  };

  return fitToBudget(digest, limitBytes, (d) => {
    const last = d.issues[d.issues.length - 1];
    if (!last) {
      if (d.coverage.length > 0) {
        d.coverage.pop();
        d.digestTruncated = true;
        return true;
      }
      return false;
    }
    if (d.issues.length > 1) {
      d.issues.pop();
      d.digestTruncated = true;
      return true;
    }
    if (last.message.length > 40) {
      last.message = truncate(last.message, 40);
      last.fixHint = truncate(last.fixHint, 40);
      last.related = [];
      d.digestTruncated = true;
      return true;
    }
    d.issues.pop();
    d.digestTruncated = true;
    return true;
  });
}

/** One compact human/model readable line per issue. */
export function formatIssueLine(row: TopIssueDigest | IssueDigestRow): string {
  return `[${row.severity.toUpperCase()}] ${row.code} ${row.title} (${row.file}:${row.line})`;
}

/** The plain-text rendering handed to language-model tools. */
export function analyzeDigestToText(digest: AnalyzeDigest): string {
  const lines: string[] = [];
  lines.push(
    `MLView analyzed ${digest.filesAnalyzed} file(s) under ${digest.root}` +
      (digest.filesFailed > 0 ? ` (${digest.filesFailed} could not be parsed)` : '') +
      '.'
  );
  lines.push(
    `Frameworks: ${digest.frameworks.length ? digest.frameworks.join(', ') : 'none detected'}.`
  );
  lines.push(
    `Graph: ${digest.stats.nodes} nodes, ${digest.stats.edges} edges. ` +
      `Issues: ${digest.stats.issues.high} high, ${digest.stats.issues.medium} medium, ${digest.stats.issues.low} low.`
  );
  if (digest.lanes.length > 0) {
    lines.push(
      `Stages: ${digest.lanes
        .map((l) => `${l.label} (${l.nodeCount}${l.maxSeverity ? `, max ${l.maxSeverity}` : ''})`)
        .join(' -> ')}`
    );
  }
  if (digest.topIssues.length > 0) {
    lines.push('Top issues:');
    for (const issue of digest.topIssues) {
      lines.push(`  ${formatIssueLine(issue)}`);
    }
  } else {
    lines.push('No issues were reported.');
  }
  if (digest.truncated) {
    lines.push('The graph was truncated by --max-nodes; narrow the scope for the full picture.');
  }
  if (digest.notebooksAnalyzed > 0) {
    lines.push(
      `${digest.notebooksAnalyzed} notebook(s) were analyzed; cell execution order is ` +
        'not knowable from the file, so order-sensitive findings there are de-rated.'
    );
  }
  if (digest.notebooksSkipped > 0) {
    lines.push(`${digest.notebooksSkipped} notebook(s) were detected but not analyzed.`);
  }
  lines.push(...coverageTextLines(digest.coverage));
  return lines.join('\n');
}

/**
 * COVERAGE: the paragraph that stops a model reporting a blind run as a clean one. It is
 * addressed to the model in the imperative because the LM tools hand this text to it verbatim.
 */
function coverageTextLines(coverage: string[]): string[] {
  if (coverage.length === 0) {
    return [];
  }
  return [
    'Coverage caveat - this analysis was INCOMPLETE, so the counts above are a floor and ' +
      'not a clean bill of health. Say so when you report them:',
    ...coverage.map((line) => `  - ${line}`)
  ];
}

export function issuesDigestToText(digest: IssuesDigest): string {
  const lines: string[] = [];
  lines.push(
    `${digest.countBySeverity.high} high, ${digest.countBySeverity.medium} medium, ` +
      `${digest.countBySeverity.low} low` +
      (digest.suppressedCount > 0 ? `, ${digest.suppressedCount} suppressed` : '') +
      '.'
  );
  if (digest.issues.length === 0) {
    lines.push('No matching issues.');
    lines.push(...coverageTextLines(digest.coverage));
    return lines.join('\n');
  }
  for (const issue of digest.issues) {
    lines.push(`${formatIssueLine(issue)}`);
    lines.push(`  why: ${issue.message}`);
    lines.push(`  fix: ${issue.fixHint}`);
    for (const rel of issue.related) {
      lines.push(`  related (${rel.role}): ${rel.file}:${rel.line}`);
    }
  }
  if (digest.digestTruncated) {
    lines.push('(list truncated to stay within the 4 KB tool budget)');
  }
  lines.push(...coverageTextLines(digest.coverage));
  return lines.join('\n');
}
