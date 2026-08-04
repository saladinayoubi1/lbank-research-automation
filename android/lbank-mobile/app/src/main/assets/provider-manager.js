(()=>{
  'use strict';
  const KEY='lbank-ai-providers-v1';
  const defaults=[
    {id:'openai',name:'OpenAI',baseUrl:'https://api.openai.com/v1',model:'gpt-4.1-mini',enabled:true,priority:10,type:'openai-compatible'},
    {id:'gemini',name:'Google Gemini',baseUrl:'https://generativelanguage.googleapis.com',model:'gemini-2.5-flash',enabled:true,priority:20,type:'gemini'},
    {id:'anthropic',name:'Anthropic Claude',baseUrl:'https://api.anthropic.com',model:'claude-sonnet-4-5',enabled:true,priority:30,type:'anthropic'},
    {id:'xai',name:'xAI Grok',baseUrl:'https://api.x.ai/v1',model:'grok-4-fast',enabled:true,priority:40,type:'openai-compatible'},
    {id:'deepseek',name:'DeepSeek',baseUrl:'https://api.deepseek.com',model:'deepseek-chat',enabled:true,priority:50,type:'openai-compatible'},
    {id:'openrouter',name:'OpenRouter',baseUrl:'https://openrouter.ai/api/v1',model:'openrouter/free',enabled:true,priority:60,type:'openai-compatible'},
    {id:'ollama',name:'Ollama Local',baseUrl:'http://127.0.0.1:11434',model:'qwen3:8b',enabled:true,priority:70,type:'ollama'}
  ];
  const load=()=>{try{const saved=JSON.parse(localStorage.getItem(KEY)||'null');return Array.isArray(saved)?saved:defaults}catch{return defaults}};
  const save=list=>localStorage.setItem(KEY,JSON.stringify(list));
  let providers=load();
  const escapeHtml=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]));
  const root=()=>document.getElementById('providerList');
  function render(){
    const el=root(); if(!el)return;
    providers.sort((a,b)=>(a.priority||999)-(b.priority||999));
    el.innerHTML=providers.map((p,i)=>`<article class="card provider-card" data-index="${i}">
      <div class="provider-head"><div><b>${escapeHtml(p.name)}</b><small>${escapeHtml(p.type)}</small></div><label class="switch"><input type="checkbox" data-field="enabled" ${p.enabled?'checked':''}><span></span></label></div>
      <label>نام<input data-field="name" value="${escapeHtml(p.name)}"></label>
      <label>نوع<select data-field="type"><option value="openai-compatible" ${p.type==='openai-compatible'?'selected':''}>OpenAI compatible</option><option value="gemini" ${p.type==='gemini'?'selected':''}>Gemini</option><option value="anthropic" ${p.type==='anthropic'?'selected':''}>Anthropic</option><option value="ollama" ${p.type==='ollama'?'selected':''}>Ollama</option></select></label>
      <label>Base URL<input data-field="baseUrl" value="${escapeHtml(p.baseUrl)}"></label>
      <label>مدل<input data-field="model" value="${escapeHtml(p.model)}"></label>
      <label>اولویت<input data-field="priority" type="number" min="1" max="999" value="${Number(p.priority)||100}"></label>
      <label>API Key<input data-secret="${escapeHtml(p.id)}" type="password" placeholder="فقط روی دستگاه ذخیره شود"></label>
      <div class="provider-actions"><button data-action="up">↑</button><button data-action="down">↓</button><button data-action="test">تست</button><button data-action="delete" class="danger-btn">حذف</button></div>
    </article>`).join('');
    bind();
    const c=document.getElementById('providerCount');if(c)c.textContent=`${providers.filter(x=>x.enabled).length} فعال`;
  }
  function bind(){
    document.querySelectorAll('.provider-card').forEach(card=>{
      const index=Number(card.dataset.index),p=providers[index];
      card.querySelectorAll('[data-field]').forEach(input=>input.onchange=()=>{const f=input.dataset.field;p[f]=f==='enabled'?input.checked:f==='priority'?Number(input.value):input.value;save(providers);render()});
      const secret=card.querySelector('[data-secret]');
      const sk='lbank-provider-key-'+p.id; secret.value=sessionStorage.getItem(sk)||'';
      secret.onchange=()=>{sessionStorage.setItem(sk,secret.value);secret.value=''};
      card.querySelector('[data-action="delete"]').onclick=()=>{if(confirm('این ارائه‌دهنده حذف شود؟')){providers.splice(index,1);save(providers);render()}};
      card.querySelector('[data-action="up"]').onclick=()=>move(index,-1);
      card.querySelector('[data-action="down"]').onclick=()=>move(index,1);
      card.querySelector('[data-action="test"]').onclick=()=>testProvider(p,card);
    });
  }
  function move(i,d){const j=i+d;if(j<0||j>=providers.length)return;[providers[i],providers[j]]=[providers[j],providers[i]];providers.forEach((p,k)=>p.priority=(k+1)*10);save(providers);render()}
  async function testProvider(p,card){
    const btn=card.querySelector('[data-action="test"]');btn.disabled=true;btn.textContent='در حال تست';
    try{
      const u=new URL(p.baseUrl);if(!['https:','http:'].includes(u.protocol))throw Error('URL نامعتبر');
      const r=await fetch(p.baseUrl,{method:'HEAD',mode:'no-cors'});void r;
      btn.textContent='قابل دسترس';
    }catch(e){btn.textContent='نیازمند بررسی'}
    setTimeout(()=>{btn.disabled=false;btn.textContent='تست'},1800);
  }
  function add(){
    providers.push({id:'custom-'+Date.now(),name:'سرویس جدید',baseUrl:'https://',model:'',enabled:true,priority:(providers.length+1)*10,type:'openai-compatible'});save(providers);render();
  }
  function exportConfig(){const data=providers.map(({id,name,baseUrl,model,enabled,priority,type})=>({id,name,baseUrl,model,enabled,priority,type}));const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));a.download='lbank-ai-providers.json';a.click();URL.revokeObjectURL(a.href)}
  function importConfig(file){const r=new FileReader();r.onload=()=>{try{const x=JSON.parse(r.result);if(!Array.isArray(x))throw Error();providers=x.map(p=>({...p,id:p.id||'custom-'+crypto.randomUUID()}));save(providers);render()}catch{alert('فایل تنظیمات معتبر نیست')}};r.readAsText(file)}
  window.LBankProviders={get:()=>providers.filter(x=>x.enabled).sort((a,b)=>a.priority-b.priority),reset:()=>{providers=defaults;save(providers);render()}};
  window.addEventListener('DOMContentLoaded',()=>{
    document.getElementById('addProvider')?.addEventListener('click',add);
    document.getElementById('exportProviders')?.addEventListener('click',exportConfig);
    document.getElementById('importProviders')?.addEventListener('change',e=>e.target.files[0]&&importConfig(e.target.files[0]));
    render();
  });
})();
