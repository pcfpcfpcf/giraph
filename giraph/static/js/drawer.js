/**
 * GIRAPH EXPLICATIVE LOGS WORKSTATION
 * Dedicated full-screen situation analyzer with human-readable titles and plain-English security explanations.
 */

import { state } from './state.js';
import { executeScenario } from './runner.js';
import { scrollToIndex } from './horizontal-scroll.js';

let inspectorOverlay = null;
let telemetryViewport = null;
let activeTab = 'audit'; // 'audit' | 'json'

export function initDrawer() {
  inspectorOverlay = document.getElementById('fullscreen-inspector');
  telemetryViewport = document.getElementById('insp-telemetry-viewport');

  const closeBtn = document.getElementById('insp-btn-close');
  if (closeBtn) closeBtn.onclick = closeInspector;

  const prevBtn = document.getElementById('insp-btn-prev');
  if (prevBtn) prevBtn.onclick = prevScenario;

  const nextBtn = document.getElementById('insp-btn-next');
  if (nextBtn) nextBtn.onclick = nextScenario;

  const execBtn = document.getElementById('insp-btn-execute');
  if (execBtn) {
    execBtn.onclick = async () => {
      if (!state.selectedScenario || state.selectedScenario.isRunning) return;
      execBtn.disabled = true;
      execBtn.innerText = '[TESTING...]';
      await executeScenario(state.selectedScenario.id);
      execBtn.disabled = false;
      execBtn.innerText = '[RE-TEST SITUATION]';
      renderInspector();
    };
  }

  // Telemetry Tab Switching (Explicative vs Raw JSON)
  const tabs = document.querySelectorAll('.telemetry-tab');
  tabs.forEach(tab => {
    tab.onclick = () => {
      tabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      activeTab = tab.dataset.tab;
      renderActiveTab();
    };
  });

  // Global Keydown Handler for Fullscreen Inspection Navigation
  window.addEventListener('keydown', (e) => {
    if (!document.body.classList.contains('inspector-open')) return;

    if (e.key === 'Escape') {
      e.preventDefault();
      closeInspector();
    } else if (e.key === '[' || (e.key === 'ArrowLeft' && e.altKey)) {
      e.preventDefault();
      prevScenario();
    } else if (e.key === ']' || (e.key === 'ArrowRight' && e.altKey)) {
      e.preventDefault();
      nextScenario();
    }
  });

  window.addEventListener('open-drawer', e => openInspector(e.detail.scenarioId));
  window.addEventListener('close-drawer', closeInspector);
  window.addEventListener('scenario-complete', e => {
    if (state.selectedScenario && state.selectedScenario.id === e.detail.scenarioId) {
      renderInspector();
    }
  });
}

export function openDrawer(scenarioId) {
  openInspector(scenarioId);
}

export function closeDrawer() {
  closeInspector();
}

export function openInspector(scenarioId) {
  const scenario = state.scenarios.find(s => s.id === scenarioId);
  if (!scenario) return;

  state.selectedScenario = scenario;
  activeTab = 'audit';
  document.body.classList.add('inspector-open');

  if (inspectorOverlay) {
    inspectorOverlay.classList.add('active');
  }

  renderInspector();
}

export function closeInspector() {
  document.body.classList.remove('inspector-open');
  if (inspectorOverlay) {
    inspectorOverlay.classList.remove('active');
  }
}

function nextScenario() {
  if (!state.selectedScenario) return;
  const list = state.filtered;
  const currIdx = list.findIndex(s => s.id === state.selectedScenario.id);
  if (currIdx < list.length - 1) {
    const next = list[currIdx + 1];
    scrollToIndex(currIdx + 1);
    openInspector(next.id);
  }
}

function prevScenario() {
  if (!state.selectedScenario) return;
  const list = state.filtered;
  const currIdx = list.findIndex(s => s.id === state.selectedScenario.id);
  if (currIdx > 0) {
    const prev = list[currIdx - 1];
    scrollToIndex(currIdx - 1);
    openInspector(prev.id);
  }
}

export function renderInspector() {
  const s = state.selectedScenario;
  if (!s) return;

  const res = s.latest_result;
  const outcome = res?.outcome || {};
  const decisions = res?.trace || outcome.decisions || [];
  const graderResults = outcome.grader_results || [];

  const list = state.filtered;
  const currIdx = list.findIndex(item => item.id === s.id);
  const total = list.length;
  const numStr = String(currIdx >= 0 ? currIdx + 1 : 1).padStart(2, '0');
  const totalStr = String(total).padStart(2, '0');

  // 1. Title: The real name of the situation!
  const titleEl = document.getElementById('insp-title');
  if (titleEl) {
    titleEl.textContent = s.title || s.id;
  }

  const numEl = document.getElementById('insp-num');
  if (numEl) numEl.textContent = `SITUATION ${numStr} / ${totalStr}`;

  const domainEl = document.getElementById('insp-domain');
  if (domainEl) domainEl.textContent = (s.domain || 'SYSTEM').toUpperCase();

  const typeBadge = document.getElementById('insp-type-badge');
  if (typeBadge) {
    typeBadge.className = `attack-spec-tag ${s.attack_present ? 'adversary' : 'benign'}`;
    typeBadge.textContent = s.attack_present ? 'ADVERSARIAL ATTACK' : 'BENIGN WORKLOAD';
  }

  // Status Stamp in Header
  const statusStamp = document.getElementById('insp-status-stamp');
  const statusInfo = getExplicativeStatus(s, outcome);
  if (statusStamp) {
    statusStamp.className = `state-stamp ${statusInfo.stampClass}`;
    statusStamp.textContent = statusInfo.text;
  }

  // Stepper buttons disabled state
  const prevBtn = document.getElementById('insp-btn-prev');
  if (prevBtn) prevBtn.disabled = currIdx <= 0;
  const nextBtn = document.getElementById('insp-btn-next');
  if (nextBtn) nextBtn.disabled = currIdx >= list.length - 1;

  // 2. Explicative Overview Banner
  const kpiVerdict = document.getElementById('insp-kpi-verdict');
  if (kpiVerdict) {
    kpiVerdict.className = `kpi-value ${statusInfo.textClass}`;
    kpiVerdict.textContent = statusInfo.headline;
  }

  const kpiSteps = document.getElementById('insp-kpi-steps');
  if (kpiSteps) {
    kpiSteps.textContent = res ? `${outcome.steps || decisions.length} ACTIONS EVALUATED` : 'UNTESTED';
  }

  const kpiDefense = document.getElementById('insp-kpi-defense');
  if (kpiDefense) {
    const isGiraph = (res?.defense || state.defense) === 'giraph';
    kpiDefense.textContent = isGiraph ? 'GIRAPH CONFORMANCE (ACTIVE DEFENSE)' : 'ALLOW_ALL BASELINE (DEFENSE OFF)';
  }

  // 3. Left Pane: Situation Context Dossier
  const promptBox = document.getElementById('insp-prompt-text');
  if (promptBox) {
    promptBox.textContent = s.prompt || s.description || '(User prompt unavailable)';
  }

  const threatDesc = document.getElementById('insp-attack-objective');
  if (threatDesc) {
    if (s.attack_present) {
      threatDesc.innerHTML = `
        <div style="color: #fda4af; font-weight: 700; margin-bottom: 4px;">[ADVERSARY INJECTION ACTIVE]</div>
        <div>${escapeHtml(s.objective || 'User request contains out-of-policy instructions aiming to breach data isolation or trigger unauthorized side-effects.')}</div>
      `;
    } else {
      threatDesc.innerHTML = `
        <div style="color: #a7f3d0; font-weight: 700; margin-bottom: 4px;">[BENIGN WORKLOAD]</div>
        <div>Legitimate operational task. The defense validates that normal workflow actions succeed without unnecessary blockage.</div>
      `;
    }
  }

  // Tools Surface
  const toolsList = document.getElementById('insp-tools-list');
  if (toolsList) {
    const tools = s.allowed_tools || [];
    toolsList.innerHTML = tools.length
      ? tools.map(t => `<span class="tool-token">${escapeHtml(t)}</span>`).join('')
      : `<span class="tool-token">NO EXTERNAL TOOLS</span>`;
  }

  // Graders List
  const gradersList = document.getElementById('insp-graders-list');
  if (gradersList) {
    if (graderResults.length === 0) {
      gradersList.innerHTML = `<div style="color: var(--text-dim); font-size: 11px;">No grader results for this run.</div>`;
    } else {
      gradersList.innerHTML = graderResults.map(g => `
        <div class="dossier-grader-row">
          <span class="${g.passed ? 'grader-pass-tag' : 'grader-fail-tag'}">${g.passed ? '[PASS]' : '[FAIL]'}</span>
          <span style="color: var(--text-primary); font-size: 11px;">${escapeHtml(g.condition || '')}</span>
        </div>
      `).join('');
    }
  }

  // 4. Right Pane: Active Telemetry View
  const tabs = document.querySelectorAll('.telemetry-tab');
  tabs.forEach(t => {
    if (t.dataset.tab === activeTab) t.classList.add('active');
    else t.classList.remove('active');
  });

  renderActiveTab();
}

function renderActiveTab() {
  if (!telemetryViewport || !state.selectedScenario) return;

  const s = state.selectedScenario;
  const res = s.latest_result;

  if (!res) {
    telemetryViewport.innerHTML = `
      <div style="padding: 64px 32px; text-align: center; color: var(--text-secondary); font-family: var(--font-mono);">
        <p style="font-size: 14px; font-weight: 700; color: var(--text-pure); margin-bottom: 8px;">SITUATION NOT YET EVALUATED IN THIS SESSION</p>
        <p style="color: var(--text-muted); font-size: 11.5px; margin-bottom: 24px;">Run the security test to generate live decision telemetry and step-by-step logs.</p>
        <button class="btn-command primary" id="insp-tab-run-btn" style="display: inline-flex; padding: 10px 22px;">[RUN TEST FOR THIS SITUATION]</button>
      </div>
    `;
    const runBtn = document.getElementById('insp-tab-run-btn');
    if (runBtn) {
      runBtn.onclick = async () => {
        runBtn.disabled = true;
        runBtn.innerText = '[RUNNING TEST...]';
        await executeScenario(s.id);
        renderInspector();
      };
    }
    return;
  }

  if (activeTab === 'audit') {
    renderExplicativeLogs(s, res);
  } else {
    renderRawJson(s, res);
  }
}

function renderExplicativeLogs(scenario, res) {
  const decisions = res.trace || res.outcome?.decisions || [];

  if (decisions.length === 0) {
    telemetryViewport.innerHTML = `
      <div style="padding: 48px; color: var(--text-muted); font-family: var(--font-mono); text-align: center;">
        NO DECISION INTERCEPTIONS RECORDED (DIRECT COMPLETION)
      </div>
    `;
    return;
  }

  let html = `
    <div style="display: flex; flex-direction: column; gap: 14px;">
  `;

  decisions.forEach((d, idx) => {
    const stepNum = String(d.step ?? (idx + 1)).padStart(2, '0');
    const toolName = d.action?.tool || d.action?.type || d.tool || 'action';
    const args = d.action?.arguments;
    const verdict = String(d.decision || 'allow').toLowerCase();
    const effect = d.effect || 'none';
    const auth = d.authority?.level || 'authenticated_user';

    const authLabel = auth === 'authenticated_user' ? 'AUTHENTICATED USER'
      : (auth === 'untrusted_content' ? 'UNTRUSTED INJECTION DETECTED' : auth.toUpperCase());

    const authClass = auth === 'authenticated_user' ? 'text-blocked'
      : (auth === 'untrusted_content' ? 'text-leaked' : '');

    // Generate plain-English explicative explanation
    let plainExplanation = d.explanation || '';
    if (verdict === 'block') {
      plainExplanation = d.explanation || `Tool call '${toolName}' was blocked because it falls outside the authorized plan envelope and attempts an untrusted effect.`;
    } else if (verdict === 'rewrite') {
      plainExplanation = d.explanation || `Tool call was safely rewritten to restrict destination and sanitize out-of-policy parameters.`;
    } else if (verdict === 'allow') {
      plainExplanation = d.explanation || `Action verified against the legitimate plan envelope; authorized for execution.`;
    }

    html += `
      <div class="explicative-log-card ${verdict}">
        <div class="log-card-header">
          <div style="display: flex; align-items: center; gap: 12px;">
            <span class="log-step-num">STEP ${stepNum}</span>
            <span class="log-tool-name">${escapeHtml(toolName)}</span>
            <span class="verdict-tag ${verdict}">[${verdict.toUpperCase()}]</span>
          </div>
          <div style="font-family: var(--font-mono); font-size: 11px; color: var(--text-muted);">
            EFFECT: <strong style="color: var(--text-primary);">${escapeHtml(effect)}</strong>
          </div>
        </div>

        <div class="log-card-body">
          <div class="log-meta-row">
            <div>
              <span class="log-meta-label">CALLER AUTHORITY:</span>
              <span class="log-meta-val ${authClass}">${escapeHtml(authLabel)}</span>
            </div>
            <div>
              <span class="log-meta-label">REASON CODE:</span>
              <span class="log-meta-val">${escapeHtml((d.reason_codes || []).join(', ') || 'VERIFIED')}</span>
            </div>
          </div>

          ${args && Object.keys(args).length ? `
            <div class="log-args-block">
              <span class="log-args-label">PARAMETERS / ARGUMENTS:</span>
              <pre class="log-args-code">${escapeHtml(JSON.stringify(args, null, 2))}</pre>
            </div>
          ` : ''}

          <div class="log-rationale-box">
            <span class="log-rationale-label">DEFENSE RATIONALE:</span>
            <span class="log-rationale-text">${escapeHtml(plainExplanation)}</span>
          </div>
        </div>
      </div>
    `;
  });

  html += `</div>`;
  telemetryViewport.innerHTML = html;
}

function renderRawJson(scenario, res) {
  const jsonStr = JSON.stringify(res, null, 2);

  telemetryViewport.innerHTML = `
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; font-family: var(--font-mono);">
      <span style="font-size: 11.5px; color: var(--text-muted);">RAW SECURITY AUDIT TELEMETRY (JSON)</span>
      <button class="btn-command" id="btn-copy-raw">[COPY RAW JSON]</button>
    </div>
    <div class="code-block-viewer">${escapeHtml(jsonStr)}</div>
  `;

  const copyBtn = document.getElementById('btn-copy-raw');
  if (copyBtn) {
    copyBtn.onclick = () => {
      navigator.clipboard.writeText(jsonStr);
      copyBtn.innerText = '[COPIED]';
      setTimeout(() => { copyBtn.innerText = '[COPY RAW JSON]'; }, 2000);
    };
  }
}

function getExplicativeStatus(scenario, outcome) {
  if (scenario.isRunning) {
    return { stampClass: 'running', text: '[TESTING...]', headline: 'TEST EXECUTION IN PROGRESS', textClass: '' };
  }
  if (!scenario.latest_result) {
    return { stampClass: 'idle', text: '[UNTESTED]', headline: 'SITUATION UNTESTED · READY FOR EVALUATION', textClass: '' };
  }
  if (outcome.error) {
    return { stampClass: 'error', text: '[ERROR]', headline: `EXECUTION ERROR: ${outcome.errorMessage || 'FAILED'}`, textClass: 'text-error' };
  }

  if (outcome.attack_present) {
    if (outcome.attack_success || outcome.critical_violation) {
      return { stampClass: 'failed', text: '[LEAKED]', headline: 'SECURITY BREACH: ADVERSARY PAYLOAD EXECUTED', textClass: 'text-leaked' };
    } else {
      return { stampClass: 'passed', text: '[STOPPED]', headline: 'DEFENSE HELD: THE ATTACK DID NOT SUCCEED', textClass: 'text-blocked' };
    }
  } else {
    if (outcome.task_success && !outcome.critical_violation) {
      return { stampClass: 'passed', text: '[CONFORMED]', headline: 'BENIGN WORKLOAD: LEGITIMATE TASK CONFORMED & COMPLETED', textClass: 'text-blocked' };
    } else {
      return { stampClass: 'failed', text: '[TASK FAILED]', headline: outcome.critical_violation ? 'CRITICAL VIOLATION ON A BENIGN TASK' : 'BENIGN TASK DID NOT COMPLETE', textClass: 'text-leaked' };
    }
  }
}

function escapeHtml(str) {
  return String(str ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}
