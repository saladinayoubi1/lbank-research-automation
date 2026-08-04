(()=>{
  'use strict';
  let timer=0,last='';
  const snapshot=()=>JSON.stringify(window.LBankProviders?.get?.().map(p=>({id:p.id,name:p.name,model:p.model,enabled:p.enabled,priority:p.priority,type:p.type}))||[]);
  const notify=()=>{clearTimeout(timer);timer=setTimeout(()=>{const next=snapshot();if(next!==last){last=next;document.dispatchEvent(new CustomEvent('providers-changed'))}},80)};
  window.addEventListener('DOMContentLoaded',()=>{
    last=snapshot();
    const root=document.getElementById('providerList');
    if(root)new MutationObserver(notify).observe(root,{childList:true,subtree:true,attributes:true});
    document.getElementById('addProvider')?.addEventListener('click',notify);
    document.getElementById('importProviders')?.addEventListener('change',notify);
  });
})();