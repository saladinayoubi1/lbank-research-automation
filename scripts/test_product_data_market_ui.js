'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const ui=path.resolve(__dirname,'../product_ui');
const js=fs.readFileSync(path.join(ui,'product.js'),'utf8');
const html=fs.readFileSync(path.join(ui,'index.html'),'utf8');
const css=fs.readFileSync(path.join(ui,'product-extra.css'),'utf8');
function isolate(start,stop){
  const i=js.indexOf(start);
  const j=js.indexOf(stop,i);
  assert.ok(i>=0&&j>i,'renderer boundary missing: '+start);
  return js.slice(i,j);
}
const fragment=isolate('function renderRegistry(){','function renderRisk(){');
const nodes={
  '#registrySummary':{innerHTML:''},
  '#registryTable':{innerHTML:''},
  '#marketProbeStatus':{innerHTML:'',textContent:'',className:''},
  '#marketProbeSubmit':{disabled:false,setAttribute(){},removeAttribute(){}},
};
const $=s=>nodes[s]??null;
const esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const metric=(k,v,d)=>'<metric>'+esc(k)+'='+esc(v)+' · '+esc(d)+'</metric>';
const state={registry:{registry_version:'1.2.0',authority:{primary:'Bybit'},mappings:[
  {canonical_symbol:'BTC/USDT',market_category:'spot',timeframe:'4h',finality:'closed_only',
    sources:[{exchange:'Bybit',role:'primary',status:'compatible'}]},
]},marketProbe:null};
let apiCalls=0;
const api=async()=>{apiCalls++;return {status:'unavailable',reason_code:'public_http_403_access_denied',
  http_status:403,source:'Bybit',symbol:'BTCUSDT',timeframe:'4h',checked_at_utc:new Date().toISOString()}};
const singleFlight=async(_k,_control,fn)=>fn();
const context={$,
  state,metric,esc,api,singleFlight,URLSearchParams,Date,
  document:{},console};
vm.createContext(context);
vm.runInContext(fragment,context,{timeout:1000});
context.renderRegistry();
context.renderMarketProbe();
assert.match(nodes['#registrySummary'].innerHTML,/NOT CHECKED/);
assert.match(nodes['#registryTable'].innerHTML,/سازگار از نظر قرارداد · اتصال نامشخص/);
assert.match(nodes['#marketProbeStatus'].textContent,/اتصال واقعی آزمایش نشده/);
assert.equal(apiCalls,0,'registry rendering cannot silently call public feed');

(async()=>{
  const form={elements:{namedItem:n=>({value:n==='symbol'?'BTCUSDT':'4h'})}};
  await context.runMarketProbe({preventDefault(){},currentTarget:form});
  assert.equal(apiCalls,1);
  assert.match(nodes['#marketProbeStatus'].innerHTML,/HTTP 403/);
  assert.doesNotMatch(nodes['#marketProbeStatus'].innerHTML,/قیمت پایان کندل تأییدشده/);
  assert.match(nodes['#registrySummary'].innerHTML,/unavailable/);
  state.marketProbe={
    status:'verified_closed_candles',reason_code:'source_probe_passed',
    source:'Bybit',symbol:'BTCUSDT',timeframe:'4h',
    checked_at_utc:new Date().toISOString(),
    last_closed_at_utc:new Date().toISOString(),
    last_close_price:'12345.67',lag_bars:0,
  };
  context.renderMarketProbe();
  assert.match(nodes['#marketProbeStatus'].innerHTML,/12345\.67/);
  assert.match(nodes['#marketProbeStatus'].className,/good/);
  state.marketProbe.checked_at_utc=new Date(Date.now()-6*60*1000).toISOString();
  context.renderMarketProbe();
  assert.match(nodes['#marketProbeStatus'].innerHTML,/نتیجه آزمایش قدیمی/);
  assert.doesNotMatch(nodes['#marketProbeStatus'].innerHTML,/12345\.67/);
  assert.match(nodes['#marketProbeStatus'].className,/bad/);
  assert.match(html,/id="marketProbeForm"/);
  assert.match(html,/id="marketProbeStatus"/);
  assert.match(html,/NO AUTOMATIC FALLBACK/);
  assert.match(css,/\.market-probe-evidence/);
  assert.doesNotMatch(fragment,/api\/product\/paper\/order/);
  console.log('PASS: Data Core registry/probe separation, explicit 403, expiry, and fail-closed UI');
})().catch(e=>{console.error(e);process.exitCode=1});
