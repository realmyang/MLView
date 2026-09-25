/**
 * Which on-disk revision an open panel shows (Campaign 1, contract 1a).
 *
 * The helper only ever moves the published revision forward; only non-helper writes (git
 * restore, sync tools, an editor saving an old buffer) move it back. The panel therefore mirrors
 * the file and refuses a revision only when its own observations prove the revision is older
 * than one it has already moved past. Freshness never decides adoption.
 *
 * This module is pure: the panel reads the artifact, validates it, and hands the result here.
 */
import { displayIssue } from './displayText';
import { ID_PATTERN, type ValidatedWorkflow, type ValidationIssue } from './workflowDocument';

export type Verdict = 'adopt' | 'refresh' | 'invalid' | 'obsolete' | 'same-id-changed' | 'keep';
export type DiskHead =
  | { kind: 'revision'; id: string; parent: string | null; verdict?: Verdict; issues?: string[] }
  | { kind: 'bad-revision' | 'missing' | 'unreadable' | 'parse'; detail?: string; verdict?: Verdict; issues?: string[] };
export interface RevisionIdent {
  id: string;
  parent: string | null;
}
export type Candidate =
  | { kind: 'missing' }
  | { kind: 'unreadable'; detail: string; transient?: boolean }
  | { kind: 'parse'; detail: string }
  | {
      kind: 'json';
      ident: RevisionIdent | null;
      sem: string;
      full: string;
      result: { value?: Pick<ValidatedWorkflow, 'document' | 'fingerprints'>; issues: ValidationIssue[] };
    };
export interface DisplayedRevision {
  id: string;
  sem: string;
  full: string;
  verified: boolean;
  baseline?: Record<string, string>;
}
export interface Observation {
  verdict: Verdict;
  lineageNote?: { from: string };
}

/**
 * Canonical JSON: arrays keep order, object keys sorted (UTF-16 order), primitives via
 * JSON.stringify. Iterative, like validateWorkflowStructure, so a deeply nested artifact (which
 * JSON.parse accepts) cannot overflow the stack.
 */
export function canonicalJson(value: unknown): string {
  const out: string[] = [];
  // Each entry is literal text to emit, or a value still to serialise; popped in document order.
  const pending: ({ text: string } | { value: unknown })[] = [{ value }];
  while (pending.length) {
    const next = pending.pop()!;
    if ('text' in next) {
      out.push(next.text);
      continue;
    }
    const current = next.value;
    if (Array.isArray(current)) {
      pending.push({ text: ']' });
      for (let i = current.length - 1; i >= 0; i--) {
        pending.push({ value: current[i] });
        if (i > 0)
          pending.push({ text: ',' });
      }
      pending.push({ text: '[' });
    }
    else if (current && typeof current === 'object') {
      const record = current as Record<string, unknown>;
      const keys = Object.keys(record).sort();
      pending.push({ text: '}' });
      for (let i = keys.length - 1; i >= 0; i--) {
        pending.push({ value: record[keys[i]!] });
        pending.push({ text: (i > 0 ? ',' : '') + JSON.stringify(keys[i]) + ':' });
      }
      pending.push({ text: '{' });
    }
    else {
      const primitive = JSON.stringify(current);
      out.push(primitive === undefined ? 'null' : primitive);
    }
  }
  return out.join('');
}

/** Deepest JSON nesting the helper and the viewer accept in an artifact or draft (a WorkflowDocument needs about 5). */
export const MAX_JSON_DEPTH = 64;

/** Nesting depth of a parsed JSON value (a scalar is 0, `[]` is 1), computed iteratively. */
export function jsonDepth(value: unknown): number {
  let deepest = 0;
  const pending: [unknown, number][] = [[value, 0]];
  while (pending.length) {
    const [current, depth] = pending.pop()!;
    if (!current || typeof current !== 'object')
      continue;
    deepest = Math.max(deepest, depth + 1);
    for (const child of Array.isArray(current) ? current : Object.values(current as Record<string, unknown>))
      if (child && typeof child === 'object')
        pending.push([child, depth + 1]);
  }
  return deepest;
}

/** The revision identity of a parsed artifact, read leniently (the helper takes it unvalidated). */
export function lenientRevision(value: unknown): RevisionIdent | null {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    return null;
  const revision = (value as Record<string, unknown>).revision;
  if (!revision || typeof revision !== 'object' || Array.isArray(revision))
    return null;
  const { id, parent } = revision as Record<string, unknown>;
  if (typeof id !== 'string' || !ID_PATTERN.test(id))
    return null;
  return { id, parent: typeof parent === 'string' && ID_PATTERN.test(parent) ? parent : null };
}

/** The document without its top-level `verification`, canonicalised (the helper's semantic identity). */
export function semanticJson(value: unknown): string {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    const copy: Record<string, unknown> = { ...(value as Record<string, unknown>) };
    delete copy.verification;
    return canonicalJson(copy);
  }
  return canonicalJson(value);
}

/** Collections bounded to `limit` entries that evict in insertion order. */
export class BoundedMap<K, V> {
  private readonly map = new Map<K, V>();
  constructor(private readonly limit: number) { }
  get(key: K): V | undefined { return this.map.get(key); }
  has(key: K): boolean { return this.map.has(key); }
  set(key: K, value: V): void {
    this.map.delete(key);
    this.map.set(key, value);
    while (this.map.size > this.limit)
      this.map.delete(this.map.keys().next().value as K);
  }
  clear(): void { this.map.clear(); }
  get size(): number { return this.map.size; }
}
export class BoundedSet<K> {
  private readonly map: BoundedMap<K, true>;
  constructor(limit: number) { this.map = new BoundedMap<K, true>(limit); }
  add(key: K): void { this.map.set(key, true); }
  has(key: K): boolean { return this.map.has(key); }
  clear(): void { this.map.clear(); }
  get size(): number { return this.map.size; }
}

export class RevisionLineage {
  displayed: DisplayedRevision | null = null;
  diskHead: DiskHead | null = null;
  /** Revision ids proven older than something observed (named as a parent, or displayed then replaced). */
  private readonly superseded = new BoundedSet<string>(256);
  /** id -> the semantic content last read under that id. */
  private readonly seenSem = new BoundedMap<string, string>(256);
  private unconditional = true;

  /** Forget the lineage (the displayed revision is kept); the next valid revision is adopted as is. */
  reset(): void {
    this.superseded.clear();
    this.seenSem.clear();
    this.unconditional = true;
  }

  observe(c: Candidate): Observation {
    if (c.kind === 'missing') {
      this.reset();
      this.diskHead = { kind: 'missing', verdict: 'keep' };
      return { verdict: 'keep' };
    }
    if (c.kind === 'unreadable' || c.kind === 'parse') {
      this.diskHead = { kind: c.kind, detail: c.detail, verdict: 'keep' };
      return { verdict: 'keep' };
    }
    const prevHead = this.diskHead;
    let prevSem: string | undefined;
    let head: DiskHead;
    if (c.ident) {
      prevSem = this.seenSem.get(c.ident.id);
      this.seenSem.set(c.ident.id, c.sem);
      if (c.ident.parent)
        this.superseded.add(c.ident.parent);
      head = { kind: 'revision', id: c.ident.id, parent: c.ident.parent };
    }
    else {
      head = { kind: 'bad-revision' };
    }
    this.diskHead = head;
    const value = c.result.value;
    if (!value) {
      head.verdict = 'invalid';
      // Bounded, single-line entries: issue paths can carry arbitrary artifact key text.
      head.issues = c.result.issues.slice(0, 8).map(displayIssue);
      return { verdict: 'invalid' };
    }
    const D = this.displayed;
    const C = value.document;
    let verdict: Verdict;
    if (!D || this.unconditional)
      verdict = 'adopt';
    else if (C.revision.id === D.id)
      verdict = c.sem === D.sem ? 'refresh' : 'same-id-changed';
    // A direct child of the displayed revision can never be older than it, even when its id was
    // named as a parent before (a restore or branch switch followed by a helper publish).
    else if ((C.revision.parent ?? null) === D.id)
      verdict = 'adopt';
    else if (this.superseded.has(C.revision.id) && (prevSem === undefined || prevSem === c.sem))
      verdict = 'obsolete';
    else
      verdict = 'adopt';
    let lineageNote: { from: string } | undefined;
    if (verdict === 'adopt') {
      if (D && D.id !== C.revision.id && !this.unconditional)
        this.superseded.add(D.id);
      if (prevHead?.kind === 'revision' && C.revision.id !== prevHead.id && (C.revision.parent ?? null) !== prevHead.id)
        lineageNote = { from: prevHead.id };
      // Re-adopting the displayed unverified revision (after Open or an ENOENT reset) keeps its
      // baseline: the panel validated this candidate against it, and the current fingerprints
      // include the changed bytes of every stale file, which would turn "stale" into a rejection.
      const keep = D && !D.verified && D.baseline && D.id === C.revision.id && D.sem === c.sem ? D.baseline : undefined;
      this.displayed = C.verification
        ? { id: C.revision.id, sem: c.sem, full: c.full, verified: true }
        : { id: C.revision.id, sem: c.sem, full: c.full, verified: false, baseline: keep ?? { ...value.fingerprints } };
      this.unconditional = false;
    }
    else if (verdict === 'refresh' && D) {
      // Same semantic content; the verification block may have changed.
      D.full = c.full;
      D.verified = !!C.verification;
      if (C.verification)
        delete D.baseline;
      else if (!D.baseline)
        D.baseline = { ...value.fingerprints };
    }
    head.verdict = verdict;
    return lineageNote ? { verdict, lineageNote } : { verdict };
  }
}
