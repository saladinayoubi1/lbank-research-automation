const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('android/lbank-mobile/app/src/main/assets/mobile-shared-client.js','utf8');
function harness({online=true,clientReady=true}={}){
  let now=1000000;
  const nodes=new Map(),events={},timers=[],renders=[],requests=[];
  const document={hidden:false,getElementById(id){if(!nodes.has(id))nodes.set(id,{dataset:{},blur(){},close(){this.open=false;}});return nodes.get(id);},addEventListener(n,f){events[n]=f;}};
  const window={navigator:{onLine:online},NexusPaperTerminal:{render(x){renders.push(x);}},NexusProductClient:{call(method,path){return new Promise((resolve,reject)=>requests.push({method,path,resolve,reject}));}},addEventListener(n,f){events[n]=f;}};
  if(!clientReady)delete window.NexusProductClient;
  vm.runInNewContext(source,{document,window,Date:{now:()=>now},setInterval(f,ms){timers.push({f,ms});},setTimeout(f,ms){const t={f,ms};timers.push(t);return t;},clearTimeout(t){if(t)t.cancelled=true;}});
  return {nodes,events,timers,renders,requests,document,window,advance(s){now+=s*1000;},async flush(){await new Promise(setImmediate);}};
}
function payload(){return {paper_only:true,live_trading_authority:false,shared_portfolio:{available:true,schema:'nexus.shared-paper-terminal.v1',mode:'internal_paper',read_only:true,live_trading_authority:false,account:{equity:503.2},positions:[],history:[],orders:[],cashflows:[],strategies:[],age_seconds:1,stale:false}};}
test('independent read-only snapshot survives unrelated canonical failures and labels disconnection',async()=>{
 const h=harness();assert.equal(h.requests[0].method,'GET');assert.equal(h.requests[0].path,'/api/product/paper');
 h.requests[0].resolve(payload());await h.flush();assert.equal(h.nodes.get('sharedConnection').dataset.state,'connected');
 h.nodes.get('refreshSharedPaper').onclick();h.requests[1].reject(Error('offline'));await h.flush();
 assert.equal(h.nodes.get('sharedConnection').dataset.state,'offline');assert.equal(h.renders.at(-1).account.equity,503.2);assert.equal(h.renders.at(-1).stale,true);
});
test('age advances without inventing fresh prices and without constantly rebuilding focused UI',async()=>{
 const h=harness();h.requests[0].resolve(payload());await h.flush();const count=h.renders.length;
 h.advance(181);h.timers.find(t=>t.ms===1000).f();assert.equal(h.nodes.get('sharedConnection').dataset.state,'stale');assert.equal(h.renders.length,count);
});
test('new native pairing discards old-origin late responses',async()=>{
 const h=harness();h.events['nexus-gateway-configured']();h.requests[0].resolve(payload());await h.flush();
 assert.equal(h.requests.length,2);assert.equal(h.renders.at(-1),null);
 const p=payload();p.shared_portfolio.account.equity=600;h.requests[1].resolve(p);await h.flush();assert.equal(h.renders.at(-1).account.equity,600);
});
test('invalid authority cannot become a connected account; hidden screens do not poll',async()=>{
 const h=harness();const p=payload();p.shared_portfolio.live_trading_authority=true;h.requests[0].resolve(p);await h.flush();
 assert.equal(h.nodes.get('sharedConnection').dataset.state,'offline');assert.equal(h.renders.at(-1),null);
 h.document.hidden=true;h.events.focus();assert.equal(h.requests.length,1);
});

test('retry backs off, online recovers immediately, and offline late success cannot revive connection',async()=>{
 const h=harness();h.requests[0].reject(Error('network'));await h.flush();
 let timer=h.timers.filter(t=>!t.cancelled).at(-1);assert.equal(timer.ms,5000);
 timer.f();h.requests[1].reject(Error('network'));await h.flush();
 timer=h.timers.filter(t=>!t.cancelled).at(-1);assert.equal(timer.ms,10000);
 h.events.online();assert.equal(timer.cancelled,true);assert.equal(h.requests.length,3);
 h.window.navigator.onLine=false;h.events.offline();h.requests[2].resolve(payload());await h.flush();
 assert.equal(h.requests.length,4);assert.equal(h.nodes.get('sharedConnection').dataset.state,'loading');assert.equal(h.renders.at(-1),null);
 h.window.navigator.onLine=true;h.events.online();h.requests[3].resolve(payload());await h.flush();
 assert.equal(h.nodes.get('sharedConnection').dataset.state,'connected');
 assert.equal(h.timers.filter(t=>!t.cancelled).at(-1).ms,30000);
});
test('a normal refresh preserves visible table until the new response arrives',async()=>{
 const h=harness();h.requests[0].resolve(payload());await h.flush();const count=h.renders.length;
 h.events.focus();assert.equal(h.renders.length,count);assert.equal(h.nodes.get('sharedConnection').dataset.state,'connected');
 h.events.focus();assert.equal(h.requests.length,2);
});

test('VPN offline hint never suppresses an authenticated HTTPS attempt',async()=>{
 const h=harness({online:false});
 assert.equal(h.requests.length,1);
 h.requests[0].resolve(payload());await h.flush();
 assert.equal(h.nodes.get('sharedConnection').dataset.state,'connected');
});
test('failures display actionable safe diagnostics without printing arbitrary exceptions',async()=>{
 const bad=harness();
 bad.requests[0].reject(Error('NEXUS gateway HTTP 401'));await bad.flush();
 assert.match(bad.nodes.get('sharedConnectionDetail').textContent,/401/);
 assert.equal(bad.nodes.get('sharedConnection').dataset.state,'offline');
 const tls=harness();
 tls.requests[0].reject(Error('SSLHandshakeException: private sensitive message'));await tls.flush();
 assert.match(tls.nodes.get('sharedConnectionDetail').textContent,/HTTPS/);
 assert.doesNotMatch(tls.nodes.get('sharedConnectionDetail').textContent,/private sensitive/);
 const other=harness();
 other.requests[0].reject(Error('Bearer owner-secret-should-not-appear'));await other.flush();
 assert.doesNotMatch(other.nodes.get('sharedConnectionDetail').textContent,/secret/);
});
test('late native bridge becomes usable without a restart',async()=>{
 const h=harness({clientReady:false});
 assert.equal(h.requests.length,0);
 assert.match(h.nodes.get('sharedConnectionDetail').textContent,/اپ/);
 h.window.NexusProductClient={call(method,path){return new Promise((resolve,reject)=>h.requests.push({method,path,resolve,reject}));}};
 h.events['nexus-product-client-ready']();
 assert.equal(h.requests.length,1);
 h.requests[0].resolve(payload());await h.flush();
 assert.equal(h.nodes.get('sharedConnection').dataset.state,'connected');
});

test('packaged canonical bridge boots before the independent Paper reader on an Android VPN',async()=>{
 const html=fs.readFileSync('android/lbank-mobile/app/src/main/assets/index.html','utf8');
 const tags=['mobile-canonical-client.js','mobile-shared-client.js'].map(s=>'<script src="'+s+'" defer></script>');
 assert(tags.every(s=>html.includes(s))&&html.indexOf(tags[0])<html.indexOf(tags[1]));
 const canonicalSource=fs.readFileSync('android/lbank-mobile/app/src/main/assets/mobile-canonical-client.js','utf8');
 const nodes=new Map(),requests=[],renders=[],events={};
 const document={hidden:false,head:{appendChild(){}},querySelector(){return null},createElement(){return {style:{},textContent:''}},
  getElementById(id){if(!nodes.has(id))nodes.set(id,{dataset:{},blur(){}});return nodes.get(id);},
  addEventListener(name,fn){events[name]=fn;}};
 const window={navigator:{onLine:false},NexusPaperTerminal:{render(v){renders.push(v)}},
  NexusNative:{requestProduct(id,method,path){requests.push({id,method,path});}},
  addEventListener(name,fn){events[name]=fn;},dispatchEvent(event){events[event.type]?.(event);}};
 const context={document,window,Date,console,Event:class {constructor(type){this.type=type}},
  setTimeout(){return 1},clearTimeout(){},setInterval(){return 2}};
 vm.runInNewContext(canonicalSource,context);
 assert.equal(typeof window.NexusProductClient.call,'function');
 assert.equal(typeof window.NexusProductResult,'function');
 vm.runInNewContext(source,context);
 const calls=requests.filter(r=>r.path==='/api/product/paper');
 assert.equal(calls.length,2,'canonical sync and independent reader both issue GET');
 assert(calls.every(r=>r.method==='GET'));
 window.NexusProductResult(calls[1].id,true,JSON.stringify(payload()));
 await new Promise(setImmediate);
 assert.equal(nodes.get('sharedConnection').dataset.state,'connected');
 assert.equal(renders.at(-1).account.equity,503.2);
});

test('queued manual tap runs one follow-up GET after an in-flight response',async()=>{
 const h=harness(),button=h.nodes.get('refreshSharedPaper');
 button.onclick();button.onclick();button.onclick();
 assert.equal(h.requests.length,1,'repeat taps must not flood native bridge');
 assert.match(button.textContent,/در صف/);
 assert.match(h.nodes.get('sharedConnectionDetail').textContent,/ثبت شد/);
 h.requests[0].resolve(payload());await h.flush();
 assert.equal(h.requests.length,2,'a queued tap must refresh immediately on completion');
 assert.match(button.textContent,/در حال دریافت/);
 const p=payload();p.shared_portfolio.account.equity=505;
 h.requests[1].resolve(p);await h.flush();
 assert.equal(h.requests.length,2,'repeat taps coalesce to a single follow-up');
 assert.equal(h.renders.at(-1).account.equity,505);
 assert.equal(button.textContent,'تازه‌سازی');
 assert.equal(h.timers.filter(t=>!t.cancelled).at(-1).ms,30000);
});
test('a single manual tap cancels retry backoff and immediately performs a GET',async()=>{
 const h=harness();
 h.requests[0].reject(Error('network'));await h.flush();
 const timer=h.timers.filter(t=>!t.cancelled).at(-1);
 assert.equal(timer.ms,5000);
 h.nodes.get('refreshSharedPaper').onclick();
 assert.equal(timer.cancelled,true);
 assert.equal(h.requests.length,2);
 h.requests[1].resolve(payload());await h.flush();
 assert.equal(h.nodes.get('sharedConnection').dataset.state,'connected');
});
test('new pairing invalidates queued old-origin manual refresh',async()=>{
 const h=harness();
 h.nodes.get('refreshSharedPaper').onclick();
 h.events['nexus-gateway-configured']();
 h.requests[0].resolve(payload());await h.flush();
 assert.equal(h.requests.length,2,'pairing starts exactly one new-origin request');
 h.requests[1].resolve(payload());await h.flush();
 assert.equal(h.requests.length,2,'no queued old-origin retry');
 assert.equal(h.nodes.get('sharedConnection').dataset.state,'connected');
});
test('hidden refresh events do not cancel pending retry',async()=>{
 const h=harness();
 h.requests[0].reject(Error('network'));await h.flush();
 const timer=h.timers.filter(t=>!t.cancelled).at(-1);
 h.document.hidden=true;h.events.focus();
 assert.equal(timer.cancelled,false);
});
