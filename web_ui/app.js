const state = document.querySelector('#state');
const cards = document.querySelector('#cards');
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
  tbody.replaceChildren();
  showState('Loading readiness reports…');
  try {
    const [summaryPayload, seriesPayload] = await Promise.all([
      readJson('/api/readiness/summary'),
      readJson('/api/readiness/series'),
    ]);
    if (!summaryPayload.summary || !Array.isArray(seriesPayload.series)) {
      throw new Error('Malformed API response');
    }
    renderSummary(summaryPayload.summary);
    renderSeries(seriesPayload.series);
    showState(seriesPayload.series.length ? 'Reports loaded.' : 'Reports loaded; no series found.', seriesPayload.series.length ? 'success' : 'empty');
  } catch (error) {
    renderSeries([]);
    showState(error instanceof Error ? error.message : 'Dashboard unavailable', 'error');
  }
}

document.querySelector('#refresh').addEventListener('click', loadDashboard);
loadDashboard();
