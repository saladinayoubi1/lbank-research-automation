from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop" / "lbank-monitor"
APP = DESKTOP / "app"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_windows_full_product_assets_are_committed_and_packaged() -> None:
    required = [
        APP / "index.html",
        APP / "full-product.css",
        APP / "desktop-product.js",
        APP / "project-data.js",
        DESKTOP / "main.js",
        DESKTOP / "preload.js",
    ]
    assert all(path.is_file() for path in required)

    package = json.loads(read(DESKTOP / "package.json"))
    assert package["version"] == "4.0.0"
    assert any(item.get("from") == "app" and item.get("to") == "app" for item in package["build"]["extraResources"])
    assert "app/desktop-product.js" in package["scripts"]["check"]


def test_windows_surface_is_integrated_nexus_product_not_market_shell() -> None:
    index = read(APP / "index.html")
    assert "NEXUS Personal Pro" in index
    assert "مرکز فرمان" in index
    assert "ترید دمو" in index
    assert "اتاق هوش مصنوعی" in index
    assert "Mission Control" in index
    assert "لابراتوار استراتژی" in index
    assert "ممیزی و بازپخش" in index
    assert "ترید اصلی قفل است" in index
    assert "desktop-product.js" in index
    assert "full-product.css" in index
    assert "Research Terminal" not in index
    assert "پایانه پژوهش بازار" not in index


def test_renderer_csp_stays_network_dark_and_electron_boundary_is_isolated() -> None:
    index = read(APP / "index.html")
    main = read(DESKTOP / "main.js")
    preload = read(DESKTOP / "preload.js")

    assert "connect-src 'none'" in index
    assert "object-src 'none'" in index
    assert "contextIsolation: true" in main
    assert "sandbox: true" in main
    assert "nodeIntegration: false" in main
    assert "devTools: false" in main
    assert "contextBridge" in preload


def test_public_market_bridge_is_bounded_read_only_and_closed_candle_runtime_filters() -> None:
    main = read(DESKTOP / "main.js")
    runtime = read(APP / "desktop-product.js")
    assert "PUBLIC_MARKET_SYMBOLS" in main
    assert "PUBLIC_MARKET_INTERVALS" in main
    assert "https://api.bybit.com/v5/market/kline" in main
    assert "method: 'GET'" in main
    assert "redirect: 'error'" in main
    assert "nexus:public-market" in main
    assert "requestPublicMarket" in read(DESKTOP / "preload.js")
    assert "c.t+step<=now" in runtime


def test_paper_product_has_deterministic_risk_execution_pnl_and_protective_controls() -> None:
    runtime = read(APP / "desktop-product.js")
    for token in (
        "paper_trading_only:true",
        "risk_allowed",
        "maxDailyLoss",
        "maxDrawdown",
        "maxSignals",
        "executePaper",
        "closePosition",
        "processProtective",
        "fee_recorded",
        "slippage_recorded",
        "position_opened",
        "position_closed",
        "kill_switch_recorded",
    ):
        assert token in runtime


def test_audit_chain_and_replay_are_tamper_evident() -> None:
    runtime = read(APP / "desktop-product.js")
    assert "GENESIS='0'.repeat(64)" in runtime
    assert "previous_event_digest" in runtime
    assert "event_digest:sha256" in runtime
    assert "function verifyLedger()" in runtime
    assert "function replayLedger()" in runtime
    assert "digest_mismatch" in runtime
    assert "chain_mismatch" in runtime


def test_ai_room_is_bounded_gateway_plus_local_fallback_without_live_authority() -> None:
    main = read(DESKTOP / "main.js")
    preload = read(DESKTOP / "preload.js")
    runtime = read(APP / "desktop-product.js")
    assert "AI_REQUEST_KEYS" in main
    assert "/api/ai-room/message" in main
    assert "method: 'POST'" in main
    assert "nexus:ai-room" in main
    assert "requestAiRoom" in preload
    assert "localAiReply" in runtime
    assert "paper-stage" in runtime
    assert "Risk Gate" in runtime


def test_research_preview_is_next_bar_open_and_no_profitability_claim_is_preserved() -> None:
    runtime = read(APP / "desktop-product.js")
    data = read(APP / "project-data.js")
    assert "strategySignal" in runtime
    assert "entry=c[i+1].o" in runtime
    assert "momentum" in runtime
    assert "trend_breakout" in runtime
    assert "mean_reversion" in runtime
    assert "profitability_claim: false" in data


def test_full_product_layout_reserves_left_sidebar_and_supports_collapse_and_overflow() -> None:
    css = read(APP / "full-product.css")
    runtime = read(APP / "desktop-product.js")
    assert ".shell{height:100vh;display:grid;grid-template-columns:var(--sidebar) minmax(0,1fr);direction:ltr" in css
    assert ".sidebar{direction:rtl" in css
    assert ".viewport{min-width:0;overflow:auto" in css
    assert "body.sidebar-collapsed .shell" in css
    assert "sidebarCollapsed:false" in runtime
    assert "e.key.toLowerCase()==='b'" in runtime


def test_project_metadata_marks_v4_complete_product_with_locked_live_authority() -> None:
    data = read(APP / "project-data.js")
    assert "product_surface: 'integrated_desktop'" in data
    assert "delivery_version: '4.0.0'" in data
    assert "paper_only: true" in data
    assert "live_trading_authority: false" in data
    assert "deterministic_risk_final_authority: true" in data
    assert "locked_live_surface" in data
    assert "paper_execution" in data
    assert "ai_room" in data
    assert "mission_control" in data
    assert "audit_replay" in data


def test_no_exchange_live_order_or_private_exchange_credential_path_in_native_bridge() -> None:
    native = (read(DESKTOP / "main.js") + read(DESKTOP / "preload.js")).lower()
    assert "/v5/order" not in native
    assert "/order/create" not in native
    assert "apikey" not in native
    assert "apisecret" not in native
    assert "secretkey" not in native
    assert "withdraw" not in native
    assert "liveTradingAuthority: false" in read(DESKTOP / "main.js")


def test_windows_targets_and_workflows_build_distinct_v4_artifacts() -> None:
    package = json.loads(read(DESKTOP / "package.json"))
    build = package["build"]
    assert build["nsis"]["artifactName"].startswith("NEXUS_Personal_Pro_Setup_")
    assert build["portable"]["artifactName"].startswith("NEXUS_Personal_Pro_Portable_")
    assert build["nsis"]["artifactName"] != build["portable"]["artifactName"]

    workflow = read(ROOT / ".github" / "workflows" / "build_lbank_desktop_windows.yml")
    verification = read(ROOT / ".github" / "workflows" / "nexus-build-verification.yml")
    for text in (workflow, verification):
        assert "full-product.css" in text
        assert "desktop-product.js" in text
        assert "NEXUS_Personal_Pro_Setup_4.0.0_" in text
        assert "NEXUS_Personal_Pro_Portable_4.0.0_" in text
