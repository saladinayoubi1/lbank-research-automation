/* NEXUS Research Operations — read-only, evidence-bound product surface.
 * Never infer a live worker, qualified strategy or Paper admission from a task
 * definition, archived snapshot, green CI or a historical backtest alone.
 */
(function () {
  'use strict';

  var saved = {filter:'all', query:'', selected:null, mission:null, onRefresh:null, monthPair:'all'};
  var CONTRACT = 'nexus.product-mission-control.v1';
  var ACTIVE = ['LEASED','RUNNING','VERIFYING','TRIAGE'];
  var BLOCKED = ['BLOCKED','QUARANTINED','OWNER_REQUIRED'];
  var LABELS = {
    PENDING:'در صف', READY:'آماده', LEASED:'واگذار شده',
    RUNNING:'در حال اجرا', VERIFYING:'ممیزی مستقل', TRIAGE:'عیب‌یابی',
    DONE:'تکمیل ثبت‌شده', BLOCKED:'متوقف', QUARANTINED:'قرنطینه',
    OWNER_REQUIRED:'اقدام مالک', UNKNOWN:'نامشخص', IDLE:'بدون مأموریت',
    BUSY:'درگیر مأموریت', DISABLED:'غیرفعال'
  };
  function el(id) { return document.getElementById(id); }
  function safe(value) {
    return String(value === undefined || value === null || value === '' ? '—' : value)
      .replace(/[&<>"']/g, function (ch) {
        return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch];
      });
  }
  function code(value) { return '<code dir="ltr">' + safe(value) + '</code>'; }
  function present(value) { return value !== undefined && value !== null && value !== ''; }
  function stateOf(value) {
    var v = String(value || 'UNKNOWN').toUpperCase();
    return Object.prototype.hasOwnProperty.call(LABELS,v) ? v : 'UNKNOWN';
  }
  function tone(value) {
    var v = stateOf(value);
    return v === 'DONE' ? 'success' : ACTIVE.indexOf(v) !== -1 ? 'progress' :
      BLOCKED.indexOf(v) !== -1 ? 'warning' : 'muted';
  }
  function tag(value, label) {
    var v = stateOf(value);
    return '<span class="ops-tag ops-tag--' + tone(v) + '">' +
      '<i aria-hidden="true"></i>' + safe(label || LABELS[v]) + '</span>';
  }
  function tasksOf(m) {
    return Array.isArray(m && m.tasks) ? m.tasks.filter(function (t) {
      return t && typeof t.id === 'string' && /^P7-RESEARCH-/.test(t.id);
    }) : [];
  }
  function receiptVerified(t) {
    var p = t && t.result_evidence, q = t && t.verification_evidence;
    // A dashboard can verify consistency of reported receipts, not replay
    // signed bytes. Require exact worker roles, common source and no widened
    // trading authority before showing a *reported* independent QA match.
    return !!(t.status === 'DONE' && p && q &&
      p.executor === 'nexus-real-composite-backtest' &&
      q.executor === 'nexus-independent-composite-numeric-qa' &&
      /^[0-9a-f]{64}$/.test(String(p.receipt_digest || '')) &&
      /^[0-9a-f]{64}$/.test(String(q.qa_digest || '')) &&
      /^[0-9a-f]{40}$/.test(String(p.source_sha || '')) &&
      q.producer_receipt_digest === p.receipt_digest &&
      q.source_sha === p.source_sha &&
      q.independent_qa_complete === true &&
      p.auto_demo_promotion === false && q.auto_demo_promotion === false &&
      p.live_enabled === false && q.live_enabled === false);
  }
  function fresh(m) {
    return !!(m && m.contract_version === CONTRACT && m.source === 'local_runtime' &&
      m.control_plane && m.control_plane.runtime_present === true && m.stale === false &&
      typeof m.snapshot_age_seconds === 'number' &&
      Number.isFinite(m.snapshot_age_seconds) && m.snapshot_age_seconds <= 900);
  }
  function stamp(value) {
    if (!present(value)) return 'ثبت نشده';
    var d = new Date(value);
    return isNaN(d.getTime()) ? String(value) : d.toLocaleString('fa-IR', {year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
  }
  function field(name, value, tip) {
    return '<div class="ops-field"><span>' + safe(name) + '</span>' +
      '<strong>' + safe(value) + '</strong>' +
      (tip ? '<small>' + safe(tip) + '</small>' : '') + '</div>';
  }
  function numericEvidence(evidence, verified) {
    var rows = evidence && Array.isArray(evidence.validation) ?
      evidence.validation.filter(function(v){return v && typeof v === 'object';}).slice(0,48) : [];
    if (!rows.length) return '';
    function cell(n, suffix) {
      if (n === null || n === undefined || n === '' || !Number.isFinite(Number(n))) return '—';
      return Number(n).toLocaleString('fa-IR',{maximumFractionDigits:3}) + (suffix || '');
    }
    return '<div class="ops-results"><div class="ops-results-heading"><div><span class="ops-eyebrow">NUMERIC VALIDATION / HISTORICAL</span>' +
      '<h4>نتایج عددی ثبت‌شده</h4></div>' + tag(verified ? 'DONE' : 'UNKNOWN',
        verified ? 'تطبیق گزارش‌شدهٔ رسید QA' : 'فقط گزارش تولیدکننده') + '</div>' +
      '<div class="ops-results-note">نمونهٔ اعتبارسنجی تاریخی است؛ OOS دست‌نخورده، سودآوری یا مجوز دمو محسوب نمی‌شود.</div>' +
      '<div class="ops-results-scroll"><table><thead><tr><th>نماد / TF</th><th>هزینه</th><th>معاملات</th><th>بازده خالص</th><th>افت سرمایه</th><th>برد</th><th>PF</th></tr></thead><tbody>' +
      rows.map(function (v) {return '<tr><td>' + safe(v.symbol) + '<small>' + safe(v.timeframe) + '</small></td>' +
        '<td>' + safe(v.profile) + '</td><td>' + cell(v.closed_round_trips) + '</td>' +
        '<td>' + cell(v.net_return_pct,'%') + '</td><td>' + cell(v.max_drawdown_pct,'%') + '</td>' +
        '<td>' + cell(v.win_rate_pct,'%') + '</td><td>' + cell(v.profit_factor) + '</td></tr>';}).join('') +
      '</tbody></table></div></div>';
  }
  function countTile(label, value, note, kind) {
    return '<div class="ops-stat ' + (kind ? 'ops-stat--' + kind : '') + '">' +
      '<span>' + safe(label) + '</span><strong>' + safe(value) +
      '</strong><small>' + safe(note) + '</small></div>';
  }
  function mainTask(tasks) {
    return tasks.find(function(t) { return ACTIVE.indexOf(t.status) !== -1; }) ||
      tasks.find(function(t) { return BLOCKED.indexOf(t.status) !== -1; }) ||
      tasks.filter(function(t) {return t.status === 'DONE';}).slice(-1)[0] ||
      tasks[0] || null;
  }
  function empty(reason) {
    return '<div class="ops-empty"><span class="ops-empty-icon" aria-hidden="true">◇</span>' +
      '<strong>شواهد قابل نمایش موجود نیست</strong><p>' + safe(reason) + '</p></div>';
  }
  function row(t) {
    var verified = receiptVerified(t);
    var historicalStatus = !fresh(saved.mission) && ACTIVE.indexOf(t.status) !== -1;
    return '<button type="button" data-ops-task="' + safe(t.id) +
      '" class="ops-job ' + (saved.selected === t.id ? 'is-selected' : '') + '">' +
      '<span class="ops-job-id" dir="ltr">' + safe(t.id) + '</span>' +
      '<span class="ops-job-main"><strong>' + safe(t.title) + '</strong><small>' +
      safe(t.assigned_worker || 'عامل تخصیص نیافته') + ' · ' +
      safe(t.dispatch_transport || 'مسیر اجرا نامشخص') + '</small></span>' +
      '<span class="ops-job-state">' + tag(t.status, historicalStatus ? 'آرشیوی: ' + LABELS[stateOf(t.status)] : null) +
      (verified ? '<small class="ops-proof">رسیدهای QA منطبق (گزارش‌شده)</small>' : '') +
      '</span><span class="ops-job-arrow" aria-hidden="true">›</span></button>';
  }
  function matchFilter(t) {
    var f = saved.filter;
    if (f === 'active' && ACTIVE.indexOf(t.status) < 0) return false;
    if (f === 'blocked' && BLOCKED.indexOf(t.status) < 0) return false;
    if (f === 'done' && t.status !== 'DONE') return false;
    var q = saved.query.trim().toLowerCase();
    return !q || [t.id,t.title,t.status,t.assigned_worker,t.blocked_reason,t.failure_class]
      .some(function (s) {return String(s || '').toLowerCase().indexOf(q) >= 0;});
  }
  function renderQueue() {
    var m = saved.mission, all = tasksOf(m), rows = all.filter(matchFilter);
    var host = el('opsQueue');
    if (!host) return;
    host.innerHTML = rows.length ? rows.map(row).join('') :
      empty('هیچ مأموریتی با فیلتر انتخابی منطبق نیست؛ حذف یا تکمیل مصنوعی انجام نمی‌شود.');
    var ctr = el('opsQueueCount');
    if (ctr) ctr.textContent = rows.length + ' / ' + all.length + ' مأموریت';
    var buttons = document.querySelectorAll('[data-ops-filter]');
    Array.prototype.forEach.call(buttons,function (button) {
      button.setAttribute('aria-pressed',String(button.getAttribute('data-ops-filter') === saved.filter));
    });
    renderInspector();
  }
  function renderInspector() {
    var host = el('opsInspector'); if (!host) return;
    var tasks = tasksOf(saved.mission);
    var t = tasks.find(function (item) {return item.id === saved.selected;}) || mainTask(tasks);
    if (!t) {host.innerHTML = empty('تعریف یا snapshot مأموریت Research در این دستگاه وجود ندارد.');return;}
    var p = t.result_evidence || {}, qa = t.verification_evidence || {};
    var fields = [
      field('عامل مسئول',t.assigned_worker || t.producer || 'ثبت نشده'),
      field('QA مستقل',t.verifier || 'ثبت نشده'),
      field('شناسه اجاره',t.lease_id || 'ندارد'),
      field('آخرین heartbeat',stamp(t.heartbeat_at)),
      field('آخرین تأیید',stamp(t.verified_at)),
      field('تلاش',t.attempt ?? '—'),
      field('Source SHA',p.source_sha || 'ثبت نشده'),
      field('Mechanism',p.mechanism || 'هنوز اجرا نشده'),
      field('Dataset SHA',p.archive_sha256 || p.dataset_digest || 'ثبت نشده'),
      field('Config fingerprint',p.config_fingerprint || 'ثبت نشده')
    ];
    var reason = t.blocked_reason || t.failure_class || t.triage_reason;
    var proof = receiptVerified(t);
    var historicalStatus = !fresh(saved.mission) && ACTIVE.indexOf(t.status) !== -1;
    host.innerHTML = '<div class="ops-inspector-head"><div><span class="ops-eyebrow">TASK INSPECTOR / READ ONLY</span>' +
      '<h3>' + safe(t.title) + '</h3><p>' + code(t.id) + '</p></div>' + tag(t.status, historicalStatus ? 'آرشیوی: ' + LABELS[stateOf(t.status)] : null) + '</div>' +
      '<div class="ops-inspector-proof ' + (proof ? 'is-verified' : '') + '">' +
      '<strong>' + (proof ? 'تطبیق گزارش‌شدهٔ رسید تولیدکننده و QA مستقل' : 'مدرک QA مستقل هنوز تأیید نشده') +
      '</strong><small>' + (proof ? 'Evidence تاریخی؛ پذیرش دمو یا سودآوری را ثابت نمی‌کند.' :
      'وضعیت DONE یا موفقیت CI به‌تنهایی مدرک بک‌تست معتبر نیست.') + '</small></div>' +
      (reason ? '<div class="ops-block"><span>BLOCKER / REJECTION</span><p>' + safe(reason) + '</p></div>' : '') +
      '<div class="ops-details">' + fields.join('') + '</div>' +
      numericEvidence(p,proof) +
      '<div class="ops-digests"><div><span>Producer receipt</span>' + code(p.receipt_digest || '—') +
      '</div><div><span>Independent QA</span>' + code(qa.qa_digest || '—') + '</div>' +
      '<div><span>Novelty ledger</span>' + code(p.ledger_digest || '—') + '</div></div>' +
      '<div class="ops-policy-note">فقط Research / Paper. هیچ مجوزی برای افزودن خودکار استراتژی به دمو یا فعال‌کردن Live صادر نمی‌شود.</div>';
  }
  function stage(index, title, note, state) {
    var marker = state === 'evidence' ? '✓' : state === 'active' ? '◉' : '·';
    return '<div class="ops-stage ops-stage--' + state + '">' +
      '<span class="ops-stage-index">' + marker + '</span>' +
      '<div><b>' + safe(title) + '</b><small>' + safe(note) +
      '</small></div></div>';
  }
  function pipeline(tasks) {
    var proof = tasks.some(receiptVerified);
    var active = fresh(saved.mission) && tasks.some(function(t) {return ACTIVE.indexOf(t.status)!==-1;});
    var data = tasks.some(function(t) {return t.result_evidence && t.result_evidence.archive_sha256;});
    return '<div class="ops-pipeline">' +
      stage(0,'داده معتبر',data ? 'Artifact source-bound ثبت شده' : 'در انتظار شواهد',data?'evidence':'unknown') +
      stage(1,'Research Agent',active?'مأموریت در جریان':(tasks.some(function(t){return t.result_evidence;})?'خروجی تاریخی ثبت‌شده':'در انتظار خروجی'),active?'active':(tasks.some(function(t){return t.result_evidence;})?'evidence':'unknown')) +
      stage(2,'QA مستقل',proof?'Receipt منطبق':'تأیید نشده',proof?'evidence':'unknown') +
      stage(3,'ارزیابی شواهد','OOS و نتایج آینده‌نگر جداگانه','unknown') +
      stage(4,'ورود به دمو','قفل؛ نیازمند گیت مستقل','locked') +
      '</div>';
  }
  function workers(m, current) {
    var ids = ['research-agent','developer-agent','qa-verifier-agent','windows-runner'];
    var rows = (m.workers || []).filter(function(w) {return ids.indexOf(w.id)!==-1;});
    return rows.length ? rows.map(function(w) {
      var display = current ? stateOf(w.state) : 'UNKNOWN';
      var label = !current ? 'بدون مدرک زنده' : LABELS[display];
      var role = w.id === 'developer-agent' ? 'طراحی سازوکار' :
        w.id === 'research-agent' ? 'پژوهش و بک‌تست' :
        w.id === 'qa-verifier-agent' ? 'اعتبارسنجی مستقل' : 'اجرای روی ویندوز';
      return '<div class="ops-worker"><span class="ops-worker-avatar" aria-hidden="true">' +
        safe(w.id.slice(0,2).toUpperCase()) + '</span><div class="ops-worker-body"><strong>' +
        safe(role) + '</strong><span dir="ltr">' + safe(w.id) +
        '</span><small>' + safe((w.active_tasks || []).join('، ') || 'مأموریت فعال ثبت نشده') +
        '</small></div>' + tag(display,label) + '</div>';
    }).join('') : empty('پیکربندی عامل‌ها در این snapshot موجود نیست.');
  }
  function events(m) {
    var rows = (m.events || []).filter(function(e) {
      var txt = String(e.kind || '') + ' ' + String(e.task_id || '');
      return /research|QA|task_leased|task_result|verification/i.test(txt);
    }).slice(-7).reverse();
    return rows.length ? rows.map(function(e) {
      return '<li class="ops-event"><span class="ops-event-dot"></span><div><strong>' +
        safe(e.kind || 'رویداد') + '</strong><small>' + safe(e.task_id || '') +
        '</small><time>' + safe(stamp(e.at || e.generated_at)) + '</time></div></li>';
    }).join('') : '<li class="ops-event-empty">رویداد ذخیره‌شدهٔ قابل استناد موجود نیست.</li>';
  }
  function render(m, opts) {
    saved.mission=m; if(opts && typeof opts.onRefresh==='function') saved.onRefresh=opts.onRefresh;
    var host=el('agentState'); if (!host) return;
    if (!m || m.contract_version!==CONTRACT) {
      host.innerHTML='<div class="ops-shell">'+empty(m && m.reason ||
        'Agent Manager هنوز snapshot معتبر ندارد. فهرست نمایشی جایگزین شواهد واقعی نمی‌شود.')+'</div>';
      renderResearch(m); return;
    }
    var tasks=tasksOf(m), current=fresh(m), running=tasks.filter(function(t){return ACTIVE.indexOf(t.status)!==-1;}).length;
    var verified=tasks.filter(receiptVerified).length;
    var blocked=tasks.filter(function(t){return BLOCKED.indexOf(t.status)!==-1;}).length;
    if(!saved.selected || !tasks.some(function(t){return t.id===saved.selected;})) {
      saved.selected = mainTask(tasks) && mainTask(tasks).id;
    }
    var staleText = m.source==='definition_only' ? 'فقط تعریف مأموریت' :
      m.source==='imported_snapshot' ? 'Snapshot واردشده / تاریخی' :
      m.stale ? 'Snapshot قدیمی' : !current ? 'تازگی داده نامشخص' : 'وضعیت محلی معتبر';
    var owner = Array.isArray(m.owner_actions) && m.owner_actions.length && current ?
      '<div class="ops-owner">🔴 ' + m.owner_actions.length + ' اقدام واقعی مالک ثبت شده است.</div>' : '';
    host.innerHTML='<div class="ops-shell">' +
      '<div class="ops-hero"><div class="ops-hero-copy"><span class="ops-eyebrow">NEXUS / RESEARCH OPERATIONS</span>' +
      '<h2>فرماندهی پژوهش و عامل‌ها</h2><p>از تولید فرضیه تا بک‌تست و QA مستقل؛ متصل به شواهد محلی، نه وضعیت‌های نمایشی.</p>' +
      '<div class="ops-hero-meta">' + tag(current?'RUNNING':'UNKNOWN',staleText) +
      '<span>منبع: ' + safe(m.source) + '</span>' +
      '<span>آخرین snapshot: ' + safe(m.generated_at ? stamp(m.generated_at) : 'تاریخ نامشخص') + '</span></div></div>' +
      '<div class="ops-hero-actions"><div class="ops-paper">PAPER / RESEARCH ONLY<br><b>LIVE LOCKED</b></div>' +
      '<button class="ops-refresh" id="opsRefresh" type="button">↻ &nbsp; تازه‌سازی واقعی</button></div></div>' +
      (current?'':'<div class="ops-trust-warning">اطلاعات جاری تأیید نشده است؛ وضعیت عامل‌ها و مأموریت‌های آرشیوی به عنوان اجرای زنده نمایش داده نمی‌شود.</div>') +
      owner +
      '<div class="ops-stats">' +
      countTile('مأموریت‌های پژوهش',tasks.length,'تعریف‌شده در Agent Manager') +
      countTile('در حال اجرا',current?running:'—',current?'Lease / QA / triage واقعی':'نیازمند snapshot تازه','active') +
      countTile('مستندات QA',verified,'Receipt تولیدکننده و QA منطبق','verified') +
      countTile('نیازمند رسیدگی',blocked,'Blocked / Quarantined / Owner','warn') + '</div>' +
      '<div class="ops-section"><div class="ops-section-heading"><div><span class="ops-eyebrow">RESEARCH DELIVERY</span><h3>زنجیرهٔ اجرای پژوهش</h3></div><small>وضعیت هر گام فقط بر اساس شواهد قابل دسترس است</small></div>' +
      pipeline(tasks) + '</div>' +
      '<div class="ops-columns"><section class="ops-section ops-queue-panel">' +
      '<div class="ops-section-heading"><div><span class="ops-eyebrow">MISSION QUEUE</span><h3>صف عملیاتی</h3></div><span id="opsQueueCount" class="ops-counter"></span></div>' +
      '<div class="ops-toolbar"><div class="ops-filters" role="group" aria-label="فیلتر مأموریت">' +
      [['all','همه'],['active','در جریان'],['blocked','متوقف'],['done','تکمیل‌شده']].map(function(f) {
        return '<button type="button" data-ops-filter="' + f[0] + '">' + f[1] + '</button>';
      }).join('') + '</div><input type="search" id="opsSearch" aria-label="جستجوی مأموریت" placeholder="جستجوی شناسه، عامل یا خطا…" value="' + safe(saved.query) + '"></div>' +
      '<div id="opsQueue" class="ops-queue" role="list"></div></section>' +
      '<section class="ops-section ops-inspector" id="opsInspector" aria-live="polite"></section></div>' +
      '<div class="ops-columns ops-columns--bottom"><section class="ops-section"><div class="ops-section-heading"><div><span class="ops-eyebrow">ASSIGNED COMPONENTS</span><h3>اجزای مسئول</h3></div><small>بدون وضعیت ساختگی Online</small></div>' +
      '<div class="ops-workers">' + workers(m,current) + '</div></section>' +
      '<section class="ops-section"><div class="ops-section-heading"><div><span class="ops-eyebrow">AUDIT TRAIL</span><h3>آخرین رویدادهای Research</h3></div><small>فقط رویدادهای ثبت‌شده</small></div>' +
      '<ol class="ops-events">' + events(m) + '</ol></section></div></div>';
    var refresh=el('opsRefresh');
    if(refresh) refresh.addEventListener('click',function(){if(saved.onRefresh) saved.onRefresh();});
    host.onclick=function(ev) {
      var filter=ev.target.closest('[data-ops-filter]');
      if(filter){saved.filter=filter.getAttribute('data-ops-filter');renderQueue();return;}
      var chosen=ev.target.closest('[data-ops-task]');
      if(chosen){saved.selected=chosen.getAttribute('data-ops-task');renderQueue();}
    };
    var search=el('opsSearch');
    if(search)search.addEventListener('input',function(ev){saved.query=ev.target.value;renderQueue();});
    renderQueue();
    renderResearch(m);
  }
  function historicalMonth(m) {
    var archive = m && m.historical_monthly_research;
    if (!archive || archive.status !== 'verified_historical_only') {
      return '<div class="ops-month-absent"><b>آرشیو ماهانهٔ اعتبارسنجی‌شده متصل نیست</b>' +
        '<p>اتصال این آرشیو به استراتژی‌های زنده یا مجوز Paper ارتباط ندارد. نصب فعلی تا تأیید منبع تغییر نمی‌کند.</p></div>';
    }
    if (archive.paper_only !== true || archive.live_trading_authority !== false ||
        archive.auto_demo_admission !== false || archive.qualified_count !== 0 ||
        archive.cell_count !== 36 || archive.rejected_count !== 36 ||
        !Array.isArray(archive.cells) || archive.cells.length !== 36) {
      return '<div class="ops-month-absent">قرارداد آرشیو تاریخی نامعتبر است؛ نمایش نتایج متوقف شد.</div>';
    }
    var pairs = ['all','BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT'];
    var visible = archive.cells.filter(function(r) {
      return r && r.qualification === 'killed' &&
        (saved.monthPair === 'all' || r.symbol === saved.monthPair);
    });
    function figure(v, decimals) {
      return v === null || v === undefined || !Number.isFinite(Number(v)) ?
        '—' : Number(v).toLocaleString('fa-IR', {maximumFractionDigits:decimals});
    }
    return '<section class="ops-month" aria-label="آرشیو کامل بک‌تست ماهانه">' +
      '<header class="ops-month-head"><div><span class="ops-eyebrow">PINNED MONTHLY ARCHIVE / READ ONLY</span>' +
      '<h3>آرشیو بک‌تست ماهانه</h3><p>منبع: Bybit (طبق آرشیو هش‌بندی‌شده) · ' +
      safe(archive.month_start_utc) + ' تا ' + safe(archive.month_end_exclusive_utc) +
      ' UTC · دادهٔ تاریخی، نه پایش بازار زنده</p></div>' +
      '<span class="ops-month-seal">HASH VERIFIED · HISTORICAL</span></header>' +
      '<div class="ops-month-kpis">' +
      countTile('مجموع نتایج',figure(archive.cell_count,0),'۴ جفت‌ارز × ۳ TF × ۳ معیار پایه') +
      countTile('ردشده',figure(archive.rejected_count,0),'گیت پژوهشی، نه سود یک ماهه','warn') +
      countTile('پذیرفته‌شده برای دمو','۰','بدون عبور مستقل از گیت','warn') +
      '</div><div class="ops-month-warning">بازده مثبت تاریخی نشان‌دهندهٔ احراز شرایط نیست. این ۳ روش پایه، استراتژی‌های مرکب جدید محسوب نمی‌شوند و هیچ معامله‌ای از این جدول مجاز نیست.</div>' +
      '<div class="ops-month-tools"><div class="ops-month-filters" role="group" aria-label="فیلتر جفت‌ارز">' +
      pairs.map(function(p) {
        return '<button type="button" data-month-pair="' + safe(p) + '" aria-pressed="' +
          (saved.monthPair === p ? 'true' : 'false') + '">' +
          (p === 'all' ? 'همه' : safe(p.replace('USDT',' / USDT'))) + '</button>';
      }).join('') +
      '</div><small>' + figure(visible.length,0) + ' نتیجه · SHA ' +
      code(String(archive.report_sha256 || '').slice(0,16)) + '…</small></div>' +
      '<div class="ops-month-table-wrap" tabindex="0" aria-label="جدول قابل پیمایش نتایج">' +
      '<table class="ops-month-table"><thead><tr>' +
      '<th>جفت‌ارز / TF</th><th>روش پایه</th><th>بازده خالص</th><th>تنش هزینه</th>' +
      '<th>معاملات بسته</th><th>DD</th><th>نرخ برد</th><th>PF</th><th>نتیجه</th>' +
      '</tr></thead><tbody>' +
      visible.map(function(r) {
        return '<tr><td><b>' + safe(r.symbol) + '</b><small>' + safe(r.timeframe) + '</small></td>' +
          '<td>' + safe(r.strategy.replace('_',' ')) + '</td>' +
          '<td class="' + (Number(r.net_return_pct) < 0 ? 'is-negative' : '') + '">' +
          figure(r.net_return_pct,3) + '٪</td>' +
          '<td class="' + (Number(r.stress_net_return_pct) < 0 ? 'is-negative' : '') + '">' +
          figure(r.stress_net_return_pct,3) + '٪</td>' +
          '<td>' + figure(r.closed_trades,0) + '</td><td>' +
          figure(r.max_drawdown_pct,3) + '٪</td><td>' +
          figure(r.win_rate_pct,2) + '٪</td><td>' +
          figure(r.profit_factor,3) + '</td>' +
          '<td><span class="ops-month-rejected">ردشده</span></td></tr>';
      }).join('') + '</tbody></table></div>' +
      '<footer>منبع کد تاریخی: ' + code(String(archive.code_sha || '').slice(0,16)) +
      '… · قفل معاملات واقعی و ورود خودکار به دمو فعال است.</footer></section>';
  }
  function renderResearch(m) {
    var host=el('researchAgentOverview');if(!host)return;
    if(!m || m.contract_version!==CONTRACT) {
      host.innerHTML=empty('این پنل منتظر snapshot واقعی Agent Manager است؛ اجرای دستی پایین صفحه مسیر جداگانه‌ای دارد.');
      return;
    }
    var tasks=tasksOf(m), candidate=mainTask(tasks), verified=tasks.filter(receiptVerified).length;
    var current=fresh(m), blocker=tasks.find(function(t){return BLOCKED.indexOf(t.status)!==-1;});
    var lastVerified=tasks.filter(receiptVerified).slice(-1)[0];
    var lastNumeric=candidate && candidate.result_evidence && Array.isArray(candidate.result_evidence.validation) ? candidate : lastVerified;
    host.innerHTML='<div class="ops-research-title"><span class="ops-eyebrow">AUTONOMOUS / EVIDENCE-BOUND</span>' +
      '<h3>چرخهٔ مستقل Research Agent</h3><p>مسیر خودکار با اجرای دستی presetهای پایین صفحه یکی نیست.</p></div>' +
      '<div class="ops-research-cards">' +
      countTile('مأموریت منتخب',candidate?candidate.id:'ثبت نشده',candidate?(current?candidate.status:'آرشیوی / بدون شواهد زنده'):'منتظر Supervisor') +
      countTile('تأیید QA',verified,'رسیدهای منطبق (طبق snapshot)') +
      countTile('مکانیزم',candidate&&candidate.result_evidence&&candidate.result_evidence.mechanism || 'هنوز تأیید نشده','فقط از خروجی عددی ثبت‌شده') +
      countTile('گیت دمو','قفل','پذیرش جداگانه؛ هیچ ارتقای خودکار') + '</div>' +
      (lastNumeric ? numericEvidence(lastNumeric.result_evidence,receiptVerified(lastNumeric)) : '') +
      historicalMonth(m) +
      (blocker?'<div class="ops-block"><span>BLOCKER</span><p>' + safe(blocker.id) + ': ' +
        safe(blocker.blocked_reason||blocker.failure_class||'علت نامشخص') + '</p></div>':'') +
      '<div class="ops-research-link">جزئیات lease، مسیر اجرا و مدارک QA در تب «عامل‌ها و صف» قابل بررسی است.</div>';
    host.onclick=function(ev){var button=ev.target.closest('[data-month-pair]');if(button){saved.monthPair=button.getAttribute('data-month-pair');renderResearch(m);}};
  }
  window.NexusResearchOps={render:render,renderResearch:renderResearch};
})();