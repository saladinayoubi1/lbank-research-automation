from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "product_ui" / "product-extra.css"
INDEX = ROOT / "product_ui" / "index.html"


def test_navigation_polish_preserves_existing_extra_styles():
    text = CSS.read_text(encoding="utf-8")
    assert ".settings-layout" in text
    assert "NEXUS readability floor" in text
    assert "research-layout" in text
    assert "@import" not in text


def test_sidebar_is_vertically_scrollable_without_page_runtime_changes():
    text = CSS.read_text(encoding="utf-8")
    assert ".sidebar nav{flex:1;min-height:0;overflow-y:auto;overflow-x:hidden" in text
    assert "overscroll-behavior:contain" in text
    assert ".side-foot{flex:0 0 auto}" in text


def test_nav_uses_semantic_icon_glyphs_in_dom_and_no_numeric_labels():
    html = INDEX.read_text(encoding="utf-8")
    icons = {
        "overview": "⌂",
        "data": "▦",
        "research": "∑",
        "paper": "↗",
        "risk": "◆",
        "ai": "✦",
        "strategies": "⎇",
        "agents": "⚙",
        "audit": "◎",
        "live": "⊘",
    }
    for view, glyph in icons.items():
        assert f'data-view="{view}"' in html
        assert f'<span class="nav-icon" aria-hidden="true">{glyph}</span>' in html
    for label in ("01","02","03","04","05","06","07","08","09","10"):
        assert f'<span>{label}</span>' not in html


def test_css_keeps_semantic_icon_projection_and_hides_legacy_number_text():
    text = CSS.read_text(encoding="utf-8")
    for view in ("overview","data","research","paper","risk","ai","strategies","agents","audit","live"):
        assert f'button[data-view="{view}"]>span::before' in text
    assert "font-size:0!important" in text


def test_refresh_and_sidebar_toggle_visual_order_is_swapped_only_in_css():
    css = CSS.read_text(encoding="utf-8")
    html = INDEX.read_text(encoding="utf-8")
    assert ".topbar>.top-status{display:contents}" in css
    assert "#reload{order:0}" in css
    assert "#sidebarToggle{order:3}" in css
    assert 'id="reload"' in html and 'id="sidebarToggle"' in html


def test_dynamic_settings_nav_uses_semantic_icon_and_preserves_live_lock_icon():
    js = (ROOT / "product_ui" / "product.js").read_text(encoding="utf-8")
    assert 'button.innerHTML=\'<span class="nav-icon" aria-hidden="true">☼</span><b>تنظیمات</b><small>Personalize</small>\'' in js
    assert "n.textContent='11'" not in js
    assert "if(live)nav.insertBefore(button,live)" in js
    assert "<span>10</span><b>تنظیمات</b>" not in js


def test_negative_status_semantics_take_precedence_over_positive_substrings():
    js = (ROOT / "product_ui" / "product.js").read_text(encoding="utf-8")
    status = js[js.index("function statusClass"):js.index("function normalizeUIPreferences")]
    assert status.index("unavailable") < status.index("available|active")
    assert "quarantined" in status
    assert "?'bad':" in status


def test_product_actions_are_single_flight():
    js = (ROOT / "product_ui" / "product.js").read_text(encoding="utf-8")
    assert "const inFlightActions=new Set()" in js
    assert "async function singleFlight(" in js
    assert "singleFlight('paper-order'" in js
    assert "singleFlight('research-run'" in js
    assert "singleFlight('auto-paper'" in js
    assert "control.disabled=true" in js
    assert "control.disabled=false" in js
    assert "aria-busy" in js


def test_optional_product_surfaces_degrade_without_hiding_critical_failures():
    js = (ROOT / "product_ui" / "product.js").read_text(encoding="utf-8")
    assert "async function optionalApi(path)" in js
    assert "api('/api/product/overview')" in js
    assert "api('/api/product/paper')" in js
    assert "api('/api/product/risk')" in js
    assert "api('/api/product/recovery')" in js
    assert "optionalApi('/api/product/mission-control')" in js
    assert "optionalApi('/api/product/notifications?limit=40')" in js
    assert "optionalApi('/api/product/data/registry')" in js
    assert "بخش محدود" in js
    assert "Paper backend unavailable" in js


def test_paper_ui_auto_refresh_is_lightweight_and_visibility_aware():
    js = (ROOT / "product_ui" / "product.js").read_text(encoding="utf-8")
    assert "PAPER_UI_REFRESH_INTERVAL_MS=60*1000" in js
    assert "async function refreshPaperSnapshot()" in js
    assert "document.visibilityState!=='visible'" in js
    assert "singleFlight('paper-ui-refresh'" in js
    assert "state.paper=await api('/api/product/paper')" in js
    assert "function startPaperUiAutoRefresh()" in js
    assert "visibilitychange" in js
    assert "await loadAll();startPaperUiAutoRefresh()" in js


def test_manual_paper_ticket_has_no_fake_price_defaults():
    html = INDEX.read_text(encoding="utf-8")
    for fake in ('value="60000"', 'value="59000"', 'value="62000"'):
        assert fake not in html
    for name in ("quantity", "reference_price", "stop_price", "target_price"):
        marker = f'name="{name}"'
        start = html.index(marker)
        tag = html[html.rfind("<input", 0, start):html.index(">", start) + 1]
        assert "required" in tag
        assert 'autocomplete="off"' in tag


def test_laptop_professional_polish_removes_visible_prototype_artifacts():
    html = INDEX.read_text(encoding="utf-8")
    offline = (ROOT / "product_ui" / "product-offline.js").read_text(encoding="utf-8")
    mission = (ROOT / "product_ui" / "product-mission.js").read_text(encoding="utf-8")
    mission_css = (ROOT / "product_ui" / "product-mission.css").read_text(encoding="utf-8")
    extra = CSS.read_text(encoding="utf-8")

    assert '<b id="buildLabel">5.1.0</b>' in html
    assert "NEXUS Personal Pro 5.1.0 - Offline-first" in offline
    assert "5.1.0 · Offline-first" not in offline
    assert "Runtime state not present on this laptop" not in mission
    assert "Mission runtime snapshot not loaded" in mission
    assert "NO MISSION SNAPSHOT" in mission
    assert "mission-resource-pill" in mission
    assert ".mission-resource-stack" in mission_css
    assert "@media(max-width:1400px){.mission-now{grid-template-columns:repeat(3" in mission_css
    assert ".pipeline{display:grid!important" in extra
    assert ".pipeline>em{display:none!important}" in extra


def test_backend_freshness_becomes_visible_after_repeated_passive_failures():
    html = INDEX.read_text(encoding="utf-8")
    js = (ROOT / "product_ui" / "product.js").read_text(encoding="utf-8")
    assert 'id="gatewayState"' in html and 'aria-live="polite"' in html
    assert 'id="reload"' in html and 'aria-label="بروزرسانی وضعیت"' in html
    assert "PAPER_UI_STALE_FAILURE_LIMIT=2" in js
    assert "paperUiRefreshFailures=0" in js
    assert "function markGatewayHealthy(" in js
    assert "paperUiRefreshFailures+=1" in js
    assert "Backend stale" in js
    assert "lastGatewayHealthyAt.toLocaleTimeString('fa-IR')" in js


def test_clean_mission_idle_does_not_render_false_local_node_failure():
    js = (ROOT / "product_ui" / "product.js").read_text(encoding="utf-8")
    assert "m.projection==='clean_install_idle'" in js
    assert "m.data?.runtime_report_present===false" in js
    assert "runtime report not generated" in js
    assert "به معنی خرابی Local Runner یا Supervisor نیست" in js
    idle_start = js.index("if(m.projection==='clean_install_idle'")
    normal_start = js.index("const q=m.queue||{}", idle_start)
    idle_block = js[idle_start:normal_start]
    assert "local_node" not in idle_block


def test_status_badges_do_not_greenwash_negative_compound_states():
    js = (ROOT / "product_ui" / "product.js").read_text(encoding="utf-8")
    assert "const bad=['locked','unavailable','not_available','inactive','not_active','disabled','offline'" in js
    assert "'unverified','not_ready','not_executed','stale'" in js
    assert "const good=['available','active','complete','completed','ready','pass','passed','paper','verified','candidate','executed','success','healthy']" in js
    assert "value.startsWith(token+'_')" in js
    assert "value.endsWith('_'+token)" in js
    assert "bad.some(" in js and "good.some(" in js
