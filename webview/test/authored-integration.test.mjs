import test from 'node:test';
import { authoredEscapeHandshake, authoredHandshake, authoredRevealHandshake, authoredStaleHandshake, authoredWalkHandshake } from './authored-handshake.mjs';

test('authored VS Code handshake supports citations, refinement, export, remount and watched revisions', async () => {
  await authoredHandshake();
});

test('authored VS Code handshake shows a stale revision as historical inside the mounted root', async () => {
  await authoredStaleHandshake();
});

test('an Escape the viewer acted on stops at the page instead of also reaching VS Code', async () => {
  await authoredEscapeHandshake();
});

test('the review walk drives the real host: opens beside with the focus kept, highlights, clears, ends; stale claims are blocked', async () => {
  await authoredWalkHandshake();
});

test('Reveal in Diagram drives the real host and page: one claim at once, several in a QuickPick, the keyboard on the claim, a discarded page served after ready', async () => {
  await authoredRevealHandshake();
});
