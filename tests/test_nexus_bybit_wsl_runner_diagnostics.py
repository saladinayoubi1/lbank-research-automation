from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "capture_nexus_bybit_wsl_runner_diagnostics.ps1"
WORKFLOW = ROOT / ".github" / "workflows" / "nexus-bybit-wsl-runner-diagnostics.yml"


def test_runner_diagnostics_are_read_only_and_redacted():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "NEXUS Bybit WSL Runner" in text
    assert "/opt/nexus-bybit-runner/_diag" not in text  # constructed only from pinned runner root
    assert "Runner\\.(Listener|Worker)" in text
    assert "Protect-DiagnosticLine" in text
    assert "[redacted]" in text
    assert "[opaque]" in text
    assert "raw_diagnostic_files_uploaded = $false" in text
    assert "runner_mutation_performed = $false" in text
    assert "windows_runner_paths_modified = $false" in text
    assert "bybit_private_credentials_used = $false" in text
    for forbidden in (
        "Register-ScheduledTask",
        "Start-ScheduledTask",
        "Stop-ScheduledTask",
        "Unregister-ScheduledTask",
        "config.sh",
        "run.sh",
        "actions/runner-registration-token",
    ):
        assert forbidden not in text


def test_runner_diagnostics_workflow_is_bounded_to_failures_and_physical_windows():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'workflows: ["NEXUS persistent Paper trading loop"]' in text
    assert "github.event.workflow_run.conclusion == 'failure'" in text
    assert "github.event.workflow_run.conclusion == 'cancelled'" in text
    assert "runs-on: [self-hosted, Windows, X64]" in text
    assert "permissions:\n  contents: read" in text
    assert "cancel-in-progress: false" in text
    assert "actions/checkout@11d5960a326750d5838078e36cf38b85af677262" in text
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in text
    assert "capture_nexus_bybit_wsl_runner_diagnostics.ps1" in text
