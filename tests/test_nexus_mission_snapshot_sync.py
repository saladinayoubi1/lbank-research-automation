from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "sync_nexus_mission_snapshot_from_github.ps1"
MAIN = ROOT / "desktop" / "nexus-product" / "main.js"
PACKAGE = ROOT / "desktop" / "nexus-product" / "package.json"
STAGE = ROOT / "desktop" / "nexus-product" / "stage-package-resources.js"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_mission_sync_helper_is_exact_source_paper_only_and_loopback_only() -> None:
    helper = text(HELPER)
    for marker in (
        "ExpectedSourceSha",
        "fast-agent-coordinator.yml",
        "fast-agent-status-$runId",
        "nexus.agent-manager-snapshot.v1",
        "github-cloud-coordinator",
        "runtime.schema_version -ne 1",
        "paper_only -ne $true",
        "live_trading_authority -ne $false",
        "127.0.0.1",
        "/api/product/mission/import",
        "/api/product/mission/full",
        "control_plane.runtime_present -ne $true",
        "NEXUS_MISSION_SYNC=PASS",
    ):
        assert marker in helper
    assert "auth token" not in helper.casefold()
    assert "GITHUB_TOKEN" not in helper
    assert "contents: write" not in helper
    assert "actions: write" not in helper


def test_mission_sync_helper_is_bounded_and_preserves_newer_local_snapshot() -> None:
    helper = text(HELPER)
    assert "5242880" in helper
    assert "2097152" in helper
    assert "UtcNow.AddMinutes(5)" in helper
    assert "local_snapshot_newer" in helper
    assert "mission-sync.log" in helper
    assert "524288" in helper


def test_windows_package_contains_mission_sync_helper() -> None:
    package = json.loads(text(PACKAGE))
    resources = package["build"]["extraResources"]
    assert {
        "from": "sidecar/sync_nexus_mission_snapshot_from_github.ps1",
        "to": "scripts/sync_nexus_mission_snapshot_from_github.ps1",
    } in resources
    stage = text(STAGE)
    assert "copyScript('sync_nexus_mission_snapshot_from_github.ps1')" in stage


def test_electron_supervisor_runs_bounded_non_overlapping_mission_sync() -> None:
    main = text(MAIN)
    assert "MISSION_SYNC_INTERVAL_MS = 5 * 60 * 1000" in main
    assert "MISSION_SYNC_TIMEOUT_MS = 2 * 60 * 1000" in main
    assert "if (isQuitting || !productReady || !productOrigin || missionSyncProcess) return" in main
    assert "sync_nexus_mission_snapshot_from_github.ps1" in main
    assert "'-ExpectedSourceSha', bindings.sourceSha" in main
    assert "'-Origin', productOrigin" in main
    assert "mission sync timed out; terminating owned helper" in main
    assert "stopMissionSync(); stopSidecar();" in main
