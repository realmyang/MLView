'use strict';
/**
 * CFG-ONE, host half — one configuration surface with a STATED precedence
 * (docs/contracts/11.40-lm-tools-scope.md).
 *
 * The roadmap entry is explicit that the requirement is "a stated precedence with a test, not
 * more surface". These are that test. Three things are asserted:
 *
 *   1. WHICH file `--config` names, in the documented order, including the case that must NOT
 *      be taken — a `pyproject.toml` with no `[tool.mlview]` table is not an MLView config.
 *   2. That the precedence is STATED where a user reads it: both settings descriptions in
 *      package.json say the file wins for `disable` / `exclude` and that the `mlview.*`
 *      settings are additive filters.
 *   3. That the flags reach the analyzer's argv, in the frozen order, and that an
 *      unconfigured project's argv is byte-identical to the one it was before this feature.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const { api } = require('./harness.js');
const {
  resolveConfig,
  resolveBaseline,
  resolveAgainstRoot,
  pyprojectHasMlviewTable,
  configLogLine,
  buildAnalyzeArgs,
  CONFIG_FILE_NAME,
  PYPROJECT_FILE_NAME,
  DEFAULT_BASELINE_RELATIVE
} = api;

const ROOT = path.resolve('/repo');

/** A filesystem that is exactly the set of paths named, with the text they hold. */
function probeOf(files) {
  const table = new Map(
    Object.entries(files).map(([p, text]) => [path.resolve(ROOT, p), text])
  );
  return {
    exists: (p) => table.has(path.resolve(p)),
    readText: (p) => table.get(path.resolve(p)) ?? ''
  };
}

const NO_SETTINGS = { configPath: '', baselinePath: '' };

// ------------------------------------------------------------------ discovery order

test('an explicit mlview.configPath wins over everything that could be discovered', () => {
  const probe = probeOf({
    '.mlview.toml': '[rules]\ndisable = ["MLV601"]\n',
    'ci/strict.toml': '[rules]\ndisable = []\n'
  });
  const resolved = resolveConfig(ROOT, { configPath: 'ci/strict.toml' }, probe);
  assert.equal(resolved.source, 'setting');
  assert.equal(resolved.path, path.resolve(ROOT, 'ci/strict.toml'));
});

test('.mlview.toml is discovered when no setting names one', () => {
  const probe = probeOf({ '.mlview.toml': '[paths]\nexclude = ["experiments/**"]\n' });
  const resolved = resolveConfig(ROOT, NO_SETTINGS, probe);
  assert.equal(resolved.source, 'toml');
  assert.equal(resolved.path, path.resolve(ROOT, CONFIG_FILE_NAME));
});

test('.mlview.toml beats a pyproject that also has the table', () => {
  const probe = probeOf({
    '.mlview.toml': '[rules]\ndisable = []\n',
    'pyproject.toml': '[tool.mlview.rules]\ndisable = ["MLV601"]\n'
  });
  assert.equal(resolveConfig(ROOT, NO_SETTINGS, probe).source, 'toml');
});

test('pyproject.toml is used ONLY when it actually carries a [tool.mlview] table', () => {
  const withTable = probeOf({
    'pyproject.toml': '[project]\nname = "x"\n\n[tool.mlview]\n[tool.mlview.rules]\ndisable = ["MLV601"]\n'
  });
  const resolved = resolveConfig(ROOT, NO_SETTINGS, withTable);
  assert.equal(resolved.source, 'pyproject');
  assert.equal(resolved.path, path.resolve(ROOT, PYPROJECT_FILE_NAME));

  // A Python project that has never heard of MLView must not look configured: handing this
  // file to --config would make the output depend on a file nobody wrote for us.
  const withoutTable = probeOf({
    'pyproject.toml': '[project]\nname = "x"\n\n[tool.ruff]\nline-length = 100\n'
  });
  const bare = resolveConfig(ROOT, NO_SETTINGS, withoutTable);
  assert.equal(bare.source, 'none');
  assert.equal(bare.path, undefined);
});

test('the [tool.mlview] detector accepts the table and its children, and nothing else', () => {
  assert.ok(pyprojectHasMlviewTable('[tool.mlview]\n'));
  assert.ok(pyprojectHasMlviewTable('[project]\nx=1\n[tool.mlview.paths]\nexclude=[]\n'));
  assert.ok(pyprojectHasMlviewTable('  [ tool . mlview ]   # spaced\n'));
  assert.ok(!pyprojectHasMlviewTable('[tool.mlviewer]\n'));
  assert.ok(!pyprojectHasMlviewTable('[tool.ruff]\n# mentions tool.mlview in a comment\n'));
  assert.ok(!pyprojectHasMlviewTable('name = "[tool.mlview]"\n'));
});

test('a mlview.configPath that names nothing is reported, never silently ignored', () => {
  // CLEANUP 3 fixed exactly this class of defect for a typo'd rule code: a setting that has no
  // effect and says nothing is indistinguishable from one that worked.
  const resolved = resolveConfig(ROOT, { configPath: 'nope.toml' }, probeOf({}));
  assert.equal(resolved.source, 'none');
  assert.equal(resolved.missing, path.resolve(ROOT, 'nope.toml'));
  assert.match(configLogLine(resolved), /does not exist/);
  assert.match(configLogLine(resolved), /nope\.toml/);
});

test('an absolute configPath is taken as-is and a relative one resolves against the folder', () => {
  const absolute = path.resolve('/elsewhere/team.toml');
  assert.equal(resolveAgainstRoot(ROOT, absolute), absolute);
  assert.equal(resolveAgainstRoot(ROOT, 'sub/team.toml'), path.resolve(ROOT, 'sub/team.toml'));
  assert.equal(resolveAgainstRoot(ROOT, '   '), undefined);
  assert.equal(resolveAgainstRoot(ROOT, undefined), undefined);
});

// -------------------------------------------------------------------------- baseline

test('a baseline is used only when it is named AND on disk - never discovered', () => {
  const probe = probeOf({ '.mlview/baseline.json': '{}' });
  // The default location exists, and is still NOT taken: a file that quietly empties the
  // Problems panel has to be opted into by name.
  assert.deepEqual(resolveBaseline(ROOT, NO_SETTINGS, probe), {});
  assert.equal(
    resolveBaseline(ROOT, { baselinePath: DEFAULT_BASELINE_RELATIVE }, probe).path,
    path.resolve(ROOT, DEFAULT_BASELINE_RELATIVE)
  );
  const missing = resolveBaseline(ROOT, { baselinePath: 'gone.json' }, probe);
  assert.equal(missing.path, undefined);
  assert.equal(missing.missing, path.resolve(ROOT, 'gone.json'));
});

// ------------------------------------------------------------------------------ argv

test('--config and --baseline sit with the excludes, ahead of every projection flag', () => {
  const args = buildAnalyzeArgs({
    paths: ['/repo'],
    maxFiles: 500,
    maxNodes: 400,
    exclude: ['experiments/**'],
    configPath: '/repo/.mlview.toml',
    baselinePath: '/repo/.mlview/baseline.json',
    includeNotebooks: true,
    scopeSpec: 'concern:evaluation',
    depth: 0
  });
  const at = (flag) => args.indexOf(flag);
  assert.ok(at('--exclude') < at('--config'), '--config follows the excludes it extends');
  assert.ok(at('--config') < at('--baseline'));
  assert.ok(at('--baseline') < at('--include-notebooks'));
  assert.ok(at('--include-notebooks') < at('--scope'), 'ingest flags precede projection flags');
  assert.equal(args[at('--config') + 1], '/repo/.mlview.toml');
  assert.equal(args[at('--baseline') + 1], '/repo/.mlview/baseline.json');
});

test('an unconfigured project produces the argv it produced before CFG-ONE existed', () => {
  const args = buildAnalyzeArgs({ paths: ['/repo'], maxFiles: 500, maxNodes: 400, exclude: [] });
  assert.deepEqual(args, [
    '-X',
    'utf8',
    '-m',
    'mlview',
    'analyze',
    '/repo',
    '--json',
    '-',
    '--max-files',
    '500',
    '--max-nodes',
    '400'
  ]);
});

// ------------------------------------------------------- the precedence must be STATED

test('both settings descriptions state the precedence, in the manifest a user reads', () => {
  const manifest = JSON.parse(
    fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf8')
  );
  const props = manifest.contributes.configuration.properties;
  const config = props['mlview.configPath'];
  const baseline = props['mlview.baselinePath'];
  assert.ok(config, 'mlview.configPath must be contributed');
  assert.ok(baseline, 'mlview.baselinePath must be contributed');
  for (const row of [config, baseline]) {
    assert.equal(row.type, 'string');
    assert.equal(row.default, '');
    assert.equal(row.scope, 'resource', 'a config file is per-folder, not per-user');
    assert.match(row.markdownDescription, /[Pp]recedence/);
  }
  // The exact claim, not merely the word: the file wins and the settings are additive.
  assert.match(config.markdownDescription, /WINS/);
  assert.match(config.markdownDescription, /ADDITIVE/);
  assert.match(config.markdownDescription, /disable/);
  assert.match(config.markdownDescription, /exclude/);
  assert.match(
    config.markdownDescription,
    /neither can re-enable a rule the file disabled/,
    'the description must say what the settings CANNOT do, which is the whole point'
  );
  assert.match(baseline.markdownDescription, /never auto-discovered|not auto-discovered/i);

  // And the README, which is where a user looks before typing a setting name (PROC-11).
  const readme = fs.readFileSync(path.join(__dirname, '..', 'README.md'), 'utf8');
  assert.match(readme, /mlview\.configPath/);
  assert.match(readme, /mlview\.baselinePath/);
  assert.match(readme, /The file wins/);
});

/**
 * CFG-ONE, Sprint 5 wave 2. 11.40 C2 says "BOTH settings' markdownDescription say this in
 * those words", and the settings it names are the two ADDITIVE ones — `mlview.disabledRules`
 * and `mlview.exclude`. The wave-1 test asserted the claim on `configPath` / `baselinePath`
 * instead, so the two rows a user actually reads while typing a rule code said nothing about
 * precedence at all. This is that gap, closed and pinned.
 */
test('the two ADDITIVE settings say so themselves, where a user types them', () => {
  const manifest = JSON.parse(
    fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf8')
  );
  const props = manifest.contributes.configuration.properties;
  const rules = props['mlview.disabledRules'];
  const exclude = props['mlview.exclude'];
  for (const row of [rules, exclude]) {
    assert.ok(row, 'both additive settings must be contributed');
    assert.ok(
      row.markdownDescription,
      'the claim needs a markdownDescription: it links to #mlview.configPath#'
    );
    assert.match(row.markdownDescription, /[Pp]recedence/);
    assert.match(row.markdownDescription, /ADDITIVE/);
    assert.match(row.markdownDescription, /WINS/);
    assert.match(row.markdownDescription, /#mlview\.configPath#/);
    assert.equal(row.description, undefined, 'one description per row, or VS Code shows both');
  }
  // The exact thing each one CANNOT do - which is the whole point of stating a precedence.
  assert.match(
    rules.markdownDescription,
    /cannot re-enable a rule the file disabled/,
    'a user must not believe mlview.disabledRules can override [rules].disable'
  );
  assert.match(
    exclude.markdownDescription,
    /cannot re-include a path the file excluded/,
    'a user must not believe mlview.exclude can override [paths].exclude'
  );
  // ...and both name the table they lose to, so the precedence is actionable, not folklore.
  assert.match(rules.markdownDescription, /\[rules\]\.disable/);
  assert.match(exclude.markdownDescription, /\[paths\]\.exclude/);
});
