/**
 * The `@mlview` chat participant (CONTRACTS.md §6).
 *
 * It NEVER calls a language model. Every answer is produced from the local <= 4 KB digest of a
 * static analysis run, so the participant works with no network, no API key and no Copilot
 * subscription — and it says so in its first response. Each finding is streamed as markdown
 * followed by a `stream.anchor(new vscode.Location(uri, range), 'file:line')`, so every line in
 * chat is a click into the source.
 */

import * as vscode from 'vscode';
import type { Issue, MLGraph, Severity } from './graph';
import { buildAnalyzeDigest, formatIssueLine } from './digest';
import { selectIssues } from './issues';
import type { Logger } from './log';
import type { CoreLike, ToolOptions } from './lmTools';
import { rangeFromLoc } from './panel';

export const PARTICIPANT_ID = 'mlview.chat';

const SEVERITY_WORD: Record<Severity, string> = {
  high: 'HIGH',
  medium: 'MEDIUM',
  low: 'LOW'
};

export interface ChatDeps {
  log: Logger;
  core: CoreLike;
  options(): ToolOptions;
  showDiagram(focusNodeId?: string, scopeSpec?: string): Promise<void>;
}

const LOCAL_NOTE =
  '_MLView answers from local static analysis only — no model call, no network, your code never leaves this machine._';

function anchorFor(stream: vscode.ChatResponseStream, issue: Issue): void {
  try {
    stream.anchor(
      new vscode.Location(vscode.Uri.file(issue.loc.absFile), rangeFromLoc(issue.loc)),
      `${issue.loc.file}:${issue.loc.line}`
    );
  } catch {
    stream.markdown(`\`${issue.loc.file}:${issue.loc.line}\`\n\n`);
  }
}

function streamIssue(stream: vscode.ChatResponseStream, issue: Issue): void {
  stream.markdown(
    `**${SEVERITY_WORD[issue.severity]} · ${issue.code}** — ${issue.title}\n\n` +
      `${issue.message}\n\n` +
      `*Why it matters:* ${issue.why}\n\n` +
      `*Fix:* ${issue.fixHint}\n\n`
  );
  anchorFor(stream, issue);
  stream.markdown('\n\n');
  for (const rel of issue.relatedLocs.slice(0, 3)) {
    stream.markdown(`- ${rel.message ?? rel.role}: `);
    try {
      stream.anchor(
        new vscode.Location(vscode.Uri.file(rel.absFile), rangeFromLoc(rel)),
        `${rel.file}:${rel.line}`
      );
    } catch {
      stream.markdown(`\`${rel.file}:${rel.line}\``);
    }
    stream.markdown('\n');
  }
  stream.markdown('\n');
}

function streamSummary(stream: vscode.ChatResponseStream, graph: MLGraph): void {
  const digest = buildAnalyzeDigest(graph);
  stream.markdown(
    `Analyzed **${digest.filesAnalyzed} file(s)** under \`${digest.root}\`` +
      (digest.frameworks.length ? ` — frameworks: ${digest.frameworks.join(', ')}` : '') +
      `.\n\n` +
      `**${digest.stats.nodes} nodes**, **${digest.stats.edges} edges**, ` +
      `**${digest.stats.issues.high} high / ${digest.stats.issues.medium} medium / ${digest.stats.issues.low} low** issues.\n\n`
  );
  if (digest.lanes.length > 0) {
    stream.markdown(
      `Pipeline: ${digest.lanes.map((l) => `**${l.label}** (${l.nodeCount})`).join(' → ')}\n\n`
    );
  }
  if (digest.truncated) {
    stream.markdown('_The graph was truncated by `mlview.maxNodes`; narrow the scope for the full picture._\n\n');
  }
}

function offerButtons(stream: vscode.ChatResponseStream): void {
  stream.button({ command: 'mlview.showIssues', title: 'Show issues' });
  stream.button({ command: 'mlview.visualizeWorkspace', title: 'Open the diagram' });
}

function findRuleCode(prompt: string): string | undefined {
  const match = /\bMLV[0-9]{3}\b/i.exec(prompt);
  return match ? match[0].toUpperCase() : undefined;
}

function findStage(prompt: string, graph: MLGraph): { id: string; label: string } | undefined {
  const lower = prompt.toLowerCase();
  for (const stage of graph.stages) {
    const id = String(stage.id).toLowerCase();
    if (lower.includes(id) || lower.includes(stage.label.toLowerCase())) {
      return { id: String(stage.id), label: stage.label };
    }
  }
  return undefined;
}

async function analyzeForChat(
  deps: ChatDeps,
  stream: vscode.ChatResponseStream,
  token: vscode.CancellationToken
): Promise<MLGraph | undefined> {
  stream.progress('Analyzing the workspace with MLView…');
  try {
    return await deps.core.analyze({}, token);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    stream.markdown(`MLView could not analyze this workspace: ${message}\n\n`);
    stream.button({ command: 'mlview.showOutput', title: 'Show MLView output' });
    stream.button({ command: 'mlview.selectInterpreter', title: 'Select Python interpreter' });
    deps.log.warn(`chat analysis failed: ${message}`);
    return undefined;
  }
}

export async function handleChatRequest(
  request: vscode.ChatRequest,
  stream: vscode.ChatResponseStream,
  token: vscode.CancellationToken,
  deps: ChatDeps
): Promise<vscode.ChatResult> {
  const command = request.command ?? '';
  const prompt = (request.prompt ?? '').trim();
  const opts = deps.options();

  if (command === 'diagram') {
    const graph = await analyzeForChat(deps, stream, token);
    if (!graph) {
      return {};
    }
    await deps.showDiagram();
    stream.markdown('Opened the MLView diagram beside the editor.\n\n');
    streamSummary(stream, graph);
    offerButtons(stream);
    stream.markdown(LOCAL_NOTE);
    return {};
  }

  if (command === 'issues') {
    const graph = await analyzeForChat(deps, stream, token);
    if (!graph) {
      return {};
    }
    const issues = selectIssues(graph, {
      minSeverity: opts.minSeverity ?? 'low',
      ...(opts.disabledRules ? { disabledRules: opts.disabledRules } : {})
    });
    if (issues.length === 0) {
      stream.markdown('No MLView issues were detected in this workspace.\n\n');
      offerButtons(stream);
      stream.markdown(LOCAL_NOTE);
      return {};
    }
    stream.markdown(`**${issues.length} issue(s)**, highest severity first.\n\n`);
    for (const issue of issues.slice(0, 12)) {
      streamIssue(stream, issue);
    }
    if (issues.length > 12) {
      stream.markdown(`…and ${issues.length - 12} more. Open the Problems panel for the full list.\n\n`);
    }
    offerButtons(stream);
    stream.markdown(LOCAL_NOTE);
    return {};
  }

  if (command === 'explain') {
    const graph = await analyzeForChat(deps, stream, token);
    if (!graph) {
      return {};
    }
    const code = findRuleCode(prompt);
    if (code) {
      const matches = graph.issues.filter((i) => i.code.toUpperCase() === code);
      if (matches.length === 0) {
        stream.markdown(
          `**${code}** did not fire in this workspace. Run \`/issues\` to see what did.\n\n`
        );
      } else {
        stream.markdown(`**${code}** fired ${matches.length} time(s):\n\n`);
        for (const issue of matches.slice(0, 5)) {
          streamIssue(stream, issue);
        }
      }
      stream.button({
        command: 'mlview.showRuleDoc',
        title: `Open the ${code} rule doc`,
        arguments: [code]
      });
      stream.markdown(LOCAL_NOTE);
      return {};
    }
    const stage = findStage(prompt, graph);
    if (stage) {
      const nodes = graph.nodes.filter((n) => String(n.stage) === stage.id);
      stream.markdown(
        `**${stage.label}** contains ${nodes.length} node(s):\n\n` +
          nodes
            .slice(0, 15)
            .map((n) => `- \`${n.label}\`${n.sublabel ? ` — ${n.sublabel}` : ''} (${n.loc.file}:${n.loc.line})`)
            .join('\n') +
          '\n\n'
      );
      const stageIssues = selectIssues(graph, {}).filter((i) => String(i.stage) === stage.id);
      for (const issue of stageIssues.slice(0, 5)) {
        streamIssue(stream, issue);
      }
      offerButtons(stream);
      stream.markdown(LOCAL_NOTE);
      return {};
    }
    stream.markdown(
      'Name a rule code (for example `MLV201`) or a pipeline stage ' +
        '(`config`, `data`, `preprocess`, `model`, `objective`, `train`, `eval`, `deliver`).\n\n'
    );
    streamSummary(stream, graph);
    offerButtons(stream);
    stream.markdown(LOCAL_NOTE);
    return {};
  }

  // Free-form.
  const graph = await analyzeForChat(deps, stream, token);
  if (!graph) {
    return {};
  }
  streamSummary(stream, graph);
  const issues = selectIssues(graph, {
    minSeverity: opts.minSeverity ?? 'low',
    ...(opts.disabledRules ? { disabledRules: opts.disabledRules } : {})
  });
  if (issues.length > 0) {
    stream.markdown('Highest-severity findings:\n\n');
    for (const issue of issues.slice(0, 5)) {
      stream.markdown(`- ${formatIssueLine({
        code: issue.code,
        severity: issue.severity,
        confidenceBucket: String(issue.confidenceBucket),
        title: issue.title,
        file: issue.loc.file,
        line: issue.loc.line
      })}\n  `);
      anchorFor(stream, issue);
      stream.markdown('\n');
    }
    stream.markdown('\n');
  }
  stream.markdown(
    'Try `/diagram` for the interactive map, `/issues` for every finding with a fix hint, ' +
      'or `/explain MLV201` for one rule.\n\n'
  );
  offerButtons(stream);
  stream.markdown(LOCAL_NOTE);
  return {};
}

/**
 * Registered only behind `typeof vscode.chat?.createChatParticipant === 'function'`; the id must
 * match the `chatParticipants` entry in package.json. `isSticky` is handled by the manifest.
 */
export function registerChat(ctx: vscode.ExtensionContext, deps: ChatDeps): void {
  const participant = vscode.chat.createChatParticipant(
    PARTICIPANT_ID,
    async (request, _context, stream, token) => handleChatRequest(request, stream, token, deps)
  );
  participant.iconPath = new vscode.ThemeIcon('graph');
  ctx.subscriptions.push(participant);
  deps.log.info(`chat participant registered: ${PARTICIPANT_ID}`);
}
