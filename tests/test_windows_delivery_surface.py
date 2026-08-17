from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop" / "lbank-monitor"
APP = DESKTOP / "app"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_windows_delivery_entrypoint_is_committed_and_packaged() -> None:
    required = [
        APP / "index.html",
        APP / "desktop.css",
        APP / "desktop-runtime.js",
        APP / "project-data.js",
    ]
    assert all(path.is_file() for path in required)

    package = json.loads(read(DESKTOP / "package.json"))
    assert package["version"] == "3.5.0"
    assert any(item.get("from") == "app" and item.get("to") == "app" for item in package["build"]["extraResources"])

    main = read(DESKTOP / "main.js")
    assert "path.join(appRoot, 'index.html')" in main
    assert "NEXUS desktop entrypoint missing" in main


def test_windows_ui_is_terminal_first_readable_and_not_legacy_placeholder() -> None:
    index = read(APP / "index.html")
    css = read(APP / "desktop.css")

    assert "NEXUS Research Terminal" in index
    assert "RESEARCH TERMINAL" in index
    assert "Phase 6 Complete" in index
    assert "PAPER ONLY" in index
    assert "نتیجه نهایی NEXUS" in index
    assert "STRATEGY FACTORY" in index
    assert "مانیتور بازار" in index
    assert index.index('id="market"') < index.index('id="result"')
    assert "در حال بارگذاری" not in index
    assert "OpenAI" not in index
    assert "Google Gemini" not in index
    assert re.search(r'font-family:\s*"Segoe UI Variable Text","Segoe UI",Tahoma,Arial,sans-serif', css)


def test_windows_theme_is_flat_dense_and_optimized_for_laptop_viewports() -> None:
    css = read(APP / "desktop.css")
    assert re.search(r"--sidebar-width\s*:\s*202px", css)
    assert re.search(r"--topbar-height\s*:\s*56px", css)
    assert ".telemetry-strip{display:grid;grid-template-columns:repeat(4" in css
    assert ".terminal-frame{background:var(--panel);border:1px solid var(--line)}" in css
    assert ".strategy-table{border:1px solid var(--line);background:var(--panel)}" in css
    assert ".integrity-table{display:grid;grid-template-columns:repeat(2" in css
    assert "@media(max-height:780px) and (min-width:1180px)" in css
    assert re.search(r"--topbar-height\s*:\s*50px", css)
    assert "linear-gradient" not in css
    assert "backdrop-filter" not in css
    assert "border-radius:18px" not in css


def test_renderer_has_strict_csp_and_no_direct_network_access() -> None:
    index = read(APP / "index.html")
    assert "connect-src 'none'" in index
    assert "object-src 'none'" in index
    assert "desktop-runtime.js" in index
    assert "project-data.js" in index


def test_electron_boundary_stays_isolated_and_public_market_is_bounded() -> None:
    main = read(DESKTOP / "main.js")
    preload = read(DESKTOP / "preload.js")

    assert "contextIsolation: true" in main
    assert "sandbox: true" in main
    assert "nodeIntegration: false" in main
    assert "devTools: false" in main
    assert "PUBLIC_MARKET_SYMBOLS" in main
    assert "BTCUSDT" in main and "XRPUSDT" in main
    assert "PUBLIC_MARKET_INTERVALS" in main
    assert "https://api.bybit.com/v5/market/kline" in main
    assert "method: 'GET'" in main
    assert "redirect: 'error'" in main
    assert "nexus:public-market" in main
    assert "requestPublicMarket" in preload
    lowered = (main + preload).lower()
    assert "/order" not in lowered
    assert "withdraw" not in lowered


def test_project_metadata_preserves_paper_only_authority() -> None:
    data = read(APP / "project-data.js")
    assert "paper_only: true" in data
    assert "live_trading_authority: false" in data
    assert "deterministic_risk_final_authority: true" in data
    assert "profitability_claim: false" in data
    assert "canonical_source: 'Bybit'" in data
    assert "delivery_version: '3.5.0'" in data


def test_windows_targets_have_distinct_artifact_names() -> None:
    package = json.loads(read(DESKTOP / "package.json"))
    build = package["build"]
    assert build["nsis"]["artifactName"].startswith("NEXUS_Personal_Pro_Setup_")
    assert build["portable"]["artifactName"].startswith("NEXUS_Personal_Pro_Portable_")
    assert build["nsis"]["artifactName"] != build["portable"]["artifactName"]


def test_windows_workflow_verifies_packaged_resources_not_mobile_copy() -> None:
    workflow = read(ROOT / ".github" / "workflows" / "build_lbank_desktop_windows.yml")
    assert "Copy dashboard assets" not in workflow
    assert "dist/win-unpacked/resources/app" in workflow
    assert "NEXUS_Personal_Pro_Setup_3.5.0_" in workflow
    assert "NEXUS_Personal_Pro_Portable_3.5.0_" in workflow
