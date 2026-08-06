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

function renderIntegrations(zotero, research) {
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
  if (!response.ok) throw new Error(`API unavailable (${response.status})`);
  const payload = await response.json();
  if (!payload || typeof payload !== 'object') throw new Error('Malformed API response');
  return payload;
}

async function loadDashboard() {
  cards.hidden = true;
  integrationCards.hidden = true;
  tbody.replaceChildren();
  showState('Loading readiness and integration reports…');
  try {
    const [summaryPayload, seriesPayload, zoteroPayload, researchPayload] = await Promise.all([
      readJson('/api/readiness/summary'),
      readJson('/api/readiness/series'),
      readJson('/api/integrations/zotero'),
      readJson('/api/integrations/research'),
    ]);
    if (!summaryPayload.summary || !Array.isArray(seriesPayload.series) || !zoteroPayload.summary || !researchPayload.summary) {
      throw new Error('Malformed API response');
    }
    renderSummary(summaryPayload.summary);
    renderIntegrations(zoteroPayload.summary, researchPayload.summary);
    renderSeries(seriesPayload.series);
    const stale = Boolean(researchPayload.summary.stale);
    const kind = stale ? 'empty' : (seriesPayload.series.length ? 'success' : 'empty');
    const message = stale ? 'Reports loaded; Research review is overdue.' : (seriesPayload.series.length ? 'Reports loaded.' : 'Reports loaded; no series found.');
    showState(message, kind);
  } catch (error) {
    renderSeries([]);
    showState(error instanceof Error ? error.message : 'Dashboard unavailable', 'error');
  }
}

document.querySelector('#refresh').addEventListener('click', loadDashboard);
loadDashboard();
