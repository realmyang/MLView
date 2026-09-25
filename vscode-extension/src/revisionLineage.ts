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

/** Canonical JSON: arrays keep order, object keys sorted (UTF-16 order), primitives via JSON.stringify. */
export function canonicalJson(value: unknown): string {
  if (Array.isArray(value))
    return '[' + value.map(item => canonicalJson(item)).join(',') + ']';
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>;
    return '{' + Object.keys(record).sort().map(key => JSON.stringify(key) + ':' + canonicalJson(record[key])).join(',') + '}';
  }
  const primitive = JSON.stringify(value);
  return primitive === undefined ? 'null' : primitive;
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
      head.issues = c.result.issues.slice(0, 8).map(issue => `${issue.path}: ${issue.message}`);
      return { verdict: 'invalid' };
    }
    const D = this.displayed;
    const C = value.document;
    let verdict: Verdict;
    if (!D || this.unconditional)
      verdict = 'adopt';
    else if (C.revision.id === D.id)
      verdict = c.sem === D.sem ? 'refresh' : 'same-id-changed';
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
      this.displayed = C.verification
        ? { id: C.revision.id, sem: c.sem, full: c.full, verified: true }
        : { id: C.revision.id, sem: c.sem, full: c.full, verified: false, baseline: { ...value.fingerprints } };
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
