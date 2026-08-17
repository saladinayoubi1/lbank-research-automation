(()=>{
'use strict';
const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
const SYMBOLS=['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT'];
const TFS={'15':{label:'۱۵ دقیقه',ms:900000},'60':{label:'۱ ساعت',ms:3600000},'240':{label:'۴ ساعت',ms:14400000}};
const KEY='nexus-windows-delivery-v1';
let state=loadState(),series=[],marketState='neutral',marketMessage='Bybit public · read-only';
function loadState(){try{return Object.assign({theme:'dark',watch:['BTCUSDT'],alerts:[],sidebarCollapsed:false},JSON.parse(localStorage.getItem(KEY)||'{}'))}catch{return{theme:'dark',watch:['BTCUSDT'],alerts:[],sidebarCollapsed:false}}}
function save(){localStorage.setItem(KEY,JSON.stringify(state))}
function fmt(v,d=8){const n=Number(v);return Number.isFinite(n)?new Intl.NumberFormat('fa-IR',{maximumFractionDigits:d}).format(n):'—'}
function price(v){const n=Number(v);return Number.isFinite(n)?fmt(n,n>=1000?2:n>=1?4:8):'—'}
function toast(text){const el=$('#toast');el.textContent=text;el.classList.add('show');clearTimeout(toast.t);toast.t=setTimeout(()=>el.classList.remove('show'),2200)}
function applyTheme(){document.body.classList.toggle('light',state.theme==='light');$('#theme').textContent=state.theme==='light'?'☾':'☀'}
function applySidebar(){
  const collapsed=!!state.sidebarCollapsed;
  document.body.classList.toggle('sidebar-collapsed',collapsed);
  const btn=$('#sidebarToggle');
  if(!btn)return;
  btn.textContent=collapsed?'▶':'◀';
  btn.setAttribute('aria-expanded',String(!collapsed));
  btn.setAttribute('aria-label',collapsed?'باز کردن پنل کناری':'جمع کردن پنل کناری');
  btn.title=collapsed?'باز کردن پنل':'جمع کردن پنل';
}
function toggleSidebar(){state.sidebarCollapsed=!state.sidebarCollapsed;save();applySidebar()}
function setupControls(){
  $('#symbol').innerHTML=SYMBOLS.map(x=>`<option value="${x}">${x}</option>`).join('');
  $('#timeframe').innerHTML=Object.entries(TFS).map(([k,v])=>`<option value="${k}">${v.label}</option>`).join('');
  $('#symbol').value='BTCUSDT';$('#timeframe').value='15';
}
async function appInfo(){try{const x=await window.NexusNative.appInfo();$('#appVersion').textContent=x.version;$('#runtimeInfo').textContent=`Windows ${x.arch} · v${x.version}`;}catch{$('#runtimeInfo').textContent='Windows package'}}
function normalize(symbol,interval,text){
  const payload=typeof text==='string'?JSON.parse(text):text;
  if(!payload||payload.retCode!==0||!Array.isArray(payload.result?.list))throw Error('پاسخ بازار معتبر نیست');
  const step=TFS[interval]?.ms;if(!step)throw Error('تایم‌فریم نامعتبر');
  const now=Date.now();
  const candles=payload.result.list.slice().reverse().map(r=>({t:Number(r[0]),o:Number(r[1]),h:Number(r[2]),l:Number(r[3]),c:Number(r[4]),v:Number(r[5])})).filter(c=>Number.isFinite(c.t)&&Number.isFinite(c.c)&&c.t+step<=now);
  if(candles.length<2)throw Error('کندل بسته کافی نیست');
  const x=candles.at(-1),p=candles.at(-2),chg=p.c?((x.c-p.c)/p.c)*100:0;
  return{symbol,interval,candles,latest:{close:x.c,high:x.h,low:x.l,volume:x.v,change:chg,openTime:x.t}};
}
function upsert(s){const i=series.findIndex(x=>x.symbol===s.symbol&&x.interval===s.interval);if(i>=0)series[i]=s;else series.push(s)}
async function loadOne(symbol,interval){if(!window.NexusNative?.requestPublicMarket)throw Error('پل بازار Windows در دسترس نیست');const raw=await window.NexusNative.requestPublicMarket(symbol,interval);const s=normalize(symbol,interval,raw);upsert(s);return s}
async function refreshAll(){
  const interval=$('#timeframe').value,selected=$('#symbol').value;
  marketState='loading';marketMessage='در حال دریافت کندل‌های بسته Bybit';renderStatus();
  $('#selected').innerHTML='<div class="loading"><i></i><span>در حال دریافت داده عمومی بازار…</span></div>';
  const order=[selected,...SYMBOLS.filter(x=>x!==selected)];
  const results=await Promise.allSettled(order.map(x=>loadOne(x,interval)));
  const ok=results.filter(x=>x.status==='fulfilled').length;
  if(ok){marketState='ready';marketMessage=`${fmt(ok,0)} نماد · Bybit public`;}
  else{marketState='offline';marketMessage='اتصال Bybit برقرار نشد؛ VPN/اینترنت را بررسی کن';}
  renderAll();
}
async function ensureSelected(){const symbol=$('#symbol').value,interval=$('#timeframe').value;if(series.some(x=>x.symbol===symbol&&x.interval===interval)){renderSelected();return}$('#selected').innerHTML='<div class="loading"><i></i><span>در حال دریافت انتخاب…</span></div>';try{await loadOne(symbol,interval);marketState='ready';marketMessage='Bybit public · read-only';}catch{marketState='offline';marketMessage='داده انتخاب در دسترس نیست';}renderAll()}
function renderStatus(){
  const pill=$('#connectionPill'),title=pill.querySelector('b');pill.className='status-pill '+(marketState==='ready'?'ready':marketState==='offline'?'offline':'neutral');
  title.textContent=marketState==='ready'?'بازار متصل':marketState==='offline'?'بازار بدون اتصال':marketState==='loading'?'در حال اتصال':'بازار در انتظار اتصال';
  $('#marketStatus').textContent=title.textContent;$('#marketDetail').textContent=marketMessage;
}
function current(){return series.find(x=>x.symbol===$('#symbol').value&&x.interval===$('#timeframe').value)}
function spark(c){if(!c?.length)return'';const v=c.slice(-80).map(x=>x.c),min=Math.min(...v),max=Math.max(...v),r=max-min||1,pts=v.map((x,i)=>`${i/(v.length-1||1)*100},${76-(x-min)/r*68}`).join(' ');return`<svg class="spark" viewBox="0 0 100 80" preserveAspectRatio="none"><polyline fill="none" stroke="currentColor" stroke-width="1.6" vector-effect="non-scaling-stroke" points="${pts}"/></svg>`}
function renderSelected(){
  const root=$('#selected'),s=current();
  if(!s){root.innerHTML='<div class="empty">داده‌ای دریافت نشده است. پروژه آماده است؛ برای قیمت عمومی روی «بروزرسانی بازار» بزن.</div>';return}
  const x=s.latest,chg=Number(x.change)||0;
  root.innerHTML=`<div class="hero-head"><div><span class="eyebrow">${s.symbol} · ${TFS[s.interval].label}</span><h3>${price(x.close)}</h3><span class="hero-change ${chg>=0?'up':'down'}">${chg>=0?'+':''}${chg.toFixed(2)}%</span></div><span class="closed-badge">CLOSED CANDLES</span></div><div class="price-metrics"><div><span>بیشترین</span><b>${price(x.high)}</b></div><div><span>کمترین</span><b>${price(x.low)}</b></div><div><span>حجم</span><b>${fmt(x.volume,2)}</b></div><div><span>آخرین کندل</span><b>${new Date(x.openTime).toLocaleTimeString('fa-IR',{hour:'2-digit',minute:'2-digit'})}</b></div></div>${spark(s.candles)}`;
  $('#toggleWatch').textContent=state.watch.includes(s.symbol)?'★ حذف از واچ‌لیست':'☆ افزودن به واچ‌لیست';
}
function card(s){const c=Number(s.latest.change)||0;return`<article class="market-card" data-symbol="${s.symbol}"><span>${s.symbol}</span><small>${TFS[s.interval].label}</small><b>${price(s.latest.close)}</b><small class="chg ${c>=0?'up':'down'}">${c>=0?'+':''}${c.toFixed(2)}%</small></article>`}
function renderMarkets(){const interval=$('#timeframe').value,items=SYMBOLS.map(sym=>series.find(x=>x.symbol===sym&&x.interval===interval)).filter(Boolean);$('#markets').innerHTML=items.length?items.map(card).join(''):'<div class="empty">داده بازار عمومی هنوز دریافت نشده است.</div>';$$('#markets [data-symbol]').forEach(el=>el.onclick=()=>{$('#symbol').value=el.dataset.symbol;renderSelected()})}
function renderWatch(){const interval=$('#timeframe').value,items=state.watch.map(sym=>series.find(x=>x.symbol===sym&&x.interval===interval)).filter(Boolean);$('#watchCount').textContent=fmt(state.watch.length,0);$('#watchlist').innerHTML=items.length?items.map(s=>`<div class="watch-row"><div><span>${s.symbol}</span><small>${TFS[s.interval].label}</small></div><b>${price(s.latest.close)}</b></div>`).join(''):'<div class="empty">واچ‌لیست خالی است یا داده هنوز دریافت نشده.</div>'}
function checkAlerts(){let changed=false;state.alerts.forEach(a=>{if(a.triggered)return;const candidates=series.filter(x=>x.symbol===a.symbol);const s=candidates.at(-1);if(!s)return;const p=Number(s.latest.close);if(a.direction==='above'?p>=a.price:p<=a.price){a.triggered=true;changed=true;toast(`هشدار ${a.symbol} فعال شد`)}});if(changed)save()}
function renderAlerts(){checkAlerts();$('#alertList').innerHTML=state.alerts.length?state.alerts.map((a,i)=>`<article class="alert-card"><header><b>${a.symbol}</b><span class="${a.triggered?'up':'muted'}">${a.triggered?'فعال شده':'در انتظار'}</span></header><p>${a.direction==='above'?'بالاتر از':'پایین‌تر از'} ${price(a.price)}</p><button data-del="${i}">حذف</button></article>`).join(''):'<div class="empty">هشدار قیمتی تعریف نشده است.</div>';$$('[data-del]').forEach(b=>b.onclick=()=>{state.alerts.splice(+b.dataset.del,1);save();renderAlerts()})}
function renderAll(){renderStatus();renderSelected();renderMarkets();renderWatch();renderAlerts()}
function bind(){
  $('#sidebarToggle').onclick=toggleSidebar;
  $('#theme').onclick=()=>{state.theme=state.theme==='light'?'dark':'light';save();applyTheme()};
  $('#refresh').onclick=refreshAll;$('#symbol').onchange=ensureSelected;$('#timeframe').onchange=refreshAll;
  $('#toggleWatch').onclick=()=>{const s=current();if(!s)return toast('ابتدا داده بازار را دریافت کن');state.watch=state.watch.includes(s.symbol)?state.watch.filter(x=>x!==s.symbol):[...state.watch,s.symbol];save();renderSelected();renderWatch()};
  $('#addAlert').onclick=()=>{const s=current();if(!s)return toast('ابتدا داده بازار را دریافت کن');$('#alertSymbol').textContent=s.symbol;$('#alertPrice').value=s.latest.close;$('#alertDialog').showModal()};
  $('#saveAlert').onclick=e=>{e.preventDefault();const s=current(),p=Number($('#alertPrice').value);if(!s||!Number.isFinite(p)||p<=0)return;state.alerts.push({symbol:s.symbol,direction:$('#alertDirection').value,price:p,triggered:false});save();$('#alertDialog').close();renderAlerts();toast('هشدار ذخیره شد')};
  const links=$$('.sidebar nav a');links.forEach(a=>a.onclick=()=>{links.forEach(x=>x.classList.remove('active'));a.classList.add('active')});
  document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='b'){e.preventDefault();toggleSidebar()}});
}
async function init(){applyTheme();applySidebar();setupControls();bind();renderAll();await appInfo();refreshAll()}
window.addEventListener('DOMContentLoaded',init);
})();
