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
 * EXT-8: real `Uri.fsPath` lower-cases a Windows drive letter while Node's realpath keeps the
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

class Location {
  constructor(uri, rangeOrPosition) {
    this.uri = uri;
    this.range = rangeOrPosition;
  }
}

class DiagnosticRelatedInformation {
  constructor(location, message) {
    this.location = location;
    this.message = message;
  }
}

const DiagnosticSeverity = { Error: 0, Warning: 1, Information: 2, Hint: 3 };

class Diagnostic {
  constructor(range, message, severity) {
    this.range = range;
    this.message = message;
    this.severity = severity === undefined ? DiagnosticSeverity.Error : severity;
    this.source = undefined;
    this.code = undefined;
    this.relatedInformation = undefined;
  }
}

class ThemeColor {
  constructor(id) {
    this.id = id;
  }
}

class ThemeIcon {
  constructor(id) {
    this.id = id;
  }
}

/**
 * H10: the status-bar tooltip becomes a trusted MarkdownString in a multi-root window, because
 * a command link is the only second action a status-bar item can carry. Only what
 * `decorateTooltip` touches is implemented, and `value` is what a test reads back.
 */
class MarkdownString {
  constructor(value = '') {
    this.value = value;
    this.isTrusted = false;
    this.supportThemeIcons = false;
  }
  appendText(text) {
    // Real VS Code escapes markdown and turns a newline into a hard break; the escaping is
    // what matters to a test, so `\n` is kept as-is and the specials are escaped.
    this.value += String(text).replace(/[\\`*_{}[\]()#+\-.!]/g, (c) => '\\' + c);
    return this;
  }
  appendMarkdown(text) {
    this.value += String(text);
    return this;
  }
}

class CodeLens {
  constructor(range, command) {
    this.range = range;
    this.command = command;
  }
}

/**
 * MLV-P10 needs three APIs the mock never had: the quick-fix classes, a workspace
 * edit the host can apply, and a `showWarningMessage` that can answer. All three are
 * recorded so a test can assert what the confirm dialog said, not just that it opened.
 */
const CodeActionKind = {
  QuickFix: { value: 'quickfix' },
  Refactor: { value: 'refactor' },
  Empty: { value: '' }
};

class CodeAction {
  constructor(title, kind) {
    this.title = title;
    this.kind = kind;
    this.command = undefined;
    this.diagnostics = undefined;
    this.isPreferred = undefined;
    this.edit = undefined;
  }
}

class WorkspaceEdit {
  constructor() {
    this.edits = [];
  }
  replace(uri, range, newText, metadata) {
    // H5: `metadata.needsConfirmation` is what routes an edit through VS Code's refactor
    // preview, so it is the thing "never auto-applied" is asserted on. Recorded, not dropped.
    this.edits.push({ kind: 'replace', uri, range, newText, metadata });
  }
  insert(uri, position, newText) {
    this.edits.push({ kind: 'insert', uri, position, newText });
  }
  createFile(uri, options) {
    this.edits.push({ kind: 'create', uri, options });
  }
  get size() {
    return this.edits.length;
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

class LanguageModelTextPart {
  constructor(value) {
    this.value = value;
  }
}

class LanguageModelToolResult {
  constructor(content) {
    this.content = content;
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
  /** Every `WorkspaceEdit` handed to `workspace.applyEdit`, newest last. */
  appliedEdits: [],
  /** H5: the `WorkspaceEditMetadata` of each of those calls, index-aligned. */
  applyEditMetadata: [],
  /** Every `registerCodeActionsProvider` registration: {selector, provider, metadata}. */
  codeActionProviders: [],
  outputChannels: [],
  diagnosticCollections: [],
  statusBarItems: [],
  commands: new Map(),
  messages: [],
  /** Webview panels created through `createWebviewPanel`, newest last. */
  panels: [],
  /** Language-model tools and chat participants, when the test enabled those APIs. */
  tools: new Map(),
  participants: [],
  serializers: new Map(),
  saveListeners: [],
  /** NB: `workspace.onDidSaveNotebookDocument` listeners, so a test can fire a notebook save. */
  notebookSaveListeners: [],
  changeListeners: [],
  folderListeners: [],
  configListeners: [],
  themeListeners: [],
  /** VIEW-07: every showSaveDialog option bag, every quick pick, and every file written. */
  saveDialogs: [],
  quickPicks: [],
  writtenFiles: [],
  /** Every showTextDocument call: {document, options, editor}; the editor records selection and revealRange. */
  shownDocuments: [],
  clipboardWrites: [],
  /** EXT-8: every live createFileSystemWatcher: {glob, change, create, delete} listener lists. */
  watchers: [],
  /** EXT-8: workspace.onDidChangeNotebookDocument listeners. */
  notebookChangeListeners: [],
  /** CFG-ONE: every workspace.getConfiguration(...).update() call. */
  configUpdates: [],
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
  /** H10: every languages.registerCodeLensProvider registration. */
  codeLensProviders: []
};

const configValues = new Map();
let workspaceFolders;
/** `workspace.workspaceFile`, set by `__setWorkspaceFile`. */
let workspaceFile;
/** FIFO of answers `show*Message` returns, set by `__answerMessage`. */
const messageAnswers = [];
/** VIEW-07: what the next showSaveDialog / showQuickPick returns, queued by the test. */
const saveDialogAnswers = [];
const quickPickAnswers = [];
/** When set, the next workspace.fs.writeFile throws it (a read-only target, a full disk). */
let fsWriteError;
/** Virtual documents keyed by `docKey`, set by `__setDocument`. */
const documents = new Map();
/** H5: the subset of those with unsaved edits, set by `__setDirty`. */
const dirtyDocuments = new Set();
/** EXT-8: open notebooks with unsaved edits, keyed like documents, set by `__setNotebookDirty`. */
const dirtyNotebooks = new Set();

/**
 * One key for one file, whatever spelling reaches us.
 *
 * A test writes `__setDocument('/repo/train.py', ...)` while the code under test hands
 * `openTextDocument` whatever `writableFile` returned, which is `path.resolve`d — HOST-6's
 * containment guard resolves `..` before it compares, so it must. On POSIX those two
 * strings are equal and the lookup hit; on Windows `path.resolve('/repo/train.py')` is
 * `D:\repo\train.py`, the lookup missed, `makeDocument` handed back the text-less stub and
 * `addIgnoreComment` died on `document.lineAt is not a function` — a Windows-only red in a
 * test double, not in the extension. Resolving on BOTH sides is what a real
 * `Uri.file()` round-trip does, so both spellings name one document on every platform.
 */
function docKey(fsPath) {
  return path.resolve(String(fsPath)).replace(/\\/g, '/');
}

/**
 * NB: the open notebooks, as `NotebookDocument` stubs. Real VS Code models a notebook as a
 * document of cells, each cell backed by its OWN TextDocument on a `vscode-notebook-cell:`
 * uri - which is the only thing a squiggle can be attached to inside a notebook, and the
 * reason `src/notebooks.ts` exists at all.
 */
let notebookDocuments = [];
let visibleTextEditors = [];
let visibleNotebookEditors = [];
/** Whether showNotebookDocument makes the selected cells' editors visible (as VS Code does once it draws them). */
let notebookCellEditors = true;

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
    /** EXT-8: every revealRange(range, revealType) call, in order. */
    revealed: [],
    revealRange(range, revealType) {
      editor.revealed.push({ range, revealType });
    },
    selection: undefined
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
    // EXT-9: VS Code clamps the index into [0, cellCount - 1] and throws on an empty notebook.
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
    // H5: an analysis describes the file ON DISK, so an unsaved buffer is stale
    // coordinates. `__setDirty` marks one, and nothing else in the mock reads it.
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
function makeWebviewPanel(viewType, title, showOptions, options, existingTab) {
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
    reveal() {
      panel.revealed += 1;
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
      const tab = makeTab(group, { label: title, viewType: `mainThreadWebview-${viewType}`, isActive: true });
      linkTab(tab, panel);
      const changed = group.tabs.filter((other) => other.isActive);
      for (const other of changed) setTabActive(other, false);
      group.tabs.push(tab);
      tabEvents.fire({ opened: [tab], closed: [], changed });
    }
  }
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
    input: spec.viewType !== undefined ? new TabInputWebview(spec.viewType) : new TabInputText(Uri.file(spec.uri || '/untitled')),
    isActive: !!spec.isActive,
    group
  };
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

const vscode = {
  version: '1.136.0-mock',
  Position,
  Range,
  Selection,
  Uri,
  Location,
  Diagnostic,
  DiagnosticSeverity,
  DiagnosticRelatedInformation,
  ThemeColor,
  ThemeIcon,
  CodeLens,
  MarkdownString,
  CodeAction,
  CodeActionKind,
  WorkspaceEdit,
  EventEmitter,
  LanguageModelTextPart,
  LanguageModelToolResult,
  ViewColumn: { One: 1, Two: 2, Beside: -2 },
  NotebookRange,
  TabInputWebview,
  TabInputText,
  Disposable,
  NotebookEditorRevealType: { Default: 0, InCenter: 1, InCenterIfOutsideViewport: 2, AtTop: 3 },
  OverviewRulerLane: { Left: 1, Center: 2, Right: 4, Full: 7 },
  DecorationRangeBehavior: { OpenOpen: 0, ClosedClosed: 1, OpenClosed: 2, ClosedOpen: 3 },
  StatusBarAlignment: { Left: 1, Right: 2 },
  ColorThemeKind: { Light: 1, Dark: 2, HighContrast: 3, HighContrastLight: 4 },
  TextEditorRevealType: { Default: 0, InCenter: 1, InCenterIfOutsideViewport: 2, AtTop: 3 },
  ProgressLocation: { Notification: 15, Window: 10 },
  ConfigurationTarget: { Global: 1, Workspace: 2, WorkspaceFolder: 3 },
  window: {
    activeTextEditor: undefined,
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
    createStatusBarItem() {
      // `texts` is the trail: a superseded analysis must never push an idle state into it
      // while the run that replaced it is still going.
      const item = {
        _text: '',
        texts: [],
        tooltip: '',
        command: '',
        get text() {
          return this._text;
        },
        set text(value) {
          this._text = value;
          if (this.texts[this.texts.length - 1] !== value) this.texts.push(value);
        },
        show() {},
        hide() {},
        dispose() {}
      };
      recorded.statusBarItems.push(item);
      return item;
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
      async close(tabs, preserveFocus) {
        const list = Array.isArray(tabs) ? tabs : [tabs];
        // `panels`: how many panels had been created when the tabs were closed.
        recorded.closedTabs.push({ tabs: list, preserveFocus, panels: recorded.panels.length });
        for (const group of tabGroups) group.tabs = group.tabs.filter((tab) => !list.includes(tab));
        for (const tab of list) if (tab.panel) tab.panel.dispose();
        tabEvents.fire({ opened: [], closed: list, changed: [] });
        return true;
      },
      onDidChangeTabs: tabEvents.event,
      onDidChangeTabGroups: tabGroupEvents.event
    },
    registerWebviewPanelSerializer: (viewType, serializer) => {
      recorded.serializers.set(viewType, serializer);
      return { dispose() {} };
    },
    onDidChangeActiveColorTheme: recordingEvent(recorded.themeListeners),
    showInformationMessage: async (m, ...rest) => {
      recorded.messages.push(['info', m, ...rest]);
      return messageAnswers.length ? messageAnswers.shift() : undefined;
    },
    showWarningMessage: async (m, ...rest) => {
      recorded.messages.push(['warn', m, ...rest]);
      return messageAnswers.length ? messageAnswers.shift() : undefined;
    },
    showErrorMessage: async (m, ...rest) => {
      recorded.messages.push(['error', m, ...rest]);
      return messageAnswers.length ? messageAnswers.shift() : undefined;
    },
    showQuickPick: async (items, options) => {
      recorded.quickPicks.push({ items, options });
      if (quickPickAnswers.length === 0) return undefined;
      const answer = quickPickAnswers.shift();
      // A queued index picks from the offered items, exactly like a click would.
      return typeof answer === 'number' ? (await items)[answer] : answer;
    },
    showInputBox: async () => undefined,
    showSaveDialog: async (options) => {
      recorded.saveDialogs.push(options);
      return saveDialogAnswers.length ? saveDialogAnswers.shift() : undefined;
    },
    showTextDocument: async (document, options) => {
      const editor = makeTextEditor(document, options && options.viewColumn);
      recorded.shownDocuments.push({ document, options, editor });
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
        viewColumn: options && options.viewColumn,
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
    onDidChangeVisibleTextEditors: recordingEvent(recorded.visibleEditorListeners),
    setStatusBarMessage: () => ({ dispose() {} }),
    withProgress: async (_options, task) => task({ report() {} }, { isCancellationRequested: false }),
    createTerminal: () => ({ show() {}, sendText() {}, dispose() {} })
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
    getConfiguration(section, resource) {
      // Resource-scoped reads win over the global value, exactly like a folder-level
      // .vscode/settings.json overriding a user setting.
      const scope = resource && resource.path ? String(resource.path).toLowerCase() : undefined;
      return {
        get(key) {
          if (scope !== undefined) {
            const scoped = configValues.get(`${scope}|${section}.${key}`);
            if (scoped !== undefined) return scoped;
          }
          return configValues.get(`${section}.${key}`);
        },
        // CFG-ONE: `MLView: Create Baseline From Current Findings` offers to point
        // mlview.baselinePath at what it wrote. Recorded AND applied, so the next read
        // sees it, exactly like a real settings write.
        async update(key, value, target) {
          recorded.configUpdates.push({ section, key, value, target, scope });
          const prefix = scope === undefined ? '' : `${scope}|`;
          configValues.set(`${prefix}${section}.${key}`, value);
        }
      };
    },
    // EXT-10: like VS Code, the innermost folder that contains the path on a separator boundary.
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
    applyEdit: async (edit, metadata) => {
      recorded.appliedEdits.push(edit);
      recorded.applyEditMetadata.push(metadata);
      // Apply single-line replacements to the virtual document so a test can read back
      // exactly what the user would see in the editor. The splice is COLUMN-accurate: H5's
      // edits replace a slice of a line (an insertion is an empty range), and a whole-line
      // replacement is just the slice [0, line.length).
      for (const change of edit.edits || []) {
        if (change.kind !== 'replace') continue;
        const key = docKey(change.uri && change.uri.fsPath);
        const text = documents.get(key);
        if (text === undefined) continue;
        const lines = text.split('\n');
        if (change.range.start.line !== change.range.end.line) continue;
        const line = lines[change.range.start.line];
        if (line === undefined) continue;
        lines[change.range.start.line] =
          line.slice(0, change.range.start.character) +
          change.newText +
          line.slice(change.range.end.character);
        documents.set(key, lines.join('\n'));
      }
      return true;
    },
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
    onDidChangeConfiguration: recordingEvent(recorded.configListeners),
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
      stat: async () => ({ type: 1 }),
      // VIEW-07: the bytes the host wrote, kept verbatim so a test can assert the FILE and
      // not merely that a write was attempted.
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
  languages: {
    createDiagnosticCollection(name) {
      const entries = new Map();
      const collection = {
        name,
        entries,
        set: (uri, diagnostics) => entries.set(uri.fsPath, diagnostics),
        delete: (uri) => entries.delete(uri.fsPath),
        clear: () => entries.clear(),
        dispose: () => entries.clear()
      };
      recorded.diagnosticCollections.push(collection);
      return collection;
    },
    registerCodeLensProvider: (selector, provider) => {
      // H10: a CodeLens is per-DOCUMENT, so `test/multiroot.test.js` has to be able to ask the
      // real provider what it draws on a file in the folder that is not active.
      recorded.codeLensProviders.push({ selector, provider });
      return { dispose() {} };
    },
    registerCodeActionsProvider: (selector, provider, metadata) => {
      recorded.codeActionProviders.push({ selector, provider, metadata });
      return { dispose() {} };
    }
  },
  commands: {
    registerCommand(id, handler) {
      recorded.commands.set(id, handler);
      return { dispose: () => recorded.commands.delete(id) };
    },
    executeCommand: async (id, ...args) => {
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
  extensions: { getExtension: () => undefined },
  CancellationTokenSource,
  NotebookCellKind,
  // Feature-detected APIs are absent by default, exactly like a VS Code build without them.
  chat: undefined,
  lm: undefined,
  __recorded: recorded,
  /** Queue what the next `show*Message` returns (a button label, or undefined). */
  __answerMessage(value) {
    messageAnswers.push(value);
  },
  /** VIEW-07: queue the Uri the next `showSaveDialog` returns (undefined = cancelled). */
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
   * NB: open one or more notebooks. Each entry is `{ path, cells: [{kind?, lines?}, ...] }`;
   * pass nothing to close them all.
   */
  __setNotebooks(specs) {
    notebookDocuments = (specs || []).map((spec) => makeNotebook(spec.path, spec.cells || []));
    return notebookDocuments;
  },
  __setVisibleTextEditors(specs) {
    visibleTextEditors = (specs || []).map((spec) => ({
      document: makeDocument(Uri.file(spec.path)),
      viewColumn: spec.viewColumn
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
  /** Whether showNotebookDocument makes the selected cells' editors visible (default true). */
  __setNotebookCellEditors(enabled) {
    notebookCellEditors = !!enabled;
  },
  /** Give `openTextDocument` real text for one absolute path. */
  __setDocument(fsPath, text) {
    documents.set(docKey(fsPath), text);
  },
  __getDocument(fsPath) {
    return documents.get(docKey(fsPath));
  },
  /** H5: mark an open document as having unsaved changes. */
  __setDirty(fsPath, dirty = true) {
    const key = docKey(fsPath);
    if (dirty) {
      dirtyDocuments.add(key);
    } else {
      dirtyDocuments.delete(key);
    }
  },
  /** EXT-8: mark an open notebook (by its path) as having unsaved changes. */
  __setNotebookDirty(fsPath, dirty = true) {
    const key = docKey(fsPath);
    if (dirty) {
      dirtyNotebooks.add(key);
    } else {
      dirtyNotebooks.delete(key);
    }
  },
  /** EXT-8: fire a file-system watcher event (`change`, `create` or `delete`) for one path. */
  __fireWatcher(kind, fsPath) {
    if (!['change', 'create', 'delete'].includes(kind)) throw new Error(`unknown watcher event: ${kind}`);
    const uri = Uri.file(fsPath);
    for (const watcher of [...recorded.watchers]) {
      for (const listener of [...watcher[kind]]) listener(uri);
    }
  },
  /** EXT-8: make Uri.file lower-case a Windows drive letter, as vscode-uri's fsPath does. */
  __setLowercaseDriveLetters(enabled = true) {
    lowercaseDriveLetters = !!enabled;
  },
  __setConfig(section, key, value, resource) {
    const scope = resource ? `${String(resource).replace(/\\/g, '/').toLowerCase()}|` : '';
    configValues.set(`${scope}${section}.${key}`, value);
  },
  __resetConfig() {
    configValues.clear();
  },
  /** A multi-root window's workspace file (a path, or an `untitled:` string); undefined for a single-folder window. */
  __setWorkspaceFile(value) {
    workspaceFile = value === undefined ? undefined : String(value).startsWith('untitled:') ? Uri.parse(String(value)) : Uri.file(value);
  },
  /**
   * Set the editor tab groups. Each spec is `{ viewColumn, tabs: [{ label, viewType?, uri?, isActive? }] }`:
   * a tab with `viewType` is a webview tab, one with `uri` a text tab. Returns the groups.
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
  /** Opt in to the feature-detected APIs; off by default so activation tests see them absent. */
  __enableChatAndLm() {
    vscode.chat = {
      createChatParticipant(id, handler) {
        const participant = { id, handler, iconPath: undefined, dispose() {} };
        recorded.participants.push(participant);
        return participant;
      }
    };
    vscode.lm = {
      registerTool(name, tool) {
        recorded.tools.set(name, tool);
        return { dispose() {} };
      }
    };
  },
  __disableChatAndLm() {
    vscode.chat = undefined;
    vscode.lm = undefined;
  },
  /** Forget everything recorded between tests. */
  __reset() {
    recorded.outputChannels.length = 0;
    recorded.diagnosticCollections.length = 0;
    recorded.statusBarItems.length = 0;
    recorded.commands.clear();
    recorded.messages.length = 0;
    recorded.appliedEdits.length = 0;
    recorded.applyEditMetadata.length = 0;
    recorded.saveDialogs.length = 0;
    recorded.quickPicks.length = 0;
    recorded.writtenFiles.length = 0;
    recorded.shownDocuments.length = 0;
    recorded.clipboardWrites.length = 0;
    recorded.configUpdates.length = 0;
    recorded.codeLensProviders.length = 0;
    recorded.decorationTypes.length = 0;
    recorded.shownNotebooks.length = 0;
    recorded.visibleEditorListeners.length = 0;
    recorded.workspaceFolderUpdates.length = 0;
    recorded.executedCommands.length = 0;
    recorded.closedTabs.length = 0;
    tabGroups = [];
    tabEvents.dispose();
    tabGroupEvents.dispose();
    workspaceFile = undefined;
    vscode.env.sessionId = 'mock-session';
    notebookCellEditors = true;
    saveDialogAnswers.length = 0;
    quickPickAnswers.length = 0;
    fsWriteError = undefined;
    recorded.codeActionProviders.length = 0;
    recorded.panels.length = 0;
    messageAnswers.length = 0;
    documents.clear();
    dirtyDocuments.clear();
    dirtyNotebooks.clear();
    recorded.watchers.length = 0;
    recorded.notebookChangeListeners.length = 0;
    lowercaseDriveLetters = false;
    recorded.tools.clear();
    recorded.participants.length = 0;
    recorded.serializers.clear();
    notebookDocuments = [];
    visibleTextEditors = [];
    visibleNotebookEditors = [];
    vscode.window.activeTextEditor = undefined;
    for (const key of [
      'saveListeners',
      'notebookSaveListeners',
      'changeListeners',
      'folderListeners',
      'configListeners',
      'themeListeners'
    ]) {
      recorded[key].length = 0;
    }
    configValues.clear();
    workspaceFolders = undefined;
    vscode.workspace.isTrusted = true;
  }
};

module.exports = vscode;
