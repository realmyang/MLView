import test from 'node:test';
import { authoredHandshake, authoredStaleHandshake } from './authored-handshake.mjs';

test('authored VS Code handshake supports citations, refinement, export, remount and watched revisions', async () => {
  await authoredHandshake();
});

test('authored VS Code handshake shows a stale revision as historical inside the mounted root', async () => {
  await authoredStaleHandshake();
});
