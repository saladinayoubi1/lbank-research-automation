(() => {
  'use strict';

  const byId = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

  async function api(path, options = {}) {
    const response = await fetch(path, {
      cache: 'no-store',
      credentials: 'same-origin',
      ...options,
      headers: {'Content-Type': 'application/json', ...(options.headers || {})},
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || payload.error || `HTTP ${response.status}`);
    return payload;
  }

  function ensureUi() {
    const head = document.head;
    if (!document.querySelector('link[href="/ui/product-offline.css"]')) {
      const link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = '/ui/product-offline.css';
      head.appendChild(link);
    }

    const topStatus = document.querySelector('.top-status');
    if (topStatus && !byId('offlineModeBadge')) {
      const badge = document.createElement('span');
      badge.id = 'offlineModeBadge';
      badge.className = 'status good offline-mode-badge';
      badge.innerHTML = '<i></i><b>OFFLINE-FIRST</b>';
      topStatus.prepend(badge);
    }

    const dataView = byId('view-data');
    if (dataView && !byId('offlineDataPanel')) {
      const panel = document.createElement('article');
      panel.id = 'offlineDataPanel';
      panel.className = 'panel offline-panel';
      panel.innerHTML = `
        <header><div><span>OFFLINE DATA VAULT</span><h2>داده محلی برای لپ‌تاپ بدون اینترنت</h2></div><strong id="offlineDatasetCount" class="badge neutral">0 DATASET</strong></header>
        <div class="offline-grid">
          <div class="offline-copy"><b>Import امن از فایل / فلش</b><p>فقط فایل NEXUS canonical با Provenance و SHA-256 معتبر پذیرفته می‌شود. داده ساختگی یا فایل دستکاری‌شده رد می‌شود.</p></div>
          <div class="offline-actions"><input id="offlineDatasetFile" type="file" accept="application/json,.json"><button id="offlineImport" class="small-btn accent">Import Canonical JSON</button></div>
        </div>
        <div id="offlineImportState" class="result-box muted">برای Research و Backtest آفلاین، یک dataset معتبر وارد کن. هر dataset آنلاین موفق هم خودکار اینجا cache می‌شود.</div>
        <div id="offlineDatasetTable" class="table-wrap"></div>`;
      const boundary = dataView.querySelectorAll('.panel')[1];
      dataView.insertBefore(panel, boundary || null);
    }

    const researchView = byId('view-research');
    if (researchView && !byId('offlineResearchPanel')) {
      const panel = document.createElement('article');
      panel.id = 'offlineResearchPanel';
      panel.className = 'panel offline-panel';
      panel.innerHTML = `
        <header><div><span>OFFLINE RESEARCH</span><h2>Backtest / Strategy Factory بدون اینترنت</h2></div><strong class="badge good">NO NETWORK I/O</strong></header>
        <div class="offline-research-controls">
          <label>Dataset<select id="offlineDatasetSelect"><option value="">— dataset وارد نشده —</option></select></label>
          <label>خانواده<select id="offlineFamily"><option value="momentum">Momentum</option><option value="trend_breakout">Trend Breakout</option><option value="mean_reversion">Mean Reversion</option></select></label>
          <button id="offlineResearchRun" class="primary">اجرای Research / Backtest آفلاین</button>
          <button id="offlineAutoPaper" class="small-btn">Auto Paper از Research آفلاین</button>
        </div>
        <div id="offlineResearchState" class="result-box muted">Historical Research آفلاین مجاز است؛ Auto Paper فقط اگر dataset هنوز fresh باشد اجازه عبور از Risk را دارد.</div>`;
      const layout = researchView.querySelector('.research-layout');
      researchView.insertBefore(panel, layout || null);
    }

    const onlineForm = byId('researchForm');
    if (onlineForm) {
      const submit = onlineForm.querySelector('button[type="submit"]');
      if (submit && !submit.dataset.offlineAnnotated) {
        submit.dataset.offlineAnnotated = '1';
        submit.textContent = 'Refresh آنلاین → Backtest → Qualification (نیازمند اینترنت)';
      }
    }
  }

  function datasetRow(dataset) {
    const date = new Date(Number(dataset.last_open_time_ms)).toLocaleString('fa-IR');
    return `<tr><td>${esc(dataset.source_symbol)}</td><td>${esc(dataset.timeframe)}</td><td>${esc(dataset.row_count)}</td><td>${esc(date)}</td><td class="mono">${esc(dataset.binding_sha256.slice(0, 14))}…</td></tr>`;
  }

  async function refreshOffline() {
    const snapshot = await api('/api/product/offline');
    const count = byId('offlineDatasetCount');
    if (count) count.textContent = `${snapshot.dataset_count} DATASET`;
    const table = byId('offlineDatasetTable');
    if (table) {
      table.innerHTML = snapshot.datasets.length
        ? `<table><thead><tr><th>Symbol</th><th>TF</th><th>Rows</th><th>آخرین کندل</th><th>Binding</th></tr></thead><tbody>${snapshot.datasets.map(datasetRow).join('')}</tbody></table>`
        : '<div class="empty-state">هنوز dataset canonical محلی ذخیره نشده است.</div>';
    }
    const select = byId('offlineDatasetSelect');
    if (select) {
      const current = select.value;
      select.innerHTML = '<option value="">— انتخاب dataset —</option>' + snapshot.datasets.map((dataset) =>
        `<option value="${esc(dataset.binding_sha256)}">${esc(dataset.source_symbol)} · ${esc(dataset.timeframe)} · ${esc(dataset.row_count)} candles</option>`
      ).join('');
      if ([...select.options].some((option) => option.value === current)) select.value = current;
    }
    return snapshot;
  }

  async function importFile() {
    const input = byId('offlineDatasetFile');
    const state = byId('offlineImportState');
    if (!input || !input.files || input.files.length !== 1) throw new Error('یک فایل JSON انتخاب کن');
    const file = input.files[0];
    if (file.size < 2 || file.size > 2_000_000) throw new Error('حجم dataset خارج از محدوده امن است');
    if (state) state.textContent = 'در حال اعتبارسنجی Provenance و Binding…';
    let payload;
    try { payload = JSON.parse(await file.text()); }
    catch { throw new Error('فایل JSON معتبر نیست'); }
    const result = await api('/api/product/offline/import', {method: 'POST', body: JSON.stringify(payload)});
    if (state) state.textContent = `✓ ${result.status}: ${result.dataset.source_symbol} / ${result.dataset.timeframe} / ${result.dataset.row_count} candles`;
    await refreshOffline();
  }

  function metric(label, value) {
    return `<div><span>${esc(label)}</span><b>${esc(value)}</b></div>`;
  }

  function renderOfflineResearch(result) {
    const state = byId('offlineResearchState');
    if (state) state.textContent = `✓ Offline · ${result.dataset.source_symbol} · ${result.dataset.timeframe} · ${result.qualification.status}`;
    const badge = byId('qualificationBadge');
    if (badge) {
      badge.textContent = result.qualification.status;
      badge.className = `badge ${result.qualification.status === 'paper_candidate' ? 'good' : 'warn'}`;
    }
    const metrics = byId('researchMetrics');
    if (metrics) {
      const m = result.backtest?.metrics || {};
      metrics.innerHTML = [
        metric('Data Mode', 'OFFLINE'),
        metric('Rows', result.dataset.row_count),
        metric('Return', m.total_return ?? '—'),
        metric('Drawdown', m.max_drawdown ?? '—'),
        metric('Fills', m.fill_count ?? '—'),
        metric('Target', result.latest_target ?? '—'),
      ].join('');
    }
    const evidence = byId('researchEvidence');
    if (evidence) evidence.textContent = JSON.stringify({qualification: result.qualification, evidence: result.evidence, dataset: result.dataset, data_mode: result.data_mode}, null, 2);
    const fills = byId('backtestFills');
    if (fills) {
      const rows = result.backtest?.fills || [];
      fills.innerHTML = rows.length ? `<table><thead><tr><th>Time</th><th>Side</th><th>Price</th><th>Notional</th><th>Fee</th></tr></thead><tbody>${rows.map((row) => `<tr><td>${esc(row.execution_time)}</td><td>${esc(row.side)}</td><td>${esc(row.fill_price)}</td><td>${esc(row.notional)}</td><td>${esc(row.fee)}</td></tr>`).join('')}</tbody></table>` : '<div class="empty-state">Fill ثبت نشده است.</div>';
    }
  }

  async function runOfflineResearch() {
    const binding = byId('offlineDatasetSelect')?.value || '';
    const family = byId('offlineFamily')?.value || '';
    if (!binding) throw new Error('ابتدا dataset محلی انتخاب کن');
    const state = byId('offlineResearchState');
    if (state) state.textContent = 'در حال اجرای canonical Backtest / OOS / Stress / Regime بدون شبکه…';
    const result = await api('/api/product/offline/research', {method: 'POST', body: JSON.stringify({binding_sha256: binding, family})});
    renderOfflineResearch(result);
  }

  async function runOfflinePaper() {
    const state = byId('offlineResearchState');
    if (state) state.textContent = 'در حال عبور از Qualification → Deterministic Risk → Paper…';
    const result = await api('/api/product/offline/paper/auto', {method: 'POST', body: '{}'});
    if (state) state.textContent = `${result.accepted ? '✓' : '•'} ${result.status}${result.kill_reasons ? ` · ${result.kill_reasons.join(', ')}` : ''}`;
  }

  function bindEvents() {
    byId('offlineImport')?.addEventListener('click', () => importFile().catch((error) => { const state = byId('offlineImportState'); if (state) state.textContent = `✕ ${error.message}`; }));
    byId('offlineResearchRun')?.addEventListener('click', () => runOfflineResearch().catch((error) => { const state = byId('offlineResearchState'); if (state) state.textContent = `✕ ${error.message}`; }));
    byId('offlineAutoPaper')?.addEventListener('click', () => runOfflinePaper().catch((error) => { const state = byId('offlineResearchState'); if (state) state.textContent = `✕ ${error.message}`; }));
  }

  async function start() {
    ensureUi();
    bindEvents();
    try { await refreshOffline(); }
    catch (error) {
      const badge = byId('offlineModeBadge');
      if (badge) { badge.className = 'status bad offline-mode-badge'; badge.querySelector('b').textContent = 'OFFLINE STORE ERROR'; }
      const state = byId('offlineImportState');
      if (state) state.textContent = `✕ ${error.message}`;
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once: true});
  else start();
})();
