/**
 * The Outline tab — the screen-reader-complete path through the graph
 * (REQUIREMENTS R4.7, UX_DESIGN §8.3).
 *
 * Three rules this file exists to keep:
 *
 * 1. It walks the DRAWN hierarchy (`laneChildren`), never the document's lexical
 *    `parent`. A node whose lexical parent sits in another stage is promoted to a
 *    root of its own lane by `GraphIndex` (model.ts), so walking `children()` here
 *    emitted it twice — once as a lane root and once inside its lexical parent's
 *    subtree — and the "complete" path contradicted itself about where half the
 *    pipeline lived (MLV-R2-W01). Every node appears exactly once.
 * 2. It is a real ARIA tree: the `treeitem` itself takes focus with a roving
 *    tabindex, Arrow/Home/End navigate, Left/Right collapse and expand, and a
 *    printable key is type-ahead (MLV-R2-W08).
 * 3. `aria-expanded` and the child list's visibility are driven by the canvas's
 *    own collapsed set, so collapsing here collapses there and vice versa.
 */

import { add, el, on } from '../dom.js';
import { uiIcon } from '../icons.js';
import { severityGlyph, countsTotal, highestSeverity } from '../markers.js';
import type { Severity } from '../types.js';
import type { GraphIndex, IssuePredicate } from '../layout/model.js';

export interface OutlineCallbacks {
  /** A node row was activated: select it and centre the canvas on it. */
  onSelectNode(id: string): void;
  /** A lane row was activated: jump to that stage. */
  onSelectLane(laneId: string): void;
  /** Left/Right on a group row: collapse or expand it in the canvas too. */
  onToggleCollapse(id: string): void;
}

export interface OutlineState {
  index: GraphIndex;
  keep: IssuePredicate;
  selectedNodeId: string | null;
  collapsed: Set<string>;
}

const TREEITEM = '[role="treeitem"]';

export function renderOutlineTree(panel: HTMLElement, s: OutlineState, cb: OutlineCallbacks): HTMLElement {
  const tree = add(panel, el('ul', 'mlv-outline'));
  tree.setAttribute('role', 'tree');
  tree.setAttribute('aria-label', 'Pipeline outline');

  for (const lane of s.index.lanes) {
    const item = add(tree, el('li', 'mlv-outline__item'));
    item.setAttribute('role', 'treeitem');
    item.setAttribute('data-outline-lane', lane.id);
    item.tabIndex = -1;
    const row = add(item, el('div', 'mlv-outline__row mlv-outline__row--lane'));
    add(row, el('span', 'mlv-outline__label', lane.label || lane.id));
    const counts = s.index.laneCounts(lane.id, s.keep);
    if (countsTotal(counts) > 0) {
      row.appendChild(severityGlyph(highestSeverity(counts) as Severity, 12, ''));
      add(row, el('span', 'mlv-outline__stage', String(countsTotal(counts))));
    }
    on(row, 'click', () => cb.onSelectLane(lane.id));
    const kids = s.index.roots(lane.id);
    item.setAttribute('aria-expanded', kids.length ? 'true' : 'false');
    if (kids.length) item.appendChild(branch(kids, s, cb));
  }

  wireTree(tree, cb);
  setRoving(tree, preferredFocus(tree, s.selectedNodeId));
  return tree;
}

/** One `role="group"` level of the drawn hierarchy. */
function branch(ids: string[], s: OutlineState, cb: OutlineCallbacks): HTMLElement {
  const ul = el('ul');
  ul.setAttribute('role', 'group');
  for (const id of ids) {
    const node = s.index.nodeById.get(id);
    if (!node) continue;
    const item = add(ul, el('li', 'mlv-outline__item'));
    item.setAttribute('role', 'treeitem');
    item.setAttribute('data-outline-id', id);
    item.tabIndex = -1;

    // The DRAWN children, matching the canvas and every other consumer.
    const kids = s.index.laneChildren(id);
    const collapsed = kids.length > 0 && s.collapsed.has(id);
    if (kids.length) item.setAttribute('aria-expanded', collapsed ? 'false' : 'true');

    const row = add(item, el('div', 'mlv-outline__row'));
    const selected = s.selectedNodeId === id;
    item.setAttribute('aria-selected', selected ? 'true' : 'false');
    if (selected) row.classList.add('is-selected');
    if (kids.length) {
      const chev = uiIcon('chevron', 12);
      chev.setAttribute('class', 'mlv-uicon mlv-outline__chevron');
      row.appendChild(chev);
    } else {
      add(row, el('span', 'mlv-outline__chevron mlv-outline__chevron--none'));
    }
    add(row, el('span', 'mlv-outline__label', node.label || node.qualname));
    add(row, el('span', 'mlv-outline__stage', node.kind));
    const glyph = severityFor(s, id);
    if (glyph) row.appendChild(glyph);
    on(row, 'click', () => cb.onSelectNode(id));

    if (kids.length) {
      const sub = branch(kids, s, cb);
      sub.hidden = collapsed;
      item.appendChild(sub);
    }
  }
  return ul;
}

function severityFor(s: OutlineState, id: string): SVGElement | null {
  const top = highestSeverity(s.index.subtreeCounts(id, s.keep));
  return top ? severityGlyph(top, 12, '') : null;
}

/* ── the tree's keyboard model ───────────────────────────────────────────── */

/** Treeitems the user can actually reach: nothing inside a collapsed group. */
function visibleItems(tree: HTMLElement): HTMLElement[] {
  const all = Array.prototype.slice.call(tree.querySelectorAll(TREEITEM)) as HTMLElement[];
  return all.filter((item) => {
    let cur: HTMLElement | null = item.parentElement;
    while (cur && cur !== tree) {
      if (cur.hidden) return false;
      cur = cur.parentElement;
    }
    return true;
  });
}

/** Exactly one treeitem is in the tab order (ARIA roving tabindex). */
function setRoving(tree: HTMLElement, active: HTMLElement | null): void {
  const items = visibleItems(tree);
  const target = active && items.indexOf(active) >= 0 ? active : items[0] || null;
  for (const item of items) item.tabIndex = item === target ? 0 : -1;
}

function preferredFocus(tree: HTMLElement, selectedNodeId: string | null): HTMLElement | null {
  if (!selectedNodeId) return null;
  const items = visibleItems(tree);
  for (const item of items) {
    if (item.getAttribute('data-outline-id') === selectedNodeId) return item;
  }
  return null;
}

function focusItem(tree: HTMLElement, item: HTMLElement | null | undefined): void {
  if (!item) return;
  setRoving(tree, item);
  item.focus();
}

function parentItem(tree: HTMLElement, item: HTMLElement): HTMLElement | null {
  let cur: HTMLElement | null = item.parentElement;
  while (cur && cur !== tree) {
    if (cur.getAttribute('role') === 'treeitem') return cur;
    cur = cur.parentElement;
  }
  return null;
}

function firstChildItem(item: HTMLElement): HTMLElement | null {
  const group = item.querySelector('[role="group"]') as HTMLElement | null;
  if (!group || group.hidden) return null;
  return group.querySelector(TREEITEM) as HTMLElement | null;
}

function activate(item: HTMLElement, cb: OutlineCallbacks): void {
  const nodeId = item.getAttribute('data-outline-id');
  if (nodeId) {
    cb.onSelectNode(nodeId);
    return;
  }
  const lane = item.getAttribute('data-outline-lane');
  if (lane) cb.onSelectLane(lane);
}

function labelOf(item: HTMLElement): string {
  const label = item.querySelector('.mlv-outline__label');
  return (label ? label.textContent || '' : '').toLowerCase();
}

function wireTree(tree: HTMLElement, cb: OutlineCallbacks): void {
  on(tree, 'keydown', (ev: KeyboardEvent) => {
    const target = ev.target as HTMLElement | null;
    if (!target || typeof target.closest !== 'function') return;
    const item = target.closest(TREEITEM) as HTMLElement | null;
    if (!item || !tree.contains(item)) return;
    const items = visibleItems(tree);
    const at = items.indexOf(item);
    if (at < 0) return;
    const expanded = item.getAttribute('aria-expanded');
    const nodeId = item.getAttribute('data-outline-id');

    switch (ev.key) {
      case 'ArrowDown':
        ev.preventDefault();
        focusItem(tree, items[Math.min(items.length - 1, at + 1)]);
        return;
      case 'ArrowUp':
        ev.preventDefault();
        focusItem(tree, items[Math.max(0, at - 1)]);
        return;
      case 'Home':
        ev.preventDefault();
        focusItem(tree, items[0]);
        return;
      case 'End':
        ev.preventDefault();
        focusItem(tree, items[items.length - 1]);
        return;
      case 'ArrowRight':
        ev.preventDefault();
        if (expanded === 'false' && nodeId) cb.onToggleCollapse(nodeId);
        else if (expanded === 'true') focusItem(tree, firstChildItem(item));
        return;
      case 'ArrowLeft':
        ev.preventDefault();
        if (expanded === 'true' && nodeId) cb.onToggleCollapse(nodeId);
        else focusItem(tree, parentItem(tree, item));
        return;
      case 'Enter':
      case ' ':
        ev.preventDefault();
        activate(item, cb);
        return;
      default:
        break;
    }

    // Type-ahead: a printable key jumps to the next row whose label starts with it.
    if (ev.key.length !== 1 || ev.ctrlKey || ev.metaKey || ev.altKey) return;
    const ch = ev.key.toLowerCase();
    for (let step = 1; step <= items.length; step++) {
      const candidate = items[(at + step) % items.length];
      if (labelOf(candidate).indexOf(ch) === 0) {
        ev.preventDefault();
        focusItem(tree, candidate);
        return;
      }
    }
  });
}
