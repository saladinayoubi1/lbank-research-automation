(() => {
  'use strict';
  const byId = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const date = ms => new Date(Number(ms)).toLocaleString('fa-IR');
  const markets = [
    {provider: 'lbank', label: 'LBank', prefix: 'lbank', path: '/api/product/lbank-market'},
    {provider: 'bitget', label: 'Bitget', prefix: 'alternative', path: '/api/product/alternative-market'}
  ];
  let pendingRefresh = null;
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
    for (const market of markets) {
      const prefix = market.prefix;
      panel(byId('view-data'), prefix + 'MarketPanel',
        '<header><div><span>' + market.label.toUpperCase() + '</span><h2>دادهٔ پشتیبان پژوهش</h2></div><strong id="' + prefix + 'MarketBadge" class="badge neutral">بررسی نشده</strong></header>' +
        '<p>منبع این داده‌ها ' + market.label + ' است. مرجع اجرای Paper همچنان Bybit است. کندل‌های باز وارد مخزن نمی‌شوند.</p>' +
        '<div class="research-data-actions"><button id="' + prefix + 'Start" class="small-btn accent">شروع پایش پشتیبان</button><button id="' + prefix + 'Stop" class="small-btn">توقف پایش</button><button id="' + prefix + 'Refresh" class="small-btn">دریافت یک‌باره</button></div>' +
        '<div id="' + prefix + 'MarketState" class="result-box muted">در حال خواندن وضعیت مخزن…</div><div id="' + prefix + 'MarketTable" class="table-wrap"></div>');
      byId(prefix + 'MarketPanel')?.setAttribute('data-provider', market.provider);
    }
    panel(byId('view-research'), 'reviewedResearchPanel',
      '<header><div><span>A6 / A7 / A9 / ELLIOTT</span><h2>گزارش‌های بررسی‌شدهٔ پژوهش</h2></div><button id="reviewedReportsRefresh" class="small-btn">بازخوانی گزارش‌ها</button></header>' +
      '<p>سرمایهٔ مبنا در هر گزارش درج شده است. سناریوهای هزینه مستقل‌اند و تعداد معاملاتشان با هم جمع نمی‌شود.</p><div id="reviewedResearchReports"></div>');
  }
  function marketRow(d, market) {
    return '<tr><td>' + market.label + ' · Spot</td><td>' + esc(d.symbol) + '</td><td>' + esc(d.timeframe) + '</td><td>' +
      esc(d.row_count) + '</td><td>' + esc(date(d.end_exclusive_ms)) + '</td><td' + (d.historical_only ? '' : ' data-current="true"') + '>' +
      (d.historical_only ? 'آرشیو تاریخی' : d.fresh ? 'تازه' : 'قدیمی') + '</td></tr>';
  }
  function renderMarket(snapshot, market) {
    if (snapshot.provider !== market.provider || (snapshot.datasets || []).some(d => d.provider !== market.provider)) {
      throw new Error('منبع پاسخ با این مخزن مطابقت ندارد.');
    }
    const prefix = market.prefix;
    const status = snapshot.state || {};
    const badge = byId(prefix + 'MarketBadge');
    if (badge) {
      badge.textContent = status.feed_healthy ? 'دادهٔ تازه و معتبر' : status.status === 'paused_after_two_failed_cycles' ? 'توقف پس از دو خطا' : snapshot.polling_enabled ? 'در حال پایش' : 'پایش متوقف';
      badge.className = 'badge ' + (status.feed_healthy ? 'good' : 'warn');
    }
    const messages = (status.cells || []).filter(c => c.status !== 'available')
      .map(c => c.symbol + ' / ' + c.timeframe + ': ' + c.reason).join(' · ');
    const state = byId(prefix + 'MarketState');
    if (state) state.textContent = (snapshot.polling_enabled ? 'پایش هر ۶۰ ثانیه' : 'پایش خودکار متوقف است') +
      ' · ' + (status.successful_cycles || 0) + ' بررسی کامل پیاپی' + (messages ? ' · ' + messages : '');
    if (byId(prefix + 'Start')) byId(prefix + 'Start').disabled = snapshot.polling_enabled;
    if (byId(prefix + 'Stop')) byId(prefix + 'Stop').disabled = !snapshot.polling_enabled;
    const datasets = [...(snapshot.datasets || [])].sort((a, b) => (b.symbol + ':' + b.timeframe).localeCompare(a.symbol + ':' + a.timeframe));
    const table = byId(prefix + 'MarketTable');
    if (table) table.innerHTML = datasets.length ? '<table><thead><tr><th>منبع</th><th>نماد</th><th>تایم‌فریم</th><th>کندل بسته</th><th>پایان داده</th><th>وضعیت</th></tr></thead><tbody>' +
      datasets.map(d => marketRow(d, market)).join('') + '</tbody></table>' :
      '<div class="empty-state">هنوز دادهٔ ' + market.label + ' در این مخزن وارد نشده است.</div>';
  }
  function marketError(market, error) {
    const badge = byId(market.prefix + 'MarketBadge');
    if (badge) { badge.textContent = 'خطای خواندن وضعیت'; badge.className = 'badge warn'; }
    const state = byId(market.prefix + 'MarketState');
    if (state) state.textContent = error.message;
    byId(market.prefix + 'MarketTable')?.querySelectorAll('[data-current]').forEach(cell => { cell.textContent = 'تازگی تأیید نشده'; });
  }
  const partLabel = part => ({train: 'آموزش', training: 'آموزش', validation: 'اعتبارسنجی',
    validation_already_inspected: 'اعتبارسنجیِ بررسی‌شده', historical_test_already_inspected: 'آزمون تاریخیِ بررسی‌شده',
    historically_inspected_test: 'بازهٔ قبلاً بررسی‌شده'}[part] || 'بازهٔ اخیر');
  const measured = value => typeof value === 'number' && Number.isFinite(value) ? esc(value.toFixed(4)) : '—';
  function entryPrefixSection(proof) {
    if (!proof) return '';
    const counts = proof.counts;
    const compatible = (counts.unique_compatible_witness || 0) + (counts.multiple_compatible_witnesses || 0);
    return '<p>تطبیق ساختاری ورودهای ثبت‌شده: <b>' + esc(compatible) + ' از ' + esc(proof.recorded_unique_entries_checked) +
      '</b> سازگار؛ بدون شاهد: ' + esc(counts.incompatible || 0) + '؛ دارای چند زنجیرهٔ سازگار: ' + esc(counts.multiple_compatible_witnesses || 0) +
      '. فقط کندل‌های بستهٔ پیش از ورود بررسی شده‌اند. این بازسازی پسینی، هویت سیگنال اصلیِ صادرشده را ثابت نمی‌کند.</p>' +
      '<details><summary>زنجیرهٔ کندل‌های پیش از هر ورود</summary><div class="table-wrap"><table><thead><tr>' +
      '<th>بازه</th><th>نماد</th><th>کندل ورود</th><th>کف صفر</th><th>سقف یک</th><th>کف دو</th><th>کندل تأیید دو</th><th>بازآزمایی</th><th>بازپس‌گیری</th><th>زمان تکمیل تأیید UTC</th></tr></thead><tbody>' +
      proof.entries.map(e => (e.witnesses.length ? e.witnesses : [null]).map(w => '<tr>' +
        [partLabel(e.part), e.symbol, e.entry_index, w?.pivot_w0_center, w?.pivot_w1_center, w?.pivot_w2_center,
          w?.w2_known_after_closed_index, w?.retest_completed_index, w?.reclaim_completed_index,
          w?.reclaim_available_utc].map(v => '<td>' + esc(v ?? '—') + '</td>').join('') + '</tr>').join('')).join('') +
      '</tbody></table></div></details>';
  }
  function elliottSection(item) {
    const report = item.report;
    const names = {context: 'داده و زمینه', pattern: 'الگو', entry: 'ورود', exit: 'خروج',
      timeout: 'مهلت خروج', sizing: 'اندازه و ریسک', no_trade: 'عدم ورود', costs: 'هزینه'};
    return '<section class="reviewed-report"><h3>ELLIOTT-V119 · Bybit Spot · 15m</h3>' +
      '<p class="badge warn">رد تاریخی: هر سه بازه در هر دو سناریوی هزینه منفی‌اند</p>' +
      '<p>سرمایهٔ مشترک مبنا: <b>' + esc(item.reference_capital_usdt) + ' USDT</b> برای BTC و ETH؛ موجودی در هر بازه و سناریو از نو آغاز شده است.</p>' +
      '<p>۷۷ مسیر معامله با دو هزینه محاسبه شده‌اند؛ ۱۵۴ مشاهدهٔ مستقل نیستند. این روش یک الگوی جزئیِ موج ۲ است؛ شمارش کامل الیوت و آزمون آیندهٔ دست‌نخورده ندارد.</p>' +
      '<p>حسابداری و مسیر خروج معاملات ثبت‌شده مستقلاً بررسی شده‌اند. هویت سیگنال اصلی در دفتر قدیمی ثبت نشده؛ هیچ بک‌تست تازه‌ای اجرا نشده است.</p>' +
      entryPrefixSection(report.entry_prefix_qa) +
      '<div class="table-wrap"><table><thead><tr><th>بازه</th><th>هزینه</th><th>از</th><th>تا</th><th>معاملهٔ بسته</th>' +
      '<th>ناخالص USDT</th><th>کارمزد USDT</th><th>لغزش USDT</th><th>خالص USDT</th><th>میانگین USDT</th><th>بازده ٪</th><th>افت Equity ٪</th></tr></thead><tbody>' +
      report.rows.map(r => '<tr><td>' + esc(partLabel(r.part)) + '</td><td>' +
        (r.profile === 'stress' ? 'سخت' : 'محافظه‌کارانه') + '</td><td>' + esc(r.first_decision_utc) + '</td><td>' + esc(r.last_decision_utc) +
        '</td><td>' + esc(r.round_trips) + '</td>' + [r.gross_pnl_usdt, r.fees_usdt, r.slippage_usdt, r.net_pnl_usdt,
          r.mean_pnl_usdt, r.net_return_pct, r.max_drawdown_pct].map(v => '<td>' + measured(v) + '</td>').join('') + '</tr>').join('') +
      '</tbody></table></div><p>افت Equity در شواهد اصلی اندازه‌گیری نشده است؛ علامت — به معنی صفر نیست. زمان خروج در دفتر، زمان بازشدن کندل منبع است.</p>' +
      '<details><summary>قواعد ثابت سیستم</summary>' + Object.entries(report.system_rules).map(([key, value]) =>
        '<p><b>' + esc(names[key] || key) + ':</b> ' + esc(value) + '</p>').join('') + '</details>' +
      '<details><summary>عملکرد ماهانهٔ هر بازه و هزینه</summary>' + report.rows.map(r => '<h4>' + esc(partLabel(r.part)) + ' · ' + esc(r.profile) + '</h4>' +
        '<div class="table-wrap"><table><thead><tr><th>ماه خروج</th><th>معامله</th><th>خالص USDT</th><th>میانگین USDT</th></tr></thead><tbody>' +
        r.monthly.map(m => '<tr><td>' + esc(m.month) + '</td><td>' + esc(m.round_trips) + '</td><td>' + measured(m.net_pnl_usdt) + '</td><td>' +
          measured(m.mean_pnl_usdt) + '</td></tr>').join('') + '</tbody></table></div>').join('') + '</details>' +
      '<p>این نتیجه برای دمو پذیرفته نشده است و روی همین بازه‌ها دوباره تنظیم نمی‌شود. <a href="' + esc(item.evidence_url) +
      '" target="_blank" rel="noopener noreferrer">شواهد پژوهش ثابت</a></p>' +
      '<details><summary>شواهد و محدودهٔ بررسی</summary><pre>' + esc(JSON.stringify(item, null, 2)) + '</pre></details></section>';
  }
  function reportRow(r) {
    const values = [r.symbol, partLabel(r.part), r.profile === 'stress' ? 'سخت' : 'محافظه‌کارانه',
      r.first_decision_utc, r.last_decision_utc, r.bars, r.closed_round_trips ?? r.closed_trades,
      r.net_return_pct, r.max_drawdown_pct];
    return '<tr>' + values.map(v => '<td>' + esc(v) + '</td>').join('') + '</tr>';
  }
  function reportSection(item) {
    if (item.id === 'ELLIOTT-V119') return elliottSection(item);
    const report = item.report;
    const rows = [...report.rows].sort((a, b) => (b.symbol + ':' + (b.part || '') + ':' + b.profile).localeCompare(a.symbol + ':' + (a.part || '') + ':' + a.profile));
    const verdict = item.id === 'A7' ? 'رد شد: هیچ سلول اخیر در سناریوی سخت مثبت نبود' : 'تأیید نشد: دادهٔ آیندهٔ مستقل لازم است';
    const dataNote = item.id === 'A6' && item.verified_data ? '<p>دادهٔ تاریخی BTC/ETH: بررسی مستقل ۶۰ آرشیو و ۵٬۷۶۰ کندل موفق. راهبرد A6 در هر شش بخش هزینهٔ تنش منفی و برای ورود به دمو رد شده است. دادهٔ آیندهٔ دست‌نخورده و تطبیق زندهٔ سمت معامله هنوز موجود نیست.</p>' : '';
    return '<section class="reviewed-report"><h3>' + esc(item.id) + ' · Bybit</h3><p class="badge warn">' + esc(verdict) + '</p>' +
      '<p>سرمایهٔ مبنا: ' + esc(item.reference_capital_usdt) + ' USDT</p><p>' + esc(item.original_verdict) + '</p><p>منبع کد: <span class="mono">' + esc(item.source_sha.slice(0, 12)) +
      '</span> · <a href="' + esc(item.evidence_url || item.run_url) + '" target="_blank" rel="noopener noreferrer">' + (item.evidence_kind === 'physical_local_research' ? 'مدرک اجرای محلی و QA مستقل' : 'اجرای ثبت‌شده') + '</a></p>' + dataNote +
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
  function refresh() {
    if (pendingRefresh) return pendingRefresh;
    pendingRefresh = (async () => {
      const results = await Promise.allSettled([...markets.map(m => api(m.path)), api('/api/product/research/reports')]);
      markets.forEach((market, i) => {
        try {
          if (results[i].status !== 'fulfilled') throw results[i].reason;
          renderMarket(results[i].value, market);
        } catch (error) { marketError(market, error); }
      });
      const reports = results[markets.length];
      if (reports.status === 'fulfilled') renderReports(reports.value);
      else if (byId('reviewedResearchReports')) byId('reviewedResearchReports').textContent = reports.reason.message;
    })().finally(() => { pendingRefresh = null; });
    return pendingRefresh;
  }
  async function action(market, path, payload) {
    const state = byId(market.prefix + 'MarketState');
    try { if (state) state.textContent = 'در حال انجام درخواست…'; await api(path, payload); await refresh(); }
    catch (error) { marketError(market, error); }
  }
  function start() {
    ensureUi();
    for (const market of markets) {
      byId(market.prefix + 'Start')?.addEventListener('click', () => action(market, market.path + '/polling', {enabled: true}));
      byId(market.prefix + 'Stop')?.addEventListener('click', () => action(market, market.path + '/polling', {enabled: false}));
      byId(market.prefix + 'Refresh')?.addEventListener('click', () => action(market, market.path + '/refresh', {}));
    }
    byId('reviewedReportsRefresh')?.addEventListener('click', refresh);
    window.NexusResearchData = {refresh};
    void refresh();
    setInterval(() => { if (!document.hidden) void refresh(); }, 10000);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once: true}); else start();
})();

