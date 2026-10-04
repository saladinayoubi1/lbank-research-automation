(() => {
  'use strict';
  const byId = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const date = ms => new Date(Number(ms)).toLocaleString('fa-IR');
  async function api(path, payload) {
    const response = await fetch(path, {cache: 'no-store', credentials: 'same-origin',
      ...(payload === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)}),
      signal: AbortSignal.timeout(12000)});
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || body.error || 'HTTP ' + response.status);
    return body;
  }
  function panel(view, id, html) {
    if (!view || byId(id)) return;
    const node = document.createElement('article');
    node.id = id; node.className = 'panel research-data-panel'; node.innerHTML = html;
    view.appendChild(node);
  }
  function ensureUi() {
    panel(byId('view-data'), 'alternativeMarketPanel',
      '<header><div><span>BITGET</span><h2>دادهٔ پشتیبان پژوهش</h2></div><strong id="alternativeMarketBadge" class="badge neutral">بررسی نشده</strong></header>' +
      '<p>منبع این داده‌ها Bitget است. مرجع اجرای Paper همچنان Bybit است. کندل‌های باز وارد مخزن نمی‌شوند.</p>' +
      '<div class="research-data-actions"><button id="alternativeStart" class="small-btn accent">شروع پایش پشتیبان</button><button id="alternativeStop" class="small-btn">توقف پایش</button><button id="alternativeRefresh" class="small-btn">دریافت یک‌باره</button></div>' +
      '<div id="alternativeMarketState" class="result-box muted">در حال خواندن وضعیت مخزن…</div><div id="alternativeMarketTable" class="table-wrap"></div>');
    panel(byId('view-research'), 'reviewedResearchPanel',
      '<header><div><span>A7 / A9</span><h2>گزارش‌های بررسی‌شدهٔ پژوهش</h2></div><button id="reviewedReportsRefresh" class="small-btn">بازخوانی گزارش‌ها</button></header>' +
      '<p>مبنای محاسبات هر پژوهش ۱۰٬۰۰۰ USDT است. سناریوهای هزینه مستقل‌اند و تعداد معاملاتشان با هم جمع نمی‌شود.</p><div id="reviewedResearchReports"></div>');
  }
  function marketRow(d) {
    return '<tr><td>Bitget · Spot</td><td>' + esc(d.symbol) + '</td><td>' + esc(d.timeframe) + '</td><td>' +
      esc(d.row_count) + '</td><td>' + esc(date(d.end_exclusive_ms)) + '</td><td>' +
      (d.historical_only ? 'آرشیو تاریخی' : d.fresh ? 'تازه' : 'قدیمی') + '</td></tr>';
  }
  function renderMarket(snapshot) {
    const status = snapshot.state || {};
    const badge = byId('alternativeMarketBadge');
    if (badge) {
      badge.textContent = status.feed_healthy ? 'دادهٔ تازه و معتبر' : snapshot.polling_enabled ? 'در حال پایش' : 'پایش متوقف';
      badge.className = 'badge ' + (status.feed_healthy ? 'good' : 'warn');
    }
    const messages = (status.cells || []).filter(c => c.status !== 'available')
      .map(c => c.symbol + ' / ' + c.timeframe + ': ' + c.reason).join(' · ');
    const state = byId('alternativeMarketState');
    if (state) state.textContent = (snapshot.polling_enabled ? 'پایش هر ۶۰ ثانیه' : 'پایش خودکار متوقف است') +
      ' · ' + (status.successful_cycles || 0) + ' بررسی کامل پیاپی' + (messages ? ' · ' + messages : '');
    if (byId('alternativeStart')) byId('alternativeStart').disabled = snapshot.polling_enabled;
    if (byId('alternativeStop')) byId('alternativeStop').disabled = !snapshot.polling_enabled;
    const datasets = [...(snapshot.datasets || [])].sort((a, b) => (b.symbol + ':' + b.timeframe).localeCompare(a.symbol + ':' + a.timeframe));
    const table = byId('alternativeMarketTable');
    if (table) table.innerHTML = datasets.length ? '<table><thead><tr><th>منبع</th><th>نماد</th><th>تایم‌فریم</th><th>کندل بسته</th><th>پایان داده</th><th>وضعیت</th></tr></thead><tbody>' +
      datasets.map(marketRow).join('') + '</tbody></table>' :
      '<div class="empty-state">هنوز دادهٔ Bitget در این مخزن وارد نشده است.</div>';
  }
  const partLabel = part => ({train: 'آموزش', validation: 'اعتبارسنجی', historically_inspected_test: 'بازهٔ قبلاً بررسی‌شده'}[part] || 'بازهٔ اخیر');
  function reportRow(r) {
    const values = [r.symbol, partLabel(r.part), r.profile === 'stress' ? 'سخت' : 'محافظه‌کارانه',
      r.first_decision_utc, r.last_decision_utc, r.bars, r.closed_round_trips ?? r.closed_trades,
      r.net_return_pct, r.max_drawdown_pct];
    return '<tr>' + values.map(v => '<td>' + esc(v) + '</td>').join('') + '</tr>';
  }
  function reportSection(item) {
    const report = item.report;
    const rows = [...report.rows].sort((a, b) => (b.symbol + ':' + (b.part || '') + ':' + b.profile).localeCompare(a.symbol + ':' + (a.part || '') + ':' + a.profile));
    const verdict = item.id === 'A7' ? 'رد شد: هیچ سلول اخیر در سناریوی سخت مثبت نبود' : 'تأیید نشد: دادهٔ آیندهٔ مستقل لازم است';
    return '<section class="reviewed-report"><h3>' + esc(item.id) + ' · Bybit</h3><p class="badge warn">' + esc(verdict) + '</p>' +
      '<p>' + esc(item.original_verdict) + '</p><p>منبع کد: <span class="mono">' + esc(item.source_sha.slice(0, 12)) +
      '</span> · <a href="' + esc(item.run_url) + '" target="_blank" rel="noopener noreferrer">اجرای ثبت‌شده</a></p>' +
      '<div class="table-wrap"><table><thead><tr><th>نماد</th><th>بازه</th><th>هزینه</th><th>از</th><th>تا</th><th>کندل</th><th>معاملهٔ بسته</th><th>بازده خالص ٪</th><th>افت سرمایه ٪</th></tr></thead><tbody>' +
      rows.map(reportRow).join('') + '</tbody></table></div><details><summary>مدرک و نتیجهٔ اصلی پژوهش</summary><pre>' +
      esc(JSON.stringify(report, null, 2)) + '</pre></details></section>';
  }
  function renderReports(snapshot) {
    const holder = byId('reviewedResearchReports'); if (!holder) return;
    const reports = [...snapshot.reports].sort((a, b) => b.id.localeCompare(a.id));
    holder.innerHTML = reports.map(reportSection).join('') + snapshot.errors.map(error =>
      '<p class="result-box">' + esc(error.id) + ': گزارش به دلیل ' + esc(error.reason) + ' نمایش داده نشد.</p>').join('');
  }
  async function refresh() {
    const results = await Promise.allSettled([api('/api/product/alternative-market'), api('/api/product/research/reports')]);
    if (results[0].status === 'fulfilled') renderMarket(results[0].value);
    else if (byId('alternativeMarketState')) byId('alternativeMarketState').textContent = results[0].reason.message;
    if (results[1].status === 'fulfilled') renderReports(results[1].value);
    else if (byId('reviewedResearchReports')) byId('reviewedResearchReports').textContent = results[1].reason.message;
  }
  async function action(path, payload) {
    const state = byId('alternativeMarketState');
    try { if (state) state.textContent = 'در حال انجام درخواست…'; await api(path, payload); await refresh(); }
    catch (error) { if (state) state.textContent = error.message; }
  }
  function start() {
    ensureUi();
    byId('alternativeStart')?.addEventListener('click', () => action('/api/product/alternative-market/polling', {enabled: true}));
    byId('alternativeStop')?.addEventListener('click', () => action('/api/product/alternative-market/polling', {enabled: false}));
    byId('alternativeRefresh')?.addEventListener('click', () => action('/api/product/alternative-market/refresh', {}));
    byId('reviewedReportsRefresh')?.addEventListener('click', refresh);
    window.NexusResearchData = {refresh};
    void refresh();
    setInterval(() => { if (!document.hidden) void refresh(); }, 10000);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once: true}); else start();
})();
