/**
 * The keyboard model — the single source of truth (UX_DESIGN section 9, R4.6).
 *
 * `KEYMAP` is also the data the `?` shortcut sheet renders, so the documented
 * bindings and the implemented ones cannot drift apart.
 *
 * Tab and Shift+Tab are deliberately NOT bound. They used to cycle issues and
 * called preventDefault(), which turned the `tabindex="0"` canvas into a
 * keyboard trap — a WCAG 2.1.2 failure with no way out but Escape (MLV-R1-005).
 * Issue cycling lives on `n` / `p`, as the spec always said.
 */

export interface KeyCommands {
  focusSearch(): void;
  /** The Escape cascade; false when nothing was left to dismiss, so the key is not consumed. */
  escape(): boolean;
  cycleIssue(backwards: boolean): boolean;
  zoom(direction: number): void;
  /** `0`: the readable view (viewer M2), the first paint again. */
  fit(): void;
  toggleFocusMode(): void;
  zoomToSelection(): void;
  /**
   * `Shift+0` (viewer M3): open the phase overview, every phase as a block of its step titles, or
   * close it. It used to fold every group and fit the whole diagram; the whole diagram is the ...
   * menu's "Fit the whole diagram", and a group folds with its own chevron (or Space).
   */
  overview(): void;
  /** `l`: show or hide the legend. */
  toggleLegend(): void;
  /** `a`: turn the connection-flow animation on or off. */
  toggleFlow(): void;
  /**
   * `Shift+A` (viewer M2): play the flow on screen again. A flow stops after two passes; false
   * when nothing is lit, the layer is off, or motion is reduced.
   */
  replayFlow(): boolean;
  toggleCollapse(): boolean;
  /** Enter: open beside the panel, focus kept; Alt+Enter (`focusEditor`): open and move focus there. */
  openSelection(focusEditor: boolean): boolean;
  move(key: string): void;
  /** 0 = high, 1 = medium, 2 = low. */
  toggleSeverity(index: number): void;
  /** `b` (viewer M2 live fix; it was Ctrl+B): show or hide the side panel, open or collapse the bottom one. */
  toggleRail(): void;
  /**
   * `t` (viewer M2 live fix; it replaced Ctrl+1 to Ctrl+4): move the focus to the panel's current
   * tab, opening the panel first; the tab strip's arrow keys then pick a tab.
   */
  focusRailTabs(): void;
  toggleShortcuts(): void;
  /** `e` / `Shift+E`: walk the selection's connections. */
  cycleConnections(backwards: boolean): boolean;
  /** Viewer M3: the review walk is running (j, k, ↓, ↑, [ and ] answer only then). */
  walking(): boolean;
  /** Viewer M3, `r`: start the review walk where it was left in this revision, or end it. */
  review(): void;
  /** Viewer M3, while walking: j / ↓ (+1) and k / ↑ (-1) step through the claims. */
  walkStep(delta: number): boolean;
  /** Viewer M3, while walking: `]` (+1) and `[` (-1) step through the claim's quotes. */
  walkQuote(delta: number): boolean;
  /** Viewer M3, `u` / `Shift+U`: start the walk on the claims not observed, or step through them. */
  walkNotObserved(backwards: boolean): boolean;
}

export interface KeyBinding {
  keys: string[];
  action: string;
  description: string;
}

export const KEYMAP: KeyBinding[] = [
  // Viewer M2: the find key too, from anywhere in the viewer (app.ts), since the webview has no find
  // bar. `Mod+F` is printed Cmd+F (⌘F) on macOS and Ctrl+F elsewhere (ui/platform.ts). Viewer M2
  // live fix: Ctrl/Cmd+K is gone; the workbench reads Cmd+K (macOS) and Ctrl+K as a chord prefix.
  { keys: ['Mod+F', '/'], action: 'focusSearch', description: 'Search steps, findings, IDs, or cited text' },
  { keys: ['n', 'p'], action: 'cycleIssue', description: 'Next / previous finding (document order); in the review walk, in the walk\'s order' },
  // Viewer M1: a click selects and shows the claim; opening the source is Enter (or a double-click).
  { keys: ['Enter'], action: 'open', description: 'Open the cited source beside the diagram; focus stays here (in the review walk: open the current quote again)' },
  { keys: ['Alt+Enter'], action: 'openFocus', description: 'Open the cited source and move focus to the editor' },
  { keys: ['Space'], action: 'collapse', description: 'Collapse or expand the selected group' },
  { keys: ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'], action: 'move', description: 'Move the selection (in the review walk, ↓ and ↑ step through the claims)' },
  // Viewer M3: the review walk. Plain keys only (the M2 key rule): VS Code leaves them to a focused
  // webview. `[` and `]` were the scope keys until viewer M2 removed scoping.
  { keys: ['r'], action: 'review', description: 'Review walk: go claim by claim, each opened and highlighted in the editor beside (starts on the claims not observed; r again or Escape ends it)' },
  { keys: ['j', 'k'], action: 'walkStep', description: 'In the review walk: next / previous claim' },
  { keys: ['[', ']'], action: 'walkQuote', description: 'In the review walk: previous / next quote of the claim' },
  { keys: ['u', 'Shift+U'], action: 'walkNotObserved', description: 'Review walk on the claims not observed: start it, then next / previous one' },
  // Viewer M2: key 0 is the readable first view; the whole document is the ... menu's "Fit the
  // whole diagram". Viewer M3: Shift+0 is the phase overview (it used to fold every group and fit).
  { keys: ['0'], action: 'fit', description: 'Readable view: the whole diagram if it fits at reading size, otherwise phase 1' },
  { keys: ['Shift+0'], action: 'overview', description: 'Phase overview: every phase as a block of its step titles; arrows move between phases, Enter goes to one, Escape comes back' },
  { keys: ['+', '='], action: 'zoomIn', description: 'Zoom in' },
  { keys: ['-', '_'], action: 'zoomOut', description: 'Zoom out' },
  { keys: ['z'], action: 'zoomToSelection', description: 'Zoom to the selection' },
  // Hovering a card lights only its direct connections; the sheet is where a
  // reader learns that `f` shows the whole lineage.
  { keys: ['f'], action: 'focusMode', description: 'Focus mode: light the full lineage of the selection' },
  { keys: ['l'], action: 'legend', description: 'Show or hide the legend' },
  { keys: ['a'], action: 'flow', description: 'Turn the connection flow animation on or off' },
  // Viewer M2: a flow stops after two passes, so nothing moves while you read.
  { keys: ['Shift+A'], action: 'replayFlow', description: 'Play the connection flow again (it stops after two passes)' },
  { keys: ['e', 'Shift+E'], action: 'cycleConnections', description: 'Next / previous connection of the selected step' },
  { keys: ['1', '2', '3'], action: 'toggleSeverity', description: 'Toggle the high / medium / low filters' },
  // Viewer M2 live fix: plain keys. Ctrl/Cmd+B also toggled the workbench's side bar, Cmd+1 to Cmd+4
  // (Ctrl on Windows and Linux) focus editor groups, and Ctrl+1 to Ctrl+4 on macOS (Alt elsewhere)
  // bring the group's Nth tab to the front, hiding the diagram.
  { keys: ['b'], action: 'toggleRail', description: 'Show or hide the side panel; open or collapse the bottom panel' },
  { keys: ['t'], action: 'railTab', description: 'Go to the panel tabs, About / Findings / Selection / Outline (opens the panel); ← and → pick a tab' },
  { keys: ['?'], action: 'shortcuts', description: 'Show this shortcut sheet' },
  // The rungs, in the order `dismissTopmost` runs them (CONTRACTS 11.13). The
  // sheet is the only place the cascade is described to the user (MLV-R1-F2-06).
  { keys: ['Escape'], action: 'escape', description: 'Close the menu, this sheet, the Refine popover, the phase list or the legend, leave the phase overview, end the review walk, collapse the bottom panel, exit focus mode, clear the selection, leave the canvas' },
  { keys: ['Tab', 'Shift+Tab'], action: 'browser', description: 'Move focus out of the diagram (never intercepted)' },
];

/** Route one keydown on the canvas. Returns true when the event was consumed. */
export function handleCanvasKey(ev: KeyboardEvent, cmd: KeyCommands): boolean {
  const key = ev.key;
  const mod = ev.ctrlKey || ev.metaKey;
  const consume = () => {
    ev.preventDefault();
    return true;
  };

  // Tab must always reach the browser's focus manager: the canvas is focusable,
  // so swallowing it strands keyboard users inside the diagram.
  if (key === 'Tab') return false;

  // Viewer M2 live fix: the find key is the only chord the canvas answers. Every other Ctrl or Cmd
  // chord is left alone, unconsumed, for the workbench (ui/platform.ts says why).
  if (mod) {
    if (key === 'f' || key === 'F') {
      cmd.focusSearch();
      return consume();
    }
    return false;
  }

  // Alt+Enter is the one Alt chord the canvas answers (viewer M1). VS Code binds Alt+Enter only
  // in the editor find widget, notebooks, chat input, the search and testing views and terminal
  // chat, never in a focused webview panel.
  if (ev.altKey && key === 'Enter' && !ev.shiftKey) {
    if (!cmd.openSelection(true)) return false;
    return consume();
  }

  if (ev.altKey) return false;

  if (key === '/') {
    cmd.focusSearch();
    return consume();
  }
  if (key === '?') {
    cmd.toggleShortcuts();
    return consume();
  }
  // Viewer M3: an Escape that dismissed nothing (the focus is already off the canvas and nothing is
  // open or selected) is left unconsumed, so VS Code can use it, for example to hide a notification.
  // An Escape the cascade used is consumed, and the panel's bootstrap then keeps VS Code from also
  // acting on it.
  if (key === 'Escape') {
    if (!cmd.escape()) return false;
    return consume();
  }
  // Viewer M3: the review walk. `r` starts or ends it; `u` / Shift+U start it on the claims not
  // observed or step through them (branch on shiftKey: Caps Lock sends 'U' for a plain u). While it
  // runs, j / k and ↓ / ↑ step and [ / ] change the quote; outside it those keys keep their meaning
  // (the arrows move spatially) or are left unconsumed.
  if (key === 'r' || key === 'R') {
    cmd.review();
    return consume();
  }
  if (key === 'u' || key === 'U') {
    if (!cmd.walkNotObserved(ev.shiftKey)) return false;
    return consume();
  }
  if (cmd.walking()) {
    const step = key === 'j' || key === 'J' || key === 'ArrowDown' ? 1 : key === 'k' || key === 'K' || key === 'ArrowUp' ? -1 : 0;
    if (step) {
      if (!cmd.walkStep(step)) return false;
      return consume();
    }
    if (key === '[' || key === ']') {
      if (!cmd.walkQuote(key === ']' ? 1 : -1)) return false;
      return consume();
    }
  }
  if (key === 'n' || key === 'N' || key === 'p' || key === 'P') {
    if (!cmd.cycleIssue(key === 'p' || key === 'P')) return false;
    return consume();
  }
  if (key === '+' || key === '=') {
    cmd.zoom(1);
    return consume();
  }
  if (key === '-' || key === '_') {
    cmd.zoom(-1);
    return consume();
  }
  // Shift+0 arrives as ')' on a US layout and as '0' with `shiftKey` elsewhere;
  // both mean the phase overview, and the plain `0` below must not swallow either.
  if (key === ')' || (key === '0' && ev.shiftKey)) {
    cmd.overview();
    return consume();
  }
  if (key === '0') {
    cmd.fit();
    return consume();
  }
  if (key === '1' || key === '2' || key === '3') {
    cmd.toggleSeverity(Number(key) - 1);
    return consume();
  }
  if (key === 'f' || key === 'F') {
    cmd.toggleFocusMode();
    return consume();
  }
  if (key === 'l' || key === 'L') {
    cmd.toggleLegend();
    return consume();
  }
  // Viewer M2: `a` turns the flow on or off; Shift+A plays it again. Branch on shiftKey
  // explicitly: with Caps Lock on, a plain `a` arrives as 'A'.
  if (key === 'a' || key === 'A') {
    if (ev.shiftKey) {
      if (!cmd.replayFlow()) return false;
      return consume();
    }
    cmd.toggleFlow();
    return consume();
  }
  // `f`/`p` fold case above, so this pair must branch on shiftKey EXPLICITLY or
  // Shift+E would be indistinguishable from `e` (CONTRACTS 11.13).
  if (key === 'e' || key === 'E') {
    if (!cmd.cycleConnections(ev.shiftKey)) return false;
    return consume();
  }
  if (key === 'z' || key === 'Z') {
    cmd.zoomToSelection();
    return consume();
  }
  if (key === 'b' || key === 'B') {
    cmd.toggleRail();
    return consume();
  }
  if (key === 't' || key === 'T') {
    cmd.focusRailTabs();
    return consume();
  }
  if (key === ' ') {
    if (!cmd.toggleCollapse()) return false;
    return consume();
  }
  if (key === 'Enter') {
    if (!cmd.openSelection(false)) return false;
    return consume();
  }
  if (key.indexOf('Arrow') === 0) {
    cmd.move(key);
    return consume();
  }
  return false;
}
