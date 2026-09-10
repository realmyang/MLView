/**
 * The webview <-> host message protocol (CONTRACTS.md §4).
 *
 * Every message carries `v: 1`. Unknown message types are logged and ignored on both sides —
 * a version skew must degrade, not crash. That tolerance is what `parseUiToHost` implements
 * and what `test/protocol.test.js` asserts.
 */

import type { MLGraph } from './graph';

export const PROTOCOL_VERSION = 1 as const;

export type ThemeKind = 'light' | 'dark' | 'hc';
export type AnalysisScope = 'workspace' | 'file';

export interface Viewport {
  x: number;
  y: number;
  zoom: number;
}

export interface Sel {
  kind: string;
  id: string;
}

/** Opaque to the host: it is stored and handed back verbatim. */
export type ViewState = Record<string, unknown>;

/** VIEW-07: the picture formats the viewer can render for the host to save. */
export type ExportKind = 'svg' | 'png';

/**
 * VIEW-07: which projection the picture shows. `view` is the current viewport, `all` the
 * whole diagram, `scope` the active §11.1 scope (which the viewer refuses when unscoped).
 */
export type ExportScope = 'view' | 'all' | 'scope';

/**
 * VIEW-07. A base64 payload has 4 characters per 3 bytes, so this is the 32 MiB decoded
 * ceiling written as the character count the guard can check BEFORE anything is decoded —
 * a webview must not be able to make the extension host allocate an arbitrary buffer.
 */
export const MAX_EXPORT_BASE64_CHARS = Math.ceil((32 * 1024 * 1024) / 3) * 4;

export interface HostCapabilities {
  canOpenSource: boolean;
  canReanalyze: boolean;
  canExport: boolean;
  canAskAssistant: boolean;
}

export type HostToUi =
  | {
      v: 1;
      type: 'init';
      schemaVersion: string;
      theme: ThemeKind;
      host: 'vscode' | 'standalone';
      capabilities: HostCapabilities;
    }
  | {
      v: 1;
      type: 'graph';
      requestId: string;
      graph: MLGraph;
      preserve?: { viewport?: Viewport; selection?: Sel; collapsed?: string[] };
    }
  | { v: 1; type: 'analysisStarted'; requestId: string; scope: AnalysisScope; path?: string }
  | { v: 1; type: 'analysisProgress'; requestId: string; done: number; total: number; file?: string }
  | {
      v: 1;
      type: 'analysisFailed';
      requestId: string;
      message: string;
      detail?: string;
      actions?: { id: string; label: string }[];
    }
  | { v: 1; type: 'theme'; kind: ThemeKind }
  | { v: 1; type: 'revealNode'; nodeId: string; center?: boolean; approximate?: boolean }
  | { v: 1; type: 'revealIssue'; issueId: string }
  | { v: 1; type: 'cursorHint'; file: string; line: number }
  | {
      v: 1;
      type: 'setFilter';
      severities?: ('low' | 'medium' | 'high')[];
      codes?: string[];
      query?: string;
    }
  | { v: 1; type: 'stale'; changedFiles: string[] }
  | { v: 1; type: 'restoreState'; state: ViewState }
  /**
   * CONTRACTS.md §11.7. The selector field is named `spec`, not `scope`: `analysisStarted` and
   * `requestRefresh` already carry a field literally named `scope`, and reusing the word would
   * be a live collision. `spec: null` clears the scope.
   */
  | { v: 1; type: 'setScope'; spec: string | null; depth?: number }
  /**
   * VIEW-07 (docs/contracts/11.33-diagram-export.md). "Render this picture and send me the
   * bytes." The host cannot render the diagram — only the viewer holds the `LayoutFrame` —
   * so an export command is a REQUEST, and the answer is a separate `exportFile` message.
   * A viewer that does not implement it ignores an unknown type, which is why nothing here
   * blocks on a reply and why the command says what it asked for rather than what it saved.
   */
  | { v: 1; type: 'requestExport'; kind: ExportKind; scope: ExportScope };

export interface OpenLocationMessage {
  v: 1;
  type: 'openLocation';
  file: string;
  absFile: string;
  line: number;
  col: number;
  endLine: number;
  endCol: number;
  preview?: boolean;
}

export type UiToHost =
  | { v: 1; type: 'ready' }
  | OpenLocationMessage
  | { v: 1; type: 'selectNode'; nodeId: string | null }
  | { v: 1; type: 'requestRefresh'; scope: AnalysisScope; path?: string }
  | { v: 1; type: 'exportHtml' }
  | { v: 1; type: 'copy'; text: string }
  | { v: 1; type: 'saveState'; state: ViewState }
  | { v: 1; type: 'action'; id: string }
  | { v: 1; type: 'askAssistant'; nodeId: string; prompt: string }
  | { v: 1; type: 'log'; level: 'debug' | 'info' | 'warn' | 'error'; message: string }
  /**
   * MLV-P10 (docs/contracts/11.27-suppression-actions.md). The rail's "this is a false
   * positive" gesture. `copy` puts the ignore comment on the clipboard, `insert` writes
   * it at `absFile:line`, `disable` adds the code to `.mlview.toml` behind a confirm.
   * The host runs the SAME code path the editor lightbulb runs; a viewer that does not
   * send this message is unaffected, which is what keeps the field additive.
   */
  | SuppressRuleMessage
  /**
   * VIEW-07. The rendered picture, coming back from the viewer. The webview sandbox has no
   * download of its own, so the bytes travel through the protocol and the HOST owns the
   * save dialog and the write (docs/contracts/11.33-diagram-export.md).
   */
  | ExportFileMessage
  /**
   * CONTRACTS.md §11.7. Posted on EVERY scope change including a clear (then `spec: null`,
   * `label: "Everything"`, `nodes === of`). The host uses it for the panel title and
   * description; it must NEVER trigger a re-analysis.
   */
  | ScopeChangedMessage;

export interface SuppressRuleMessage {
  v: 1;
  type: 'suppressRule';
  /** `MLV201`. Anything else is rejected by `isUiToHost`, not by the handler. */
  code: string;
  action: 'copy' | 'insert' | 'disable';
  /** Absolute path of the file the finding is anchored in; required by `insert`. */
  absFile?: string;
  /** 1-based, like every `Loc.line` in the document (CONTRACTS §0). */
  line?: number;
}

export interface ExportFileMessage {
  v: 1;
  type: 'exportFile';
  /** `svg` or `png`; anything else is rejected by `isUiToHost`, not by the handler. */
  kind: ExportKind;
  /**
   * Base64 of the FILE's bytes — for SVG that is base64 of the UTF-8 text, not the text.
   * One encoding for both kinds is what keeps the host's write path byte-exact and
   * identical for the two formats.
   */
  data: string;
  /** A basename hint. Directory separators are stripped; the user still gets a save dialog. */
  suggestedName?: string;
  /** Echoed from `requestExport` so the toast can say what was exported. */
  scope?: ExportScope;
}

export interface ScopeChangedMessage {
  v: 1;
  type: 'scopeChanged';
  /** The normalized §11.1 selector, or null when the scope was cleared. */
  spec: string | null;
  /** Human label for the scope ("Everything" when cleared). */
  label: string;
  /** Nodes drawn in the projection. */
  nodes: number;
  /** Nodes in the whole analyzed workspace (`view.of.nodes`). */
  of: number;
}

export type UiToHostType = UiToHost['type'];
export type HostToUiType = HostToUi['type'];

export const UI_TO_HOST_TYPES: readonly UiToHostType[] = [
  'ready',
  'openLocation',
  'selectNode',
  'requestRefresh',
  'exportHtml',
  'copy',
  'saveState',
  'action',
  'askAssistant',
  'log',
  'scopeChanged',
  'suppressRule',
  'exportFile'
];

export const HOST_TO_UI_TYPES: readonly HostToUiType[] = [
  'init',
  'graph',
  'analysisStarted',
  'analysisProgress',
  'analysisFailed',
  'theme',
  'revealNode',
  'revealIssue',
  'cursorHint',
  'setFilter',
  'stale',
  'restoreState',
  'setScope',
  'requestExport'
];

/** The four error-banner action ids the host answers (CONTRACTS.md §4, UX §12 "hard error"). */
export const ACTION_IDS = ['retry', 'selectInterpreter', 'showOutput', 'installCore'] as const;
export type ActionId = (typeof ACTION_IDS)[number];

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

export function isUiToHostType(type: unknown): type is UiToHostType {
  return typeof type === 'string' && (UI_TO_HOST_TYPES as readonly string[]).includes(type);
}

export function isHostToUiType(type: unknown): type is HostToUiType {
  return typeof type === 'string' && (HOST_TO_UI_TYPES as readonly string[]).includes(type);
}

/**
 * VIEW-07. Checked BEFORE anything is decoded: `data` must be pure base64 (no whitespace,
 * no data: prefix, no path) and must be under the size ceiling, so a hostile or broken
 * viewer cannot make the extension host allocate an arbitrary buffer. `suggestedName` is a
 * basename hint only — a name carrying a separator or `..` is rejected here rather than
 * sanitized silently, because a rejected export is visible and a rewritten path is not.
 */
function isExportFile(value: Record<string, unknown>): boolean {
  const data = value['data'];
  const name = value['suggestedName'];
  return (
    (value['kind'] === 'svg' || value['kind'] === 'png') &&
    typeof data === 'string' &&
    data.length > 0 &&
    data.length <= MAX_EXPORT_BASE64_CHARS &&
    /^[A-Za-z0-9+/]+={0,2}$/.test(data) &&
    data.length % 4 === 0 &&
    (name === undefined ||
      (typeof name === 'string' &&
        name.length > 0 &&
        name.length <= 128 &&
        !/[\\/]/.test(name) &&
        !name.includes('..'))) &&
    (value['scope'] === undefined ||
      value['scope'] === 'view' ||
      value['scope'] === 'all' ||
      value['scope'] === 'scope')
  );
}

/**
 * MLV-P10. `suppressRule.absFile` names a file the host will WRITE to, so the guard is
 * as strict as `isExportFile`'s: an absolute path (POSIX `/…`, or a Windows drive or UNC
 * path), with no NUL. A relative path is rejected here rather than resolved against
 * whatever the extension host's cwd happens to be. Containment against the open
 * workspace folders is a separate check, in `codeActions.writableFile`.
 */
function isAbsoluteFilePath(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    value.length > 0 &&
    !value.includes('\0') &&
    (/^[/\\]/.test(value) || /^[A-Za-z]:[/\\]/.test(value))
  );
}

/**
 * Structural guard for a message arriving from the webview. Anything that is not a
 * well-formed, known message is rejected here and the caller logs + ignores it.
 */
export function isUiToHost(value: unknown): value is UiToHost {
  if (!isObject(value) || value['v'] !== PROTOCOL_VERSION || !isUiToHostType(value['type'])) {
    return false;
  }
  switch (value['type'] as UiToHostType) {
    case 'ready':
    case 'exportHtml':
      return true;
    case 'openLocation':
      return (
        typeof value['file'] === 'string' &&
        typeof value['absFile'] === 'string' &&
        isFiniteNumber(value['line']) &&
        isFiniteNumber(value['col']) &&
        isFiniteNumber(value['endLine']) &&
        isFiniteNumber(value['endCol'])
      );
    case 'selectNode':
      return typeof value['nodeId'] === 'string' || value['nodeId'] === null;
    case 'requestRefresh':
      return value['scope'] === 'workspace' || value['scope'] === 'file';
    case 'copy':
      return typeof value['text'] === 'string';
    case 'saveState':
      return isObject(value['state']);
    case 'action':
      return typeof value['id'] === 'string';
    case 'askAssistant':
      return typeof value['nodeId'] === 'string' && typeof value['prompt'] === 'string';
    case 'log':
      return (
        typeof value['message'] === 'string' &&
        ['debug', 'info', 'warn', 'error'].includes(String(value['level']))
      );
    case 'suppressRule':
      return (
        typeof value['code'] === 'string' &&
        /^MLV[0-9]{3}$/.test(value['code']) &&
        ['copy', 'insert', 'disable'].includes(String(value['action'])) &&
        (value['absFile'] === undefined || isAbsoluteFilePath(value['absFile'])) &&
        (value['line'] === undefined || (isFiniteNumber(value['line']) && value['line'] >= 1))
      );
    case 'exportFile':
      return isExportFile(value);
    case 'scopeChanged':
      return (
        (typeof value['spec'] === 'string' || value['spec'] === null) &&
        typeof value['label'] === 'string' &&
        isFiniteNumber(value['nodes']) &&
        isFiniteNumber(value['of'])
      );
    default:
      return false;
  }
}

export type ParseResult =
  | { ok: true; msg: UiToHost }
  | { ok: false; reason: 'not-an-object' | 'bad-version' | 'unknown-type' | 'malformed'; detail: string };

/**
 * Classify an inbound webview message. `unknown-type` and `bad-version` are the
 * forward-compatibility paths: the host logs them and carries on.
 */
export function parseUiToHost(value: unknown): ParseResult {
  if (!isObject(value)) {
    return { ok: false, reason: 'not-an-object', detail: typeof value };
  }
  if (value['v'] !== PROTOCOL_VERSION) {
    return { ok: false, reason: 'bad-version', detail: String(value['v']) };
  }
  if (!isUiToHostType(value['type'])) {
    return { ok: false, reason: 'unknown-type', detail: String(value['type']) };
  }
  if (!isUiToHost(value)) {
    return { ok: false, reason: 'malformed', detail: String(value['type']) };
  }
  return { ok: true, msg: value };
}

/** Sanity guard used by the (mocked) webview side in tests. */
export function isHostToUi(value: unknown): value is HostToUi {
  return isObject(value) && value['v'] === PROTOCOL_VERSION && isHostToUiType(value['type']);
}

let requestCounter = 0;

/** Monotonic, process-local request id. Correlates `analysisStarted` with `graph`. */
export function nextRequestId(prefix = 'req'): string {
  requestCounter += 1;
  return `${prefix}-${requestCounter}`;
}
