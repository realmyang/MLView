/**
 * The "MLView" output channel. Library code never writes to stdout — every diagnostic line
 * from the extension and every byte of the analyzer's stderr lands here.
 */

import * as vscode from 'vscode';

export type TraceLevel = 'off' | 'messages' | 'verbose';

export interface Logger {
  info(message: string): void;
  warn(message: string): void;
  error(message: string, err?: unknown): void;
  /** Only emitted when `mlview.trace` is `verbose`. */
  debug(message: string): void;
  /** Only emitted when `mlview.trace` is `messages` or `verbose`. */
  trace(message: string): void;
  /** Raw passthrough, used for streamed analyzer stderr — no timestamp, no prefix. */
  raw(chunk: string): void;
  show(preserveFocus?: boolean): void;
  channel: vscode.OutputChannel;
  dispose(): void;
}

function stamp(): string {
  const now = new Date();
  const pad = (n: number, w = 2) => String(n).padStart(w, '0');
  return `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}.${pad(
    now.getMilliseconds(),
    3
  )}`;
}

export function describeError(err: unknown): string {
  if (err instanceof Error) {
    return err.stack ? `${err.message}\n${err.stack}` : err.message;
  }
  if (typeof err === 'string') {
    return err;
  }
  try {
    return JSON.stringify(err);
  } catch {
    return String(err);
  }
}

export function createLogger(getTrace: () => TraceLevel): Logger {
  const channel = vscode.window.createOutputChannel('MLView');
  const write = (level: string, message: string): void => {
    channel.appendLine(`[${stamp()}] [${level}] ${message}`);
  };
  return {
    channel,
    info: (message) => write('info', message),
    warn: (message) => write('warn', message),
    error: (message, err) =>
      write('error', err === undefined ? message : `${message}: ${describeError(err)}`),
    debug: (message) => {
      if (getTrace() === 'verbose') {
        write('debug', message);
      }
    },
    trace: (message) => {
      const level = getTrace();
      if (level === 'messages' || level === 'verbose') {
        write('trace', message);
      }
    },
    raw: (chunk) => {
      const text = chunk.replace(/\r\n/g, '\n').replace(/\s+$/, '');
      if (text.length > 0) {
        channel.appendLine(text);
      }
    },
    show: (preserveFocus = true) => channel.show(preserveFocus),
    dispose: () => channel.dispose()
  };
}
