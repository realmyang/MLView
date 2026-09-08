/**
 * H3 — turning the analyzer's `--progress-json` stderr into `analysisProgress`.
 *
 * `analysisProgress` has been fully specified at `protocol.ts:54`, listed in
 * `HOST_TO_UI_TYPES`, and drawn by a working receiver in the viewer
 * (`webview/src/ui/states.ts`) since the first release — and no host has ever sent
 * one, so a 445-file workspace showed an indeterminate spinner for 5.64 s.
 *
 * The analyzer writes one NDJSON frame per file to **stderr** (stdout purity is a
 * frozen gate, CONTRACTS §3):
 *
 *     {"t":"progress","done":12,"total":445,"file":"src/train.py"}
 *
 * This module is the parser, kept out of `coreClient.ts` so it can be tested
 * without a child process. Three rules it enforces, each of which was a way to
 * corrupt the output channel:
 *
 * 1. **Only lines that start with `{"t":"progress"` are candidates.** Everything
 *    else — a warning, a traceback, a library's own chatter — reaches the log
 *    exactly as it does today. A cheap prefix test, not a JSON parse of every line.
 * 2. **A candidate that does not parse is still log output.** A frame split across
 *    two chunks arrives as a partial line; it is held, and only dropped when the
 *    buffer stops looking like a frame.
 * 3. **Nothing is invented.** `done`/`total` must be finite non-negative numbers,
 *    `file` is optional, and `done` is clamped to `total` so a progress bar can
 *    never render 451 of 445.
 */

export const PROGRESS_PREFIX = '{"t":"progress"';

export interface ProgressFrame {
  done: number;
  total: number;
  file?: string;
}

/** One line -> a frame, or `undefined` when the line is ordinary stderr. */
export function parseProgressLine(line: string): ProgressFrame | undefined {
  const text = line.trim();
  if (!text.startsWith(PROGRESS_PREFIX)) {
    return undefined;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return undefined;
  }
  if (typeof parsed !== 'object' || parsed === null) {
    return undefined;
  }
  const obj = parsed as Record<string, unknown>;
  if (obj['t'] !== 'progress') {
    return undefined;
  }
  const done = obj['done'];
  const total = obj['total'];
  if (typeof done !== 'number' || typeof total !== 'number') {
    return undefined;
  }
  if (!Number.isFinite(done) || !Number.isFinite(total) || done < 0 || total < 0) {
    return undefined;
  }
  const file = typeof obj['file'] === 'string' ? obj['file'] : undefined;
  return {
    done: Math.min(done, total),
    total,
    ...(file ? { file } : {})
  };
}

/**
 * Splits a stderr byte stream into lines, hands the progress frames to `onFrame`
 * and everything else to `onText` — verbatim, newline included, so the output
 * channel reads exactly as it did before H3 existed.
 */
export class ProgressSplitter {
  private buffer = '';

  constructor(
    private readonly onFrame: (frame: ProgressFrame) => void,
    private readonly onText: (chunk: string) => void
  ) {}

  push(chunk: string): void {
    this.buffer += chunk;
    let cut = this.buffer.indexOf('\n');
    while (cut >= 0) {
      const upTo = cut + 1;
      this.consume(this.buffer.slice(0, upTo));
      this.buffer = this.buffer.slice(upTo);
      cut = this.buffer.indexOf('\n');
    }
    // A partial line that cannot become a frame is log output; forward it now so a
    // traceback's last line is not held back until the process exits.
    if (this.buffer.length > 0 && !PROGRESS_PREFIX.startsWith(this.buffer.trimStart().slice(0, PROGRESS_PREFIX.length))) {
      const pending = this.buffer;
      this.buffer = '';
      this.onText(pending);
    }
  }

  /** Called when the child's stderr closes: whatever is left is log output. */
  flush(): void {
    if (this.buffer.length === 0) {
      return;
    }
    const pending = this.buffer;
    this.buffer = '';
    this.consume(pending);
  }

  private consume(line: string): void {
    const frame = parseProgressLine(line);
    if (frame) {
      this.onFrame(frame);
      return;
    }
    this.onText(line);
  }
}
