from __future__ import annotations

import json
from pathlib import Path

ASSETS = Path("android/lbank-mobile/app/src/main/assets")
MAIN_ACTIVITY = Path("android/lbank-mobile/app/src/main/java/com/saladinayoubi/lbankmobile/MainActivity.java")
BUILD_GRADLE = Path("android/lbank-mobile/app/build.gradle")
WORKFLOW = Path(".github/workflows/build_lbank_mobile_apk.yml")


def test_mobile_entrypoint_keeps_full_nexus_product_surface() -> None:
    html = (ASSETS / "index.html").read_text(encoding="utf-8")
    assert 'href="delivery.css"' in html
    assert 'src="mobile-core.js"' in html
    assert 'src="mobile-runtime.js"' in html
    assert 'src="app.js"' not in html
    for surface in (
        "ترید دمو", "اتاق هوش مصنوعی", "مدیریت عملیات", "آزمایشگاه پژوهش",
        "دفتر رویداد و بازپخش", "ترید اصلی قفل است",
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


def test_mobile_retains_local_paper_risk_fallback_but_labels_it_explicitly() -> None:
    local_runtime = (ASSETS / "mobile-core.js").read_text(encoding="utf-8") + (ASSETS / "mobile-runtime.js").read_text(encoding="utf-8")
    canonical = (ASSETS / "mobile-canonical-client.js").read_text(encoding="utf-8")
    for token in (
        "maxPosition:.20", "maxAggregate:.50", "maxDailyLoss:.05", "maxDrawdown:.10",
        "risk_allowed", "kill_switch_enabled", "paper_trading_only:true", "event_digest",
        "verifyLedger", "sha256(canonical(core))", "fee_recorded", "slippage_recorded",
        "position_opened", "position_closed",
    ):
        assert token in local_runtime
    assert "LOCAL FALLBACK" in canonical
    assert "CANONICAL BACKEND" in canonical
    assert "canonical.connected" in canonical
    assert "Mission unsynced" in canonical


def test_android_prefers_bounded_canonical_product_backend_when_connected() -> None:
    activity = MAIN_ACTIVITY.read_text(encoding="utf-8")
    client = (ASSETS / "mobile-canonical-client.js").read_text(encoding="utf-8")
    assert "requestProduct" in activity
    assert "NexusProductResult" in activity
    assert "PRODUCT_GET_PATHS" in activity
    assert "PRODUCT_POST_PATHS" in activity
    for route in (
        "/api/product/overview", "/api/product/paper", "/api/product/paper/events",
        "/api/product/strategies", "/api/product/mission/full", "/api/product/live", "/api/product/data/registry",
        "/api/product/research/last", "/api/product/risk", "/api/product/recovery",
        "/api/product/notifications", "/api/product/paper/order", "/api/product/paper/auto",
        "/api/product/research/run", "/api/product/session", "/api/product/kill-switch",
    ):
        assert route in activity
    for route in (
        "/api/product/overview", "/api/product/paper", "/api/product/risk",
        "/api/product/recovery", "/api/product/data/registry", "/api/product/research/run",
        "/api/product/paper/order", "/api/product/session", "/api/product/kill-switch",
        "/api/product/mission/full",
    ):
        assert route in client
    assert "document.addEventListener('click',intercept,true)" in client
    assert "Mission + Paper → backend" in client


def test_android_mission_control_uses_real_backend_contract_and_never_fabricates_unsynced_state() -> None:
    activity = MAIN_ACTIVITY.read_text(encoding="utf-8")
    client = (ASSETS / "mobile-canonical-client.js").read_text(encoding="utf-8")
    assert '"/api/product/mission/full"' in activity
    assert "/api/product/mission/full" in client
    for marker in (
        "MISSION UNSYNCED", "OWNER ACTION", "LEADING STRATEGY", "CI / EXACT HEAD",
        "owner_actions", "strategy_center", "ci_health", "snapshot_age_seconds",
        "local_supervisor", "build_evidence", "dispatch_transport", "heartbeat_at",
    ):
        assert marker in client
    assert "/api/product/mission/import" not in activity
    assert "/api/product/mission/import" not in client
    assert "هیچ Task/Agent/CI state ساختگی نمایش داده نمی‌شود" in client


def test_android_product_bridge_is_https_origin_bounded_and_fail_closed() -> None:
    activity = MAIN_ACTIVITY.read_text(encoding="utf-8")
    assert '"https".equalsIgnoreCase(base.getProtocol())' in activity
    assert "Gateway origin escape rejected" in activity
    assert "Absolute product URLs are forbidden" in activity
    assert "Product GET route is not allowlisted" in activity
    assert "Product POST route is not allowlisted" in activity
    assert "Remote product attempted to widen Live authority" in activity
    assert "MAX_RESPONSE_BYTES = 1_000_000" in activity
    assert "MAX_REQUEST_CHARS = 16_384" in activity
    assert "AndroidKeyStore" in activity
    assert "AES/GCM/NoPadding" in activity
    assert "gateway_token" in activity


def test_ai_room_stays_policy_gated_and_cannot_activate_live_authority() -> None:
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
    assert 'put("liveTradingAuthority", false)' in activity


def test_mobile_network_surface_has_no_live_exchange_private_write_path() -> None:
    runtime = "\n".join((ASSETS / name).read_text(encoding="utf-8") for name in ("mobile-core.js", "mobile-runtime.js", "mobile-canonical-client.js"))
    activity = MAIN_ACTIVITY.read_text(encoding="utf-8")
    assert "requestPublicMarket" in runtime
    assert "https://api.bybit.com" in activity
    assert "/v5/market/kline" in activity
    assert "category=spot" in activity
    assert '"15", "60", "240"' in activity
    for forbidden in ("/v5/order", "apiKey", "apiSecret", "secretKey", "withdrawalEndpoint", "/api/product/live/order", "/withdraw"):
        assert forbidden not in runtime
        assert forbidden not in activity


def test_mobile_metadata_discloses_real_mission_control_backend_and_local_fallback() -> None:
    project = json.loads((ASSETS / "data.json").read_text(encoding="utf-8"))["project"]
    assert project["status"] == "complete"
    assert project["phase"] == 6
    assert project["mode"] == "research_backtest_paper"
    assert project["canonical_source"] == "Bybit"
    assert project["deterministic_risk_final_authority"] is True
    assert project["live_trading_authority"] is False
    assert project["profitability_claim"] is False
    assert project["product_version"] == "3.2.0"
    assert project["canonical_windows_main_sha"] == "366fe9b2b8e3788a3cb510af9a040fc091a2632d"
    assert project["backend_contracts"]["mission_control"] == "product_mission_runtime.py / nexus.product-mission-control.v1"
    assert project["backend_contracts"]["strategy_center"] == "product_mission_runtime.py / nexus.product-strategy-center.v1"
    assert project["mobile_delivery"]["mode"] == "canonical_backend_first_with_explicit_local_fallback"
    assert "/api/product/*" in project["mobile_delivery"]["canonical_product"]
    assert "LOCAL FALLBACK" in project["mobile_delivery"]["local_fallback"]
    assert "/api/product/mission/full" in project["mobile_delivery"]["mission_control"]
    assert "MISSION UNSYNCED" in project["mobile_delivery"]["mission_control"]
    assert "does not fabricate state" in project["mobile_delivery"]["mission_control"]
    assert "locked" in project["mobile_delivery"]["live"]


def test_mobile_version_and_ci_package_android_final_mission_control_build() -> None:
    gradle = BUILD_GRADLE.read_text(encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "versionCode 7" in gradle
    assert 'versionName "3.2.0"' in gradle
    assert "NEXUS_PERSONAL_PRO_3_2_0.apk" in workflow
    assert "versionCode='7' versionName='3.2.0'" in workflow
    assert "assets/mobile-canonical-client.js" in workflow
    for marker in (
        "CANONICAL BACKEND", "LOCAL FALLBACK", "/api/product/research/run",
        "/api/product/paper/order", "/api/product/mission/full", "MISSION UNSYNCED",
        "OWNER ACTION", "LEADING STRATEGY", "CI / EXACT HEAD", "NexusProductResult",
    ):
        assert marker in workflow
    assert "push:" in workflow and "branches: [main]" in workflow
