(()=>{
'use strict';
const BASE='https://raw.githubusercontent.com/saladinayoubi1/lbank-research-automation/main/android/lbank-mobile/app/src/main/assets/';
const MANIFEST=BASE+'update-manifest.json';
const CACHE_KEY='nexus-style-bundle-v1';
const STYLES=['v3.css','nexus-council.css'];
const status=()=>document.getElementById('updateStatus');
const setStatus=text=>{const el=status();if(el)el.lastChild.textContent=' '+text};
const fetchText=async url=>{const join=url.includes('?')?'&':'?';const r=await fetch(url+join+'t='+Date.now(),{cache:'no-store',redirect:'error'});if(!r.ok)throw Error('HTTP '+r.status);return r.text()};
function validate(m){if(!m||typeof m.version!=='string'||!Array.isArray(m.files))throw Error('Invalid manifest');for(const f of m.files){if(!STYLES.includes(f.name)||typeof f.url!=='string'||!f.url.startsWith(BASE))throw Error('Executable or unsafe remote update rejected')}}
async function download(){const m=JSON.parse(await fetchText(MANIFEST));validate(m);const files={};for(const f of m.files)files[f.name]=await fetchText(f.url);return{version:m.version,files,savedAt:Date.now()}}
function cached(){try{const b=JSON.parse(localStorage.getItem(CACHE_KEY)||'null');return b&&b.files?b:null}catch{return null}}
function apply(bundle){if(!bundle)return setStatus('LOCAL');for(const name of STYLES){if(!bundle.files[name])continue;document.querySelector(`[data-remote-style="${name}"]`)?.remove();const style=document.createElement('style');style.dataset.remoteStyle=name;style.textContent=bundle.files[name];document.head.appendChild(style)}setStatus('V'+bundle.version)}
async function check(force=false){setStatus('CHECK');try{const before=cached(),fresh=await download();localStorage.setItem(CACHE_KEY,JSON.stringify(fresh));apply(fresh);if(force&&(!before||before.version!==fresh.version))location.reload()}catch(e){console.warn('Safe style update unavailable:',e);apply(cached())}}
window.LBankUpdater={check:()=>check(true),clear:()=>localStorage.removeItem(CACHE_KEY)};
window.addEventListener('DOMContentLoaded',()=>{check(false);document.getElementById('checkUpdate')?.addEventListener('click',()=>check(true));setInterval(()=>check(false),6*60*60*1000)});
})();