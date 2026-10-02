/**
 * Finding connectors (UX_DESIGN section 4.6, R3.10). Selecting a finding that
 * names several steps draws a numbered dotted line from its first step to each
 * of the others.
 */

import { clear } from '../dom.js';
import { buildConnector } from './edges.js';
import { normalizeSeverity } from '../markers.js';
import type { GraphIndex } from '../layout/model.js';
import type { LayoutFrame } from '../layout/layout.js';
import type { Issue } from '../types.js';

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
  // RENDER-4. A finding draws only the relationships its author wrote: a
  // connector to each further node in `nodeIds`. Evidence line ranges are never
  // used to guess a node, which drew links to nodes the finding never named and
  // made counter-evidence look like support.
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
