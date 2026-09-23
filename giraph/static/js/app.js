/**
 * GIRAPH WEB APPLICATION ORCHESTRATOR
 * Tightened front-end logic: uncluttered, highly readable, no filler sections.
 */

import { state, setScenarios, applyFilter, recalculateMetrics, CONCURRENCY } from './state.js';
import { executeScenario, runAllScenarios, stopBatchRun } from './runner.js';
import { initHorizontalScroll, recalculateDimensions, scrollToIndex, scrollToScenario } from './horizontal-scroll.js';
import { initDrawer, openDrawer } from './drawer.js';

// DOM Elements
const trackEl = document.getElementById('horizontal-track');
const btnMasterRun = document.getElementById('btn-master-run');
const defenseToggle = document.getElementById('defense-toggle');
const defenseStatusLabel = document.getElementById('defense-status-label');
const filterBtns = document.querySelectorAll('.filter-tabs .tab-btn');
const railPrevBtn = document.getElementById('rail-prev');
const railNextBtn = document.getElementById('rail-next');

// Telemetry Elements
const countTotal = document.getElementById('telemetry-total');
const countBlocked = document.getElementById('telemetry-blocked');
const countLeaked = document.getElementById('telemetry-leaked');
const countBenignFailed = document.getElementById('telemetry-benign-failed');
const progressFill = document.getElementById('harness-progress-fill');

// Summary Modal Elements
const summaryBackdrop = document.getElementById('summary-backdrop');
const summaryCloseBtn = document.getElementById('summary-close-btn');

export async function initApp() {
  console.log('[GIRAPH] Initializing Security Runner Dashboard...');

  initHorizontalScroll();
  initDrawer();
  wireEventHandlers();

  await fetchScenarios();
}

async function fetchScenarios() {
  try {
    const res = await fetch('/api/scenarios');
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    const scenarios = await res.json();
    setScenarios(scenarios);
    renderPanels();
    updateTelemetryCounters();
    recalculateDimensions();
  } catch (err) {
    console.error('[GIRAPH] Failed to load scenarios:', err);
    if (trackEl) {
      trackEl.innerHTML = `
        <div style="padding: 48px; color: var(--verdict-leaked); font-family: var(--font-mono); text-align: center;">
          <p style="font-weight: 700; margin-bottom: 8px;">[SYSTEM ERROR] FAILED TO LOAD SITUATIONS</p>
          <p style="color: var(--text-muted); font-size: 11px;">${err.message}</p>
        </div>
      `;
    }
  }
}

export function getScenarioStatus(scenario) {
  if (scenario.isRunning) {
    return { stamp: 'running', text: '[TESTING...]', label: 'IN PROGRESS' };
  }
  const res = scenario.latest_result;
  if (!res) {
    return { stamp: 'idle', text: '[UNTESTED]', label: 'READY TO RUN' };
  }
  if (res.outcome?.error) {
    return { stamp: 'error', text: '[ERROR]', label: 'SYSTEM ERROR' };
  }

  if (res.outcome?.attack_present) {
    if (res.outcome.attack_success || res.outcome.critical_violation) {
      return { stamp: 'failed', text: '[LEAKED]', label: 'ATTACK SUCCEEDED' };
    } else {
      return { stamp: 'passed', text: '[STOPPED]', label: 'DEFENSE HELD' };
    }
  } else {
    if (res.outcome?.task_success && !res.outcome?.critical_violation) {
      return { stamp: 'passed', text: '[CONFORMED]', label: 'BENIGN COMPLETED' };
    } else {
      return { stamp: 'failed', text: '[TASK FAILED]', label: res.outcome?.critical_violation ? 'CRITICAL VIOLATION' : 'BENIGN TASK FAILED' };
    }
  }
}

export function renderPanels() {
  if (!trackEl) return;
  trackEl.innerHTML = '';

  state.filtered.forEach((scenario, idx) => {
    const status = getScenarioStatus(scenario);
    const panel = document.createElement('div');
    const tools = scenario.allowed_tools || [];
    const toolsHtml = tools.length
      ? tools.map(t => `<span class="tool-token">${escapeHtml(t)}</span>`).join('')
      : `<span class="tool-token-none">NONE (INTERNAL AGENT)</span>`;

    panel.className = `scenario-panel ${status.stamp} ${scenario.isRunning ? 'is-running' : ''} ${idx === state.currentIndex ? 'is-focused' : ''}`;
    panel.dataset.id = scenario.id;
    panel.dataset.index = idx;

    const numStr = String(idx + 1).padStart(2, '0');
    const attackTag = scenario.attack_present
      ? '<span class="attack-spec-tag adversary">ADVERSARIAL ATTACK</span>'
      : '<span class="attack-spec-tag benign">BENIGN WORKLOAD</span>';

    const stepsVal = scenario.latest_result?.outcome?.steps;
    const defVal = scenario.latest_result?.defense ? scenario.latest_result.defense.toUpperCase() : null;

    let statusLine = 'Awaiting evaluation run';
    if (scenario.latest_result) {
      if (status.stamp === 'passed') {
        statusLine = scenario.attack_present
          ? `Defense Held &middot; ${stepsVal || 0} actions evaluated &middot; ${defVal || 'GIRAPH'}`
          : `Task Succeeded &middot; Conformed to authorized plan`;
      } else if (status.stamp === 'failed') {
        statusLine = scenario.attack_present
          ? `Security Breach &middot; Attack payload executed &middot; ${defVal || 'ALLOW_ALL'}`
          : (scenario.latest_result?.outcome?.critical_violation
            ? `Critical violation &middot; ${defVal || 'ALLOW_ALL'}`
            : `Task did not complete &middot; ${defVal || 'GIRAPH'}`);
      } else if (status.stamp === 'error') {
        statusLine = `Execution Error: ${scenario.latest_result?.outcome?.errorMessage || 'Failed'}`;
      }
    }

    panel.innerHTML = `
      <div class="panel-header">
        <div class="header-meta-group">
          <div style="display: flex; align-items: center; gap: 10px;">
            <span class="panel-index">${numStr}</span>
            <span class="tag-domain">${escapeHtml((scenario.domain || 'SYSTEM').toUpperCase())}</span>
          </div>
          <div class="meta-tags-row">
            ${attackTag}
          </div>
        </div>
        <div class="state-stamp ${status.stamp}">
          ${status.text}
        </div>
      </div>

      <div class="panel-body">
        <h2 class="scenario-heading">${escapeHtml(scenario.title || scenario.id)}</h2>

        <div class="prompt-narrative">
          <div class="prompt-narrative-label">SITUATION REQUEST (USER PROMPT)</div>
          <div class="prompt-narrative-text">${escapeHtml(scenario.prompt || scenario.description || '(Prompt unavailable)')}</div>
        </div>

        ${scenario.attack_present && scenario.objective ? `
          <div class="threat-highlight-line">
            <span class="threat-highlight-label">ATTACK OBJECTIVE:</span>
            <span class="threat-highlight-text">${escapeHtml(scenario.objective)}</span>
          </div>
        ` : ''}

        <div class="card-tools-row">
          <span class="card-tools-label">ENVIRONMENT TOOLS:</span>
          <div class="card-tools-list">${toolsHtml}</div>
        </div>

        <div class="telemetry-strip">
          <div class="telemetry-stat-cell">
            <span class="stat-label">OUTCOME</span>
            <span class="stat-value ${status.stamp === 'passed' ? 'text-blocked' : (status.stamp === 'failed' ? 'text-leaked' : '')}">${status.label}</span>
          </div>
          <div class="telemetry-stat-cell">
            <span class="stat-label">EVALUATED ACTIONS</span>
            <span class="stat-value">${stepsVal !== undefined ? `${stepsVal} STEPS` : '—'}</span>
          </div>
          <div class="telemetry-stat-cell">
            <span class="stat-label">ACTIVE DEFENSE</span>
            <span class="stat-value">${defVal || state.defense.toUpperCase()}</span>
          </div>
        </div>

        </div>
      </div>

      <div class="panel-footer">
        <button class="btn-card primary btn-run-single" data-id="${scenario.id}">
          ${scenario.isRunning ? '[TESTING...]' : '[RUN TEST]'}
        </button>
        <button class="btn-card btn-inspect" data-id="${scenario.id}">
          [INSPECT LOGS]
        </button>
      </div>
    `;

    // Panel click focuses it
    panel.addEventListener('click', (e) => {
      if (e.target.closest('button')) return;
      scrollToIndex(idx);
    });

    // Run single button
    const runBtn = panel.querySelector('.btn-run-single');
    runBtn.addEventListener('click', async (e) => {
      e.stopPropagation();
      if (scenario.isRunning || state.isRunning) return;
      await executeScenario(scenario.id);
    });

    // Inspect logs button
    const inspectBtn = panel.querySelector('.btn-inspect');
    inspectBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      openDrawer(scenario.id);
    });

    trackEl.appendChild(panel);
  });
}

function updateScenarioPanel(scenarioId) {
  const panel = trackEl?.querySelector(`.scenario-panel[data-id="${scenarioId}"]`);
  const scenario = state.scenarios.find(s => s.id === scenarioId);
  if (!panel || !scenario) return;

  const status = getScenarioStatus(scenario);

  if (scenario.isRunning) {
    panel.classList.add('is-running');
  } else {
    panel.classList.remove('is-running');
  }

  panel.classList.remove('passed', 'failed', 'error', 'idle');
  panel.classList.add(status.stamp);

  // Update stamp
  const stampEl = panel.querySelector('.state-stamp');
  if (stampEl) {
    stampEl.className = `state-stamp ${status.stamp}`;
    stampEl.textContent = status.text;
  }

  // Update telemetry strip
  const cells = panel.querySelectorAll('.telemetry-stat-cell .stat-value');
  if (cells.length >= 3) {
    cells[0].textContent = status.label;
    cells[0].className = `stat-value ${status.stamp === 'passed' ? 'text-blocked' : (status.stamp === 'failed' ? 'text-leaked' : '')}`;
    cells[1].textContent = scenario.latest_result?.outcome?.steps !== undefined ? `${scenario.latest_result.outcome.steps} STEPS` : '—';
    cells[2].textContent = scenario.latest_result?.defense ? scenario.latest_result.defense.toUpperCase() : state.defense.toUpperCase();
  }

  // Update single run button label
  const runBtn = panel.querySelector('.btn-run-single');
  if (runBtn) {
    runBtn.textContent = scenario.isRunning ? '[TESTING...]' : '[RUN TEST]';
  }
}

function updateTelemetryCounters() {
  if (countTotal) countTotal.textContent = state.metrics.total;
  if (countBlocked) countBlocked.textContent = state.metrics.blocked;
  if (countLeaked) countLeaked.textContent = state.metrics.leaked;
  if (countBenignFailed) countBenignFailed.textContent = state.metrics.benignFailed;

  const totalCount = state.scenarios.length;
  const attacksCount = state.scenarios.filter(s => s.attack_present).length;
  const benignCount = state.scenarios.filter(s => !s.attack_present).length;

  filterBtns.forEach(btn => {
    const f = btn.dataset.filter;
    if (f === 'all') btn.textContent = `ALL [${totalCount}]`;
    else if (f === 'attacks') btn.textContent = `ATTACKS [${attacksCount}]`;
    else if (f === 'benign') btn.textContent = `BENIGN [${benignCount}]`;
  });

  if (btnMasterRun && !state.isRunning) {
    btnMasterRun.textContent = `RUN ALL [${state.filtered.length}]`;
  }
}

function wireEventHandlers() {
  // Filter tabs
  filterBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      filterBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      applyFilter(btn.dataset.filter);
      renderPanels();
      updateTelemetryCounters();
      recalculateDimensions();
    });
  });

  // Defense Toggle (giraph vs allow_all)
  if (defenseToggle) {
    defenseToggle.addEventListener('click', () => {
      if (state.defense === 'giraph') {
        state.defense = 'allow_all';
        defenseToggle.classList.add('off');
        if (defenseStatusLabel) defenseStatusLabel.textContent = 'DEFENSE: OFF (ALLOW_ALL)';
      } else {
        state.defense = 'giraph';
        defenseToggle.classList.remove('off');
        if (defenseStatusLabel) defenseStatusLabel.textContent = 'DEFENSE: GIRAPH (ON)';
      }
    });
  }

  // Master Run All / Stop Button
  if (btnMasterRun) {
    btnMasterRun.addEventListener('click', async () => {
      if (state.isRunning) {
        stopBatchRun();
      } else {
        await runAllScenarios({
          onProgress: (processed, total, scenarioId) => {
            if (progressFill) {
              const pct = (processed / total) * 100;
              progressFill.style.width = `${pct}%`;
            }
          },
          onComplete: ({ cancelled, durationMs }) => {
            showSummaryModal(cancelled, durationMs);
          }
        });
      }
    });
  }

  // Bottom Rail Navigation Buttons
  if (railPrevBtn) {
    railPrevBtn.addEventListener('click', () => {
      scrollToIndex(state.currentIndex - 1);
    });
  }
  if (railNextBtn) {
    railNextBtn.addEventListener('click', () => {
      scrollToIndex(state.currentIndex + 1);
    });
  }

  // Summary Modal Close
  if (summaryCloseBtn) {
    summaryCloseBtn.addEventListener('click', closeSummaryModal);
  }
  if (summaryBackdrop) {
    summaryBackdrop.addEventListener('click', (e) => {
      if (e.target === summaryBackdrop) closeSummaryModal();
    });
  }

  // Global Event Listeners
  window.addEventListener('scenario-start', (e) => {
    updateScenarioPanel(e.detail.scenarioId);
    updateTelemetryCounters();
  });

  window.addEventListener('scenario-complete', (e) => {
    updateScenarioPanel(e.detail.scenarioId);
    updateTelemetryCounters();
  });

  window.addEventListener('batch-start', () => {
    if (btnMasterRun) {
      btnMasterRun.textContent = '[STOP EXECUTION]';
      btnMasterRun.classList.add('is-running');
    }
    if (progressFill) progressFill.style.width = '0%';
  });

  window.addEventListener('batch-progress', (e) => {
    const { processed, total } = e.detail;
    if (progressFill) {
      progressFill.style.width = `${(processed / total) * 100}%`;
    }
    if (btnMasterRun) {
      btnMasterRun.textContent = `[STOP: ${processed}/${total}]`;
    }
    updateTelemetryCounters();
  });

  window.addEventListener('batch-finish', (e) => {
    if (btnMasterRun) {
      btnMasterRun.textContent = `RUN ALL [${state.filtered.length}]`;
      btnMasterRun.classList.remove('is-running');
    }
    updateTelemetryCounters();
  });

  window.addEventListener('batch-abort-requested', () => {
    if (btnMasterRun) {
      btnMasterRun.textContent = '[STOPPING...]';
    }
  });

  window.addEventListener('execute-current-scenario', async (e) => {
    if (!state.isRunning) {
      await executeScenario(e.detail.scenarioId);
    }
  });
}

function showSummaryModal(cancelled = false, durationMs = 0) {
  if (!summaryBackdrop) return;

  const durationSec = (durationMs / 1000).toFixed(1);
  const sumTotal = document.getElementById('sum-total');
  const sumBlocked = document.getElementById('sum-blocked');
  const sumLeaked = document.getElementById('sum-leaked');
  const sumBenignFailed = document.getElementById('sum-benign-failed');
  const sumDuration = document.getElementById('sum-duration');
  const sumStatus = document.getElementById('sum-status');

  if (sumTotal) sumTotal.textContent = state.metrics.total;
  if (sumBlocked) sumBlocked.textContent = state.metrics.blocked;
  if (sumLeaked) sumLeaked.textContent = state.metrics.leaked;
  if (sumBenignFailed) sumBenignFailed.textContent = state.metrics.benignFailed;
  if (sumDuration) sumDuration.textContent = `${durationSec}s`;
  if (sumStatus) {
    sumStatus.textContent = cancelled ? '[EVALUATION CANCELLED]' : '[EVALUATION RUN COMPLETE]';
    sumStatus.style.color = cancelled ? 'var(--verdict-error)' : 'var(--verdict-blocked)';
  }

  summaryBackdrop.classList.add('active');
}

function closeSummaryModal() {
  if (summaryBackdrop) {
    summaryBackdrop.classList.remove('active');
  }
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// Bootstrap when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initApp);
} else {
  initApp();
}
