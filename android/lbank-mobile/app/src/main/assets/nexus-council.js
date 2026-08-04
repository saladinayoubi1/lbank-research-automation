(()=>{
'use strict';
const KEY='nexus-council-v1';
const ROLES={builder:'سازنده',architect:'معمار',critic:'منتقد',risk:'مدیر ریسک',research:'پژوهشگر',qa:'تست و کنترل کیفیت',judge:'داور'};
let state=load();
function load(){try{return Object.assign({leader:'openai',mode:'specialist',rounds:2,memory:[],roleMap:{}},JSON.parse(localStorage.getItem(KEY)||'{}'))}catch{return{leader:'openai',mode:'specialist',rounds:2,memory:[],roleMap:{}}}}
const save=()=>localStorage.setItem(KEY,JSON.stringify(state));
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const providers=()=>window.LBankProviders?.get?.()||[];
function defaultRole(p,i){const map=['builder','critic','research','risk','architect','qa'];return state.roleMap[p.id]||map[i%map.length]}
function renderTeam(){const list=providers();const team=$('#nexusTeam');if(!team)return;team.innerHTML=list.map((p,i)=>`<article class="card nexus-member"><header><b>${esc(p.name)}</b><label><input type="radio" name="leader" value="${esc(p.id)}" ${state.leader===p.id?'checked':''}> رهبر</label></header><small>${esc(p.model)}</small><label>نقش<select data-role="${esc(p.id)}">${Object.entries(ROLES).map(([k,v])=>`<option value="${k}" ${defaultRole(p,i)===k?'selected':''}>${v}</option>`).join('')}</select></label></article>`).join('')||'<article class="card empty">هیچ ارائه‌دهنده فعالی وجود ندارد.</article>';
 team.querySelectorAll('input[name="leader"]').forEach(x=>x.onchange=()=>{state.leader=x.value;save();syncLeader()});
 team.querySelectorAll('[data-role]').forEach(x=>x.onchange=()=>{state.roleMap[x.dataset.role]=x.value;save()});
 syncLeader();
}
function syncLeader(){const p=providers().find(x=>x.id===state.leader)||providers()[0];if(p&&state.leader!==p.id){state.leader=p.id;save()}$('#nexusLeaderLabel')&&($('#nexusLeaderLabel').textContent=p?`${p.name} · ${p.model}`:'—')}
function systemPrompt(role,topic,round,prior){return`تو عضو شورای NEXUS با نقش ${ROLES[role]||role} هستی. موضوع: ${topic}\nدور: ${round}. پاسخ دقیق، کوتاه و قابل اجرا بده. نقاط ضعف و فرض‌ها را صریح بنویس.${prior?`\nخلاصه نظرات قبلی:\n${prior}`:''}`}
async function callProvider(p,messages){const key=sessionStorage.getItem('lbank-provider-key-'+p.id)||'';if(p.type!=='ollama'&&!key)throw Error('API Key تنظیم نشده');
 if(p.type==='openai-compatible'){const r=await fetch(p.baseUrl.replace(/\/$/,'')+'/chat/completions',{method:'POST',headers:{'content-type':'application/json','authorization':'Bearer '+key},body:JSON.stringify({model:p.model,messages,temperature:.25})});if(!r.ok)throw Error('HTTP '+r.status);const j=await r.json();return j.choices?.[0]?.message?.content||''}
 if(p.type==='anthropic'){const r=await fetch(p.baseUrl.replace(/\/$/,'')+'/v1/messages',{method:'POST',headers:{'content-type':'application/json','x-api-key':key,'anthropic-version':'2023-06-01'},body:JSON.stringify({model:p.model,max_tokens:1800,messages:messages.filter(x=>x.role!=='system'),system:messages.find(x=>x.role==='system')?.content||''})});if(!r.ok)throw Error('HTTP '+r.status);const j=await r.json();return j.content?.map(x=>x.text||'').join('\n')||''}
 if(p.type==='gemini'){const url=p.baseUrl.replace(/\/$/,'')+`/v1beta/models/${encodeURIComponent(p.model)}:generateContent?key=${encodeURIComponent(key)}`;const r=await fetch(url,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({contents:[{parts:[{text:messages.map(x=>`${x.role}: ${x.content}`).join('\n\n')}]}]})});if(!r.ok)throw Error('HTTP '+r.status);const j=await r.json();return j.candidates?.[0]?.content?.parts?.map(x=>x.text||'').join('\n')||''}
 if(p.type==='ollama'){const r=await fetch(p.baseUrl.replace(/\/$/,'')+'/api/chat',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({model:p.model,stream:false,messages})});if(!r.ok)throw Error('HTTP '+r.status);const j=await r.json();return j.message?.content||''}
 throw Error('نوع سرویس پشتیبانی نمی‌شود')}
function addBubble(name,role,text,status='ok'){const root=$('#nexusChat');root.insertAdjacentHTML('beforeend',`<article class="nexus-bubble ${status}"><header><b>${esc(name)}</b><span>${esc(ROLES[role]||role)}</span></header><pre>${esc(text)}</pre></article>`);root.scrollTop=root.scrollHeight}
async function run(){const topic=$('#nexusTopic').value.trim();if(!topic)return alert('موضوع را وارد کن.');const active=providers();if(!active.length)return alert('ارائه‌دهنده فعالی وجود ندارد.');state.mode=$('#nexusMode').value;state.rounds=Math.max(1,Math.min(4,Number($('#nexusRounds').value)||2));save();$('#nexusRun').disabled=true;$('#nexusChat').innerHTML='';$('#nexusFinal').textContent='';let transcript=[];
 try{
  if(state.mode==='specialist'){
   await Promise.all(active.map(async(p,i)=>{const role=defaultRole(p,i);try{const text=await callProvider(p,[{role:'system',content:systemPrompt(role,topic,1,'')},{role:'user',content:topic}]);transcript.push({provider:p.id,name:p.name,role,text});addBubble(p.name,role,text)}catch(e){transcript.push({provider:p.id,name:p.name,role,error:e.message});addBubble(p.name,role,e.message,'error')}}));
  }else{
   for(let round=1;round<=state.rounds;round++){
    for(let i=0;i<active.length;i++){const p=active[i],role=defaultRole(p,i),prior=transcript.filter(x=>x.text).slice(-8).map(x=>`${x.name}: ${x.text.slice(0,700)}`).join('\n');try{const text=await callProvider(p,[{role:'system',content:systemPrompt(role,topic,round,prior)},{role:'user',content:round===1?topic:'نظرات قبلی را نقد و اصلاح کن.'}]);transcript.push({provider:p.id,name:p.name,role,round,text});addBubble(`${p.name} · دور ${round}`,role,text)}catch(e){transcript.push({provider:p.id,name:p.name,role,round,error:e.message});addBubble(p.name,role,e.message,'error')}}
   }
  }
  const leader=active.find(x=>x.id===state.leader)||active[0];const evidence=transcript.filter(x=>x.text).map(x=>`[${x.name}/${ROLES[x.role]}]\n${x.text}`).join('\n\n');let final='';try{final=await callProvider(leader,[{role:'system',content:'تو رهبر NEXUS هستی. همه نظرات را به یک خروجی واحد، بدون تناقض، با بخش‌های تصمیم نهایی، دلایل، ریسک‌ها، موارد ردشده و گام‌های بعدی تبدیل کن.'},{role:'user',content:`موضوع: ${topic}\n\nنظرات شورا:\n${evidence}`}])}catch(e){final='جمع‌بندی خودکار انجام نشد: '+e.message+'\n\n'+evidence}
  $('#nexusFinal').textContent=final;state.memory.unshift({id:Date.now(),topic,leader:leader.id,mode:state.mode,createdAt:new Date().toISOString(),final,transcript});state.memory=state.memory.slice(0,40);save();renderMemory();
 }finally{$('#nexusRun').disabled=false}
}
function renderMemory(){const root=$('#nexusMemory');if(!root)return;root.innerHTML=state.memory.map((m,i)=>`<article class="card memory-card"><b>${esc(m.topic)}</b><small>${new Date(m.createdAt).toLocaleString('fa-IR')}</small><p>${esc((m.final||'').slice(0,220))}</p><button data-open-memory="${i}">بازکردن</button><button data-delete-memory="${i}" class="danger-btn">حذف</button></article>`).join('')||'<article class="card empty">حافظه پروژه هنوز خالی است.</article>';root.querySelectorAll('[data-open-memory]').forEach(b=>b.onclick=()=>{const m=state.memory[+b.dataset.openMemory];$('#nexusTopic').value=m.topic;$('#nexusChat').innerHTML='';m.transcript?.forEach(x=>addBubble(x.name,x.role,x.text||x.error,x.error?'error':'ok'));$('#nexusFinal').textContent=m.final||''});root.querySelectorAll('[data-delete-memory]').forEach(b=>b.onclick=()=>{state.memory.splice(+b.dataset.deleteMemory,1);save();renderMemory()})}
window.addEventListener('DOMContentLoaded',()=>{renderTeam();renderMemory();$('#nexusRun')?.addEventListener('click',run);$('#nexusMode')&&($('#nexusMode').value=state.mode);$('#nexusRounds')&&($('#nexusRounds').value=state.rounds);document.addEventListener('providers-changed',renderTeam)});
window.NexusCouncil={refresh:renderTeam,getMemory:()=>state.memory};
})();