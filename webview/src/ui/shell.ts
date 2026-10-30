/**
 * The application shell: the DOM skeleton and the canvas gestures.
 *
 * Structure only — no graph knowledge. `buildShell` returns the slots the app
 * fills (chrome, rail, tooltip, toasts, states) and `wireCanvasGestures`
 * attaches pan, wheel-zoom and background-click, returning their disposers.
 */

import { add, clear, el, on, svg } from '../dom.js';
import { PinchTracker, wireWheel } from './gestures.js';
import { buildDefs } from '../render/edges.js';
import type { ThemeKind } from '../types.js';
import type { ViewportController } from '../render/canvas.js';

export interface Shell {
  body: HTMLElement;
  /**
   * The `<main>` landmark around the diagram. The canvas (with the phase index and the
   * phase overview inside it) and the review walk's bar live inside it; the rail is a sibling
   * `<aside>`, so a landmark walk reaches the diagram in one step.
   */
  main: HTMLElement;
  canvas: HTMLElement;
  world: HTMLElement;
  lanesLayer: HTMLElement;
  edgesSvg: SVGElement;
  /** The cross-lane trunks, drawn UNDER the cables they stand for. */
  bundleGroup: SVGElement;
  edgeGroup: SVGElement;
  connectorLayer: SVGElement;
  nodesLayer: HTMLElement;
  /** The status bar's zoom control; the readout inside it is `zoomLevel`. */
  zoomBar: HTMLElement;
  zoomLevel: HTMLElement;
  stateHost: HTMLElement;
  live: HTMLElement;
}

/**
 * Claim the page-fill chain when the viewer IS the page.
 *
 * `.mlv-root` is `height: 100%`, which resolves to `auto` unless every ancestor
 * has a definite height. The VS Code host mounts into a direct child of
 * <body> and wants the app to fill the window; a dev page that
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

  // The rail is beside the canvas or a bottom sheet under it (`data-rail`), never a
  // drawer over it, so there is no scrim.
  const body = el('div', 'mlv-body');

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

  // THE FIRST TAB STOP, appended before anything the App adds. It is a
  // real anchor so assistive tech announces it as a link, but the click is
  // handled here and the default prevented: the webview must never navigate its
  // own document, not even to a fragment, and a hash would
  // also push a history entry a reader never asked for.
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
  const bundleGroup = svg('g', { class: 'mlv-bundles' });
  const edgeGroup = svg('g', { class: 'mlv-edges' });
  const connectorLayer = svg('g', { class: 'mlv-connectors' });
  edgesSvg.appendChild(bundleGroup);
  edgesSvg.appendChild(edgeGroup);
  edgesSvg.appendChild(connectorLayer);
  world.appendChild(edgesSvg);
  const nodesLayer = add(world, el('div', 'mlv-layer mlv-layer--nodes'));

  // The zoom readout lives in the status bar (ui/chrome.ts adds its two buttons).
  const zoomBar = el('div', 'mlv-zoom');
  const zoomLevel = add(zoomBar, el('span', 'mlv-zoom__level', '100%'));
  zoomLevel.setAttribute('aria-label', 'Zoom level');

  const stateHost = add(canvas, el('div', 'mlv-statehost'));

  const live = el('div', 'mlv-sr');
  live.setAttribute('aria-live', 'polite');
  live.setAttribute('role', 'status');

  return {
    body,
    main,
    canvas,
    world,
    lanesLayer,
    edgesSvg,
    bundleGroup,
    edgeGroup,
    connectorLayer,
    nodesLayer,
    zoomBar,
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
  /** The window resized. Absent: only the derived chrome is refreshed. */
  onResize?(): void;
}

/**
 * How far the pointer travels, in pixels along x plus y, before a press on the background is a
 * drag and not a click.
 */
const PAN_CLICK_SLOP_PX = 4;

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
  // Where the pan under way started, and whether it has travelled further than a click does. The
  // browser sends a click after every press and release on the canvas, also after a drag: such a
  // click is the end of a pan, not a click on the background, and keeps the selection, so a reader
  // who drags the diagram to follow a selected connection's line still has it selected.
  let downX = 0;
  let downY = 0;
  let dragged = false;

  disposers.push(
    on(canvas, 'pointerdown', (ev: PointerEvent) => {
      // A new press starts clean, so a drag whose click never came cannot swallow this one's.
      dragged = false;
      // The phase overview covers the canvas and scrolls by itself; a press on it is
      // never a pan or a pinch of the diagram hidden under it.
      const over = ev.target as HTMLElement;
      if (over && over.closest && over.closest('.mlv-overview')) return;
      // EVERY pointer joins the pinch, wherever it landed, so this stands above the
      // card guard below. A finger placed on a node card must be registered, or
      // `active()` stays false and the second finger starts an ordinary
      // one-pointer PAN. Pinching to zoom into a card is the normal touch gesture
      // and cards cover most of the canvas, and on a tablet `canvas.css` sets
      // `touch-action: none`, so the browser's own pinch is suppressed and this
      // one is the only pinch there is.
      pinch.down(ev);
      if (pinch.active()) {
        // A second finger turns a drag into a pinch: the one-pointer pan must
        // let go, or the canvas would pan and scale from the same travel.
        panning = false;
        canvas.classList.remove('is-panning');
        return;
      }
      // The guard decides whether a DRAG-PAN may start: dragging a card, a group
      // header, the phase index or an edge is that widget's gesture.
      //
      // The list must name EVERY overlay painted over the canvas, not only those
      // the shell builds itself: `app/build.ts` appends the legend and
      // `canvasview.ts` the tooltip and the toast stack to the canvas, and a
      // pointerdown that is not exempted here calls `setPointerCapture`, which
      // retargets the rest of the gesture to the canvas — so in a real browser
      // the legend's own close button would never see its `click`, and a drag
      // inside the panel would pan the diagram underneath it. The rule behind the
      // list is "a direct child of `.mlv-canvas` that is not `.mlv-world` is
      // chrome". Extend the list by hand when a new overlay is appended to the
      // canvas.
      const target = ev.target as HTMLElement;
      if (target.closest && target.closest('.mlv-node, .mlv-group__header, .mlv-phaseindex, .mlv-zoom, .mlv-edge__hit, .mlv-legend, .mlv-statehost, .mlv-tooltip, .mlv-toasts, .mlv-farcap')) {
        return;
      }
      panning = true;
      lastX = ev.clientX;
      lastY = ev.clientY;
      downX = ev.clientX;
      downY = ev.clientY;
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
      if (Math.abs(ev.clientX - downX) + Math.abs(ev.clientY - downY) > PAN_CLICK_SLOP_PX) dragged = true;
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

  // Wheel: deltaMode-normalized, ctrl-branched, two-axis.
  disposers.push(wireWheel(canvas, viewport));

  disposers.push(on(canvas, 'keydown', (ev: KeyboardEvent) => handlers.onKeyDown(ev)));

  // ...and the same keys again when focus has fallen OFF the canvas onto a
  // container. Anything that steals focus and hands it back to <body> — a
  // clipboard fallback, a host dialog, a removed element — would otherwise
  // leave the whole canvas keymap dead until the user clicked the diagram
  // again, with a latched pulse that could not be dismissed. Only the three
  // CONTAINERS qualify (<body>, <html> and the app root), so no event from the
  // rail, the chrome, a dialog or a text field is ever taken twice or taken
  // at all.
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
      const wasDrag = dragged;
      dragged = false;
      if (wasDrag) return;
      const target = ev.target as HTMLElement;
      // A click in the phase index, the phase overview or the legend is not a click on
      // the diagram's background, so it keeps the selection.
      // Nor is a click on the cap of a far connection's line.
      if (!target.closest || !target.closest('.mlv-node, .mlv-edge__hit, .mlv-group, .mlv-phaseindex, .mlv-overview, .mlv-legend, .mlv-farcap')) handlers.onBackgroundClick();
    }),
  );

  if (typeof window !== 'undefined') {
    // Keep the derived chrome (zoom readout, the phase index's marks) in step with a
    // resized panel. The canvas view decides whether a fitted viewport refits;
    // nothing the reader moved is ever moved back.
    disposers.push(on(window, 'resize', () => (handlers.onResize ? handlers.onResize() : viewport.apply())));
  }

  disposers.push(() => pinch.clear());
  return disposers;
}
