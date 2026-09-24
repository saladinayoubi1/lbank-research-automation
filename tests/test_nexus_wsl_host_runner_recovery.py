from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(".github/workflows/nexus-wsl-host-runner-recovery.yml")


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_recovery_can_be_triggered_by_bounded_main_push() -> None:
    text = _text()
    assert "workflow_dispatch:" in text
    assert "push:" in text
    assert "branches: [main]" in text
    assert "'.github/workflows/nexus-wsl-host-runner-recovery.yml'" in text
    assert "'.nexus/wsl-host-recovery-trigger.txt'" in text
    assert "runs-on: nexus-bybit-network" in text


def test_recovery_targets_exact_local_runner_without_registration_mutation() -> None:
    text = _text()
    for marker in (
        "Recover exact Lenovo local Actions runner through WSL interop",
        'Join-Path $env:LOCALAPPDATA "NEXUS\\actions-runner"',
        'expectedRunnerName = "NEXUS-LOCAL-RUNNER"',
        "exact local runner repository binding mismatch",
        "NEXUS_LOCAL_RUNNER_TARGET_VERIFIED=true",
        "multiple exact local runner listeners observed before recovery",
        "duplicate exact local runner listeners observed after recovery",
        "NEXUS_LOCAL_RUNNER_WAKE=SUCCESS",
        "NEXUS_LOCAL_RUNNER_REGISTRATION_CHANGED=false",
        "NEXUS_LOCAL_RUNNER_CREDENTIALS_CHANGED=false",
        "NEXUS_LIVE_TRADING_AUTHORITY_CHANGED=false",
    ):
        assert marker in text

    lowered = text.casefold()
    for forbidden in (
        "config.cmd",
        "remove.cmd",
        "new-service",
        "set-service",
        "runner_registration_changed=true",
        "runner_credentials_changed=true",
        "live_trading_authority_changed=true",
    ):
        assert forbidden not in lowered


def test_remote_commander_recovery_remains_reused_not_recreated() -> None:
    text = _text()
    assert 'NEXUS-Remote-Commander-Recovery' in text
    assert 'schtasks.exe /Query /TN $task' in text
    assert 'schtasks.exe /Run /TN $task' in text
    assert 'remote_commander_task_mutated=false' in text
    assert 'windows_acl_modified=false' in text
