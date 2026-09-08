'use strict';
/**
 * A hand-written stand-in for the `vscode` module.
 *
 * `node --test` runs outside VS Code, so the bundled extension modules resolve `require('vscode')`
 * to this file through the hook in test/harness.js. It implements only what the host-independent
 * code paths touch, and it records what was created so tests can assert on it.
 */

const path = require('node:path');

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

class CodeLens {
  constructor(range, command) {
    this.range = range;
    this.command = command;
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
  changeListeners: [],
  folderListeners: [],
  configListeners: [],
  themeListeners: []
};

const configValues = new Map();
let workspaceFolders;

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
  EventEmitter,
  LanguageModelTextPart,
  LanguageModelToolResult,
  ViewColumn: { One: 1, Two: 2, Beside: -2 },
  StatusBarAlignment: { Left: 1, Right: 2 },
  ColorThemeKind: { Light: 1, Dark: 2, HighContrast: 3, HighContrastLight: 4 },
  TextEditorRevealType: { Default: 0, InCenter: 1, InCenterIfOutsideViewport: 2, AtTop: 3 },
  ProgressLocation: { Notification: 15, Window: 10 },
  window: {
    activeTextEditor: undefined,
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
    showInformationMessage: async (m) => void recorded.messages.push(['info', m]),
    showWarningMessage: async (m) => void recorded.messages.push(['warn', m]),
    showErrorMessage: async (m) => void recorded.messages.push(['error', m]),
    showQuickPick: async () => undefined,
    showInputBox: async () => undefined,
    showSaveDialog: async () => undefined,
    showTextDocument: async () => ({
      setDecorations() {},
      revealRange() {},
      selection: undefined
    }),
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
        }
      };
    },
    getWorkspaceFolder: (uri) => {
      const target = String(uri && uri.path).toLowerCase();
      return (workspaceFolders || []).find((folder) =>
        target.startsWith(folder.uri.path.toLowerCase())
      );
    },
    openTextDocument: async (uri) => ({ uri, lineCount: 400, languageId: 'python' }),
    onDidSaveTextDocument: recordingEvent(recorded.saveListeners),
    onDidChangeTextDocument: recordingEvent(recorded.changeListeners),
    onDidChangeWorkspaceFolders: recordingEvent(recorded.folderListeners),
    onDidChangeConfiguration: recordingEvent(recorded.configListeners),
    fs: { stat: async () => ({ type: 1 }) }
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
    registerCodeLensProvider: () => ({ dispose() {} })
  },
  commands: {
    registerCommand(id, handler) {
      recorded.commands.set(id, handler);
      return { dispose: () => recorded.commands.delete(id) };
    },
    executeCommand: async () => undefined
  },
  env: {
    clipboard: { writeText: async () => undefined },
    openExternal: async () => true
  },
  extensions: { getExtension: () => undefined },
  CancellationTokenSource,
  // Feature-detected APIs are absent by default, exactly like a VS Code build without them.
  chat: undefined,
  lm: undefined,
  __recorded: recorded,
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
    recorded.panels.length = 0;
    recorded.tools.clear();
    recorded.participants.length = 0;
    recorded.serializers.clear();
    for (const key of [
      'saveListeners',
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
