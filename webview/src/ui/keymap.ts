/**
 * The keyboard model — the single source of truth.
 *
 * `KEYMAP` is also the data the `?` shortcut sheet renders and tools/keys-table.mjs
 * prints, so the sheet always shows the key map; `handleCanvasKey` below must answer
 * the same keys.
 *
 * Tab and Shift+Tab are deliberately NOT bound. A preventDefault() on Tab would turn
 * the `tabindex="0"` canvas into a keyboard trap — a WCAG 2.1.2 failure with no way
 * out but Escape. Findings are cycled with `n` / `p` (`cycleIssue`).
 */

export interface KeyCommands {
  focusSearch(): void;
  /** The Escape cascade; false when nothing was left to dismiss, so the key is not consumed. */
  escape(): boolean;
  cycleIssue(backwards: boolean): boolean;
  zoom(direction: number): void;
  /** `0`: the readable view, the first paint again. */
  fit(): void;
  toggleFocusMode(): void;
  zoomToSelection(): void;
  /**
   * `Shift+0`: open the phase overview, every phase as a block of its step titles, or
   * close it. The whole diagram is the ... menu's "Fit the whole diagram", and a group folds with
   * its own chevron (or Space).
   */
  overview(): void;
  /** `l`: show or hide the legend. */
  toggleLegend(): void;
  /** `a`: turn the connection-flow animation on or off. */
  toggleFlow(): void;
  /**
   * `Shift+A`: play the flow on screen again. A flow stops after two passes; false
   * when nothing is lit, the layer is off, or motion is reduced.
   */
  replayFlow(): boolean;
  toggleCollapse(): boolean;
  /** Enter: open beside the panel, focus kept; Alt+Enter (`focusEditor`): open and move focus there. */
  openSelection(focusEditor: boolean): boolean;
  move(key: string): void;
  /** 0 = high, 1 = medium, 2 = low. */
  toggleSeverity(index: number): void;
  /** `b`: show or hide the side panel, open or collapse the bottom one. */
  toggleRail(): void;
  /**
   * `t`: move the focus to the panel's current tab, opening the panel first; the tab strip's
   * arrow keys then pick a tab.
   */
  focusRailTabs(): void;
  toggleShortcuts(): void;
  /** `e` / `Shift+E`: walk the selection's connections. */
  cycleConnections(backwards: boolean): boolean;
  /**
   * The review walk is running: only then do j, k, [, ] and o answer, and ↓ and ↑ step through
   * the claims.
   */
  walking(): boolean;
  /** `r`: start the review walk where it was left in this revision, or end it. */
  review(): void;
  /** While walking: j / ↓ (+1) and k / ↑ (-1) step through the claims. */
  walkStep(delta: number): boolean;
  /** While walking: `]` (+1) and `[` (-1) step through the claim's quotes. */
  walkQuote(delta: number): boolean;
  /** `u` / `Shift+U`: start the walk on the claims not observed, or step through them. */
  walkNotObserved(backwards: boolean): boolean;
  /**
   * `o` while walking: on a connection whose other end card is out of view, show both ends when
   * they fit the canvas together, else go to that end; again, come back. The walk stays on the
   * connection. False when it is not on one.
   */
  walkOtherEnd(): boolean;
}

export interface KeyBinding {
  keys: string[];
  action: string;
  description: string;
}

export const KEYMAP: KeyBinding[] = [
  // The find key too, from anywhere in the viewer but a modal surface (app.ts), since the webview
  // has no find bar. `Mod+F` is printed ⌘F on macOS and Ctrl+F elsewhere (ui/platform.ts); either
  // modifier works on every platform.
  // Ctrl/Cmd+K is left to the workbench.
  { keys: ['Mod+F', '/'], action: 'focusSearch', description: 'Search steps, findings, IDs, or cited text' },
  { keys: ['n', 'p'], action: 'cycleIssue', description: 'Next / previous finding (document order); in the review walk, in the walk\'s order' },
  // A click selects and shows the claim; opening the source is Enter (or a double-click).
  { keys: ['Enter'], action: 'open', description: 'Open the cited source beside the diagram; focus stays here (in the review walk: open the current quote again)' },
  { keys: ['Alt+Enter'], action: 'openFocus', description: 'Open the cited source and move focus to the editor' },
  { keys: ['Space'], action: 'collapse', description: 'Collapse or expand the selected group' },
  // From the walk's connection, ← or → towards an end out of view looks at it and keeps the
  // claim; towards an end in view it selects that end, or says which end it is (`WalkFar.arrow`).
  // After a move to a phase, and before any selection, the next arrow that reaches `move` selects
  // that phase's first step instead, when it has one (app/keys.ts).
  { keys: ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'], action: 'move', description: 'Move the selection (from a connection, to its end that lies that way; in the review walk, ↓ and ↑ step through the claims, and from the connection the walk is on, ← and → show the end that lies that way if it is out of view, while the walk stays on the connection; if that end is in view, the selection moves to it or stays)' },
  // The review walk. No Ctrl, Cmd or Alt chords (ui/platform.ts says why).
  { keys: ['r'], action: 'review', description: 'Review walk: go claim by claim, each opened and highlighted in the editor beside (starts on the claims not observed; r again or Escape ends it)' },
  { keys: ['j', 'k'], action: 'walkStep', description: 'In the review walk: next / previous claim' },
  { keys: ['[', ']'], action: 'walkQuote', description: 'In the review walk: previous / next quote of the claim' },
  { keys: ['u', 'Shift+U'], action: 'walkNotObserved', description: 'Review walk on the claims not observed: start it, then next / previous one' },
  // As `o` does in an editor's visual selection: the other end of what is selected.
  { keys: ['o'], action: 'walkOtherEnd', description: 'In the review walk, on a connection whose other end is out of view: show both ends if they fit the diagram together; if not, go to that end, and o again comes back (the walk stays on the connection)' },
  // Key 0 is the readable first view; the whole document is the ... menu's "Fit the
  // whole diagram". Shift+0 is the phase overview.
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
  // A flow stops after two passes, so nothing moves while you read.
  { keys: ['Shift+A'], action: 'replayFlow', description: 'Play the connection flow again (it stops after two passes)' },
  { keys: ['e', 'Shift+E'], action: 'cycleConnections', description: 'Next / previous connection of the selected step' },
  { keys: ['1', '2', '3'], action: 'toggleSeverity', description: 'Toggle the high / medium / low filters' },
  // Not a Ctrl or Cmd chord (ui/platform.ts says why).
  { keys: ['b'], action: 'toggleRail', description: 'Show or hide the side panel; open or collapse the bottom panel' },
  { keys: ['t'], action: 'railTab', description: 'Go to the panel tabs, About / Findings / Selection / Outline (opens the panel); ← and → pick a tab' },
  { keys: ['?'], action: 'shortcuts', description: 'Show this shortcut sheet' },
  // The rungs in the order they run: the ... menu's own Escape (moremenu.ts), then those of
  // `dismissTopmost`. The guide's key table (docs/user-guide.md) holds what tools/keys-table.mjs
  // prints from this array.
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

  // The find key is the only Ctrl or Cmd chord the canvas answers. Every other Ctrl or Cmd
  // chord is left alone, unconsumed, for the workbench (ui/platform.ts says why).
  if (mod) {
    if (key === 'f' || key === 'F') {
      cmd.focusSearch();
      return consume();
    }
    return false;
  }

  // Alt+Enter is the one Alt chord the canvas answers (ui/platform.ts says why); every other
  // Alt chord is left alone, unconsumed.
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
  // An Escape that dismissed nothing (the focus is already off the canvas and nothing is
  // open or selected) is left unconsumed, so the workbench can use it.
  // An Escape the cascade used is consumed, and the panel's bootstrap then keeps VS Code from also
  // acting on it.
  if (key === 'Escape') {
    if (!cmd.escape()) return false;
    return consume();
  }
  // The review walk. `r` starts or ends it; `u` / Shift+U start it on the claims not
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
    // The other end of the walk's connection. Left alone when the walk is not on one.
    if (key === 'o' || key === 'O') {
      if (!cmd.walkOtherEnd()) return false;
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
  // `a` turns the flow on or off; Shift+A plays it again. Branch on shiftKey
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
  // Shift+E would be indistinguishable from `e`.
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
