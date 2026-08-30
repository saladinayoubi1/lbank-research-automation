from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
WAKE_WORKFLOW = ROOT / ".github" / "workflows" / "nexus-bybit-wsl-runner-wake.yml"
DIAGNOSTIC_SCRIPT = ROOT / "scripts" / "run_nexus_bybit_wsl_runner_diagnostics.ps1"


def test_wake_is_bootstrap_independent_and_scheduler_bounded() -> None:
    text = WAKE_WORKFLOW.read_text(encoding="utf-8")

    assert not re.search(r"(?m)^\s*uses:\s*", text)
    assert "actions/checkout" not in text
    assert "actions/upload-artifact" not in text
    assert "NEXUS Bybit WSL Runner Persistent" in text
    assert "NEXUS Bybit WSL Runner" in text
    assert "schtasks.exe" in text
    assert "/Run /TN $selected" in text
    assert "wsl.exe" not in text.lower()


def test_diagnostics_treat_service_wsl_visibility_as_context_limited() -> None:
    text = DIAGNOSTIC_SCRIPT.read_text(encoding="utf-8")

    assert "NEXUS Bybit WSL Runner Persistent" in text
    assert "NEXUS Bybit WSL Runner" in text
    assert "WSL_DISTRIBUTION_NOT_VISIBLE_FROM_WINDOWS_RUNNER_CONTEXT" in text
    assert "runner_health_verified = $false" in text
    assert "recovery_request_performed = $false" in text
