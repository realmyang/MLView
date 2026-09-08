/**
 * Wall-clock budgets that survive a slower machine (HEALTH-03).
 *
 * `layout.test.mjs` budgets 300 ms for a 150-node / 300-edge layout. That layout
 * measures ~113 ms on the machine the budget was set on and ~225 ms on the one
 * the roadmap audit used — 25% headroom, which on a shared 2-core CI runner is a
 * coin flip. Raising the constant would weaken the gate everywhere to fix it in
 * one place.
 *
 * So the budget is expressed as a *ratio against a calibration workload run in
 * the same process*: a fixed arithmetic loop that took REFERENCE_MS on the
 * machine the budgets were written on. A machine half the speed measures twice
 * the calibration and gets twice the budget; a machine as fast gets exactly the
 * budget that was written down. The regression the gate exists to catch — layout
 * getting algorithmically slower — moves the measurement without moving the
 * calibration, so it still fails.
 *
 * Two escape hatches on top:
 *   · `CI=true` doubles the result, because a hosted runner's *variance* (noisy
 *     neighbours, a stolen scheduling quantum) is not something a steady-state
 *     calibration can see.
 *   · `MLVIEW_PERF_BUDGET_MS=<n>` replaces the budget outright, for bisecting a
 *     regression or for a machine whose calibration is not representative.
 */

/** The calibration loop's time on the reference machine (Node 20, Windows 11). */
const REFERENCE_MS = 40;

/** Never scale past this, or a wildly mismeasured machine gets a free pass. */
const MAX_FACTOR = 8;

/** Fixed work: no allocation, no I/O, nothing the optimizer can elide. */
function referenceWorkload() {
  let acc = 0;
  for (let i = 1; i <= 6000000; i++) acc += Math.sqrt(i) % 7;
  return acc;
}

let cachedFactor = null;

/** How much slower this process is than the machine the budgets were set on. */
export function machineFactor() {
  if (cachedFactor !== null) return cachedFactor;
  referenceWorkload(); // warm-up: this pass measures the JIT, not the machine
  let best = Infinity;
  for (let run = 0; run < 3; run++) {
    const started = performance.now();
    referenceWorkload();
    best = Math.min(best, performance.now() - started);
  }
  cachedFactor = Math.min(MAX_FACTOR, Math.max(1, best / REFERENCE_MS));
  return cachedFactor;
}

/** The budget in ms for a measurement that costs `baseMs` on the reference machine. */
export function budgetMs(baseMs) {
  const override = Number(process.env.MLVIEW_PERF_BUDGET_MS);
  if (Number.isFinite(override) && override > 0) return override;
  const ciSlack = process.env.CI ? 2 : 1;
  return Math.round(baseMs * machineFactor() * ciSlack);
}

/** The assertion message: what was measured, against what, and why that budget. */
export function budgetReport(what, elapsedMs, baseMs) {
  const budget = budgetMs(baseMs);
  if (Number(process.env.MLVIEW_PERF_BUDGET_MS) > 0) {
    return what + ' took ' + elapsedMs + ' ms (budget ' + budget + ' ms, MLVIEW_PERF_BUDGET_MS)';
  }
  return (
    what + ' took ' + elapsedMs + ' ms (budget ' + budget + ' ms = ' + baseMs +
    ' ms base x ' + machineFactor().toFixed(2) + ' machine factor' +
    (process.env.CI ? ' x 2 for CI' : '') + ')'
  );
}
