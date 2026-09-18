import test from 'node:test';
import { authoredHandshake } from './authored-handshake.mjs';

test('authored VS Code handshake supports citations, refinement, export, and revisions', async () => {
  await authoredHandshake();
});
