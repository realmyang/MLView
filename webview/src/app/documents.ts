/**
 * The DOCUMENT: the graph the canvas draws and the collapse set that goes with it.
 *
 * `setGraph` owns both. Chrome, rail, outline, minimap and layout all read only
 * the index, so a new document needs no further edits (FEATURES 5.1). Viewer M2
 * removed the scope picker and its projection: the whole document is always drawn.
 */

import { GraphIndex } from '../layout/model.js';
import { renderChrome, renderRail } from './surfaces.js';
import type { App } from '../app.js';
import type { MLGraph, ViewState } from '../types.js';

/** A new document: index it, restore or default the collapse set, lay it out and repaint. */
export function setGraph(app: App, graph: MLGraph, preserve?: Partial<ViewState>, announce = false): void {
  app.graph = graph;
  const index = new GraphIndex(graph);
  app.index = index;
  if (preserve && preserve.collapsed) app.collapsedState = preserve.collapsed.slice();
  else if (!app.collapsedState.length && app.view.collapsed.size === 0) app.collapsedState = index.defaultCollapsed();

  const known = new Set(graph.nodes.map((n) => n.id));
  app.view.setIndex(index);
  // Every flow element and every --mlv-flow-* property goes before the scene
  // is rebuilt, and the remembered endpoint ids reset (CONTRACTS 11.14 C1).
  app.view.flow.clear();
  app.view.setCollapsed(app.collapsedState.filter((id) => known.has(id) && index.isGroup(id)));

  if (preserve && preserve.selection !== undefined) app.selection = preserve.selection;
  if (app.selection && app.selection.kind === 'node' && !known.has(app.selection.id)) app.selection = null;
  if (app.selection && app.selection.kind === 'edge' && !index.edgeById.has(app.selection.id)) app.selection = null;
  // VIEWUI-15: a finding the new revision removed is not a selection either,
  // or the Selection pane goes blank and the composer posts a stale id.
  if (app.selection && app.selection.kind === 'issue' && !index.issueById.has(app.selection.id)) app.selection = null;

  app.view.relayout();
  const vp = preserve && preserve.viewport ? preserve.viewport : null;
  if (vp) app.view.viewport.set(vp);
  else app.view.fit();
  renderChrome(app);
  renderRail(app);
  app.view.applySelection(app.selection);
  if (announce) {
    // Viewer M2 review (A11Y-10): the nouns the diagram prints (steps, findings), each count with
    // its unit; the high-severity count only when there is one.
    const plural = (n: number, one: string, many: string) => n + ' ' + (n === 1 ? one : many);
    const high = graph.stats.issues.high;
    app.announce(
      'Workflow loaded: ' + plural(graph.nodes.length, 'step', 'steps') + ', ' +
        plural(graph.edges.length, 'connection', 'connections') + ', ' +
        plural(graph.issues.length, 'finding', 'findings') +
        (high ? ' (' + high + ' high severity)' : '') + '.',
    );
  }
  app.saveSoon();
}

/**
 * Merge the drawn collapse set back into the remembered one. Ids the current document does not
 * have are kept, so a group a revision dropped and a later one restored comes back collapsed.
 */
export function syncCollapsed(app: App): void {
  if (!app.graph) return;
  const inView = new Set(app.graph.nodes.map((n) => n.id));
  const outside = app.collapsedState.filter((id) => !inView.has(id));
  app.collapsedState = outside.concat(Array.from(app.view.collapsed)).sort();
}
