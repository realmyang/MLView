'use strict';
/**
 * A hand-written stand-in for the `vscode` module.
 *
 * `node --test` runs outside VS Code, so the bundled extension modules resolve `require('vscode')`
 * to this file through the hook in test/harness.js. It implements only what the host-independent
 * code paths touch, and it records what was created so tests can assert on it.
 */

const path = require('node:path');
const fs = require('node:fs');

class Position {
  constructor(line, character) {
    this.line = line;
    this.character = character;
  }
}

class Range {
  constructor(startLine, startChar, endLine, endChar) {
    if (startLine instanceof Position) {
      this.start = startLine;
      this.end = startChar;
    } else {
      this.start = new Position(startLine, startChar);
      this.end = new Position(endLine, endChar);
    }
  }
}

class Selection extends Range {
  /** Like VS Code: `anchor` is where the selection starts, `active` where the cursor is. */
  get anchor() {
    return this.start;
  }
  get active() {
    return this.end;
  }
}

/** A range of notebook cells, end exclusive. */
class NotebookRange {
  constructor(start, end) {
    this.start = start;
    this.end = end;
  }
}

/**
 * Real `Uri.fsPath` lower-cases a Windows drive letter while Node's realpath keeps the
 * canonical upper-case one. Off by default; `__setLowercaseDriveLetters(true)` opts in.
 */
let lowercaseDriveLetters = false;

class Uri {
  constructor(fsPath, scheme = 'file') {
    this.fsPath = fsPath;
    this.scheme = scheme;
    this.path = fsPath.replace(/\\/g, '/');
  }
  static file(p) {
    let value = String(p);
    if (lowercaseDriveLetters && /^[A-Za-z]:/.test(value)) value = value[0].toLowerCase() + value.slice(1);
    return new Uri(value);
  }
  static parse(value) {
    return new Uri(value, value.split(':')[0] || 'file');
  }
  static joinPath(base, ...parts) {
    return new Uri(path.join(base.fsPath, ...parts));
  }
  with() {
    return this;
  }
  toString() {
    return `${this.scheme}://${this.path}`;
  }
}

class ThemeColor {
  constructor(id) {
    this.id = id;
  }
}

class EventEmitter {
  constructor() {
    this.listeners = new Set();
    this.event = (listener) => {
      this.listeners.add(listener);
      return { dispose: () => this.listeners.delete(listener) };
    };
  }
  fire(value) {
    for (const listener of [...this.listeners]) {
      listener(value);
    }
  }
  dispose() {
    this.listeners.clear();
  }
}

/** `vscode.Disposable`: `from` combines several disposables into one. */
class Disposable {
  constructor(callOnDispose) {
    this.callOnDispose = callOnDispose;
  }
  static from(...items) {
    return new Disposable(() => {
      for (const item of items) if (item) item.dispose();
    });
  }
  dispose() {
    const call = this.callOnDispose;
    this.callOnDispose = undefined;
    if (call) call();
  }
}

class CancellationTokenSource {
  constructor() {
    this.emitter = new EventEmitter();
    this.token = { isCancellationRequested: false, onCancellationRequested: this.emitter.event };
  }
  cancel() {
    this.token.isCancellationRequested = true;
    this.emitter.fire();
  }
  dispose() {
    this.emitter.dispose();
  }
}

/** An event whose listeners are kept, so a test can fire it (`recorded.<name>`). */
function recordingEvent(store) {
  return (listener) => {
    store.push(listener);
    return {
      dispose() {
        const at = store.indexOf(listener);
        if (at >= 0) store.splice(at, 1);
      }
    };
  };
}

const recorded = {
  outputChannels: [],
  commands: new Map(),
  messages: [],
  /** Webview panels created through `createWebviewPanel`, newest last. */
  panels: [],
  serializers: new Map(),
  saveListeners: [],
  /** `workspace.onDidSaveNotebookDocument` listeners, so a test can fire a notebook save. */
  notebookSaveListeners: [],
  changeListeners: [],
  folderListeners: [],
  themeListeners: [],
  /** Every showSaveDialog option bag, every quick pick, and every file written. */
  saveDialogs: [],
  quickPicks: [],
  writtenFiles: [],
  /** Every showTextDocument call: {document, options, editor}; the editor records selection and revealRange. */
  shownDocuments: [],
  clipboardWrites: [],
  /** Every live createFileSystemWatcher: {glob, change, create, delete} listener lists. */
  watchers: [],
  /** workspace.onDidChangeNotebookDocument listeners. */
  notebookChangeListeners: [],
  /** Every createTextEditorDecorationType: {options, disposed}. */
  decorationTypes: [],
  /** Every showNotebookDocument call: {notebook, options, editor}. */
  shownNotebooks: [],
  /** window.onDidChangeVisibleTextEditors listeners. */
  visibleEditorListeners: [],
  /** Every workspace.updateWorkspaceFolders(start, deleteCount, ...folders) call. */
  workspaceFolderUpdates: [],
  /** Every commands.executeCommand(id, ...args) call. */
  executedCommands: [],
  /** Every window.tabGroups.close(tabs, preserveFocus) call. */
  closedTabs: [],
  /** window.onDidChangeActiveTextEditor and onDidChangeActiveNotebookEditor listeners (`__setActiveEditor`). */
  activeEditorListeners: [],
  activeNotebookListeners: [],
  /**
   * `setContext` is a built-in command, kept out of `executedCommands`: the context keys as they
   * are now, and every setContext call, in order.
   */
  contexts: new Map(),
  contextCalls: [],
  /** `registerCustomEditorProvider` registrations by view type: {provider, options}. */
  customEditors: new Map(),
  /** Every `vscode.openWith` command, kept out of `executedCommands`: {uri, viewType, options}. */
  openWith: [],
  /** Diagram-editor reveals into no group or another group's (VS Code would show it in two): {panel, viewColumn}. */
  splitReveals: []
};

let workspaceFolders;
/** `workspace.workspaceFile`, set by `__setWorkspaceFile`. */
let workspaceFile;
/** What the next showSaveDialog / showQuickPick returns, queued by the test. */
const saveDialogAnswers = [];
const quickPickAnswers = [];
/** When set, the next workspace.fs.writeFile throws it (a read-only target, a full disk). */
let fsWriteError;
/** Virtual documents keyed by `docKey`, set by `__setDocument`. */
const documents = new Map();
/** The subset of those with unsaved edits, set by `__setDirty`. */
const dirtyDocuments = new Set();
/** Open notebooks with unsaved edits, keyed like documents, set by `__setNotebookDirty`. */
const dirtyNotebooks = new Set();

/**
 * One key for one file, whatever spelling reaches the mock. A test names a document by a
 * forward-slashed path (`__setDocument('/repo/train.py', ...)`), while the code under test opens
 * it by a resolved path, which on Windows carries a drive letter (`D:\repo\train.py`). Both
 * sides are resolved here, as a `Uri.file()` round trip does, so both spellings name one document
 * on every platform.
 */
function docKey(fsPath) {
  return path.resolve(String(fsPath)).replace(/\\/g, '/');
}

/**
 * The open notebooks, as `NotebookDocument` stubs. Real VS Code models a notebook as a document
 * of cells, each cell backed by its own TextDocument on a `vscode-notebook-cell:` uri, and
 * `makeNotebook` builds the stubs that way.
 */
let notebookDocuments = [];
let visibleTextEditors = [];
let visibleNotebookEditors = [];
/** Whether showNotebookDocument makes the selected cells' editors visible (as VS Code does once it draws them). */
let notebookCellEditors = true;
/** Opt-in: showTextDocument's editor becomes the visible one in its column, as a preview tab replaces the last. */
let shownEditorsVisible = false;
/** Opt-in: showTextDocument into an existing group adds a text tab there, in front. */
let shownEditorsTabbed = false;
/** Opt-in: like VS Code's default `workbench.editor.closeEmptyGroups`, closing a group's last tab removes the group. */
let closeEmptyGroups = false;
/**
 * Opt-in: when groups close, every remaining tab is a new object, as VS Code's extension host
 * rebuilds its tab model on a group change; a tab object kept from before is then in no group.
 */
let freshTabsOnGroupChange = false;

/**
 * The column an editor shown with `viewColumn` lands in. With tab groups set (`__setTabGroups`),
 * ViewColumn.Beside opens a new group after the last one, as VS Code does beside a panel that is
 * alone or rightmost, and the editor reports that group's column; without them the option is
 * reported as it was passed.
 */
function resolveColumn(viewColumn, label) {
  if (viewColumn !== -2 || tabGroups.length === 0) return viewColumn;
  const column = Math.max(...tabGroups.map((group) => group.viewColumn)) + 1;
  const group = { viewColumn: column, isActive: false, tabs: [], get activeTab() { return group.tabs.find((tab) => tab.isActive); } };
  group.tabs = [makeTab(group, { label: label || 'source', uri: '/' + (label || 'source'), isActive: true })];
  tabGroups = [...tabGroups, group];
  tabGroupEvents.fire({ opened: [group], closed: [], changed: [] });
  return column;
}

/** A text editor stub that records its selection, reveals and decorations. */
function makeTextEditor(document, viewColumn) {
  const editor = {
    document,
    viewColumn,
    /** Every setDecorations(type, ranges) call, in order. */
    decorations: [],
    setDecorations(type, ranges) {
      editor.decorations.push({ type, ranges });
    },
    /** Every revealRange(range, revealType) call, in order. */
    revealed: [],
    revealRange(range, revealType) {
      editor.revealed.push({ range, revealType });
    },
    // Like VS Code, an editor always has a selection: the cursor at the start until something moves it.
    selection: new Selection(new Position(0, 0), new Position(0, 0))
  };
  return editor;
}

const NotebookCellKind = { Markup: 1, Code: 2 };

/**
 * Build one notebook stub. `cells` is a list of `{ kind, lines }` (kind defaults to Code),
 * and every cell gets the cell uri VS Code would give it: the notebook path with a
 * `vscode-notebook-cell` scheme and a `#chNNNN` fragment.
 */
function makeNotebook(fsPath, cells) {
  const uri = Uri.file(fsPath);
  const built = cells.map((cell, index) => {
    const kind = cell.kind === undefined ? NotebookCellKind.Code : cell.kind;
    const cellUri = new Uri(fsPath, 'vscode-notebook-cell');
    cellUri.fragment = 'ch' + String(index).padStart(4, '0');
    cellUri.toString = () => `vscode-notebook-cell://${cellUri.path}#${cellUri.fragment}`;
    return {
      index,
      kind,
      notebook: null,
      document: {
        uri: cellUri,
        languageId: kind === NotebookCellKind.Code ? 'python' : 'markdown',
        lineCount: typeof cell.lines === 'number' ? cell.lines : String(cell.text || '').split('\n').length,
        getText: () => String(cell.text || ''),
        lineAt: (line) => ({ text: String(cell.text || '').split('\n')[line] || '' })
      }
    };
  });
  const notebook = {
    uri,
    notebookType: 'jupyter-notebook',
    cellCount: built.length,
    get isDirty() {
      return dirtyNotebooks.has(docKey(fsPath));
    },
    getCells: () => built,
    // VS Code clamps the index into [0, cellCount - 1] and throws on an empty notebook.
    cellAt: (index) => {
      if (built.length === 0) throw new TypeError('Cannot read properties of undefined (reading \'apiCell\')');
      return built[Math.min(Math.max(0, index), built.length - 1)];
    }
  };
  for (const cell of built) {
    cell.notebook = notebook;
  }
  return notebook;
}

function makeDocument(uri) {
  const key = docKey(uri && uri.fsPath ? uri.fsPath : uri);
  const text = documents.get(key) ?? (fs.existsSync(key) && fs.statSync(key).isFile() ? fs.readFileSync(key, 'utf8') : undefined);
  if (text === undefined) {
    return { uri, lineCount: 400, languageId: 'python', isDirty: false, getText: () => '' };
  }
  const lines = text.split('\n');
  return {
    uri,
    languageId: 'python',
    lineCount: lines.length,
    // True only for a document that a test marked with `__setDirty`.
    isDirty: dirtyDocuments.has(key),
    getText: () => text,
    lineAt(line) {
      const value = lines[line];
      if (value === undefined) {
        throw new Error('Illegal value for line: ' + line);
      }
      return { text: value, lineNumber: line, range: new Range(line, 0, line, value.length) };
    }
  };
}

/**
 * A stand-in for a `WebviewPanel`: it records everything the host posts (`panel.posted`) and
 * lets a test play the webview's part with `panel.fire(message)`. When `window.tabGroups` has a
 * group in the panel's column, the panel gets a tab there, in front, like a new editor in VS Code
 * (`panel.tab`); closing that tab disposes the panel, and disposing the panel removes the tab.
 * `existingTab` links the panel to a tab that is already open instead (a restored tab revived by
 * the serializer, see `__reviveTab`).
 */
function makeWebviewPanel(viewType, title, showOptions, options, existingTab, customUri) {
  const messages = new EventEmitter();
  const disposal = new EventEmitter();
  const viewState = new EventEmitter();
  const panel = {
    viewType,
    title,
    options,
    viewColumn: typeof showOptions === 'object' ? showOptions.viewColumn : showOptions,
    /** VS Code's `visible`: the panel is the editor its group shows. */
    visible: true,
    active: false,
    tab: undefined,
    posted: [],
    revealed: 0,
    /** Every reveal(viewColumn, preserveFocus) call, in order. */
    revealCalls: [],
    disposed: false,
    webview: {
      html: '',
      cspSource: 'vscode-webview://mock',
      options,
      asWebviewUri: (uri) => new Uri('/mock-resource' + uri.path, 'https'),
      postMessage: async (message) => {
        panel.posted.push(message);
        return true;
      },
      onDidReceiveMessage: messages.event
    },
    /** Play the webview's part. */
    fire: (message) => messages.fire(message),
    postedTypes: () => panel.posted.map((m) => m.type),
    reveal(viewColumn, preserveFocus) {
      panel.revealed += 1;
      panel.revealCalls.push({ viewColumn, preserveFocus });
      // A diagram editor (several allowed per file, so not a singleton) revealed with no column
      // or another group's is shown by VS Code in two groups at once. Its own group: the column
      // VS Code reported, else the group holding a tab of its file.
      if (panel.customUri) {
        const own = panel.viewColumn > 0 ? panel.viewColumn
          : (tabGroups.find((group) => group.tabs.some((tab) => tab.input instanceof TabInputCustom && tab.input.uri.fsPath === panel.customUri.fsPath)) || {}).viewColumn;
        if (viewColumn === undefined || viewColumn !== own) recorded.splitReveals.push({ panel, viewColumn });
      }
    },
    onDidDispose: disposal.event,
    onDidChangeViewState: viewState.event,
    /** Play VS Code's view state change: assign `{ viewColumn?, visible?, active? }` and fire the event. */
    __setViewState(state) {
      Object.assign(panel, state);
      viewState.fire({ webviewPanel: panel });
    },
    dispose() {
      if (panel.disposed) return;
      panel.disposed = true;
      const tab = panel.tab;
      if (tab && tab.group.tabs.includes(tab)) {
        tab.group.tabs = tab.group.tabs.filter((other) => other !== tab);
        tabEvents.fire({ opened: [], closed: [tab], changed: [] });
      }
      disposal.fire();
    }
  };
  if (existingTab) {
    linkTab(existingTab, panel);
    panel.viewColumn = existingTab.group.viewColumn;
    panel.visible = existingTab.isActive;
  } else {
    const group = tabGroups.find((candidate) => candidate.viewColumn === panel.viewColumn);
    if (group) {
      // A custom editor's tab reports the file and the editor's view type.
      const tab = makeTab(group, customUri ? { label: title, custom: customUri.fsPath, customViewType: viewType, isActive: true } : { label: title, viewType: `mainThreadWebview-${viewType}`, isActive: true });
      linkTab(tab, panel);
      const changed = group.tabs.filter((other) => other.isActive);
      for (const other of changed) setTabActive(other, false);
      group.tabs.push(tab);
      tabEvents.fire({ opened: [tab], closed: [], changed });
    }
  }
  if (customUri) panel.customUri = customUri;
  recorded.panels.push(panel);
  return panel;
}

/** A webview tab's input, as the tabs API reports it (VS Code prefixes the view type). */
class TabInputWebview {
  constructor(viewType) {
    this.viewType = viewType;
  }
}

/** A text tab's input. */
class TabInputText {
  constructor(uri) {
    this.uri = uri;
  }
}

/** A custom editor tab's input (the file and the editor's view type). */
class TabInputCustom {
  constructor(uri, viewType) {
    this.uri = uri;
    this.viewType = viewType;
  }
}

/**
 * The editor tab groups (`window.tabGroups`), set by `__setTabGroups`. Each group is
 * `{ viewColumn, tabs, activeTab }` and each tab `{ label, input, isActive, group }`, like VS
 * Code's. `close` records the call, removes the tabs (disposing a panel whose tab it is) and fires
 * `onDidChangeTabs`. It does not bring another tab to the front: a test does that with
 * `__activateTab`.
 */
let tabGroups = [];
const tabEvents = new EventEmitter();
const tabGroupEvents = new EventEmitter();
function makeTab(group, spec) {
  return {
    label: spec.label,
    input: spec.custom !== undefined
      ? new TabInputCustom(Uri.file(spec.custom), spec.customViewType || 'mlview.diagram')
      : spec.viewType !== undefined ? new TabInputWebview(spec.viewType) : new TabInputText(Uri.file(spec.uri || '/untitled')),
    isActive: !!spec.isActive,
    /** A preview tab, which the next preview opened in its group replaces. */
    isPreview: !!spec.isPreview,
    group
  };
}
/** The same tab as a new object (see `freshTabsOnGroupChange`). */
function freshTab(tab) {
  const copy = { label: tab.label, input: tab.input, isActive: tab.isActive, isPreview: tab.isPreview, group: tab.group };
  if (tab.panel) linkTab(copy, tab.panel);
  return copy;
}
/** The tab shows `panel`: its label is the panel's title, and its front state is the panel's visibility. */
function linkTab(tab, panel) {
  Object.defineProperty(tab, 'label', { get: () => panel.title, configurable: true, enumerable: true });
  tab.panel = panel;
  panel.tab = tab;
}
function setTabActive(tab, active) {
  tab.isActive = active;
  if (tab.panel && !tab.panel.disposed && tab.panel.visible !== active) tab.panel.__setViewState({ visible: active });
}
function makeGroup(viewColumn, isActive = false) {
  const group = { viewColumn, isActive, tabs: [], get activeTab() { return group.tabs.find((tab) => tab.isActive); } };
  return group;
}
/** Put `tab` in front of its group, as VS Code does for an editor it opens there. */
function addTab(group, tab) {
  const changed = group.tabs.filter((other) => other.isActive);
  for (const other of changed) setTabActive(other, false);
  group.tabs.push(tab);
  tabEvents.fire({ opened: [tab], closed: [], changed });
}
/**
 * VS Code's `vscode.openWith` for a registered custom editor. In the target group (the active one
 * when none is given; a new group after the last for ViewColumn.Beside), an editor of the same
 * file and view type is brought to the front, as VS Code matches the input; otherwise a panel is
 * created there and the provider's `openCustomDocument` and `resolveCustomEditor` run before the
 * command returns.
 */
async function openWithCustomEditor(uri, viewType, options) {
  recorded.openWith.push({ uri, viewType, options });
  const entry = recorded.customEditors.get(viewType);
  if (!entry) return undefined;
  const requested = typeof options === 'number' ? options : options && options.viewColumn;
  // With no groups modelled, VS Code would still report a real column: Beside is the second.
  let column = requested === undefined || requested === -1 ? ((tabGroups.find((group) => group.isActive) || tabGroups[0] || {}).viewColumn || 1) : (requested === -2 && !tabGroups.length ? 2 : requested);
  if (tabGroups.length) {
    if (column === -2) {
      column = Math.max(...tabGroups.map((group) => group.viewColumn)) + 1;
      const group = makeGroup(column);
      tabGroups = [...tabGroups, group];
      tabGroupEvents.fire({ opened: [group], closed: [], changed: [] });
    } else {
      let group = tabGroups.find((candidate) => candidate.viewColumn === column);
      if (!group) {
        group = makeGroup(Math.max(...tabGroups.map((candidate) => candidate.viewColumn)) + 1);
        column = group.viewColumn;
        tabGroups = [...tabGroups, group];
        tabGroupEvents.fire({ opened: [group], closed: [], changed: [] });
      }
      const existing = group.tabs.find((tab) => tab.input instanceof TabInputCustom && tab.input.viewType === viewType && tab.input.uri.fsPath === uri.fsPath);
      if (existing) {
        // Like VS Code, `preview: false` keeps an open preview editor.
        if (options && typeof options === 'object' && options.preview === false) existing.isPreview = false;
        vscode.__activateTab(existing);
        return undefined;
      }
    }
  }
  const panel = makeWebviewPanel(viewType, path.basename(uri.fsPath), { viewColumn: column }, {}, undefined, uri);
  // `preview: true` stands in for an Explorer single click, a preview tab.
  if (panel.tab && options && typeof options === 'object' && options.preview === true) panel.tab.isPreview = true;
  const token = new CancellationTokenSource().token;
  const document = await entry.provider.openCustomDocument(uri, { backupId: undefined, untitledDocumentData: undefined }, token);
  await entry.provider.resolveCustomEditor(document, panel, token);
  return undefined;
}

const vscode = {
  version: '1.136.0-mock',
  Position,
  Range,
  Selection,
  Uri,
  ThemeColor,
  EventEmitter,
  ViewColumn: { Active: -1, One: 1, Two: 2, Beside: -2 },
  NotebookRange,
  TabInputWebview,
  TabInputText,
  TabInputCustom,
  Disposable,
  NotebookEditorRevealType: { Default: 0, InCenter: 1, InCenterIfOutsideViewport: 2, AtTop: 3 },
  OverviewRulerLane: { Left: 1, Center: 2, Right: 4, Full: 7 },
  DecorationRangeBehavior: { OpenOpen: 0, ClosedClosed: 1, OpenClosed: 2, ClosedOpen: 3 },
  ColorThemeKind: { Light: 1, Dark: 2, HighContrast: 3, HighContrastLight: 4 },
  TextEditorRevealType: { Default: 0, InCenter: 1, InCenterIfOutsideViewport: 2, AtTop: 3 },
  window: {
    activeTextEditor: undefined,
    activeNotebookEditor: undefined,
    onDidChangeActiveTextEditor: recordingEvent(recorded.activeEditorListeners),
    onDidChangeActiveNotebookEditor: recordingEvent(recorded.activeNotebookListeners),
    get visibleTextEditors() {
      return visibleTextEditors;
    },
    get visibleNotebookEditors() {
      return visibleNotebookEditors;
    },
    activeColorTheme: { kind: 2 },
    createOutputChannel(name) {
      const channel = { name, lines: [], appendLine: (l) => channel.lines.push(l), show() {}, dispose() {} };
      recorded.outputChannels.push(channel);
      return channel;
    },
    createTextEditorDecorationType(options) {
      const type = {
        options,
        disposed: false,
        dispose() {
          type.disposed = true;
        }
      };
      recorded.decorationTypes.push(type);
      return type;
    },
    createWebviewPanel: makeWebviewPanel,
    tabGroups: {
      get all() {
        return tabGroups;
      },
      get activeTabGroup() {
        return tabGroups.find((group) => group.isActive) || tabGroups[0];
      },
      async close(tabs, preserveFocus) {
        const list = Array.isArray(tabs) ? tabs : [tabs];
        // `panels`: how many panels had been created when the tabs were closed.
        recorded.closedTabs.push({ tabs: list, preserveFocus, panels: recorded.panels.length });
        for (const group of tabGroups) group.tabs = group.tabs.filter((tab) => !list.includes(tab));
        for (const tab of list) if (tab.panel) tab.panel.dispose();
        tabEvents.fire({ opened: [], closed: list, changed: [] });
        if (closeEmptyGroups && tabGroups.length > 1 && tabGroups.some((group) => !group.tabs.length)) {
          // VS Code closes the emptied groups and numbers the rest from 1 again.
          const closed = tabGroups.filter((group) => !group.tabs.length);
          tabGroups = tabGroups.filter((group) => group.tabs.length);
          if (!tabGroups.length) tabGroups = [closed.shift()];
          tabGroups.forEach((group, index) => {
            group.viewColumn = index + 1;
            for (const tab of group.tabs) if (tab.panel && !tab.panel.disposed && tab.panel.viewColumn !== index + 1) tab.panel.__setViewState({ viewColumn: index + 1 });
            if (freshTabsOnGroupChange) group.tabs = group.tabs.map(freshTab);
          });
          tabGroupEvents.fire({ opened: [], closed, changed: tabGroups });
        }
        return true;
      },
      onDidChangeTabs: tabEvents.event,
      onDidChangeTabGroups: tabGroupEvents.event
    },
    registerWebviewPanelSerializer: (viewType, serializer) => {
      recorded.serializers.set(viewType, serializer);
      return { dispose() {} };
    },
    registerCustomEditorProvider: (viewType, provider, options) => {
      recorded.customEditors.set(viewType, { provider, options });
      return {
        dispose() {
          if (recorded.customEditors.get(viewType)?.provider === provider) recorded.customEditors.delete(viewType);
        }
      };
    },
    onDidChangeActiveColorTheme: recordingEvent(recorded.themeListeners),
    showInformationMessage: async (m, ...rest) => {
      recorded.messages.push(['info', m, ...rest]);
      return undefined;
    },
    showWarningMessage: async (m, ...rest) => {
      recorded.messages.push(['warn', m, ...rest]);
      return undefined;
    },
    showErrorMessage: async (m, ...rest) => {
      recorded.messages.push(['error', m, ...rest]);
      return undefined;
    },
    showQuickPick: async (items, options) => {
      recorded.quickPicks.push({ items, options });
      if (quickPickAnswers.length === 0) return undefined;
      const answer = quickPickAnswers.shift();
      // A queued index picks from the offered items, exactly like a click would.
      return typeof answer === 'number' ? (await items)[answer] : answer;
    },
    showSaveDialog: async (options) => {
      recorded.saveDialogs.push(options);
      return saveDialogAnswers.length ? saveDialogAnswers.shift() : undefined;
    },
    showTextDocument: async (documentOrUri, options) => {
      // Like VS Code, a Uri is opened as a document first.
      const document = documentOrUri instanceof Uri ? makeDocument(documentOrUri) : documentOrUri;
      const editor = makeTextEditor(document, resolveColumn(options && options.viewColumn, document && document.uri && path.basename(document.uri.fsPath)));
      recorded.shownDocuments.push({ document, options, editor });
      if (shownEditorsVisible) visibleTextEditors = [...visibleTextEditors.filter((other) => other.viewColumn !== editor.viewColumn), editor];
      const group = shownEditorsTabbed && tabGroups.find((candidate) => candidate.viewColumn === editor.viewColumn);
      if (group && !group.tabs.some((tab) => tab.input instanceof TabInputText && tab.input.uri.fsPath === document.uri.fsPath && tab.isActive)) {
        addTab(group, makeTab(group, { label: path.basename(document.uri.fsPath), uri: document.uri.fsPath, isActive: true }));
      }
      return editor;
    },
    /**
     * Records the call and returns a notebook editor stub. When `notebookCellEditors` is on, the
     * selected cells' editors become visible on the next turn and the visible-editors event fires,
     * the way VS Code creates a cell's editor once it draws the cell.
     */
    showNotebookDocument: async (notebook, options) => {
      const editor = {
        notebook,
        viewColumn: resolveColumn(options && options.viewColumn, notebook && notebook.uri && path.basename(notebook.uri.fsPath)),
        selections: (options && options.selections) || [],
        revealed: [],
        revealRange(range, revealType) {
          editor.revealed.push({ range, revealType });
        }
      };
      recorded.shownNotebooks.push({ notebook, options, editor });
      if (notebookCellEditors) {
        setImmediate(() => {
          for (const range of editor.selections) {
            for (let index = range.start; index < range.end; index++) {
              const cell = notebook.cellAt(index);
              if (!visibleTextEditors.some((e) => e.document === cell.document)) {
                visibleTextEditors = [...visibleTextEditors, makeTextEditor(cell.document, editor.viewColumn)];
              }
            }
          }
          for (const listener of [...recorded.visibleEditorListeners]) listener(visibleTextEditors);
        });
      }
      return editor;
    },
    onDidChangeVisibleTextEditors: recordingEvent(recorded.visibleEditorListeners)
  },
  workspace: {
    isTrusted: true,
    get workspaceFolders() {
      return workspaceFolders;
    },
    /** Undefined in a single-folder window; the workspace file's Uri in a multi-root one. */
    get workspaceFile() {
      return workspaceFile;
    },
    // Like VS Code, the innermost folder that contains the path on a separator boundary.
    getWorkspaceFolder: (uri) => {
      const target = String(uri && uri.path).toLowerCase();
      let best;
      let bestLength = -1;
      for (const folder of workspaceFolders || []) {
        const root = folder.uri.path.toLowerCase().replace(/\/+$/, '');
        if ((target === root || target.startsWith(root + '/')) && root.length > bestLength) {
          best = folder;
          bestLength = root.length;
        }
      }
      return best;
    },
    openTextDocument: async (uri) => makeDocument(uri),
    get notebookDocuments() {
      return notebookDocuments;
    },
    get textDocuments() {
      // Keys use '/' (docKey); a real Uri.file(...).fsPath is native, so normalise for Windows.
      return [...documents.keys()].map((file) => makeDocument(Uri.file(path.normalize(file))));
    },
    openNotebookDocument: async (uri) => {
      const found = notebookDocuments.find((doc) => doc.uri.fsPath === uri.fsPath);
      if (!found) throw new Error(`notebook is not open: ${uri.fsPath}`);
      return found;
    },
    onDidSaveTextDocument: recordingEvent(recorded.saveListeners),
    onDidSaveNotebookDocument: recordingEvent(recorded.notebookSaveListeners),
    onDidChangeTextDocument: recordingEvent(recorded.changeListeners),
    onDidChangeNotebookDocument: recordingEvent(recorded.notebookChangeListeners),
    onDidChangeWorkspaceFolders: recordingEvent(recorded.folderListeners),
    /**
     * Like VS Code: splice the folder list, then fire onDidChangeWorkspaceFolders on a later turn.
     * Returns true when the call was accepted.
     */
    updateWorkspaceFolders(start, deleteCount, ...folders) {
      recorded.workspaceFolderUpdates.push({ start, deleteCount, folders });
      const current = workspaceFolders ? workspaceFolders.slice() : [];
      const removed = current.splice(start, deleteCount || 0, ...folders.map((f) => ({ uri: f.uri, name: f.name || path.basename(f.uri.fsPath), index: 0 })));
      workspaceFolders = current.map((folder, index) => ({ ...folder, index }));
      const added = workspaceFolders.slice(start, start + folders.length);
      setImmediate(() => {
        for (const listener of [...recorded.folderListeners]) listener({ added, removed });
      });
      return true;
    },
    createFileSystemWatcher: (glob) => {
      const watcher = { glob, change: [], create: [], delete: [] };
      recorded.watchers.push(watcher);
      return {
        onDidChange: recordingEvent(watcher.change),
        onDidCreate: recordingEvent(watcher.create),
        onDidDelete: recordingEvent(watcher.delete),
        dispose() {
          const at = recorded.watchers.indexOf(watcher);
          if (at >= 0) recorded.watchers.splice(at, 1);
        }
      };
    },
    fs: {
      // The bytes the host wrote, kept verbatim so a test can assert the FILE and not merely that
      // a write was attempted.
      writeFile: async (uri, bytes) => {
        if (fsWriteError) {
          const err = fsWriteError;
          fsWriteError = undefined;
          throw err;
        }
        recorded.writtenFiles.push({ fsPath: uri.fsPath, bytes: Buffer.from(bytes) });
      }
    }
  },
  commands: {
    registerCommand(id, handler) {
      recorded.commands.set(id, handler);
      return { dispose: () => recorded.commands.delete(id) };
    },
    executeCommand: async (id, ...args) => {
      if (id === 'vscode.openWith') return openWithCustomEditor(args[0], args[1], args[2]);
      if (id === 'setContext') {
        recorded.contexts.set(args[0], args[1]);
        recorded.contextCalls.push({ key: args[0], value: args[1] });
        return undefined;
      }
      recorded.executedCommands.push({ id, args });
      return undefined;
    }
  },
  env: {
    clipboard: { writeText: async (value) => void recorded.clipboardWrites.push(value) },
    openExternal: async () => true,
    /** The window session; the same across an extension host restart (set it to play another window). */
    sessionId: 'mock-session'
  },
  CancellationTokenSource,
  NotebookCellKind,
  __recorded: recorded,
  /** Queue the Uri the next `showSaveDialog` returns (undefined = cancelled). */
  __answerSaveDialog(uri) {
    saveDialogAnswers.push(uri);
  },
  /** Queue the next `showQuickPick` answer: an item, or an index into the offered items. */
  __answerQuickPick(value) {
    quickPickAnswers.push(value);
  },
  /** Make the next `workspace.fs.writeFile` throw. */
  __failNextWrite(err) {
    fsWriteError = err || new Error('EACCES: permission denied');
  },
  /**
   * Open one or more notebooks. Each entry is `{ path, cells: [{kind?, lines?}, ...] }`;
   * pass nothing to close them all.
   */
  __setNotebooks(specs) {
    notebookDocuments = (specs || []).map((spec) => makeNotebook(spec.path, spec.cells || []));
    return notebookDocuments;
  },
  __setVisibleTextEditors(specs) {
    visibleTextEditors = (specs || []).map((spec) => ({
      document: makeDocument(Uri.file(spec.path)),
      viewColumn: spec.viewColumn,
      selection: new Selection(new Position(0, 0), new Position(0, 0))
    }));
    vscode.window.activeTextEditor = visibleTextEditors.find(editor => editor.viewColumn === specs?.find(spec => spec.active)?.viewColumn);
    return visibleTextEditors;
  },
  __setVisibleNotebookEditors(specs) {
    visibleNotebookEditors = (specs || []).map((spec) => ({
      notebook: notebookDocuments.find(notebook => notebook.uri.fsPath === spec.path),
      viewColumn: spec.viewColumn
    }));
    return visibleNotebookEditors;
  },
  /**
   * The reader moves to an editor outside the panel. `{ path, viewColumn }` is a text editor,
   * `{ notebook: path, viewColumn }` a notebook editor; it becomes the active one and the matching
   * change event fires. Pass nothing for "a webview took the focus" (undefined fires).
   */
  __setActiveEditor(spec) {
    if (spec && spec.notebook !== undefined) {
      const editor = { notebook: notebookDocuments.find((notebook) => notebook.uri.fsPath === spec.notebook), viewColumn: spec.viewColumn };
      vscode.window.activeNotebookEditor = editor;
      for (const listener of [...recorded.activeNotebookListeners]) listener(editor);
      return editor;
    }
    // `{ cellOf: notebookPath, cell }` is the editor of one cell of an open notebook;
    // `selection: [startLine, startChar, endLine, endChar]` (zero-based, default the start of the
    // document) is its selection.
    let document;
    if (spec && spec.cellOf !== undefined) {
      const notebook = notebookDocuments.find((candidate) => candidate.uri.fsPath === spec.cellOf);
      if (!notebook) throw new Error(`notebook is not open: ${spec.cellOf}`);
      document = notebook.cellAt(spec.cell).document;
    } else if (spec) {
      document = makeDocument(Uri.file(spec.path));
    }
    const [l1, c1, l2, c2] = (spec && spec.selection) || [0, 0, 0, 0];
    const editor = spec ? { document, viewColumn: spec.viewColumn, selection: new Selection(new Position(l1, c1), new Position(l2 === undefined ? l1 : l2, c2 === undefined ? c1 : c2)) } : undefined;
    vscode.window.activeTextEditor = editor;
    for (const listener of [...recorded.activeEditorListeners]) listener(editor);
    return editor;
  },
  /** Whether showNotebookDocument makes the selected cells' editors visible (default true). */
  __setNotebookCellEditors(enabled) {
    notebookCellEditors = !!enabled;
  },
  /** Whether showTextDocument's editor joins visibleTextEditors, replacing the one in its column (default false). */
  __setShownEditorsVisible(enabled) {
    shownEditorsVisible = !!enabled;
  },
  /** Whether showTextDocument into an existing group adds a text tab in front there (default false). */
  __setShownEditorsTabbed(enabled) {
    shownEditorsTabbed = !!enabled;
  },
  /** Whether closing a group's last tab removes the group, as VS Code does by default (default false). */
  __setCloseEmptyGroups(enabled) {
    closeEmptyGroups = !!enabled;
  },
  /** Whether a closed group gives every remaining tab a new object (default false). */
  __setFreshTabsOnGroupChange(enabled) {
    freshTabsOnGroupChange = !!enabled;
  },
  /** Give `openTextDocument` real text for one absolute path. */
  __setDocument(fsPath, text) {
    documents.set(docKey(fsPath), text);
  },
  /** Mark an open document as having unsaved changes. */
  __setDirty(fsPath, dirty = true) {
    const key = docKey(fsPath);
    if (dirty) {
      dirtyDocuments.add(key);
    } else {
      dirtyDocuments.delete(key);
    }
  },
  /** Mark an open notebook (by its path) as having unsaved changes. */
  __setNotebookDirty(fsPath, dirty = true) {
    const key = docKey(fsPath);
    if (dirty) {
      dirtyNotebooks.add(key);
    } else {
      dirtyNotebooks.delete(key);
    }
  },
  /** Fire a file-system watcher event (`change`, `create` or `delete`) for one path. */
  __fireWatcher(kind, fsPath) {
    if (!['change', 'create', 'delete'].includes(kind)) throw new Error(`unknown watcher event: ${kind}`);
    const uri = Uri.file(fsPath);
    for (const watcher of [...recorded.watchers]) {
      for (const listener of [...watcher[kind]]) listener(uri);
    }
  },
  /** Make Uri.file lower-case a Windows drive letter, as vscode-uri's fsPath does. */
  __setLowercaseDriveLetters(enabled = true) {
    lowercaseDriveLetters = !!enabled;
  },
  /** A multi-root window's workspace file (a path, or an `untitled:` string); undefined for a single-folder window. */
  __setWorkspaceFile(value) {
    workspaceFile = value === undefined ? undefined : String(value).startsWith('untitled:') ? Uri.parse(String(value)) : Uri.file(value);
  },
  /**
   * Set the editor tab groups. Each spec is `{ viewColumn, tabs: [{ label, viewType?, uri?, custom?, isActive? }] }`:
   * a tab with `custom` (a path) is a diagram editor tab, one with `viewType` a webview
   * tab, one with `uri` a text tab. Returns the groups.
   */
  __setTabGroups(specs) {
    tabGroups = (specs || []).map((spec) => {
      const group = {
        viewColumn: spec.viewColumn,
        isActive: !!spec.isActive,
        tabs: [],
        get activeTab() {
          return group.tabs.find((tab) => tab.isActive);
        }
      };
      group.tabs = (spec.tabs || []).map((tab) => makeTab(group, tab));
      return group;
    });
    return tabGroups;
  },
  /** Bring `tab` to the front of its group (the others in it go behind) and fire `onDidChangeTabs`. */
  __activateTab(tab) {
    const changed = tab.group.tabs.filter((other) => other.isActive !== (other === tab));
    for (const other of changed) setTabActive(other, other === tab);
    tabEvents.fire({ opened: [], closed: [], changed });
  },
  /**
   * VS Code revives a restored tab through the serializer: a new panel for the tab that is
   * already open (its title, its column, visible when the tab is in front). The test then passes
   * it to the serializer's `deserializeWebviewPanel`.
   */
  __reviveTab(tab, viewType = 'mlview.authoredDiagram') {
    return makeWebviewPanel(viewType, tab.label, { viewColumn: tab.group.viewColumn }, {}, tab);
  },
  /**
   * VS Code resolves a diagram editor tab that is already open (one restored with the window,
   * shown for the first time): a panel for that tab, then the provider's `openCustomDocument` and
   * `resolveCustomEditor`. Returns the panel.
   */
  async __resolveCustomTab(tab) {
    const entry = recorded.customEditors.get(tab.input.viewType);
    if (!entry) throw new Error(`no custom editor provider for ${tab.input.viewType}`);
    const panel = makeWebviewPanel(tab.input.viewType, tab.label, { viewColumn: tab.group.viewColumn }, {}, tab, tab.input.uri);
    const token = new CancellationTokenSource().token;
    const document = await entry.provider.openCustomDocument(tab.input.uri, { backupId: undefined, untitledDocumentData: undefined }, token);
    await entry.provider.resolveCustomEditor(document, panel, token);
    return panel;
  },
  /** How many listeners `window.tabGroups` events have (a finished recovery leaves none). */
  __tabListeners() {
    return tabEvents.listeners.size + tabGroupEvents.listeners.size;
  },
  /**
   * A Memento like `ExtensionContext.globalState`: `values` is the store, `updates` every update
   * call. Like VS Code's, `get` sees an update at once and the promise resolves once the window
   * has stored it; `persisted` is what the window has stored, which outlives the extension host.
   * `delayMs` makes that store take a while.
   */
  __memento(initial, { delayMs = 0 } = {}) {
    const values = new Map(Object.entries(initial || {}));
    const memento = {
      values,
      persisted: new Map(values),
      updates: [],
      keys: () => [...values.keys()],
      get: (key, fallback) => (values.has(key) ? values.get(key) : fallback),
      async update(key, value) {
        memento.updates.push({ key, value });
        const copy = value === undefined ? undefined : JSON.parse(JSON.stringify(value));
        if (copy === undefined) values.delete(key);
        else values.set(key, copy);
        if (delayMs) await new Promise((resolve) => setTimeout(resolve, delayMs));
        if (copy === undefined) memento.persisted.delete(key);
        else memento.persisted.set(key, copy);
      }
    };
    return memento;
  },
  /** Open one or more folders. Paths are forward-slashed absolute paths. */
  __setWorkspaceFolders(roots) {
    workspaceFolders = roots
      ? roots.map((root, index) => ({ uri: Uri.file(root), name: 'ws' + index, index }))
      : undefined;
  },
  /** Forget everything recorded between tests. */
  __reset() {
    recorded.outputChannels.length = 0;
    recorded.commands.clear();
    recorded.messages.length = 0;
    recorded.saveDialogs.length = 0;
    recorded.quickPicks.length = 0;
    recorded.writtenFiles.length = 0;
    recorded.shownDocuments.length = 0;
    recorded.clipboardWrites.length = 0;
    recorded.decorationTypes.length = 0;
    recorded.shownNotebooks.length = 0;
    recorded.visibleEditorListeners.length = 0;
    recorded.workspaceFolderUpdates.length = 0;
    recorded.executedCommands.length = 0;
    recorded.closedTabs.length = 0;
    recorded.activeEditorListeners.length = 0;
    recorded.activeNotebookListeners.length = 0;
    recorded.contexts.clear();
    recorded.contextCalls.length = 0;
    recorded.customEditors.clear();
    recorded.openWith.length = 0;
    recorded.splitReveals.length = 0;
    shownEditorsTabbed = false;
    closeEmptyGroups = false;
    freshTabsOnGroupChange = false;
    vscode.window.activeNotebookEditor = undefined;
    tabGroups = [];
    tabEvents.dispose();
    tabGroupEvents.dispose();
    workspaceFile = undefined;
    vscode.env.sessionId = 'mock-session';
    notebookCellEditors = true;
    saveDialogAnswers.length = 0;
    quickPickAnswers.length = 0;
    fsWriteError = undefined;
    recorded.panels.length = 0;
    documents.clear();
    dirtyDocuments.clear();
    dirtyNotebooks.clear();
    recorded.watchers.length = 0;
    recorded.notebookChangeListeners.length = 0;
    lowercaseDriveLetters = false;
    recorded.serializers.clear();
    notebookDocuments = [];
    visibleTextEditors = [];
    visibleNotebookEditors = [];
    shownEditorsVisible = false;
    vscode.window.activeTextEditor = undefined;
    for (const key of [
      'saveListeners',
      'notebookSaveListeners',
      'changeListeners',
      'folderListeners',
      'themeListeners'
    ]) {
      recorded[key].length = 0;
    }
    workspaceFolders = undefined;
    vscode.workspace.isTrusted = true;
  }
};

module.exports = vscode;
