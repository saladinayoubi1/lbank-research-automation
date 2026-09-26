(()=>{
'use strict';
let snapshot=null,received=0,inflight=false,epoch=0,connection='offline',failures=0,retryTimer=null;
function schedule(delay){clearTimeout(retryTimer);retryTimer=setTimeout(refresh,delay);}
const $=id=>document.getElementById(id);
function valid(s){
  return s?.available===true && s.schema==='nexus.shared-paper-terminal.v1' &&
    s.mode==='internal_paper' && s.read_only===true && s.live_trading_authority===false &&
    s.account && Number.isFinite(s.account.equity) &&
    ['positions','history','orders','cashflows','strategies'].every(k=>Array.isArray(s[k]));
}
function paint(redraw=true){
  const elapsed=Math.max(0,(Date.now()-received)/1000);
  const age=snapshot?Number(snapshot.age_seconds)+elapsed:Infinity;
  const stale=!Number.isFinite(age)||age>180||snapshot?.stale===true;
  const state=connection==='connected'&&stale?'stale':connection;
  $('sharedConnection').dataset.state=state;
  $('sharedConnectionTitle').textContent=({connected:'حساب مشترک لپ‌تاپ · متصل',stale:'حساب مشترک لپ‌تاپ · داده قدیمی',offline:'حساب مشترک لپ‌تاپ · ارتباط قطع است',loading:'حساب مشترک لپ‌تاپ · در حال دریافت'})[state];
  $('sharedConnectionDetail').textContent=snapshot?
    `آخرین دریافت ${Math.floor(elapsed)} ثانیه پیش · ${state==='connected'?'دموی داخلی، فقط مشاهده':'اطلاعات ذخیره‌شده است؛ قیمت و سود فعلی تأیید نشده'}`:
    'اتصال HTTPS و توکن لپ‌تاپ لازم است. حساب تمرینی گوشی جایگزین این سبد نیست.';
  $('sharedHomeSummary').textContent=snapshot?`${snapshot.account.equity.toFixed(2)} USDT · ${snapshot.positions.length} پوزیشن · ${state==='connected'?'متصل':'داده زنده تأیید نشده'}`:'اتصال به لپ‌تاپ تنظیم نشده یا در دسترس نیست.';
  if(redraw)window.NexusPaperTerminal?.render(snapshot?{...snapshot,stale:stale||state!=='connected'}:null);
}
async function refresh(){
  clearTimeout(retryTimer);
  if(inflight||document.hidden||!window.NexusProductClient)return;
  if(window.navigator?.onLine===false){connection='offline';paint(false);schedule(60000);return;}
  inflight=true;const requestEpoch=epoch;if(!snapshot)connection='loading';paint(false);
  try{
    const payload=await window.NexusProductClient.call('GET','/api/product/paper');
    if(requestEpoch!==epoch)return;
    if(payload.live_trading_authority!==false||payload.paper_only!==true||!valid(payload.shared_portfolio))throw Error('invalid shared paper snapshot');
    snapshot=payload.shared_portfolio;received=Date.now();connection='connected';failures=0;
  }catch(e){if(requestEpoch===epoch){connection='offline';failures++;}}
  finally{inflight=false;paint();if(requestEpoch!==epoch)refresh();else schedule(failures?Math.min(60000,5000*2**Math.min(failures-1,4)):30000);}
}
function configure(){
  if(typeof window.NexusNative?.configureGateway==='function')window.NexusNative.configureGateway();
  else {$('sharedConnectionDetail').textContent='برای تنظیم اتصال، نسخه جدید APK را نصب کنید.';}
}
function configured(){
  epoch++;failures=0;snapshot=null;received=0;connection='offline';
  const modal=$('terminalDetails');if(modal?.open)modal.close();
  $('terminalSearch')?.blur();paint();refresh();
}
window.addEventListener('nexus-product-client-ready',refresh);
window.addEventListener('nexus-gateway-configured',configured);
window.addEventListener('focus',refresh);
window.addEventListener('online',()=>{failures=0;refresh();});
window.addEventListener('offline',()=>{epoch++;connection='offline';paint(false);});
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
$('configureLaptop').onclick=configure;$('refreshSharedPaper').onclick=refresh;
setInterval(()=>{if(!document.hidden)paint(false);},1000);
paint();refresh();
})();
