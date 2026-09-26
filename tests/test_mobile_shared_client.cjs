const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('android/lbank-mobile/app/src/main/assets/mobile-shared-client.js','utf8');
function harness(){
  let now=1000000;
  const nodes=new Map(),events={},timers=[],renders=[],requests=[];
  const document={hidden:false,getElementById(id){if(!nodes.has(id))nodes.set(id,{dataset:{},blur(){},close(){this.open=false;}});return nodes.get(id);},addEventListener(n,f){events[n]=f;}};
  const window={NexusPaperTerminal:{render(x){renders.push(x);}},NexusProductClient:{call(method,path){return new Promise((resolve,reject)=>requests.push({method,path,resolve,reject}));}},addEventListener(n,f){events[n]=f;}};
  vm.runInNewContext(source,{document,window,Date:{now:()=>now},setInterval(f,ms){timers.push({f,ms});}});
  return {nodes,events,timers,renders,requests,document,advance(s){now+=s*1000;},async flush(){await new Promise(setImmediate);}};
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
 h.document.hidden=true;h.timers.find(t=>t.ms===30000).f();assert.equal(h.requests.length,1);
});
