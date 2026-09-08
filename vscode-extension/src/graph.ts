/**
 * Structural types for the MLGraph document (CONTRACTS.md §1).
 *
 * These are deliberately permissive on the closed enumerations: invariant 1.1.6 requires an
 * unknown `kind` / `stage` / `edge.kind` to still render, so the host types them as widened
 * string unions rather than exact literals. Everything the host actually depends on is
 * required here, and nothing else.
 */

export const SCHEMA_VERSION = '1.0';

export type Severity = 'low' | 'medium' | 'high';
export type ConfidenceBucket = 'certain' | 'likely' | 'possible' | 'speculative';
export type StageId =
  | 'config'
  | 'data'
  | 'preprocess'
  | 'model'
  | 'objective'
  | 'train'
  | 'eval'
  | 'deliver';
export type NodeLevel = 'stage' | 'unit' | 'op';

/** Line numbers are 1-based; column numbers are 0-based. The asymmetry is deliberate (§0). */
export interface Loc {
  file: string;
  absFile: string;
  line: number;
  col: number;
  endLine: number;
  endCol: number;
  symbol?: string;
  snippet?: string;
}

export interface RelatedLoc extends Loc {
  role: string;
  message?: string;
}

export interface Port {
  name: string;
  tags: string[];
}

export interface Evidence {
  kind: string;
  detail: string;
  weight: number;
}

export interface IssueCounts {
  low: number;
  medium: number;
  high: number;
}

export interface Generator {
  name: string;
  version: string;
  rendererSha: string;
  generatedAt: string;
}

export interface Workspace {
  root: string;
  entrypoints: string[];
  filesAnalyzed: number;
  filesFailed: number;
  notebooksSkipped: number;
  frameworks: string[];
  configPath?: string;
}

export interface Stage {
  id: StageId | string;
  label: string;
  order: number;
  present: boolean;
  nodeCount: number;
  issueCounts: IssueCounts;
  maxSeverity: Severity | null;
}

export interface GraphNode {
  id: string;
  kind: string;
  level: NodeLevel | string;
  stage: StageId | string;
  label: string;
  sublabel?: string;
  qualname: string;
  fqn?: string;
  framework?: string;
  var?: string;
  loc: Loc;
  defLoc?: Loc;
  parent: string | null;
  attrs: Record<string, string>;
  produces: Port[];
  consumes: Port[];
  ghost: boolean;
  dynamic: boolean;
  confidence: number;
  confidenceBucket: ConfidenceBucket | string;
  issueIds: string[];
  collapsedByDefault: boolean;
  stageEvidence: Evidence[];
}

export interface GraphEdge {
  id: string;
  kind: string;
  subkind?: string;
  source: string;
  target: string;
  label?: string;
  loc: Loc;
  tags: string[];
  confidence: number;
  issueIds: string[];
}

export interface Issue {
  id: string;
  code: string;
  ruleVersion: number;
  severity: Severity;
  confidence: number;
  confidenceBucket: ConfidenceBucket | string;
  title: string;
  message: string;
  why: string;
  fixHint: string;
  loc: Loc;
  relatedLocs: RelatedLoc[];
  nodeIds: string[];
  edgeIds: string[];
  stage: StageId | string;
  frameworks: string[];
  tags: string[];
  evidence: Evidence[];
  suppressed: boolean;
  docs?: string;
}

export interface GraphDiagnostic {
  kind: string;
  message: string;
  file?: string;
  line?: number;
  scope?: string;
  ruleCode?: string;
  codes?: string[];
  count?: number;
}

export interface Stats {
  nodes: number;
  edges: number;
  issues: IssueCounts;
  suppressed?: number;
  durationMs: number;
  truncated: boolean;
}

export interface MLGraph {
  schemaVersion: string;
  generator: Generator;
  workspace: Workspace;
  stages: Stage[];
  nodes: GraphNode[];
  edges: GraphEdge[];
  issues: Issue[];
  diagnostics: GraphDiagnostic[];
  stats: Stats;
}

export const STAGE_LABELS: ReadonlyArray<{ id: StageId; label: string }> = [
  { id: 'config', label: 'Configuration' },
  { id: 'data', label: 'Data' },
  { id: 'preprocess', label: 'Preprocess' },
  { id: 'model', label: 'Model' },
  { id: 'objective', label: 'Objective' },
  { id: 'train', label: 'Train' },
  { id: 'eval', label: 'Evaluate' },
  { id: 'deliver', label: 'Save / Deploy' }
];

export const SEVERITY_ORDER: Record<Severity, number> = { low: 0, medium: 1, high: 2 };

/** True when `severity` is at least `floor`. */
export function severityAtLeast(severity: Severity, floor: Severity): boolean {
  return SEVERITY_ORDER[severity] >= SEVERITY_ORDER[floor];
}

/** The MAJOR component of a `schemaVersion` string; hosts refuse a mismatch (§1). */
export function schemaMajor(version: string): string {
  const dot = version.indexOf('.');
  return dot === -1 ? version : version.slice(0, dot);
}

export function isSchemaCompatible(version: unknown): boolean {
  return typeof version === 'string' && schemaMajor(version) === schemaMajor(SCHEMA_VERSION);
}

/** Cheap structural validation — enough to reject "this is not an MLGraph" before use. */
export function looksLikeGraph(value: unknown): value is MLGraph {
  if (typeof value !== 'object' || value === null) {
    return false;
  }
  const g = value as Partial<MLGraph>;
  return (
    typeof g.schemaVersion === 'string' &&
    Array.isArray(g.nodes) &&
    Array.isArray(g.edges) &&
    Array.isArray(g.issues) &&
    Array.isArray(g.stages) &&
    typeof g.stats === 'object' &&
    g.stats !== null &&
    typeof g.workspace === 'object' &&
    g.workspace !== null
  );
}

/**
 * A schema-valid document with nothing in it. Used for exit code 4 ("nothing analyzable"),
 * which must land the viewer on its designed empty state rather than on a blank canvas.
 */
export function emptyGraph(root: string): MLGraph {
  return {
    schemaVersion: SCHEMA_VERSION,
    generator: {
      name: 'mlview',
      version: '0.0.0',
      rendererSha: '0'.repeat(64),
      generatedAt: new Date().toISOString().replace(/\.\d{3}Z$/, 'Z')
    },
    workspace: {
      root,
      entrypoints: [],
      filesAnalyzed: 0,
      filesFailed: 0,
      notebooksSkipped: 0,
      frameworks: []
    },
    stages: STAGE_LABELS.map((s, order) => ({
      id: s.id,
      label: s.label,
      order,
      present: false,
      nodeCount: 0,
      issueCounts: { low: 0, medium: 0, high: 0 },
      maxSeverity: null
    })),
    nodes: [],
    edges: [],
    issues: [],
    diagnostics: [],
    stats: {
      nodes: 0,
      edges: 0,
      issues: { low: 0, medium: 0, high: 0 },
      suppressed: 0,
      durationMs: 0,
      truncated: false
    }
  };
}

/** Total unsuppressed issue counts, used by the status bar and the digests. */
export function countIssues(issues: Issue[]): IssueCounts {
  const counts: IssueCounts = { low: 0, medium: 0, high: 0 };
  for (const issue of issues) {
    if (issue.suppressed) {
      continue;
    }
    if (issue.severity === 'high' || issue.severity === 'medium' || issue.severity === 'low') {
      counts[issue.severity] += 1;
    }
  }
  return counts;
}
