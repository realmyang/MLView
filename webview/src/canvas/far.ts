/**
 * The canvas's part in a far connection of the review walk, one whose two end
 * cards cannot both be shown. The rules are pure functions in `far.ts`; this object applies them
 * to the viewport: which end the view keeps, the look at the other end and back, and the caps on
 * the lit line (`render/farcap.ts`).
 *
 * The least pan to the two cards' union, the walk's move for a connection that fits, leaves the
 * reader at its top-left corner when it does not fit (`revealRect`), and that corner can show
 * neither card whole and none of the line.
 *
 * `CanvasView` owns the viewport and decides what a resize keeps; it asks this object which end
 * of a far connection that is (`kept`), and hands a walk step onto a connection here first (`step`).
 */

import { capPoint, farEnd, farWay, fitsCanvas, inView, isFar, isUncertain, leadBox, leadChoices, lineInView, meetBox, portBox, portStretch, unionOf } from '../far.js';
import type { DrawnLine, End, FarEnd, FarEnds, XY } from '../far.js';
import { FarCaps } from '../render/farcap.js';
import type { CapState } from '../render/farcap.js';
import { clearOfAll, FRAME_MIN_ZOOM, LOD_FULL_ZOOM, READABLE_MIN_ZOOM, READABLE_ZOOM } from '../render/canvas.js';
import type { Rect, ViewportController } from '../render/canvas.js';
import { NODE_W } from '../layout/constants.js';
import type { GraphIndex } from '../layout/model.js';
import type { LayoutBox, LayoutFrame } from '../layout/layout.js';
import type { RoutedEdge } from '../layout/routing.js';
import type { Viewport } from '../types.js';

/**
 * Everything a far connection reaches on the canvas. The scene is read through functions because
 * `render()` replaces the frame, the routes and the maps wholesale; the viewport is the same
 * object for the life of the view.
 */
export interface FarContext {
  readonly viewport: ViewportController;
  index(): GraphIndex | null;
  frame(): LayoutFrame | null;
  routes(): RoutedEdge[];
  collapsed(): Set<string>;
  edgeEls(): Map<string, SVGElement>;
  /** A connection's two drawn end cards, source first (`CanvasView.endBoxes`). */
  endBoxes(id: string): [LayoutBox, LayoutBox] | null;
  /** The drawn route `id` is in its own colour now, not yet or no longer the accent (`FlowController.inChargeColour`). */
  inChargeColour(id: string): boolean;
  /** READABLE_ZOOM, or less when the box would not fit the canvas at it. */
  readableZoomFor(box: { w: number; h: number }): number;
  /** The zoom on screen while the viewer chose it, else null (`CanvasView.framedZoom`). */
  viewerZoom(): number | null;
  /** A move that started at zoom `before` is done: whose zoom it is now (`CanvasView.noteFramedZoom`). */
  noteFramedZoom(before: number): void;
  /** A picture was put back whose zoom the viewer had chosen (`CanvasView.restoreFramedZoom`). */
  restoreFramedZoom(zoom: number): void;
  /** A cap was clicked (`ev`): look at that end of the walk's connection. */
  onCap(end: End, ev: MouseEvent): void;
  /** The pointer is on a cap, or left it. */
  onCue(on: boolean): void;
}

/**
 * The picture the reader left at the source for a look at the far end: the viewport, whether its
 * zoom was the viewer's own choice, and how much of the line was kept in view with the card. It
 * shows the source on the canvas it was left on (`area`, with the phase index over `covered`); on
 * another it need not. `cut`: it did not show the source there either, only some of its card (the
 * reader had dragged the card partly off the canvas).
 */
interface Left {
  vp: Viewport;
  framed: boolean;
  lead: number;
  inSight: boolean;
  area: { w: number; h: number };
  covered: Rect | null;
  cut: boolean;
}

/** The far connection the view holds an end of. */
interface Held {
  id: string;
  /** The end kept in view: the source after a step, the target after a look at the far end. */
  keep: End;
  /** How much of the line is kept in view with that card, in screen pixels (`leadBox`); 0 for none. */
  lead: number;
  /** That lead was counted in sight (a stretch behind another card not counted), not as the line runs. */
  inSight: boolean;
  /** What the way back from a look restores, exactly; null when there is nothing to go back to. */
  back: Left | null;
  /**
   * Where the view was left when the canvas could not show the kept end by the rule (a canvas
   * shorter than a card, or than the stretch of line that stands for one): until the view moves,
   * that end counts as in view, so the walk bar's line names the other end and key o goes there.
   * Null when the kept end is in view by the rule.
   */
  at: Viewport | null;
}

const sameView = (a: Viewport, b: Viewport): boolean => a.x === b.x && a.y === b.y && a.zoom === b.zoom;
/** Two rectangles in canvas pixels are one, half a pixel of rounding allowed; so are two nulls. */
const sameRect = (a: Rect | null, b: Rect | null): boolean =>
  a === b || (!!a && !!b && Math.abs(a.x - b.x) < 0.5 && Math.abs(a.y - b.y) < 0.5 && Math.abs(a.w - b.w) < 0.5 && Math.abs(a.h - b.h) < 0.5);

/**
 * The start of an open group's header, as wide as a card: its chevron, its kind and the first of
 * its name. Null for a card without a header (a step, a collapsed group).
 */
function headOf(card: LayoutBox): Rect | null {
  return card.headerH > 0 ? { x: card.x, y: card.y, w: Math.min(card.w, NODE_W), h: card.headerH } : null;
}

export class FarView {
  private ctx: FarContext;
  private caps: FarCaps;
  private held: Held | null = null;

  constructor(ctx: FarContext) {
    this.ctx = ctx;
    this.caps = new FarCaps(
      (end, ev) => ctx.onCap(end, ev),
      (on) => ctx.onCue(on),
    );
  }

  /** The caps' layer: over the world, under the phase index, the overview and the toasts. */
  get root(): HTMLElement {
    return this.caps.root;
  }

  /** Forget the far connection (the walk stepped on or ended, or the selection moved off its claim). */
  clear(): void {
    this.held = null;
    this.caps.set([]);
  }

  /** Every box may have moved (a relayout), so the picture saved for the way back means nothing now. */
  relaid(): void {
    if (this.held) this.held.back = null;
  }

  /* ── the walk's step ─────────────────────────────────────────────────────────────────── */

  /**
   * A walk step onto connection `id`. False, with nothing moved, when its two cards fit the canvas
   * at the zoom the step would be at: the walk frames them as it frames any connection
   * (`CanvasView.revealTarget`).
   * Otherwise:
   *
   * - a connection whose line is drawn dashed or dotted (`uncertain`) and whose two cards fit at
   *   FRAME_MIN_ZOOM or more is shown with both cards, as Reveal in Diagram frames a connection
   *   (`frameClear`); the line between them can still leave the canvas on its way;
   * - every other connection keeps its SOURCE card in view, as a step onto that card would
   *   (`keep`), with its line lit. The App then draws the cap and the walk bar's line (`ends`).
   */
  step(id: string): boolean {
    const index = this.ctx.index();
    const ends = this.ctx.endBoxes(id);
    if (!index || !ends) return false;
    const viewport = this.ctx.viewport;
    const union = unionOf(ends[0], ends[1]);
    const zoom = viewport.vp.zoom;
    const viewerChose = zoom === this.ctx.viewerZoom() && zoom >= LOD_FULL_ZOOM && zoom < READABLE_MIN_ZOOM;
    const at = viewerChose || zoom < LOD_FULL_ZOOM ? Math.max(zoom, this.ctx.readableZoomFor(union)) : zoom;
    if (viewport.fitsAt(union, at, 0)) return false;
    if (this.uncertain(id) && viewport.fitsAt(union, FRAME_MIN_ZOOM) && viewport.frameClear(union, ends, { from: Math.max(zoom, READABLE_ZOOM), floor: FRAME_MIN_ZOOM })) return true;
    this.keep(id, 'source');
    return true;
  }

  /**
   * After the walk's own frame of connection `id` (`CanvasView.revealTarget`). A union that fits
   * the canvas, but that no pan and no zoom down to READABLE_MIN_ZOOM clears of the phase index,
   * is left with an end card under the index or off the canvas. Such a connection is far too: its
   * source card is kept.
   */
  afterReveal(id: string): void {
    const ends = this.ends(id);
    if (ends && isFar(ends)) this.keep(id, 'source');
  }

  /**
   * Bring one end card of a far connection into view as a walk step onto that card would: back to
   * reading size from a zoom the viewer chose or from below full detail, then the least pan that
   * shows the card, and the start of its line (`leadBox`), whole and clear of the phase index.
   * That end is then the one a resize keeps. Of an open group too large for the canvas the place
   * its line leaves it is shown, with the start of the group's header when both fit the canvas.
   * Where the canvas can show the end no better than this, it counts as shown (`latch`).
   */
  private keep(id: string, end: End): void {
    this.reveal(id, end);
    this.latch();
  }

  /** The moves of `keep`. */
  private reveal(id: string, end: End): void {
    const ends = this.ctx.endBoxes(id);
    if (!ends) return;
    const viewport = this.ctx.viewport;
    const card = ends[end === 'source' ? 0 : 1];
    const points = this.pointsOf(id);
    // A card too large for the canvas at reading size (an open group): the place its line leaves it.
    const port = portBox(points, end, card, viewport.vp.zoom, viewport.visibleArea());
    const box = port || card;
    const zoom = viewport.vp.zoom;
    if (zoom === this.ctx.viewerZoom() && zoom >= LOD_FULL_ZOOM && zoom < READABLE_MIN_ZOOM) {
      const next = Math.max(zoom, this.ctx.readableZoomFor(box));
      if (next > zoom) {
        const { w, h } = viewport.visibleArea();
        viewport.zoomAt(next / zoom, w / 2, h / 2);
      }
    }
    if (viewport.vp.zoom < LOD_FULL_ZOOM) viewport.centerOn(box, Math.max(viewport.vp.zoom, this.ctx.readableZoomFor(box)));
    if (port) {
      this.held = { id, keep: end, lead: 0, inSight: false, back: null, at: null };
      this.showPort(card, portBox(points, end, card, viewport.vp.zoom, viewport.visibleArea()) || port);
      return;
    }
    const lead = this.showLead(id, end, card);
    const meet = lead.px ? null : this.meetOf(id, end, card);
    if (meet) this.showPort(card, meet);
    // The card itself comes first: a lead the phase index leaves no room for gives way to it.
    else if (!this.inView(card)) viewport.revealRect(card);
    this.held = { id, keep: end, lead: lead.px, inSight: lead.inSight, back: null, at: null };
  }

  /**
   * For the far card of a line drawn dashed or dotted, when that card is an open group: the place
   * the line meets it (`meetBox`). It is what the walk shows of such a group that leaves no room
   * beside it for the line, as of a group larger than the canvas, so that the reader sees the
   * line's dashes at its far end; the view then counts as at that end (`latch`). Else null.
   */
  private meetOf(id: string, end: End, card: LayoutBox): Rect | null {
    if (end !== 'target' || !this.uncertain(id) || !headOf(card)) return null;
    return meetBox(this.pointsOf(id), end, card, this.ctx.viewport.vp.zoom);
  }

  /**
   * Show `at`, the place a line meets a card that is not shown whole. The header of a group names
   * it: its start is in view with that place when the canvas has room for both.
   */
  private showPort(card: LayoutBox, at: Rect): void {
    const viewport = this.ctx.viewport;
    const head = headOf(card);
    const both = head ? unionOf(head, at) : null;
    if (head && both && viewport.fitsAt(both, viewport.vp.zoom, 32)) {
      const from = { ...viewport.vp };
      if (!(this.inView(head) && this.inView(at))) viewport.revealRect(both);
      if (this.inView(head) && this.inView(at)) return;
      viewport.set(from);
    }
    if (!viewport.isVisible(at)) viewport.revealRect(at, 32);
  }

  /**
   * The least pan that shows `card`, an end card of connection `id`, together with the stretch of
   * its line beside it: the longest lead that fits the canvas with the card (`leadChoices`).
   * Returns the lead used; `px` is 0, and nothing has moved, when none fits.
   */
  private showLead(id: string, end: End, card: LayoutBox): { px: number; inSight: boolean } {
    const viewport = this.ctx.viewport;
    const points = this.pointsOf(id);
    for (const lead of leadChoices(this.uncertain(id), viewport.visibleArea())) {
      const shown = leadBox(points, end, card, lead.px, viewport.vp.zoom, { behind: lead.inSight ? this.cardBoxes(card.id) : undefined });
      if (!viewport.fitsAt(shown, viewport.vp.zoom, 32)) continue;
      if (!viewport.isVisible(shown)) viewport.revealRect(shown);
      return lead;
    }
    return { px: 0, inSight: false };
  }

  /* ── the look at the other end, and back ─────────────────────────────────────────────── */

  /**
   * The reader asked for one end of the walk's connection (the walk bar's line, key o, a click on
   * a cap, an arrow key towards an end that is out of view). The connection stays selected and lit
   * and the walk stays on it; only the view moves. To the far card: centred, at reading size when
   * the diagram is below full detail (`LOD_FULL_ZOOM`), then moved the least distance that shows
   * the end of a dashed or dotted line with it (of an open group with no room for that, the place
   * the line meets it); the picture the reader left is remembered. Back to the source:
   * that picture again, exactly, when there is one; else the least pan that shows it. A picture
   * left on a canvas of another size, or with the phase index elsewhere, may not show the
   * source card, and one the reader left with the card dragged partly off the canvas never did:
   * the picture is put back and the card then shown as a step onto it would, which at reading
   * size is the least pan from that picture.
   *
   * Two cards that can be shown together (`FarEnds.together`) are, whichever end was asked for and
   * with no picture to go back to: the connection is not a far one, a pan or a zoom took a card of
   * it out of view, and centring that card would cut the other one off beside it. The view then
   * holds no end.
   */
  look(id: string, end: End): boolean {
    const ends = this.ctx.endBoxes(id);
    if (!ends) return false;
    const viewport = this.ctx.viewport;
    const held = this.held && this.held.id === id ? this.held : null;
    if (end === 'source' && held && held.back) {
      const back = held.back;
      this.restore(back);
      this.held = { id, keep: 'source', lead: back.lead, inSight: back.inSight, back: null, at: null };
      const area = viewport.visibleArea();
      const changed = Math.abs(area.w - back.area.w) >= 0.5 || Math.abs(area.h - back.area.h) >= 0.5 || !sameRect(viewport.covered(), back.covered);
      const now = changed || back.cut ? this.ends(id) : null;
      if (now && !now.source.inView) {
        this.reveal(id, 'source');
        this.ctx.noteFramedZoom(back.vp.zoom);
      }
      this.latch();
      return true;
    }
    if (this.showBoth(id, ends)) {
      this.held = null;
      return true;
    }
    const before = viewport.vp.zoom;
    if (end === 'source') this.keep(id, 'source');
    else {
      const points = this.pointsOf(id);
      const area = viewport.visibleArea();
      // The source as the walk left it (`latch`) is a picture to come back to as well.
      const sourceSeen = (!!held && held.keep === 'source' && this.latched()) || inView(portStretch(points, 'source', ends[0], before, area) || ends[0], viewport.vp, area, viewport.covered());
      const here = (cut: boolean): Left => ({ vp: { ...viewport.vp }, framed: this.ctx.viewerZoom() === before, lead: held && held.keep === 'source' ? held.lead : 0, inSight: !!held && held.keep === 'source' && held.inSight, area: { w: area.w, h: area.h }, covered: viewport.covered(), cut });
      const shown = this.ends(id);
      // The picture in front of the reader is the one to come back to while it shows the source;
      // else the one an earlier look left there; else this one again while some of the source
      // card is on the canvas (a drag cut it off): the way back then brings the card into view.
      const back: Left | null = sourceSeen ? here(false) : held && held.back ? held.back : shown && shown.source.onCanvas ? here(true) : null;
      const box = portBox(points, 'target', ends[1], before, area) || ends[1];
      if (before < LOD_FULL_ZOOM) viewport.centerOn(box, Math.max(before, this.ctx.readableZoomFor(box)));
      else viewport.centerOn(box);
      // A dashed or dotted line is what shows that its connection is uncertain: the far card of
      // one comes with the end of that line, as the step shows its source with the start of it.
      const lead = box === ends[1] && this.uncertain(id) ? this.showLead(id, 'target', ends[1]) : { px: 0, inSight: false };
      if (lead.px && !this.inView(ends[1])) viewport.revealRect(ends[1]);
      const meet = box === ends[1] && !lead.px ? this.meetOf(id, 'target', ends[1]) : null;
      if (meet) this.showPort(ends[1], meet);
      this.held = { id, keep: 'target', lead: lead.px, inSight: lead.inSight, back, at: null };
      this.latch();
    }
    this.ctx.noteFramedZoom(before);
    return true;
  }

  /**
   * The least pan that shows both cards of connection `id` whole and clear of the phase index at
   * the zoom on screen, in canvas pixels (`clearOfAll`); null when no pan does, and when an end is
   * too large for the canvas (it is shown by the place its line meets it, `portStretch`).
   */
  private bothShift(id: string, boxes: [LayoutBox, LayoutBox]): { dx: number; dy: number } | null {
    const viewport = this.ctx.viewport;
    const vp = viewport.vp;
    const area = viewport.visibleArea();
    const points = this.pointsOf(id);
    if (portStretch(points, 'source', boxes[0], vp.zoom, area) || portStretch(points, 'target', boxes[1], vp.zoom, area)) return null;
    const onScreen = (box: Rect): Rect => ({ x: box.x * vp.zoom + vp.x, y: box.y * vp.zoom + vp.y, w: box.w * vp.zoom, h: box.h * vp.zoom });
    return clearOfAll([onScreen(boxes[0]), onScreen(boxes[1])], viewport.covered(), area.w, area.h);
  }

  /**
   * Show both cards of connection `id`, keeping the zoom: the least pan that brings the rectangle
   * around them into view, as a walk step shows a connection (`CanvasView.revealTarget`), and
   * where that leaves a card under the phase index, the least pan that clears both cards of it
   * (`bothShift`). False, with the view where it was, when no pan shows both.
   */
  private showBoth(id: string, boxes: [LayoutBox, LayoutBox]): boolean {
    if (!this.bothShift(id, boxes)) return false;
    const viewport = this.ctx.viewport;
    const from = { ...viewport.vp };
    const shown = (): boolean => this.inView(boxes[0]) && this.inView(boxes[1]);
    viewport.revealRect(unionOf(boxes[0], boxes[1]));
    if (shown()) return true;
    if (!sameView(viewport.vp, from)) viewport.set(from);
    // Twice: the index names the phase in view, so a pan can widen it over a card it had cleared.
    for (let pass = 0; pass < 2; pass++) {
      const shift = this.bothShift(id, boxes);
      if (!shift) break;
      viewport.panBy(shift.dx, shift.dy);
      if (shown()) return true;
    }
    if (!sameView(viewport.vp, from)) viewport.set(from);
    return false;
  }

  /**
   * The walk is about to leave a connection the reader was looking at the far end of: the next
   * step starts from the picture they left at the source, so a look never moves the walk's path.
   */
  endLook(): void {
    const held = this.held;
    this.held = null;
    if (held && held.keep === 'target' && held.back) this.restore(held.back);
  }

  /**
   * The view has just been moved to the end it holds. When the canvas cannot show that end by the
   * rule, this is as well as it can be shown: it counts as in view until the view moves (`Held.at`).
   */
  latch(): void {
    const held = this.held;
    if (!held) return;
    held.at = null;
    const ends = this.ends(held.id);
    if (ends && !ends[held.keep].inView) held.at = { ...this.ctx.viewport.vp };
  }

  /**
   * The canvas changed size while the view stood where `latch` left it. One that `grew` may have
   * room for the end it could not show, so that end is revealed again as a step shows it; the way
   * back from a look is kept. Either way the view is at that end, as before the resize.
   */
  relatch(grew: boolean): void {
    const held = this.held;
    if (!held) return;
    if (grew) {
      const back = held.back;
      const before = this.ctx.viewport.vp.zoom;
      this.reveal(held.id, held.keep);
      if (this.held) this.held.back = back;
      this.ctx.noteFramedZoom(before);
    }
    this.latch();
  }

  /** The view stands where `latch` left it. */
  latched(): boolean {
    return !!this.held && !!this.held.at && sameView(this.held.at, this.ctx.viewport.vp);
  }

  /** Put a picture back as it was left, with the zoom whose it was (`CanvasView.framedZoom`). */
  private restore(left: Left): void {
    this.ctx.viewport.set(left.vp);
    if (left.framed) this.ctx.restoreFramedZoom(left.vp.zoom);
  }

  /* ── what the canvas shows now ───────────────────────────────────────────────────────── */

  /** Both ends of connection `id` as the canvas shows them now, or null when it is not drawn. */
  ends(id: string): FarEnds | null {
    const index = this.ctx.index();
    const edge = index ? index.edgeById.get(id) : undefined;
    const boxes = this.ctx.endBoxes(id);
    if (!edge || !boxes) return null;
    const viewport = this.ctx.viewport;
    const area = viewport.visibleArea();
    const covered = viewport.covered();
    const points = this.pointsOf(id);
    const held = this.held && this.held.id === id ? this.held : null;
    const here = held && held.at && sameView(held.at, viewport.vp) ? held.keep : null;
    const source = farEnd('source', edge.source, boxes[0], points, viewport.vp, area, covered);
    const target = farEnd('target', edge.target, boxes[1], points, viewport.vp, area, covered);
    // What "in view" is judged by: the card, or of one too large for the canvas the place its line meets it.
    const shown = (end: End, box: LayoutBox): Rect => portStretch(points, end, box, viewport.vp.zoom, area) || box;
    // A card the canvas's edge cuts, or that the phase index covers part of, with the other card
    // on the canvas too: the reader sees it beside that card, so that is where its way is taken
    // from. A card wholly under the index is not seen, and lies where any card off screen does.
    const beside = (end: FarEnd, box: LayoutBox, other: FarEnd, otherBox: LayoutBox): FarEnd =>
      !end.inView && end.seen && !end.byLine && other.onCanvas && !other.byLine ? { ...end, way: farWay(box, viewport.vp, area, otherBox) } : end;
    return {
      source: here === 'source' ? { ...source, inView: true } : beside(source, boxes[0], target, boxes[1]),
      target: here === 'target' ? { ...target, inView: true } : beside(target, boxes[1], source, boxes[0]),
      keep: held ? held.keep : null,
      fits: fitsCanvas(unionOf(shown('source', boxes[0]), shown('target', boxes[1])), area, viewport.vp.zoom, 0),
      together: !!this.bothShift(id, boxes),
      lineCut: !lineInView(points, viewport.vp, area, covered),
    };
  }

  /** Whole on the canvas and clear of the phase index (`inView` in `far.ts`). */
  inView(box: Rect): boolean {
    const viewport = this.ctx.viewport;
    return inView(box, viewport.vp, viewport.visibleArea(), viewport.covered());
  }

  /**
   * What a resize keeps in view of connection `id` while the view holds one of its ends: `card`,
   * that end's card (for an open group too large for the canvas, the place its line leaves it),
   * and `box`, the card with the start of its line (that place with the group's header) when that
   * was in view before the resize (`was`), else the card again. Null for a connection the view
   * holds no end of.
   */
  kept(id: string, was: (box: Rect) => boolean): { card: Rect; box: Rect } | null {
    const held = this.held && this.held.id === id ? this.held : null;
    const ends = held ? this.ctx.endBoxes(id) : null;
    if (!held || !ends) return null;
    const viewport = this.ctx.viewport;
    const own = ends[held.keep === 'source' ? 0 : 1];
    const points = this.pointsOf(id);
    const card = portBox(points, held.keep, own, viewport.vp.zoom, viewport.visibleArea()) || own;
    const lead = held.lead > 0 ? leadBox(points, held.keep, own, held.lead, viewport.vp.zoom, { behind: held.inSight ? this.cardBoxes(own.id) : undefined }) : null;
    const head = card === own ? null : headOf(own);
    const more = head ? unionOf(head, card) : lead;
    return { card, box: more && was(more) ? more : card };
  }

  /* ── the caps ────────────────────────────────────────────────────────────────────────── */

  /**
   * Draw the caps of connection `id` towards these ends (none: remove them). A cap goes where the
   * lit line runs out of sight on its way to that end (`capPoint`); an end whose stretch of line
   * is in sight, or whose line is nowhere on the canvas, gets none. Returns the ends capped.
   */
  setCaps(id: string | null, wanted: ReadonlyArray<{ end: End; title: string }>): End[] {
    const index = this.ctx.index();
    const route = id ? this.routeOf(id) : null;
    if (!id || !route || !index || !wanted.length) {
      this.caps.set([]);
      return [];
    }
    const viewport = this.ctx.viewport;
    const vp = viewport.vp;
    const area = viewport.visibleArea();
    const covered = viewport.covered();
    // The cards on the canvas hide the stretch of line behind them (an open group does not).
    const cards: Rect[] = [];
    for (const box of this.cardBoxes()) {
      const r = { x: box.x * vp.zoom + vp.x, y: box.y * vp.zoom + vp.y, w: box.w * vp.zoom, h: box.h * vp.zoom };
      if (r.x < area.w && r.x + r.w > 0 && r.y < area.h && r.y + r.h > 0) cards.push(r);
    }
    const drawn = this.drawn(id);
    const states: CapState[] = [];
    for (const want of wanted) {
      const at = capPoint(route.points, vp, area, covered, want.end, cards);
      if (!at) continue;
      states.push({ at, end: want.end, basis: drawn.basis, tone: drawn.tone, severity: drawn.severity, lit: drawn.lit, title: want.title });
    }
    this.caps.set(states);
    return states.map((s) => s.end);
  }

  /** The walk bar's line has the pointer or the focus: the caps answer (a static fill). */
  cue(on: boolean): void {
    this.caps.cue(on);
  }

  /**
   * How the line of `id` is drawn, which its cap and the walk bar's line copy (`DrawnLine`), read
   * from the line itself: its phase tone or its finding's severity, whether it is `lit` in them
   * now, and its basis. A selected line is the accent first (a finding's, its severity): for the
   * two passes of its charge under full motion, and for as long as the flow layer is off. The
   * basis is the line's, so the cap of a line that is drawn dashed or dotted is dashed or dotted
   * whichever of the connections it carries the walk is on.
   */
  drawn(id: string): DrawnLine {
    const route = this.routeOf(id);
    const line = route ? this.ctx.edgeEls().get(route.id) : undefined;
    return {
      tone: line ? line.getAttribute('data-phase-tone') : null,
      severity: line ? line.getAttribute('data-sev') : null,
      lit: !!route && this.ctx.inChargeColour(route.id),
      basis: line ? line.getAttribute('data-basis') : null,
    };
  }

  /* ── the scene ───────────────────────────────────────────────────────────────────────── */

  /**
   * The line of connection `id` is drawn dashed or dotted: the connection is inferred or
   * unresolved, or shares its line with one that is (`RoutedEdge.notObserved`). The walk gives
   * such a line the room its stroke needs whichever of its connections it is on.
   */
  private uncertain(id: string): boolean {
    const index = this.ctx.index();
    const edge = index ? index.edgeById.get(id) : undefined;
    const route = this.routeOf(id);
    return (!!edge && isUncertain(edge.basis)) || !!(route && route.notObserved);
  }

  /** The drawn route that carries connection `id` (its own, or the merged cable it is part of). */
  private routeOf(id: string): RoutedEdge | null {
    const routes = this.ctx.routes();
    return routes.find((r) => r.id === id) || routes.find((r) => r.ids.indexOf(id) >= 0) || null;
  }

  /** That route's polyline in world coordinates, source first, or null when it is not drawn. */
  private pointsOf(id: string): readonly XY[] | null {
    const route = this.routeOf(id);
    return route ? route.points : null;
  }

  /** The cards a line can run behind, in world coordinates: every drawn box but open groups and `except`. */
  private cardBoxes(except?: string): LayoutBox[] {
    const out: LayoutBox[] = [];
    const index = this.ctx.index();
    const frame = this.ctx.frame();
    if (!frame || !index) return out;
    const collapsed = this.ctx.collapsed();
    for (const box of frame.boxes.values()) {
      if (box.id === except) continue;
      if (index.isGroup(box.id) && !collapsed.has(box.id)) continue;
      out.push(box);
    }
    return out;
  }
}
