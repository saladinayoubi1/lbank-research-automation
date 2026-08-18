from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop" / "nexus-product"
UI = ROOT / "product_ui"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_canonical_windows_product_packages_python_sidecar_and_source_bindings() -> None:
    required = [
        DESKTOP / "main.js", DESKTOP / "package.json",
        ROOT / "product_runtime.py", ROOT / "product_research_runtime.py",
        ROOT / "product_control_runtime.py", ROOT / "product_web_server.py",
        UI / "index.html", UI / "product.css", UI / "product-extra.css", UI / "product.js",
    ]
    assert all(path.is_file() for path in required)

    package = json.loads(read(DESKTOP / "package.json"))
    assert package["version"] == "4.1.0"
    assert package["main"] == "main.js"
    resources = {(item.get("from"), item.get("to")) for item in package["build"]["extraResources"]}
    assert ("sidecar/nexus-product-server.exe", "nexus-product-server.exe") in resources
    assert ("sidecar/source-sha.txt", "source-sha.txt") in resources
    assert ("sidecar/market-data-source-registry.yaml", "docs/architecture/market-data-source-registry.yaml") in resources

    main = read(DESKTOP / "main.js")
    assert "nexus-product-server.exe" in main
    assert "spawn(bindings.executable" in main
    assert "NEXUS_SOURCE_SHA" in main
    assert "NEXUS_MARKET_REGISTRY_PATH" in main
    assert "source-sha.txt" in main
    assert "market-data-source-registry.yaml" in main
    assert "127.0.0.1" in main
    assert "/api/product/overview" in main


def test_canonical_surface_is_full_nexus_product_not_market_shell() -> None:
    index = read(UI / "index.html")
    for marker in (
        "NEXUS Personal Pro", "Mission Control", "داده و بازار", "بک‌تست و پژوهش",
        "ترید دمو", "ریسک و پرتفوی", "اتاق هوش مصنوعی", "Strategy Lab",
        "عامل‌ها و صف", "ممیزی و بازیابی", "ترید اصلی", "OWNER-CONTROLLED FUTURE STAGE",
    ):
        assert marker in index
    assert "Research Terminal" not in index
    assert "پایانه پژوهش بازار" not in index


def test_canonical_product_uses_real_python_data_research_paper_risk_and_event_store() -> None:
    runtime = read(ROOT / "product_runtime.py")
    research = read(ROOT / "product_research_runtime.py")
    controls = read(ROOT / "product_control_runtime.py")
    assert "from deterministic_risk import" in runtime and "evaluate_risk" in runtime
    assert "from paper_execution import" in runtime and "execute_paper_command" in runtime
    assert "from paper_event_store import" in runtime and "replay" in runtime and "validate_event" in runtime
    assert "paper-events.jsonl" in runtime
    assert "_session_signal_count" in runtime
    assert "fetch_bind_bybit_dataset" in research
    assert "run_research_job" in research
    assert "run_target_exposure_backtest" in research
    assert "run_automated_signal_pipeline" in research
    assert "qualification_killed" in research and "paper_executed" in research
    assert "recovery_snapshot" in controls and "export_csv" in controls


def test_product_gateway_exposes_real_full_current_scope_contracts() -> None:
    server = read(ROOT / "product_web_server.py")
    for route in (
        "/api/product/overview", "/api/product/paper", "/api/product/paper/events",
        "/api/product/paper/order", "/api/product/paper/auto", "/api/product/research/run",
        "/api/product/data/registry", "/api/product/risk", "/api/product/recovery",
        "/api/product/notifications", "/api/product/export/paper.json", "/api/product/export/paper.csv",
        "/api/product/strategies", "/api/product/mission-control", "/api/product/live",
    ):
        assert route in server
    assert "build_ai_handler" in server
    assert '"live_main": "locked_owner_controlled"' in server
    assert '"/ui/product-extra.css": "product-extra.css"' in server


def test_electron_boundary_is_loopback_only_sandboxed_source_bound_and_fail_closed() -> None:
    main = read(DESKTOP / "main.js")
    for marker in (
        "contextIsolation: true", "sandbox: true", "nodeIntegration: false", "devTools: false",
        "webSecurity: true", "allowRunningInsecureContent: false", "target.origin === origin",
        "NEXUS startup blocked", "No Paper or Live state was changed",
        "NEXUS release source SHA is missing or invalid", "NEXUS canonical market registry missing",
    ):
        assert marker in main


def test_canonical_runtime_has_no_live_exchange_write_or_private_credential_path() -> None:
    product_text = "\n".join(read(path).casefold() for path in (
        ROOT / "product_runtime.py", ROOT / "product_research_runtime.py",
        ROOT / "product_control_runtime.py", ROOT / "product_web_server.py",
        UI / "product.js", DESKTOP / "main.js",
    ))
    for forbidden in ("/v5/order", "/order/create", "/api/product/live/order", "apisecret", "secretkey", "private_key"):
        assert forbidden not in product_text


def test_windows_targets_are_distinct_and_trusted_workflow_builds_exact_source_product() -> None:
    package = json.loads(read(DESKTOP / "package.json"))
    build = package["build"]
    assert build["nsis"]["artifactName"].startswith("NEXUS_Personal_Pro_Setup_")
    assert build["portable"]["artifactName"].startswith("NEXUS_Personal_Pro_Portable_")
    assert build["nsis"]["artifactName"] != build["portable"]["artifactName"]

    workflow = read(ROOT / ".github" / "workflows" / "build_lbank_desktop_windows.yml")
    for marker in (
        "product_runtime.py", "product_research_runtime.py", "product_control_runtime.py",
        "product_web_server.py", "desktop/nexus-product", "PyInstaller", "nexus-product-server.exe",
        "Smoke-test canonical product sidecar", "source-sha.txt", "market-data-source-registry.yaml",
        "NEXUS_Personal_Pro_Setup_4.1.0_", "NEXUS_Personal_Pro_Portable_4.1.0_",
    ):
        assert marker in workflow
    assert "push:" in workflow and "branches: [main]" in workflow


def test_frozen_workflow_permissions_policy_remains_authoritative() -> None:
    policy = json.loads(read(ROOT / "security" / "workflow-permissions-policy-v1.json"))
    trusted = policy["workflows"][".github/workflows/build_lbank_desktop_windows.yml"]
    assert trusted["workflow_permissions"] == {"contents": "read"}
    assert set(trusted["jobs"]) == {"build-windows"}
    assert ".github/workflows/build_nexus_product_windows.yml" not in policy["workflows"]
