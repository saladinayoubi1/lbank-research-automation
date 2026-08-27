from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "android" / "lbank-mobile" / "app" / "src" / "main"
ASSETS = ANDROID / "assets"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_mobile_polish_assets_are_loaded_after_canonical_runtime():
    html = read(ASSETS / "index.html")
    assert '<link rel="stylesheet" href="mobile-polish.css">' in html
    assert '<script src="mobile-polish.js" defer></script>' in html
    assert html.index('mobile-core.js') < html.index('mobile-runtime.js') < html.index('mobile-polish.js')


def test_mobile_polish_javascript_syntax():
    node = shutil.which("node")
    if not node:
        return
    subprocess.run([node, "--check", str(ASSETS / "mobile-polish.js")], check=True)


def test_polish_layer_keeps_mobile_navigation_bounded_and_live_non_restorable():
    js = read(ASSETS / "mobile-polish.js")
    assert "new Set(['lab', 'audit', 'live'])" in js
    assert "new Set(['home', 'paper', 'ai', 'mission', 'lab', 'audit'])" in js
    assert "SAFE_RESTORE.has(saved)" in js
    assert "live" not in js.split("const SAFE_RESTORE", 1)[1].split(";", 1)[0]
    assert "fetch(" not in js
    assert "XMLHttpRequest" not in js
    assert "requestPublicMarket" not in js
    assert "requestAiRoom" not in js


def test_polish_layer_has_mobile_safe_touch_navigation_and_offline_state():
    css = read(ASSETS / "mobile-polish.css")
    js = read(ASSETS / "mobile-polish.js")
    assert "--touch:48px" in css
    assert "grid-template-columns:repeat(5,1fr)" in css
    assert "env(safe-area-inset-bottom" in css
    assert "prefers-reduced-motion" in css
    assert "mobile-network-banner" in css
    assert "navigator.onLine" in js
    assert "Live locked" in js


def test_android_delivery_remains_fail_closed_for_remote_authority():
    manifest = read(ANDROID / "AndroidManifest.xml")
    activity = read(ANDROID / "java" / "com" / "saladinayoubi" / "lbankmobile" / "MainActivity.java")
    assert 'android:allowBackup="false"' in manifest
    assert 'android:usesCleartextTraffic="false"' in manifest
    assert 'android:hardwareAccelerated="true"' in manifest
    assert 'android:windowSoftInputMode="adjustResize"' in manifest
    assert '"https".equalsIgnoreCase(base.getProtocol())' in activity
    assert 'payload.optBoolean("live_trading_authority", false)' in activity
    assert 'Remote product attempted to widen Live authority' in activity
    assert 'Only the NEXUS gateway token is accepted by the native bridge' in activity


def test_live_surface_stays_explicitly_locked_without_activation_inputs():
    html = read(ASSETS / "index.html")
    live = html.split('id="screen-live"', 1)[1].split('</section>', 1)[0]
    assert "ترید اصلی قفل است" in live
    assert "Private API Keys" in live
    assert "Order Endpoint" in live
    assert "وجود ندارد" in live
    assert "هیچ دکمه فعال‌سازی" in live
    assert "<input" not in live
