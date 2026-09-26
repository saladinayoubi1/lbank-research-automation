"""Execute the real Electron startup code with deterministic host doubles."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('mode', ['late', 'exhausted', 'exit', 'quit', 'immediate'])
def test_startup_recovery(mode):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node required for Electron startup regression')
    harness = r'''
const vm = require('vm'), fs = require('fs'), assert = require('assert');
const source = fs.readFileSync(process.argv[1], 'utf8').split('const singleInstanceLock =')[0];
const mode = process.argv[2];
const states = [], windows = [], child = {stdout:{on(){}}, stderr:{on(){}}, on(){}, kill(){}};
let spawns=0, calls=0;
const context = {require(name) {
 if(name==='electron') return {app:{getPath:()=>'/tmp'},BrowserWindow:{}};
 if(name==='child_process') return {spawn(){spawns++; return child;}};
 if(name==='fs') return {mkdirSync(){}};
 return require(name);
}, process, setTimeout, console};
vm.createContext(context);
vm.runInContext(source,context);
vm.runInContext(`
freePort = async () => 23456;
productBindings = () => ({executable:'/engine',sourceSha:'a'.repeat(40)});
initStartupLog = () => {startupLogPath='/log'};
logStartup = () => {};
writeSupervisorState = (status,extra) => states.push({status,...extra});
showStartupFailure = () => windows.push('waiting');
waitForProduct = async (origin,timeout) => {
 calls++;
 if(mode==='immediate') return;
 if(calls===1) {const e=new Error('delayed'); e.code='NEXUS_GATEWAY_TIMEOUT'; throw e;}
 assert.strictEqual(origin,'http://127.0.0.1:23456');
 assert.strictEqual(timeout,12*60*1000);
 if(mode==='exhausted') throw new Error('deadline');
 if(mode==='exit') sidecarExit={code:1};
 if(mode==='quit') isQuitting=true;
};
`,Object.assign(context,{states,windows,mode,assert,calls:0}));
(async()=>{
 const first=vm.runInContext('startSidecar()',context);
 const second=vm.runInContext('startSidecar()',context);
 assert.strictEqual(first,second);
 if(['exhausted','exit','quit'].includes(mode)) {
   await assert.rejects(first);
   assert(!states.some(s=>s.status==='healthy'));
   if(mode==='exhausted') await assert.rejects(vm.runInContext('startSidecar()',context));
 } else {
   assert.strictEqual(await first,'http://127.0.0.1:23456');
   assert.strictEqual(states.at(-1).status,'healthy');
   assert.strictEqual(states.at(-1).source_sha,'a'.repeat(40));
 }
 assert.strictEqual(spawns,1);
 assert.strictEqual(windows.length,mode==='immediate'?0:1);
})().catch(e=>{console.error(e);process.exitCode=1});
'''
    result = subprocess.run([node, '-e', harness, str(ROOT / 'desktop/nexus-product/main.js'), mode], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
