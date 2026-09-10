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
import { toRangeTuple, type RangeTuple } from './location';
import {
  openNotebooks,
  resolveNotebookTarget,
  type NotebookDocumentLike
} from './notebooks';

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
  /**
   * NB: the open notebooks, so a finding inside an `.ipynb` can be published on the
   * `vscode-notebook-cell:` uri of the cell it is actually in. Defaults to
   * `vscode.workspace.notebookDocuments`; a test passes its own list. An empty list is not an
   * error - it means no notebook is open, and those findings fall back to the file uri.
   */
  notebooks?: readonly NotebookDocumentLike[];
  /**
   * NB: `graph.workspace.root`. The notebook paths a finding carries are workspace-relative,
   * so without a root there is nothing to resolve them against and the notebook path is not
   * taken — which is what an older core, or a caller that has no graph, gets.
   */
  root?: string;
}

/**
 * NB: one finding's publishing address. `uri` is the `.py` file for ordinary code, and the
 * `vscode-notebook-cell:` document of the owning cell for a notebook finding, which is the
 * only uri VS Code will actually draw a squiggle on inside a notebook.
 */
export interface DiagnosticTarget {
  uri: vscode.Uri;
  diagnostics: vscode.Diagnostic[];
}

function toRange(t: RangeTuple): vscode.Range {
  return new vscode.Range(t.startLine, t.startChar, t.endLine, t.endChar);
}

interface ResolvedLocation {
  uri: vscode.Uri;
  range: vscode.Range;
}

/**
 * NB: where one finding's squiggle goes. A finding inside a notebook is re-anchored onto the
 * cell the user is looking at; everything else keeps the file uri and the flat range it has
 * always had. `relatedLocs` are deliberately NOT re-anchored: they carry no evidence, so the
 * cell they came from is not recoverable, and the generated module they name is a real file
 * that re-opens and slices correctly (R2.1).
 */
function locate(
  issue: { loc: Issue['loc']; evidence?: Issue['evidence'] },
  ctx: { root: string; notebooks: readonly NotebookDocumentLike[] }
): ResolvedLocation {
  const notebook = ctx.root ? resolveNotebookTarget(issue, ctx) : undefined;
  if (notebook) {
    return { uri: notebook.uri, range: toRange(notebook.range) };
  }
  return {
    uri: vscode.Uri.file(issue.loc.absFile),
    range: toRange(toRangeTuple(issue.loc))
  };
}

/**
 * Build the per-target diagnostics. Keyed by `uri.toString()` - which is `absFile` in all but
 * name for a `.py` file, and the distinct cell uri for each cell of a notebook - so a file (or
 * a cell) that drops to zero issues can be cleared explicitly rather than left with stale
 * squiggles.
 */
export function buildDiagnostics(
  issues: Issue[],
  opts: BuildDiagnosticsOptions
): Map<string, DiagnosticTarget> {
  const ctx = { root: opts.root ?? '', notebooks: opts.notebooks ?? openNotebooks() };
  const byTarget = new Map<string, DiagnosticTarget>();
  for (const issue of issues) {
    const where = locate(issue, ctx);
    const diagnostic = new vscode.Diagnostic(
      where.range,
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
            new vscode.Location(vscode.Uri.file(rel.absFile), toRange(toRangeTuple(rel))),
            rel.message ?? `${rel.role} (${rel.file}:${rel.line})`
          )
      );
    }
    const key = where.uri.toString();
    const target = byTarget.get(key) ?? { uri: where.uri, diagnostics: [] };
    target.diagnostics.push(diagnostic);
    byTarget.set(key, target);
  }
  return byTarget;
}

/** Owns the `mlview` DiagnosticCollection and its lifecycle. */
export class DiagnosticsPublisher implements vscode.Disposable {
  private readonly collection: vscode.DiagnosticCollection;
  private readonly disposables: vscode.Disposable[] = [];
  private publishedFiles = new Map<string, vscode.Uri>();

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
    const byTarget = buildDiagnostics(issues, {
      mode: settings.diagnosticSeverity,
      ruleDocs: this.ruleDocs(),
      root: graph.workspace.root
    });

    const nextFiles = new Map<string, vscode.Uri>();
    for (const [key, target] of byTarget) {
      nextFiles.set(key, target.uri);
      this.collection.set(target.uri, target.diagnostics);
    }
    // Targets that had issues last time and none now must be cleared explicitly. NB: the key
    // is the uri, so closing the last cell of a notebook clears that cell's entry too.
    for (const [stale, uri] of this.publishedFiles) {
      if (!nextFiles.has(stale)) {
        this.collection.delete(uri);
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
