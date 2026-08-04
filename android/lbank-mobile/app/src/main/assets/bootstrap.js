(()=>{
  'use strict';
  const BASE='https://raw.githubusercontent.com/saladinayoubi1/lbank-research-automation/main/android/lbank-mobile/app/src/main/assets/';
  const MANIFEST=BASE+'update-manifest.json';
  const CACHE_KEY='lbank-remote-bundle-v3';
  const SCRIPTS=['provider-manager.js','nexus-council.js','app.js','personal-tools.js'];
  const STYLES=['v3.css','nexus-council.css'];
  const ALLOWED=[...SCRIPTS,...STYLES];
  let applied=false;
  const status=()=>document.getElementById('updateStatus');
  const setStatus=text=>{const el=status();if(el)el.lastChild.textContent=' '+text};
  const safeName=name=>ALLOWED.includes(name)&&!name.includes('..')&&!name.includes('/');
  const moduleLoaded=name=>(name==='provider-manager.js'&&window.LBankProviders)||(name==='nexus-council.js'&&window.NexusCouncil);
  const fetchText=async url=>{const join=url.includes('?')?'&':'?';const r=await fetch(url+join+'t='+Date.now(),{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);return r.text()};
  const injectStyle=(text,name)=>{if(document.querySelector(`[data-remote-update="${name}"]`))return;const el=document.createElement('style');el.dataset.remoteUpdate=name;el.textContent=text;document.head.appendChild(el)};
  const execute=(text,name)=>{if(moduleLoaded(name)||document.querySelector(`[data-remote-update="${name}"]`))return;const el=document.createElement('script');el.dataset.remoteUpdate=name;el.textContent=text+'\n//# sourceURL='+name;document.body.appendChild(el)};
  const fallback=name=>{if(moduleLoaded(name)||document.querySelector(`script[data-local-module="${name}"]`))return;const el=document.createElement('script');el.src=name;el.dataset.localModule=name;el.async=false;document.body.appendChild(el)};
  function validateManifest(m){if(!m||typeof m.version!=='string'||!Array.isArray(m.files))throw new Error('Invalid manifest');const names=new Set();for(const f of m.files){if(!safeName(f.name)||names.has(f.name)||typeof f.url!=='string'||!f.url.startsWith(BASE))throw new Error('Unsafe update manifest');names.add(f.name)}}
  async function downloadBundle(){const manifest=JSON.parse(await fetchText(MANIFEST));validateManifest(manifest);const files={};for(const f of manifest.files)files[f.name]=await fetchText(f.url);return{version:manifest.version,files,savedAt:Date.now()}}
  function cachedBundle(){try{const b=JSON.parse(localStorage.getItem(CACHE_KEY)||'null');return b&&b.files?b:null}catch{return null}}
  function saveBundle(bundle){localStorage.setItem(CACHE_KEY,JSON.stringify(bundle))}
  function apply(bundle){if(applied)return;applied=true;for(const n of STYLES){if(bundle?.files?.[n])injectStyle(bundle.files[n],n)}for(const n of SCRIPTS){if(bundle?.files?.[n])execute(bundle.files[n],n);else fallback(n)}setStatus(bundle?'V'+bundle.version:'LOCAL')}
  async function initialLoad(){setStatus('CHECK');const cached=cachedBundle();try{const fresh=await downloadBundle();saveBundle(fresh);apply(fresh)}catch(e){console.warn('Remote update unavailable:',e);apply(cached)}}
  async function backgroundCheck(force=false){setStatus('CHECK');try{const before=cachedBundle();const fresh=await downloadBundle();saveBundle(fresh);if(!before||before.version!==fresh.version){setStatus('NEW');setTimeout(()=>location.reload(),force?250:1200)}else setStatus('V'+fresh.version)}catch(e){console.warn('Update check failed:',e);const current=cachedBundle();setStatus(current?'V'+current.version:'LOCAL')}}
  window.LBankUpdater={check:()=>backgroundCheck(true),clear:()=>localStorage.removeItem(CACHE_KEY)};
  window.addEventListener('DOMContentLoaded',()=>{initialLoad();document.getElementById('checkUpdate')?.addEventListener('click',()=>backgroundCheck(true));setInterval(()=>backgroundCheck(false),6*60*60*1000)});
})();