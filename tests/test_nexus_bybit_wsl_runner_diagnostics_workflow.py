from pathlib import Path


WORKFLOW = Path(".github/workflows/nexus-bybit-wsl-runner-diagnostics.yml")


def _capture_job(text: str) -> str:
    return text.split("  capture:", 1)[1]


def test_physical_windows_diagnostics_avoid_javascript_action_predownload() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    capture = _capture_job(text)
    assert "uses:" not in capture
    assert "actions/checkout@" not in capture
    assert "actions/upload-artifact@" not in capture
    assert "Prepare exact diagnostic source without JavaScript actions" in capture
    assert "diagnostic_javascript_actions_used=false" in capture


def test_diagnostics_native_checkout_is_exact_sha_bound() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    capture = _capture_job(text)
    assert "git -c credential.helper= -c http.https://github.com/.extraheader= fetch --no-tags --prune --depth=1 $repoUrl $env:GITHUB_SHA" in capture
    assert "$env:GIT_TERMINAL_PROMPT = '0'" in capture
    assert "$env:GCM_INTERACTIVE = 'Never'" in capture
    assert "diagnostic_anonymous_public_fetch=true" in capture
    assert "git checkout --force --detach FETCH_HEAD" in capture
    assert "git rev-parse HEAD" in capture
    assert "$head -ne $env:GITHUB_SHA" in capture
    assert "diagnostic_checkout_sha=$head" in capture


def test_sanitized_evidence_is_published_without_raw_diag_upload() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    capture = _capture_job(text)
    assert "Publish sanitized runner diagnostics to job log" in capture
    assert "sanitized_diagnostics_log_begin" in capture
    assert "sanitized_diagnostics_log_end" in capture
    assert "raw_diagnostic_files_uploaded=false" in capture
    assert "runner_mutation_performed=false" in capture
    assert "windows_runner_paths_modified=false" in capture
    assert "bybit_private_credentials_used=false" in capture
    assert "Raw diagnostic upload is forbidden." in capture


def test_diagnostics_remain_read_only_and_failure_triggered() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    permissions = text.split("permissions:", 1)[1].split("concurrency:", 1)[0]
    assert "contents: read" in permissions
    assert "write" not in permissions
    assert 'workflows: ["NEXUS persistent Paper trading loop"]' in text
    assert "github.event.workflow_run.conclusion == 'failure'" in text
    assert "github.event.workflow_run.conclusion == 'cancelled'" in text
    assert "runs-on: [self-hosted, Windows, X64]" in text
