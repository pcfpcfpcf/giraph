/**
 * DNA CAPITAL HORIZONTAL PINNED SCROLL CONTROLLER
 * Translates vertical wheel/trackpad/touch inputs into 60fps horizontal transforms.
 */

import { state } from './state.js';

let trackEl = null;
let stageEl = null;
let progressBarEl = null;
let counterEl = null;

let currentX = 0;
let targetX = 0;
let maxScroll = 0;
let panelStep = 0; // panelWidth + gap
let isUserInteracting = false;
let userInteractionTimer = null;
let isDragging = false;
let dragStartX = 0;
let dragStartScrollX = 0;

export function initHorizontalScroll() {
  trackEl = document.getElementById('horizontal-track');
  stageEl = document.getElementById('stage-container');
  progressBarEl = document.getElementById('harness-progress');
  counterEl = document.getElementById('specimen-counter');

  if (!trackEl || !stageEl) return;

  recalculateDimensions();
  window.addEventListener('resize', recalculateDimensions);

  // Wheel listener: converts vertical scroll into horizontal translation
  stageEl.addEventListener('wheel', handleWheel, { passive: false });

  // Drag listeners
  stageEl.addEventListener('mousedown', handleMouseDown);
  window.addEventListener('mousemove', handleMouseMove);
  window.addEventListener('mouseup', handleMouseUp);

  // Keyboard navigation
  window.addEventListener('keydown', handleKeyDown);

  // Listen to auto-scroll events when batch runner progresses
  window.addEventListener('scenario-start', e => {
    if (!isUserInteracting) {
      scrollToScenario(e.detail.scenarioId);
    }
  });

  updateFocus();
}

export function recalculateDimensions() {
  if (!trackEl) return;

  const panels = trackEl.querySelectorAll('.scenario-panel');
  if (panels.length === 0) return;

  const panelWidth = panels[0].offsetWidth;
  const gap = parseInt(window.getComputedStyle(trackEl).gap) || 32;
  panelStep = panelWidth + gap;

  // Maximum scroll distance
  maxScroll = Math.max(0, (panels.length - 1) * panelStep);

  // Align to current index
  scrollToIndex(state.currentIndex, { immediate: true });
}

function handleWheel(e) {
  // If inspector is open, don't hijack scroll
  if (document.body.classList.contains('inspector-open') || document.body.classList.contains('drawer-open')) return;

  // Respect reduced motion
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  e.preventDefault();
  flagUserInteraction();

  const delta = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
  targetX -= delta * 1.4;
  targetX = Math.max(-maxScroll, Math.min(0, targetX));

  applyTransform();
}

function handleMouseDown(e) {
  if (document.body.classList.contains('inspector-open') || document.body.classList.contains('drawer-open')) return;
  if (e.target.closest('.btn-card') || e.target.closest('select') || e.target.closest('button')) return;

  isDragging = true;
  dragStartX = e.clientX;
  dragStartScrollX = targetX;
  trackEl.classList.add('is-scrubbing');
  flagUserInteraction();
}

function handleMouseMove(e) {
  if (!isDragging) return;
  const deltaX = e.clientX - dragStartX;
  targetX = dragStartScrollX + deltaX * 1.5;
  targetX = Math.max(-maxScroll, Math.min(0, targetX));
  applyTransform({ immediate: true });
}

function handleMouseUp() {
  if (!isDragging) return;
  isDragging = false;
  trackEl.classList.remove('is-scrubbing');

  // Snap to nearest panel
  const nearestIndex = Math.round(Math.abs(targetX) / panelStep);
  scrollToIndex(nearestIndex);
}

function handleKeyDown(e) {
  if (document.body.classList.contains('inspector-open') || document.body.classList.contains('drawer-open')) {
    if (e.key === 'Escape') {
      window.dispatchEvent(new CustomEvent('close-drawer'));
    }
    return;
  }

  if (e.key === 'ArrowRight' || e.key === 'PageDown') {
    e.preventDefault();
    scrollToIndex(state.currentIndex + 1);
  } else if (e.key === 'ArrowLeft' || e.key === 'PageUp') {
    e.preventDefault();
    scrollToIndex(state.currentIndex - 1);
  } else if (e.key === 'Home') {
    e.preventDefault();
    scrollToIndex(0);
  } else if (e.key === 'End') {
    e.preventDefault();
    scrollToIndex(state.filtered.length - 1);
  } else if (e.key === ' ' || e.key === 'Enter') {
    e.preventDefault();
    const currentScenario = state.filtered[state.currentIndex];
    if (currentScenario) {
      window.dispatchEvent(new CustomEvent('execute-current-scenario', { detail: { scenarioId: currentScenario.id } }));
    }
  }
}

function flagUserInteraction() {
  isUserInteracting = true;
  clearTimeout(userInteractionTimer);
  userInteractionTimer = setTimeout(() => {
    isUserInteracting = false;
  }, 2000);
}

function applyTransform({ immediate = false } = {}) {
  currentX = targetX;

  if (window.gsap && !immediate) {
    window.gsap.to(trackEl, {
      x: currentX,
      duration: 0.35,
      ease: 'power2.out',
      overwrite: 'auto',
      onUpdate: updateFocus
    });
  } else {
    trackEl.style.transform = `translateX(${currentX}px)`;
    updateFocus();
  }
}

export function scrollToIndex(index, { immediate = false } = {}) {
  const total = state.filtered.length;
  if (total === 0) return;

  const safeIndex = Math.max(0, Math.min(total - 1, index));
  state.currentIndex = safeIndex;

  targetX = - (safeIndex * panelStep);
  targetX = Math.max(-maxScroll, Math.min(0, targetX));

  applyTransform({ immediate });
}

export function scrollToScenario(scenarioId) {
  const idx = state.filtered.findIndex(s => s.id === scenarioId);
  if (idx !== -1) {
    scrollToIndex(idx);
  }
}

function updateFocus() {
  const panels = trackEl.querySelectorAll('.scenario-panel');
  if (panels.length === 0) return;

  const activeIdx = Math.max(0, Math.min(panels.length - 1, Math.round(Math.abs(currentX) / panelStep)));
  state.currentIndex = activeIdx;

  panels.forEach((p, i) => {
    if (i === activeIdx) {
      p.classList.add('is-focused');
    } else {
      p.classList.remove('is-focused');
    }
  });

  // Update progress bar
  if (progressBarEl) {
    const ratio = maxScroll > 0 ? (Math.abs(currentX) / maxScroll) : 0;
    progressBarEl.style.width = `${Math.min(100, Math.max(0, ratio * 100))}%`;
  }

  // Update counter display
  if (counterEl) {
    const currentNum = String(activeIdx + 1).padStart(2, '0');
    const totalNum = String(state.filtered.length).padStart(2, '0');
    counterEl.innerHTML = `SPECIMEN <b>${currentNum}</b> <span>/ ${totalNum}</span>`;
  }
}
