// The key map (src/ui/keymap.ts) is shown in two places, and each is compared with it here: the key
// table of docs/user-guide.md, which tools/keys-table.mjs prints from the source, and the shortcut
// sheet of the built viewer. The first test fails after a change of the key map until the lines
// between the guide's two markers are what `node tools/keys-table.mjs` prints. The second fails
// while dist/mlview.js is built from another key map than the source holds.
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { GUIDE_FILE, guideTable, keyTable, readKeyMap } from '../tools/keys-table.mjs';
import { WEBVIEW_ROOT, loadBundle, recordingBridge } from './helpers.mjs';

const TOOL = join(WEBVIEW_ROOT, 'tools', 'keys-table.mjs');

const DOCUMENT = {
  workflowVersion: '1.0', title: 'One step',
  producer: { kind: 'host-llm', host: 'claude-code', model: 'fixture-model' }, revision: { id: 'r1' },
  request: { question: 'What does the script do?', scope: 'train.py' },
  phases: [{ id: 'fit', label: 'Fit' }],
  nodes: [{ id: 'step', label: 'Optimizer step', phase: 'fit', basis: 'observed', evidence: ['e1'] }],
  edges: [],
  findings: [],
  evidence: [{ id: 'e1', file: 'train.py', line: 9, endLine: 9, quote: 'opt.step()' }],
  coverage: { status: 'scoped', summary: 's', inspectedFiles: ['train.py'], limitations: [] },
};

test('the key table of docs/user-guide.md is the table that tools/keys-table.mjs prints from the key map', async () => {
  const guide = guideTable(await readFile(GUIDE_FILE, 'utf8'));
  assert.notEqual(guide, null, 'docs/user-guide.md holds the two markers');
  assert.equal(guide, keyTable(await readKeyMap()));
  const printed = spawnSync(process.execPath, [TOOL], { encoding: 'utf8' });
  assert.equal(printed.status, 0, printed.stderr);
  assert.equal(printed.stdout, guide + '\n');
  const check = spawnSync(process.execPath, [TOOL, '--check'], { encoding: 'utf8' });
  assert.equal(check.status, 0, check.stdout + check.stderr);
});

test('the shortcut sheet of the built viewer shows the keys and the descriptions of the key map', async () => {
  const keymap = await readKeyMap();
  const ctx = await loadBundle();
  const app = ctx.MLView.mountWorkflow(ctx.document.getElementById('mlview-root'), DOCUMENT, recordingBridge(ctx.window));
  app.toggleShortcuts(true);
  const sheet = ctx.document.querySelector('.mlv-sheet');
  assert.ok(sheet && !sheet.hidden, 'the shortcut sheet is open');
  const shown = Array.from(sheet.querySelectorAll('dt'), (keys) => ({
    keys: Array.from(keys.querySelectorAll('kbd'), (key) => key.textContent),
    description: keys.nextElementSibling ? keys.nextElementSibling.textContent : null,
  }));
  // The sheet prints each key for the reader's platform. jsdom does not report macOS, so `Mod+` is
  // printed `Ctrl+` and every other key as the key map has it.
  const expected = keymap.map((binding) => ({
    keys: binding.keys.map((key) => key.replace(/^Mod\+/, 'Ctrl+')),
    description: binding.description,
  }));
  assert.deepEqual(shown, expected);
  app.destroy();
});
