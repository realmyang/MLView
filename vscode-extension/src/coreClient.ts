/**
 * The process seam (CONTRACTS.md §3). This module is the ONLY place in the extension that
 * spawns the analyzer, and the extension contains no analysis of its own.
 *
 *   python -X utf8 -m mlview analyze <paths...> --json - --max-files N --max-nodes N [--exclude G]...
 *
 * Windows/UTF-8 invariant: `-X utf8` in argv, `PYTHONUTF8=1` + `PYTHONIOENCODING=utf-8` in the
 * environment, `shell: false`, and an absolute interpreter path. Without them cp1252 mangles the
 * JSON on the first non-ASCII identifier or path.
 */

import { execFile, type ChildProcess } from 'node:child_process';
import * as vscode from 'vscode';
import { emptyGraph, isSchemaCompatible, looksLikeGraph, type MLGraph } from './graph';
import type { Logger } from './log';
import { PythonEnvironment, schemaMismatchMessage } from './pythonEnv';
import { readSettings, type MlviewSettings } from './settings';
import type { AnalysisScope } from './protocol';
import { isTrusted, MANAGE_TRUST_ACTION, RESTRICTED_DETAIL, RESTRICTED_MESSAGE } from './trust';

export const MAX_BUFFER_BYTES = 32 * 1024 * 1024;
export const SAVE_DEBOUNCE_MS = 400;
const KILL_GRACE_MS = 2000;

export type CoreErrorKind =
  | 'restricted'
  | 'interpreter'
  | 'spawn'
  | 'usage'
  | 'internal'
  | 'parse'
  | 'schema'
  | 'cancelled';

export interface CoreAction {
  id: string;
  label: string;
}

export class CoreError extends Error {
  readonly kind: CoreErrorKind;
  readonly detail: string;
  readonly actions: CoreAction[];

  constructor(kind: CoreErrorKind, message: string, detail = '', actions: CoreAction[] = []) {
    super(message);
    this.name = 'CoreError';
    this.kind = kind;
    this.detail = detail;
    this.actions = actions;
  }
}

export const DEFAULT_ACTIONS: CoreAction[] = [
  { id: 'retry', label: 'Retry' },
  { id: 'selectInterpreter', label: 'Select Interpreter' },
  { id: 'showOutput', label: 'Show Output' }
];

export interface AnalyzeArgOptions {
  paths: string[];
  maxFiles: number;
  maxNodes: number;
  exclude: string[];
  /** When set, the graph is written to this file as a self-contained HTML report instead. */
  htmlOut?: string;
  /**
   * A CONTRACTS.md §11.1 diagram selector (`unit:train.validate`, `concern:evaluation`, ...).
   * Named `scopeSpec`, not `scope`, because `AnalyzeRequest.scope` is already the
   * `'workspace' | 'file'` ANALYSIS scope - the same collision §11.7 avoided by naming the
   * message field `spec`.
   */
  scopeSpec?: string;
  /** Boundary hops, 0..2 (§11.5). Omitted means the per-kind default. */
  depth?: number;
}

/**
 * Pure argv builder. Order is frozen: `analyze`, the paths, `--json -`, the caps, the excludes,
 * then the optional projection flags. `-X utf8` is prepended by the caller so it is impossible
 * to forget. An unscoped call produces exactly the argv it produced before scopes existed.
 */
export function buildAnalyzeArgs(opts: AnalyzeArgOptions): string[] {
  const args = ['-X', 'utf8', '-m', 'mlview', 'analyze', ...opts.paths];
  if (opts.htmlOut) {
    args.push('--html', opts.htmlOut, '--format', 'summary');
  } else {
    args.push('--json', '-');
  }
  args.push('--max-files', String(opts.maxFiles), '--max-nodes', String(opts.maxNodes));
  for (const glob of opts.exclude) {
    if (glob.trim().length > 0) {
      args.push('--exclude', glob.trim());
    }
  }
  if (opts.scopeSpec && opts.scopeSpec.trim().length > 0) {
    args.push('--scope', opts.scopeSpec.trim());
    if (typeof opts.depth === 'number' && Number.isInteger(opts.depth)) {
      args.push('--depth', String(opts.depth));
    }
  }
  return args;
}

export type ExitClass = 'ok' | 'nothing-analyzable' | 'usage' | 'internal' | 'fail-on' | 'unknown';

/** CONTRACTS.md §3 exit codes. `2` is never produced here because `--fail-on` is never passed. */
export function classifyExit(code: number | null): ExitClass {
  switch (code) {
    case 0:
      return 'ok';
    case 1:
      return 'usage';
    case 2:
      return 'fail-on';
    case 3:
      return 'internal';
    case 4:
      return 'nothing-analyzable';
    default:
      return 'unknown';
  }
}

export function tailLines(text: string, count = 8): string {
  return text
    .replace(/\r\n/g, '\n')
    .split('\n')
    .filter((line) => line.trim().length > 0)
    .slice(-count)
    .join('\n');
}

export interface AnalyzeRequest {
  scope: AnalysisScope;
  /** Absolute paths handed to the analyzer. */
  paths: string[];
  /** Absolute directory the analyzer runs in; also the graph's workspace root. */
  cwd: string;
  token?: vscode.CancellationToken;
  settings?: MlviewSettings;
}

export interface AnalyzeResult {
  graph: MLGraph;
  /** True when the analyzer reported exit code 4 (nothing analyzable). */
  empty: boolean;
  durationMs: number;
}

interface RunResult {
  code: number | null;
  stdout: string;
  stderr: string;
  cancelled: boolean;
}

/** A trailing-edge debounce, used for the analyze-on-save burst. */
export class Debouncer implements vscode.Disposable {
  private timer: NodeJS.Timeout | undefined;

  constructor(private readonly delayMs: number) {}

  schedule(fn: () => void): void {
    this.cancel();
    this.timer = setTimeout(() => {
      this.timer = undefined;
      fn();
    }, this.delayMs);
  }

  cancel(): void {
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = undefined;
    }
  }

  dispose(): void {
    this.cancel();
  }
}

interface InFlight {
  child: ChildProcess;
  kill: () => void;
}

export class CoreClient implements vscode.Disposable {
  private readonly inFlight = new Map<string, InFlight>();
  private readonly saveDebounce = new Debouncer(SAVE_DEBOUNCE_MS);

  constructor(
    private readonly env: PythonEnvironment,
    private readonly log: Logger
  ) {}

  /** Debounced entry point used by the analyze-on-save handler. */
  scheduleAnalyze(fn: () => void): void {
    this.saveDebounce.schedule(fn);
  }

  cancel(scope: AnalysisScope, path?: string): void {
    const key = scopeKey(scope, path);
    const running = this.inFlight.get(key);
    if (running) {
      this.log.info(`cancelling in-flight analysis for ${key}`);
      running.kill();
      this.inFlight.delete(key);
    }
  }

  cancelAll(): void {
    for (const [key, running] of this.inFlight) {
      this.log.debug(`cancelling ${key}`);
      running.kill();
    }
    this.inFlight.clear();
  }

  async analyze(request: AnalyzeRequest): Promise<AnalyzeResult> {
    const settings = request.settings ?? readSettings();
    const args = buildAnalyzeArgs({
      paths: request.paths,
      maxFiles: settings.maxFiles,
      maxNodes: settings.maxNodes,
      exclude: settings.exclude
    });
    const started = Date.now();
    const run = await this.spawn(scopeKey(request.scope, request.paths[0]), args, request);
    const durationMs = Date.now() - started;
    if (run.cancelled) {
      throw new CoreError('cancelled', 'Analysis cancelled.');
    }
    const outcome = classifyExit(run.code);
    if (outcome === 'nothing-analyzable') {
      this.log.info('analyzer reported nothing analyzable (exit 4)');
      return { graph: emptyGraph(forwardSlashes(request.cwd)), empty: true, durationMs };
    }
    if (outcome === 'usage') {
      throw new CoreError(
        'usage',
        'MLView analyzer reported a usage or I/O error.',
        tailLines(run.stderr) || tailLines(run.stdout),
        DEFAULT_ACTIONS
      );
    }
    if (outcome === 'internal' || outcome === 'unknown') {
      throw new CoreError(
        'internal',
        'MLView analyzer failed internally.',
        tailLines(run.stderr) || tailLines(run.stdout),
        DEFAULT_ACTIONS
      );
    }
    return { graph: this.parseGraph(run), empty: false, durationMs };
  }

  /** `analyze --html <file>`; returns the file that was written. */
  async exportHtml(
    request: AnalyzeRequest & { outFile: string; scopeSpec?: string; depth?: number }
  ): Promise<string> {
    const settings = request.settings ?? readSettings();
    const args = buildAnalyzeArgs({
      paths: request.paths,
      maxFiles: settings.maxFiles,
      maxNodes: settings.maxNodes,
      exclude: settings.exclude,
      htmlOut: request.outFile,
      // What the panel is drawing, so the exported report opens on the same diagram (§11.8:
      // the file still embeds the WHOLE graph; the scope is one attribute on the root).
      scopeSpec: request.scopeSpec,
      depth: request.depth
    });
    const run = await this.spawn(`export:${request.outFile}`, args, request);
    if (run.cancelled) {
      throw new CoreError('cancelled', 'Export cancelled.');
    }
    const outcome = classifyExit(run.code);
    if (outcome !== 'ok' && outcome !== 'fail-on') {
      throw new CoreError(
        outcome === 'nothing-analyzable' ? 'usage' : 'internal',
        outcome === 'nothing-analyzable'
          ? 'Nothing analyzable was found, so no report was written.'
          : 'MLView could not write the HTML report.',
        tailLines(run.stderr),
        DEFAULT_ACTIONS
      );
    }
    return request.outFile;
  }

  private parseGraph(run: RunResult): MLGraph {
    let parsed: unknown;
    try {
      parsed = JSON.parse(run.stdout);
    } catch (err) {
      throw new CoreError(
        'parse',
        'MLView returned output that is not valid JSON.',
        `${String(err)}\n${tailLines(run.stderr)}`,
        DEFAULT_ACTIONS
      );
    }
    if (!looksLikeGraph(parsed)) {
      throw new CoreError(
        'parse',
        'MLView returned JSON that is not a graph document.',
        tailLines(run.stderr),
        DEFAULT_ACTIONS
      );
    }
    if (!isSchemaCompatible(parsed.schemaVersion)) {
      throw new CoreError('schema', schemaMismatchMessage(parsed.schemaVersion), '', [
        { id: 'installCore', label: 'Install MLView core' },
        { id: 'showOutput', label: 'Show Output' }
      ]);
    }
    return parsed;
  }

  private async spawn(key: string, args: string[], request: AnalyzeRequest): Promise<RunResult> {
    // THE trust gate. This is the only place in the extension that starts a child process, so
    // checking here is what actually keeps the `untrustedWorkspaces: "limited"` promise: no
    // interpreter probe, no `--version` handshake, no analyzer (CONTRACTS.md §6).
    if (!isTrusted()) {
      throw new CoreError('restricted', RESTRICTED_MESSAGE, RESTRICTED_DETAIL, [
        MANAGE_TRUST_ACTION,
        { id: 'showOutput', label: 'Show Output' }
      ]);
    }
    const state = await this.env.resolve();
    if (!state.ok) {
      throw new CoreError(
        'interpreter',
        state.failure.message,
        state.failure.detail,
        state.failure.actions
      );
    }
    const executable = state.interpreter.executable;

    // Single-flight per scope: a newer request for the same scope supersedes the running one.
    const previous = this.inFlight.get(key);
    if (previous) {
      this.log.debug(`superseding in-flight analysis for ${key}`);
      previous.kill();
      this.inFlight.delete(key);
    }

    this.log.info(`> "${executable}" ${args.map(quoteForLog).join(' ')}`);
    this.log.debug(`cwd: ${request.cwd}`);

    return await new Promise<RunResult>((resolve, reject) => {
      let cancelled = false;
      let settled = false;
      let stderrBuffer = '';
      let tokenSub: vscode.Disposable | undefined;
      // Supersede is synchronous but this child's terminal handler is not: by the time it runs,
      // the map entry for `key` may already belong to the run that REPLACED us. Only ever
      // unregister our own record, or `cancelAll()`, `cancel()` and single-flight all start
      // operating on a map that no longer knows about the process that is actually running.
      let entry: InFlight | undefined;
      const release = (): void => {
        if (entry && this.inFlight.get(key) === entry) {
          this.inFlight.delete(key);
        }
      };

      const child = execFile(
        executable,
        args,
        {
          cwd: request.cwd,
          shell: false,
          windowsHide: true,
          maxBuffer: MAX_BUFFER_BYTES,
          env: {
            ...process.env,
            PYTHONUTF8: '1',
            PYTHONIOENCODING: 'utf-8'
          }
        },
        (err, stdout, stderr) => {
          if (settled) {
            return;
          }
          settled = true;
          release();
          tokenSub?.dispose();
          const code = extractExitCode(err);
          const text = String(stderr ?? '') || stderrBuffer;
          if (err && code === null && !cancelled) {
            const overflow =
              (err as { code?: unknown }).code === 'ERR_CHILD_PROCESS_STDIO_MAXBUFFER';
            reject(
              new CoreError(
                overflow ? 'internal' : 'spawn',
                overflow
                  ? `The graph exceeded the ${Math.round(
                      MAX_BUFFER_BYTES / (1024 * 1024)
                    )} MB transfer limit. Lower mlview.maxNodes or narrow the scope with mlview.exclude.`
                  : `Could not run the MLView analyzer with ${executable}.`,
                `${String(err)}\n${tailLines(text)}`,
                DEFAULT_ACTIONS
              )
            );
            return;
          }
          resolve({ code, stdout: String(stdout ?? ''), stderr: text, cancelled });
        }
      );

      const kill = (): void => {
        cancelled = true;
        if (child.exitCode === null && !child.killed) {
          child.kill('SIGTERM');
          const hard = setTimeout(() => {
            if (child.exitCode === null) {
              child.kill('SIGKILL');
            }
          }, KILL_GRACE_MS);
          hard.unref?.();
        }
      };

      child.stderr?.setEncoding('utf8');
      child.stderr?.on('data', (chunk: string) => {
        stderrBuffer += chunk;
        this.log.raw(chunk);
      });
      child.on('error', (err) => {
        if (settled) {
          return;
        }
        settled = true;
        release();
        tokenSub?.dispose();
        reject(
          new CoreError(
            'spawn',
            `Could not run the MLView analyzer with ${executable}.`,
            String(err),
            DEFAULT_ACTIONS
          )
        );
      });

      tokenSub = request.token?.onCancellationRequested(() => kill());
      entry = { child, kill };
      this.inFlight.set(key, entry);
    });
  }

  dispose(): void {
    this.saveDebounce.dispose();
    this.cancelAll();
  }
}

function extractExitCode(err: unknown): number | null {
  if (!err) {
    return 0;
  }
  const code = (err as { code?: unknown }).code;
  if (typeof code === 'number') {
    return code;
  }
  return null;
}

function quoteForLog(arg: string): string {
  return /\s/.test(arg) ? `"${arg}"` : arg;
}

export function scopeKey(scope: AnalysisScope, path?: string): string {
  return scope === 'workspace' ? 'workspace' : `file:${path ?? ''}`;
}

export function forwardSlashes(p: string): string {
  return p.replace(/\\/g, '/');
}
