/**
 * The one-shot things a reader ASKS FOR, and what the viewer is allowed to do
 * about them.
 *
 * Every one of these is a REQUEST posted to the host. The viewer opens no file,
 * writes no file and edits nothing, in any host: what `openLocation`,
 * `suppressRule`, `applyFix` and `copy` actually do is the host's decision, and
 * the announcements here are careful to claim only what the host will have done
 * (VW-10).
 */

import { ignoreComment } from '../ui/suppress.js';
import { runFixAction } from '../ui/fixes.js';
import type { App } from '../app.js';
import type { Loc, RelatedLoc } from '../types.js';

/** H5. A REQUEST, never an edit — the decision itself lives in `ui/fixes.ts`. */
export function applyFix(app: App, issueId: string): void {
  const issue = app.index ? app.index.issueById.get(issueId) : null;
  if (!issue) return;
  runFixAction(issue, {
    canApply: app.canApplyFix(),
    post: (msg) => app.bridge.post(msg),
    toast: (text) => app.view.toast(text),
    announce: (text) => app.announce(text),
  });
}

/**
 * MLV-P10, "Copy ignore comment". It goes through the SAME `copy` message the
 * scope breadcrumb uses, so the standalone report answers with the clipboard
 * plus its copy toast (CONTRACTS 11.17.1) and VS Code with its own clipboard.
 * Nothing is written to any file by the viewer, ever.
 */
export function copyIgnore(app: App, code: string): void {
  const text = ignoreComment(code);
  app.bridge.post({ v: 1, type: 'copy', text });
  app.view.toast('Copied ' + text);
  app.announce('Copied the ignore comment for ' + code + '.');
}

/**
 * MLV-P10, "Disable this rule". A REQUEST, not an edit: the host decides
 * whether and how to write `.mlview.toml`. A host predating the message drops
 * it, which leaves the viewer exactly as it was.
 */
export function disableRule(app: App, code: string): void {
  app.bridge.post({ v: 1, type: 'suppressRule', code, scope: 'workspace', action: 'disable' });
  // VW-10. What the announcement may claim is bounded by what the HOST does
  // with the frame. VS Code writes `.mlview.toml`; the standalone report
  // answers it in the same page by copying the snippet to the clipboard
  // (`bridges.ts`), so "Asked the host to disable X" announced an edit that
  // nobody made, and did it before the toast that told the truth. This says
  // the request and names the answer, in both hosts.
  app.announce(
    'Requested that ' + code + ' be disabled for this workspace — ' +
      (app.bridge.host === 'standalone'
        ? 'this host answers by copying the .mlview.toml snippet.'
        : 'the host decides whether to write .mlview.toml.'),
  );
}

/** Composes the prompt described in UX_DESIGN section 7; hidden unless the host offers it. */
export function askAssistant(app: App, nodeId: string): void {
  if (!app.caps.canAskAssistant || !app.index) return;
  const node = app.index.nodeById.get(nodeId);
  if (!node) return;
  const codes = app.index.issuesOf(nodeId, app.filters.keep).map((i) => i.code);
  const prompt =
    'Explain the MLView node ' +
    (node.fqn || node.qualname) +
    ' at ' +
    node.loc.file +
    ':' +
    node.loc.line +
    ' in the ' +
    node.stage +
    ' stage' +
    (codes.length ? ', and the findings ' + codes.join(', ') : '') +
    '.';
  app.bridge.post({ v: 1, type: 'askAssistant', nodeId, prompt });
}

export function openLocation(app: App, loc: Loc | RelatedLoc): void {
  if (!app.caps.canOpenSource) return;
  const message: any = {
    v: 1,
    type: 'openLocation',
    file: loc.file,
    absFile: loc.absFile,
    line: loc.line,
    col: loc.col,
    endLine: loc.endLine,
    endCol: loc.endCol,
    preview: true,
  };
  // Preserve the frozen legacy frame byte-for-byte. Authored evidence adds
  // identifiers only when it actually has them.
  if (loc.evidenceId) message.evidenceId = loc.evidenceId;
  if (loc.evidenceId && loc.cell !== undefined) message.cell = loc.cell;
  app.bridge.post(message);
}

export function onAction(app: App, id: string): void {
  if (id === 'mlview.copyErrorDetails' && app.error) {
    app.bridge.post({
      v: 1,
      type: 'copy',
      text: app.error.message + (app.error.detail ? '\n' + app.error.detail : ''),
    });
    app.view.toast('Error details copied');
    return;
  }
  app.bridge.post({ v: 1, type: 'action', id });
}
