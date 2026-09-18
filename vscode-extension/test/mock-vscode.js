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

class Selection extends Range {}

class Uri {
  constructor(fsPath, scheme = 'file') {
    this.fsPath = fsPath;
    this.scheme = scheme;
    this.path = fsPath.replace(/\\/g, '/');
  }
  static file(p) {
    return new Uri(p);
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
  shownDocuments: [],
  clipboardWrites: [],
  /** CFG-ONE: every workspace.getConfiguration(...).update() call. */
  configUpdates: [],
  /** H10: every languages.registerCodeLensProvider registration. */
  codeLensProviders: []
};

const configValues = new Map();
let workspaceFolders;
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
    getCells: () => built,
    cellAt: (index) => built[index]
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
 * lets a test play the webview's part with `panel.fire(message)`.
 */
function makeWebviewPanel(viewType, title, showOptions, options) {
  const messages = new EventEmitter();
  const disposal = new EventEmitter();
  const panel = {
    viewType,
    title,
    options,
    viewColumn: typeof showOptions === 'object' ? showOptions.viewColumn : showOptions,
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
    dispose() {
      if (panel.disposed) return;
      panel.disposed = true;
      disposal.fire();
    }
  };
  recorded.panels.push(panel);
  return panel;
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
    createTextEditorDecorationType() {
      return { dispose() {} };
    },
    createWebviewPanel: makeWebviewPanel,
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
      recorded.shownDocuments.push({ document, options });
      const editor = {
        document,
        viewColumn: options && options.viewColumn,
        setDecorations() {},
        revealRange() {},
        selection: undefined
      };
      return editor;
    },
    setStatusBarMessage: () => ({ dispose() {} }),
    withProgress: async (_options, task) => task({ report() {} }, { isCancellationRequested: false }),
    createTerminal: () => ({ show() {}, sendText() {}, dispose() {} })
  },
  workspace: {
    isTrusted: true,
    get workspaceFolders() {
      return workspaceFolders;
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
    getWorkspaceFolder: (uri) => {
      const target = String(uri && uri.path).toLowerCase();
      return (workspaceFolders || []).find((folder) =>
        target.startsWith(folder.uri.path.toLowerCase())
      );
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
      return [...documents.keys()].map((file) => makeDocument(Uri.file(file)));
    },
    openNotebookDocument: async (uri) => {
      const found = notebookDocuments.find((doc) => doc.uri.fsPath === uri.fsPath);
      if (!found) throw new Error(`notebook is not open: ${uri.fsPath}`);
      return found;
    },
    onDidSaveTextDocument: recordingEvent(recorded.saveListeners),
    onDidSaveNotebookDocument: recordingEvent(recorded.notebookSaveListeners),
    onDidChangeTextDocument: recordingEvent(recorded.changeListeners),
    onDidChangeWorkspaceFolders: recordingEvent(recorded.folderListeners),
    onDidChangeConfiguration: recordingEvent(recorded.configListeners),
    createFileSystemWatcher: () => {
      const change = [];
      const create = [];
      const remove = [];
      return {
        onDidChange: recordingEvent(change),
        onDidCreate: recordingEvent(create),
        onDidDelete: recordingEvent(remove),
        dispose() {}
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
    executeCommand: async () => undefined
  },
  env: {
    clipboard: { writeText: async (value) => void recorded.clipboardWrites.push(value) },
    openExternal: async () => true
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
  __setConfig(section, key, value, resource) {
    const scope = resource ? `${String(resource).replace(/\\/g, '/').toLowerCase()}|` : '';
    configValues.set(`${scope}${section}.${key}`, value);
  },
  __resetConfig() {
    configValues.clear();
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
    saveDialogAnswers.length = 0;
    quickPickAnswers.length = 0;
    fsWriteError = undefined;
    recorded.codeActionProviders.length = 0;
    recorded.panels.length = 0;
    messageAnswers.length = 0;
    documents.clear();
    dirtyDocuments.clear();
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
