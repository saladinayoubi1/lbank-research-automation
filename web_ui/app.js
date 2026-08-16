const state = document.querySelector('#state');
const cards = document.querySelector('#cards');
const integrationCards = document.querySelector('#integration-cards');
const tbody = document.querySelector('#series');
const alerts = document.querySelector('#alerts');

const surfaces = new Map(
  [...document.querySelectorAll('[data-surface]')].map((view) => [view.dataset.surface, view]),
);

function selectSurface(name, { updateHistory = true } = {}) {
  const selectedName = surfaces.has(name) ? name : 'mission';
  const target = surfaces.get(selectedName);
  if (!target) return;
  document.querySelectorAll('.view').forEach((view) => view.classList.toggle('active', view === target));
  document.querySelectorAll('.nav-item').forEach((button) => {
    const active = button.dataset.view === selectedName;
    button.classList.toggle('active', active);
    button.setAttribute('aria-current', active ? 'page' : 'false');
  });
  if (updateHistory && location.hash !== `#${selectedName}`) {
    history.pushState(null, '', `#${selectedName}`);
  }
}

document.querySelectorAll('.nav-item').forEach((button) => button.addEventListener('click', () => selectSurface(button.dataset.view)));
window.addEventListener('popstate', () => selectSurface(location.hash.slice(1), { updateHistory: false }));

function showState(message, kind = 'info') {
  state.hidden = false;
  state.dataset.kind = kind;
  state.textContent = message;
}

function normalizeSummary(summary = {}) {
  if (summary && typeof summary.summary === 'object' && !Array.isArray(summary.summary)) {
    return summary.summary;
  }
  return summary || {};
}

function renderSummary(rawSummary = {}) {
  const summary = normalizeSummary(rawSummary);
  const total = Number(summary.total_series ?? 0);
  const ready = Number(summary.ready_series ?? 0);
  const blocked = Number(summary.blocked_series ?? 0);
  const safeTotal = Number.isFinite(total) ? total : 0;
  const safeReady = Number.isFinite(ready) ? ready : 0;
  const safeBlocked = Number.isFinite(blocked) ? blocked : 0;
  const rate = safeTotal > 0 ? Math.round((safeReady / safeTotal) * 100) : 0;
  document.querySelector('#total').textContent = safeTotal;
  document.querySelector('#ready').textContent = safeReady;
  document.querySelector('#blocked').textContent = safeBlocked;
  document.querySelector('#readiness-rate').textContent = `${rate}%`;
  document.querySelector('#readiness-caption').textContent = summary.all_ready ? 'All tracked series ready' : `${safeBlocked} series still blocked`;
  document.querySelector('#overall').textContent = summary.all_ready ? 'Ready' : 'Attention';
  cards.hidden = false;
}

function renderIntegrations(zotero = {}, research = {}) {
  document.querySelector('#zotero-items').textContent = zotero.item_count ?? 0;
  document.querySelector('#zotero-findings').textContent = zotero.finding_count ?? 0;
  document.querySelector('#zotero-status').textContent = zotero.status === 'clean' ? 'Clean' : 'Attention';
  document.querySelector('#zotero-duplicates').textContent = `${zotero.duplicate_doi_groups ?? 0} DOI duplicate groups`;
  document.querySelector('#research-claims').textContent = research.claim_count ?? 0;
  document.querySelector('#research-evidence').textContent = research.evidence_count ?? 0;
  document.querySelector('#research-status').textContent = research.stale ? 'Review overdue' : 'Research-only';
  document.querySelector('#research-review').textContent = research.next_review_due ? `Review ${research.next_review_due}` : 'No review date';
  integrationCards.hidden = false;
}

function renderAlerts(rows = [], zotero = {}, research = {}, errors = []) {
  alerts.replaceChildren();
  const blockedRows = Array.isArray(rows) ? rows.filter((item) => String(item.ready_for_research).toLowerCase() !== 'true') : [];
  const items = [];
  if (errors.length) items.push({icon: '🔴', title: 'Dashboard input warning', detail: errors[0]});
  if (blockedRows.length) {
    const sample = blockedRows.slice(0, 2).map((item) => `${item.symbol || 'Unknown'} ${item.timeframe || ''}`).join(', ');
    items.push({icon: '🔴', title: `${blockedRows.length} market-data series blocked`, detail: sample || 'Review readiness reasons in the table below.'});
  }
  if (Number(zotero.finding_count ?? 0) > 0) items.push({icon: '🔴', title: `${zotero.finding_count} Zotero metadata findings`, detail: 'Findings are research metadata issues, not a dashboard process failure.'});
  if (research.stale) items.push({icon: '🔴', title: 'Research review overdue', detail: research.next_review_due ? `Review due ${research.next_review_due}` : 'No current review date is available.'});
  if (!items.length) items.push({icon: '●', title: 'No immediate intervention required', detail: 'Current dashboard inputs report no active blocker that needs manual action.'});

  for (const item of items.slice(0, 4)) {
    const row = document.createElement('div');
    row.className = 'alert';
    const icon = document.createElement('span');
    icon.className = 'alert-icon';
    icon.textContent = item.icon;
    const body = document.createElement('div');
    const title = document.createElement('strong');
    title.textContent = item.title;
    const detail = document.createElement('small');
    detail.textContent = item.detail;
    body.append(title, detail);
    row.append(icon, body);
    alerts.append(row);
  }
}

function renderSeries(rows) {
  tbody.replaceChildren();
  if (!Array.isArray(rows) || rows.length === 0) {
    const row = tbody.insertRow();
    const cell = row.insertCell();
    cell.colSpan = 4;
    cell.className = 'empty';
    cell.textContent = 'No series records are available.';
    return;
  }
  for (const item of rows) {
    const row = tbody.insertRow();
    const ready = String(item.ready_for_research).toLowerCase() === 'true';
    for (const value of [item.symbol, item.timeframe, ready ? 'Ready' : 'Blocked', item.readiness_reason]) {
      const cell = row.insertCell();
      cell.textContent = value || '—';
    }
    row.dataset.status = ready ? 'ready' : 'blocked';
  }
}

async function readJson(url) {
  const response = await fetch(url, {headers: {'Accept': 'application/json'}, cache: 'no-store'});
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail || payload.error || `HTTP ${response.status}`;
    throw new Error(`${url}: ${detail}`);
  }
  if (!payload || typeof payload !== 'object') throw new Error(`${url}: malformed response`);
  return payload;
}

async function loadDashboard() {
  cards.hidden = true;
  integrationCards.hidden = true;
  tbody.replaceChildren();
  alerts.innerHTML = '<p class="muted">Checking blockers…</p>';
  showState('Loading readiness and integration reports…');

  const results = await Promise.allSettled([
    readJson('/api/readiness/summary'),
    readJson('/api/readiness/series'),
    readJson('/api/integrations/zotero'),
    readJson('/api/integrations/research'),
  ]);

  const [summaryResult, seriesResult, zoteroResult, researchResult] = results;
  const errors = [];
  const summary = summaryResult.status === 'fulfilled' ? summaryResult.value.summary || {} : {};
  const rows = seriesResult.status === 'fulfilled' && Array.isArray(seriesResult.value.series) ? seriesResult.value.series : [];
  const zotero = zoteroResult.status === 'fulfilled' ? zoteroResult.value.summary || {} : {};
  const research = researchResult.status === 'fulfilled' ? researchResult.value.summary || {} : {};

  if (summaryResult.status === 'fulfilled' && summaryResult.value.summary) renderSummary(summary);
  else errors.push(summaryResult.reason?.message || 'Readiness summary unavailable');

  if (seriesResult.status === 'fulfilled' && Array.isArray(seriesResult.value.series)) renderSeries(rows);
  else { renderSeries([]); errors.push(seriesResult.reason?.message || 'Readiness series unavailable'); }

  renderIntegrations(zotero, research);
  if (zoteroResult.status === 'rejected') errors.push(zoteroResult.reason?.message || 'Zotero report unavailable');
  if (researchResult.status === 'rejected') errors.push(researchResult.reason?.message || 'Research report unavailable');
  renderAlerts(rows, zotero, research, errors);

  if (errors.length) showState(`Loaded with warnings: ${errors.join(' | ')}`, 'error');
  else if (research.stale) showState('Reports loaded; research review is overdue.', 'error');
  else showState('Reports loaded. Monitoring surface is healthy.', 'success');
}

document.querySelector('#refresh').addEventListener('click', loadDashboard);
selectSurface(location.hash.slice(1) || 'mission', { updateHistory: false });
loadDashboard();
