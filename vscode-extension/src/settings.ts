/**
 * Typed access to the `mlview.*` settings contributed in package.json (CONTRACTS.md §6).
 * Every read goes through here so defaults live in exactly one place in the code.
 */

import * as vscode from 'vscode';
import { CURRENT_FILE_SCOPES, type CurrentFileAnalysisScope } from './currentFile';
import type { Severity } from './graph';
import type { TraceLevel } from './log';

export type DiagnosticSeverityMode = 'warning' | 'error';

export interface MlviewSettings {
  pythonPath: string;
  analyzeOnSave: boolean;
  /** What `MLView: Visualize (Current File)` analyzes before scoping to the file (COVERAGE). */
  currentFileAnalysisScope: CurrentFileAnalysisScope;
  exclude: string[];
  maxFiles: number;
  maxNodes: number;
  minSeverity: Severity;
  minConfidence: number;
  diagnosticsEnabled: boolean;
  diagnosticSeverity: DiagnosticSeverityMode;
  disabledRules: string[];
  codeLens: boolean;
  trace: TraceLevel;
}

export const SETTINGS_SECTION = 'mlview';

export const DEFAULT_SETTINGS: MlviewSettings = {
  pythonPath: '',
  analyzeOnSave: true,
  currentFileAnalysisScope: 'package',
  exclude: [],
  maxFiles: 500,
  maxNodes: 400,
  minSeverity: 'low',
  minConfidence: 0.6,
  diagnosticsEnabled: true,
  diagnosticSeverity: 'warning',
  disabledRules: [],
  codeLens: true,
  trace: 'off'
};

function oneOf<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return typeof value === 'string' && (allowed as readonly string[]).includes(value)
    ? (value as T)
    : fallback;
}

function stringArray(value: unknown, fallback: string[]): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : fallback;
}

function positiveInt(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0
    ? Math.trunc(value)
    : fallback;
}

function clamped(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value)
    ? Math.min(1, Math.max(0, value))
    : fallback;
}

/** Read the effective settings, resource-scoped when a resource is supplied. */
export function readSettings(resource?: vscode.Uri): MlviewSettings {
  const cfg = vscode.workspace.getConfiguration(SETTINGS_SECTION, resource ?? null);
  const d = DEFAULT_SETTINGS;
  return {
    pythonPath: (cfg.get<string>('pythonPath') ?? d.pythonPath).trim(),
    analyzeOnSave: cfg.get<boolean>('analyzeOnSave') ?? d.analyzeOnSave,
    currentFileAnalysisScope: oneOf(
      cfg.get('currentFileAnalysisScope'),
      CURRENT_FILE_SCOPES,
      d.currentFileAnalysisScope
    ),
    exclude: stringArray(cfg.get('exclude'), d.exclude),
    maxFiles: positiveInt(cfg.get('maxFiles'), d.maxFiles),
    maxNodes: positiveInt(cfg.get('maxNodes'), d.maxNodes),
    minSeverity: oneOf(cfg.get('minSeverity'), ['low', 'medium', 'high'] as const, d.minSeverity),
    minConfidence: clamped(cfg.get('minConfidence'), d.minConfidence),
    diagnosticsEnabled: cfg.get<boolean>('diagnosticsEnabled') ?? d.diagnosticsEnabled,
    diagnosticSeverity: oneOf(
      cfg.get('diagnosticSeverity'),
      ['warning', 'error'] as const,
      d.diagnosticSeverity
    ),
    disabledRules: stringArray(cfg.get('disabledRules'), d.disabledRules).map((c) =>
      c.trim().toUpperCase()
    ),
    codeLens: cfg.get<boolean>('codeLens') ?? d.codeLens,
    trace: oneOf(cfg.get('trace'), ['off', 'messages', 'verbose'] as const, d.trace)
  };
}

/** True when the change event touches any `mlview.*` key. */
export function affectsMlview(e: vscode.ConfigurationChangeEvent): boolean {
  return e.affectsConfiguration(SETTINGS_SECTION);
}
