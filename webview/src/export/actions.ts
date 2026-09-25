/**
 * What the export menu actually does (VIEW-07).
 *
 * Three regions × four outputs, plus print. The region is pure geometry over
 * the `LayoutFrame`, the outputs all descend from ONE `buildExportSvg` call, and
 * the bytes leave the viewer through exactly two doors:
 *
 *   - `exportFile` — the host writes the file. The VS Code webview cannot open
 *     a save dialog and must not try; the standalone bridge answers the same
 *     message with a download and falls back to the copy toast (CONTRACTS
 *     11.17.1 already owns that toast, so a blocked download still tells the
 *     truth instead of silently doing nothing).
 *   - the async clipboard API, attempted here because it is the one path that
 *     works identically in both hosts. Every failure — no API, a denied
 *     permission, an image type the host will not take — falls back to the
 *     `copy` message, which each host already implements.
 *
 * Nothing here throws at a caller: an export that could not happen says so in
 * the toast and the live region, which is the whole difference between this and
 * a button that appears to work.
 */

import { buildExportSvg, ExportRegionKind, ExportSvgResult } from './svg.js';
import { MIME, base64ToBytes, rasterize, utf8ToBase64 } from './raster.js';
import type { Palette } from './palette.js';
import type { ScenePlan } from '../render/plan.js';
import type { Rect } from '../render/canvas.js';
import type { ActionResult, MLGraph, ThemeKind, UiToHost } from '../types.js';

/** How much world margin a cropped region keeps around its content. */
const REGION_PAD = 24;

/** The PNG is drawn at twice the SVG's user units (VIEW-07). */
export const PNG_SCALE = 2;

export interface ExportHost {
  post(msg: UiToHost): void;
  /**
   * Post a request the host answers with one `actionResult` (§1e). The
   * handler runs when that answer arrives; nothing is claimed before it.
   */
  request(msg: UiToHost, onResult: (result: ActionResult) => void): void;
  toast(text: string): void;
  announce(text: string): void;
  /** `window.print()`, injected so a gate can observe the call. */
  print(): void;
}

export interface ExportRequest {
  plan: ScenePlan;
  palette: Palette;
  theme: ThemeKind;
  graph: MLGraph;
  regionKind: ExportRegionKind;
  /** The visible canvas rectangle in world coordinates. */
  viewRect: Rect;
  /** A human name for the active scope, or null when nothing is scoped. */
  scopeLabel: string | null;
  generatedAt?: string;
}

/**
 * The world rectangle a region names.
 *
 * `scope` is the bounding box of the CORE nodes — the scope's actual subject —
 * rather than the whole projection, because a projection also carries boundary
 * stubs and context frames that the reader did not ask to share. With no
 * projection there is no core, and it degrades to the whole diagram rather than
 * exporting an empty rectangle.
 */
export function regionRect(request: ExportRequest): Rect {
  const frame = request.plan.frame;
  const whole: Rect = { x: 0, y: 0, w: frame.width, h: frame.height };
  if (request.regionKind === 'diagram') return whole;
  if (request.regionKind === 'view') return clampTo(request.viewRect, whole);
  const boxes: Rect[] = [];
  for (const planned of request.plan.nodes) {
    if (planned.visual.node.viewRole !== 'core') continue;
    const box = planned.visual.box;
    boxes.push({ x: box.x, y: box.y, w: box.w, h: box.h });
  }
  if (!boxes.length) return whole;
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const box of boxes) {
    minX = Math.min(minX, box.x);
    minY = Math.min(minY, box.y);
    maxX = Math.max(maxX, box.x + box.w);
    maxY = Math.max(maxY, box.y + box.h);
  }
  return clampTo(
    { x: minX - REGION_PAD, y: minY - REGION_PAD, w: maxX - minX + REGION_PAD * 2, h: maxY - minY + REGION_PAD * 2 },
    whole,
  );
}

function clampTo(rect: Rect, whole: Rect): Rect {
  const x = Math.max(whole.x, Math.min(rect.x, whole.x + whole.w));
  const y = Math.max(whole.y, Math.min(rect.y, whole.y + whole.h));
  const w = Math.max(1, Math.min(rect.w, whole.x + whole.w - x));
  const h = Math.max(1, Math.min(rect.h, whole.y + whole.h - y));
  return { x, y, w, h };
}

/** True when the `scope` region has a subject of its own to offer. */
export function hasScopeRegion(plan: ScenePlan | null): boolean {
  if (!plan) return false;
  for (const planned of plan.nodes) {
    if (planned.visual.node.viewRole === 'core') return true;
  }
  return false;
}

export function regionLabel(kind: ExportRegionKind): string {
  if (kind === 'view') return 'current view';
  if (kind === 'scope') return 'current scope';
  return 'whole diagram';
}

/**
 * The same three regions in the HOST's vocabulary: the host-side amendment
 * calls the whole diagram `all`, this renderer calls it `diagram`. One mapping,
 * stated once, rather than two words drifting apart in five call sites.
 */
export function hostRegionWord(kind: ExportRegionKind): 'view' | 'all' | 'scope' {
  return kind === 'diagram' ? 'all' : kind;
}

/** The inverse, for a `requestExport` frame. Anything unknown means the whole. */
export function regionFromHostWord(word: string | undefined): ExportRegionKind {
  if (word === 'view') return 'view';
  if (word === 'scope') return 'scope';
  return 'diagram';
}

/** Build the picture. Everything downstream is a delivery of this one result. */
export function renderExport(request: ExportRequest): ExportSvgResult {
  const graph = request.graph;
  const scope = request.scopeLabel;
  const title =
    'MLView — ' + subjectOf(graph) + (scope ? ' — ' + scope : '') + ' — ' + regionLabel(request.regionKind);
  const desc =
    graph.nodes.length + ' nodes, ' + graph.edges.length + ' edges · schema ' + graph.schemaVersion +
    (graph.schemaVersion === 'workflow-view/1'
      ? ' · authored by ' + graph.generator.name + ' · model ' + graph.generator.version + ' · revision ' + graph.generator.rendererSha
      : ' · mlview ' + graph.generator.version) +
    (request.generatedAt ? ' · exported ' + request.generatedAt : '');
  return buildExportSvg({
    plan: request.plan,
    palette: request.palette,
    theme: request.theme,
    region: regionRect(request),
    regionKind: request.regionKind,
    title,
    desc,
  });
}

/** `mlview-vision_pipeline-evaluation-diagram.svg`, and nothing a shell hates. */
export function exportFileName(request: ExportRequest, ext: string): string {
  const bits = ['mlview', subjectOf(request.graph)];
  if (request.scopeLabel) bits.push(request.scopeLabel);
  bits.push(request.regionKind);
  return bits.map(slug).filter((s) => !!s).join('-') + '.' + ext;
}

/**
 * What the picture is of. An authored document carries its TITLE where the
 * analyzer kept a workspace path, and a title such as `Train/eval loop` is not
 * a path: it is used whole (RENDER-8). An analyzer root is still reduced to its
 * last segment.
 */
function subjectOf(graph: MLGraph): string {
  if (graph.schemaVersion === 'workflow-view/1') return String(graph.workspace.root || '') || 'workflow';
  return baseName(graph.workspace.root);
}

function baseName(root: string): string {
  const parts = String(root || '').split(/[\\/]+/).filter((p) => !!p);
  return parts.length ? parts[parts.length - 1] : 'workspace';
}

function slug(value: string): string {
  return String(value)
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 48);
}

/* ── delivery ───────────────────────────────────────────────────────────── */

/**
 * The one frame the viewer hands its host, in BOTH field spellings.
 *
 * See the INTEROP NOTE on `UiToHost.exportFile`: `name === suggestedName` and
 * `base64 === data`, always, so either validator accepts the frame and either
 * reader decodes the same bytes.
 */
function exportFileMessage(kind: 'svg' | 'png', name: string, base64: string, region: ExportRegionKind): UiToHost {
  return {
    v: 1,
    type: 'exportFile',
    kind,
    name,
    base64,
    data: base64,
    suggestedName: name,
    scope: hostRegionWord(region),
  };
}

/**
 * What the viewer says once the host has answered an export (CRIT-5). Success
 * is announced only: the host's own notification is the visible message, and
 * nothing claims a file before the host reports one.
 */
function exportAnswer(host: ExportHost, done: (name: string) => string, suggested: string) {
  return (answer: ActionResult) => {
    if (answer.outcome === 'done') {
      host.announce(done(answer.name || suggested));
      return;
    }
    if (answer.outcome === 'cancelled') {
      host.announce('Export cancelled.');
      return;
    }
    const said = 'Export failed: ' + (answer.message || 'the host did not say why');
    host.toast(said);
    host.announce(said);
  };
}

export function saveSvg(host: ExportHost, result: ExportSvgResult, name: string): void {
  const base64 = utf8ToBase64(result.svg);
  if (!base64) {
    host.toast('This browser could not encode the SVG.');
    return;
  }
  const cards = result.nodeIds.length;
  const connections = result.edgeIds.length;
  host.announce('Saving SVG…');
  host.request(
    exportFileMessage('svg', name, base64, result.regionKind),
    exportAnswer(host, (saved) => 'Exported ' + cards + ' cards and ' + connections + ' connections as ' + saved + '.', name),
  );
}

export async function savePng(host: ExportHost, result: ExportSvgResult, name: string): Promise<boolean> {
  const raster = await safeRasterize(result);
  if (!raster) {
    host.toast('Could not draw the PNG here — save the SVG instead.');
    host.announce('PNG export is not available in this host.');
    return false;
  }
  // The size actually drawn, which `rasterize` may have scaled down (RENDER-3).
  const size = raster.width + '×' + raster.height;
  host.announce('Saving PNG…');
  host.request(
    exportFileMessage('png', name, raster.base64, result.regionKind),
    exportAnswer(host, (saved) => 'Exported ' + size + ' PNG as ' + saved + '.', name),
  );
  return true;
}

export async function copySvgText(host: ExportHost, result: ExportSvgResult): Promise<boolean> {
  const ok = await writeText(result.svg);
  if (ok) {
    const said = 'SVG copied — ' + result.nodeIds.length + ' cards, ' + result.edgeIds.length + ' connections.';
    host.toast(said);
    host.announce(said);
    return true;
  }
  // The host's clipboard, which answers with an `actionResult` (VIEWUI-10):
  // success is claimed only once the host has written the text.
  const cards = result.nodeIds.length;
  const connections = result.edgeIds.length;
  host.request({ v: 1, type: 'copy', text: result.svg }, (answer) => {
    if (answer.outcome === 'done') {
      const said = 'SVG copied — ' + cards + ' cards, ' + connections + ' connections.';
      host.toast(said);
      host.announce(said);
    } else {
      host.announce('The SVG could not be copied.');
    }
  });
  return false;
}

export async function copyPngImage(host: ExportHost, result: ExportSvgResult): Promise<boolean> {
  const raster = await safeRasterize(result);
  if (raster && (await writeImage(raster.base64))) {
    const said = 'PNG copied at ' + raster.width + '×' + raster.height + '.';
    host.toast(said);
    host.announce(said);
    return true;
  }
  host.toast('The clipboard would not take an image — copying the SVG instead.');
  await copySvgText(host, result);
  return false;
}

export function printDiagram(host: ExportHost): void {
  host.announce('Opening the print dialog. The toolbar, rail and minimap are not printed.');
  host.print();
}

async function safeRasterize(result: ExportSvgResult) {
  try {
    return await rasterize(result.svg, result.width, result.height, PNG_SCALE);
  } catch (_e) {
    return null;
  }
}

async function writeText(value: string): Promise<boolean> {
  const nav: any = typeof navigator !== 'undefined' ? navigator : null;
  if (!nav || !nav.clipboard || typeof nav.clipboard.writeText !== 'function') return false;
  try {
    await nav.clipboard.writeText(value);
    return true;
  } catch (_e) {
    return false;
  }
}

async function writeImage(base64: string): Promise<boolean> {
  const g: any = typeof globalThis === 'undefined' ? {} : globalThis;
  const nav: any = typeof navigator !== 'undefined' ? navigator : null;
  if (!nav || !nav.clipboard || typeof nav.clipboard.write !== 'function') return false;
  if (typeof g.ClipboardItem !== 'function' || typeof g.Blob !== 'function') return false;
  try {
    const blob = new g.Blob([base64ToBytes(base64)], { type: MIME.png });
    await nav.clipboard.write([new g.ClipboardItem({ [MIME.png]: blob })]);
    return true;
  } catch (_e) {
    return false;
  }
}
