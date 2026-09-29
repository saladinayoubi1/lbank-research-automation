/* NEXUS Strategy Workspace — owner-local, real ledger, no fake execution. */
(function () {
  'use strict';
  var el = function(id){return document.getElementById(id);};
  var esc = function(v){return String(v === undefined || v === null ? '' : v).replace(/[&<>"']/g,function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
  });};
  var s={data:null,filter:'all',search:'',busy:false};
  var labels={
    structural_pullback:'Structural Pullback / پول‌بک ساختاری',
    volatility_compression_expansion:'Volatility Compression / انقباض و گسترش',
    bar_proxy_vwap_reclaim:'Bar VWAP Proxy / بازپس‌گیری',
    failed_range_break_reversal:'Failed Break / شکست ناموفق محدوده',
    cross_pair_relative_reclaim:'Cross-Pair Reclaim / بازپس‌گیری نسبی',
    lagged_peer_impulse_confirmation:'Lagged Peer / تأیید حرکت جفت مرجع',
    peer_shock_noncontagion_rebound:'Peer Shock / بازگشت بدون سرایت',
    momentum:'Momentum (مرجع ساده)',
    trend_breakout:'Trend Breakout (مرجع ساده)',
    mean_reversion:'Mean Reversion (مرجع ساده)'
  };
  var dataNames={
    closed_ohlcv:'کندل بسته‌شده و معتبر OHLCV',
    aligned_peer_ohlcv:'کندل هم‌زمان جفت مرجع',
    authenticated_trade_flow:'جریان معاملات تأییدشده',
    open_interest:'Open Interest معتبر',
    funding_rate:'نرخ Funding معتبر',
    order_book_l2:'دفتر سفارش L2 معتبر'
  };
  function pct(v){return typeof v === 'number' && Number.isFinite(v) ?
    (v*100).toLocaleString('fa-IR',{maximumFractionDigits:2})+'٪':'—';}
  function val(v){return v === undefined || v === null || v === '' ? '—' : esc(v);}
  function short(v){return esc(v ? String(v).slice(0,13)+'…' : '—');}
  function panel(){return el('strategyWorkspace');}
  async function api(path,options){
    var opt=Object.assign({cache:'no-store',credentials:'same-origin'},options||{});
    opt.headers=Object.assign({Accept:'application/json'},opt.headers||{});
    if(opt.body)opt.headers['Content-Type']='application/json';
    var res=await fetch(path,opt),payload=await res.json().catch(function(){return {};});
    if(!res.ok)throw Error(payload.detail||payload.error||'HTTP '+res.status);
    return payload;
  }
  function stateMessage(message,bad){
    var host=el('workspaceFeedback');if(host){host.textContent=message;host.className='sw-feedback '+(bad?'is-error':'is-info');}
  }
  function shell(){
    var view=el('view-strategies');
    if(!view || panel())return;
    var host=document.createElement('section');host.id='strategyWorkspace';host.className='strategy-workspace';
    host.innerHTML=
      '<header class="sw-hero"><div><span class="sw-kicker">NEXUS / STRATEGY RESEARCH TERMINAL</span>'+
      '<h2>Strategy Workspace <small> / استراتژی‌های من</small></h2>'+
      '<p>انتخاب، طراحی و بررسی فرضیه؛ فقط خروجی واقعی بک‌تست وارد گزارش می‌شود. انتخاب به معنای فعال‌سازی دمو نیست.</p></div>'+
      '<strong class="sw-authority">RESEARCH / PAPER<br>LIVE DISABLED</strong></header>'+
      '<div id="workspaceFeedback" class="sw-feedback is-info" role="status">در حال خواندن مدارک محلی…</div>'+
      '<div class="sw-stats" id="workspaceStats"></div>'+
      '<div class="sw-main">'+
      '<section class="sw-card sw-browser"><div class="sw-title"><div><span class="sw-kicker">MECHANISM LIBRARY</span><h3>انتخاب استراتژی</h3></div>'+
      '<button type="button" id="workspaceRefresh" class="sw-secondary">↻ تازه‌سازی</button></div>'+
      '<div class="sw-toolbar"><input id="workspaceSearch" type="search" placeholder="جستجوی نام، مکانیزم یا فرضیه…" aria-label="جستجوی استراتژی">'+
      '<div class="sw-filters" role="group" aria-label="نوع استراتژی">'+
      '<button type="button" data-sw-filter="all" aria-pressed="true">همه</button>'+
      '<button type="button" data-sw-filter="causal" aria-pressed="false">ترکیبی و علّی</button>'+
      '<button type="button" data-sw-filter="mine" aria-pressed="false">استراتژی‌های من</button>'+
      '<button type="button" data-sw-filter="legacy" aria-pressed="false">مرجع ساده</button></div></div>'+
      '<div id="workspaceCards" class="sw-list" aria-live="polite"></div></section>'+
      '<section class="sw-side"><div id="workspaceSelected" class="sw-card"></div>'+
      '<details id="workspaceNew" class="sw-card sw-new"><summary><span>＋</span> طراحی و افزودن استراتژی جدید</summary>'+
      '<form id="workspaceForm" class="sw-form"><p>فقط ثبت پروپوزال پژوهشی؛ هر روش تازه قبل از اجرا به پیاده‌سازی و بررسی مستقل نیاز دارد.</p>'+
      '<label>نام استراتژی<input name="name" required minlength="3" maxlength="100" placeholder="مثلاً شکست ناموفق در فاز تغییر رژیم"></label>'+
      '<label>مکانیزم<select name="mechanism" id="workspaceMechanism"></select></label>'+
      '<label>یا مکانیزم جدید<input name="custom_mechanism" maxlength="120" placeholder="اختیاری: مکانیزم تازه قابل ابطال"></label>'+
      '<label>فرضیهٔ علّی و شروط ورود<textarea name="hypothesis" required minlength="20" maxlength="1200" rows="4" placeholder="چه اتفاقی، چرا، با چه ورودی قابل‌مشاهده و در چه شرایطی؟"></textarea></label>'+
      '<label>ابطال فرضیه و شرایط خروج<textarea name="invalidation" required minlength="20" maxlength="1200" rows="3" placeholder="چه داده یا نتیجه‌ای نشان می‌دهد روش رد شده است؟"></textarea></label>'+
      '<fieldset id="workspacePairs"><legend>جفت‌ارزها</legend></fieldset>'+
      '<fieldset id="workspaceTimeframes"><legend>تایم‌فریم‌ها</legend></fieldset>'+
      '<fieldset id="workspaceInputs"><legend>ورودی‌های مورد نیاز (طبق منبع واقعی)</legend></fieldset>'+
      '<button type="submit" id="workspaceSubmit" class="sw-primary">ثبت پروپوزال در حافظهٔ محلی</button></form></details></section></div>'+
      '<section class="sw-card sw-ledger"><div class="sw-title"><div><span class="sw-kicker">MEASURED / NOT PROMOTED</span>'+
      '<h3>دفتر واقعی نتایج بک‌تست</h3></div><span id="workspaceCount" class="sw-pill">—</span></div>'+
      '<p class="sw-footnote">اعداد صرفاً از دفتر ثبت‌شدهٔ Research؛ اجرای CI، انتخاب روش یا نتیجهٔ تاریخی، به معنی تأیید مستقل، OOS دست‌نخورده یا اجازهٔ دمو نیست.</p>'+
      '<div id="workspaceHistory" class="sw-scroll" aria-live="polite"></div></section>';
    var original=view.querySelector('.section-head');
    view.insertBefore(host,original ? original.nextSibling : view.firstChild);
    var research=el('view-research');
    if(research&&!el('workspaceResearchHistory')){
      var compact=document.createElement('article');compact.className='panel sw-research-entry';compact.id='workspaceResearchHistory';
      compact.innerHTML='<header><div><span>HISTORICAL EVIDENCE</span><h2>دفتر نتایج پژوهش‌های اجراشده</h2></div>'+
        '<button type="button" id="workspaceResearchRefresh" class="small-btn">تازه‌سازی تاریخچه</button></header>'+
        '<div class="sw-research-summary" id="workspaceResearchSummary">فقط خروجی عددی واقعی</div>';
      var layout=research.querySelector('.research-layout');
      research.insertBefore(compact,layout||null);
    }
    var legacy=el('strategyFamilies');
    if(legacy&&legacy.parentElement&&legacy.parentElement.classList.contains('panel')){
      var legacyPanel=legacy.parentElement;legacyPanel.classList.add('sw-legacy-panel');
      var hint=document.createElement('p');hint.className='sw-footnote';
      hint.textContent='کارت‌های سنتی فقط مرجع هستند؛ وضعیت آن‌ها صلاحیت دمو یا موفقیت پژوهش را ثابت نمی‌کند.';
      legacyPanel.insertBefore(hint,legacy);
    }
  }
  function itemLabel(x){
    return x.kind==='owner_research_proposal'?'PROPOSAL / REVIEW REQUIRED':
      x.kind==='legacy_reference_only'?'LEGACY / MANUAL BASELINE':'COMPOSITE / AGENT REQUIRED';
  }
  function allItems(){
    return s.data ? [].concat(s.data.catalog||[],s.data.proposals||[]) : [];
  }
  function selectedItem(){
    return allItems().find(function(x){return x.id===s.data.selected_id;})||null;
  }
  function cards(){
    var result=allItems().filter(function(x){
      if(s.filter==='mine'&&x.kind!=='owner_research_proposal')return false;
      if(s.filter==='causal'&&x.kind!=='reviewed_causal_family')return false;
      if(s.filter==='legacy'&&x.kind!=='legacy_reference_only')return false;
      var search=s.search.toLowerCase().trim();
      return !search||[x.name,x.mechanism,x.hypothesis].some(function(v){
        return String(v||'').toLowerCase().indexOf(search)!==-1;
      });
    });
    el('workspaceCards').innerHTML=result.length?result.map(function(x){
      var selected=s.data.selected_id===x.id;
      var detail=x.hypothesis||('ورودی: '+(x.required_data||[]).map(function(k){return dataNames[k]||k;}).join('، '));
      return '<article class="sw-strategy '+(selected?'is-selected':'')+'"><div>'+
        '<span class="sw-type">'+esc(itemLabel(x))+'</span><h4>'+esc(labels[x.mechanism]||x.name)+'</h4>'+
        (x.name!==x.mechanism&&x.kind==='owner_research_proposal'?'<b>'+esc(x.name)+'</b>':'')+
        '<p>'+esc(detail)+'</p></div><button data-sw-select="'+esc(x.id)+'" class="'+(selected?'sw-active':'sw-secondary')+
        '" type="button" '+(selected?'disabled':'')+'>'+(selected?'انتخاب‌شده':'انتخاب برای پژوهش')+'</button></article>';
    }).join(''):'<div class="sw-empty">استراتژی مطابق فیلتر موجود نیست.</div>';
    panel().querySelectorAll('[data-sw-filter]').forEach(function(btn){
      btn.setAttribute('aria-pressed',String(btn.dataset.swFilter===s.filter));
    });
  }
  function options(items,selected){return items.map(function(x){
    return '<option value="'+esc(x.id)+'" '+(x.id===selected?'selected':'')+'>'+esc(x.label)+'</option>';
  }).join('');}
  function selection(){
    var x=selectedItem(),host=el('workspaceSelected');
    if(!x){host.innerHTML='<div class="sw-title"><span class="sw-kicker">ACTIVE RESEARCH FOCUS</span></div>'+
      '<div class="sw-empty"><b>هنوز استراتژی انتخاب نشده</b><p>از کتابخانهٔ مکانیزم‌های واقعی یکی را انتخاب کن یا فرضیهٔ تازه ثبت کن.</p></div>';return;}
    var input=(x.required_data||[]).map(function(i){return '<span>'+esc(dataNames[i]||i)+'</span>';}).join('');
    var manual=x.execution==='canonical_manual_offline_available';
    var data=(s.data.datasets||[]).filter(function(d){return d&&d.binding_sha256&&/^[0-9a-f]{64}$/.test(d.binding_sha256);});
    host.innerHTML='<span class="sw-kicker">SELECTED / READ-ONLY FOCUS</span><h3>'+esc(x.name)+'</h3>'+
      '<p class="sw-status">'+esc(itemLabel(x))+'</p>'+
      '<div class="sw-facts"><div><span>مکانیزم</span><b>'+esc(x.mechanism)+'</b></div>'+
      '<div><span>اجرای مستقیم</span><b>'+(manual?'فقط مقایسهٔ مرجع با دادهٔ معتبر':'نیازمند عامل پژوهش و بازبینی کد')+'</b></div>'+
      '<div><span>مجوز دمو</span><b>قفل؛ ارزیابی مستقل و آینده‌نگر لازم است</b></div></div>'+
      (x.hypothesis?'<div class="sw-narrative"><strong>فرضیه</strong><p>'+esc(x.hypothesis)+'</p>'+
      '<strong>ابطال</strong><p>'+esc(x.invalidation)+'</p></div>':'')+
      '<div class="sw-input-tags">'+input+'</div>'+
      (manual?'<div class="sw-run"><label>Dataset محلی معتبر<select id="workspaceDataset">'+
        '<option value="">انتخاب Dataset</option>'+options(data.map(function(v){
          return {id:v.binding_sha256,label:v.source_symbol+' / '+v.timeframe+' / '+v.row_count+' candles'};
        }),null)+'</select></label>'+
        '<button type="button" class="sw-primary" id="workspaceRun" '+(data.length?'':'disabled')+
        '>اجرای Research مرجع از دادهٔ واقعی</button></div>':
      '<p class="sw-notice">این مکانیزم فقط به‌عنوان هدف پژوهش انتخاب شده است. اتصال به صف واقعی Supervisor / Developer Agent و QA هنوز باید با شواهد اجرایی تأیید شود؛ اجرا یا نتیجهٔ ساختگی نشان داده نمی‌شود.</p>')+
      '<div id="workspaceSelectedState" class="sw-footnote" role="status">انتخاب فقط در حافظهٔ محلی ثبت شده است.</div>';
    if(manual){
      var run=el('workspaceRun');
      if(run)run.onclick=function(){void runManual(x.id);};
    }
  }
  function history(){
    if(!s.data)return;
    var rows=(s.data.history||[]).slice().reverse(),host=el('workspaceHistory'),summary=el('workspaceResearchSummary');
    el('workspaceCount').textContent=rows.length+' نتیجهٔ ثبت‌شده';
    if(summary)summary.innerHTML='<span><b>'+esc(rows.length)+'</b> گزارش محلی واقعی</span>'+
      '<span>QA مستقل: هنوز ادعا نمی‌شود</span><span>گیت Paper: قفل</span>'+
      (rows.length?'<div>آخرین اجرا: '+esc(rows[0].family)+' · '+esc(rows[0].symbol)+' · '+esc(rows[0].timeframe)+'</div>':
      '<div>هیچ خروجی واقعی ثبت نشده؛ برای نتایج خودکار به رسیدهای معتبر Agent نیاز است.</div>');
    if(!rows.length){host.innerHTML='<div class="sw-empty"><b>هیچ بک‌تست ثبت‌شده‌ای موجود نیست.</b>'+
      '<p>بعد از اجرای واقعی، زمان، جفت‌ارز، تایم‌فریم، معاملات، بازده، افت سرمایه و SHA داده اینجا درج می‌شوند.</p>'+
      '<small>'+esc(s.data.agent_evidence_reason||'Agent evidence unavailable')+'</small></div>';return;}
    host.innerHTML='<table class="sw-table"><thead><tr><th>زمان / روش</th><th>جفت / TF</th><th>بازده</th>'+
      '<th>افت سرمایه</th><th>Fills</th><th>برد</th><th>PF</th><th>وضعیت</th><th>Provenance</th></tr></thead><tbody>'+
      rows.map(function(x){
        return '<tr><td><strong>'+esc(x.family||'—')+'</strong><small>'+esc(x.recorded_at||'—')+'</small></td>'+
          '<td>'+esc(x.symbol||'—')+'<small>'+esc(x.timeframe||'—')+'</small></td>'+
          '<td class="'+(typeof x.total_return==='number'&&x.total_return<0?'sw-loss':'')+'">'+pct(x.total_return)+'</td>'+
          '<td>'+pct(x.max_drawdown)+'</td><td>'+val(x.fill_count)+'</td>'+
          '<td>'+pct(x.win_rate)+'</td><td>'+val(x.profit_factor)+'</td>'+
          '<td><span class="sw-unverified">'+esc(x.qualification||'—')+'</span>'+
          '<small>Historical / QA جداگانه</small></td>'+
          '<td><details><summary>مدرک</summary><code>Data: '+esc(x.dataset_binding_sha256||'—')+
          '<br>Source: '+esc(x.source_sha||'نامشخص')+'<br>Rows: '+val(x.row_count)+
          '<br>Mode: '+esc(x.data_mode||'—')+'<br>Stress: '+val(x.stress)+
          '<br>Reason: '+esc(JSON.stringify(x.reason||[]))+'</code></details></td></tr>';
      }).join('')+'</tbody></table>';
  }
  function stats(){
    if(!s.data)return;
    var total=s.data.proposals.length,advanced=s.data.catalog.filter(function(x){return x.kind==='reviewed_causal_family';}).length;
    el('workspaceStats').innerHTML=[
      ['مکانیزم‌های ترکیبی',advanced,'تعریف‌شده در موتور مستقل'],
      ['فرضیه‌های ثبت‌شده',total,'طرح، نه اجرای خودکار'],
      ['نتایج تاریخی محلی',s.data.run_count,'از دفتر واقعی Research'],
      ['گیت دمو','LOCKED','QA / prospective جدا']
    ].map(function(row){
      return '<div><span>'+esc(row[0])+'</span><strong>'+esc(row[1])+'</strong><small>'+esc(row[2])+'</small></div>';
    }).join('');
  }
  function render(){
    if(!s.data)return;stats();cards();selection();history();
    stateMessage('اطلاعات از حافظهٔ محلی خوانده شد. اجرای مستقل Research Agent و پذیرش دمو جداگانه تأیید می‌شوند.',false);
  }
  async function refresh(){
    if(s.busy)return;
    try{s.data=await api('/api/product/strategy-workspace');render();}
    catch(error){stateMessage('خواندن Workspace ناموفق: '+error.message,true);}
  }
  async function select(id){
    if(s.busy)return;s.busy=true;
    try{await api('/api/product/strategy-workspace/select',{method:'POST',body:JSON.stringify({strategy_id:id})});
      s.data=await api('/api/product/strategy-workspace');render();
    }catch(error){stateMessage('انتخاب رد شد: '+error.message,true);}finally{s.busy=false;}
  }
  async function runManual(id){
    if(s.busy)return;
    var dataset=el('workspaceDataset');
    if(!dataset||!dataset.value){stateMessage('یک Dataset واردشدهٔ معتبر انتخاب کن.',true);return;}
    s.busy=true;stateMessage('اجرای واقعی مقایسهٔ مرجع؛ داده و Risk مستقل بررسی می‌شوند…',false);
    try{
      var result=await api('/api/product/strategy-workspace/research',{method:'POST',
        body:JSON.stringify({strategy_id:id,binding_sha256:dataset.value})});
      s.data=await api('/api/product/strategy-workspace');render();
      stateMessage('Research واقعی ثبت شد: '+result.request.family+' / '+result.qualification.status+
        '. این یک مرجع تاریخی است، نه تأیید QA یا اجازهٔ دمو.',false);
    }catch(error){stateMessage('اجرای پژوهش رد شد: '+error.message,true);}
    finally{s.busy=false;}
  }
  function checked(fieldset){
    return Array.from(fieldset.querySelectorAll('input:checked')).map(function(x){return x.value;});
  }
  function makeChecks(id,items,selected){
    var host=el(id);if(!host)return;
    host.insertAdjacentHTML('beforeend',items.map(function(x){
      return '<label><input type="checkbox" value="'+esc(x.id)+'" '+(selected.indexOf(x.id)!==-1?'checked':'')+
        '><span>'+esc(x.label)+'</span></label>';
    }).join(''));
  }
  function formInit(){
    var items=['','structural_pullback','volatility_compression_expansion',
      'bar_proxy_vwap_reclaim','failed_range_break_reversal','cross_pair_relative_reclaim',
      'lagged_peer_impulse_confirmation','peer_shock_noncontagion_rebound'];
    el('workspaceMechanism').innerHTML=items.map(function(key){
      return '<option value="'+esc(key)+'">'+esc(key ? (labels[key]||key):'— انتخاب مکانیزم —')+'</option>';
    }).join('');
    makeChecks('workspacePairs',['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','BNBUSDT'].map(function(x){
      return {id:x,label:x};
    }),['BTCUSDT','ETHUSDT']);
    makeChecks('workspaceTimeframes',['15m','1h','4h'].map(function(x){return {id:x,label:x};}),['15m','1h','4h']);
    makeChecks('workspaceInputs',Object.keys(dataNames).map(function(x){return {id:x,label:dataNames[x]};}),['closed_ohlcv']);
  }
  async function submit(ev){
    ev.preventDefault();if(s.busy)return;s.busy=true;
    var form=el('workspaceForm'),f=new FormData(form);
    var payload={
      name:String(f.get('name')||'').trim(),mechanism:String(f.get('custom_mechanism')||'').trim()||
        String(f.get('mechanism')||''),
      hypothesis:String(f.get('hypothesis')||'').trim(),
      invalidation:String(f.get('invalidation')||'').trim(),
      symbols:checked(el('workspacePairs')),
      timeframes:checked(el('workspaceTimeframes')),
      required_data:checked(el('workspaceInputs'))
    };
    try{
      var proposal=await api('/api/product/strategy-workspace/propose',{method:'POST',
        body:JSON.stringify(payload)});
      await api('/api/product/strategy-workspace/select',{method:'POST',body:JSON.stringify({strategy_id:proposal.id})});
      s.data=await api('/api/product/strategy-workspace');
      form.reset();render();el('workspaceNew').open=false;
      stateMessage('طرح پژوهش ذخیره و انتخاب شد. برای اجرای مکانیزم تازه، پیاده‌سازی و QA مستقل لازم است.',false);
    }catch(error){stateMessage('ثبت طرح رد شد: '+error.message,true);}
    finally{s.busy=false;}
  }
  function bind(){
    panel().addEventListener('click',function(ev){
      var filter=ev.target.closest('[data-sw-filter]');
      if(filter){s.filter=filter.dataset.swFilter;cards();return;}
      var button=ev.target.closest('[data-sw-select]');
      if(button)void select(button.dataset.swSelect);
    });
    el('workspaceSearch').addEventListener('input',function(ev){s.search=ev.target.value;cards();});
    el('workspaceRefresh').addEventListener('click',function(){void refresh();});
    el('workspaceResearchRefresh')?.addEventListener('click',function(){void refresh();});
    el('workspaceForm').addEventListener('submit',submit);
  }
  function start(){shell();if(!panel())return;formInit();bind();void refresh();}
  window.NexusStrategyWorkspace={refresh:refresh};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});
  else start();
})();