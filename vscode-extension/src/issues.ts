/**
 * Issue selection and ordering, shared by the Problems panel, the chat participant and the
 * language-model digests so that all three agree on what "an issue" is.
 */

import { SEVERITY_ORDER, severityAtLeast, type Issue, type MLGraph, type Severity } from './graph';

export interface IssueFilter {
  /** Lowest severity kept. */
  minSeverity?: Severity;
  /** Lowest confidence kept. Diagnostics use `mlview.minConfidence`; the canvas keeps all. */
  minConfidence?: number;
  /** Rule codes to drop, e.g. `['MLV601']`. */
  disabledRules?: string[];
  /** Suppressed issues are emitted by the analyzer but never published. */
  includeSuppressed?: boolean;
  /** Keep only this rule code. */
  code?: string;
}

/** `(severity desc, confidence desc, file, line, code)` — stable and demo-friendly. */
export function compareIssues(a: Issue, b: Issue): number {
  const sev = SEVERITY_ORDER[b.severity] - SEVERITY_ORDER[a.severity];
  if (sev !== 0) {
    return sev;
  }
  const conf = (b.confidence ?? 0) - (a.confidence ?? 0);
  if (conf !== 0) {
    return conf;
  }
  const file = a.loc.file.localeCompare(b.loc.file);
  if (file !== 0) {
    return file;
  }
  if (a.loc.line !== b.loc.line) {
    return a.loc.line - b.loc.line;
  }
  return a.code.localeCompare(b.code);
}

export function selectIssues(graph: MLGraph, filter: IssueFilter = {}): Issue[] {
  const disabled = new Set((filter.disabledRules ?? []).map((c) => c.toUpperCase()));
  const wanted = filter.code?.trim().toUpperCase();
  const minConfidence = filter.minConfidence ?? 0;
  const minSeverity = filter.minSeverity ?? 'low';
  return graph.issues
    .filter((issue) => {
      if (!filter.includeSuppressed && issue.suppressed) {
        return false;
      }
      if (disabled.has(issue.code.toUpperCase())) {
        return false;
      }
      if (wanted && issue.code.toUpperCase() !== wanted) {
        return false;
      }
      if ((issue.confidence ?? 0) < minConfidence) {
        return false;
      }
      return severityAtLeast(issue.severity, minSeverity);
    })
    .slice()
    .sort(compareIssues);
}

/** The three settings that decide whether a finding is shown outside the canvas. */
export interface PublishedIssueSettings {
  minSeverity: Severity;
  minConfidence: number;
  disabledRules: string[];
}

/**
 * THE filter shared by every issue surface outside the diagram canvas: the Problems panel
 * (`DiagnosticsPublisher.publish`), the status-bar counts and the `MLView: Show ML Issues`
 * quick pick. They must agree — the quick pick tells the user it mirrors the Problems panel,
 * and `mlview.minConfidence` (default 0.6) is exactly what pulls them apart when it does not.
 * The canvas deliberately keeps the lower-confidence findings, and only the canvas.
 */
export function publishedIssueFilter(settings: PublishedIssueSettings): IssueFilter {
  return {
    minSeverity: settings.minSeverity,
    minConfidence: settings.minConfidence,
    disabledRules: settings.disabledRules,
    includeSuppressed: false
  };
}

/**
 * The KEEP-list the diagram is sent for `mlview.disabledRules` (the viewer's `setCodes`).
 *
 * Every rule code present in the graph, minus the disabled ones. When the setting disables
 * everything the graph contains, the list would be empty — which the viewer reads as "no
 * restriction" — so a code that can never match is sent instead.
 */
export const NO_RULE_CODES = 'MLV-none';

export function allowedRuleCodes(graph: MLGraph, disabledRules: string[]): string[] {
  const disabled = new Set(disabledRules.map((c) => c.trim().toUpperCase()).filter(Boolean));
  const present = Array.from(new Set(graph.issues.map((i) => i.code.toUpperCase()))).sort();
  if (disabled.size === 0) {
    return [];
  }
  const allowed = present.filter((code) => !disabled.has(code));
  return allowed.length > 0 ? allowed : [NO_RULE_CODES];
}

/** The severity glyph words used in chat and hovers. Never colour alone. */
export const SEVERITY_GLYPH: Record<Severity, string> = {
  high: '$(error)',
  medium: '$(warning)',
  low: '$(info)'
};

export const SEVERITY_MARKDOWN: Record<Severity, string> = {
  high: 'HIGH',
  medium: 'MEDIUM',
  low: 'LOW'
};

export function truncate(text: string, max: number): string {
  const clean = text.replace(/\s+/g, ' ').trim();
  return clean.length <= max ? clean : `${clean.slice(0, Math.max(0, max - 1))}…`;
}
