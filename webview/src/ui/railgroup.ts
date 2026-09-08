/**
 * Grouping for the Issues rail (RAIL-GROUP).
 *
 * Two audits measured the same failure on two corpora: **113 rows / 6334 px in
 * an 830 px panel (7.6 screens) from 12 distinct codes**, and **111 rows that
 * are 11 codes × 10 identical repeats**. The HIGH band reads MLV702 / MLV101 /
 * MLV201 / MLV401 / MLV301 for `pipeline_0`, then the identical five for
 * `pipeline_1`. The user scrolls 40 rows to learn there are five problems.
 *
 * Rendering only — no schema change, no reordering of the underlying findings.
 * `none` is the default and reproduces today's flat list exactly, so every rail
 * snapshot and `render_report` assertion holds.
 */

import type { Issue, RailGroupBy } from '../types.js';

export const RAIL_GROUP_MODES: RailGroupBy[] = ['none', 'rule', 'file'];

export const RAIL_GROUP_LABEL: Record<RailGroupBy, string> = {
  none: 'None',
  rule: 'Rule',
  file: 'File',
};

/** Anything else restores the default rather than throwing (invariant 1.1/6). */
export function sanitizeGroupBy(value: unknown): RailGroupBy {
  return RAIL_GROUP_MODES.indexOf(value as RailGroupBy) >= 0 ? (value as RailGroupBy) : 'none';
}

export interface IssueGroup {
  /** Stable within a mode: the rule code, or the file path. */
  key: string;
  /** The header's first line — the code, or the file name. */
  title: string;
  /** The header's second line: a rule's title, or a file's directory. */
  subtitle: string;
  issues: Issue[];
  /** Distinct `loc.file` values in the group — "10 occurrences in 10 files". */
  files: number;
  /** The lowest bucket present, which is the one a reviewer should read first. */
  worstBucket: string;
}

/** Ordered worst-first: the bucket a group is only as strong as. */
const BUCKET_ORDER = ['speculative', 'possible', 'likely', 'certain'];

function bucketRank(bucket: string): number {
  const at = BUCKET_ORDER.indexOf(bucket);
  return at < 0 ? 0 : at;
}

/**
 * Group a severity band's findings.
 *
 * Order is the input order of each group's FIRST member, so grouping never
 * reshuffles a list the user has already read (CONTRACTS section 0). Every
 * finding lands in exactly one group, in its original relative order.
 */
export function groupIssues(issues: Issue[], mode: RailGroupBy): IssueGroup[] {
  if (mode === 'none') return [];
  const byKey = new Map<string, IssueGroup>();
  const order: string[] = [];
  for (const issue of issues) {
    const key = mode === 'rule' ? issue.code || 'unknown' : fileOf(issue);
    let group = byKey.get(key);
    if (!group) {
      group = {
        key,
        title: mode === 'rule' ? key : baseName(key),
        subtitle: mode === 'rule' ? issue.title || '' : dirName(key),
        issues: [],
        files: 0,
        worstBucket: issue.confidenceBucket || '',
      };
      byKey.set(key, group);
      order.push(key);
    }
    group.issues.push(issue);
    if (bucketRank(issue.confidenceBucket) < bucketRank(group.worstBucket)) {
      group.worstBucket = issue.confidenceBucket;
    }
  }
  const out: IssueGroup[] = [];
  for (const key of order) {
    const group = byKey.get(key)!;
    const files = new Set<string>();
    for (const issue of group.issues) files.add(fileOf(issue));
    group.files = files.size;
    out.push(group);
  }
  return out;
}

/** "10 occurrences in 10 files" — the count line RAIL-GROUP is named for. */
export function occurrenceText(group: IssueGroup, mode: RailGroupBy): string {
  const n = group.issues.length;
  const head = n + (n === 1 ? ' occurrence' : ' occurrences');
  if (mode === 'file') return head;
  return head + ' in ' + group.files + (group.files === 1 ? ' file' : ' files');
}

/**
 * A group is collapsed until it is worth folding. One occurrence renders as a
 * plain row, so the 15-finding demo rail is unchanged; two stay open because
 * folding them saves nothing; three or more start folded, which is the whole
 * point of the feature.
 */
export const GROUP_HEADER_MIN = 2;
export const GROUP_COLLAPSE_MIN = 3;

export function needsHeader(group: IssueGroup): boolean {
  return group.issues.length >= GROUP_HEADER_MIN;
}

export function defaultExpanded(group: IssueGroup): boolean {
  return group.issues.length < GROUP_COLLAPSE_MIN;
}

function fileOf(issue: Issue): string {
  return (issue.loc && issue.loc.file) || '(no file)';
}

function baseName(path: string): string {
  const at = path.lastIndexOf('/');
  return at < 0 ? path : path.slice(at + 1);
}

function dirName(path: string): string {
  const at = path.lastIndexOf('/');
  return at < 0 ? '' : path.slice(0, at);
}
