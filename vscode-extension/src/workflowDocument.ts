import * as crypto from 'node:crypto';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';
import { toEditorLine } from './authoredSupport';
export type EvidenceBasis = 'observed' | 'inferred' | 'unresolved';
export interface WorkflowEvidence {
    id: string;
    file: string;
    line: number;
    endLine: number;
    quote: string;
    cell?: number;
}
export interface WorkflowDocument {
    workflowVersion: '1.0';
    title: string;
    producer: {
        kind: 'host-llm';
        host: 'copilot' | 'codex' | 'claude-code' | 'unknown';
        model?: string;
    };
    revision: {
        id: string;
        parent?: string;
    };
    request: {
        question: string;
        scope: string;
        entrypoints?: string[];
        configuration?: string;
    };
    phases: {
        id: string;
        label: string;
    }[];
    nodes: {
        id: string;
        label: string;
        phase: string;
        parent?: string;
        kind?: string;
        detail?: string;
        basis: EvidenceBasis;
        evidence: string[];
    }[];
    edges: {
        id: string;
        source: string;
        target: string;
        label: string;
        kind?: string;
        basis: EvidenceBasis;
        evidence: string[];
    }[];
    findings: {
        id: string;
        title: string;
        message: string;
        severity: 'low' | 'medium' | 'high';
        nodeIds: string[];
        edgeIds?: string[];
        basis: EvidenceBasis;
        evidence: string[];
        counterEvidence?: string[];
        suggestion?: string;
    }[];
    evidence: WorkflowEvidence[];
    coverage: {
        status: 'scoped' | 'partial';
        summary: string;
        inspectedFiles: string[];
        limitations: string[];
    };
    verification?: {
        files: Record<string, string>;
        publishedAt: string;
    };
}
export interface ValidationIssue {
    path: string;
    message: string;
}
export interface ValidatedWorkflow {
    document: WorkflowDocument;
    files: string[];
    staleFiles: string[];
}
export type ReadText = (absolutePath: string) => Promise<string>;
export type ReadNotebookCell = (absolutePath: string, cell: number) => Promise<string | undefined>;
const BASIS = new Set(['observed', 'inferred', 'unresolved']);
const HOSTS = new Set(['copilot', 'codex', 'claude-code', 'unknown']);
const SEVERITIES = new Set(['low', 'medium', 'high']);
const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const RFC3339 = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|[+-](\d{2}):(\d{2}))$/;
const own = (o: object, k: string): boolean => Object.prototype.hasOwnProperty.call(o, k);
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const strings = (v: unknown): v is string[] => Array.isArray(v) && v.every(x => typeof x === 'string' && x.length > 0);
const relativePath = (value: string): boolean => value.length > 0 && value.length <= 500 && !path.posix.isAbsolute(value) && !value.includes('\\') && !value.split('/').some(part => part === '' || part === '.' || part === '..') && !value.includes('\0');
const strictRfc3339 = (value: string): boolean => {
    const match = RFC3339.exec(value);
    if (!match)
        return false;
    const [, year, month, day, hour, minute, second, offsetHour = '00', offsetMinute = '00'] = match;
    const parts = [year, month, day, hour, minute, second, offsetHour, offsetMinute].map(Number);
    if (parts.slice(3, 6).some((part, i) => part > [23, 59, 59][i]!) || parts[6]! > 23 || parts[7]! > 59)
        return false;
    if (parts[0] === 0)
        return false;
    const date = new Date(0);
    date.setUTCHours(0, 0, 0, 0);
    date.setUTCFullYear(parts[0]!, parts[1]! - 1, parts[2]!);
    return date.getUTCFullYear() === parts[0] && date.getUTCMonth() === parts[1]! - 1 && date.getUTCDate() === parts[2];
};
function maxText(o: Record<string, unknown>, key: string, maximum: number, at: string, out: ValidationIssue[]): void {
    if (typeof o[key] === 'string' && (o[key] as string).length > maximum)
        out.push({ path: `${at}.${key}`, message: `must be at most ${maximum} characters` });
}
const text = (o: Record<string, unknown>, k: string, at: string, out: ValidationIssue[]): string => {
    if (typeof o[k] !== 'string' || (o[k] as string).length === 0)
        out.push({ path: `${at}.${k}`, message: 'must be a non-empty string' });
    return typeof o[k] === 'string' ? o[k] as string : '';
};
function exactKeys(o: Record<string, unknown>, allowed: string[], required: string[], at: string, out: ValidationIssue[]): void {
    for (const k of required)
        if (!own(o, k))
            out.push({ path: `${at}.${k}`, message: 'is required' });
    for (const k of Object.keys(o))
        if (!allowed.includes(k))
            out.push({ path: `${at}.${k}`, message: 'is not allowed' });
}
function unique(items: {
    id: string;
}[], at: string, out: ValidationIssue[]): Set<string> {
    const ids = new Set<string>();
    for (let i = 0; i < items.length; i++) {
        const id = items[i]?.id;
        if (!id)
            continue;
        if (!ID.test(id))
            out.push({ path: `${at}[${i}].id`, message: 'has an invalid ID format' });
        if (ids.has(id))
            out.push({ path: `${at}[${i}].id`, message: 'must be unique' });
        ids.add(id);
    }
    return ids;
}
function parseList(v: unknown, at: string, out: ValidationIssue[]): Record<string, unknown>[] {
    if (!Array.isArray(v)) {
        out.push({ path: at, message: 'must be an array' });
        return [];
    }
    return v.map((x, i) => {
        if (!object(x)) {
            out.push({ path: `${at}[${i}]`, message: 'must be an object' });
            return {};
        }
        return x;
    });
}
export function validateWorkflowStructure(raw: unknown): {
    document?: WorkflowDocument;
    issues: ValidationIssue[];
} {
    const issues: ValidationIssue[] = [];
    if (!object(raw))
        return { issues: [{ path: '$', message: 'must be an object' }] };
    exactKeys(raw, ['workflowVersion', 'title', 'producer', 'revision', 'request', 'phases', 'nodes', 'edges', 'findings', 'evidence', 'coverage', 'verification'], ['workflowVersion', 'title', 'producer', 'revision', 'request', 'phases', 'nodes', 'edges', 'findings', 'evidence', 'coverage'], '$', issues);
    if (raw.workflowVersion !== '1.0')
        issues.push({ path: '$.workflowVersion', message: 'must equal "1.0"' });
    text(raw, 'title', '$', issues);
    if (typeof raw.title === 'string' && raw.title.length > 200)
        issues.push({ path: '$.title', message: 'must be at most 200 characters' });
    const producer = object(raw.producer) ? raw.producer : {};
    exactKeys(producer, ['kind', 'host', 'model'], ['kind', 'host'], '$.producer', issues);
    if (producer.kind !== 'host-llm')
        issues.push({ path: '$.producer.kind', message: 'must equal "host-llm"' });
    if (!HOSTS.has(String(producer.host)))
        issues.push({ path: '$.producer.host', message: 'is unsupported' });
    if (own(producer, 'model') && typeof producer.model !== 'string')
        issues.push({ path: '$.producer.model', message: 'must be a string' });
    if (own(producer, 'model')) {
        maxText(producer, 'model', 200, '$.producer', issues);
        if (producer.model === '')
            issues.push({ path: '$.producer.model', message: 'must not be empty' });
    }
    const revision = object(raw.revision) ? raw.revision : {};
    exactKeys(revision, ['id', 'parent'], ['id'], '$.revision', issues);
    text(revision, 'id', '$.revision', issues);
    if (typeof revision.id === 'string' && !ID.test(revision.id))
        issues.push({ path: '$.revision.id', message: 'has an invalid ID format' });
    if (own(revision, 'parent') && typeof revision.parent !== 'string')
        issues.push({ path: '$.revision.parent', message: 'must be a string' });
    if (revision.parent === revision.id)
        issues.push({ path: '$.revision.parent', message: 'cannot equal revision id' });
    if (typeof revision.parent === 'string' && !ID.test(revision.parent))
        issues.push({ path: '$.revision.parent', message: 'has an invalid ID format' });
    const request = object(raw.request) ? raw.request : {};
    exactKeys(request, ['question', 'scope', 'entrypoints', 'configuration'], ['question', 'scope'], '$.request', issues);
    text(request, 'question', '$.request', issues);
    text(request, 'scope', '$.request', issues);
    maxText(request, 'question', 4000, '$.request', issues);
    maxText(request, 'scope', 2000, '$.request', issues);
    if (own(request, 'entrypoints') && !strings(request.entrypoints))
        issues.push({ path: '$.request.entrypoints', message: 'must be non-empty strings' });
    if (Array.isArray(request.entrypoints)) {
        if (request.entrypoints.length > 100)
            issues.push({ path: '$.request.entrypoints', message: 'must contain at most 100 paths' });
        request.entrypoints.forEach((value, i) => { if (typeof value === 'string' && !relativePath(value))
            issues.push({ path: `$.request.entrypoints[${i}]`, message: 'must be a slash-separated workspace-relative path' }); });
    }
    if (own(request, 'configuration') && typeof request.configuration !== 'string')
        issues.push({ path: '$.request.configuration', message: 'must be a string' });
    if (own(request, 'configuration')) {
        maxText(request, 'configuration', 2000, '$.request', issues);
        if (request.configuration === '')
            issues.push({ path: '$.request.configuration', message: 'must not be empty' });
    }
    const limits: [
        string,
        Record<string, unknown>[],
        number,
        number
    ][] = [['$.phases', parseList(raw.phases, '$.phases', issues), 1, 100], ['$.nodes', parseList(raw.nodes, '$.nodes', issues), 1, 2000], ['$.edges', parseList(raw.edges, '$.edges', issues), 0, 4000], ['$.findings', parseList(raw.findings, '$.findings', issues), 0, 1000], ['$.evidence', parseList(raw.evidence, '$.evidence', issues), 0, 5000]];
    for (const [at, list, min, max] of limits)
        if (list.length < min || list.length > max)
            issues.push({ path: at, message: `must contain ${min}..${max} items` });
    const phases = limits[0]![1];
    phases.forEach((x, i) => { const at = `$.phases[${i}]`; exactKeys(x, ['id', 'label'], ['id', 'label'], at, issues); text(x, 'id', at, issues); text(x, 'label', at, issues); maxText(x, 'label', 200, at, issues); });
    const nodes = limits[1]![1];
    nodes.forEach((x, i) => {
        const a = `$.nodes[${i}]`;
        exactKeys(x, ['id', 'label', 'phase', 'parent', 'kind', 'detail', 'basis', 'evidence'], ['id', 'label', 'phase', 'basis', 'evidence'], a, issues);
        ['id', 'label', 'phase'].forEach(k => text(x, k, a, issues));
        maxText(x, 'label', 300, a, issues);
        maxText(x, 'kind', 100, a, issues);
        maxText(x, 'detail', 8000, a, issues);
        if (!BASIS.has(String(x.basis)))
            issues.push({ path: `${a}.basis`, message: 'is invalid' });
        if (!strings(x.evidence) && !(Array.isArray(x.evidence) && x.evidence.length === 0))
            issues.push({ path: `${a}.evidence`, message: 'must be string IDs' });
        for (const k of ['parent', 'kind', 'detail'])
            if (own(x, k) && typeof x[k] !== 'string')
                issues.push({ path: `${a}.${k}`, message: 'must be a string' });
        if (x.kind === '')
            issues.push({ path: `${a}.kind`, message: 'must not be empty' });
    });
    const edges = limits[2]![1];
    edges.forEach((x, i) => {
        const a = `$.edges[${i}]`;
        exactKeys(x, ['id', 'source', 'target', 'label', 'kind', 'basis', 'evidence'], ['id', 'source', 'target', 'label', 'basis', 'evidence'], a, issues);
        ['id', 'source', 'target', 'label'].forEach(k => text(x, k, a, issues));
        maxText(x, 'label', 300, a, issues);
        maxText(x, 'kind', 100, a, issues);
        if (!BASIS.has(String(x.basis)))
            issues.push({ path: `${a}.basis`, message: 'is invalid' });
        if (!Array.isArray(x.evidence) || !x.evidence.every(y => typeof y === 'string'))
            issues.push({ path: `${a}.evidence`, message: 'must be string IDs' });
        if (own(x, 'kind') && typeof x.kind !== 'string')
            issues.push({ path: `${a}.kind`, message: 'must be a string' });
        if (x.kind === '')
            issues.push({ path: `${a}.kind`, message: 'must not be empty' });
    });
    const findings = limits[3]![1];
    findings.forEach((x, i) => {
        const a = `$.findings[${i}]`;
        exactKeys(x, ['id', 'title', 'message', 'severity', 'nodeIds', 'edgeIds', 'basis', 'evidence', 'counterEvidence', 'suggestion'], ['id', 'title', 'message', 'severity', 'nodeIds', 'basis', 'evidence'], a, issues);
        ['id', 'title', 'message'].forEach(k => text(x, k, a, issues));
        maxText(x, 'title', 300, a, issues);
        maxText(x, 'message', 8000, a, issues);
        maxText(x, 'suggestion', 4000, a, issues);
        if (!SEVERITIES.has(String(x.severity)))
            issues.push({ path: `${a}.severity`, message: 'is invalid' });
        if (!BASIS.has(String(x.basis)))
            issues.push({ path: `${a}.basis`, message: 'is invalid' });
        for (const k of ['nodeIds', 'evidence', 'edgeIds', 'counterEvidence'])
            if (own(x, k) && !strings(x[k]) && !(Array.isArray(x[k]) && x[k].length === 0))
                issues.push({ path: `${a}.${k}`, message: 'must contain string IDs' });
        if (own(x, 'suggestion') && typeof x.suggestion !== 'string')
            issues.push({ path: `${a}.suggestion`, message: 'must be a string' });
    });
    const evidence = limits[4]![1];
    evidence.forEach((x, i) => {
        const a = `$.evidence[${i}]`;
        exactKeys(x, ['id', 'file', 'line', 'endLine', 'quote', 'cell'], ['id', 'file', 'line', 'endLine', 'quote'], a, issues);
        ['id', 'file'].forEach(k => text(x, k, a, issues));
        if (typeof x.file === 'string' && !relativePath(x.file))
            issues.push({ path: `${a}.file`, message: 'must be a slash-separated workspace-relative path' });
        if (typeof x.quote !== 'string')
            issues.push({ path: `${a}.quote`, message: 'must be a string' });
        if (typeof x.quote === 'string' && x.quote.length > 16000)
            issues.push({ path: `${a}.quote`, message: 'must be at most 16000 characters' });
        for (const k of ['line', 'endLine'])
            if (!Number.isInteger(x[k]) || Number(x[k]) < 1)
                issues.push({ path: `${a}.${k}`, message: 'must be a positive integer' });
        if (Number(x.endLine) < Number(x.line))
            issues.push({ path: `${a}.endLine`, message: 'must be at least line' });
        if (own(x, 'cell') && (!Number.isInteger(x.cell) || Number(x.cell) < 0))
            issues.push({ path: `${a}.cell`, message: 'must be a zero-based integer' });
    });
    const coverage = object(raw.coverage) ? raw.coverage : {};
    exactKeys(coverage, ['status', 'summary', 'inspectedFiles', 'limitations'], ['status', 'summary', 'inspectedFiles', 'limitations'], '$.coverage', issues);
    if (coverage.status !== 'scoped' && coverage.status !== 'partial')
        issues.push({ path: '$.coverage.status', message: 'must be scoped or partial' });
    text(coverage, 'summary', '$.coverage', issues);
    maxText(coverage, 'summary', 4000, '$.coverage', issues);
    for (const k of ['inspectedFiles', 'limitations'])
        if (!Array.isArray(coverage[k]) || !(coverage[k] as unknown[]).every(x => typeof x === 'string'))
            issues.push({ path: `$.coverage.${k}`, message: 'must be strings' });
    if (Array.isArray(coverage.inspectedFiles)) {
        if (coverage.inspectedFiles.length > 2000)
            issues.push({ path: '$.coverage.inspectedFiles', message: 'must contain at most 2000 paths' });
        coverage.inspectedFiles.forEach((v, i) => { if (typeof v !== 'string' || !relativePath(v))
            issues.push({ path: `$.coverage.inspectedFiles[${i}]`, message: 'must contain non-empty workspace-relative paths' }); });
    }
    if (Array.isArray(coverage.limitations)) {
        if (coverage.limitations.length > 500)
            issues.push({ path: '$.coverage.limitations', message: 'must contain at most 500 items' });
        coverage.limitations.forEach((v, i) => { if (typeof v !== 'string' || !v || v.length > 2000)
            issues.push({ path: `$.coverage.limitations[${i}]`, message: 'must contain non-empty strings of at most 2000 characters' }); });
    }
    if (own(raw, 'verification') && !object(raw.verification))
        issues.push({ path: '$.verification', message: 'must be an object' });
    if (object(raw.verification)) {
        exactKeys(raw.verification, ['files', 'publishedAt'], ['files', 'publishedAt'], '$.verification', issues);
        if (!object(raw.verification.files) || Object.values(raw.verification.files).some(x => typeof x !== 'string' || !/^[a-f0-9]{64}$/.test(x)))
            issues.push({ path: '$.verification.files', message: 'must map paths to lowercase SHA-256 hashes' });
        if (object(raw.verification.files)) {
            if (Object.keys(raw.verification.files).length > 2000)
                issues.push({ path: '$.verification.files', message: 'must contain at most 2000 files' });
            for (const key of Object.keys(raw.verification.files))
                if (!relativePath(key))
                    issues.push({ path: `$.verification.files.${key}`, message: 'must use a workspace-relative path' });
        }
        const published = text(raw.verification, 'publishedAt', '$.verification', issues);
        if (published && !strictRfc3339(published))
            issues.push({ path: '$.verification.publishedAt', message: 'must be an ISO date-time' });
    }
    const phaseIds = unique(phases as {
        id: string;
    }[], '$.phases', issues), nodeIds = unique(nodes as {
        id: string;
    }[], '$.nodes', issues), edgeIds = unique(edges as {
        id: string;
    }[], '$.edges', issues), evidenceIds = unique(evidence as {
        id: string;
    }[], '$.evidence', issues);
    unique(findings as {
        id: string;
    }[], '$.findings', issues);
    nodes.forEach((n, i) => {
        if (!phaseIds.has(String(n.phase)))
            issues.push({ path: `$.nodes[${i}].phase`, message: 'references an unknown phase' });
        if (n.parent && !nodeIds.has(String(n.parent)))
            issues.push({ path: `$.nodes[${i}].parent`, message: 'references an unknown node' });
    });
    edges.forEach((e, i) => {
        for (const k of ['source', 'target'])
            if (!nodeIds.has(String(e[k])))
                issues.push({ path: `$.edges[${i}].${k}`, message: 'references an unknown node' });
    });
    const checkRefs = (xs: unknown, valid: Set<string>, at: string) => {
        if (!Array.isArray(xs))
            return;
        if (xs.length > 100)
            issues.push({ path: at, message: 'must contain at most 100 IDs' });
        const seen = new Set<string>();
        xs.forEach((x, i) => {
            if (typeof x === 'string' && seen.has(x))
                issues.push({ path: `${at}[${i}]`, message: 'must be unique' });
            if (typeof x === 'string')
                seen.add(x);
            if (typeof x !== 'string' || !ID.test(x) || !valid.has(x))
                issues.push({ path: `${at}[${i}]`, message: 'references an unknown or invalid id' });
        });
    };
    nodes.forEach((n, i) => checkRefs(n.evidence, evidenceIds, `$.nodes[${i}].evidence`));
    edges.forEach((e, i) => checkRefs(e.evidence, evidenceIds, `$.edges[${i}].evidence`));
    findings.forEach((f, i) => { checkRefs(f.nodeIds, nodeIds, `$.findings[${i}].nodeIds`); checkRefs(f.edgeIds, edgeIds, `$.findings[${i}].edgeIds`); checkRefs(f.evidence, evidenceIds, `$.findings[${i}].evidence`); checkRefs(f.counterEvidence, evidenceIds, `$.findings[${i}].counterEvidence`); });
    // Resolve each parent chain once. Repeated Array.find calls made a valid
    // maximum-size nested workflow quadratic-to-cubic work for untrusted input.
    const nodeById = new Map(nodes.map(n => [String(n.id), n]));
    const resolvedParents = new Set<string>();
    let cyclicParents = false;
    for (const node of nodes) {
        let current: Record<string, unknown> | undefined = node;
        const chain: string[] = [];
        const inChain = new Set<string>();
        while (current) {
            const id = String(current.id);
            if (resolvedParents.has(id))
                break;
            if (inChain.has(id)) {
                cyclicParents = true;
                break;
            }
            inChain.add(id);
            chain.push(id);
            current = typeof current.parent === 'string' ? nodeById.get(current.parent) : undefined;
        }
        for (const id of chain)
            resolvedParents.add(id);
        if (cyclicParents)
            break;
    }
    if (cyclicParents)
        issues.push({ path: '$.nodes', message: 'parent relationships must form a forest' });
    return issues.length ? { issues } : { document: raw as unknown as WorkflowDocument, issues };
}
export async function validateWorkflow(raw: unknown, root: string, readText: ReadText = async (p) => fs.readFile(p, 'utf8'), readNotebookCell?: ReadNotebookCell): Promise<{
    value?: ValidatedWorkflow;
    issues: ValidationIssue[];
}> {
    const structural = validateWorkflowStructure(raw);
    if (!structural.document)
        return { issues: structural.issues };
    const doc = structural.document;
    const issues = [...structural.issues];
    const realRoot = await fs.realpath(root);
    const stale = new Set<string>(), files = new Set<string>();
    // Evidence commonly cites several ranges in one source file. Cache the
    // workspace-aware reader so validation reads and hashes that file once.
    type CachedSource = { raw: string; hash: string; lines: string[]; notebook?: { cells?: { source?: string[] | string }[] } };
    const sourceCache = new Map<string, Promise<CachedSource>>();
    const sourceFor = (file: string): Promise<CachedSource> => {
        let source = sourceCache.get(file);
        if (!source) {
            source = readText(file).then(raw => {
                const normalized = raw.replace(/\r\n?/g, '\n');
                return { raw, hash: crypto.createHash('sha256').update(raw).digest('hex'), lines: normalized.split('\n') };
            });
            sourceCache.set(file, source);
        }
        return source;
    };
    const contained = (value: string): boolean => value === realRoot || value.startsWith(realRoot + path.sep);
    for (let i = 0; i < doc.evidence.length; i++) {
        const e = doc.evidence[i]!;
        const at = `$.evidence[${i}]`;
        if (path.isAbsolute(e.file)) {
            issues.push({ path: `${at}.file`, message: 'must be workspace-relative' });
            continue;
        }
        const candidate = path.resolve(realRoot, e.file);
        if (!contained(candidate)) {
            issues.push({ path: `${at}.file`, message: 'escapes the owning workspace' });
            continue;
        }
        const expected = doc.verification?.files[e.file];
        let real: string;
        try {
            real = await fs.realpath(candidate);
        }
        catch {
            if (expected) {
                files.add(candidate);
                stale.add(candidate);
                continue;
            }
            issues.push({ path: `${at}.file`, message: 'does not exist' });
            continue;
        }
        if (!contained(real)) {
            issues.push({ path: `${at}.file`, message: 'escapes the owning workspace' });
            continue;
        }
        files.add(real);
        let cached: CachedSource;
        try {
            cached = await sourceFor(real);
        }
        catch {
            if (expected) {
                stale.add(real);
                continue;
            }
            issues.push({ path: `${at}.file`, message: 'cannot be read' });
            continue;
        }
        const hashMatches = expected === undefined || cached.hash === expected;
        if (!hashMatches)
            stale.add(real);
        let lines = cached.lines;
        let usedOpenCell = false;
        if (e.cell !== undefined) {
            try {
                const openCell = await readNotebookCell?.(real, e.cell);
                if (openCell !== undefined) {
                    usedOpenCell = true;
                    lines = openCell.replace(/\r\n?/g, '\n').split('\n');
                }
                else {
                    cached.notebook ??= JSON.parse(cached.raw) as CachedSource['notebook'];
                    const cell = cached.notebook?.cells?.[e.cell];
                    if (!cell)
                        throw new Error();
                    const body = Array.isArray(cell.source) ? cell.source.join('') : String(cell.source ?? '');
                    lines = body.replace(/\r\n?/g, '\n').split('\n');
                }
            }
            catch {
                if (!hashMatches || (usedOpenCell && expected !== undefined)) {
                    stale.add(real);
                    continue;
                }
                issues.push({ path: `${at}.cell`, message: 'does not resolve to a notebook cell' });
                continue;
            }
        }
        if (e.endLine > lines.length) {
            if (!hashMatches || (usedOpenCell && expected !== undefined)) {
                stale.add(real);
                continue;
            }
            issues.push({ path: `${at}.endLine`, message: 'is outside the cited source' });
            continue;
        }
        const quote = lines.slice(toEditorLine(e.line), e.endLine).join('\n');
        if (quote !== e.quote.replace(/\r\n?/g, '\n')) {
            if (!hashMatches || (usedOpenCell && expected !== undefined))
                stale.add(real);
            else
                issues.push({ path: `${at}.quote`, message: 'does not exactly match the current LF-normalized lines' });
        }
    }
    for (const [rel, expected] of Object.entries(doc.verification?.files ?? {})) {
        if (path.isAbsolute(rel)) {
            issues.push({ path: '$.verification.files', message: `${rel} must be workspace-relative` });
            continue;
        }
        const abs = path.resolve(realRoot, rel);
        if (!contained(abs)) {
            issues.push({ path: '$.verification.files', message: `${rel} escapes the owning workspace` });
            continue;
        }
        let real: string;
        try {
            real = await fs.realpath(abs);
        }
        catch {
            files.add(abs);
            stale.add(abs);
            continue;
        }
        if (!contained(real)) {
            issues.push({ path: '$.verification.files', message: `${rel} escapes the owning workspace` });
            continue;
        }
        files.add(real);
        try {
            const current = await sourceFor(real);
            if (current.hash !== expected)
                stale.add(real);
        }
        catch {
            stale.add(real);
        }
    }
    for (const rel of doc.coverage.inspectedFiles) {
        if (path.isAbsolute(rel)) {
            issues.push({ path: '$.coverage.inspectedFiles', message: `${rel} must be workspace-relative` });
            continue;
        }
        const abs = path.resolve(realRoot, rel);
        if (!contained(abs)) {
            issues.push({ path: '$.coverage.inspectedFiles', message: `${rel} escapes the owning workspace` });
            continue;
        }
        const expected = doc.verification?.files[rel];
        let real: string;
        try {
            real = await fs.realpath(abs);
        }
        catch {
            if (expected) {
                files.add(abs);
                stale.add(abs);
                continue;
            }
            issues.push({ path: '$.coverage.inspectedFiles', message: `${rel} does not exist` });
            continue;
        }
        if (!contained(real)) {
            issues.push({ path: '$.coverage.inspectedFiles', message: `${rel} escapes the owning workspace` });
            continue;
        }
        files.add(real);
    }
    return issues.length ? { issues } : { value: { document: doc, files: [...files], staleFiles: [...stale] }, issues };
}
