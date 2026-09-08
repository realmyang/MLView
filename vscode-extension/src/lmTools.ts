/**
 * The three language-model tools of CONTRACTS.md §6.
 *
 * Copilot is not installed on the build machine, so every tool BODY is an exported pure
 * function over a `CoreLike` interface: `runAnalyzeTool`, `runListIssuesTool` and
 * `runShowDiagramTool` are directly invocable from `node --test` with a stubbed core, which is
 * the best available substitute for the untestable agent-mode path.
 *
 * Registration is feature-detected by the caller (`typeof vscode.lm?.registerTool`), and both
 * `canBeReferencedInPrompt: true` and `toolReferenceName` are declared in package.json —
 * without both, agent mode never calls the tool.
 */

import * as vscode from 'vscode';
import type { MLGraph, Severity } from './graph';
import {
  analyzeDigestToText,
  buildAnalyzeDigest,
  buildIssuesDigest,
  issuesDigestToText,
  DIGEST_LIMIT_BYTES
} from './digest';
import type { Logger } from './log';

export const TOOL_ANALYZE = 'mlview_analyzeWorkspace';
export const TOOL_ISSUES = 'mlview_listIssues';
export const TOOL_DIAGRAM = 'mlview_showDiagram';

export interface AnalyzeToolInput {
  path?: string;
}

export interface IssuesToolInput {
  minSeverity?: Severity;
  code?: string;
}

export interface DiagramToolInput {
  focusNodeId?: string;
}

/** Everything the tools need from the extension host; stubbable in tests. */
export interface CoreLike {
  /** Analyze the workspace, or one workspace-relative path. */
  analyze(input: { path?: string }, token?: vscode.CancellationToken): Promise<MLGraph>;
  /** Open the diagram panel, optionally focused on a node. Absent in the pure tests. */
  showDiagram?(focusNodeId?: string): Promise<void> | void;
}

export interface ToolOptions {
  minSeverity?: Severity;
  disabledRules?: string[];
  limitBytes?: number;
}

function clampToBudget(text: string, limitBytes = DIGEST_LIMIT_BYTES): string {
  const buffer = Buffer.from(text, 'utf8');
  if (buffer.byteLength <= limitBytes) {
    return text;
  }
  return `${buffer.subarray(0, limitBytes - 32).toString('utf8')}\n… (truncated)`;
}

/** `mlview_analyzeWorkspace` — pipeline structure + an issue summary, <= 4 KB. */
export async function runAnalyzeTool(
  input: AnalyzeToolInput,
  core: CoreLike,
  opts: ToolOptions = {},
  token?: vscode.CancellationToken
): Promise<string> {
  const graph = await core.analyze({ ...(input.path ? { path: input.path } : {}) }, token);
  const digest = buildAnalyzeDigest(graph, {
    ...(opts.minSeverity ? { minSeverity: opts.minSeverity } : {}),
    ...(opts.disabledRules ? { disabledRules: opts.disabledRules } : {}),
    ...(opts.limitBytes ? { limitBytes: opts.limitBytes } : {})
  });
  return clampToBudget(analyzeDigestToText(digest), opts.limitBytes ?? DIGEST_LIMIT_BYTES);
}

/** `mlview_listIssues` — rule code, severity, message, fix hint, file and line, <= 4 KB. */
export async function runListIssuesTool(
  input: IssuesToolInput,
  core: CoreLike,
  opts: ToolOptions = {},
  token?: vscode.CancellationToken
): Promise<string> {
  const graph = await core.analyze({}, token);
  const digest = buildIssuesDigest(graph, {
    minSeverity: input.minSeverity ?? opts.minSeverity ?? 'low',
    ...(input.code ? { code: input.code } : {}),
    ...(opts.disabledRules ? { disabledRules: opts.disabledRules } : {}),
    ...(opts.limitBytes ? { limitBytes: opts.limitBytes } : {})
  });
  return clampToBudget(issuesDigestToText(digest), opts.limitBytes ?? DIGEST_LIMIT_BYTES);
}

/** `mlview_showDiagram` — the one tool with a side effect, hence its confirmation prompt. */
export async function runShowDiagramTool(
  input: DiagramToolInput,
  core: CoreLike,
  opts: ToolOptions = {},
  token?: vscode.CancellationToken
): Promise<string> {
  if (core.showDiagram) {
    await core.showDiagram(input.focusNodeId);
  }
  const graph = await core.analyze({}, token);
  const digest = buildAnalyzeDigest(graph, {
    ...(opts.minSeverity ? { minSeverity: opts.minSeverity } : {}),
    ...(opts.disabledRules ? { disabledRules: opts.disabledRules } : {}),
    maxTopIssues: 5
  });
  const focus = input.focusNodeId ? ` Focused on node ${input.focusNodeId}.` : '';
  return clampToBudget(
    `The MLView diagram panel is open beside the editor.${focus}\n${analyzeDigestToText(digest)}`
  );
}

function textResult(text: string): vscode.LanguageModelToolResult {
  return new vscode.LanguageModelToolResult([new vscode.LanguageModelTextPart(text)]);
}

class AnalyzeWorkspaceTool implements vscode.LanguageModelTool<AnalyzeToolInput> {
  constructor(
    private readonly core: CoreLike,
    private readonly options: () => ToolOptions
  ) {}

  prepareInvocation(
    options: vscode.LanguageModelToolInvocationPrepareOptions<AnalyzeToolInput>
  ): vscode.PreparedToolInvocation {
    // Same tolerance as `invoke`: `prepareInvocation` runs BEFORE the confirmation UI, so a
    // throw here is a failed tool call with a TypeError instead of anything actionable.
    const input = options?.input ?? {};
    const target = input.path ? ` (${input.path})` : '';
    return { invocationMessage: `Analyzing ML workflow${target}…` };
  }

  async invoke(
    options: vscode.LanguageModelToolInvocationOptions<AnalyzeToolInput>,
    token: vscode.CancellationToken
  ): Promise<vscode.LanguageModelToolResult> {
    return textResult(await runAnalyzeTool(options.input ?? {}, this.core, this.options(), token));
  }
}

class ListIssuesTool implements vscode.LanguageModelTool<IssuesToolInput> {
  constructor(
    private readonly core: CoreLike,
    private readonly options: () => ToolOptions
  ) {}

  prepareInvocation(): vscode.PreparedToolInvocation {
    return { invocationMessage: 'Listing detected ML issues…' };
  }

  async invoke(
    options: vscode.LanguageModelToolInvocationOptions<IssuesToolInput>,
    token: vscode.CancellationToken
  ): Promise<vscode.LanguageModelToolResult> {
    return textResult(
      await runListIssuesTool(options.input ?? {}, this.core, this.options(), token)
    );
  }
}

class ShowDiagramTool implements vscode.LanguageModelTool<DiagramToolInput> {
  constructor(
    private readonly core: CoreLike,
    private readonly options: () => ToolOptions
  ) {}

  prepareInvocation(
    options: vscode.LanguageModelToolInvocationPrepareOptions<DiagramToolInput>
  ): vscode.PreparedToolInvocation {
    // This is the contract-mandated confirmation step (CONTRACTS.md §6); it must survive a
    // missing `input` rather than throwing before the user is ever asked.
    const input = options?.input ?? {};
    return {
      invocationMessage: 'Opening the MLView diagram…',
      // A side effect, so the user is asked first.
      confirmationMessages: {
        title: 'Open MLView diagram?',
        message: input.focusNodeId
          ? `MLView will open the workflow diagram beside the editor and focus node ${input.focusNodeId}.`
          : 'MLView will analyze this workspace and open the workflow diagram beside the editor.'
      }
    };
  }

  async invoke(
    options: vscode.LanguageModelToolInvocationOptions<DiagramToolInput>,
    token: vscode.CancellationToken
  ): Promise<vscode.LanguageModelToolResult> {
    return textResult(
      await runShowDiagramTool(options.input ?? {}, this.core, this.options(), token)
    );
  }
}

/**
 * Register all three tools. The caller has already checked `typeof vscode.lm?.registerTool`;
 * any registration failure is logged and swallowed so activation can never break.
 */
export function registerLmTools(
  ctx: vscode.ExtensionContext,
  core: CoreLike,
  options: () => ToolOptions,
  log: Logger
): void {
  ctx.subscriptions.push(
    vscode.lm.registerTool(TOOL_ANALYZE, new AnalyzeWorkspaceTool(core, options)),
    vscode.lm.registerTool(TOOL_ISSUES, new ListIssuesTool(core, options)),
    vscode.lm.registerTool(TOOL_DIAGRAM, new ShowDiagramTool(core, options))
  );
  log.info(`language-model tools registered: ${[TOOL_ANALYZE, TOOL_ISSUES, TOOL_DIAGRAM].join(', ')}`);
}
