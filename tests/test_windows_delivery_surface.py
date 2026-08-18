from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop" / "nexus-product"
UI = ROOT / "product_ui"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_canonical_windows_product_packages_python_sidecar() -> None:
    required = [
        DESKTOP / "main.js",
        DESKTOP / "package.json",
        ROOT / "product_runtime.py",
        ROOT / "product_web_server.py",
        UI / "index.html",
        UI / "product.css",
        UI / "product.js",
    ]
    assert all(path.is_file() for path in required)

    package = json.loads(read(DESKTOP / "package.json"))
    assert package["version"] == "4.0.0"
    assert package["main"] == "main.js"
    assert any(
        item.get("from") == "sidecar/nexus-product-server.exe"
        and item.get("to") == "nexus-product-server.exe"
        for item in package["build"]["extraResources"]
    )

    main = read(DESKTOP / "main.js")
    assert "nexus-product-server.exe" in main
    assert "spawn(executable" in main
    assert "127.0.0.1" in main
    assert "/api/product/overview" in main


def test_canonical_surface_is_full_nexus_product_not_market_shell() -> None:
    index = read(UI / "index.html")
    for marker in (
        "NEXUS Personal Pro",
        "Mission Control",
        "ترید دمو",
        "اتاق هوش مصنوعی",
        "Strategy Lab",
        "Research Lab",
        "تصمیم و ریسک",
        "عامل‌ها و صف",
        "رویداد و بازپخش",
        "ترید اصلی",
        "OWNER-CONTROLLED FUTURE STAGE",
    ):
        assert marker in index
    assert "Research Terminal" not in index
    assert "پایانه پژوهش بازار" not in index


def test_canonical_product_uses_real_python_paper_risk_and_event_store() -> None:
    runtime = read(ROOT / "product_runtime.py")
    assert "from deterministic_risk import" in runtime
    assert "evaluate_risk" in runtime
    assert "from paper_execution import" in runtime
    assert "execute_paper_command" in runtime
    assert "from paper_event_store import" in runtime
    assert "replay_events" in runtime
    assert "validate_event_chain" in runtime
    assert "paper-events.jsonl" in runtime
    assert "paper_trading_only" in runtime


def test_product_gateway_exposes_real_paper_ai_mission_and_locked_live_contracts() -> None:
    server = read(ROOT / "product_web_server.py")
    assert "/api/product/overview" in server
    assert "/api/product/paper" in server
    assert "/api/product/paper/events" in server
    assert "/api/product/paper/order" in server
    assert "/api/product/strategies" in server
    assert "/api/product/mission-control" in server
    assert "/api/product/live" in server
    assert "build_ai_handler" in server
    assert "live_main\": \"locked_owner_controlled" in server


def test_electron_boundary_is_loopback_only_sandboxed_and_fail_closed() -> None:
    main = read(DESKTOP / "main.js")
    assert "contextIsolation: true" in main
    assert "sandbox: true" in main
    assert "nodeIntegration: false" in main
    assert "devTools: false" in main
    assert "webSecurity: true" in main
    assert "allowRunningInsecureContent: false" in main
    assert "target.origin === origin" in main
    assert "NEXUS startup blocked" in main
    assert "No Paper or Live state was changed" in main


def test_canonical_runtime_has_no_live_exchange_write_or_private_credential_path() -> None:
    product_text = "\n".join(
        read(path).casefold()
        for path in (
            ROOT / "product_runtime.py",
            ROOT / "product_web_server.py",
            UI / "product.js",
            DESKTOP / "main.js",
        )
    )
    for forbidden in (
        "/v5/order",
        "/order/create",
        "/api/product/live/order",
        "apisecret",
        "secretkey",
        "private_key",
    ):
        assert forbidden not in product_text


def test_windows_targets_are_distinct_and_trusted_workflow_builds_canonical_sidecar() -> None:
    package = json.loads(read(DESKTOP / "package.json"))
    build = package["build"]
    assert build["nsis"]["artifactName"].startswith("NEXUS_Personal_Pro_Setup_")
    assert build["portable"]["artifactName"].startswith("NEXUS_Personal_Pro_Portable_")
    assert build["nsis"]["artifactName"] != build["portable"]["artifactName"]

    workflow = read(ROOT / ".github" / "workflows" / "build_lbank_desktop_windows.yml")
    assert "product_runtime.py" in workflow
    assert "product_web_server.py" in workflow
    assert "desktop/nexus-product" in workflow
    assert "PyInstaller" in workflow
    assert "nexus-product-server.exe" in workflow
    assert "Smoke-test canonical product sidecar" in workflow
    assert "NEXUS_Personal_Pro_Setup_4.0.0_" in workflow
    assert "NEXUS_Personal_Pro_Portable_4.0.0_" in workflow


def test_frozen_workflow_permissions_policy_remains_authoritative() -> None:
    policy = json.loads(read(ROOT / "security" / "workflow-permissions-policy-v1.json"))
    trusted = policy["workflows"][".github/workflows/build_lbank_desktop_windows.yml"]
    assert trusted["workflow_permissions"] == {"contents": "read"}
    assert set(trusted["jobs"]) == {"build-windows"}
    # Product delivery must use an already-authorized trusted workflow instead of
    # self-authorizing a new control-plane entry in the same candidate change.
    assert ".github/workflows/build_nexus_product_windows.yml" not in policy["workflows"]
