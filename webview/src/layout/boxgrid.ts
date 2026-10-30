/**
 * The boxes of one layout on a uniform grid.
 *
 * The router asks of every segment it proposes whether it passes through a
 * card, and the separation pass (`layout/separate.ts`) asks through how many for
 * every offset it tries. Both read the cells a segment covers here, not every
 * box: a segment that passes through a box's interior shares a point with the
 * box's rectangle, hence a cell, so the cells hold every box `segHitsBox` can
 * accept.
 */

// Module constants, not lookups of `Math` on the global object (`layout/separate.ts`).
const { floor, max, min } = Math;

/** What the grid reads of a box; a `LayoutBox` is one. */
export interface GridBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Axis-aligned segment, by its bounds, against a box interior (1 px inset, so faces are free). */
export function segHitsBox(x0: number, x1: number, y0: number, y1: number, box: GridBox): boolean {
  const m = 1;
  return x1 > box.x + m && x0 < box.x + box.w - m && y1 > box.y + m && y0 < box.y + box.h - m;
}

/** Grid cell size, in px. */
const CELL = 128;
/** The most cells a grid takes. A drawing that needs more doubles the cell size until it fits. */
const MAX_CELLS = 65536;
/**
 * The most entries a grid takes, a box having one in every cell it lies in;
 * past it the cell size doubles too, unless the grid holds no more than four
 * entries for each box. Cells alone do not bound a grid: a group lies in every
 * cell its frame covers, so a thousand groups nested one inside the next are
 * each written to nearly every cell, and a segment then reads most of them
 * once for each cell it passes. Without this limit the entries of such a
 * drawing grow with the number of groups times the cells each one covers.
 */
const MAX_ENTRIES = 65536;

export class BoxGrid {
  /** After `hitBy`: the positions in `boxes` of the boxes it found, in no particular order. */
  readonly found: Int32Array;
  /**
   * The entries `hitBy` has read, all its calls so far together: a box once for
   * each cell it was read from, whether the segment hits it or not, and once if
   * it is `loose`. A segment under many groups nested one inside the next reads
   * every one of them, so this, and not the number of segments, is what a
   * reader of the grid pays for; the separation pass bounds its own share of it
   * (`cards` in `layout/separate.ts`).
   */
  read = 0;
  private size = CELL;
  /** The grid's first column and row, in cells from the origin. */
  private gx0 = 0;
  private gy0 = 0;
  private cols = 0;
  private rows = 0;
  /** Cell `gx * rows + gy` holds `items[start[at]]` up to `items[start[at + 1]]`, positions in `boxes`. */
  private start: Int32Array;
  private items: Int32Array;
  /**
   * Boxes that are no finite rectangle of non-negative size, which the cells
   * cannot hold: read for every segment. `layoutGraph` cannot make one of
   * negative size: a card's size is `cardSize` and a group's at least
   * `GROUP_MIN_W` by `GROUP_MIN_H`.
   */
  private loose: number[] = [];
  /** Per box, the last `hitBy` that read it, so a box lying in several cells is read once. */
  private mark: Float64Array;
  private stamp = 0;

  constructor(private readonly boxes: GridBox[]) {
    this.found = new Int32Array(boxes.length);
    this.mark = new Float64Array(boxes.length);
    const placed: number[] = [];
    boxes.forEach((box, at) => {
      if (box.w >= 0 && box.h >= 0 && Number.isFinite(box.x + box.w) && Number.isFinite(box.y + box.h)) placed.push(at);
      else this.loose.push(at);
    });
    let last = 0;
    while (placed.length) {
      let ax = Infinity;
      let ay = Infinity;
      let bx = -Infinity;
      let by = -Infinity;
      let entries = 0;
      for (const at of placed) {
        const box = boxes[at];
        const gx0 = floor(box.x / this.size);
        const gy0 = floor(box.y / this.size);
        const gx1 = floor((box.x + box.w) / this.size);
        const gy1 = floor((box.y + box.h) / this.size);
        ax = min(ax, gx0);
        ay = min(ay, gy0);
        bx = max(bx, gx1);
        by = max(by, gy1);
        entries += (gx1 - gx0 + 1) * (gy1 - gy0 + 1);
      }
      this.gx0 = ax;
      this.gy0 = ay;
      this.cols = bx - ax + 1;
      this.rows = by - ay + 1;
      last = this.cols * this.rows;
      // A cell larger than every box leaves a box in four cells at most, so this ends.
      if (last <= MAX_CELLS && entries <= max(MAX_ENTRIES, 4 * placed.length)) break;
      this.size *= 2;
    }
    // Two passes: count each cell's boxes, then write them in, in `boxes` order.
    this.start = new Int32Array(last + 1);
    for (const at of placed) this.eachCell(boxes[at], (cell) => this.start[cell + 1]++);
    for (let cell = 0; cell < last; cell++) this.start[cell + 1] += this.start[cell];
    this.items = new Int32Array(this.start[last]);
    const next = this.start.slice(0, last);
    for (const at of placed) this.eachCell(boxes[at], (cell) => (this.items[next[cell]++] = at));
  }

  private eachCell(box: GridBox, visit: (cell: number) => void): void {
    const gx1 = floor((box.x + box.w) / this.size) - this.gx0;
    const gy1 = floor((box.y + box.h) / this.size) - this.gy0;
    for (let gx = floor(box.x / this.size) - this.gx0; gx <= gx1; gx++) {
      for (let gy = floor(box.y / this.size) - this.gy0; gy <= gy1; gy++) visit(gx * this.rows + gy);
    }
  }

  /**
   * The boxes whose interior the segment with these bounds passes through
   * (`segHitsBox`), each once: their number, and their positions in `found`.
   */
  hitBy(x0: number, x1: number, y0: number, y1: number): number {
    const { boxes, found, mark, start, items, rows, size } = this;
    const stamp = ++this.stamp;
    let n = 0;
    let read = this.loose.length;
    for (const at of this.loose) if (segHitsBox(x0, x1, y0, y1, boxes[at])) found[n++] = at;
    // Cells outside the grid hold nothing, so the walk stops at its edges.
    const gx1 = min(floor(x1 / size) - this.gx0, this.cols - 1);
    const gy0 = max(floor(y0 / size) - this.gy0, 0);
    const gy1 = min(floor(y1 / size) - this.gy0, rows - 1);
    for (let gx = max(floor(x0 / size) - this.gx0, 0); gx <= gx1; gx++) {
      for (let gy = gy0; gy <= gy1; gy++) {
        const from = start[gx * rows + gy];
        const end = start[gx * rows + gy + 1];
        read += end - from;
        for (let k = from; k < end; k++) {
          const at = items[k];
          if (mark[at] === stamp) continue;
          mark[at] = stamp;
          if (segHitsBox(x0, x1, y0, y1, boxes[at])) found[n++] = at;
        }
      }
    }
    this.read += read;
    return n;
  }
}
