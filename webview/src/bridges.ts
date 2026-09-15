/**
 * Host bridges (CONTRACTS section 8 + amendment A3).
 *
 * `vscode()` wraps acquireVsCodeApi() exactly once. `standalone()` implements
 * openLocation WITHOUT EVER NAVIGATING THE DOCUMENT (CONTRACTS 11.17), no-ops
 * requestRefresh / askAssistant, and reports capabilities that hide the buttons
 * those messages would drive.
 *
 * On that "without ever navigating". The report used to open a location by
 * building a hidden `<a href="vscode://file/...">` and clicking it. Inside a
 * SANDBOXED IFRAME — how the report is embedded on claude.ai, and how any chat,
 * notebook or docs host embeds it — that is a top-level navigation to a scheme
 * the sandbox forbids, so the browser REPLACES THE FRAME with its blocked-content
 * page: the whole diagram gone, "This content is blocked. Contact the site owner
 * to fix the issue.", no way back but a reload. The Issues rail's Go to button,
 * the Inspector's "Open file:line", the related-location links and every node /
 * edge click all went through it.
 *
 * So the page is never the thing that moves. `deepLinkPlan` decides between two
 * outcomes from two facts — am I embedded, am I local — and neither outcome can
 * navigate the document:
 *
 *   embedded? | local (file:)? | outcome
 *   ----------+----------------+----------------------------------------------
 *   yes       | either         | COPY: clipboard + a toast carrying an
 *   no        | no             | COPY: "Open in VS Code" anchor, target=_blank
 *   no        | yes            | LAUNCH: a transient SEPARATE browsing context
 *             |                | -> OS protocol handler, closed again, with the
 *             |                | copy + toast as the fallback
 *
 * The anchor in the copy toast is deliberate: a host that permits the protocol
 * still gets a one-click jump, and a sandbox WITHOUT `allow-popups` merely drops
 * the click on the floor — silently, into a new browsing context, leaving the
 * report exactly where it was. That is the whole difference from the old path.
 *
 * On that "SEPARATE" in the LAUNCH row (MLV-R3-WEB-H2). The launch used to go
 * through a hidden `<iframe src="vscode://...">` appended to this document. It
 * never moved the page — and it still killed the report: measured in Chrome 141
 * on macOS, ONE node click in a `file://` report left the document receiving NO
 * keydown at all, ever again. A capture listener on `document` recorded zero
 * events; `l`, `?`, `f`, `s`, `[`, `]`, `e`, the arrows and Escape were all
 * dead, and nothing brought them back: not removing the frame, not focusing the
 * canvas, not `window.focus()`, not clicking the background, not navigating the
 * frame to `about:blank` first. The cause is not the frame but the LAUNCH: the
 * same page with `location.href = 'vscode://…'` dies identically, while the
 * same frame pointed at an UNREGISTERED scheme (`zzqq://…`) does not die at all.
 * Handing the URL to the OS costs the launching browsing context its keyboard.
 *
 * So the launch is done in a context this report can afford to lose: a named,
 * transient window opened for the URL and closed again ~700 ms later. It is not
 * a navigation of this document (CONTRACTS 11.17 is untouched — the page stays
 * exactly where it is, the diagram is never replaced), it is detectable when a
 * host refuses it (`window.open` returns null, which the silent iframe could
 * never report), and the name means a run of "Go to" clicks reuses the one
 * context instead of stacking them.
 */

import { el, on } from './dom.js';
import { disableSnippet, disableToast } from './ui/suppress.js';
import { MIME, base64ToBytes, base64ToUtf8 } from './export/raster.js';
import { downloadBytes } from './export/download.js';
import type { Capabilities, HostBridge, HostToUi, ThemeKind, UiToHost, ViewState } from './types.js';

const STATE_KEY = 'mlview.viewState.v1';

let cachedVsCodeApi: any = null;

function acquireOnce(): any {
  if (cachedVsCodeApi) return cachedVsCodeApi;
  const g: any = typeof window !== 'undefined' ? (window as any) : {};
  if (typeof g.acquireVsCodeApi === 'function') {
    try {
      cachedVsCodeApi = g.acquireVsCodeApi();
    } catch (_e) {
      cachedVsCodeApi = null;
    }
  }
  return cachedVsCodeApi;
}

function detectVsCodeTheme(): ThemeKind {
  if (typeof document === 'undefined' || !document.body) return 'light';
  const cls = document.body.className || '';
  if (cls.indexOf('vscode-high-contrast') >= 0) return 'hc';
  if (cls.indexOf('vscode-dark') >= 0) return 'dark';
  return 'light';
}

function prefersDark(): boolean {
  try {
    return typeof window !== 'undefined' && !!window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  } catch (_e) {
    return false;
  }
}

function listenToWindow(cb: (msg: HostToUi) => void): () => void {
  if (typeof window === 'undefined') return () => undefined;
  const handler = (ev: MessageEvent) => {
    const data = ev && (ev as any).data;
    if (data && typeof data === 'object') cb(data as HostToUi);
  };
  window.addEventListener('message', handler as EventListener);
  return () => window.removeEventListener('message', handler as EventListener);
}

export function vscodeBridge(): HostBridge {
  const api = acquireOnce();
  const capabilities: Capabilities = {
    canOpenSource: true,
    canReanalyze: true,
    canExport: true,
    canAskAssistant: false,
  };
  return {
    host: 'vscode',
    theme: detectVsCodeTheme(),
    capabilities,
    post(msg: UiToHost) {
      if (api && typeof api.postMessage === 'function') api.postMessage(msg);
    },
    onMessage(cb) {
      return listenToWindow(cb);
    },
    saveState(state: ViewState) {
      if (api && typeof api.setState === 'function') api.setState(state);
    },
    loadState() {
      if (api && typeof api.getState === 'function') {
        const s = api.getState();
        return s && typeof s === 'object' ? (s as ViewState) : null;
      }
      return null;
    },
  };
}

export interface StandaloneOptions {
  theme?: 'auto' | ThemeKind;
  /** Extra sink for posted messages — used by the report's own bootstrap and by tests. */
  onPost?: (msg: UiToHost) => void;
}

export function standaloneBridge(opts?: StandaloneOptions): HostBridge {
  // The toast is this host's only report of an open-in-editor gesture, so the
  // host has to know which input raised the gesture before the gesture happens.
  watchInputModality();
  const wanted = (opts && opts.theme) || 'auto';
  const theme: ThemeKind = wanted === 'auto' ? (prefersDark() ? 'dark' : 'light') : wanted;
  const capabilities: Capabilities = {
    canOpenSource: true,
    canReanalyze: false,
    canExport: false,
    canAskAssistant: false,
  };
  return {
    host: 'standalone',
    theme,
    // Additive, host-side only: lets the app pre-select Auto in the theme switch
    // and keep following the OS. Not part of the frozen HostBridge shape.
    themePreference: wanted,
    capabilities,
    post(msg: UiToHost) {
      if (opts && typeof opts.onPost === 'function') {
        try {
          opts.onPost(msg);
        } catch (_e) {
          /* a broken sink must not break the viewer */
        }
      }
      if (msg.type === 'openLocation') openInEditor(msg.absFile, msg.file, msg.line, msg.col);
      else if (msg.type === 'copy') copyText(msg.text, 'Copied');
      // MLV-P10. This host has no workspace and cannot write `.mlview.toml`, so
      // the honest answer to "disable this rule" is the snippet that does it,
      // delivered through the copy toast the deep-link path already owns
      // (CONTRACTS 11.17.1) — never a claim that something was configured.
      else if (msg.type === 'suppressRule') copyText(disableSnippet(msg.code), disableToast(msg.code));
      // VIEW-07. This host has no save dialog, so the download IS the dialog.
      // Either field spelling is accepted (see the INTEROP NOTE in types.ts).
      else if (msg.type === 'exportFile') {
        saveExportedFile(msg.kind, msg.name || msg.suggestedName, msg.base64 || msg.data);
      }
    },
    onMessage(cb) {
      return listenToWindow(cb);
    },
    saveState(state: ViewState) {
      try {
        window.localStorage.setItem(STATE_KEY, JSON.stringify(state));
      } catch (_e) {
        /* private mode, or storage disabled */
      }
    },
    loadState() {
      try {
        const raw = window.localStorage.getItem(STATE_KEY);
        return raw ? (JSON.parse(raw) as ViewState) : null;
      } catch (_e) {
        return null;
      }
    },
  };
}

/** The two facts the decision turns on, plus the location being opened. */
export interface DeepLinkContext {
  /** True when this document is not the top-level one — any iframe. */
  embedded: boolean;
  /** True only for a `file:` document, the one context an OS handler can serve. */
  local: boolean;
  absFile: string;
  file: string;
  line: number;
  col: number;
}

export interface DeepLinkPlan {
  /** `launch` hands the URL to the OS; `copy` never leaves the page at all. */
  mode: 'copy' | 'launch';
  /**
   * vscode://file/<abs>:<line>:<col+1> — built either way, since the copy toast
   * still offers it as an anchor the reader may click.
   */
  url: string;
  /** What lands on the clipboard: `file:line`, the thing a human retypes. */
  copyText: string;
  toast: string;
}

/**
 * The absolute path, made safe to put in a URL (R3-DL-04).
 *
 * `#` and `?` are URL SYNTAX, and `encodeURI` deliberately leaves both alone —
 * so a project checked out under `C:/w/issue#1/` used to produce
 * `vscode://file/C:/w/issue#1/a.py:3:1`, which a handler reads as the file
 * `C:/w/issue` with `#1/a.py:3:1` as a fragment: the wrong file, with the line
 * and column gone. Nothing said so, because the clipboard text (`file:line`) was
 * still right and the anchor still read "Open in VS Code". Spaces and non-ASCII
 * are already handled by `encodeURI`. `:line:col` is appended AFTER the
 * encoding, so the two separators the URL needs stay literal.
 */
function encodePath(absFile: string): string {
  try {
    return encodeURI(absFile).replace(/#/g, '%23').replace(/\?/g, '%3F');
  } catch (_e) {
    // A lone surrogate throws in encodeURI; a broken link beats a thrown click.
    return absFile.replace(/#/g, '%23').replace(/\?/g, '%3F');
  }
}

/**
 * The whole decision, as a pure function of two booleans (CONTRACTS 11.17).
 *
 * It is exported and DOM-free on purpose: the branch that matters is the one
 * that only reproduces inside a cross-origin sandboxed iframe, which no unit
 * test can construct. Pinning the table here means the untestable environment
 * only has to supply two booleans correctly, and `openInEditor` only has to
 * execute a plan.
 */
export function deepLinkPlan(ctx: DeepLinkContext): DeepLinkPlan {
  const url = ctx.absFile ? 'vscode://file/' + encodePath(ctx.absFile) + ':' + ctx.line + ':' + (ctx.col + 1) : '';
  const ref = ctx.file + ':' + ctx.line;
  // Embedded, or served over http(s): an OS protocol handler is either
  // unreachable or unsafe to attempt, so the page does not try.
  if (ctx.embedded || !ctx.local) {
    return {
      mode: 'copy',
      url,
      copyText: ref,
      toast: 'Copied ' + ref + ' — open the report locally to jump into VS Code',
    };
  }
  return { mode: 'launch', url, copyText: ref, toast: 'Copied ' + ref };
}

/**
 * `window.self !== window.top` is the test, and a THROW is also an answer: only
 * a cross-origin embedding can make that comparison raise, so the catch reports
 * `embedded` rather than swallowing the one case the bug actually lives in.
 */
function isEmbedded(): boolean {
  try {
    if (typeof window === 'undefined') return false;
    return window.self !== window.top;
  } catch (_e) {
    return true;
  }
}

function isLocalDocument(): boolean {
  try {
    return typeof location !== 'undefined' && !!location && location.protocol === 'file:';
  } catch (_e) {
    return false;
  }
}

/**
 * The name of the one transient context a launch may own. Named rather than
 * `_blank`, so a run of "Go to" clicks REUSES it: the old frame sweep (R3-DL-03)
 * exists here as a property of the target name, plus the explicit close below.
 */
const LAUNCH_TARGET = 'mlview-deeplink';

/**
 * How long that context is kept. Long enough for the browser to commit the
 * navigation and hand the URL to the OS; short enough that it is gone before the
 * reader has looked at it.
 */
const LAUNCH_CLOSE_MS = 700;

/**
 * The old 400 ms blur probe, moved behind the close. The clipboard fallback
 * needs THIS document focused — `execCommand('copy')` fails in an unfocused one
 * — and the transient context holds focus until it is closed.
 */
const LAUNCH_FALLBACK_MS = LAUNCH_CLOSE_MS + 200;

let launchWindow: Window | null = null;
let launchTimer: any = null;

/** Close the transient context, if this report still owns one. */
function closeLaunchWindow(): void {
  if (launchTimer) {
    clearTimeout(launchTimer);
    launchTimer = null;
  }
  const win = launchWindow;
  launchWindow = null;
  if (!win) return;
  try {
    if (!win.closed) win.close();
  } catch (_e) {
    /* a context this document no longer owns closes itself, or stays */
  }
}

/**
 * Put focus back where the gesture started — never on `<body>` (11.17.1 D4).
 *
 * Only the ELEMENT is refocused. `window.focus()` is not called: a document
 * cannot reliably ask for the window back, the browser hands it to the opener
 * when the transient context closes, and in a host without it the call is noise
 * on the console — which library code does not make.
 */
function restoreLaunchFocus(previous: HTMLElement | null): void {
  if (!previous || !previous.isConnected || typeof previous.focus !== 'function') return;
  if (typeof document === 'undefined' || !document) return;
  // Only when focus was DROPPED. 700 ms is long enough for the reader to have
  // moved on — into the search box, into the rail — and a viewer that yanks
  // focus back out of what someone is typing in is worse than the thing this
  // repairs.
  const active = document.activeElement as HTMLElement | null;
  if (active && active !== document.body && active !== document.documentElement) return;
  try {
    previous.focus();
  } catch (_e) {
    /* the element may have been re-rendered while the launch stood */
  }
}

/**
 * Hand a URL to the OS protocol handler from a context that is NOT this one.
 *
 * Returns whether a context was actually created: a popup blocker, a host with
 * no `window.open`, or a refusal all report themselves here, which is the one
 * thing the hidden iframe could never do — it failed silently and left the
 * reader with nothing. This document is not navigated, not replaced and not
 * moved; it simply is not the context that spends its keyboard on the hand-off.
 */
function launchDeepLink(url: string): boolean {
  try {
    if (!url) return false;
    if (typeof window === 'undefined' || typeof window.open !== 'function') return false;
    const previous =
      typeof document !== 'undefined' && document ? (document.activeElement as HTMLElement | null) : null;
    closeLaunchWindow();
    const win = window.open(url, LAUNCH_TARGET);
    if (!win) return false;
    launchWindow = win;
    launchTimer = setTimeout(() => {
      launchTimer = null;
      closeLaunchWindow();
      restoreLaunchFocus(previous);
    }, LAUNCH_CLOSE_MS);
    return true;
  } catch (_e) {
    return false;
  }
}

/**
 * Open a location. The document is NEVER navigated (CONTRACTS 11.17): there is
 * no `anchor.click()` on a same-frame link and no `location.href` assignment
 * anywhere on this path — and since MLV-R3-WEB-H2, no browsing context inside
 * this document either.
 */
function openInEditor(absFile: string, file: string, line: number, col: number): void {
  const plan = deepLinkPlan({ embedded: isEmbedded(), local: isLocalDocument(), absFile, file, line, col });
  if (plan.mode === 'copy') {
    copyText(plan.copyText, plan.toast, plan.url);
    return;
  }
  // Top-level AND file:. Try the OS, and keep the existing blur-based detection:
  // if focus never left the page nothing handled the URL, so fall back to the
  // clipboard exactly as before.
  let blurred = false;
  const onBlur = () => {
    blurred = true;
  };
  if (typeof window !== 'undefined') window.addEventListener('blur', onBlur, { once: true });
  if (!launchDeepLink(plan.url)) {
    // Refused — and refusals are now visible. Say so at once, and keep the
    // anchor: it is the only way left from here to the editor.
    if (typeof window !== 'undefined') window.removeEventListener('blur', onBlur);
    copyText(plan.copyText, plan.toast, plan.url);
    return;
  }
  setTimeout(() => {
    if (typeof window !== 'undefined') window.removeEventListener('blur', onBlur);
    if (blurred) return;
    copyText(plan.copyText, plan.toast);
  }, LAUNCH_FALLBACK_MS);
}

/**
 * Save an exported diagram from the standalone report (VIEW-07).
 *
 * An object URL plus `<a download>` — which is NOT a document navigation and so
 * is not the thing CONTRACTS 11.17 forbids: the anchor carries `download`, its
 * href is a `blob:` of bytes this page just produced, and a host that refuses
 * the download (a sandbox without `allow-downloads`) drops the click without
 * touching the frame. The report is never the thing that moves, exactly as on
 * the deep-link path.
 *
 * Every failure has an answer rather than a silence: an SVG lands on the
 * clipboard through the toast 11.17.1 already owns, and a PNG — which no
 * clipboard takes as text — says so.
 */
function saveExportedFile(kind: 'svg' | 'png', name: string, base64: string): void {
  const mime = kind === 'png' ? MIME.png : MIME.svg + ';charset=utf-8';
  if (downloadBytes(base64ToBytes(base64), name, mime)) return;
  // No download machinery, or a sandbox that refused it. Say so, and for an SVG
  // hand the bytes to the clipboard the deep-link path already owns (11.17.1).
  if (kind === 'svg') copyText(base64ToUtf8(base64), 'Could not download ' + name + ' — the SVG is on your clipboard');
  else showFloatingToast('Could not download ' + name + ' here — use Copy PNG instead.');
}

/**
 * The textarea + execCommand fallback. Returns whether the copy actually
 * happened, so the toast can tell the truth.
 */
function legacyCopy(text: string): boolean {
  try {
    if (typeof document === 'undefined' || !document.body) return false;
    // `select()` steals focus, and removing the textarea drops it on <body> —
    // which silently killed the canvas keymap for the rest of the session
    // (MLV-R1-FLOW-007). Whoever had focus gets it back.
    const previous = document.activeElement as HTMLElement | null;
    const area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', 'true');
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    const ok = !!(document as any).execCommand && (document as any).execCommand('copy') === true;
    document.body.removeChild(area);
    if (previous && previous !== document.body && typeof previous.focus === 'function') {
      try {
        previous.focus();
      } catch (_e) {
        /* the element may have been removed while the copy ran */
      }
    }
    return ok;
  } catch (_e) {
    return false;
  }
}

/**
 * Copy `text`, then report honestly (MLV-R1-007).
 *
 * `navigator.clipboard.writeText` returns a promise. It used to be fired and
 * dropped, with `done = true` set synchronously: on a file:// report the write
 * is denied, so every node click produced an unhandled rejection in the console,
 * skipped the fallback, and still claimed "Copied train.py:44". The toast is now
 * strictly downstream of a confirmed copy.
 */
function copyText(text: string, toast: string, deepLink?: string): void {
  // Put the live region up NOW, while the gesture is still running. A screen
  // reader announces a region that was already there and then changed; a
  // `role="status"` node that appears with its text already in it is announced
  // by some AT and missed by others, and the clipboard write below resolves in a
  // later task, so this costs one statement and buys the reliable case.
  toastHost();
  const nav: any = typeof navigator !== 'undefined' ? navigator : null;
  let promise: any = null;
  try {
    if (nav && nav.clipboard && typeof nav.clipboard.writeText === 'function') {
      promise = nav.clipboard.writeText(text);
    }
  } catch (_e) {
    promise = null;
  }
  if (promise && typeof promise.then === 'function') {
    promise.then(
      () => showFloatingToast(toast, deepLink),
      () => showFloatingToast(legacyCopy(text) ? toast : 'Copy blocked — ' + text, deepLink),
    );
    return;
  }
  showFloatingToast(promise !== null || legacyCopy(text) ? toast : 'Copy blocked — ' + text, deepLink);
}

/* ── the floating toast (CONTRACTS 11.17.1) ───────────────────────────────
 *
 * Since 11.17 this toast is not a rare fallback: in every embedded or http(s)
 * report it IS the whole outcome of "Go to" / "Open file:line" / a node click,
 * and its anchor is the only affordance left. It had no `role` and no live
 * region, so a screen-reader user got NOTHING from the gesture — the app's own
 * announcer was byte-identical before and after — and a keyboard user was 17 Tab
 * presses away from a control that expired in 3000 ms. Hence: a PERSISTENT
 * `role="status"` host created before the message lands (so the text is a
 * live-region MUTATION, not a node that appears already containing it), exactly
 * ONE card inside it, a timer that holds while the pointer or focus is on it,
 * and focus on the anchor when the keyboard raised it. None of it can live in
 * `.mlv-toasts`: that stack is `pointer-events: none`, which would make the link
 * unclickable. `aria-live` is left off so the app's announcer stays the only
 * `[aria-live]` element, exactly as `ui/states.ts` does (MLV-R2-W10).
 */

const TOAST_MS = 3000;

let toastHostEl: HTMLElement | null = null;
let currentToast: HTMLElement | null = null;
let toastTimer: any = null;
let focusBeforeToast: HTMLElement | null = null;
/** When an ACTIVATION key and a pointer were last seen, in ms since epoch. */
let lastActivationKeyAt = 0;
let lastPointerAt = 0;
let modalityBound = false;
/** How recent an activation key has to be to still own the gesture. */
const GESTURE_MS = 1000;

/**
 * Which input raised the current gesture, tracked in the CAPTURE phase so it is
 * settled before any click handler runs. Only `Enter` and `Space` count, because
 * only those two turn into an activation, and only for `GESTURE_MS`. It decides
 * one thing: whether the toast's anchor takes focus. Moving focus at a mouse user
 * is unasked for; leaving a keyboard user 17 Tab presses from the only affordance
 * their gesture produced, inside a 3000 ms window, is worse.
 */
function watchInputModality(): void {
  if (modalityBound || typeof document === 'undefined' || typeof document.addEventListener !== 'function') return;
  modalityBound = true;
  on(
    document,
    'keydown',
    (ev: KeyboardEvent) => {
      const k = ev && ev.key;
      if (k === 'Enter' || k === ' ' || k === 'Spacebar') lastActivationKeyAt = Date.now();
    },
    true,
  );
  const pointer = () => {
    lastPointerAt = Date.now();
  };
  on(document, 'pointerdown', pointer, true);
  on(document, 'mousedown', pointer, true);
}

/** True while an activation keystroke, not a pointer, owns the current gesture. */
function keyboardGesture(): boolean {
  return lastActivationKeyAt > lastPointerAt && Date.now() - lastActivationKeyAt <= GESTURE_MS;
}

/**
 * The live region, created once and kept.
 *
 * Mounted INSIDE `.mlv-root` when there is one. The theme is stamped there
 * (`data-theme` on the mounted element, tokens.css), so a toast parked on
 * `<body>` reads the page-level token set instead: with an explicit Dark choice
 * on a light OS it would be a light card in a dark app, inheriting neither the
 * font stack nor `--mlv-text`. The FIXED positioning moved from the card to this
 * host, so the card looks the same and the host can be created early without
 * anything appearing — it is empty, and an empty flex column has no size.
 */
function toastHost(): HTMLElement | null {
  if (typeof document === 'undefined' || !document.body) return null;
  let host = toastHostEl;
  if (!host || !host.isConnected) {
    host = el('div', 'mlv-toasts--floating');
    host.setAttribute('role', 'status');
    host.style.position = 'fixed';
    host.style.left = '50%';
    host.style.bottom = '24px';
    host.style.transform = 'translateX(-50%)';
    host.style.zIndex = '9999';
    host.style.display = 'flex';
    host.style.flexDirection = 'column';
    host.style.alignItems = 'center';
    toastHostEl = host;
    currentToast = null;
  }
  const parent = document.querySelector('.mlv-root') || document.body;
  // Re-parent only when the app mounted after the host was created; moving a
  // live region for no reason can cost an announcement.
  if (host.parentNode !== parent) parent.appendChild(host);
  return host;
}

function holdToast(): void {
  if (toastTimer) {
    clearTimeout(toastTimer);
    toastTimer = null;
  }
}

function armToastTimer(): void {
  holdToast();
  toastTimer = setTimeout(() => {
    toastTimer = null;
    dismissToast();
  }, TOAST_MS);
}

/** Take the card down — and never leave focus on `<body>` (MLV-R1-FLOW-007). */
function dismissToast(): void {
  holdToast();
  const toast = currentToast;
  currentToast = null;
  if (!toast) return;
  const doc = toast.ownerDocument;
  const active = doc ? (doc.activeElement as HTMLElement | null) : null;
  const held = !!active && toast.contains(active);
  if (toast.parentNode) toast.parentNode.removeChild(toast);
  const back = focusBeforeToast;
  focusBeforeToast = null;
  if (held && back && back.isConnected && typeof back.focus === 'function') {
    try {
      back.focus();
    } catch (_e) {
      /* the element may have been re-rendered while the toast stood */
    }
  }
}

/**
 * The message, plus — when a deep link came with it — the one affordance that
 * can still reach VS Code from a page that must not navigate itself.
 *
 * `target="_blank"` is what makes it safe: the click opens a NEW browsing
 * context, so a host that allows the protocol launches the editor and a sandbox
 * that does not simply drops the click. Either way this document stays put,
 * which is the entire point of CONTRACTS 11.17. `rel="noopener noreferrer"` is
 * the usual hygiene for a `_blank` link.
 */
function showFloatingToast(text: string, deepLink?: string): void {
  const host = toastHost();
  if (!host) return;
  dismissToast();
  const toast = el('div', 'mlv-toast mlv-toast--floating', text);
  let link: HTMLAnchorElement | null = null;
  if (deepLink) {
    link = el('a', 'mlv-toast__link', 'Open in VS Code');
    link.href = deepLink;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    toast.appendChild(link);
  }
  host.appendChild(toast);
  currentToast = toast;
  // A control that expires under the cursor on its way to it is not a control.
  on(toast, 'mouseenter', holdToast);
  on(toast, 'focusin', holdToast);
  on(toast, 'mouseleave', armToastTimer);
  on(toast, 'focusout', armToastTimer);
  armToastTimer();
  if (link && keyboardGesture()) {
    const doc = toast.ownerDocument;
    focusBeforeToast = doc ? (doc.activeElement as HTMLElement | null) : null;
    try {
      link.focus();
    } catch (_e) {
      /* a host that cannot focus it still leaves it announced and clickable */
    }
  }
}

export type ThemeChoice = 'auto' | ThemeKind;

const THEME_LABEL: Record<string, string> = {
  auto: 'Auto',
  light: 'Light',
  dark: 'Dark',
  hc: 'High contrast',
};

/**
 * Standalone-only Auto / Light / Dark / High contrast switch (UX_DESIGN §3).
 * Mounted by App.build() when `bridge.host === 'standalone'`.
 */
export function buildThemeSwitch(current: ThemeChoice, onPick: (t: ThemeChoice) => void): HTMLElement {
  const wrap = el('div', 'mlv-themeswitch');
  wrap.setAttribute('role', 'group');
  wrap.setAttribute('aria-label', 'Colour theme');
  const options: ThemeChoice[] = ['auto', 'light', 'dark', 'hc'];
  for (const option of options) {
    const b = el('button', 'mlv-chip mlv-chip--btn', THEME_LABEL[option]) as HTMLButtonElement;
    b.type = 'button';
    b.setAttribute('data-theme-option', option);
    b.title = THEME_LABEL[option] + ' theme';
    b.setAttribute('aria-pressed', option === current ? 'true' : 'false');
    on(b, 'click', () => {
      for (const other of Array.from(wrap.children)) other.setAttribute('aria-pressed', 'false');
      b.setAttribute('aria-pressed', 'true');
      onPick(option);
    });
    wrap.appendChild(b);
  }
  return wrap;
}
