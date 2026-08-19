from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "desktop" / "nexus-product" / "main.js"
PRELOAD = ROOT / "desktop" / "nexus-product" / "preload.js"
PACKAGE = ROOT / "desktop" / "nexus-product" / "package.json"
UI = ROOT / "product_ui" / "product.js"
CSS = ROOT / "product_ui" / "product-extra.css"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_windows_uses_native_frame_so_caption_controls_cannot_cover_product_topbar():
    text = read(MAIN)
    assert "frame: true" in text
    assert "titleBarOverlay" not in text
    assert "titleBarStyle: 'hidden'" not in text
    assert "autoHideMenuBar: true" in text
    assert "minWidth: 800" in text
    assert "minHeight: 560" in text


def test_desktop_preferences_bridge_is_narrow_and_keeps_renderer_sandboxed():
    main = read(MAIN)
    preload = read(PRELOAD)
    for marker in (
        "contextIsolation: true",
        "sandbox: true",
        "nodeIntegration: false",
        "webSecurity: true",
        "preload: path.join(__dirname, 'preload.js')",
        "trustedPreferenceSender",
        "nexus:ui-preferences:get",
        "nexus:ui-preferences:set",
        "nexus:ui-preferences:reset",
    ):
        assert marker in main
    assert "contextBridge.exposeInMainWorld('nexusDesktop'" in preload
    assert "ipcRenderer.send(" not in preload
    assert "ipcRenderer.sendSync(" not in preload
    assert "shell" not in preload
    assert "child_process" not in preload


def test_preferences_are_whitelisted_bounded_and_local_to_user_data():
    text = read(MAIN)
    for marker in (
        "app.getPath('userData')",
        "nexus.ui-preferences.v1",
        "fontFamily: 'system'",
        "fontSize: 14",
        "uiScale: 1",
        "windowPreset: 'auto'",
        "Math.min(19, Math.max(12",
        "Math.min(1.4, Math.max(0.8",
        "fontFamily: new Set(['system', 'tahoma', 'arial', 'mono'])",
        "windowPreset: new Set(['auto', 'compact', 'standard', 'large', 'maximize'])",
    ):
        assert marker in text
    assert "process.env" not in text[text.index("function saveUiPreferences"):text.index("function writeSupervisorState")]


def test_window_resolution_presets_are_bounded_to_real_work_area():
    text = read(MAIN)
    for marker in (
        "screen.getPrimaryDisplay()?.workAreaSize",
        "screen.getDisplayMatching(win.getBounds())",
        "compact: { width: 1024, height: 700 }",
        "standard: { width: 1280, height: 800 }",
        "large: { width: 1480, height: 920 }",
        "Math.min(requested.width, availableWidth)",
        "Math.min(requested.height, availableHeight)",
    ):
        assert marker in text


def test_product_exposes_visual_only_personalization_controls():
    text = read(UI)
    for marker in (
        "settings:['NEXUS / SETTINGS','تنظیمات و شخصی‌سازی']",
        "فونت رابط",
        "مقیاس رابط / Resolution Scale",
        "تراکم رابط",
        "قاب پنل‌ها",
        "رنگ اصلی",
        "کنتراست",
        "منوی کناری پیش‌فرض",
        "حرکت و انیمیشن",
        "اندازه پنجره",
        "بازگشت به پیش‌فرض",
        "VISUAL ONLY",
        "Risk، Paper authority، Live/L4",
    ):
        assert marker in text
    settings_logic = text[text.index("function ensureSettingsSurface"):text.index("function renderOverview")]
    assert "api(" not in settings_logic
    assert "/api/" not in settings_logic
    assert "fetch(" not in settings_logic


def test_personalization_supports_safe_fonts_scale_themes_frames_and_reduced_motion():
    js = read(UI)
    css = read(CSS)
    for marker in (
        "UI_FONT_STACKS",
        "UI_ACCENTS",
        "UI_THEMES",
        "fontFamily:'system'",
        "uiScale:1",
        "frameStyle:'soft'",
        "motion:'full'",
        "window.nexusDesktop?.setPreferences",
        "window.nexusDesktop?.resetPreferences",
    ):
        assert marker in js
    for marker in (
        '.settings-layout',
        'body[data-frame-style="sharp"]',
        'body[data-frame-style="soft"]',
        'body[data-frame-style="rounded"]',
        'body[data-density="compact"]',
        'body[data-density="spacious"]',
        'body[data-contrast="high"]',
        'body[data-motion="reduced"]',
        '@media(max-width:900px)',
    ):
        assert marker in css


def test_next_windows_package_contains_preload_and_is_versioned_5_1():
    text = read(PACKAGE)
    assert '"version": "5.1.0"' in text
    assert '"preload.js"' in text
    assert '"main": "bootstrap-main.js"' in text
    assert 'electron-builder --win nsis portable' in text
