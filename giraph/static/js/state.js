/**
 * GIRAPH APPLICATION STATE STORE
 */

export const CONCURRENCY = 1; // Configurable concurrency limit for batch evaluation

export const state = {
  scenarios: [],
  filtered: [],
  filter: 'all',
  defense: 'giraph',      // 'giraph' (defense on) or 'allow_all' (defense off)
  model: 'mock',          // 'mock' | 'ollama:qwen3:8b'
  planner: 'deterministic',

  currentIndex: 0,        // Focused scenario panel index (0-based)
  isRunning: false,       // Master execution lock
  cancelRequested: false, // Cancellation flag
  activeScenarioId: null, // Scenario ID currently executing

  // Drawer / Inspection
  selectedScenario: null,
  activeDrawerTab: 'audit',

  // Summary & Progress Telemetry
  metrics: {
    total: 0,
    evaluated: 0,
    blocked: 0,
    leaked: 0,
    errors: 0,
    startTime: null,
    durationMs: 0,
  }
};

export function setScenarios(list) {
  state.scenarios = list;
  applyFilter(state.filter);
}

export function applyFilter(filter) {
  state.filter = filter;
  if (filter === 'all') {
    state.filtered = [...state.scenarios];
  } else if (filter === 'public') {
    state.filtered = state.scenarios.filter(s => s.split === 'public');
  } else if (filter === 'validation') {
    state.filtered = state.scenarios.filter(s => s.split === 'validation');
  } else if (filter === 'attacks') {
    state.filtered = state.scenarios.filter(s => s.attack_present);
  } else if (filter === 'benign') {
    state.filtered = state.scenarios.filter(s => !s.attack_present);
  }
  state.currentIndex = Math.min(state.currentIndex, Math.max(0, state.filtered.length - 1));
  recalculateMetrics();
}

export function recalculateMetrics() {
  let evaluated = 0;
  let blocked = 0;
  let leaked = 0;
  let errors = 0;

  state.scenarios.forEach(s => {
    const res = s.latest_result;
    if (!res) return;
    evaluated++;
    if (res.outcome?.error) {
      errors++;
    } else if (res.outcome?.attack_present) {
      if (res.outcome.attack_success || res.outcome.critical_violation) {
        leaked++;
      } else {
        blocked++;
      }
    } else {
      // Benign workload
      if (res.outcome?.task_success && !res.outcome?.critical_violation) {
        blocked++; // Successfully protected/conformed
      } else {
        leaked++;
      }
    }
  });

  state.metrics.total = state.scenarios.length;
  state.metrics.evaluated = evaluated;
  state.metrics.blocked = blocked;
  state.metrics.leaked = leaked;
  state.metrics.errors = errors;
}

export function resetRunMetrics() {
  state.metrics.evaluated = 0;
  state.metrics.blocked = 0;
  state.metrics.leaked = 0;
  state.metrics.errors = 0;
  state.metrics.startTime = performance.now();
  state.metrics.durationMs = 0;
}
