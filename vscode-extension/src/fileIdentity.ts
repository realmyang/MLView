/**
 * The one place that decides whether two path spellings name the same file.
 *
 * The validator reads sources through their realpath, while VS Code reports open documents by
 * `uri.fsPath` (a symlinked folder keeps its non-real spelling, and on Windows the drive letter
 * is lower-cased). Comparing those strings directly misses matches (EXT-2), so every identity
 * comparison goes through `identity()`: realpath when the file resolves, lower-cased on win32.
 */
import * as fs from 'node:fs';
import * as path from 'node:path';

function pathFor(platform: NodeJS.Platform): typeof path.posix {
  return platform === 'win32' ? path.win32 : path.posix;
}

/** Lexical identity: resolved, and lower-cased on win32 (defence in depth; realpath already canonicalises case). */
export function normCase(p: string, platform: NodeJS.Platform = process.platform): string {
  const resolved = pathFor(platform).resolve(p);
  return platform === 'win32' ? resolved.toLowerCase() : resolved;
}

/** Physical identity: the realpath when it resolves, otherwise the resolved spelling. */
export async function identity(p: string, platform: NodeJS.Platform = process.platform): Promise<string> {
  let real: string;
  try {
    real = await fs.promises.realpath(p);
  } catch {
    real = pathFor(platform).resolve(p);
  }
  return platform === 'win32' ? real.toLowerCase() : real;
}

/**
 * The files a panel reacts to. Each workspace-relative path is registered in its lexical
 * spelling and, when known, its realpath, so a watcher or editor event reported under either
 * spelling is recognised.
 */
export class DependencySet {
  private readonly paths = new Set<string>();
  constructor(private readonly platform: NodeJS.Platform = process.platform) { }
  add(rel: string, root: string, real?: string): void {
    this.paths.add(normCase(pathFor(this.platform).resolve(root, rel), this.platform));
    if (real)
      this.paths.add(normCase(real, this.platform));
  }
  addPath(absolute: string): void {
    this.paths.add(normCase(absolute, this.platform));
  }
  has(fsPath: string): boolean {
    return this.paths.has(normCase(fsPath, this.platform));
  }
  get size(): number {
    return this.paths.size;
  }
}
