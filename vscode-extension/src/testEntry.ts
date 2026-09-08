/**
 * Test surface. `node esbuild.mjs --test` bundles this file to `out/test-entry.cjs` with
 * `--external:vscode`, and `test/mock-vscode.js` is substituted for the real `vscode` module by
 * a `Module._resolveFilename` hook (see test/harness.js). That is how the host-independent
 * logic is exercised by `node --test` with no VS Code process (amendment A7).
 *
 * Nothing in the extension imports this file.
 */

export * from './graph';
export * from './protocol';
export * from './location';
export * from './locationIndex';
export * from './issues';
export * from './digest';
export {
  CoreClient,
  buildAnalyzeArgs,
  classifyExit,
  tailLines,
  scopeKey,
  forwardSlashes,
  Debouncer,
  CoreError,
  MAX_BUFFER_BYTES,
  SAVE_DEBOUNCE_MS
} from './coreClient';
export {
  buildDiagnostics,
  mapSeverity,
  toVsSeverity,
  resolveRuleDocPath,
  DIAGNOSTIC_SOURCE,
  DIAGNOSTIC_COLLECTION_NAME
} from './diagnostics';
export {
  buildPanelHtml,
  createNonce,
  themeKindOf,
  rangeFromLoc,
  scopeChrome,
  activeScopeFrom,
  PANEL_TITLE,
  VIEW_TYPE
} from './panel';
export { clearScope, scopeToSymbol, unitScopeSpec, SCOPE_KIND_UNIT } from './scopeCommands';
export { DeferredMessages, preserveFromState } from './panelState';
export {
  buildCandidates,
  pickInterpreter,
  parseHandshake,
  meetsMinimum,
  isSchemaMismatch,
  schemaMismatchMessage,
  MIN_PYTHON
} from './pythonEnv';
export {
  runAnalyzeTool,
  runListIssuesTool,
  runShowDiagramTool,
  TOOL_ANALYZE,
  TOOL_ISSUES,
  TOOL_DIAGRAM
} from './lmTools';
export { isTrusted, ensureTrusted, RESTRICTED_MESSAGE } from './trust';
export { CODELENS_TITLE } from './codelens';
export { PARTICIPANT_ID, handleChatRequest } from './chat';
export { statusBarText, statusBarTooltip, renderStatusBar } from './statusBar';
export {
  coverageChip,
  coverageFor,
  coverageLines,
  coverageNotes,
  COVERAGE_DIAGNOSTIC_KINDS
} from './coverage';
export {
  fileScopeSpec,
  focusScopeSpec,
  packageRootFor,
  resolveCurrentFileTarget,
  CURRENT_FILE_SCOPES
} from './currentFile';
export { readSettings, DEFAULT_SETTINGS, SETTINGS_SECTION } from './settings';
export { chatAvailable } from './chatSurfaces';
