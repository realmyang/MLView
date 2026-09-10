/**
 * The application shell: the DOM skeleton and the canvas gestures.
 *
 * Structure only — no graph knowledge. `buildShell` returns the slots the app
 * fills (chrome, rail, tooltip, minimap, toasts, states) and `wireCanvasGestures`
 * attaches pan, wheel-zoom and background-click, returning their disposers.
 */

import { add, clear, el, on, svg } from '../dom.js';
import { PinchTracker, wireWheel } from './gestures.js';
import { buildDefs } from '../render/edges.js';
import type { ThemeKind } from '../types.js';
import type { ViewportController } from '../render/canvas.js';

export interface Shell {
  body: HTMLElement;
  scrim: HTMLElement;
  /**
   * The `<main>` landmark around the diagram (VIEW-12). The canvas, the minimap
   * and the Pipeline Answer Card live inside it; the rail is a sibling `<aside>`,
   * so a landmark walk reaches the diagram in one step.
   */
  main: HTMLElement;
  canvas: HTMLElement;
  world: HTMLElement;
  lanesLayer: HTMLElement;
  edgesSvg: SVGElement;
  edgeGroup: SVGElement;
  connectorLayer: SVGElement;
  nodesLayer: HTMLElement;
  zoomLevel: HTMLElement;
  stateHost: HTMLElement;
  live: HTMLElement;
}

/**
 * Claim the page-fill chain when the viewer IS the page (MLV-R1-001).
 *
 * `.mlv-root` is `height: 100%`, which resolves to `auto` unless every ancestor
 * has a definite height. Both contracted hosts mount into a direct child of
 * <body> (CONTRACTS A4, A5) and want the app to fill the window; a dev page that
 * merely tiles components does not, so the claim is conditional and reversible.
 */
export function claimPage(root: HTMLElement): () => void {
  const doc = root.ownerDocument;
  if (!doc || !doc.body || root.parentElement !== doc.body) return () => undefined;
  doc.documentElement.classList.add('mlv-fills-page');
  doc.body.classList.add('mlv-fills-page');
  return () => {
    doc.documentElement.classList.remove('mlv-fills-page');
    doc.body.classList.remove('mlv-fills-page');
  };
}

let shellSeq = 0;

/** Build the empty shell inside `root`. Chrome and rail are appended by the app. */
export function buildShell(root: HTMLElement, theme: ThemeKind): Shell {
  root.classList.add('mlv-root');
  root.setAttribute('data-theme', theme);
  clear(root);
  const uid = 'mlv-shell' + ++shellSeq;

  const body = el('div', 'mlv-body');

  // Overlay scrim behind the rail below the 900 px breakpoint (UX_DESIGN §1).
  const scrim = add(body, el('div', 'mlv-scrim'));
  scrim.hidden = true;

  const main = el('main', 'mlv-main');
  main.setAttribute('aria-labelledby', uid + '-main-heading');
  const mainHeading = add(main, el('h2', 'mlv-sr', 'Pipeline diagram'));
  mainHeading.id = uid + '-main-heading';

  const canvas = el('div', 'mlv-canvas');
  canvas.id = uid + '-canvas';
  canvas.setAttribute('role', 'application');
  canvas.setAttribute('aria-label', 'ML pipeline diagram');
  canvas.setAttribute('data-lod', 'full');
  canvas.tabIndex = 0;
  main.appendChild(canvas);

  // VIEW-12. THE FIRST TAB STOP, appended before anything the App adds. It is a
  // real anchor so assistive tech announces it as a link, but the click is
  // handled here and the default prevented: the standalone report must never
  // navigate its own document (CONTRACTS 11.17), not even to a fragment, and a
  // hash would also push a history entry a reader never asked for.
  const skip = el('a', 'mlv-skiplink', 'Skip to diagram');
  skip.href = '#' + canvas.id;
  on(skip, 'click', (ev: MouseEvent) => {
    ev.preventDefault();
    try {
      canvas.focus();
    } catch (_e) {
      /* a host may have detached the canvas already */
    }
  });
  root.appendChild(skip);

  const world = add(canvas, el('div', 'mlv-world'));
  const lanesLayer = add(world, el('div', 'mlv-layer mlv-layer--lanes'));
  const edgesSvg = svg('svg', { class: 'mlv-layer mlv-layer--edges', width: 1, height: 1 });
  edgesSvg.appendChild(buildDefs());
  const edgeGroup = svg('g', { class: 'mlv-edges' });
  const connectorLayer = svg('g', { class: 'mlv-connectors' });
  edgesSvg.appendChild(edgeGroup);
  edgesSvg.appendChild(connectorLayer);
  world.appendChild(edgesSvg);
  const nodesLayer = add(world, el('div', 'mlv-layer mlv-layer--nodes'));

  const zoomBar = add(canvas, el('div', 'mlv-zoom'));
  const zoomLevel = add(zoomBar, el('span', 'mlv-zoom__level', '100%'));

  const stateHost = add(canvas, el('div', 'mlv-statehost'));

  const live = el('div', 'mlv-sr');
  live.setAttribute('aria-live', 'polite');
  live.setAttribute('role', 'status');

  return {
    body,
    scrim,
    main,
    canvas,
    world,
    lanesLayer,
    edgesSvg,
    edgeGroup,
    connectorLayer,
    nodesLayer,
    zoomLevel,
    stateHost,
    live,
  };
}

/** The app root itself — focus lands there after a host steals and returns it. */
function isAppRoot(node: Node): boolean {
  const el = node as HTMLElement;
  return !!el.classList && el.classList.contains('mlv-root');
}

export interface GestureHandlers {
  onKeyDown(ev: KeyboardEvent): void;
  onBackgroundClick(): void;
}

/** Pan by dragging the background, zoom on the wheel, keys on the canvas. */
export function wireCanvasGestures(
  canvas: HTMLElement,
  viewport: ViewportController,
  handlers: GestureHandlers,
): (() => void)[] {
  const disposers: (() => void)[] = [];
  const pinch = new PinchTracker(canvas, viewport);
  let panning = false;
  let lastX = 0;
  let lastY = 0;

  disposers.push(
    on(canvas, 'pointerdown', (ev: PointerEvent) => {
      // EVERY pointer joins the pinch, wherever it landed (VIEW-06). This used
      // to sit below the card guard, so a finger placed on a node card was never
      // registered: `active()` stayed false and the second finger started an
      // ordinary one-pointer PAN. Pinching to zoom into a card is the normal
      // touch gesture and cards cover most of the canvas, so on a tablet — where
      // `canvas.css` sets `touch-action: none` and the browser's own pinch is
      // therefore suppressed — the diagram slid sideways instead of zooming.
      pinch.down(ev);
      if (pinch.active()) {
        // A second finger turns a drag into a pinch: the one-pointer pan must
        // let go, or the canvas would pan and scale from the same travel.
        panning = false;
        canvas.classList.remove('is-panning');
        return;
      }
      // The guard still decides whether a DRAG-PAN may start: dragging a card,
      // the minimap, the zoom cluster or an edge is that widget's gesture.
      const target = ev.target as HTMLElement;
      if (target.closest && target.closest('.mlv-node, .mlv-group__header, .mlv-minimap, .mlv-zoom, .mlv-edge__hit')) {
        return;
      }
      panning = true;
      lastX = ev.clientX;
      lastY = ev.clientY;
      canvas.classList.add('is-panning');
      try {
        canvas.setPointerCapture(ev.pointerId);
      } catch (_e) {
        /* jsdom and some hosts have no pointer capture */
      }
    }),
  );

  disposers.push(
    on(canvas, 'pointermove', (ev: PointerEvent) => {
      if (pinch.move(ev)) return;
      if (!panning) return;
      viewport.panBy(ev.clientX - lastX, ev.clientY - lastY);
      lastX = ev.clientX;
      lastY = ev.clientY;
    }),
  );

  const endPan = (ev?: PointerEvent) => {
    if (ev) pinch.up(ev);
    panning = false;
    canvas.classList.remove('is-panning');
  };
  disposers.push(on(canvas, 'pointerup', endPan));
  disposers.push(on(canvas, 'pointercancel', endPan));
  disposers.push(on(canvas, 'pointerleave', endPan));

  // Wheel: deltaMode-normalized, ctrl-branched, two-axis (VIEW-06).
  disposers.push(wireWheel(canvas, viewport));

  disposers.push(on(canvas, 'keydown', (ev: KeyboardEvent) => handlers.onKeyDown(ev)));

  // ...and the same keys again when focus has fallen OFF the canvas onto a
  // container. Anything that steals focus and hands it back to <body> — a
  // clipboard fallback, a host dialog, a removed element — used to kill the
  // whole canvas keymap until the user clicked the diagram again: `e`, then
  // Shift+E, Escape, `f` and `0` all dead, with a latched pulse that could not
  // be dismissed (MLV-R1-FLOW-007). Only the three CONTAINERS qualify, so no
  // event from the rail, the chrome, a dialog or a text field is ever taken
  // twice or taken at all.
  const doc = canvas.ownerDocument;
  if (doc) {
    disposers.push(
      on(doc, 'keydown', (ev: KeyboardEvent) => {
        const target = ev.target as unknown as Node | null;
        if (!target) return;
        if (target !== doc.body && target !== doc.documentElement && !isAppRoot(target)) return;
        handlers.onKeyDown(ev);
      }),
    );
  }

  disposers.push(
    on(canvas, 'click', (ev: MouseEvent) => {
      const target = ev.target as HTMLElement;
      if (!target.closest || !target.closest('.mlv-node, .mlv-edge__hit, .mlv-group')) handlers.onBackgroundClick();
    }),
  );

  if (typeof window !== 'undefined') {
    // Keep the derived chrome (zoom readout, minimap viewport) in step with a
    // resized panel without moving what the user is looking at.
    disposers.push(on(window, 'resize', () => viewport.apply()));
  }

  disposers.push(() => pinch.clear());
  return disposers;
}
