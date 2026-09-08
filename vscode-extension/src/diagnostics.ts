/**
 * The Problems panel integration — and, per ARCHITECTURE.md §6.3, the GitHub Copilot
 * integration that actually works today: Copilot Chat's `#problems` context, inline fix and
 * agent mode all read this collection, with zero Copilot API surface required.
 *
 * Mapping is frozen (CONTRACTS.md §6):
 *
 *   severity | mlview.diagnosticSeverity = "warning" (default) | = "error"
 *   high     | Warning                                          | Error
 *   medium   | Warning                                          | Warning
 *   low      | Information                                      | Information
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import * as vscode from 'vscode';
import type { Issue, MLGraph, Severity } from './graph';
import { publishedIssueFilter, selectIssues } from './issues';
import { toRangeTuple } from './location';
import type { Logger } from './log';
import type { DiagnosticSeverityMode, MlviewSettings } from './settings';

export const DIAGNOSTIC_SOURCE = 'MLView';
export const DIAGNOSTIC_COLLECTION_NAME = 'mlview';

export type DiagnosticSeverityName = 'error' | 'warning' | 'information';

/** The frozen table above, as a pure function. */
export function mapSeverity(severity: Severity, mode: DiagnosticSeverityMode): DiagnosticSeverityName {
  if (severity === 'high') {
    return mode === 'error' ? 'error' : 'warning';
  }
  if (severity === 'medium') {
    return 'warning';
  }
  return 'information';
}

export function toVsSeverity(name: DiagnosticSeverityName): vscode.DiagnosticSeverity {
  switch (name) {
    case 'error':
      return vscode.DiagnosticSeverity.Error;
    case 'warning':
      return vscode.DiagnosticSeverity.Warning;
    default:
      return vscode.DiagnosticSeverity.Information;
  }
}

export interface RuleDocLookup {
  /** `<extension>/docs/rules` — preferred, ships with the extension. */
  extensionDocsDir: string;
  /** `<repo>/docs/rules` — the dev-checkout fallback. */
  repoDocsDir?: string;
  exists?: (p: string) => boolean;
}

/**
 * A diagnostic's `code.target` must be a LOCAL file so rule docs work offline. Returns
 * undefined when neither location has a page, in which case the code is published as a
 * plain string.
 */
export function resolveRuleDocPath(code: string, lookup: RuleDocLookup): string | undefined {
  const exists = lookup.exists ?? fs.existsSync;
  const candidates = [path.join(lookup.extensionDocsDir, `${code}.md`)];
  if (lookup.repoDocsDir) {
    candidates.push(path.join(lookup.repoDocsDir, `${code}.md`));
  }
  for (const candidate of candidates) {
    try {
      if (exists(candidate)) {
        return candidate;
      }
    } catch {
      /* an unreadable path is simply not a doc */
    }
  }
  return undefined;
}

export interface BuildDiagnosticsOptions {
  mode: DiagnosticSeverityMode;
  ruleDocs?: RuleDocLookup;
}

function rangeOf(loc: { line: number; col: number; endLine: number; endCol: number }): vscode.Range {
  const t = toRangeTuple(loc);
  return new vscode.Range(t.startLine, t.startChar, t.endLine, t.endChar);
}

/**
 * Build the per-file diagnostics. Keyed by `absFile` so a file that drops to zero issues can be
 * cleared explicitly rather than left with stale squiggles.
 */
export function buildDiagnostics(
  issues: Issue[],
  opts: BuildDiagnosticsOptions
): Map<string, vscode.Diagnostic[]> {
  const byFile = new Map<string, vscode.Diagnostic[]>();
  for (const issue of issues) {
    const diagnostic = new vscode.Diagnostic(
      rangeOf(issue.loc),
      `${issue.title} — ${issue.message}\nFix: ${issue.fixHint}`,
      toVsSeverity(mapSeverity(issue.severity, opts.mode))
    );
    diagnostic.source = DIAGNOSTIC_SOURCE;
    const docPath = opts.ruleDocs ? resolveRuleDocPath(issue.code, opts.ruleDocs) : undefined;
    diagnostic.code = docPath
      ? { value: issue.code, target: vscode.Uri.file(docPath) }
      : issue.code;
    if (issue.relatedLocs.length > 0) {
      diagnostic.relatedInformation = issue.relatedLocs.map(
        (rel) =>
          new vscode.DiagnosticRelatedInformation(
            new vscode.Location(vscode.Uri.file(rel.absFile), rangeOf(rel)),
            rel.message ?? `${rel.role} (${rel.file}:${rel.line})`
          )
      );
    }
    const key = issue.loc.absFile;
    const list = byFile.get(key) ?? [];
    list.push(diagnostic);
    byFile.set(key, list);
  }
  return byFile;
}

/** Owns the `mlview` DiagnosticCollection and its lifecycle. */
export class DiagnosticsPublisher implements vscode.Disposable {
  private readonly collection: vscode.DiagnosticCollection;
  private readonly disposables: vscode.Disposable[] = [];
  private publishedFiles = new Set<string>();

  constructor(
    private readonly ctx: vscode.ExtensionContext,
    private readonly log: Logger
  ) {
    this.collection = vscode.languages.createDiagnosticCollection(DIAGNOSTIC_COLLECTION_NAME);
    this.disposables.push(
      this.collection,
      // A workspace-folder change invalidates every path we published.
      vscode.workspace.onDidChangeWorkspaceFolders(() => {
        this.log.info('workspace folders changed - clearing MLView diagnostics');
        this.clear();
      })
    );
  }

  private ruleDocs(): RuleDocLookup {
    const extensionDocsDir = path.join(this.ctx.extensionPath, 'docs', 'rules');
    const repoDocsDir = path.join(path.dirname(this.ctx.extensionPath), 'docs', 'rules');
    return { extensionDocsDir, repoDocsDir };
  }

  /** Publish the unsuppressed, sufficiently confident issues of one graph. */
  publish(graph: MLGraph, settings: MlviewSettings): number {
    if (!settings.diagnosticsEnabled) {
      this.clear();
      return 0;
    }
    const issues = selectIssues(graph, publishedIssueFilter(settings));
    const byFile = buildDiagnostics(issues, {
      mode: settings.diagnosticSeverity,
      ruleDocs: this.ruleDocs()
    });

    const nextFiles = new Set<string>();
    for (const [absFile, diagnostics] of byFile) {
      nextFiles.add(absFile);
      this.collection.set(vscode.Uri.file(absFile), diagnostics);
    }
    // Files that had issues last time and none now must be cleared explicitly.
    for (const stale of this.publishedFiles) {
      if (!nextFiles.has(stale)) {
        this.collection.delete(vscode.Uri.file(stale));
      }
    }
    this.publishedFiles = nextFiles;
    this.log.info(
      `published ${issues.length} diagnostic(s) across ${nextFiles.size} file(s) ` +
        `(minConfidence=${settings.minConfidence}, minSeverity=${settings.minSeverity})`
    );
    return issues.length;
  }

  clear(): void {
    this.collection.clear();
    this.publishedFiles.clear();
  }

  dispose(): void {
    for (const d of this.disposables) {
      d.dispose();
    }
  }
}
