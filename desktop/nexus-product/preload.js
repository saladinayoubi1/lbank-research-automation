const { contextBridge, ipcRenderer } = require('electron');

const CHANNELS = Object.freeze({
  get: 'nexus:ui-preferences:get',
  set: 'nexus:ui-preferences:set',
  reset: 'nexus:ui-preferences:reset',
  runner: 'nexus:runner-bootstrap:get',
});

function runnerBadgeState(status) {
  const value = String(status || 'UNKNOWN').toUpperCase();
  if (value.includes('RUNNING') || value === 'LISTENER_ALREADY_RUNNING') return { className: 'good', label: 'RUNNER READY' };
  if (value.includes('NOT_OBSERVED') || value.includes('BLOCKED') || value.includes('REJECTED') || value.includes('FAILED') || value.includes('NOT_FOUND')) {
    return { className: 'bad', label: 'RUNNER BLOCKED' };
  }
  return { className: 'neutral', label: 'RUNNER UNKNOWN' };
}

async function refreshRunnerBadge() {
  const host = document.querySelector('.top-status');
  if (!host) return;
  let badge = document.getElementById('runnerBootstrapState');
  if (!badge) {
    badge = document.createElement('span');
    badge.id = 'runnerBootstrapState';
    badge.className = 'status neutral';
    const dot = document.createElement('i');
    const label = document.createElement('b');
    label.textContent = 'RUNNER UNKNOWN';
    badge.append(dot, label);
    const reload = document.getElementById('reload');
    host.insertBefore(badge, reload || null);
  }
  try {
    const state = await ipcRenderer.invoke(CHANNELS.runner);
    const visible = runnerBadgeState(state?.status);
    badge.className = `status ${visible.className}`;
    const label = badge.querySelector('b');
    if (label) label.textContent = visible.label;
    const details = [
      String(state?.status || 'UNKNOWN'),
      state?.source_sha ? `sha=${String(state.source_sha).slice(0, 12)}` : '',
      state?.service_state ? `service=${state.service_state}` : '',
      state?.agent_name ? `agent=${state.agent_name}` : '',
      state?.error ? `error=${state.error}` : '',
    ].filter(Boolean);
    badge.title = details.join(' · ').slice(0, 480);
  } catch {
    badge.className = 'status neutral';
    const label = badge.querySelector('b');
    if (label) label.textContent = 'RUNNER UNKNOWN';
    badge.title = 'Runner bootstrap evidence unavailable';
  }
}

contextBridge.exposeInMainWorld('nexusDesktop', Object.freeze({
  getPreferences: () => ipcRenderer.invoke(CHANNELS.get),
  setPreferences: preferences => ipcRenderer.invoke(CHANNELS.set, preferences),
  resetPreferences: () => ipcRenderer.invoke(CHANNELS.reset),
  getRunnerBootstrapState: () => ipcRenderer.invoke(CHANNELS.runner),
}));

window.addEventListener('DOMContentLoaded', () => {
  void refreshRunnerBadge();
  setTimeout(() => { void refreshRunnerBadge(); }, 32000);
});
window.addEventListener('focus', () => { void refreshRunnerBadge(); });
