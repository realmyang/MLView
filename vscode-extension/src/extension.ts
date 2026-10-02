import * as vscode from 'vscode';
import { AuthoredDiagramController } from './authoredPanel';
import { createLogger } from './log';

let authoredController: AuthoredDiagramController | undefined;

export function activate(ctx: vscode.ExtensionContext): void {
  const log = createLogger(() => 'off');
  ctx.subscriptions.push({ dispose: () => log.dispose() });
  const version = String(
    (ctx.extension?.packageJSON as { version?: string } | undefined)?.version ?? 'unknown'
  );
  log.info(`MLView ${version} activating (VS Code ${vscode.version})`);
  authoredController = new AuthoredDiagramController(ctx, log);
  authoredController.register();
  ctx.subscriptions.push(authoredController);
  // After VS Code restarted the extension host in this window: replace the dead diagram tabs.
  void authoredController.recoverAfterRestart().catch((error: unknown) => log.error('reopening diagrams after the restart failed', error));
}

export function deactivate(): void {
  authoredController?.dispose();
  authoredController = undefined;
}
