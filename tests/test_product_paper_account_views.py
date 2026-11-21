from pathlib import Path
import shutil
import subprocess
from unittest import SkipTest

ROOT = Path(__file__).resolve().parents[1]


def test_explicit_paper_account_views_preserve_sources_and_financial_truth():
    node = shutil.which('node')
    if not node:
        raise SkipTest('Node is unavailable')
    source = (ROOT / 'product_ui/product.js').read_text(encoding='utf-8')
    helpers = source[source.index('function activePaperTerminalSnapshot'):source.index('function renderMatrix')]
    terminal = (ROOT / 'product_ui/product-terminal.js').read_text(encoding='utf-8')
    program = r"""
const assert=require('node:assert/strict');
const elements=new Map();
function element(id){
  if(!elements.has(id))elements.set(id,{id,innerHTML:'',textContent:'',className:'',value:'',title:'',dataset:{},querySelector(selector){return selector==='dialog[open]'?null:element(id+selector)},querySelectorAll(){return[]}});
  return elements.get(id);
}
const document={getElementById:id=>element('#'+id),activeElement:null};
const $=id=>element(id),window={},metric=()=>'',esc=value=>String(value??'—');
const state={paper:null,events:null,sharedPaper:null,paperAccountChoice:null};
""" + helpers + '\n' + terminal + r"""
function deepFreeze(value){if(value&&typeof value==='object'){Object.freeze(value);Object.values(value).forEach(deepFreeze)}return value;}
const shared=deepFreeze({available:true,read_only:true,live_trading_authority:false,status:'waiting_for_closed_bar',projection:'nexus.shared-paper-live-display.v1',market_live:true,quote_status:'fresh',paper_state_stale:false,checked_at:'2026-11-21T14:00:00Z',last_execution_utc:'2026-11-21T12:00:00Z',account:{equity:777,balance:777,net_pnl:277,unrealized_pnl:0,realized_gross:277,fees:0,funding:0,free_margin:777},positions:[],history:[],orders:[],cashflows:[],strategies:[]});
const originalShared=JSON.stringify(shared);
// Synthetic complete 20-event journal; no owner data or new financial events are written.
const rows=[
 ['demo_account_opened',{opening_cash:'500',currency:'USDT'}],
 ['session_boundary_recorded',{boundary:'open'}],
 ['equity_snapshot_recorded',{cash:'500',equity:'500',unrealized_pnl:'0'}],
 ['signal_recorded',{}],['order_intent_recorded',{order_type:'paper_open'}],['risk_decision_recorded',{}],
 ['simulated_fill_recorded',{symbol:'XRPUSDT',side:'long',quantity:'1',price:'10'}],
 ['position_opened',{symbol:'XRPUSDT',side:'long',quantity:'1',entry_price:'10'}],
 ['fee_recorded',{amount:'0.02',currency:'USDT'}],
 ['slippage_recorded',{amount:'0.01',currency:'USDT'}],
 ['stop_registered',{}],['equity_snapshot_recorded',{cash:'499.97',equity:'499.97',unrealized_pnl:'0'}],
 ['order_intent_recorded',{order_type:'paper_close'}],['risk_decision_recorded',{}],
 ['simulated_fill_recorded',{symbol:'XRPUSDT',side:'long',quantity:'1',price:'9.5'}],
 ['position_closed',{symbol:'XRPUSDT',exit_price:'9.5',realized_pnl:'-0.5'}],
 ['fee_recorded',{amount:'0.03',currency:'USDT'}],
 ['slippage_recorded',{amount:'0.01',currency:'USDT'}],
 ['session_boundary_recorded',{boundary:'open'}],
 ['equity_snapshot_recorded',{cash:'499.43',equity:'499.43',unrealized_pnl:'0'}],
];
const events=rows.map(([event_type,payload],i)=>({sequence:i+1,event_type,payload,aggregate_id:'nexus-demo-paper',event_id:'fixture-'+i,event_digest:'fixture-digest-'+i,correlation_id:i<12?'open':'close',occurred_at:'2020-01-01T00:00:00Z',provenance:{strategy_version:'fixture-strategy',kind:'automatic',source_id:'fixture-source',timeframe:'minute15'}}));
const paper=deepFreeze({active:true,paper_only:true,live_trading_authority:false,event_count:20,client_received_at:'2026-11-21T14:34:00Z',head_event_digest:events.at(-1).event_digest,account:{aggregate_id:'nexus-demo-paper',cash:'499.43',equity:'499.43',realized_pnl:'-0.5',unrealized_pnl:'0',session_open:true,positions:[],stops:[],targets:[]}});
const envelope=deepFreeze({total:20,events});
Object.assign(state,{paper,events:envelope,sharedPaper:shared});
assert.strictEqual(selectedPaperAccountView(paper,envelope,shared).snapshot,shared);
renderPaper();
assert.equal($('#paperAccountView').value,'shared');
assert.match($('#sharedTerminal').innerHTML,/777\.00 USDT/);
selectPaperAccountView('journal');
assert.equal($('#paperAccountView').value,'journal');
assert.match($('#paperAccountLabel').textContent,/حساب Paper دستگاه/);
assert.match($('#paperAccountExplanation').textContent,/سبد خودکار بازیابی نشده/);
assert.match($('#sharedTerminal').innerHTML,/499\.43 USDT/);
assert.match($('#sharedTerminal').innerHTML,/خروجی رویدادهای دفتر حساب \(CSV\)/);
assert.match($('#sharedTerminal').innerHTML,/۱۰۰۰ رویداد آخر/);
assert.doesNotMatch($('#sharedTerminal').innerHTML,/خروجی CSV کامل/);
assert.doesNotMatch($('#sharedTerminal').innerHTML,/777\.00 USDT|MARK زنده|MID زنده/);
assert.match($('#sharedTerminal').innerHTML,/آخرین رویداد مالی ثبت‌شده/);
assert.match($('#sharedTerminal').innerHTML,/زمان خواندن حساب از backend/);
assert.match($('#sharedPaperFreshness').textContent,/وضعیت موتور تأییدنشده/);
// Search focus must not prevent an explicit account switch or carry filters across accounts.
element('#sharedTerminal#terminalSearch').onchange({target:{value:'old-account-filter'}});
document.activeElement=element('#sharedTerminal#terminalSearch');
selectPaperAccountView('shared');
assert.match($('#sharedTerminal').innerHTML,/777\.00 USDT/);
assert.doesNotMatch($('#sharedTerminal').innerHTML,/old-account-filter/);
assert.equal(JSON.stringify(shared),originalShared);
document.activeElement=null;
// An unavailable Shared view defaults to the clearly labelled, separate journal view.
Object.assign(state,{sharedPaper:{available:false,reason:'snapshot_invalid'},paperAccountChoice:null});
renderPaper();
assert.equal($('#paperAccountView').value,'journal');
assert.match($('#paperAccountExplanation').textContent,/سبد خودکار در دسترس نیست/);
assert.match($('#sharedTerminal').innerHTML,/جدا از سبد خودکار/);
selectPaperAccountView('shared');
assert.match($('#sharedTerminal').innerHTML,/دادهٔ حساب مشترک در دسترس نیست/);
assert.doesNotMatch($('#sharedTerminal').innerHTML,/499\.43 USDT|500\.00 USDT/);
const journal=selectedPaperAccountView(paper,envelope,null,'journal').snapshot;
assert.equal(journal.account.balance,'499.43');
assert.ok(Math.abs(journal.account.net_pnl-(-0.57))<1e-9);
assert.equal(journal.orders.length,2);assert.equal(journal.history.length,1);
assert.equal(journal.orders[0].side,'buy');assert.equal(journal.orders[1].side,'sell');
assert.ok(journal.cashflows.every(row=>Number(row.amount)<0),'Fees are debits, never green cash inflows');
assert.equal(journal.history[0].gross_pnl,'-0.5');
assert.equal(journal.history[0].net_pnl,null,'Do not call an exit-fee-only figure round-trip net PnL');
assert.equal(journal.worker_status,'unverified');assert.equal(journal.stale,null);
assert.equal(journal.status,'journal_only');assert.equal(journal.market_live,false);
assert.equal(journal.book_read_at,paper.client_received_at);
assert.equal(journal.last_financial_event_at,'2020-01-01T00:00:00Z');
assert.equal(journal.last_execution_utc,null,'A financial event is not a closed-candle worker receipt');
// No opening event or missing prefix means totals cannot be invented from a partial window.
const partial=selectedPaperAccountView({...paper,event_count:120},{total:120,events:events.slice(-6)},null,'journal').snapshot;
assert.equal(partial.event_window_complete,false);
assert.equal(partial.account.net_pnl,null);assert.equal(partial.account.fees,null);
assert.equal(partial.account.balance,paper.account.cash);
// A recent session event must not make the last financial event look newer.
const trailing=[...events,{sequence:21,event_type:'session_boundary_recorded',aggregate_id:'nexus-demo-paper',occurred_at:'2026-11-21T14:00:00Z',payload:{boundary:'open'}}];
const quiet=selectedPaperAccountView({...paper,event_count:21},{total:21,events:trailing},null,'journal').snapshot;
assert.equal(quiet.last_financial_event_at,'2020-01-01T00:00:00Z');
const initial={...paper,event_count:2,head_event_digest:events[1].event_digest,account:{...paper.account,cash:'500',equity:'500'}};
const empty=selectedPaperAccountView(initial,{total:2,events:events.slice(0,2)},null,'journal').snapshot;
assert.equal(empty.account.net_pnl,0);assert.equal(empty.positions.length,0);
assert.equal(empty.worker_status,'unverified');assert.equal(empty.status,'journal_only');
// Position direction and order direction differ on close/reduce; missing intent stays unknown.
for(const [order_type,positionSide,want] of [['paper_open','long','buy'],['paper_open','short','sell'],['paper_reverse','long','buy'],['paper_reverse','short','sell'],['paper_close','long','sell'],['paper_close','short','buy'],['paper_reduce','long','sell'],['paper_reduce','short','buy'],[null,'long',null]]){
  const ledger=[];
  if(order_type)ledger.push({event_type:'order_intent_recorded',correlation_id:'direction',aggregate_id:'nexus-demo-paper',payload:{order_type}});
  ledger.push({event_type:'simulated_fill_recorded',correlation_id:'direction',aggregate_id:'nexus-demo-paper',payload:{symbol:'BTCUSDT',side:positionSide,quantity:'1',price:'100'}});
  const projected=activePaperTerminalSnapshot(paper,{total:100,events:ledger}).orders[0];
  assert.equal(projected.side,want);assert.equal(projected.position_side,positionSide);
}
// Correlation-wide costs cannot be repeated on each fill slice.
const sliced=[...events.slice(0,7),{...events[6],event_id:'second-fill-slice'},...events.slice(7)].map((e,i)=>({...e,sequence:i+1}));
const multi=selectedPaperAccountView({...paper,event_count:21},{total:21,events:sliced},null,'journal').snapshot;
assert.equal(multi.event_window_complete,true);assert.equal(multi.orders.length,3);
for(const row of multi.orders.slice(0,2)){assert.equal(row.fee,null);assert.equal(row.slippage_cost,null);}
assert.equal(multi.account.fees,journal.account.fees,'Complete-journal totals are counted once');
// A malformed response containing another account must not merge its history or costs.
const foreign=events.slice(-6).map((e,i)=>({...e,aggregate_id:'foreign-account',event_id:'foreign-'+i,payload:{...e.payload,symbol:'FOREIGNUSDT'}}));
const mixed=selectedPaperAccountView(paper,{total:26,events:[...events,...foreign]},null,'journal').snapshot;
assert.equal(mixed.account.balance,paper.account.cash);assert.equal(mixed.event_window_complete,false);
assert.equal(mixed.history.length,journal.history.length);assert.equal(mixed.orders.length,journal.orders.length);
assert.ok([...mixed.history,...mixed.orders,...mixed.cashflows].every(row=>row.symbol!=='FOREIGNUSDT'));
assert.equal(mixed.account.fees,null);assert.equal(mixed.account.net_pnl,null);
const beforeChoice=state.paperAccountChoice;selectPaperAccountView('unknown-account');assert.equal(state.paperAccountChoice,beforeChoice);
assert.equal(JSON.stringify(shared),originalShared);
console.log('PAPER_ACCOUNT_VIEWS=PASS');
"""
    result = subprocess.run([node, '-'], input=program, cwd=ROOT, text=True,
                            capture_output=True, check=False, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PAPER_ACCOUNT_VIEWS=PASS' in result.stdout
