/**
 * The App's part in a far connection of the review walk, one whose two end
 * cards cannot both be shown. It ties three things together and holds almost no state of its own:
 *
 *   - the walk says which connection it is on (`ReviewWalk.current`);
 *   - the canvas says how it shows that connection's two ends now, moves to one of them, and
 *     draws the caps on its lit line (`canvas/far.ts`);
 *   - the walk bar prints one line that names the far card (`ui/walkbar.ts`).
 *
 * What is far, where a cap sits and every word said are the pure functions of `far.ts`.
 */

import { atEnd, atEndAnnouncement, capTitle, farAnnouncement, farGoal, farIdleText, farLine, inViewAnnouncement, isFar, lookAnnouncement, stepRanks, stepTitle } from '../far.js';
import type { End, FarEnds, FarLine } from '../far.js';
import { sameClaim } from '../walk.js';
import type { App } from '../app.js';
import type { GraphIndex } from '../layout/model.js';

export class WalkFar {
  private app: App;
  /**
   * The walk bar's line is on show: the walk is on a connection, that connection is the selection
   * and one of its ends is out of view, however the walk came onto it (a step, a look, a click on
   * its line, Reveal in Diagram) and however the end left the view.
   */
  private shown = false;
  /** Each step's place in reading order, built once per document (`stepRanks`). */
  private ranks: { index: GraphIndex; ranks: Map<string, number> } | null = null;
  /**
   * The connection the walk came onto by a selection that was no step of its own (a click on its
   * line, Reveal in Diagram) while its two cards did not fit the canvas. The view holds neither
   * end of it; for the arrows it is a far one all the same.
   */
  private cameFar: string | null = null;
  /**
   * The connection `cameFar` was judged for, and whether a walk step is bringing the next one:
   * from `beforeStep` until a `sync` finds the step's claim selected.
   */
  private at: string | null = null;
  private stepping = false;

  constructor(app: App) {
    this.app = app;
  }

  /** The walk's current claim when it is a connection and still the selection, else null. */
  private edge(): string | null {
    const claim = this.app.walk.active ? this.app.walk.current() : null;
    return claim && claim.kind === 'edge' && sameClaim(claim, this.app.selection) ? claim.id : null;
  }

  /** What the walk bar's line says of the walk's connection as the canvas shows it, or null. */
  private line(edgeId: string, ends: FarEnds): FarLine | null {
    const index = this.app.index;
    if (!index) return null;
    if (!this.ranks || this.ranks.index !== index) this.ranks = { index, ranks: stepRanks(index) };
    return farLine(index, edgeId, ends, this.ranks.ranks, this.app.view.far.drawn(edgeId));
  }

  /**
   * Bring the walk bar's line and the caps in step with the canvas. While an end of the walk's
   * connection is out of view the line is on show and follows the view (the direction and the
   * distance in screens change as the reader pans); with both ends in view the line's place says
   * so. The place is never empty on a connection.
   */
  sync(): void {
    const app = this.app;
    if (!app.walkBar || !app.view) return;
    const index = app.index;
    const edgeId = this.edge();
    const ends = edgeId ? app.view.far.ends(edgeId) : null;
    if (edgeId !== this.at) {
      this.at = edgeId;
      this.cameFar = edgeId && ends && !ends.fits && !this.stepping ? edgeId : null;
    }
    // The step has landed once its claim is the selection. A sync earlier in the step is not that:
    // opening a folded group around the claim lays the diagram out again, which syncs.
    if (!app.walk.active || sameClaim(app.walk.current(), app.selection)) this.stepping = false;
    if (!edgeId) app.view.far.clear();
    const line = edgeId && ends ? this.line(edgeId, ends) : null;
    app.walkBar.setFar(line);
    app.walkBar.setFarIdle(ends && !line ? farIdleText(ends) : '');
    this.shown = !!line;
    if (!edgeId || !ends || !line || !index) {
      app.view.far.setCaps(null, []);
      return;
    }
    const wanted = (['source', 'target'] as const)
      .filter((end) => !ends[end].inView)
      .map((end) => ({ end, title: capTitle(stepTitle(index, ends[end].id), ends[end].way) }));
    // The line's own copy of the cap is shown only while a cap is on the canvas.
    app.walkBar.markFar(app.view.far.setCaps(edgeId, wanted).length > 0);
  }

  /**
   * A walk step is about to show its claim. A look at a far end was a detour: the step starts
   * from the picture the reader left at the source. The line goes until the step has landed.
   */
  beforeStep(): void {
    const app = this.app;
    app.view.far.endLook();
    this.stepping = true;
    if (app.walkBar) app.walkBar.setFar(null);
    this.shown = false;
    app.view.far.setCaps(null, []);
  }

  /**
   * Key o, the walk bar's line, a cap, or an arrow key towards an end that is out of view: look at
   * an end of the walk's connection. Without `end`: the end that is out of view (`farGoal`), so
   * the same key goes to the far card and comes back. The connection stays the walk's
   * claim, selected and lit; the walk's place and the Selection pane do not change, and the
   * keyboard focus stays where it is. A look that shows both cards says that both ends are in
   * view, whichever end it was for: two cards that can be shown together are, and the view then
   * holds no end (`FarView.look`), so there is no far end with a way back and no source to be back
   * at. So does a look towards the far card that leaves both ends in view. False when the walk is
   * not on a connection.
   */
  otherEnd(end?: End): boolean {
    const app = this.app;
    const index = app.index;
    const edgeId = this.edge();
    const ends = edgeId ? app.view.far.ends(edgeId) : null;
    if (!edgeId || !ends || !index) return false;
    const to = end || farGoal(ends);
    if (!to) {
      app.announce(inViewAnnouncement(ends));
      return true;
    }
    app.view.holdHover();
    app.view.far.look(edgeId, to);
    this.sync();
    const now = app.view.far.ends(edgeId);
    const both = now && !isFar(now) && (to === 'target' || now.keep === null) ? now : null;
    app.announce(both ? inViewAnnouncement(both) : lookAnnouncement(index, edgeId, ends, to));
    return true;
  }

  /**
   * ← or → while the walk is on a connection. When the card that lies that way is out of view,
   * look at it; the walk stays on the connection. When it is in view and the line is on show (the
   * other end is out of view), the arrow says which end of the connection that card is and moves
   * nothing in two cases, where selecting the card would take the walk with it to another claim,
   * which may lie far from this one in the walk's order:
   *
   * - the connection's two cards do not fit the canvas, and the view holds an end of it or the
   *   walk came onto it by a selection that was no step (`cameFar`), whichever of the two is in
   *   view and however much of the other one still shows;
   * - the reader is at that end (`atEnd`).
   *
   * True when it looked or said so. Otherwise the arrow selects the card (`moveSelection`): on a
   * connection with both ends in view, on two cards that fit the canvas together wherever the
   * reader moved the other one (unless the card in view is the end the view holds), and on two
   * the view holds neither of and `cameFar` does not name, while the other one is only cut off
   * at the canvas's edge or under the phase index. Such a connection is not a far one.
   */
  arrow(key: string): boolean {
    const app = this.app;
    const edgeId = this.edge();
    const ends = edgeId ? app.view.far.ends(edgeId) : null;
    if (!edgeId || !ends) return false;
    const next = app.view.nextSelection(app.selection, key);
    if (!next) return false;
    const end = next.id === ends.target.drawnId ? 'target' : next.id === ends.source.drawnId ? 'source' : null;
    if (!end) return false;
    if (!ends[end].inView) return this.otherEnd(end);
    const far = !ends.fits && (ends.keep !== null || this.cameFar === edgeId);
    if (!this.shown || !(far || atEnd(ends, end))) return false;
    app.announce(atEndAnnouncement(end));
    return true;
  }

  /** What the walk's announcement adds on a connection whose far end is out of view, else ''. */
  announcement(): string {
    const edgeId = this.edge();
    const ends = edgeId && this.shown ? this.app.view.far.ends(edgeId) : null;
    const line = edgeId && ends ? this.line(edgeId, ends) : null;
    return line ? farAnnouncement(line) : '';
  }
}
