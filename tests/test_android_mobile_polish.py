from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "android" / "lbank-mobile" / "app" / "src" / "main"
ASSETS = ANDROID / "assets"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_android_v4_assets_are_loaded_after_product_runtime():
    html = read(ASSETS / "index.html")
    assert '<link rel="stylesheet" href="mobile-redesign.css">' in html
    assert '<script src="mobile-redesign.js" defer></script>' in html
    assert "mobile-polish.css" not in html
    assert "mobile-polish.js" not in html
    assert html.index("mobile-core.js") < html.index("mobile-runtime.js") < html.index("mobile-redesign.js")


def test_android_v4_javascript_syntax():
    node = shutil.which("node")
    if not node:
        return
    subprocess.run([node, "--check", str(ASSETS / "mobile-redesign.js")], check=True)


def test_android_v4_navigation_is_mobile_bounded_and_live_is_not_restored():
    html = read(ASSETS / "index.html")
    js = read(ASSETS / "mobile-redesign.js")
    primary_nav = html.split('<nav class="bottom-nav v4-nav"', 1)[1].split("</nav>", 1)[0]

    assert "new Set(['lab','audit','live'])" in js
    assert "new Set(['home','paper','mission','ai','more','lab','audit'])" in js
    safe_literal = js.split("const SAFE", 1)[1].split(";", 1)[0]
    assert "live" not in safe_literal
    for destination in ("home", "paper", "mission", "ai", "more"):
        assert f'data-go="{destination}"' in primary_nav
    for specialist in ("lab", "audit", "live"):
        assert f'data-go="{specialist}"' not in primary_nav
    assert "history.pushState" in js
    assert "popstate" in js
    assert "NexusMobileBack" in js
    assert "fetch(" not in js
    assert "XMLHttpRequest" not in js
    assert "requestPublicMarket" not in js
    assert "requestAiRoom" not in js


def test_android_v4_has_safe_area_large_primary_targets_and_offline_state():
    css = read(ASSETS / "mobile-redesign.css")
    js = read(ASSETS / "mobile-redesign.js")
    assert "grid-template-columns:repeat(5,1fr)" in css
    assert "env(safe-area-inset-bottom" in css
    assert "min-height:52px" in css
    assert "min-height:50px" in css
    assert "navigator.onLine" in js
    assert "اینترنت قطع است" in js
    assert "Live همچنان قفل است" in js


def test_android_v4_is_structural_cockpit_not_a_polish_overlay():
    html = read(ASSETS / "index.html")
    css = read(ASSETS / "mobile-redesign.css")
    js = read(ASSETS / "mobile-redesign.js")
    assert 'data-nexus-mobile="4"' in html
    assert 'id="proChart"' in html
    assert 'id="systemPulse"' in html
    assert 'id="portfolioArc"' in html
    assert 'id="screen-more"' in html
    assert "Paper Portfolio" in html
    assert "NEXUS AI" in html
    for selector in (".market-cockpit", ".kpi-strip", ".pulse-grid", ".portfolio-balance", ".v4-chat", ".v4-nav"):
        assert selector in css
    for function_name in ("chartSvg", "renderPulse", "renderPortfolioArc"):
        assert function_name in js


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
