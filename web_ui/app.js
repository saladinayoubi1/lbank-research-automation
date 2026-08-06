const state = document.querySelector('#state');
const cards = document.querySelector('#cards');
const integrationCards = document.querySelector('#integration-cards');
const tbody = document.querySelector('#series');

function showState(message, kind = 'info') {
  state.hidden = false;
  state.dataset.kind = kind;
  state.textContent = message;
}

function renderSummary(summary) {
  document.querySelector('#total').textContent = summary.total_series ?? 0;
  document.querySelector('#ready').textContent = summary.ready_series ?? 0;
  document.querySelector('#blocked').textContent = summary.blocked_series ?? 0;
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
  showState('Loading readiness and integration reports…');

  const results = await Promise.allSettled([
    readJson('/api/readiness/summary'),
    readJson('/api/readiness/series'),
    readJson('/api/integrations/zotero'),
    readJson('/api/integrations/research'),
  ]);

  const [summaryResult, seriesResult, zoteroResult, researchResult] = results;
  const errors = [];

  if (summaryResult.status === 'fulfilled' && summaryResult.value.summary) {
    renderSummary(summaryResult.value.summary);
  } else {
    errors.push(summaryResult.reason?.message || 'Readiness summary unavailable');
  }

  if (seriesResult.status === 'fulfilled' && Array.isArray(seriesResult.value.series)) {
    renderSeries(seriesResult.value.series);
  } else {
    renderSeries([]);
    errors.push(seriesResult.reason?.message || 'Readiness series unavailable');
  }

  const zotero = zoteroResult.status === 'fulfilled' ? zoteroResult.value.summary : {};
  const research = researchResult.status === 'fulfilled' ? researchResult.value.summary : {};
  renderIntegrations(zotero, research);
  if (zoteroResult.status === 'rejected') errors.push(zoteroResult.reason?.message || 'Zotero report unavailable');
  if (researchResult.status === 'rejected') errors.push(researchResult.reason?.message || 'Research report unavailable');

  if (errors.length) {
    showState(`Loaded with warnings: ${errors.join(' | ')}`, 'error');
  } else {
    const stale = Boolean(research?.stale);
    showState(stale ? 'Reports loaded; Research review is overdue.' : 'Reports loaded.', stale ? 'empty' : 'success');
  }
}

document.querySelector('#refresh').addEventListener('click', loadDashboard);
loadDashboard();
