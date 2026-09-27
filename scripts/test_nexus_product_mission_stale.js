'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'..','product_ui','product-mission.js'),'utf8');

function fixture(stale, ageSeconds=stale?226000:20){
  const el=new Map();
  for(const id of ['missionNow','missionOwnerActions','missionSystemEvidence','missionResources','missionTasks',
    'missionEvents','strategyMissionLeader','strategyMissionRows','missionSyncState','missionBadge',
    'missionAgentRuntime','view-overview','agentState','view-strategies','buildLabel']){
    el.set(id,{id,innerHTML:'',textContent:'',className:'',classList:{add(){},remove(){}}});
  }
  const data={
    source:'local_runtime',generated_at:'2026-09-25T00:00:00Z',stale,snapshot_age_seconds:ageSeconds,
    control_plane:{runtime_present:true,active_tasks:[{id:'OLD-PHASE4',title:'OLD TASK',priority:90}],
      blocked_or_triage:[{id:'OLD-BLOCKER',status:'BLOCKED'}],verified_progress_percent:71},
    owner_actions:[{id:'P4-L4-GUARD',title:'OLD L4 OWNER TASK',status:'OWNER_REQUIRED',authority:4}],
    tasks:[{id:'P4-L4-GUARD',title:'OLD L4 OWNER TASK',priority:9,status:'OWNER_REQUIRED',authority:4}],
    events:[],resources:[],workers:[],strategy_center:{runs:[]},
    local_supervisor:{status:'healthy'},build_evidence:{status:'verified',exact_source:true,source_sha:'a'.repeat(40)},
    ci_health:{status:'available',state:'DONE',summary:{DONE:7},workflows:{}}
  };
  const document={readyState:'complete',getElementById:id=>el.get(id)||null};
  const sandbox={document,window:{addEventListener(){}},console,URL,
    setInterval(){return 1},fetch:async()=>({ok:true,status:200,text:async()=>JSON.stringify(data)})};
  vm.runInNewContext(source,sandbox,{timeout:3000});
  return new Promise(resolve=>setImmediate(()=>resolve(el)));
}
(async()=>{
  const old=await fixture(true);
  assert.match(old.get('missionNow').innerHTML,/HISTORICAL SNAPSHOT · REVALIDATION REQUIRED/);
  assert.doesNotMatch(old.get('missionNow').innerHTML,/No owner action required|🔴|OLD-BLOCKER/);
  assert.match(old.get('missionOwnerActions').innerHTML,/HISTORICAL OWNER ACTIONS — NOT CURRENT/);
  assert.doesNotMatch(old.get('missionOwnerActions').innerHTML,/🔴|OLD L4 OWNER TASK/);
  assert.match(old.get('missionTasks').innerHTML,/HISTORICAL TASK SNAPSHOT/);
  assert.match(old.get('missionSystemEvidence').innerHTML,/HISTORICAL · NOT CURRENT/);
  assert.match(old.get('missionResources').innerHTML,/HISTORICAL RESOURCES/);
  assert.match(old.get('missionBadge').textContent,/HISTORICAL SNAPSHOT/);
  assert.match(old.get('missionSyncState').textContent,/STALE/);
  const staleAge=await fixture(false, 901);
  assert.match(staleAge.get('missionNow').innerHTML,/HISTORICAL SNAPSHOT/);
  assert.match(staleAge.get('missionOwnerActions').innerHTML,/HISTORICAL OWNER ACTIONS/);
  assert.doesNotMatch(staleAge.get('missionOwnerActions').innerHTML,/🔴/);
  assert.match(staleAge.get('missionSystemEvidence').innerHTML,/HISTORICAL · NOT CURRENT/);
  assert.match(staleAge.get('missionResources').innerHTML,/HISTORICAL RESOURCES/);
  assert.match(staleAge.get('missionTasks').innerHTML,/HISTORICAL TASK SNAPSHOT/);
  assert.equal(staleAge.get('missionBadge').textContent,'HISTORICAL SNAPSHOT');
  assert.match(staleAge.get('missionSyncState').textContent,/STALE/);
  const fresh=await fixture(false);
  assert.match(fresh.get('missionNow').innerHTML,/OLD-PHASE4/);
  assert.match(fresh.get('missionOwnerActions').innerHTML,/🔴 P4-L4-GUARD/);
  assert.doesNotMatch(fresh.get('missionTasks').innerHTML,/HISTORICAL TASK SNAPSHOT/);
  assert.equal(fresh.get('missionBadge').textContent,'CONTROL PLANE');
  console.log('MISSION_STALE_ACTION_GUARD_TESTS=PASS');
})().catch(error=>{console.error(error);process.exitCode=1});
