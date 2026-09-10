/**
 * The OPTIONAL host surfaces: the chat participant and the language-model tools.
 *
 * They are registered after the diagram, diagnostics, reveal, CodeLens and status bar
 * (CONTRACTS.md §6) and behind `typeof` guards inside try/catch, so a chat-API change on a
 * future VS Code can never break activation. Kept out of extension.ts so the activation file
 * stays about wiring and stays inside the repo's ~600-line file budget.
 */

import * as vscode from 'vscode';
import { registerChat, type ChatDeps } from './chat';
import type { Logger } from './log';
import { registerLmTools, type CoreLike, type ToolOptions } from './lmTools';
import { readSettings } from './settings';

/** What the two optional surfaces need from the controller. */
export interface ChatSurfaceHost {
  readonly ctx: vscode.ExtensionContext;
  readonly log: Logger;
  /** The CONTROLLER (not `CoreClient`): chat and the tools analyze through it. */
  readonly analyzer: CoreLike;
  /** Opens the diagram and, when a node is named, reveals it. */
  showDiagram(focusNodeId?: string): Promise<void>;
}

/** The settings the chat and tool answers filter by, re-read on every request. */
export function toolOptions(): ToolOptions {
  const settings = readSettings();
  return { minSeverity: settings.minSeverity, disabledRules: settings.disabledRules };
}

/**
 * True when this VS Code build exposes the chat API the participant is registered against.
 *
 * The panel reads it for `capabilities.canAskAssistant` (CLEANUP 5): the diagram's "Ask the
 * assistant" affordance is offered exactly when there is an assistant to open, and the check
 * lives here so there is one `typeof` guard and not two that can drift apart.
 */
export function chatAvailable(): boolean {
  return typeof vscode.chat?.createChatParticipant === 'function';
}

export function registerChatSurfaces(host: ChatSurfaceHost): void {
  if (chatAvailable()) {
    try {
      const deps: ChatDeps = {
        log: host.log,
        core: host.analyzer,
        options: () => toolOptions(),
        showDiagram: (focusNodeId?: string) => host.showDiagram(focusNodeId)
      };
      registerChat(host.ctx, deps);
    } catch (e) {
      host.log.warn(`chat participant not registered: ${String(e)}`);
    }
  } else {
    host.log.info('chat API unavailable - participant not registered');
  }

  if (typeof vscode.lm?.registerTool === 'function') {
    try {
      registerLmTools(host.ctx, host.analyzer, () => toolOptions(), host.log);
    } catch (e) {
      host.log.warn(`LM tools not registered: ${String(e)}`);
    }
  } else {
    host.log.info('language-model tool API unavailable - tools not registered');
  }
}

/**
 * CLEANUP 5 — the diagram-to-chat path. The viewer composes the prompt (UX_DESIGN §7)
 * and posts `askAssistant`; the host's whole job is to open chat with it, addressed to
 * the `@mlview` participant this extension already registers.
 *
 * `workbench.action.chat.open` is a built-in command, not a typed API, so a build that
 * does not have it must degrade to the same "nothing happened, and we said why" the rest
 * of the optional surfaces use — never to a failed promise the webview cannot see. It
 * lives here rather than in `panel.ts` because it is one more optional chat surface, and
 * because `chatAvailable()` is already the single `typeof` guard for all of them.
 */
export async function openAssistantChat(
  nodeId: string,
  prompt: string,
  log: Logger
): Promise<void> {
  if (!chatAvailable()) {
    log.info(`askAssistant ignored for node ${nodeId}: no chat API in this build`);
    return;
  }
  try {
    await vscode.commands.executeCommand('workbench.action.chat.open', {
      query: `@mlview ${prompt}`
    });
    log.debug(`askAssistant opened chat for node ${nodeId}`);
  } catch (err) {
    log.warn(`askAssistant could not open chat: ${String(err)}`);
  }
}
