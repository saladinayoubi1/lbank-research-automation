'use strict';
(() => {
  const q = s => document.querySelector(s);
  const qa = s => [...document.querySelectorAll(s)];
  const LAST_SCREEN = 'nexus-mobile-last-screen-v1';
  const SECONDARY = new Set(['lab', 'audit', 'live']);
  const SAFE_RESTORE = new Set(['home', 'paper', 'ai', 'mission', 'lab', 'audit']);

  function activeScreen() {
    return q('.screen.active')?.dataset.screen || 'home';
  }

  function clickScreen(name) {
    const button = q(`[data-go="${name}"]`);
    if (button) button.click();
  }

  function installStatusStrip() {
    const hero = q('#screen-home .hero');
    if (!hero || q('#mobileStatusStrip')) return;
    const strip = document.createElement('div');
    strip.id = 'mobileStatusStrip';
    strip.className = 'mobile-status-strip';
    strip.innerHTML = '<span class="mobile-status-dot" aria-hidden="true"></span><div><strong id="mobileStatusTitle">NEXUS آماده‌سازی</strong><div id="mobileStatusMeta">Paper-only · Live locked</div></div><span id="mobileStatusClock">—</span>';
    hero.before(strip);

    const badge = q('#marketBadge');
    const update = () => {
      const online = navigator.onLine;
      const marketOnline = badge?.textContent?.includes('ONLINE');
      strip.classList.toggle('online', online && marketOnline);
      strip.classList.toggle('offline', !online);
      q('#mobileStatusTitle').textContent = !online ? 'اتصال اینترنت قطع است' : marketOnline ? 'Market + Paper آماده' : 'در حال همگام‌سازی بازار';
      q('#mobileStatusMeta').textContent = 'Research · Risk · Paper · Live locked';
      q('#mobileStatusClock').textContent = new Intl.DateTimeFormat('fa-IR', {hour:'2-digit', minute:'2-digit'}).format(new Date());
    };
    if (badge) new MutationObserver(update).observe(badge, {childList:true, characterData:true, subtree:true, attributes:true});
    window.addEventListener('online', update);
    window.addEventListener('offline', update);
    setInterval(update, 60000);
    update();
  }

  function installQuickActions() {
    const home = q('#screen-home');
    const stats = home?.querySelector('.stat-grid');
    if (!home || !stats || q('#mobileQuickActions')) return;
    const box = document.createElement('div');
    box.id = 'mobileQuickActions';
    box.className = 'mobile-quick-actions';
    box.innerHTML = [
      ['paper','↕','Paper','دمو + Risk'],
      ['mission','◎','Mission','وضعیت سیستم'],
      ['ai','✦','AI Room','Ops bounded']
    ].map(([go, icon, title, sub]) => `<button type="button" data-mobile-go="${go}"><b>${icon} ${title}</b><span>${sub}</span></button>`).join('');
    stats.after(box);
    box.addEventListener('click', e => {
      const button = e.target.closest('[data-mobile-go]');
      if (button) clickScreen(button.dataset.mobileGo);
    });
  }

  function installCompactNavigation() {
    const nav = q('.bottom-nav');
    if (!nav || q('#mobileMore')) return;
    const secondaryButtons = [...nav.querySelectorAll('[data-go]')].filter(b => SECONDARY.has(b.dataset.go));
    const sheet = document.createElement('div');
    sheet.id = 'mobileMoreSheet';
    sheet.className = 'mobile-more-sheet';
    sheet.setAttribute('role','dialog');
    sheet.setAttribute('aria-label','ابزارهای بیشتر NEXUS');
    secondaryButtons.forEach(button => {
      button.classList.toggle('locked-entry', button.dataset.go === 'live');
      sheet.appendChild(button);
    });
    document.body.appendChild(sheet);

    const more = document.createElement('button');
    more.id = 'mobileMore';
    more.type = 'button';
    more.setAttribute('aria-label','بخش‌های بیشتر');
    more.setAttribute('aria-expanded','false');
    more.innerHTML = '<span>•••</span><b>بیشتر</b>';
    nav.appendChild(more);

    const close = () => { sheet.classList.remove('open'); more.setAttribute('aria-expanded','false'); };
    more.addEventListener('click', () => {
      const next = !sheet.classList.contains('open');
      sheet.classList.toggle('open', next);
      more.setAttribute('aria-expanded', String(next));
    });
    sheet.addEventListener('click', e => { if (e.target.closest('[data-go]')) close(); });
    document.addEventListener('click', e => {
      if (sheet.classList.contains('open') && !sheet.contains(e.target) && !more.contains(e.target)) close();
    });

    function sync() {
      const screen = activeScreen();
      more.classList.toggle('active', SECONDARY.has(screen));
      qa('.bottom-nav [data-go]').forEach(button => button.setAttribute('aria-current', button.dataset.go === screen ? 'page' : 'false'));
    }
    new MutationObserver(sync).observe(q('main'), {attributes:true, subtree:true, attributeFilter:['class']});
    sync();
  }

  function installBackButton() {
    const actions = q('.top-actions');
    if (!actions || q('#mobileBack')) return;
    const back = document.createElement('button');
    back.id = 'mobileBack';
    back.type = 'button';
    back.className = 'mobile-back';
    back.setAttribute('aria-label','بازگشت به خانه');
    back.textContent = '‹';
    actions.prepend(back);
    back.addEventListener('click', () => clickScreen('home'));

    function sync() {
      const screen = activeScreen();
      back.classList.toggle('visible', screen !== 'home');
      if (SAFE_RESTORE.has(screen)) localStorage.setItem(LAST_SCREEN, screen);
    }
    new MutationObserver(sync).observe(q('main'), {attributes:true, subtree:true, attributeFilter:['class']});
    sync();
  }

  function installNetworkBanner() {
    if (q('#mobileNetworkBanner')) return;
    const banner = document.createElement('div');
    banner.id = 'mobileNetworkBanner';
    banner.className = 'mobile-network-banner';
    banner.setAttribute('role','status');
    banner.textContent = 'اینترنت قطع است؛ NEXUS در حالت محلی Paper/Audit ادامه می‌دهد و Live همچنان قفل است.';
    document.body.appendChild(banner);
    const sync = () => banner.classList.toggle('show', !navigator.onLine);
    window.addEventListener('online', sync);
    window.addEventListener('offline', sync);
    sync();
  }

  function installBusyFeedback() {
    const ids = ['refreshMarket','syncMission','aiSend','runPreview','previewRisk','executePaper','verifyLedger'];
    ids.forEach(id => {
      const button = q('#'+id);
      if (!button) return;
      button.addEventListener('click', () => {
        button.classList.add('busy');
        window.setTimeout(() => button.classList.remove('busy'), id === 'syncMission' || id === 'aiSend' ? 1800 : 700);
      });
    });
  }

  function installScreenPersistence() {
    qa('[data-go]').forEach(button => button.addEventListener('click', () => {
      const name = button.dataset.go;
      if (SAFE_RESTORE.has(name)) localStorage.setItem(LAST_SCREEN, name);
      q('main')?.scrollTo?.({top:0, behavior:'auto'});
      window.scrollTo({top:0, behavior:'auto'});
    }));
    const saved = localStorage.getItem(LAST_SCREEN);
    if (saved && saved !== 'home' && SAFE_RESTORE.has(saved)) window.setTimeout(() => clickScreen(saved), 0);
  }

  function installResumeRefresh() {
    let hiddenAt = 0;
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) { hiddenAt = Date.now(); return; }
      if (hiddenAt && Date.now() - hiddenAt > 5 * 60 * 1000 && navigator.onLine) q('#refreshMarket')?.click();
      hiddenAt = 0;
    });
  }

  installStatusStrip();
  installQuickActions();
  installCompactNavigation();
  installBackButton();
  installNetworkBanner();
  installBusyFeedback();
  installScreenPersistence();
  installResumeRefresh();
  document.documentElement.dataset.mobilePolish = 'v1';
})();
