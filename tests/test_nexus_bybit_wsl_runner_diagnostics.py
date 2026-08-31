from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "capture_nexus_bybit_wsl_runner_diagnostics.ps1"
WORKFLOW = ROOT / ".github" / "workflows" / "nexus-bybit-wsl-runner-diagnostics.yml"


def test_runner_diagnostics_are_read_only_and_redacted():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "NEXUS Bybit WSL Runner" in text
    assert "/opt/nexus-bybit-runner/_diag" not in text  # constructed only from pinned runner root
    assert "Runner" in text and "Listener|Worker" in text
    assert "Runner\\\\.Worker" in text and "Runner\\\\.Listener" in text
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
    assert "github.event_name != 'workflow_dispatch'" in text
    assert "github.ref == 'refs/heads/main'" in text
    assert "runs-on: [self-hosted, Windows, X64]" in text
    assert "permissions:\n  contents: read" in text
    assert "cancel-in-progress: false" in text
    assert "uses:" not in text.split("  capture:", 1)[1]
    assert "actions/checkout@" not in text
    assert "actions/upload-artifact@" not in text
    assert "Prepare exact diagnostic source without JavaScript actions" in text
    assert "git -c credential.helper= -c http.https://github.com/.extraheader= fetch --no-tags --prune --depth=1 $repoUrl $env:GITHUB_SHA" in text
    assert "$env:GIT_TERMINAL_PROMPT = '0'" in text
    assert "$env:GCM_INTERACTIVE = 'Never'" in text
    assert "git checkout --force --detach FETCH_HEAD" in text
    assert "diagnostic_anonymous_public_fetch=true" in text
    assert "diagnostic_javascript_actions_used=false" in text
    assert "Publish sanitized runner diagnostics to job log" in text
    assert "sanitized_diagnostics_log_begin" in text
    assert "sanitized_diagnostics_log_end" in text
    assert "raw_diagnostic_files_uploaded=false" in text
    assert "runner_mutation_performed=false" in text
    assert "windows_runner_paths_modified=false" in text
    assert "bybit_private_credentials_used=false" in text
    assert "capture_nexus_bybit_wsl_runner_diagnostics.ps1" in text
