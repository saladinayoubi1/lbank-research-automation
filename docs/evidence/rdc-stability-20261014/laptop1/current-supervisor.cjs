const fs=require('fs'),path=require('path'),cp=require('child_process');
const root=path.join(process.env.LOCALAPPDATA,'NEXUS','desktop-commander-remote');
const entry=path.join(process.env.LOCALAPPDATA,'npm-cache','_npx','4b4c857f6efdfb61','node_modules','@wonderwhy-er','desktop-commander','dist','index.js');
const state=path.join(process.env.USERPROFILE,'.desktop-commander-device','device.json');
const log=path.join(root,'remote.log'), lock=path.join(root,'supervisor.json');
const stamp=s=>fs.appendFileSync(log,new Date().toISOString()+' '+s+'\n');
const alive=pid=>{try{process.kill(pid,0);return true}catch{return false}};
try{if(fs.existsSync(lock)){const o=JSON.parse(fs.readFileSync(lock,'utf8'));if(o.pid&&alive(o.pid))process.exit(0);fs.rmSync(lock,{force:true});}}catch{}
if(!fs.existsSync(entry)){stamp('runtime entry missing');process.exit(20);}
let cfg;try{cfg=JSON.parse(fs.readFileSync(state,'utf8'));}catch{stamp('state missing/invalid; auth not started');process.exit(21);}
if(!cfg?.session?.refresh_token){stamp('persisted session missing; auth not started');process.exit(22);}
if(process.argv.includes('--check')){console.log('REMOTE_AUTOSTART_CHECK=PASS');process.exit(0);}
fs.writeFileSync(lock,JSON.stringify({pid:process.pid,started:new Date().toISOString()}));
process.on('exit',()=>{try{fs.rmSync(lock,{force:true})}catch{}});
const out=fs.openSync(log,'a');
const child=cp.spawn(process.execPath,[entry,'remote'],{stdio:['ignore',out,out],windowsHide:true,env:{...process.env}});
stamp('remote child started pid='+child.pid);
child.on('exit',(code,signal)=>{stamp('remote child exited code='+code+' signal='+(signal||'')+'; no auth retry loop');process.exit(code||0);});