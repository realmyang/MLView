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

/**
 * H10 (11.40): the §11.1 selector every tool now accepts. §11.11 cut `scope` from the LM
 * tools for v1, which left the two hosts describing DIFFERENT products — the MCP tools take
 * the whole grammar while Copilot agent mode could not ask about `concern:evaluation` — and
 * the flags were already built by `buildAnalyzeArgs({scopeSpec, depth})`.
 *
 * `stages` and `units` stay MCP-only on purpose: they are catalogue payloads that tool shapes
 * as JSON rows, not projections of the document, and `--scope stages` is a `bad_selector`
 * refusal at the CLI. Everything the CLI accepts, these tools accept — including
 * `pipeline:<entrypoint.py>` (MLV-P12, 11.47), which is why this comment names the grammar in
 * one place: §11.16 moves the two `project()` implementations, the parity fixtures, the MCP
 * docstring and this vocabulary together or not at all.
 */
export interface ScopedToolInput {
  /**
   * `all`, `stage:`, `unit:`, `file:`, `concern:`, `node:`, `pipeline:` or `symbol:` — the
   * §11.1 grammar, spelled the same way in every host (the MCP server's `mlview_graph`
   * docstring, `mlview analyze --scope` and this tool all read one vocabulary).
   *
   * `pipeline:<entrypoint.py>` (MLV-P12, 11.47) is the newest kind: everything one workspace
   * entrypoint reaches over data and call edges plus containment. A node reachable from two
   * entrypoints is shared and comes back as `context`, so a `pipeline:` answer is about one
   * script's own work and says so.
   */
  scope?: string;
  /** 0, 1 or 2 boundary hops. Ignored without a scope. */
  depth?: number;
}

export interface AnalyzeToolInput extends ScopedToolInput {
  path?: string;
}

export interface IssuesToolInput extends ScopedToolInput {
  minSeverity?: Severity;
  code?: string;
}

export interface DiagramToolInput extends ScopedToolInput {
  focusNodeId?: string;
}

/** The analyze request the tools make of the host. */
export interface ToolAnalyzeInput extends ScopedToolInput {
  path?: string;
}

/** Everything the tools need from the extension host; stubbable in tests. */
export interface CoreLike {
  /** Analyze the workspace, or one workspace-relative path, optionally projected. */
  analyze(input: ToolAnalyzeInput, token?: vscode.CancellationToken): Promise<MLGraph>;
  /** Open the diagram panel, optionally focused on a node and narrowed to a scope. */
  showDiagram?(focusNodeId?: string, scopeSpec?: string): Promise<void> | void;
}

/**
 * The scope/depth pair as the host passes it on, dropping an empty or non-integer depth.
 * A model that sends `depth: "2"` or `depth: 5` gets the per-kind default rather than a
 * refusal it cannot act on; a scope it invents is a refusal, because a silently substituted
 * default would answer a question nobody asked (the MCP tools make the same distinction).
 */
export function scopeArgs(input: ScopedToolInput): { scopeSpec?: string; depth?: number } {
  const spec = typeof input.scope === 'string' ? input.scope.trim() : '';
  if (!spec) {
    return {};
  }
  const depth = input.depth;
  const clean =
    typeof depth === 'number' && Number.isInteger(depth) && depth >= 0 && depth <= 2
      ? depth
      : undefined;
  return { scopeSpec: spec, ...(clean !== undefined ? { depth: clean } : {}) };
}

/** One line naming the projection, so a scoped answer never reads as a project-wide one. */
export function scopeNote(input: ScopedToolInput): string {
  const { scopeSpec, depth } = scopeArgs(input);
  if (!scopeSpec) {
    return '';
  }
  const hops = depth === undefined ? '' : ` at depth ${depth}`;
  return (
    `This is a filtered view of ${scopeSpec}${hops}: the counts below describe that scope, ` +
    'not the whole project. Re-run without a scope for the project-wide numbers.\n'
  );
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
  const graph = await core.analyze(
    { ...(input.path ? { path: input.path } : {}), ...scopeArgs(input) },
    token
  );
  const digest = buildAnalyzeDigest(graph, {
    ...(opts.minSeverity ? { minSeverity: opts.minSeverity } : {}),
    ...(opts.disabledRules ? { disabledRules: opts.disabledRules } : {}),
    ...(opts.limitBytes ? { limitBytes: opts.limitBytes } : {})
  });
  return clampToBudget(
    scopeNote(input) + analyzeDigestToText(digest),
    opts.limitBytes ?? DIGEST_LIMIT_BYTES
  );
}

/** `mlview_listIssues` — rule code, severity, message, fix hint, file and line, <= 4 KB. */
export async function runListIssuesTool(
  input: IssuesToolInput,
  core: CoreLike,
  opts: ToolOptions = {},
  token?: vscode.CancellationToken
): Promise<string> {
  const graph = await core.analyze(scopeArgs(input), token);
  const digest = buildIssuesDigest(graph, {
    minSeverity: input.minSeverity ?? opts.minSeverity ?? 'low',
    ...(input.code ? { code: input.code } : {}),
    ...(opts.disabledRules ? { disabledRules: opts.disabledRules } : {}),
    ...(opts.limitBytes ? { limitBytes: opts.limitBytes } : {})
  });
  return clampToBudget(
    scopeNote(input) + issuesDigestToText(digest),
    opts.limitBytes ?? DIGEST_LIMIT_BYTES
  );
}

/** `mlview_showDiagram` — the one tool with a side effect, hence its confirmation prompt. */
export async function runShowDiagramTool(
  input: DiagramToolInput,
  core: CoreLike,
  opts: ToolOptions = {},
  token?: vscode.CancellationToken
): Promise<string> {
  const { scopeSpec, depth } = scopeArgs(input);
  if (core.showDiagram) {
    await core.showDiagram(input.focusNodeId, scopeSpec);
  }
  const graph = await core.analyze(scopeArgs(input), token);
  const digest = buildAnalyzeDigest(graph, {
    ...(opts.minSeverity ? { minSeverity: opts.minSeverity } : {}),
    ...(opts.disabledRules ? { disabledRules: opts.disabledRules } : {}),
    maxTopIssues: 5
  });
  const focus = input.focusNodeId ? ` Focused on node ${input.focusNodeId}.` : '';
  const scoped = scopeSpec
    ? ` Narrowed to ${scopeSpec}${depth === undefined ? '' : ` at depth ${depth}`}; the reader can widen or clear the scope in the diagram's own toolbar.`
    : '';
  return clampToBudget(
    `The MLView diagram panel is open beside the editor.${focus}${scoped}\n` +
      `${scopeNote(input)}${analyzeDigestToText(digest)}`
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
    const scope = scopeArgs(input).scopeSpec;
    return {
      invocationMessage: `Analyzing ML workflow${target}${scope ? ` — ${scope}` : ''}…`
    };
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
