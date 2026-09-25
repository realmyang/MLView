/**
 * Multi-location connectors (UX_DESIGN section 4.6, R3.10). Selecting an issue
 * with relatedLocs draws a numbered dotted line from the primary node to each
 * related node — the MLV101 leak becomes a picture rather than a sentence.
 */

import { clear } from '../dom.js';
import { buildConnector } from './edges.js';
import { normalizeSeverity } from '../markers.js';
import type { GraphIndex } from '../layout/model.js';
import type { LayoutFrame } from '../layout/layout.js';
import type { Issue, MLNode } from '../types.js';

/** The NARROWEST node whose source range contains this line — `forward` beats its class. */
export function nodeIdForLoc(
  index: GraphIndex,
  collapsed: Set<string>,
  loc: { file: string; line: number },
): string | null {
  let best: MLNode | null = null;
  let bestSpan = Infinity;
  for (const node of index.graph.nodes) {
    if (node.loc.file !== loc.file) continue;
    if (loc.line < node.loc.line || loc.line > node.loc.endLine) continue;
    const span = node.loc.endLine - node.loc.line;
    if (span < bestSpan) {
      best = node;
      bestSpan = span;
    }
  }
  return best ? index.visibleRepresentative(best.id, collapsed) : null;
}

export function drawIssueConnectors(
  layer: SVGElement,
  index: GraphIndex,
  frame: LayoutFrame,
  collapsed: Set<string>,
  issue: Issue,
): number {
  clear(layer);
  const primary = issue.nodeIds[0];
  if (!primary) return 0;
  const fromBox = frame.boxes.get(index.visibleRepresentative(primary, collapsed));
  if (!fromBox) return 0;
  const severity = normalizeSeverity(issue.severity);
  let drawn = 0;
  // RENDER-4. An authored finding draws only the relationships its author
  // wrote: a connector to each further node in `nodeIds`. Evidence line ranges
  // are never used to guess a node, which drew links to nodes the finding never
  // named and made counter-evidence look like support.
  if (index.graph.schemaVersion === 'workflow-view/1') {
    const seen = new Set<string>([fromBox.id]);
    for (const nodeId of issue.nodeIds.slice(1)) {
      const node = index.nodeById.get(nodeId);
      if (!node) continue;
      const toBox = frame.boxes.get(index.visibleRepresentative(nodeId, collapsed));
      if (!toBox || seen.has(toBox.id)) continue;
      seen.add(toBox.id);
      drawn++;
      layer.appendChild(
        buildConnector(
          { x: fromBox.x + fromBox.w / 2, y: fromBox.y },
          { x: toBox.x + toBox.w / 2, y: toBox.y },
          drawn,
          severity,
          'Also affects — ' + (node.label || node.id),
        ),
      );
    }
    return drawn;
  }
  for (const rel of issue.relatedLocs || []) {
    const targetId = nodeIdForLoc(index, collapsed, rel);
    if (!targetId) continue;
    const toBox = frame.boxes.get(targetId);
    if (!toBox || toBox.id === fromBox.id) continue;
    drawn++;
    layer.appendChild(
      buildConnector(
        { x: fromBox.x + fromBox.w / 2, y: fromBox.y },
        { x: toBox.x + toBox.w / 2, y: toBox.y },
        drawn,
        severity,
        (rel.message || rel.role) + ' — ' + rel.file + ':' + rel.line,
      ),
    );
  }
  return drawn;
}
