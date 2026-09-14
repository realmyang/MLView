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
  reactToTextSave,
  reactToNotebookSave,
  reactToConfigChange,
  recordStale,
  registerWatchers,
  REPUBLISH_KEYS,
  REANALYZE_KEYS
} from './watchers';
export {
  isNotebookPath,
  notebookForShadow,
  cellRefFromEvidence,
  cellRefFor,
  findNotebook,
  cellAtIndex,
  resolveNotebookTarget,
  notebookCounts,
  notebookTooltipFragment,
  analyzedAnyNotebook,
  openNotebooks,
  CELL_EVIDENCE_RE,
  OUTSIDE_CELL_EVIDENCE_RE,
  NOTEBOOK_EXTENSION,
  NOTEBOOK_ANALYZED_KIND,
  SHADOW_DIR,
  CODE_CELL_KIND,
  NO_NOTEBOOKS
} from './notebooks';
export {
  buildDiagnostics,
  DiagnosticsPublisher,
  mapSeverity,
  toVsSeverity,
  resolveRuleDocPath,
  DIAGNOSTIC_SOURCE,
  DIAGNOSTIC_COLLECTION_NAME
} from './diagnostics';
export {
  MlviewPanel,
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
  scopeArgs,
  scopeNote,
  TOOL_ANALYZE,
  TOOL_ISSUES,
  TOOL_DIAGRAM
} from './lmTools';
// H10 — multi-root folders (docs/contracts/11.40-lm-tools-scope.md).
export {
  FolderBook,
  folderKey,
  folderPickItems,
  folderTooltipLine,
  pickFolder
} from './folders';
// CFG-ONE — the one configuration surface and its stated precedence.
export {
  configLogLine,
  createBaseline,
  openConfiguration,
  pyprojectHasMlviewTable,
  resolveAgainstRoot,
  resolveBaseline,
  resolveConfig,
  CONFIG_FILE_NAME,
  DEFAULT_BASELINE_RELATIVE,
  PYPROJECT_FILE_NAME
} from './mlviewConfig';
export { isTrusted, ensureTrusted, RESTRICTED_MESSAGE } from './trust';
export { CODELENS_TITLE } from './codelens';
export { PARTICIPANT_ID, handleChatRequest } from './chat';
export { statusBarText, statusBarTooltip, renderStatusBar, decorateTooltip } from './statusBar';
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
// PACKAGING — the bundled-core precedence chain (docs/CONTRACTS.md §11.25).
export { readBundledCore, chooseCore, compareVersions, coreLabel } from './bundledCore';
// H3 — the stderr progress frames.
export { parseProgressLine, ProgressSplitter, PROGRESS_PREFIX } from './progress';
// MLV-P10 — suppression as a one-click action (docs/CONTRACTS.md §11.27).
export {
  ignoreComment,
  withIgnoreComment,
  addDisabledRule,
  splitComment,
  isInsideWorkspace,
  insideAnyWorkspace,
  isRuleCode
} from './suppression';
export {
  MlviewCodeActionProvider,
  mlviewCodesIn,
  diagnosticCode,
  copyActionTitle,
  addActionTitle,
  disableActionTitle,
  copyIgnoreComment,
  addIgnoreComment,
  disableRule,
  configPathFor,
  writableFile,
  runSuppression,
  COPY_IGNORE_COMMAND,
  ADD_IGNORE_COMMAND,
  DISABLE_RULE_COMMAND,
  CONFIG_FILE
} from './codeActions';
// H5 — structured fixes (docs/contracts/11.43-host-fixes-and-comparison.md).
export {
  applyIssueFix,
  buildFixEdit,
  fixActionTitle,
  isMechanical,
  issueById,
  issuesAt,
  readFix,
  registerFixActions,
  MlviewFixActionProvider,
  APPLY_FIX_COMMAND,
  FIXABLE_BUCKETS,
  FIX_SAFETIES,
  MAX_FIX_EDITS,
  MAX_FIX_TEXT_CHARS
} from './fixes';
// VIEW-08 — the comparison commands and the diff overlay.
export {
  comparisonBasePath,
  compareWithCleanSample,
  compareWithSavedBase,
  findCleanTwin,
  overlayHeadline,
  overlayNoteLines,
  readOverlay,
  registerComparisonCommands,
  saveComparisonBase,
  withinRoot,
  CLEAN_TWIN_RELATIVE,
  COMPARE_BASE_COMMAND,
  COMPARE_CLEAN_COMMAND,
  COMPARISON_BASE_RELATIVE,
  SAVE_BASE_COMMAND
} from './compare';
// VIEW-07 — the diagram picture export (docs/contracts/11.33-diagram-export.md).
export {
  decodeExportPayload,
  defaultExportName,
  exportScopeChoices,
  requestDiagramExport,
  saveExportedFile,
  MAX_EXPORT_BYTES
} from './exportDiagram';
