/**
 * Workspace trust, in one place.
 *
 * `package.json` declares `capabilities.untrustedWorkspaces = { supported: "limited" }` and
 * CONTRACTS.md §6 froze the promise behind it: MLView spawns a Python interpreter, so in
 * Restricted Mode it spawns NOTHING — not the analyzer, not the `--version` handshake, not the
 * interpreter probe. Every entry point that can reach `CoreClient` therefore asks here first,
 * and `CoreClient.spawn()` asks again at the process seam itself so a future caller cannot
 * forget (that is the check that actually holds the promise; the ones above it exist to give
 * the user a warning instead of an error banner).
 */

import * as vscode from 'vscode';
import type { Logger } from './log';

export const RESTRICTED_MESSAGE =
  'MLView analysis is disabled in Restricted Mode because it spawns a Python interpreter.';

export const RESTRICTED_DETAIL =
  'Trust this workspace to enable analysis, the HTML export and the diagram.';

/** The action id offered alongside the restricted-mode error; handled in `onAction`. */
export const MANAGE_TRUST_ACTION = { id: 'manageTrust', label: 'Manage Trust' };

/** `workspace.isTrusted` is only absent on a host predating workspace trust; absent = trusted. */
export function isTrusted(): boolean {
  return vscode.workspace.isTrusted !== false;
}

export function manageTrust(): void {
  void vscode.commands.executeCommand('workbench.trust.manage');
}

/**
 * True when the caller may proceed. Otherwise it logs, offers "Manage Trust", and returns false
 * — so a command body reads `if (!ensureTrusted(log)) { return; }`.
 */
export function ensureTrusted(log?: Logger): boolean {
  if (isTrusted()) {
    return true;
  }
  log?.warn(RESTRICTED_MESSAGE);
  void Promise.resolve(
    vscode.window.showWarningMessage(RESTRICTED_MESSAGE, MANAGE_TRUST_ACTION.label)
  ).then((choice) => {
    if (choice) {
      manageTrust();
    }
  });
  return false;
}
