/**
 * Keyboard navigation over the laid-out boxes: arrows move the selection among
 * siblings in spatial order, and continue through the whole diagram when a run
 * of siblings ends, so every node stays reachable from the keyboard (R4.6).
 */

import type { GraphIndex } from './model.js';
import type { LayoutBox, LayoutFrame } from './layout.js';

export function firstBox(frame: LayoutFrame): LayoutBox | null {
  const boxes = Array.from(frame.boxes.values());
  if (!boxes.length) return null;
  return boxes.slice().sort((a, b) => a.y - b.y || a.x - b.x)[0];
}

export function nextBox(index: GraphIndex, frame: LayoutFrame, currentId: string, key: string): LayoutBox | null {
  const boxes = Array.from(frame.boxes.values());
  const current = frame.boxes.get(currentId);
  if (!current || !boxes.length) return firstBox(frame);

  const parent = index.parentOf.get(currentId) || null;
  let siblings = boxes.filter((b) => (index.parentOf.get(b.id) || null) === parent && b.laneId === current.laneId);
  if (siblings.length < 2) siblings = boxes.filter((b) => b.laneId === current.laneId);

  const horizontal = key === 'ArrowRight' || key === 'ArrowLeft';
  const forward = key === 'ArrowRight' || key === 'ArrowDown';
  const step = (list: LayoutBox[]): LayoutBox | null => {
    const sorted = list.slice().sort((a, b) => (horizontal ? a.x - b.x || a.y - b.y : a.y - b.y || a.x - b.x));
    const at = sorted.findIndex((b) => b.id === currentId);
    return at < 0 ? null : sorted[at + (forward ? 1 : -1)] || null;
  };
  return step(siblings) || step(boxes);
}

/**
 * Viewer M3 (live check, W5): from a selected connection, an arrow key moves to whichever of its two
 * drawn cards lies further that way: → the one further right, ← further left, ↓ lower, ↑ higher,
 * by their centres. On a tie (both ends in one column for → and ←, one row for ↓ and ↑) → and ↓
 * take the connection's target and ← and ↑ its source. Both ids are the cards as drawn (a collapsed
 * group stands for the steps inside it); a card that is not drawn is skipped.
 */
export function connectionEnd(frame: LayoutFrame, sourceId: string | null, targetId: string | null, key: string): LayoutBox | null {
  const source = sourceId ? frame.boxes.get(sourceId) || null : null;
  const target = targetId ? frame.boxes.get(targetId) || null : null;
  if (!source || !target) return source || target;
  const horizontal = key === 'ArrowRight' || key === 'ArrowLeft';
  const forward = key === 'ArrowRight' || key === 'ArrowDown';
  const centre = (b: LayoutBox) => (horizontal ? b.x + b.w / 2 : b.y + b.h / 2);
  const delta = centre(target) - centre(source);
  if (delta === 0) return forward ? target : source;
  return (delta > 0) === forward ? target : source;
}

