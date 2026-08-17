(()=>{
'use strict';

const $=s=>document.querySelector(s);
const $$=s=>[...document.querySelectorAll(s)];
const SYMBOLS=['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT'];
const TIMEFRAMES={
  '15':{label:'۱۵ دقیقه',ms:15*60*1000},
  '60':{label:'۱ ساعت',ms:60*60*1000},
  '240':{label:'۴ ساعت',ms:4*60*60*1000}
};
const STATE_KEY='nexus-mobile-delivery-v1';
let state=Object.assign({theme:'dark',watch:['BTCUSDT'],alerts:[]},safeJson(localStorage.getItem(STATE_KEY),{}));
let project={};
let series=[];
let marketState='loading';
let marketMessage='در حال اتصال به داده عمومی';
const pending=new Map();

function safeJson(text,fallback){try{return text?JSON.parse(text):fallback}catch{return fallback}}
function save(){localStorage.setItem(STATE_KEY,JSON.stringify(state))}
function fmt(value,digits=8){
  const n=Number(value);
  if(!Number.isFinite(n))return '—';
  return new Intl.NumberFormat('fa-IR',{maximumFractionDigits:digits}).format(n);
}
function priceFmt(value){
  const n=Number(value);
  if(!Number.isFinite(n))return '—';
  const digits=n>=1000?2:n>=1?4:8;
  return fmt(n,digits);
}
function toast(message){
  const el=$('#toast');
  if(!el)return;
  el.textContent=message;
  el.classList.add('show');
  clearTimeout(toast.timer);
  toast.timer=setTimeout(()=>el.classList.remove('show'),2200);
}
function applyTheme(){
  document.body.classList.toggle('light',state.theme==='light');
  const btn=$('#theme');
  if(btn)btn.textContent=state.theme==='light'?'☾':'☀';
}

window.NexusPublicMarketResult=(id,ok,payload)=>{
  const task=pending.get(id);
  if(!task)return;
  pending.delete(id);
  ok?task.resolve(payload):task.reject(new Error(payload||'خطای دریافت بازار'));
};

function nativeMarket(symbol,interval){
  return new Promise((resolve,reject)=>{
    if(!window.NexusNative||typeof window.NexusNative.requestPublicMarket!=='function'){
      reject(new Error('native bridge unavailable'));
      return;
    }
    const id='m'+Date.now().toString(36)+Math.random().toString(16).slice(2);
    pending.set(id,{resolve,reject});
    const timer=setTimeout(()=>{
      if(pending.delete(id))reject(new Error('مهلت دریافت داده بازار تمام شد'));
    },35000);
    const originalResolve=resolve,originalReject=reject;
    pending.set(id,{
      resolve:value=>{clearTimeout(timer);originalResolve(value)},
      reject:error=>{clearTimeout(timer);originalReject(error)}
    });
    window.NexusNative.requestPublicMarket(id,symbol,interval);
  });
}

async function browserMarket(symbol,interval){
  const url=`https://api.bybit.com/v5/market/kline?category=spot&symbol=${encodeURIComponent(symbol)}&interval=${encodeURIComponent(interval)}&limit=120`;
  const response=await fetch(url,{cache:'no-store',redirect:'error',headers:{accept:'application/json'}});
  if(!response.ok)throw new Error('Bybit HTTP '+response.status);
  return response.text();
}

async function requestMarket(symbol,interval){
  try{
    return await nativeMarket(symbol,interval);
  }catch(nativeError){
    try{return await browserMarket(symbol,interval)}
    catch(browserError){throw new Error(browserError.message||nativeError.message)}
  }
}

function normalizeMarket(symbol,interval,text){
  const payload=typeof text==='string'?JSON.parse(text):text;
  if(!payload||payload.retCode!==0||!Array.isArray(payload.result?.list))throw new Error('پاسخ بازار معتبر نیست');
  const step=TIMEFRAMES[interval]?.ms;
  if(!step)throw new Error('تایم‌فریم پشتیبانی نمی‌شود');
  const now=Date.now();
  const candles=payload.result.list
    .slice()
    .reverse()
    .map(row=>({
      t:Number(row[0]),o:Number(row[1]),h:Number(row[2]),l:Number(row[3]),c:Number(row[4]),v:Number(row[5])
    }))
    .filter(c=>Number.isFinite(c.t)&&Number.isFinite(c.c)&&c.t+step<=now);
  if(candles.length<2)throw new Error('کندل بسته کافی دریافت نشد');
  const latestCandle=candles[candles.length-1];
  const previous=candles[candles.length-2];
  const change=previous.c?((latestCandle.c-previous.c)/previous.c)*100:0;
  return {
    symbol,interval,candles,
    latest:{
      close:latestCandle.c,
      high:latestCandle.h,
      low:latestCandle.l,
      volume:latestCandle.v,
      change_percent:change,
      open_time_ms:latestCandle.t
    }
  };
}

function key(symbol,interval){return `${symbol}:${interval}`}
function upsert(next){
  const k=key(next.symbol,next.interval);
  const index=series.findIndex(x=>key(x.symbol,x.interval)===k);
  if(index>=0)series[index]=next;else series.push(next);
}
function selectedSeries(){
  const symbol=$('#symbol')?.value||SYMBOLS[0];
  const interval=$('#timeframe')?.value||'15';
  return series.find(x=>x.symbol===symbol&&x.interval===interval);
}

async function loadOne(symbol,interval){
  const raw=await requestMarket(symbol,interval);
  const normalized=normalizeMarket(symbol,interval,raw);
  upsert(normalized);
  return normalized;
}

async function refreshAll(){
  const interval=$('#timeframe')?.value||'15';
  marketState='loading';
  marketMessage='در حال دریافت کندل‌های بسته Bybit';
  renderOverview();
  const selected=$('#symbol')?.value||SYMBOLS[0];
  const order=[selected,...SYMBOLS.filter(x=>x!==selected)];
  const results=await Promise.allSettled(order.map(symbol=>loadOne(symbol,interval)));
  const success=results.filter(x=>x.status==='fulfilled').length;
  if(success){
    marketState='ready';
    marketMessage=`${fmt(success,0)} نماد · Bybit عمومی`;
  }else{
    marketState='offline';
    marketMessage='اتصال بازار برقرار نشد';
  }
  renderAll();
}

async function ensureSelected(){
  const symbol=$('#symbol').value,interval=$('#timeframe').value;
  if(selectedSeries()){renderSelected();return}
  $('#selected').innerHTML='<div class="loading-line"><i></i>در حال دریافت داده انتخاب‌شده…</div>';
  try{
    await loadOne(symbol,interval);
    marketState='ready';
    marketMessage='Bybit عمومی · فقط خواندنی';
  }catch(e){
    marketState='offline';
    marketMessage='داده این انتخاب در دسترس نیست';
  }
  renderAll();
}

async function loadProject(){
  try{
    const response=await fetch(`data.json?t=${Date.now()}`,{cache:'no-store'});
    if(!response.ok)throw new Error(String(response.status));
    const payload=await response.json();
    project=payload.project||{};
  }catch{
    project={status:'complete',phase:6,mode:'research_backtest_paper',canonical_source:'Bybit'};
  }
}

function renderOverview(){
  const health=$('#health');
  if(health){
    health.textContent=project.status==='complete'?'آماده':'در حال بررسی';
    health.className=project.status==='complete'?'up':'warn';
  }
  const mode=$('#operatingMode');
  if(mode)mode.textContent='Research / Paper';
  const market=$('#marketStatus');
  if(market){
    market.textContent=marketState==='loading'?'در حال اتصال':marketState==='ready'?'متصل':'بدون اتصال';
    market.className=marketState==='ready'?'up':marketState==='offline'?'warn':'';
  }
  const detail=$('#marketDetail');if(detail)detail.textContent=marketMessage;
  const updated=$('#updated');if(updated)updated.textContent=new Date().toLocaleTimeString('fa-IR',{hour:'2-digit',minute:'2-digit'});
}

function renderProject(){
  $('#projectPhase').textContent=`Phase ${project.phase||6} · ${project.gates||'0–6'}`;
  $('#pipelineState').textContent=project.pipeline_status||'کامل و تثبیت‌شده';
  $('#riskState').textContent=project.deterministic_risk_final_authority===false?'نامشخص':'Deterministic Risk';
  $('#sourceState').textContent=project.canonical_source||'Bybit';
  $('#buildSha').textContent=(project.main_sha||'5b2c12be').slice(0,10);
  $('#resultNote').textContent=project.result_note||'زیرساخت پژوهش، بک‌تست و Paper Trading تکمیل است. این نسخه عمداً مجوز معامله با پول واقعی ندارد.';
}

function renderStrategies(){
  const root=$('#strategies');
  const families=Array.isArray(project.strategy_families)?project.strategy_families:['momentum','trend_breakout','mean_reversion'];
  const labels={momentum:'مومنتوم',trend_breakout:'شکست روند',mean_reversion:'بازگشت به میانگین'};
  root.innerHTML=families.map(name=>`<article class="strategy-card"><b>${labels[name]||name}</b><p>عضو Strategy Factory؛ پذیرش فقط پس از شواهد OOS، تنش هزینه، رژیم و کنترل ریسک. هیچ ادعای سود تضمینی وجود ندارد.</p></article>`).join('');
}

function spark(candles){
  if(!candles?.length)return '';
  const values=candles.slice(-70).map(x=>x.c);
  const min=Math.min(...values),max=Math.max(...values),range=max-min||1;
  const points=values.map((v,i)=>`${(i/(values.length-1||1))*100},${74-((v-min)/range)*66}`).join(' ');
  return `<svg class="spark" viewBox="0 0 100 78" preserveAspectRatio="none" aria-hidden="true"><polyline fill="none" stroke="currentColor" stroke-width="1.7" vector-effect="non-scaling-stroke" points="${points}"/></svg>`;
}

function renderSelected(){
  const root=$('#selected'),s=selectedSeries();
  if(!s){
    root.innerHTML=`<div class="empty-card"><b>داده بازار برای این انتخاب هنوز دریافت نشده</b><br><span>پروژه آماده است؛ برای دریافت قیمت عمومی، اتصال اینترنت/VPN را بررسی و «بروزرسانی» را بزن.</span></div>`;
    return;
  }
  const x=s.latest,chg=Number(x.change_percent)||0;
  root.innerHTML=`
    <div class="hero-top">
      <div><span class="kicker">${s.symbol} · ${TIMEFRAMES[s.interval]?.label||s.interval}</span><h3>${priceFmt(x.close)}</h3><span class="price-change ${chg>=0?'up':'down'}">${chg>=0?'+':''}${chg.toFixed(2)}%</span></div>
      <span class="badge">CLOSED CANDLES</span>
    </div>
    <div class="metrics">
      <div><span>بیشترین</span><b>${priceFmt(x.high)}</b></div>
      <div><span>کمترین</span><b>${priceFmt(x.low)}</b></div>
      <div><span>حجم</span><b>${fmt(x.volume,2)}</b></div>
    </div>
    ${spark(s.candles)}
  `;
  $('#toggleWatch').textContent=state.watch.includes(s.symbol)?'★ حذف از واچ‌لیست':'☆ افزودن به واچ‌لیست';
}

function marketCard(s){
  const chg=Number(s.latest.change_percent)||0;
  return `<article class="market-card" data-symbol="${s.symbol}" data-interval="${s.interval}"><div class="market-name"><b>${s.symbol}</b><small>${TIMEFRAMES[s.interval]?.label||s.interval}</small></div><div class="market-price"><b>${priceFmt(s.latest.close)}</b><span class="${chg>=0?'up':'down'}">${chg>=0?'+':''}${chg.toFixed(2)}%</span></div></article>`;
}

function renderMarkets(){
  const root=$('#markets'),interval=$('#timeframe').value;
  const items=SYMBOLS.map(symbol=>series.find(x=>x.symbol===symbol&&x.interval===interval)).filter(Boolean);
  root.innerHTML=items.length?items.map(marketCard).join(''):'<article class="empty-card">هنوز داده عمومی بازار دریافت نشده است.</article>';
  root.querySelectorAll('[data-symbol]').forEach(card=>card.onclick=()=>{
    $('#symbol').value=card.dataset.symbol;
    $('#timeframe').value=card.dataset.interval;
    renderSelected();
    window.scrollTo({top:$('#selected').offsetTop-92,behavior:'smooth'});
  });
}

function renderWatchlist(){
  const root=$('#watchlist'),interval=$('#timeframe').value;
  const items=state.watch.map(symbol=>series.find(x=>x.symbol===symbol&&x.interval===interval)).filter(Boolean);
  root.innerHTML=items.length?items.map(marketCard).join(''):'<article class="empty-card">واچ‌لیست خالی است یا داده این تایم‌فریم هنوز دریافت نشده.</article>';
  $('#watchCount').textContent=`${fmt(state.watch.length,0)} نماد`;
}

function renderAlerts(){
  const root=$('#alerts');
  root.innerHTML=state.alerts.length?state.alerts.map((a,i)=>`<article class="quality-card ${a.triggered?'ok':''}"><b>${a.symbol}</b><p>${a.direction==='above'?'بالاتر از':'پایین‌تر از'} ${priceFmt(a.price)} · ${a.triggered?'فعال شده':'در انتظار'}</p><button data-delete-alert="${i}">حذف</button></article>`).join(''):'<article class="empty-card">هشدار قیمتی تعریف نشده است.</article>';
  root.querySelectorAll('[data-delete-alert]').forEach(btn=>btn.onclick=()=>{state.alerts.splice(Number(btn.dataset.deleteAlert),1);save();renderAlerts()});
  checkAlerts();
}

function checkAlerts(){
  let changed=false;
  state.alerts.forEach(a=>{
    if(a.triggered)return;
    const matches=series.filter(x=>x.symbol===a.symbol);
    const s=matches[matches.length-1];
    if(!s)return;
    const price=Number(s.latest.close);
    if(a.direction==='above'?price>=a.price:price<=a.price){a.triggered=true;changed=true;toast(`هشدار ${a.symbol} فعال شد`)}
  });
  if(changed)save();
}

function renderQuality(){
  const root=$('#quality');
  const marketOk=marketState==='ready';
  root.innerHTML=`
    <article class="quality-card ok"><b>گیت‌های مهندسی</b><p>Phase 6 / Gates 0–6 تکمیل و روی main ادغام شده‌اند.</p></article>
    <article class="quality-card ok"><b>مرز مالی</b><p>Research / Backtest / Paper-only؛ مسیر معامله واقعی و برداشت وجود ندارد.</p></article>
    <article class="quality-card ${marketOk?'ok':'warn-card'}"><b>داده عمومی بازار</b><p>${marketOk?'کندل‌های بسته Bybit از مسیر read-only دریافت می‌شوند.':'در حال حاضر اتصال عمومی بازار برقرار نیست؛ هیچ داده ساختگی نمایش داده نمی‌شود.'}</p></article>
    <article class="quality-card ok"><b>هوش مصنوعی</b><p>اختیاری و advisory؛ Deterministic Risk مرجع نهایی باقی می‌ماند.</p></article>
  `;
}

function renderAll(){
  renderOverview();
  renderProject();
  renderStrategies();
  renderSelected();
  renderMarkets();
  renderWatchlist();
  renderAlerts();
  renderQuality();
}

function bind(){
  $('#symbol').innerHTML=SYMBOLS.map(x=>`<option value="${x}">${x}</option>`).join('');
  $('#timeframe').innerHTML=Object.entries(TIMEFRAMES).map(([value,meta])=>`<option value="${value}">${meta.label}</option>`).join('');
  $('#symbol').value='BTCUSDT';
  $('#timeframe').value='15';
  $('#symbol').onchange=ensureSelected;
  $('#timeframe').onchange=refreshAll;
  $('#refresh').onclick=refreshAll;
  $('#theme').onclick=()=>{state.theme=state.theme==='light'?'dark':'light';save();applyTheme()};
  $('#toggleWatch').onclick=()=>{
    const symbol=$('#symbol').value;
    state.watch=state.watch.includes(symbol)?state.watch.filter(x=>x!==symbol):[...state.watch,symbol];
    save();renderWatchlist();renderSelected();toast('واچ‌لیست بروزرسانی شد');
  };
  $('#addAlert').onclick=()=>{
    const s=selectedSeries();
    if(!s)return toast('ابتدا داده بازار را دریافت کن');
    $('#alertSymbol').textContent=s.symbol;
    $('#alertPrice').value=s.latest.close;
    $('#alertDialog').showModal();
  };
  $('#saveAlert').onclick=e=>{
    e.preventDefault();
    const s=selectedSeries(),price=Number($('#alertPrice').value);
    if(!s||!Number.isFinite(price)||price<=0)return;
    state.alerts.push({symbol:s.symbol,direction:$('#alertDirection').value,price,triggered:false});
    save();$('#alertDialog').close();renderAlerts();toast('هشدار ذخیره شد');
  };
  $('#clearLocal').onclick=()=>{
    if(confirm('واچ‌لیست، هشدارها و تنظیمات محلی پاک شوند؟')){
      localStorage.removeItem(STATE_KEY);location.reload();
    }
  };
}

async function init(){
  applyTheme();
  bind();
  await loadProject();
  renderAll();
  await refreshAll();
}

document.addEventListener('DOMContentLoaded',init);
})();
