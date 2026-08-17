from __future__ import annotations

import json
from pathlib import Path

ASSETS = Path("android/lbank-mobile/app/src/main/assets")
MAIN_ACTIVITY = Path("android/lbank-mobile/app/src/main/java/com/saladinayoubi/lbankmobile/MainActivity.java")
BUILD_GRADLE = Path("android/lbank-mobile/app/build.gradle")
WORKFLOW = Path(".github/workflows/build_lbank_mobile_apk.yml")


def test_mobile_entrypoint_is_integrated_nexus_product_surface() -> None:
    html = (ASSETS / "index.html").read_text(encoding="utf-8")
    assert 'href="delivery.css"' in html
    assert 'src="mobile-core.js"' in html
    assert 'src="mobile-runtime.js"' in html
    assert 'src="app.js"' not in html
    for surface in (
        "ترید دمو",
        "اتاق هوش مصنوعی",
        "مدیریت عملیات",
        "آزمایشگاه پژوهش",
        "دفتر رویداد و بازپخش",
        "ترید اصلی قفل است",
    ):
        assert surface in html
    assert "Private API Keys" in html
    assert "این صفحه عمداً هیچ دکمه فعال‌سازی یا ورودی credential ندارد" in html


def test_mobile_delivery_css_uses_explicit_readable_font_stack() -> None:
    css = (ASSETS / "delivery.css").read_text(encoding="utf-8")
    assert '"Roboto"' in css
    assert '"Noto Sans Arabic"' in css
    assert "system-ui" not in css
    assert ".bottom-nav" in css
    assert ".risk-preview" in css
    assert ".lock-screen" in css


def test_mobile_runtime_has_real_local_paper_risk_and_audit_controls() -> None:
    runtime = (ASSETS / "mobile-core.js").read_text(encoding="utf-8") + (ASSETS / "mobile-runtime.js").read_text(encoding="utf-8")
    for token in (
        "maxPosition:.20",
        "maxAggregate:.50",
        "maxDailyLoss:.05",
        "maxDrawdown:.10",
        "risk_allowed",
        "kill_switch_enabled",
        "paper_open",
        "paper_close",
        "paper_trading_only:true",
        "event_digest",
        "verifyLedger",
        "sha256(canonical(core))",
        "fee_recorded",
        "slippage_recorded",
        "position_opened",
        "position_closed",
    ):
        assert token in runtime
    assert "executePaper()" in runtime
    assert "local deterministic simulator" not in runtime  # metadata owns this disclosure


def test_ai_room_is_bounded_and_cannot_activate_live_authority() -> None:
    runtime = (ASSETS / "mobile-core.js").read_text(encoding="utf-8") + (ASSETS / "mobile-runtime.js").read_text(encoding="utf-8")
    activity = MAIN_ACTIVITY.read_text(encoding="utf-8")
    assert "requestAiRoom" in runtime
    assert "NexusAiRoomResult" in runtime
    assert "paper_action" in runtime
    assert "فقط staged شد" in runtime
    assert "owner_sensitive" in runtime
    assert "/api/ai-room/message" in activity
    assert "AI_REQUEST_KEYS" in activity
    assert '"session_id", "conversation_id", "turn_id", "message"' in activity
    assert 'put("liveTradingAuthority",false)' in activity


def test_mobile_network_surface_is_public_market_plus_allowlisted_gateway_only() -> None:
    runtime = (ASSETS / "mobile-core.js").read_text(encoding="utf-8") + (ASSETS / "mobile-runtime.js").read_text(encoding="utf-8")
    activity = MAIN_ACTIVITY.read_text(encoding="utf-8")
    assert "requestPublicMarket" in runtime
    assert "https://api.bybit.com" in activity
    assert "/v5/market/kline" in activity
    assert "category=spot" in activity
    assert '"15", "60", "240"' in activity
    assert "/api/mission-control" in activity
    for forbidden in ("/v5/order", "apiKey", "apiSecret", "secretKey", "withdrawalEndpoint"):
        assert forbidden not in runtime
        assert forbidden not in activity


def test_mobile_bundled_metadata_discloses_mirror_and_authority_boundaries() -> None:
    project = json.loads((ASSETS / "data.json").read_text(encoding="utf-8"))["project"]
    assert project["status"] == "complete"
    assert project["phase"] == 6
    assert project["mode"] == "research_backtest_paper"
    assert project["canonical_source"] == "Bybit"
    assert project["deterministic_risk_final_authority"] is True
    assert project["live_trading_authority"] is False
    assert project["profitability_claim"] is False
    assert project["product_version"] == "3.0.0"
    assert project["backend_contracts"]["paper_execution"] == "paper_execution.py"
    assert "local deterministic simulator" in project["mobile_delivery"]["paper_execution"]
    assert "locked" in project["mobile_delivery"]["live"]


def test_mobile_version_and_ci_package_product_build() -> None:
    gradle = BUILD_GRADLE.read_text(encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "versionCode 5" in gradle
    assert 'versionName "3.0.0"' in gradle
    assert "NEXUS_PERSONAL_PRO_3_0_0.apk" in workflow
    assert "versionCode='5' versionName='3.0.0'" in workflow
    assert "assets/mobile-core.js" in workflow
    assert "assets/mobile-runtime.js" in workflow
    assert "اتاق هوش مصنوعی" in workflow
    assert "ترید دمو" in workflow
    assert "ترید اصلی قفل است" in workflow
