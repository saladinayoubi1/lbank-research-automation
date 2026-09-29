/* DOM-free contract tests for the shipped Research Operations renderer. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const fields = new Map();
function field(id) {
  if (!fields.has(id)) {
    fields.set(id, {
      innerHTML:'', textContent:'', value:'', setAttribute(){},
      addEventListener(){}, onclick:null
    });
  }
  return fields.get(id);
}
const sandbox = {
  window:{},
  document:{
    getElementById:field,
    querySelectorAll:()=>[]
  },
  Date, Number, Array, String, Object, RegExp
};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../product_ui/research-operations.js'),'utf8'),sandbox);
const ops = sandbox.window.NexusResearchOps;
assert.equal(typeof ops.render,'function');
assert.equal(typeof ops.renderResearch,'function');
const sha = 'a'.repeat(64);
const done = {
  id:'P7-RESEARCH-COMPOSITE-001',title:'Reviewed closed candle research',
  status:'DONE',result_evidence:{
    source_sha:'b'.repeat(40),archive_sha256:sha,config_fingerprint:'c'.repeat(64),
    mechanism:'structural_pullback',receipt_digest:sha,ledger_digest:'d'.repeat(64),live_enabled:false,validation:[{symbol:'BTCUSDT',timeframe:'15m',profile:'conservative',closed_round_trips:7,net_return_pct:-1.5,max_drawdown_pct:2.25,win_rate_pct:42.86,profit_factor:0.72}]
  },
  verification_evidence:{independent_qa_complete:true,producer_receipt_digest:sha,qa_digest:'e'.repeat(64),live_enabled:false}
};
const running = {
  id:'P7-RESEARCH-COMPOSITE-002',
  title:'<img src=x onerror="not_safe">',
  status:'RUNNING',assigned_worker:'research-agent',lease_id:'lease-123'
};
function snapshot(overrides) {
  return Object.assign({
    contract_version:'nexus.product-mission-control.v1',
    paper_only:true,live_trading_authority:false,
    source:'definition_only',stale:false,snapshot_age_seconds:null,
    control_plane:{runtime_present:false},
    tasks:[done,running],workers:[{
      id:'research-agent',state:'UNKNOWN',active_tasks:[],resources:['github-cloud']
    }],
    events:[],owner_actions:[]
  },overrides || {});
}
ops.render(snapshot());
assert.match(field('agentState').innerHTML,/فقط تعریف مأموریت/);
assert.match(field('agentState').innerHTML,/اطلاعات جاری تأیید نشده/);
assert.match(field('opsQueue').innerHTML,/&lt;img src=x onerror=&quot;not_safe&quot;&gt;/);
assert.doesNotMatch(field('opsQueue').innerHTML,/<img src=x/);
assert.match(field('researchAgentOverview').innerHTML,/گیت دمو/);
assert.match(field('researchAgentOverview').innerHTML,/نتایج عددی ثبت‌شده/);
assert.match(field('researchAgentOverview').innerHTML,/BTCUSDT/);
assert.match(field('researchAgentOverview').innerHTML,/OOS دست‌نخورده/);
assert.match(field('researchAgentOverview').innerHTML,/قفل/);
assert.match(field('opsInspector').innerHTML,/Producer receipt/i);
ops.render(snapshot({source:'local_runtime',snapshot_age_seconds:6,
  control_plane:{runtime_present:true}}));
assert.doesNotMatch(field('agentState').innerHTML,/اطلاعات جاری تأیید نشده/);
assert.match(field('agentState').innerHTML,/وضعیت محلی معتبر/);
assert.match(field('agentState').innerHTML,/LIVE LOCKED/);
assert.match(field('opsQueue').innerHTML,/research-agent/);
// Inspect the completed task rather than assuming the active task has QA proof.
field('agentState').onclick({target:{closest:(selector)=>
  selector === '[data-ops-task]' ? {getAttribute:()=>done.id} : null}});
assert.match(field('opsInspector').innerHTML,/تطبیق receipt/);
// A matching QA digest is compulsory; task DONE alone must not be promoted.
const mismatched = JSON.parse(JSON.stringify(done));
mismatched.verification_evidence.producer_receipt_digest = 'f'.repeat(64);
ops.render(snapshot({tasks:[mismatched],source:'local_runtime',
  snapshot_age_seconds:6,control_plane:{runtime_present:true}}));
assert.match(field('opsInspector').innerHTML,/مدرک QA مستقل هنوز تأیید نشده/);
assert.doesNotMatch(field('opsInspector').innerHTML,/تطبیق receipt/);
// Historical or old data must never be presented as real-time execution.
ops.render(snapshot({source:'local_runtime',snapshot_age_seconds:901,
  stale:true,control_plane:{runtime_present:true}}));
assert.match(field('agentState').innerHTML,/Snapshot قدیمی/);
assert.match(field('agentState').innerHTML,/اطلاعات جاری تأیید نشده/);
ops.render(null);
assert.match(field('agentState').innerHTML,/snapshot معتبر ندارد/);
console.log('Research Operations UI: fresh/stale, escaped data, QA receipt and read-only gates PASS');
