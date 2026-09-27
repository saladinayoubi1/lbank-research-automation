'use strict';
/* Regression tests for connected, stale, and independent local phone Paper views.
 * Runs without Android, browser networking, credentials or mutable owner data. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const asset=path.resolve(__dirname,'../android/lbank-mobile/app/src/main/assets');
const read=name=>fs.readFileSync(path.join(asset,name),'utf8');
const source=read('mobile-shared-terminal.js');
const html=read('index.html');
const style=read('mobile-shared-terminal.css');
const redraw=read('mobile-redesign.js');
const core=read('mobile-core.js');

function renderer(){
  const root={
    innerHTML:'',
    querySelector(s){
      if(s==='dialog[open]')return null;
      return {};
    },
    querySelectorAll(){return []}
  };
  const document={getElementById:s=>s==='sharedTerminal'?root:null,activeElement:{},};
  const window={};
  vm.runInNewContext(source,{document,window},{timeout:1500});
  assert.equal(typeof window.NexusPaperTerminal.render,'function');
  return {root,render:window.NexusPaperTerminal.render};
}
const fixture={
  available:true,stale:false,read_only:true,live_trading_authority:false,
  status:'running_waiting_for_closed_bar',valuation:'closed_4h_mark',
  checked_at:'2026-09-27T20:29:00Z',last_execution_utc:'2026-09-27T16:00:00Z',
  account:{initial_balance:500,equity:498.5180817766671,balance:498.5180817766671,
    net_pnl:-1.4819182233329,unrealized_pnl:0,realized_gross:-0.9685122467744,
    fees:0.50724803894,funding:-0.006157937618,free_margin:498.5180817766671},
  positions:[],
  history:[
    {id:'h1',symbol:'BTCUSDT',strategy:'macd12_26_9',net_pnl:-0.7,time:'2026-09-27T16:00:00Z'},
    {id:'h2',symbol:'BTCUSDT',strategy:'momentum20_ema100',net_pnl:-0.5,time:'2026-09-27T16:00:00Z'},
    {id:'h3',symbol:'BTCUSDT',strategy:'momentum20_ema100',net_pnl:-0.25,time:'2026-09-27T04:00:00Z'}],
  orders:[],cashflows:[],strategies:[]
};
{
  const {root,render}=renderer();
  render(fixture);
  assert.match(root.innerHTML,/class="terminal-account-primary"/);
  assert.match(root.innerHTML,/498\.52 USDT/);
  assert.match(root.innerHTML,/500\.00 USDT/);
  assert.match(root.innerHTML,/-0\.30%/);
  assert.match(root.innerHTML,/معاملات بسته‌شده در تاریخچه/);
  assert.doesNotMatch(root.innerHTML,/1000\.00 USDT/);
  assert.match(root.innerHTML,/حساب لپ‌تاپ · فقط مشاهده/);
}
{
  const {root,render}=renderer();
  render({...fixture,stale:true});
  assert.match(root.innerHTML,/داده ذخیره‌شده · اعتبار فعلی تأیید نشده/);
  assert.match(root.innerHTML,/badge bad/);
}
{
  const {root,render}=renderer();
  render({...fixture,history:[]});
  assert.match(root.innerHTML,/هنوز پوزیشنی باز نشده است/);
  assert.doesNotMatch(root.innerHTML,/معاملات بسته‌شده در تاریخچه/);
}
{
  const {root,render}=renderer();
  render(null);
  assert.match(root.innerHTML,/دادهٔ حساب مشترک در دسترس نیست/);
  assert.doesNotMatch(root.innerHTML,/1000\.00 USDT|500\.00 USDT/);
}
{
  const {root,render}=renderer();
  render({...fixture,positions:[{id:'p1',strategy:'momentum20_ema100',symbol:'BTCUSDT',
    side:'long',quantity:0.001,entry_price:84300,mark_price:84400,unrealized_pnl:0.1,
    net_pnl_to_date:0.02,opened_at:fixture.last_execution_utc,mark_time:fixture.last_execution_utc,
    stop_loss:null,take_profit:null}]});
  assert.match(root.innerHTML,/پوزیشن باز/);
  assert.doesNotMatch(root.innerHTML,/فعلاً پوزیشن بازی وجود ندارد/);
  assert.match(root.innerHTML,/استاپ و تارگت ثابت تنظیم نشده‌اند/);
}
assert.ok(html.indexOf('id="sharedTerminal"')<html.indexOf('id="mobileLocalSandbox"'));
assert.match(html,/<details class="mobile-local-sandbox" id="mobileLocalSandbox">/);
assert.match(html,/<details class="home-local-sandbox" id="homeLocalSandbox">/);
assert.match(html,/LOCAL PHONE SANDBOX · NOT LAPTOP PAPER/);
const paperStart=html.indexOf('<details class="mobile-local-sandbox"');
const paperEnd=html.indexOf('<section id="screen-mission"');
const localPart=html.slice(paperStart,paperEnd);
assert.ok(localPart.includes('id="executePaper"')&&localPart.includes('id="positions"'));
assert.equal((localPart.match(/<details\b/g)||[]).length,
  (localPart.match(/<\/details>/g)||[]).length,
  'Local sandbox must close after its nested ticket and risk panels');
const localTag=html.match(/<details class="mobile-local-sandbox"[^>]*>/)[0];
assert.doesNotMatch(localTag,/\bopen(?:\s|=|>)/);
assert.match(style,/\.terminal-primary-equity/);
assert.match(style,/unicode-bidi:isolate/);
assert.match(redraw,/LOCAL MANUAL/);
assert.match(core,/openingCash:1000,cash:1000/);
console.log('PASS: 6 connected/stale/flat/open/unavailable mobile Paper cases + sandbox/RTL source guards');
