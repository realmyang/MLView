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
  escape(): void;
  cycleIssue(backwards: boolean): boolean;
  zoom(direction: number): void;
  fit(): void;
  toggleFocusMode(): void;
  zoomToSelection(): void;
  /** `Shift+0`: collapse every group and fit — the one-screen picture. */
  overview(): void;
  /** `l`: show or hide the legend. */
  toggleLegend(): void;
  /** `a`: turn the connection-flow animation on or off. */
  toggleFlow(): void;
  toggleCollapse(): boolean;
  openSelection(): boolean;
  move(key: string): void;
  /** 0 = high, 1 = medium, 2 = low. */
  toggleSeverity(index: number): void;
  toggleRail(): void;
  /** 0 = Issues, 1 = Inspector, 2 = Outline. */
  selectRailTab(index: number): void;
  toggleShortcuts(): void;
  /** `e` / `Shift+E`: walk the selection's connections. */
  cycleConnections(backwards: boolean): boolean;
  /** `s`: scope the diagram to the selection. */
  scopeToSelection(): boolean;
  /** `Shift+S`: clear the scope. False when there is none. */
  clearScope(): boolean;
  /** `[` / `]`: step the scope depth. False when there is no scope. */
  stepDepth(delta: number): boolean;
}

export interface KeyBinding {
  keys: string[];
  action: string;
  description: string;
}

export const KEYMAP: KeyBinding[] = [
  { keys: ['Ctrl/Cmd+K', '/'], action: 'focusSearch', description: 'Search nodes, issues and rule codes' },
  { keys: ['n', 'p'], action: 'cycleIssue', description: 'Next / previous issue by severity' },
  { keys: ['Enter'], action: 'open', description: 'Open the selection in the editor' },
  { keys: ['Space'], action: 'collapse', description: 'Collapse or expand the selected group' },
  { keys: ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'], action: 'move', description: 'Move the selection' },
  { keys: ['0'], action: 'fit', description: 'Fit the whole diagram' },
  { keys: ['Shift+0'], action: 'overview', description: 'Overview: collapse every group and fit' },
  { keys: ['+', '='], action: 'zoomIn', description: 'Zoom in' },
  { keys: ['-', '_'], action: 'zoomOut', description: 'Zoom out' },
  { keys: ['z'], action: 'zoomToSelection', description: 'Zoom to the selection' },
  { keys: ['f'], action: 'focusMode', description: 'Focus mode on the selection' },
  { keys: ['l'], action: 'legend', description: 'Show or hide the legend' },
  { keys: ['a'], action: 'flow', description: 'Turn the connection flow animation on or off' },
  { keys: ['e', 'Shift+E'], action: 'cycleConnections', description: 'Next / previous connection of the selected node' },
  { keys: ['s', 'Shift+S'], action: 'scope', description: 'Scope the diagram to the selection / clear the scope' },
  { keys: ['[', ']'], action: 'scopeDepth', description: 'Narrow / widen the scope by one hop' },
  { keys: ['1', '2', '3'], action: 'toggleSeverity', description: 'Toggle the high / medium / low filters' },
  { keys: ['Ctrl+B'], action: 'toggleRail', description: 'Show or hide the side rail' },
  { keys: ['Ctrl+1', 'Ctrl+2', 'Ctrl+3'], action: 'railTab', description: 'Issues / Inspector / Outline' },
  { keys: ['?'], action: 'shortcuts', description: 'Show this shortcut sheet' },
  // The rungs, in the order `dismissTopmost` runs them (CONTRACTS 11.13). The
  // sheet is the only place the cascade is described to the user, and a scoped
  // diagram is exactly where someone presses Escape expecting the selection to
  // go and loses the scope instead (MLV-R1-F2-06).
  { keys: ['Escape'], action: 'escape', description: 'Close the picker, sheet or legend, exit focus mode, clear the scope, clear the selection, leave the canvas' },
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

  if (mod) {
    if (key === 'k' || key === 'K') {
      cmd.focusSearch();
      return consume();
    }
    if (key === 'b' || key === 'B') {
      cmd.toggleRail();
      return consume();
    }
    if (key === '1' || key === '2' || key === '3') {
      cmd.selectRailTab(Number(key) - 1);
      return consume();
    }
    return false;
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
  if (key === 'Escape') {
    cmd.escape();
    return consume();
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
  // both mean Overview, and the plain `0` below must not swallow either.
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
  if (key === 'a' || key === 'A') {
    cmd.toggleFlow();
    return consume();
  }
  // `f`/`p` fold case above, so this pair must branch on shiftKey EXPLICITLY or
  // Shift+E would be indistinguishable from `e` (CONTRACTS 11.13).
  if (key === 'e' || key === 'E') {
    if (!cmd.cycleConnections(ev.shiftKey)) return false;
    return consume();
  }
  if (key === 's' || key === 'S') {
    const done = ev.shiftKey ? cmd.clearScope() : cmd.scopeToSelection();
    if (!done) return false;
    return consume();
  }
  if (key === '[' || key === ']') {
    if (!cmd.stepDepth(key === ']' ? 1 : -1)) return false;
    return consume();
  }
  if (key === 'z' || key === 'Z') {
    cmd.zoomToSelection();
    return consume();
  }
  if (key === ' ') {
    if (!cmd.toggleCollapse()) return false;
    return consume();
  }
  if (key === 'Enter') {
    if (!cmd.openSelection()) return false;
    return consume();
  }
  if (key.indexOf('Arrow') === 0) {
    cmd.move(key);
    return consume();
  }
  return false;
}
