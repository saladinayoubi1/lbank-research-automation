'use strict';
(() => {
  const q = s => document.querySelector(s);
  const qa = s => [...document.querySelectorAll(s)];
  const SECONDARY = new Set(['lab','audit','live']);
  const SAFE = new Set(['home','paper','mission','ai','more','lab','audit']);
  const LAST = 'nexus-mobile-v4-last-screen';
  let previousScreen = 'home';
  let installed = false;
  let handlingPopState = false;

  function activeScreen(){ return q('.screen.active')?.dataset.screen || 'home'; }
  function remember(name){ if (SAFE.has(name)) localStorage.setItem(LAST,name); }
  function pushHistory(name){
    if (handlingPopState || history.state?.screen === name) return;
    history.pushState({screen:name},'',`#${name}`);
  }
  function openScreen(name,{historyMode='push'}={}){
    if (typeof go !== 'function' || !q(`[data-screen="${name}"]`)) return;
    const current = activeScreen();
    if (current !== name) previousScreen = current;
    go(name); remember(name);
    if (historyMode === 'push') pushHistory(name);
    if (historyMode === 'replace') history.replaceState({screen:name},'',`#${name}`);
    syncSecondaryNav(); requestAnimationFrame(refreshVisuals);
  }

  function installQuickNavigation(){
    history.replaceState({screen:'home'},'','#home');
    qa('[data-open-screen]').forEach(button => button.addEventListener('click', () => openScreen(button.dataset.openScreen)));
    qa('[data-go]').forEach(button => button.addEventListener('click', () => {
      const name = button.dataset.go; remember(name); pushHistory(name); window.setTimeout(syncSecondaryNav,0);
    }));
    window.addEventListener('popstate',event=>{
      const name=event.state?.screen||'home';
      if(!q(`[data-screen="${name}"]`)||typeof go!=='function')return;
      handlingPopState=true;go(name);remember(name);syncSecondaryNav();requestAnimationFrame(refreshVisuals);handlingPopState=false;
    });
    const saved = localStorage.getItem(LAST);
    if (saved && saved !== 'home' && SAFE.has(saved)) window.setTimeout(() => openScreen(saved,{historyMode:'replace'}),50);
  }

  function syncSecondaryNav(){
    const name = activeScreen();
    const more = q('.v4-nav [data-go="more"]');
    if (more) more.classList.toggle('secondary-active', SECONDARY.has(name));
  }

  function installAiSuggestions(){
    qa('[data-ai-prompt]').forEach(button => button.addEventListener('click', () => {
      const input = q('#aiInput'); if (!input) return; input.value = button.dataset.aiPrompt || ''; input.focus();
    }));
  }

  function installBusyFeedback(){
    ['refreshMarket','syncMission','aiSend','runPreview','previewRisk','executePaper','verifyLedger'].forEach(id => {
      const button=q('#'+id); if(!button) return;
      button.addEventListener('click',()=>{button.classList.add('busy');window.setTimeout(()=>button.classList.remove('busy'),['syncMission','aiSend'].includes(id)?1800:850);});
    });
  }

  function chartSvg(values){
    if (!Array.isArray(values) || values.length < 3) return '<div class="chart-empty">داده کافی برای نمودار وجود ندارد</div>';
    const w=1000,h=310,pad=16,min=Math.min(...values),max=Math.max(...values),range=max-min||1;
    const pts=values.map((v,i)=>[pad+(i/(values.length-1))*(w-pad*2),pad+(1-(v-min)/range)*(h-pad*2)]);
    const path=pts.map((p,i)=>(i?'L':'M')+p[0].toFixed(2)+' '+p[1].toFixed(2)).join(' ');
    const area=path+` L ${pts.at(-1)[0].toFixed(2)} ${h} L ${pts[0][0].toFixed(2)} ${h} Z`,last=pts.at(-1);
    const grid=[.25,.5,.75].map(y=>`<line x1="0" y1="${(h*y).toFixed(1)}" x2="${w}" y2="${(h*y).toFixed(1)}"/>`).join('');
    return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="نمودار کندل‌های بسته"><defs><linearGradient id="v4Area" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#75a7ff" stop-opacity=".26"/><stop offset="1" stop-color="#75a7ff" stop-opacity="0"/></linearGradient></defs><g class="chart-grid">${grid}</g><path class="chart-area" d="${area}"/><path class="chart-line" d="${path}"/><circle class="chart-dot" cx="${last[0].toFixed(2)}" cy="${last[1].toFixed(2)}" r="5"/></svg>`;
  }

  function renderChart(){
    const root=q('#proChart'); if(!root) return;
    try{const m=typeof market==='function'?market():null,candles=m?.candles;if(!candles?.length){root.innerHTML='<div class="chart-empty">نمودار پس از دریافت بازار نمایش داده می‌شود</div>';return;}root.innerHTML=chartSvg(candles.slice(-72).map(c=>Number(c.c)).filter(Number.isFinite));}
    catch{root.innerHTML='<div class="chart-empty">Market chart unavailable</div>';}
  }

  function setPulse(name,status,label){
    const node=q(`[data-pulse="${name}"]`); if(!node)return;node.classList.remove('ready','bad');if(status==='ready')node.classList.add('ready');if(status==='bad')node.classList.add('bad');const b=node.querySelector('b');if(b)b.textContent=label;
  }
  function renderPulse(){
    let marketOk=false,paperOk=false,riskOk=false,auditOk=false;
    try{marketOk=marketState==='ready';paperOk=!!state.paper.sessionOpen;riskOk=!state.paper.killSwitch;auditOk=verifyLedger().ok}catch{}
    setPulse('market',marketOk?'ready':'wait',marketOk?'ONLINE':'SYNC');setPulse('paper',paperOk?'ready':'wait',paperOk?'OPEN':'CLOSED');setPulse('risk',riskOk?'ready':'bad',riskOk?'READY':'KILL');setPulse('audit',auditOk?'ready':'bad',auditOk?'VERIFIED':'CHECK');
    const scoreNode=q('#systemPulseScore');if(scoreNode)scoreNode.textContent=`${[marketOk,paperOk,riskOk,auditOk].filter(Boolean).length}/4 READY`;
  }

  function renderPortfolioArc(){
    const arc=q('#portfolioArc');if(!arc)return;
    try{const eq=Number(equity()),opening=Number(state.paper.openingCash)||1,ratio=Math.max(8,Math.min(100,(eq/opening)*70));arc.style.setProperty('--arc',ratio.toFixed(1)+'%');const label=arc.querySelector('span');if(label)label.textContent=(eq/opening*100).toFixed(0)+'%';const move=q('#portfolioMove');if(move){const p=((eq-opening)/opening)*100;move.textContent=`${p>=0?'+':''}${p.toFixed(2)}% FROM OPENING CASH`;move.className=p>=0?'up':'down';}}
    catch{}
  }
  function refreshVisuals(){renderChart();renderPulse();renderPortfolioArc();syncSecondaryNav();}

  function installObservers(){
    const marketBox=q('#marketHero');if(marketBox)new MutationObserver(()=>requestAnimationFrame(refreshVisuals)).observe(marketBox,{childList:true,subtree:true,characterData:true});
    const paper=q('#screen-paper');if(paper)new MutationObserver(()=>requestAnimationFrame(renderPortfolioArc)).observe(paper,{childList:true,subtree:true,characterData:true});
    const main=q('#appMain');if(main)new MutationObserver(syncSecondaryNav).observe(main,{attributes:true,subtree:true,attributeFilter:['class']});
    window.addEventListener('online',refreshVisuals);window.addEventListener('offline',refreshVisuals);
  }

  function installNetworkBanner(){
    if(q('#v4NetworkBanner'))return;const banner=document.createElement('div');banner.id='v4NetworkBanner';banner.setAttribute('role','status');
    Object.assign(banner.style,{position:'fixed',left:'14px',right:'14px',top:'72px',zIndex:'80',padding:'9px 12px',borderRadius:'12px',fontSize:'9px',textAlign:'center',background:'#4a2228',color:'#ffdce0',border:'1px solid #7a3842',display:'none'});
    banner.textContent='اینترنت قطع است · Paper/Audit محلی قابل مشاهده است · Live همچنان قفل است';document.body.appendChild(banner);const sync=()=>banner.style.display=navigator.onLine?'none':'block';window.addEventListener('online',sync);window.addEventListener('offline',sync);sync();
  }

  function installResumeRefresh(){
    let hiddenAt=0;document.addEventListener('visibilitychange',()=>{if(document.hidden){hiddenAt=Date.now();return;}if(hiddenAt&&Date.now()-hiddenAt>180000&&navigator.onLine)q('#refreshMarket')?.click();hiddenAt=0;refreshVisuals();});
  }

  window.NexusMobileBack=()=>{if(activeScreen()==='home')return false;history.back();return true;};

  function install(){
    if(installed)return;installed=true;document.documentElement.dataset.mobileRedesign='v4';installQuickNavigation();installAiSuggestions();installBusyFeedback();installObservers();installNetworkBanner();installResumeRefresh();window.setTimeout(refreshVisuals,120);
  }
  window.addEventListener('DOMContentLoaded',install);
})();
