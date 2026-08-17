from __future__ import annotations

import json
from pathlib import Path


ASSETS = Path("android/lbank-mobile/app/src/main/assets")
MAIN_ACTIVITY = Path(
    "android/lbank-mobile/app/src/main/java/com/saladinayoubi/lbankmobile/MainActivity.java"
)
BUILD_GRADLE = Path("android/lbank-mobile/app/build.gradle")


def test_mobile_entrypoint_uses_result_first_runtime() -> None:
    html = (ASSETS / "index.html").read_text(encoding="utf-8")
    assert 'href="delivery.css"' in html
    assert 'src="mobile-runtime.js"' in html
    assert 'src="app.js"' not in html
    assert 'src="bootstrap.js"' not in html
    assert "نتیجه نهایی پروژه" in html
    assert "Research / Paper" in html
    assert "PAPER ONLY" in html


def test_mobile_delivery_css_uses_explicit_readable_font_stack() -> None:
    css = (ASSETS / "delivery.css").read_text(encoding="utf-8")
    assert '"Roboto"' in css
    assert '"Noto Sans Arabic"' in css
    assert "system-ui" not in css


def test_mobile_runtime_only_requests_public_read_only_market_data() -> None:
    runtime = (ASSETS / "mobile-runtime.js").read_text(encoding="utf-8")
    activity = MAIN_ACTIVITY.read_text(encoding="utf-8")
    assert "requestPublicMarket" in runtime
    assert "requestPublicMarket" in activity
    assert "https://api.bybit.com" in activity
    assert "/v5/market/kline" in activity
    assert "category=spot" in activity
    assert '"15", "60", "240"' in activity
    assert "c.t+step<=now" in runtime
    assert "/v5/order" not in runtime
    assert "/v5/order" not in activity
    assert "apiKey" not in activity
    assert "apiSecret" not in activity


def test_mobile_bundled_result_metadata_is_truthful_and_fail_closed() -> None:
    payload = json.loads((ASSETS / "data.json").read_text(encoding="utf-8"))
    project = payload["project"]
    assert project["status"] == "complete"
    assert project["phase"] == 6
    assert project["mode"] == "research_backtest_paper"
    assert project["canonical_source"] == "Bybit"
    assert project["deterministic_risk_final_authority"] is True
    assert project["live_trading_authority"] is False
    assert project["profitability_claim"] is False
    assert payload["series"] == []


def test_mobile_version_is_bumped_for_installable_update() -> None:
    gradle = BUILD_GRADLE.read_text(encoding="utf-8")
    assert 'versionCode 4' in gradle
    assert 'versionName "2.2.0"' in gradle
