/**
 * GIRAPH TEST RUNNER ENGINE
 * Handles individual execution, concurrent batch orchestration, and cancellation.
 */

import { state, CONCURRENCY, recalculateMetrics } from './state.js';

export async function executeScenario(scenarioId, { defense, model, planner } = {}) {
  const def = defense || state.defense;
  const mod = model || state.model;
  const plan = planner || state.planner;

  const target = state.scenarios.find(s => s.id === scenarioId);
  if (target) {
    target.isRunning = true;
    target.hasError = false;
  }

  state.activeScenarioId = scenarioId;

  // Dispatch custom event for UI updates
  window.dispatchEvent(new CustomEvent('scenario-start', { detail: { scenarioId } }));

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 95000); // 95s defensive timeout

  try {
    const res = await fetch('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scenario_id: scenarioId, defense: def, model: mod, planner: plan }),
      signal: controller.signal
    });

    clearTimeout(timeoutId);

    if (!res.ok) {
      throw new Error(`Server returned HTTP ${res.status}: ${res.statusText}`);
    }

    const data = await res.json();
    if (target) {
      target.latest_result = data;
      target.isRunning = false;
    }
    recalculateMetrics();
    window.dispatchEvent(new CustomEvent('scenario-complete', { detail: { scenarioId, result: data } }));
    return data;
  } catch (err) {
    clearTimeout(timeoutId);
    console.error(`Scenario [${scenarioId}] execution error:`, err);
    if (target) {
      target.isRunning = false;
      target.hasError = true;
      target.latest_result = {
        scenario_id: scenarioId,
        defense: def,
        model: mod,
        outcome: {
          scenario_id: scenarioId,
          error: true,
          task_success: false,
          attack_success: false,
          critical_violation: true,
          errorMessage: err.name === 'AbortError' ? 'Execution Timed Out (95s)' : err.message,
          steps: 0,
          decisions: [],
          grader_results: [{ condition: 'Execution Pipeline', passed: false, detail: err.message }]
        },
        trace: [],
        events: []
      };
    }
    recalculateMetrics();
    window.dispatchEvent(new CustomEvent('scenario-complete', { detail: { scenarioId, error: err } }));
    return target ? target.latest_result : null;
  } finally {
    if (state.activeScenarioId === scenarioId) {
      state.activeScenarioId = null;
    }
  }
}

export async function runAllScenarios({ onProgress, onComplete } = {}) {
  if (state.isRunning) return;

  state.isRunning = true;
  state.cancelRequested = false;
  state.metrics.startTime = performance.now();

  window.dispatchEvent(new CustomEvent('batch-start'));

  const queue = [...state.filtered];
  let processed = 0;
  const total = queue.length;

  // Concurrency pool runner
  async function worker() {
    while (queue.length > 0) {
      if (state.cancelRequested) break;
      const scenario = queue.shift();
      if (!scenario) break;

      await executeScenario(scenario.id);
      processed++;

      if (onProgress) {
        onProgress(processed, total, scenario.id);
      }
      window.dispatchEvent(new CustomEvent('batch-progress', {
        detail: { processed, total, scenarioId: scenario.id }
      }));
    }
  }

  // Launch workers according to CONCURRENCY limit
  const activeWorkers = [];
  const workerCount = Math.max(1, Math.min(CONCURRENCY, queue.length));
  for (let i = 0; i < workerCount; i++) {
    activeWorkers.push(worker());
  }

  await Promise.all(activeWorkers);

  state.metrics.durationMs = Math.round(performance.now() - state.metrics.startTime);
  state.isRunning = false;

  const cancelled = state.cancelRequested;
  state.cancelRequested = false;

  window.dispatchEvent(new CustomEvent('batch-finish', { detail: { cancelled, durationMs: state.metrics.durationMs } }));

  if (onComplete) {
    onComplete({ cancelled, durationMs: state.metrics.durationMs });
  }
}

export function stopBatchRun() {
  if (state.isRunning) {
    state.cancelRequested = true;
    window.dispatchEvent(new CustomEvent('batch-abort-requested'));
  }
}
