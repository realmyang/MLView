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
 *   no        | yes            | LAUNCH: hidden iframe -> OS protocol handler,
 *             |                | with the copy + toast as the 400 ms fallback
 *
 * The anchor in the copy toast is deliberate: a host that permits the protocol
 * still gets a one-click jump, and a sandbox WITHOUT `allow-popups` merely drops
 * the click on the floor — silently, into a new browsing context, leaving the
 * report exactly where it was. That is the whole difference from the old path.
 */

import { el, on } from './dom.js';
import { disableSnippet, disableToast } from './ui/suppress.js';
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
 * Hand a URL to the OS protocol handler through a hidden iframe.
 *
 * A child frame's navigation to an external scheme invokes the handler exactly
 * as a top-level one does, but anything that goes wrong replaces a 0x0 element
 * that is removed a moment later — the report itself is never the thing that
 * moves. This is the ONLY place the deep link is navigated to at all, and it is
 * reached only when the document is top-level AND local.
 */
function launchDeepLink(url: string): void {
  try {
    if (!url) return;
    if (typeof document === 'undefined' || !document.body) return;
    // The removal timeout below never prevented ACCUMULATION, whatever its
    // comment used to claim: six "Go to" clicks inside 1500 ms left six frames
    // attached — six simultaneous OS protocol invocations, i.e. six "Open Visual
    // Studio Code?" prompts (R3-DL-03). One at a time, newest wins.
    const stale = document.querySelectorAll('iframe.mlv-deeplink');
    for (let i = 0; i < stale.length; i++) {
      const old = stale[i];
      if (old.parentNode) old.parentNode.removeChild(old);
    }
    const frame = document.createElement('iframe');
    frame.className = 'mlv-deeplink';
    frame.hidden = true;
    frame.setAttribute('aria-hidden', 'true');
    frame.setAttribute('tabindex', '-1');
    frame.setAttribute('title', 'Opening in VS Code');
    frame.style.position = 'fixed';
    frame.style.width = '0';
    frame.style.height = '0';
    frame.style.border = '0';
    frame.style.opacity = '0';
    frame.src = url;
    document.body.appendChild(frame);
    // Long enough for the handler to be invoked. A rapid sequence of "Go to"
    // clicks is handled by the sweep above, not by this delay.
    setTimeout(() => {
      if (frame.parentNode) frame.parentNode.removeChild(frame);
    }, 1500);
  } catch (_e) {
    /* the OS hand-off is best effort; the 400 ms fallback still copies */
  }
}

/**
 * Open a location. The document is NEVER navigated (CONTRACTS 11.17): there is
 * no `anchor.click()` on a same-frame link and no `location.href` assignment
 * anywhere on this path.
 */
function openInEditor(absFile: string, file: string, line: number, col: number): void {
  const plan = deepLinkPlan({ embedded: isEmbedded(), local: isLocalDocument(), absFile, file, line, col });
  if (plan.mode === 'copy') {
    copyText(plan.copyText, plan.toast, plan.url);
    return;
  }
  // Top-level AND file:. Try the OS, and keep the existing blur-based detection:
  // if focus never left the page within 400 ms nothing handled the URL, so fall
  // back to the clipboard exactly as before.
  let blurred = false;
  const onBlur = () => {
    blurred = true;
  };
  if (typeof window !== 'undefined') window.addEventListener('blur', onBlur, { once: true });
  launchDeepLink(plan.url);
  setTimeout(() => {
    if (typeof window !== 'undefined') window.removeEventListener('blur', onBlur);
    if (blurred) return;
    copyText(plan.copyText, plan.toast);
  }, 400);
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
