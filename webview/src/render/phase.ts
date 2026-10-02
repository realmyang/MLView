/**
 * Viewer M2: phase colour by document order.
 *
 * Every element drawn for a phase (lane, card, group, connection, trunk, phase-index row)
 * carries `data-phase-index` (its phase's 0-based position in the document) and `data-phase-tone`
 * (that position modulo `PHASE_TONES`). The stylesheet binds `--mlv-stage` from the tone
 * (styles/node.css), so the colour never depends on how the author spelled the phase id: the
 * eight analyzer stage ids used to be the only ones with a hue, and 88% of authored phases drew
 * grey. `data-stage` (the id) stays where it was, because the geometry golden hashes it on lanes.
 */

import { phaseTone } from '../layout/model.js';

export function stampPhase(element: Element, phaseIndex: number): void {
  element.setAttribute('data-phase-index', String(phaseIndex));
  element.setAttribute('data-phase-tone', String(phaseTone(phaseIndex)));
}
