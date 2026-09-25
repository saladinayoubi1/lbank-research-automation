"""Safety and isolation checks for the action-free owner runner probe."""

from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/nexus-runner-transport-probe.yml"


def test_probe_is_action_free_and_never_runs_without_explicit_dispatch():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "runs-on: [self-hosted, Windows, X64, nexus-local]" in text
    assert "uses:" not in text
    assert "actions/checkout" not in text
    assert "actions/upload-artifact@" not in text
    assert "contents: read" in text
    assert "timeout-minutes: 12" in text
    assert "cancel-in-progress: false" in text


def test_probe_is_bounded_and_never_uses_secrets_or_trading_commands():
    text = WORKFLOW.read_text(encoding="utf-8")
    for required in (
        "RUNNER_ISOLATED_WORKER_STARTED=1",
        "RUNNER_ISOLATED_TRANSPORT_PASS=1",
        "NEXUS-LOCAL-RUNNER",
        "api.github.com/",
        "codeload.github.com/actions/upload-artifact/zip/",
        "broker.actions.githubusercontent.com/",
        "--ipv4",
        "--http1.1",
        "--connect-timeout 6",
        "--max-time 15",
    ):
        assert required in text
    for forbidden in ("secrets.", "gh auth token", "git reset", "bybit", "orders_allowed", "live_trading"):
        assert forbidden not in text.casefold()
