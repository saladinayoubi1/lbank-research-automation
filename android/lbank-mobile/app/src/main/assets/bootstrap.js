(()=>{
  'use strict';
  const BASE='https://raw.githubusercontent.com/saladinayoubi1/lbank-research-automation/main/android/lbank-mobile/app/src/main/assets/';
  const MANIFEST=BASE+'update-manifest.json';
  const CACHE_KEY='lbank-remote-bundle-v1';
  const ALLOWED=['app.js','personal-tools.js','v3.css'];
  const status=()=>document.getElementById('updateStatus');
  const setStatus=text=>{const el=status();if(el)el.lastChild.textContent=' '+text};
  const safeName=name=>ALLOWED.includes(name)&&!name.includes('..')&&!name.includes('/');
  const fetchText=async url=>{const r=await fetch(url+'?t='+Date.now(),{cache:'no-store',redirect:'error'});if(!r.ok)throw new Error('HTTP '+r.status);return r.text()};
  const injectStyle=text=>{const el=document.createElement('style');el.dataset.remoteUpdate='true';el.textContent=text;document.head.appendChild(el)};
  const runScript=text,name)=>{};
  function execute(text,name){const el=document.createElement('script');el.dataset.remoteUpdate=name;el.textContent=text+'\n//# sourceURL='+name;document.body.appendChild(el)}
  function validateManifest(m){if(!m||typeof m.version!=='string'||!Array.isArray(m.files))throw new Error('Invalid manifest');for(const f of m.files){if(!safeName(f.name)||typeof f.url!=='string'||!f.url.startsWith(BASE))throw new Error('Unsafe update source')}}
  async function downloadBundle(){const manifest=JSON.parse(await fetchText(MANIFEST));validateManifest(manifest);const files={};for(const f of manifest.files)files[f.name]=await fetchText(f.url);const bundle={version:manifest.version,files,savedAt:Date.now()};localStorage.setItem(CACHE_KEY,JSON.stringify(bundle));return bundle}
  function cachedBundle(){try{const b=JSON.parse(localStorage.getItem(CACHE_KEY)||'null');if(!b||!b.files)return null;return b}catch{return null}}
  function apply(bundle){if(bundle?.files?.['v3.css'])injectStyle(bundle.files['v3.css']);if(bundle?.files?.['app.js'])execute(bundle.files['app.js'],'remote-app.js');else fallback('app.js');if(bundle?.files?.['personal-tools.js'])execute(bundle.files['personal-tools.js'],'remote-personal-tools.js');else fallback('personal-tools.js');setStatus(bundle?'V'+bundle.version:'LOCAL')}
  function fallback(name){const el=document.createElement('script');el.src=name;el.defer=false;document.body.appendChild(el)}
  async function update(force=false){setStatus('CHECK');try{const fresh=await downloadBundle();const current=cachedBundle();apply(fresh);if(force&&current?.version!==fresh.version)setTimeout(()=>location.reload(),450)}catch(e){console.warn('Remote update unavailable:',e);const cached=cachedBundle();apply(cached)}}
  window.LBankUpdater={check:()=>update(true),clear:()=>localStorage.removeItem(CACHE_KEY)};
  window.addEventListener('DOMContentLoaded',()=>{
    update(false);
    const button=document.getElementById('checkUpdate');if(button)button.addEventListener('click',()=>update(true));
    setInterval(()=>update(false),6*60*60*1000);
  });
})();
