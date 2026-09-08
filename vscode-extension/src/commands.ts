/**
 * The self-contained command bodies (issue list, HTML export, rule docs), kept out of
 * extension.ts so the activation file stays about wiring.
 */

import * as path from 'node:path';
import * as vscode from 'vscode';
import type { CoreClient } from './coreClient';
import type { MLGraph } from './graph';
import { publishedIssueFilter, selectIssues } from './issues';
import type { Logger } from './log';
import { MlviewPanel, rangeFromLoc } from './panel';
import { nextRequestId, type AnalysisScope } from './protocol';
import { readSettings } from './settings';
import { ensureTrusted } from './trust';

/** What the command bodies need from the controller. */
export interface CommandHost {
  readonly ctx: vscode.ExtensionContext;
  readonly log: Logger;
  readonly core: CoreClient;
  getGraph(): MLGraph | undefined;
  /** Runs an analysis when there is no graph yet, then returns it. */
  ensureGraph(): Promise<MLGraph | undefined>;
  workspaceRoot(): string | undefined;
  /** The paths the current scope hands to the analyzer. */
  currentPaths(root: string): string[];
  currentScope(): AnalysisScope;
  reportError(err: unknown, requestId: string): void;
}

const SEVERITY_ICON: Record<string, string> = {
  high: '$(error)',
  medium: '$(warning)',
  low: '$(info)'
};

/** `MLView: Show ML Issues` — a quick pick that lands on the line, mirroring the Problems panel. */
export async function showIssues(host: CommandHost): Promise<void> {
  const graph = host.getGraph() ?? (await host.ensureGraph());
  if (!graph) {
    return;
  }
  const root = host.workspaceRoot();
  const settings = readSettings(root ? vscode.Uri.file(root) : undefined);
  // The SAME filter the Problems panel uses (`DiagnosticsPublisher.publish`) and the same one
  // the status bar counts, or the placeholder below would be a lie: mlview.minConfidence
  // defaults to 0.6, so an unfiltered pick lists findings Problems never shows.
  const issues = selectIssues(graph, publishedIssueFilter(settings));
  if (issues.length === 0) {
    void vscode.window.showInformationMessage('MLView found no issues in this workspace.');
    return;
  }
  const picked = await vscode.window.showQuickPick(
    issues.map((issue) => ({
      label: `${SEVERITY_ICON[issue.severity] ?? ''} ${issue.code} — ${issue.title}`,
      description: `${issue.loc.file}:${issue.loc.line}`,
      detail: issue.fixHint,
      issue
    })),
    {
      title: `MLView — ${issues.length} issue(s)`,
      placeHolder: 'Select a finding to open it (the Problems panel has the same list)',
      matchOnDescription: true,
      matchOnDetail: true
    }
  );
  if (!picked) {
    return;
  }
  MlviewPanel.current?.postRevealIssue(picked.issue.id);
  const loc = picked.issue.loc;
  try {
    const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(loc.absFile));
    const editor = await vscode.window.showTextDocument(doc, {
      viewColumn: vscode.ViewColumn.One
    });
    // rangeFromLoc -> toRangeTuple is the single 1-based -> 0-based conversion (CONTRACTS.md §0).
    const position = rangeFromLoc(loc).start;
    editor.selection = new vscode.Selection(position, position);
    editor.revealRange(
      new vscode.Range(position, position),
      vscode.TextEditorRevealType.InCenterIfOutsideViewport
    );
  } catch (err) {
    host.log.error(`could not open ${loc.absFile}`, err);
  }
}

/** `MLView: Export HTML Report` — save dialog, then `analyze --html <file>`. */
export async function exportHtml(host: CommandHost): Promise<void> {
  // Restricted Mode: `core.exportHtml` would run the whole interpreter chain and then the
  // analyzer. Refuse before the save dialog, exactly like `runAnalysis` (CONTRACTS.md §6).
  if (!ensureTrusted(host.log)) {
    return;
  }
  const root = host.workspaceRoot();
  if (!root) {
    void vscode.window.showWarningMessage('MLView: open a folder before exporting a report.');
    return;
  }
  const target = await vscode.window.showSaveDialog({
    title: 'Export MLView report',
    defaultUri: vscode.Uri.file(path.join(root, 'mlview-report.html')),
    filters: { 'HTML report': ['html'] }
  });
  if (!target) {
    return;
  }
  // What you see is what you export: a diagram narrowed to `concern:evaluation` must not
  // export the whole workspace with nothing said about it. The report still embeds the FULL
  // graph (§11.8) - the selector only decides which projection it opens on, so the scope
  // narrows the view and never loses data. Undefined when no panel is open or it is unscoped.
  const diagram = MlviewPanel.current;
  const active = diagram && !diagram.isDisposed ? diagram.activeScope : undefined;
  await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: 'MLView: writing report…' },
    async () => {
      try {
        await host.core.exportHtml({
          scope: host.currentScope(),
          paths: host.currentPaths(root),
          cwd: root,
          // Resource-scoped, exactly like the analysis behind the diagram: without this the
          // report is generated with the USER-level maxNodes / maxFiles / exclude and silently
          // differs from what the user is looking at.
          settings: readSettings(vscode.Uri.file(root)),
          outFile: target.fsPath,
          scopeSpec: active?.spec,
          depth: active?.depth
        });
        const choice = await vscode.window.showInformationMessage(
          active
            ? `MLView report written to ${target.fsPath} (scoped to ${active.spec})`
            : `MLView report written to ${target.fsPath}`,
          'Open'
        );
        if (choice === 'Open') {
          await vscode.env.openExternal(target);
        }
      } catch (err) {
        host.reportError(err, nextRequestId('export'));
      }
    }
  );
}

/**
 * `MLView: Open Rule Documentation` — the extension's own offline copy first, then the repo
 * checkout, then a summary from the finding itself.
 */
export async function showRuleDoc(host: CommandHost, code?: string): Promise<void> {
  let ruleCode = typeof code === 'string' ? code.trim().toUpperCase() : '';
  if (!/^MLV[0-9]{3}$/.test(ruleCode)) {
    const codes = Array.from(new Set((host.getGraph()?.issues ?? []).map((i) => i.code))).sort();
    const picked = codes.length
      ? await vscode.window.showQuickPick(codes, { title: 'MLView rule documentation' })
      : await vscode.window.showInputBox({
          title: 'MLView rule documentation',
          prompt: 'Rule code, e.g. MLV201',
          validateInput: (v) => (/^MLV[0-9]{3}$/i.test(v.trim()) ? undefined : 'Expected MLVnnn')
        });
    if (!picked) {
      return;
    }
    ruleCode = picked.trim().toUpperCase();
  }
  const candidates = [
    path.join(host.ctx.extensionPath, 'docs', 'rules', `${ruleCode}.md`),
    path.join(path.dirname(host.ctx.extensionPath), 'docs', 'rules', `${ruleCode}.md`)
  ];
  for (const candidate of candidates) {
    const uri = vscode.Uri.file(candidate);
    try {
      await vscode.workspace.fs.stat(uri);
    } catch {
      continue;
    }
    try {
      await vscode.commands.executeCommand('markdown.showPreview', uri);
    } catch {
      await vscode.window.showTextDocument(uri);
    }
    return;
  }
  const issue = host.getGraph()?.issues.find((i) => i.code.toUpperCase() === ruleCode);
  if (issue) {
    void vscode.window.showInformationMessage(
      `${ruleCode}: ${issue.title}. ${issue.why} Fix: ${issue.fixHint}`
    );
    return;
  }
  void vscode.window.showWarningMessage(
    `MLView: no offline documentation found for ${ruleCode}. ` +
      'Generate the rule pages into docs/rules/ and reload the window.'
  );
}
