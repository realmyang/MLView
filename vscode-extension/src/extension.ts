import * as vscode from 'vscode';
import { AuthoredDiagramController } from './authoredPanel';
import { createLogger } from './log';

let authoredController: AuthoredDiagramController | undefined;

export function activate(ctx: vscode.ExtensionContext): void {
  const log = createLogger(() => 'off');
  ctx.subscriptions.push({ dispose: () => log.dispose() });
  const version = String(
    (ctx.extension?.packageJSON as { version?: string } | undefined)?.version ?? '0.1.0'
  );
  log.info(`MLView ${version} activating (VS Code ${vscode.version})`);
  authoredController = new AuthoredDiagramController(ctx, log);
  authoredController.register();
  ctx.subscriptions.push(authoredController);
}

export function deactivate(): void {
  authoredController?.dispose();
  authoredController = undefined;
}
