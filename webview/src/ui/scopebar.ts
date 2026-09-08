/**
 * The scope's two chrome surfaces, kept together because they are one control:
 * the BREADCRUMB (what is scoped, how deep, how much of the project, and the way
 * out) and the PICKER (how to get there).
 *
 * Keeping them in one composite is what lets `app.ts` grow by a handful of lines
 * for a whole feature rather than by a panel.
 */

import { Breadcrumb } from './breadcrumb.js';
import { ScopePicker } from './scopepicker.js';
import type { MLGraph, View } from '../types.js';

export interface ScopeBarCallbacks {
  /** `spec: null` means Everything. */
  onPick(spec: string | null, depth?: number): void;
  onClear(): void;
  onDepth(delta: number): void;
  onCopy(spec: string): void;
}

export class ScopeBar {
  readonly breadcrumb: Breadcrumb;
  readonly picker: ScopePicker;

  constructor(cb: ScopeBarCallbacks) {
    this.breadcrumb = new Breadcrumb({
      onClear: () => cb.onClear(),
      onDepth: (delta) => cb.onDepth(delta),
      onCopy: (spec) => cb.onCopy(spec),
    });
    this.picker = new ScopePicker({
      onPick: (spec, depth) => cb.onPick(spec, depth),
      onClose: () => this.picker.hide(),
    });
  }

  get pickerOpen(): boolean {
    return this.picker.open;
  }

  update(view: View | null, graph: MLGraph | null, spec: string | null, depth: number, truncated: boolean): void {
    this.breadcrumb.update(view, truncated);
    this.picker.update({ graph, spec, depth });
  }

  togglePicker(graph: MLGraph | null, spec: string | null, depth: number): void {
    if (this.picker.open) {
      this.picker.hide();
      return;
    }
    this.picker.show({ graph, spec, depth });
  }

  closePicker(): boolean {
    if (!this.picker.open) return false;
    this.picker.hide();
    return true;
  }
}
