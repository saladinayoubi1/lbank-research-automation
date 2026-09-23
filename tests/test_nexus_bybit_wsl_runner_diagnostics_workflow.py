from pathlib import Path


WORKFLOW = Path(".github/workflows/nexus-bybit-wsl-runner-diagnostics.yml")
CAPTURE = Path("scripts/capture_nexus_bybit_wsl_runner_diagnostics.ps1")


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
    assert "git -C $sourceRoot -c credential.helper= -c http.https://github.com/.extraheader= fetch --no-tags --prune --depth=1 $repoUrl $env:GITHUB_SHA" in capture
    assert 'Join-Path $env:RUNNER_TEMP ("nexus-bybit-wsl-diagnostics-" + $env:GITHUB_RUN_ID)' in capture
    assert "DIAGNOSTIC_SOURCE_ROOT=$sourceRoot" in capture
    assert "$fetchSucceeded = $false" in capture
    assert "for ($attempt = 1; $attempt -le 3; $attempt++)" in capture
    assert "exact diagnostic source fetch attempt $attempt failed" in capture
    assert "Start-Sleep -Seconds (2 * $attempt)" in capture
    assert "exact diagnostic source fetch failed after bounded retries." in capture
    assert "diagnostic_fetch_retry_bound=3" in capture
    assert "$env:GIT_TERMINAL_PROMPT = '0'" in capture
    assert "$env:GCM_INTERACTIVE = 'Never'" in capture
    assert "diagnostic_anonymous_public_fetch=true" in capture
    assert "git -C $sourceRoot checkout --force --detach FETCH_HEAD" in capture
    assert "git -C $sourceRoot rev-parse HEAD" in capture
    assert "$head -ne $env:GITHUB_SHA" in capture
    assert "diagnostic_checkout_sha=$head" in capture
    assert "diagnostic_source_root=$sourceRoot" in capture


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
    assert "Join-Path $env:DIAGNOSTIC_SOURCE_ROOT 'build\\bybit-wsl-runner-diagnostics\\evidence.json'" in capture
    assert "Join-Path $env:DIAGNOSTIC_SOURCE_ROOT 'scripts\\run_nexus_bybit_wsl_runner_diagnostics.ps1'" in capture


def test_diagnostics_remain_read_only_and_failure_triggered() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    permissions = text.split("permissions:", 1)[1].split("concurrency:", 1)[0]
    assert "contents: read" in permissions
    assert "write" not in permissions
    assert 'workflows: ["NEXUS persistent Paper trading loop"]' in text
    assert "github.event.workflow_run.conclusion == 'failure'" in text
    assert "github.event.workflow_run.conclusion == 'cancelled'" in text
    assert "runs-on: [self-hosted, Windows, X64, nexus-remote-rescue]" in text
    assert "nexus-bybit-wsl-runner-diagnostics-${{" in text
    assert "github.event.workflow_run.id" in text


def test_linux_diagnostics_support_minimal_wsl_without_coreutils_process_tools() -> None:
    text = CAPTURE.read_text(encoding="utf-8")
    forbidden = (
        "ps -",
        "| sort",
        "| uniq",
        "tail -n",
        "head -n",
        "find '$RunnerRoot",
        "grep -",
        "df -",
    )
    for fragment in forbidden:
        assert fragment not in text
    assert "/proc/[0-9]*" in text
    assert "/proc/meminfo" in text
    assert "/proc/loadavg" in text
    assert "/proc/uptime" in text
    assert "Runner.Listener|Runner.Worker|dotnet" in text
    assert '$Command.Replace("`r`n", "`n").Replace("`r", "`n")' in text
    assert '$psi.Arguments = "-d $Distribution -u root -- bash -s"' in text
    assert "$psi.RedirectStandardInput = $true" in text
    assert '[Console]::InputEncoding = (New-Object System.Text.UTF8Encoding($false))' in text
    assert "$process.StandardInput.Encoding.GetPreamble().Length -ne 0" in text
    assert "$process.StandardInput.Write($normalizedCommand)" in text
    assert "$process.WaitForExit(30000)" in text
    assert "for prefix in Runner Worker" in text
    assert '[ "${#recent_files[@]}" -gt 2 ]' in text
    assert '[ "$lines_read" -ge 400 ] && break' in text
    assert 'collect_signal_lines < "$file"' in text
    assert "bash -lc $Command" not in text
    assert "runner_mutation_performed = $false" in text
    assert "windows_runner_paths_modified = $false" in text
    assert "bybit_private_credentials_used = $false" in text
