(()=>{
'use strict';
let snapshot=null,received=0,inflight=false,epoch=0,connection='offline',failures=0,retryTimer=null,lastFailure='',manualPending=false;
function schedule(delay){clearTimeout(retryTimer);retryTimer=setTimeout(refresh,delay);}
const $=id=>document.getElementById(id);
function failureMessage(error){
  const msg=String(error?.message||'');
  if(/(?:HTTP|status)\s*401/i.test(msg))return 'توکن Gateway پذیرفته نشد (HTTP 401). توکن لپ‌تاپ را دوباره وارد کنید.';
  if(/(?:HTTP|status)\s*400/i.test(msg))return 'آدرس Gateway مجاز نیست (HTTP 400). نشانی HTTPS را دقیق بررسی کنید.';
  if(/(?:HTTP|status)\s*403/i.test(msg))return 'درخواست توسط محدودیت امنیتی Gateway رد شد (HTTP 403).';
  if(/(?:HTTP|status)\s*404/i.test(msg))return 'مسیر حساب مشترک در سرور پیدا نشد (HTTP 404).';
  if(/SSL|TLS|certificat|trust anchor|handshake|hostname.*verif/i.test(msg))return 'اعتبار گواهی HTTPS تأیید نشد؛ هیچ‌وقت بررسی امنیتی را خاموش نکنید.';
  if(/UnknownHost|DNS|ENOTFOUND|resolve|Connection refused|ConnectException|failed to connect|timeout/i.test(msg))return 'ارتباط HTTPS برقرار نشد؛ Tailscale، نشانی و دسترسی به لپ‌تاپ را بررسی کنید.';
  if(/invalid shared paper snapshot/i.test(msg))return 'اطلاعات Paper سرور با قرارداد امن اپ سازگار نیست.';
  if(/bridge unavailable/i.test(msg))return 'اتصال داخلی برنامه آماده نیست؛ نسخه جدید اپ لازم است.';
  if(/reader busy/i.test(msg))return 'درگاه موقتاً مشغول است؛ دوباره تلاش کنید.';
  return 'خطای اتصال نامشخص؛ اتصال را تازه‌سازی کنید. اطلاعات حساب فرضی نمایش داده نمی‌شود.';
}
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
  $('sharedConnectionDetail').textContent=manualPending&&inflight?
    'درخواست تازه‌سازی ثبت شد و پس از پاسخ جاری خودکار اجرا می‌شود.':!snapshot&&lastFailure?lastFailure:snapshot?
    `آخرین دریافت ${Math.floor(elapsed)} ثانیه پیش · ${state==='connected'?'دموی داخلی، فقط مشاهده':'اطلاعات ذخیره‌شده است؛ قیمت و سود فعلی تأیید نشده'}`:
    'اتصال HTTPS و توکن لپ‌تاپ لازم است. حساب تمرینی گوشی جایگزین این سبد نیست.';
  $('sharedHomeSummary').textContent=snapshot?`${snapshot.account.equity.toFixed(2)} USDT · ${snapshot.positions.length} پوزیشن · ${state==='connected'?'متصل':'داده زنده تأیید نشده'}`:'اتصال به لپ‌تاپ تنظیم نشده یا در دسترس نیست.';
  $('refreshSharedPaper').textContent=manualPending?'تازه‌سازی در صف':inflight?'در حال دریافت…':'تازه‌سازی';
  if(redraw)window.NexusPaperTerminal?.render(snapshot?{...snapshot,stale:stale||state!=='connected'}:null);
}
async function refresh(){
  if(inflight||document.hidden)return;
  clearTimeout(retryTimer);
  if(!window.NexusProductClient){connection='offline';lastFailure='اتصال داخلی اپ آماده نیست؛ نسخه جدید اپ را بررسی کنید.';paint(false);schedule(5000);return;}
  // navigator.onLine is unreliable on Android VPNs; the HTTPS request is authoritative.
  inflight=true;const requestEpoch=epoch;if(!snapshot)connection='loading';paint(false);
  try{
    const payload=await window.NexusProductClient.call('GET','/api/product/paper');
    if(requestEpoch!==epoch)return;
    if(payload.live_trading_authority!==false||payload.paper_only!==true||!valid(payload.shared_portfolio))throw Error('invalid shared paper snapshot');
    snapshot=payload.shared_portfolio;received=Date.now();connection='connected';failures=0;lastFailure='';
  }catch(e){if(requestEpoch===epoch){connection='offline';lastFailure=failureMessage(e);failures++;}}
  finally{
    inflight=false;
    const followUp=manualPending;
    manualPending=false;
    paint();
    if(requestEpoch!==epoch||followUp)refresh();
    else schedule(failures?Math.min(60000,5000*2**Math.min(failures-1,4)):30000);
  }
}
function manualRefresh(){
  // Keep only one follow-up GET even after multiple taps. Never race two native requests.
  if(inflight){manualPending=true;paint(false);return;}
  refresh();
}
function configure(){
  if(typeof window.NexusNative?.configureGateway==='function')window.NexusNative.configureGateway();
  else {$('sharedConnectionDetail').textContent='برای تنظیم اتصال، نسخه جدید APK را نصب کنید.';}
}
function configured(){
  epoch++;failures=0;manualPending=false;snapshot=null;received=0;connection='offline';lastFailure='';
  const modal=$('terminalDetails');if(modal?.open)modal.close();
  $('terminalSearch')?.blur();paint();refresh();
}
window.addEventListener('nexus-product-client-ready',refresh);
window.addEventListener('nexus-gateway-configured',configured);
window.addEventListener('focus',refresh);
window.addEventListener('online',()=>{failures=0;refresh();});
window.addEventListener('offline',()=>{epoch++;manualPending=false;connection='offline';lastFailure='';paint(false);schedule(5000);});
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
$('configureLaptop').onclick=configure;$('refreshSharedPaper').onclick=manualRefresh;
setInterval(()=>{if(!document.hidden)paint(false);},1000);
paint();refresh();
})();
