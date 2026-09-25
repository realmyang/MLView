/**
 * The host side of saving the diagram as a picture.
 *
 * The extension host cannot draw the diagram: only the webview holds the laid-out scene and the
 * resolved theme. The webview's export menu therefore renders the SVG or PNG itself and posts one
 * `exportFile { kind, data, suggestedName?, scope?, requestId? }` message. This file is the single
 * host path for it:
 *
 *   webview `exportFile` -> `parseExportFileMessage` -> `decodeExportPayload` -> save dialog -> write
 *
 * The webview sandbox has no download of its own (an `<a download>` in a VS Code webview is
 * inert), which is why the bytes travel through the message protocol and the save dialog and the
 * write live here.
 *
 * Nothing in this file trusts the payload: `parseExportFileMessage` checks the message shape and
 * caps the base64 length, `decodeExportPayload` validates the base64 and decodes it under a size
 * ceiling, and then checks the file signature for the kind that was asked for, so a `png` request
 * cannot be answered with something that is not a PNG and end up on disk under a `.png` name.
 */

import * as path from 'node:path';
import * as vscode from 'vscode';
import type { Logger } from './log';

export type ExportKind = 'svg' | 'png';
export type ExportScope = 'all' | 'view' | 'scope';
export interface ExportFileMessage {
  readonly v: 1;
  readonly type: 'exportFile';
  readonly kind: ExportKind;
  readonly data: string;
  readonly suggestedName?: string;
  readonly scope?: ExportScope;
  readonly requestId?: string;
}

/** 32 MiB decoded. */
export const MAX_EXPORT_BYTES = 32 * 1024 * 1024;
/** The longest base64 text that can decode to at most MAX_EXPORT_BYTES. */
export const MAX_EXPORT_BASE64_LENGTH = 4 * Math.ceil(MAX_EXPORT_BYTES / 3);

export function parseExportFileMessage(raw: unknown): ExportFileMessage | undefined {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return undefined;
  const value = raw as Record<string, unknown>;
  if (value.v !== 1 || value.type !== 'exportFile') return undefined;
  if (value.kind !== 'svg' && value.kind !== 'png') return undefined;
  if (typeof value.data !== 'string' || value.data.length > MAX_EXPORT_BASE64_LENGTH) return undefined;
  if (value.suggestedName !== undefined && typeof value.suggestedName !== 'string') return undefined;
  if (value.scope !== undefined && !['all', 'view', 'scope'].includes(String(value.scope))) return undefined;
  if (value.requestId !== undefined && typeof value.requestId !== 'string') return undefined;
  return value as unknown as ExportFileMessage;
}

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
 * `wrong-format` is the interesting one: a valid base64 string says nothing about what the bytes
 * ARE. A `.svg` file the user opens in a browser is executable content, so the host refuses to
 * write anything under an `.svg` name that does not start with an XML/SVG opening tag, and
 * anything under a `.png` name that does not carry the PNG signature.
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
  const text = buffer.subarray(0, 512).toString('utf8');
  const head = (text.charCodeAt(0) === 0xfeff ? text.slice(1) : text).trimStart();
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

/** How one export request ended; reported to the webview as an `actionResult`. */
export type ExportOutcome =
  | { outcome: 'done'; name: string }
  | { outcome: 'cancelled' }
  | { outcome: 'failed'; message: string };

/**
 * Handle one `exportFile` message: decode, ask where to put it, write it, say so.
 *
 * The VS Code notifications stay host-side; the returned outcome carries no absolute path, so it
 * can be posted back to the webview.
 */
export async function saveExportedFile(
  msg: ExportFileMessage,
  deps: ExportSaveDeps
): Promise<ExportOutcome> {
  const decoded = decodeExportPayload(msg.kind, msg.data);
  if (!decoded.ok) {
    deps.log.warn(`refused a ${msg.kind} export payload: ${decoded.reason}`);
    void vscode.window.showWarningMessage(
      `MLView could not save the ${KIND_LABEL[msg.kind]}: the viewer sent a payload this ` +
        `host will not write (${decoded.reason}).`
    );
    return { outcome: 'failed', message: `the payload was refused (${decoded.reason})` };
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
    return { outcome: 'cancelled' };
  }

  try {
    await vscode.workspace.fs.writeFile(target, decoded.bytes);
  } catch (err) {
    deps.log.error(`could not write ${target.fsPath}`, err);
    void vscode.window.showErrorMessage(
      `MLView could not write ${target.fsPath}. See the MLView output channel.`
    );
    return { outcome: 'failed', message: 'the file could not be written' };
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
  return { outcome: 'done', name: path.basename(target.fsPath) };
}
