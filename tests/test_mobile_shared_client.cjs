const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('android/lbank-mobile/app/src/main/assets/mobile-shared-client.js','utf8');
function harness(){
  let now=1000000;
  const nodes=new Map(),events={},timers=[],renders=[],requests=[];
  const document={hidden:false,getElementById(id){if(!nodes.has(id))nodes.set(id,{dataset:{},blur(){},close(){this.open=false;}});return nodes.get(id);},addEventListener(n,f){events[n]=f;}};
  const window={navigator:{onLine:true},NexusPaperTerminal:{render(x){renders.push(x);}},NexusProductClient:{call(method,path){return new Promise((resolve,reject)=>requests.push({method,path,resolve,reject}));}},addEventListener(n,f){events[n]=f;}};
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
 assert.equal(h.nodes.get('sharedConnection').dataset.state,'offline');assert.equal(h.renders.at(-1),null);
 h.window.navigator.onLine=true;h.events.online();h.requests[3].resolve(payload());await h.flush();
 assert.equal(h.nodes.get('sharedConnection').dataset.state,'connected');
 assert.equal(h.timers.filter(t=>!t.cancelled).at(-1).ms,30000);
});
test('a normal refresh preserves visible table until the new response arrives',async()=>{
 const h=harness();h.requests[0].resolve(payload());await h.flush();const count=h.renders.length;
 h.events.focus();assert.equal(h.renders.length,count);assert.equal(h.nodes.get('sharedConnection').dataset.state,'connected');
 h.events.focus();assert.equal(h.requests.length,2);
});
