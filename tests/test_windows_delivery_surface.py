from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop" / "nexus-product"
UI = ROOT / "product_ui"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_final_windows_product_packages_real_mission_control_and_source_bindings() -> None:
    required = [
        DESKTOP / "main.js", DESKTOP / "package.json",
        ROOT / "product_runtime.py", ROOT / "product_research_runtime.py",
        ROOT / "product_control_runtime.py", ROOT / "product_web_server.py",
        ROOT / "product_offline_runtime.py", ROOT / "product_offline_web_server.py",
        ROOT / "product_mission_runtime.py", ROOT / "product_build_runtime.py",
        ROOT / "config" / "nexus-agent-manager.json",
        ROOT / "scripts" / "export_mission_control_snapshot.py",
        UI / "index.html", UI / "product.css", UI / "product-extra.css", UI / "product.js",
        UI / "product-offline.js", UI / "product-offline.css",
        UI / "product-mission.js", UI / "product-mission.css",
    ]
    assert all(path.is_file() for path in required)

    package = json.loads(read(DESKTOP / "package.json"))
    assert package["version"] == "5.0.0"
    assert package["main"] == "main.js"
    resources = {(item.get("from"), item.get("to")) for item in package["build"]["extraResources"]}
    assert ("sidecar/nexus-product-server", "nexus-product-server") in resources
    assert ("sidecar/source-sha.txt", "source-sha.txt") in resources
    assert ("sidecar/build-evidence.json", "build-evidence.json") in resources
    assert ("sidecar/market-data-source-registry.yaml", "docs/architecture/market-data-source-registry.yaml") in resources
    assert ("sidecar/nexus-agent-manager.json", "config/nexus-agent-manager.json") in resources

    main = read(DESKTOP / "main.js")
    for marker in (
        "nexus-product-server.exe", "spawn(bindings.executable", "NEXUS_SOURCE_SHA",
        "NEXUS_MARKET_REGISTRY_PATH", "NEXUS_AGENT_MANAGER_CONFIG", "NEXUS_BUILD_EVIDENCE_PATH",
        "source-sha.txt", "build-evidence.json", "nexus-agent-manager.json", "127.0.0.1",
        "/api/product/overview",
    ):
        assert marker in main


def test_windows_startup_is_slow_machine_tolerant_diagnostic_and_bounded_self_recovering() -> None:
    main = read(DESKTOP / "main.js")
    for marker in (
        "const http = require('http')", "timeoutMs = 90000", "sidecarExit", "sidecarStderr",
        "nexus-product-startup.log", "engine exited before startup", "Startup diagnostics",
        "cwd: path.dirname(bindings.executable)", "MAX_RESTARTS_PER_WINDOW = 3",
        "RESTART_WINDOW_MS", "bounded_restart_policy", "restartProductAfterExit",
        "supervisor-state.json", "bounded_restart_limit_reached",
    ):
        assert marker in main
    assert "fetch(`${origin}/api/product/overview`" not in main


def test_surface_is_nexus_mission_control_not_market_or_github_shell() -> None:
    index = read(UI / "index.html")
    mission = read(UI / "product-mission.js")
    for marker in (
        "NEXUS Personal Pro", "Mission Control", "داده و بازار", "بک‌تست و پژوهش",
        "ترید دمو", "ریسک و پرتفوی", "اتاق هوش مصنوعی", "Strategy Lab",
        "عامل‌ها و صف", "ممیزی و بازیابی", "ترید اصلی", "OWNER-CONTROLLED FUTURE STAGE",
    ):
        assert marker in index
    for marker in (
        "NOW", "RESOURCES", "LEADING STRATEGY", "BLOCKER / RECOVERY", "OWNER ACTION",
        "TASK QUEUE / ASSIGNMENTS", "CONTROL-PLANE EVENTS", "QUALIFICATION EVIDENCE",
        "/api/product/mission/full", "/api/product/mission/import",
    ):
        assert marker in mission
    assert "Research Terminal" not in index
    assert "پایانه پژوهش بازار" not in index


def test_product_uses_real_python_data_research_strategy_paper_risk_agent_state_and_offline_vault() -> None:
    runtime = read(ROOT / "product_runtime.py")
    research = read(ROOT / "product_research_runtime.py")
    controls = read(ROOT / "product_control_runtime.py")
    offline = read(ROOT / "product_offline_runtime.py")
    mission = read(ROOT / "product_mission_runtime.py")
    assert "from deterministic_risk import" in runtime and "evaluate_risk" in runtime
    assert "from paper_execution import" in runtime and "execute_paper_command" in runtime
    assert "from paper_event_store import" in runtime and "replay" in runtime and "validate_event" in runtime
    assert "paper-events.jsonl" in runtime
    assert "fetch_bind_bybit_dataset" in research
    assert "run_research_job" in research and "run_canonical_target_exposure_backtest" in research
    assert "run_automated_signal_pipeline" in research
    assert "recovery_snapshot" in controls and "export_csv" in controls
    assert "OfflineDatasetStore" in offline and "CachingProductResearchRuntime" in offline
    assert "StrategyEvidenceStore" in offline
    assert '"internet_required_for_startup": False' in offline
    assert "agent_manager_runtime.json" in mission
    assert "manager_state.json" in mission
    assert "manager_events.jsonl" in mission
    assert "OWNER_REQUIRED" in mission and "heartbeat_at" in mission and "dispatch_transport" in mission
    assert "leading_candidate" in mission and "walk_forward_score" in mission and "oos_score" in mission


def test_gateway_exposes_final_mission_strategy_supervisor_build_and_offline_contracts() -> None:
    server = read(ROOT / "product_web_server.py")
    final_server = read(ROOT / "product_offline_web_server.py")
    for route in (
        "/api/product/overview", "/api/product/paper", "/api/product/paper/events",
        "/api/product/paper/order", "/api/product/paper/auto", "/api/product/research/run",
        "/api/product/data/registry", "/api/product/risk", "/api/product/recovery",
        "/api/product/notifications", "/api/product/export/paper.json", "/api/product/export/paper.csv",
        "/api/product/strategies", "/api/product/mission-control", "/api/product/live",
    ):
        assert route in server
    for route in (
        "/api/product/offline", "/api/product/offline/import", "/api/product/offline/research",
        "/api/product/offline/paper/auto", "/api/product/mission/full", "/api/product/mission/import",
        "/api/product/mission/export", "/api/product/strategies/evidence",
        "/api/product/build-evidence", "/api/product/local-supervisor",
    ):
        assert route in final_server
    assert "build_ai_handler" in server
    assert '"live_main": "locked_owner_controlled"' in server
    assert "product-offline.js" in final_server and "product-mission.js" in final_server


def test_electron_boundary_is_loopback_only_sandboxed_source_bound_and_fail_closed() -> None:
    main = read(DESKTOP / "main.js")
    for marker in (
        "contextIsolation: true", "sandbox: true", "nodeIntegration: false", "devTools: false",
        "webSecurity: true", "allowRunningInsecureContent: false", "target.origin === origin",
        "NEXUS startup blocked", "No Paper or Live state was changed",
        "NEXUS release source SHA is missing or invalid", "NEXUS canonical market registry missing",
        "NEXUS Agent Manager contract missing", "NEXUS exact-source build evidence missing",
    ):
        assert marker in main


def test_runtime_has_no_live_exchange_write_private_credential_or_l4_execution_path() -> None:
    product_text = "\n".join(read(path).casefold() for path in (
        ROOT / "product_runtime.py", ROOT / "product_research_runtime.py",
        ROOT / "product_control_runtime.py", ROOT / "product_web_server.py",
        ROOT / "product_offline_runtime.py", ROOT / "product_offline_web_server.py",
        ROOT / "product_mission_runtime.py", ROOT / "product_build_runtime.py",
        UI / "product.js", UI / "product-offline.js", UI / "product-mission.js", DESKTOP / "main.js",
    ))
    for forbidden in ("/v5/order", "/order/create", "/api/product/live/order", "apisecret", "secretkey", "private_key"):
        assert forbidden not in product_text
    assert "live_trading_authority\": false" in product_text or "live_trading_authority': false" in product_text or "live_trading_authority: false" in product_text


def test_windows_targets_are_distinct_and_trusted_workflow_builds_exact_source_final_product() -> None:
    package = json.loads(read(DESKTOP / "package.json"))
    build = package["build"]
    assert build["nsis"]["artifactName"].startswith("NEXUS_Personal_Pro_Setup_")
    assert build["portable"]["artifactName"].startswith("NEXUS_Personal_Pro_Portable_")
    assert build["nsis"]["artifactName"] != build["portable"]["artifactName"]

    workflow = read(ROOT / ".github" / "workflows" / "build_lbank_desktop_windows.yml")
    for marker in (
        "product_mission_runtime.py", "product_build_runtime.py", "tests/test_product_mission_runtime.py",
        "Build final Mission Control Python sidecar", "Smoke-test final Mission Control sidecar",
        "nexus-agent-manager.json", "build-evidence.json", "source-sha.txt",
        "NEXUS_Personal_Pro_Setup_5.0.0_", "NEXUS_Personal_Pro_Portable_5.0.0_",
    ):
        assert marker in workflow
    assert "push:" in workflow and "branches: [main]" in workflow


def test_coordinator_exports_portable_real_mission_snapshot_without_permission_expansion() -> None:
    workflow = read(ROOT / ".github" / "workflows" / "fast-agent-coordinator.yml")
    assert "scripts/export_mission_control_snapshot.py" in workflow
    assert "nexus-mission-control-snapshot.json" in workflow
    assert "contents: read" in workflow and "actions: write" in workflow
    script = read(ROOT / "scripts" / "export_mission_control_snapshot.py")
    assert 'SNAPSHOT_CONTRACT = "nexus.agent-manager-snapshot.v1"' in script
    assert '"live_trading_authority": False' in script


def test_frozen_workflow_permissions_policy_remains_authoritative() -> None:
    policy = json.loads(read(ROOT / "security" / "workflow-permissions-policy-v1.json"))
    trusted = policy["workflows"][".github/workflows/build_lbank_desktop_windows.yml"]
    assert trusted["workflow_permissions"] == {"contents": "read"}
    assert set(trusted["jobs"]) == {"build-windows"}
    assert ".github/workflows/build_nexus_product_windows.yml" not in policy["workflows"]
