from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "nexus_github_runner_autostart.ps1"


def read() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_running_service_requires_exact_root_listener_before_healthy_status() -> None:
    text = read()
    reconcile = text[text.index("function Reconcile-Runner"):text.index("function Install-Autostart")]
    observed = reconcile.index("runner_service_running_observed")
    listener_lookup = reconcile.index("$listener = Get-ListenerProcess $runner", observed)
    grace = reconcile.index("Start-Sleep -Seconds 8", listener_lookup)
    verified = reconcile.index("runner_service_running_listener_verified", grace)
    healthy_return = reconcile.index("return 'SERVICE_RUNNING'", verified)
    assert observed < listener_lookup < grace < verified < healthy_return
    prefix = reconcile[:healthy_return]
    assert "return 'SERVICE_RUNNING'" not in prefix


def test_stale_running_service_fallback_is_bounded_and_non_elevating() -> None:
    text = read()
    reconcile = text[text.index("function Reconcile-Runner"):text.index("function Install-Autostart")]
    for marker in (
        "SERVICE_RUNNING_LISTENER_MISSING_COOLDOWN",
        "LISTENER_RUNNING_SERVICE_STALE_FALLBACK",
        "LISTENER_STARTING_SERVICE_STALE_FALLBACK",
        "runner_service_running_stale_user_fallback",
        "TotalSeconds -lt 60",
        "Start-InteractiveRunner $runner",
    ):
        assert marker in reconcile
    # Start-InteractiveRunner does a final exact-root listener check before launch.
    helper = text[text.index("function Start-InteractiveRunner"):text.index("function Reconcile-Runner")]
    assert "$existing = Get-ListenerProcess $Runner" in helper
    assert "if ($existing) { return $true }" in helper
    lowered = reconcile.casefold()
    assert "stop-service" not in lowered
    assert "restart-service" not in lowered
    assert "-verb runas" not in text.casefold()
    assert "config.cmd" not in text.casefold()
    assert "--token" not in text.casefold()


def test_status_surface_does_not_equate_service_running_with_listener_running() -> None:
    text = read()
    status = text[text.index("function Show-Status"):text.index("function Run-Daemon")]
    assert "$listener = Get-ListenerProcess $runner" in status
    assert "LISTENER $listenerState" in status
    assert "NOT OBSERVED" in status


def test_runner_registration_and_owner_task_safety_boundaries_remain_intact() -> None:
    text = read()
    for marker in (
        "-LogonType Interactive",
        "-RunLevel Limited",
        "CreateNoWindow = $true",
        "duplicate_runner_daemon_rejected",
        "repository must remain $ExpectedRepo",
    ):
        assert marker in text
    lowered = text.casefold()
    assert "config.cmd" not in lowered
    assert "--token" not in lowered
    assert "-verb runas" not in lowered
