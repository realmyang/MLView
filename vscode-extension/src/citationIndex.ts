/**
 * Viewer M3 (roadmap step 14), MLView: Reveal in Diagram: which claims of a validated revision cite
 * a line of a file.
 *
 * Built from the document's evidence records only: the files, line ranges and notebook cells the
 * model quoted, and the steps, connections and findings that cite each record (a finding's
 * counter-evidence included). It reads no source code and infers nothing: a line is cited when it
 * lies inside a range a claim quotes. The panel decides which ranges still hold (the file is not
 * stale and the editor's text still has the quote at the cited lines) before it asks this index.
 */
import { displayText } from './displayText';
import type { EvidenceBasis, WorkflowDocument, WorkflowEvidence } from './workflowDocument';

/** The webview's claim kinds: a step, a connection, a finding. */
export type ClaimKind = 'node' | 'edge' | 'issue';
export interface ClaimRef {
    kind: ClaimKind;
    id: string;
}
export interface CitedClaim extends ClaimRef {
    /** The step's or connection's label, or the finding's title, as authored. */
    title: string;
    /** `F1`, `F2`… by document order, as the diagram labels findings (viewer M2); findings only. */
    label?: string;
    severity?: 'low' | 'medium' | 'high';
    basis: EvidenceBasis;
    /**
     * The phase labels the claim belongs to, in document order: a step's phase, a connection's
     * source step's phase, and every phase a finding touches through the steps and connections it
     * cites (the PR #14 rule the phase counts use).
     */
    phases: string[];
    /** A connection's two ends, as their step labels. */
    ends?: [string, string];
    /** Place in document order among the claims of its kind. */
    order: number;
}
/** One cited range and the claims that cite it. */
export interface CitedRange {
    evidence: WorkflowEvidence;
    claims: { claim: CitedClaim; counter: boolean }[];
}
/** A claim found for a place in a file, with the range that cites it and how far that range is. */
export interface ClaimMatch {
    claim: CitedClaim;
    evidence: WorkflowEvidence;
    /** The range is the finding's counter-evidence. */
    counter: boolean;
    /** Cells between the range and the place (notebooks), then lines between them; 0 and 0 inside. */
    cells: number;
    lines: number;
    /** The range lies above the place (when `lines` > 0). */
    above: boolean;
}
const KIND_ORDER: Record<ClaimKind, number> = { node: 0, edge: 1, issue: 2 };
/** Steps, then connections, then findings; each in document order. */
const byKind = (a: CitedClaim, b: CitedClaim): number => KIND_ORDER[a.kind] - KIND_ORDER[b.kind] || a.order - b.order;
export class CitationIndex {
    private constructor(
        readonly document: WorkflowDocument,
        private readonly byFile: ReadonlyMap<string, readonly CitedRange[]>,
        private readonly claims: ReadonlyMap<string, CitedClaim>
    ) { }
    /** The index of a validated document: its references are known to resolve. */
    static from(document: WorkflowDocument): CitationIndex {
        const phaseLabel = new Map(document.phases.map(phase => [phase.id, phase.label]));
        const phaseRank = new Map(document.phases.map((phase, rank) => [phase.id, rank]));
        const nodes = new Map(document.nodes.map(node => [node.id, node]));
        const edges = new Map(document.edges.map(edge => [edge.id, edge]));
        const labels = (ids: Iterable<string>): string[] => [...new Set(ids)].filter(id => phaseLabel.has(id)).sort((a, b) => phaseRank.get(a)! - phaseRank.get(b)!).map(id => phaseLabel.get(id)!);
        const claims = new Map<string, CitedClaim>();
        const cites = new Map<string, { claim: CitedClaim; counter: boolean }[]>();
        const cite = (claim: CitedClaim, ids: readonly string[] | undefined, counter: boolean): void => {
            for (const id of new Set(ids ?? [])) {
                const list = cites.get(id) ?? [];
                if (!list.some(entry => entry.claim === claim))
                    list.push({ claim, counter });
                cites.set(id, list);
            }
        };
        document.nodes.forEach((node, order) => {
            const claim: CitedClaim = { kind: 'node', id: node.id, title: node.label, basis: node.basis, phases: labels([node.phase]), order };
            claims.set(key(claim), claim);
            cite(claim, node.evidence, false);
        });
        document.edges.forEach((edge, order) => {
            const source = nodes.get(edge.source);
            const target = nodes.get(edge.target);
            const claim: CitedClaim = { kind: 'edge', id: edge.id, title: edge.label, basis: edge.basis, phases: labels(source ? [source.phase] : []), ends: [source?.label ?? edge.source, target?.label ?? edge.target], order };
            claims.set(key(claim), claim);
            cite(claim, edge.evidence, false);
        });
        document.findings.forEach((finding, order) => {
            const touched = [
                ...finding.nodeIds.map(id => nodes.get(id)?.phase),
                ...(finding.edgeIds ?? []).map(id => nodes.get(edges.get(id)?.source ?? '')?.phase)
            ].filter((phase): phase is string => typeof phase === 'string');
            const claim: CitedClaim = { kind: 'issue', id: finding.id, title: finding.title, label: `F${order + 1}`, severity: finding.severity, basis: finding.basis, phases: labels(touched), order };
            claims.set(key(claim), claim);
            cite(claim, finding.evidence, false);
            cite(claim, finding.counterEvidence, true);
        });
        const byFile = new Map<string, CitedRange[]>();
        for (const evidence of document.evidence) {
            const cited = (cites.get(evidence.id) ?? []).slice().sort((a, b) => byKind(a.claim, b.claim));
            if (!cited.length)
                continue;
            const list = byFile.get(evidence.file) ?? [];
            list.push({ evidence, claims: cited });
            byFile.set(evidence.file, list);
        }
        return new CitationIndex(document, byFile, claims);
    }
    get revision(): string {
        return this.document.revision.id;
    }
    /** The workspace-relative files some claim cites, as the evidence records spell them. */
    files(): string[] {
        return [...this.byFile.keys()];
    }
    /** The ranges cited in `rel`, in document order. */
    ranges(rel: string): readonly CitedRange[] {
        return this.byFile.get(rel) ?? [];
    }
    /** The claim `ref` names, when this revision has it. */
    claim(ref: ClaimRef): CitedClaim | undefined {
        return this.claims.get(key(ref));
    }
}
const key = (ref: ClaimRef): string => `${ref.kind}\n${ref.id}`;
/** Whether a range is in the place's notebook cell (both undefined: a plain file). */
const sameCell = (evidence: WorkflowEvidence, cell: number | undefined): boolean => evidence.cell === cell;
/** How far `evidence` lies from lines `start`..`end` of `cell`; a cell range never matches a plain file (MAX_SAFE_INTEGER cells). */
function distance(evidence: WorkflowEvidence, cell: number | undefined, start: number, end: number): { cells: number; lines: number; above: boolean } {
    const cells = evidence.cell === undefined || cell === undefined ? (evidence.cell === cell ? 0 : Number.MAX_SAFE_INTEGER) : Math.abs(evidence.cell - cell);
    if (cells)
        return { cells, lines: 0, above: evidence.cell !== undefined && cell !== undefined && evidence.cell < cell };
    if (evidence.endLine < start)
        return { cells: 0, lines: start - evidence.endLine, above: true };
    if (evidence.line > end)
        return { cells: 0, lines: evidence.line - end, above: false };
    return { cells: 0, lines: 0, above: false };
}
/** Each claim once, from its nearest range. */
function perClaim(ranges: readonly CitedRange[], cell: number | undefined, start: number, end: number): ClaimMatch[] {
    const best = new Map<string, ClaimMatch>();
    for (const range of ranges) {
        const far = distance(range.evidence, cell, start, end);
        if (far.cells === Number.MAX_SAFE_INTEGER)
            continue;
        for (const { claim, counter } of range.claims) {
            const known = best.get(key(claim));
            if (!known || far.cells < known.cells || (far.cells === known.cells && far.lines < known.lines) || (far.cells === known.cells && far.lines === known.lines && known.counter && !counter))
                best.set(key(claim), { claim, evidence: range.evidence, counter, ...far });
        }
    }
    return [...best.values()];
}
/**
 * The claims whose cited lines include a line of `start`..`end` (one-based, inclusive) in the same
 * notebook cell, or none: steps, then connections, then findings, each in document order.
 */
export function claimsAt(ranges: readonly CitedRange[], cell: number | undefined, start: number, end: number): ClaimMatch[] {
    return perClaim(ranges.filter(range => sameCell(range.evidence, cell) && range.evidence.line <= end && range.evidence.endLine >= start), cell, start, end)
        .sort((a, b) => byKind(a.claim, b.claim));
}
/**
 * The claims cited nearest to `start`..`end` (none of them includes it), at most `limit`: the same
 * cell first, then the nearest cells, then the fewest lines away; ties in kind and document order.
 */
export function nearestClaims(ranges: readonly CitedRange[], cell: number | undefined, start: number, end: number, limit: number): ClaimMatch[] {
    return perClaim(ranges, cell, start, end)
        .sort((a, b) => a.cells - b.cells || a.lines - b.lines || byKind(a.claim, b.claim))
        .slice(0, Math.max(0, limit));
}
/** "line 12" or "lines 12–14". */
export function linesText(start: number, end: number): string {
    return start === end ? `line ${start}` : `lines ${start}–${end}`;
}
/**
 * Model text for a QuickPick row: bounded and escaped (displayText), and with VS Code's `$(icon)`
 * syntax escaped, so a title cannot draw an icon.
 */
export function pickText(value: string, max = 120): string {
    return displayText(value, max).replace(/\$\(/g, '\\$(');
}
const KIND_WORD: Record<ClaimKind, string> = { node: 'Step', edge: 'Connection', issue: 'Finding' };
/**
 * One claim as a QuickPick row: the kind and title (a finding's F label first), then its phase (a
 * finding's severity first; a basis other than observed), then where it is cited and, for a
 * nearest claim, how far from the cursor.
 */
export function claimPickText(match: ClaimMatch, nearest = false): { label: string; description: string; detail: string } {
    const { claim, evidence } = match;
    const title = claim.kind === 'edge' && claim.ends ? `${claim.ends[0]} → ${claim.ends[1]}` : claim.title;
    const label = `${claim.label ? claim.label + ' ' : ''}${KIND_WORD[claim.kind]}: ${pickText(title)}`;
    const description = [
        ...(claim.kind === 'edge' && claim.title ? [`“${pickText(claim.title, 80)}”`] : []),
        ...(claim.severity ? [claim.severity] : []),
        ...(claim.phases.length ? [pickText(claim.phases.join(', '), 80)] : []),
        ...(claim.basis !== 'observed' ? [claim.basis] : [])
    ].join(' · ');
    const where = `${evidence.cell !== undefined ? `cell ${evidence.cell}, ` : ''}${linesText(evidence.line, evidence.endLine)}`;
    let detail = `${match.counter ? 'Counter-evidence' : 'Cited'} at ${where}`;
    if (nearest && match.cells)
        detail += `, ${match.cells} ${match.cells === 1 ? 'cell' : 'cells'} ${match.above ? 'above' : 'below'}`;
    else if (nearest && match.lines)
        detail += `, ${match.lines} ${match.lines === 1 ? 'line' : 'lines'} ${match.above ? 'above' : 'below'}`;
    return { label, description, detail };
}
