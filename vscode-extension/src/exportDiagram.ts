/**
 * VIEW-07 — the host side of exporting the diagram as a picture
 * (docs/contracts/11.33-diagram-export.md).
 *
 * The extension host cannot draw the diagram: only the viewer holds the `LayoutFrame`, the
 * routed edges and the resolved theme tokens. So the split is:
 *
 *   host  -> ui : `requestExport { kind, scope }`   (the two commands below)
 *   ui    -> host: `exportFile { kind, data, ... }`  (`saveExportedFile` below)
 *
 * The webview sandbox has no download of its own — an `<a download>` in a VS Code webview
 * is inert — which is why the bytes travel through the message protocol and the SAVE
 * DIALOG AND THE WRITE LIVE HERE, in the one place that is allowed to touch the disk.
 *
 * Nothing in this file trusts the payload: the base64 is validated by the protocol guard
 * before it arrives, decoded under a size ceiling here, and then checked against the file
 * signature for the kind that was asked for, so a `png` request cannot be answered with
 * something that is not a PNG and end up on disk under a `.png` name.
 */

import * as path from 'node:path';
import * as vscode from 'vscode';
import type { Logger } from './log';
import type { ExportFileMessage, ExportKind, ExportScope } from './protocol';

/** 32 MiB decoded. The protocol guard rejects the base64 above this before we allocate. */
export const MAX_EXPORT_BYTES = 32 * 1024 * 1024;

/** The eight-byte PNG signature (RFC 2083 §3.1). */
const PNG_SIGNATURE = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];

const EXTENSION: Record<ExportKind, string> = { svg: 'svg', png: 'png' };
const FILTER_LABEL: Record<ExportKind, string> = { svg: 'SVG image', png: 'PNG image' };
const KIND_LABEL: Record<ExportKind, string> = { svg: 'SVG', png: 'PNG' };

const SCOPE_LABEL: Record<ExportScope, string> = {
  view: 'current view',
  all: 'whole diagram',
  scope: 'current scope'
};

export type DecodeFailure = 'not-base64' | 'too-large' | 'empty' | 'wrong-format';

export type DecodeResult =
  | { ok: true; bytes: Uint8Array }
  | { ok: false; reason: DecodeFailure };

/**
 * Decode the payload and prove it is the picture that was asked for.
 *
 * `wrong-format` is the interesting one: the guard in protocol.ts only proves the string is
 * base64: it says nothing about what the bytes ARE. A `.svg` file the user opens in a
 * browser is executable content, so the host refuses to write anything under an `.svg` name
 * that does not start with an XML/SVG opening tag, and anything under a `.png` name that
 * does not carry the PNG signature.
 */
export function decodeExportPayload(kind: ExportKind, data: string): DecodeResult {
  if (data.length === 0) {
    return { ok: false, reason: 'empty' };
  }
  if (!/^[A-Za-z0-9+/]+={0,2}$/.test(data) || data.length % 4 !== 0) {
    return { ok: false, reason: 'not-base64' };
  }
  if (Math.floor((data.length / 4) * 3) > MAX_EXPORT_BYTES) {
    return { ok: false, reason: 'too-large' };
  }
  const buffer = Buffer.from(data, 'base64');
  if (buffer.length === 0) {
    return { ok: false, reason: 'empty' };
  }
  if (buffer.length > MAX_EXPORT_BYTES) {
    return { ok: false, reason: 'too-large' };
  }
  if (!looksLike(kind, buffer)) {
    return { ok: false, reason: 'wrong-format' };
  }
  return { ok: true, bytes: new Uint8Array(buffer) };
}

function looksLike(kind: ExportKind, buffer: Buffer): boolean {
  if (kind === 'png') {
    if (buffer.length < PNG_SIGNATURE.length) {
      return false;
    }
    return PNG_SIGNATURE.every((byte, i) => buffer[i] === byte);
  }
  // SVG: the first non-space characters must open an XML document or the <svg> root itself.
  const head = buffer.subarray(0, 512).toString('utf8').replace(/^﻿/, '').trimStart();
  return head.startsWith('<?xml') || head.startsWith('<!DOCTYPE svg') || head.startsWith('<svg');
}

/**
 * The basename the save dialog opens on. The viewer's hint wins when it is a plain,
 * safe basename with the right extension; otherwise the host names the file itself.
 * A hint is never turned into a directory: everything but the last path segment is dropped.
 */
export function defaultExportName(
  kind: ExportKind,
  suggested?: string,
  scope?: ExportScope
): string {
  const ext = EXTENSION[kind];
  const cleaned = (suggested ?? '')
    .split(/[\\/]/)
    .pop()!
    .replace(/[^A-Za-z0-9._-]/g, '-')
    .replace(/^[.-]+/, '')
    .slice(0, 80);
  if (cleaned.length > 0) {
    return cleaned.toLowerCase().endsWith(`.${ext}`) ? cleaned : `${cleaned}.${ext}`;
  }
  const suffix = scope === 'view' ? '-view' : scope === 'scope' ? '-scope' : '';
  return `mlview-diagram${suffix}.${ext}`;
}

/** What `saveExportedFile` needs from the panel that received the message. */
export interface ExportSaveDeps {
  readonly log: Logger;
  /** Absolute path the save dialog opens in; undefined with no folder open. */
  workspaceRoot(): string | undefined;
}

/**
 * Handle one `exportFile` message: decode, ask where to put it, write it, say so.
 *
 * Returns the path written, or undefined when the user cancelled or the payload was
 * refused — so a test can tell "the user said no" from "the bytes were rejected" by
 * pairing the return value with what reached the log.
 */
export async function saveExportedFile(
  msg: ExportFileMessage,
  deps: ExportSaveDeps
): Promise<string | undefined> {
  const decoded = decodeExportPayload(msg.kind, msg.data);
  if (!decoded.ok) {
    deps.log.warn(`refused a ${msg.kind} export payload: ${decoded.reason}`);
    void vscode.window.showWarningMessage(
      `MLView could not save the ${KIND_LABEL[msg.kind]}: the viewer sent a payload this ` +
        `host will not write (${decoded.reason}).`
    );
    return undefined;
  }

  const root = deps.workspaceRoot();
  const name = defaultExportName(msg.kind, msg.suggestedName, msg.scope);
  const target = await vscode.window.showSaveDialog({
    title: `Export MLView diagram as ${KIND_LABEL[msg.kind]}`,
    // With no folder open there is no sensible directory to propose, so VS Code picks its
    // own default rather than being handed a relative path it would resolve unpredictably.
    ...(root ? { defaultUri: vscode.Uri.file(path.join(root, name)) } : {}),
    filters: { [FILTER_LABEL[msg.kind]]: [EXTENSION[msg.kind]] }
  });
  if (!target) {
    deps.log.info(`${msg.kind} export cancelled at the save dialog`);
    return undefined;
  }

  try {
    await vscode.workspace.fs.writeFile(target, decoded.bytes);
  } catch (err) {
    deps.log.error(`could not write ${target.fsPath}`, err);
    void vscode.window.showErrorMessage(
      `MLView could not write ${target.fsPath}. See the MLView output channel.`
    );
    return undefined;
  }

  deps.log.info(
    `wrote ${decoded.bytes.length} bytes of ${msg.kind.toUpperCase()} to ${target.fsPath}`
  );
  const scopeNote = msg.scope ? ` (${SCOPE_LABEL[msg.scope]})` : '';
  void vscode.window
    .showInformationMessage(
      `MLView diagram exported to ${target.fsPath}${scopeNote}`,
      'Open',
      'Copy Path'
    )
    .then(async (choice) => {
      if (choice === 'Open') {
        await vscode.env.openExternal(target);
      } else if (choice === 'Copy Path') {
        await vscode.env.clipboard.writeText(target.fsPath);
      }
    });
  return target.fsPath;
}

/** The panel surface the two export commands drive; kept narrow so tests can stand one in. */
export interface ExportPanelLike {
  postRequestExport(kind: ExportKind, scope: ExportScope): void;
  /** The §11.1 selector the diagram is drawing, when it is scoped. */
  readonly activeScope: { spec: string; depth?: number } | undefined;
}

export interface ExportCommandDeps {
  readonly log: Logger;
  /** The live panel, or undefined when the diagram is not open. */
  panel(): ExportPanelLike | undefined;
}

/** The quick-pick items, exported so a test can assert the offer without opening a dialog. */
export function exportScopeChoices(
  activeScopeSpec?: string
): { label: string; description: string; scope: ExportScope }[] {
  const choices: { label: string; description: string; scope: ExportScope }[] = [
    { label: 'Whole diagram', description: 'every node, at natural size', scope: 'all' },
    { label: 'Current view', description: 'exactly what is on screen now', scope: 'view' }
  ];
  if (activeScopeSpec) {
    choices.push({
      label: 'Current scope',
      description: activeScopeSpec,
      scope: 'scope'
    });
  }
  return choices;
}

/**
 * `MLView: Export Diagram as SVG` / `... as PNG`.
 *
 * The command does NOT wait for the picture: it asks, and the viewer answers with an
 * `exportFile` message that `saveExportedFile` handles. That is what keeps a slow render of
 * a 400-node diagram from blocking the command, and what makes the viewer's own export menu
 * and these commands the same code path on the host side.
 */
export async function requestDiagramExport(
  kind: ExportKind,
  deps: ExportCommandDeps,
  preset?: ExportScope
): Promise<void> {
  const panel = deps.panel();
  if (!panel) {
    void vscode.window.showWarningMessage(
      `MLView: open the diagram (MLView: Visualize ML Workflow) before exporting ${KIND_LABEL[kind]}.`
    );
    return;
  }
  const activeSpec = panel.activeScope?.spec;
  let scope = preset;
  if (!scope) {
    const choices = exportScopeChoices(activeSpec);
    const picked = await vscode.window.showQuickPick(choices, {
      title: `Export MLView diagram as ${KIND_LABEL[kind]}`,
      placeHolder: 'What should the picture contain?'
    });
    if (!picked) {
      return;
    }
    scope = picked.scope;
  }
  // A `scope` export with nothing scoped would be an empty picture; fall back to everything
  // rather than asking the viewer for something it must refuse.
  if (scope === 'scope' && !activeSpec) {
    deps.log.warn('export scope "scope" requested with no active scope; exporting everything');
    scope = 'all';
  }
  deps.log.info(`asked the viewer for a ${kind} export of the ${SCOPE_LABEL[scope]}`);
  panel.postRequestExport(kind, scope);
}
