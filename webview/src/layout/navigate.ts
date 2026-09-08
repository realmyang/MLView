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
