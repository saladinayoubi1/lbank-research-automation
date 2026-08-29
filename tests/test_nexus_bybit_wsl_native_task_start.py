from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STARTER = ROOT / "scripts" / "start_nexus_bybit_wsl_runner_native.ps1"
WORKFLOW = ROOT / ".github" / "workflows" / "nexus-bybit-wsl1-fallback.yml"


def test_native_starter_avoids_scheduledtasks_cim_cmdlets() -> None:
    source = STARTER.read_text(encoding="utf-8")

    assert "schtasks.exe" in source
    assert "'/Create'" in source
    assert "'/Run'" in source
    assert "'/Query'" in source
    assert "task_scheduler_backend = 'schtasks.exe'" in source
    assert "RUNNER_TRACKING_ID=" in source

    for cmdlet in (
        "New-ScheduledTaskAction",
        "New-ScheduledTaskTrigger",
        "New-ScheduledTaskPrincipal",
        "New-ScheduledTaskSettingsSet",
        "Register-ScheduledTask",
        "Start-ScheduledTask",
        "Get-ScheduledTaskInfo",
        "Get-ScheduledTask",
    ):
        assert cmdlet not in source


def test_native_starter_is_fail_closed_on_task_or_runner_failure() -> None:
    source = STARTER.read_text(encoding="utf-8")

    assert "SCHTASKS_CREATE_FAILED" in source
    assert "SCHTASKS_RUN_FAILED" in source
    assert "SCHTASKS_QUERY_FAILED" in source
    assert "RUNNER_NOT_ONLINE_AFTER_NATIVE_START" in source
    assert "READY_FOR_GITHUB_VALIDATION" in source
    assert "$RunnerLabel -in $labels" in source
    assert "github_registration_token_persisted = $false" in source
    assert "windows_runner_paths_modified = $false" in source
    assert "windows_runner_service_modified = $false" in source


def test_fallback_workflow_uses_native_starter_only_after_successful_repair() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "scripts/start_nexus_bybit_wsl_runner_native.ps1" in workflow
    assert "Start repaired runner with native Task Scheduler" in workflow
    assert "id: provision_after_repair" in workflow
    assert "if: steps.provision.outcome == 'failure' && steps.repair.outcome == 'success'" in workflow
    assert '-File scripts\\start_nexus_bybit_wsl_runner_native.ps1' in workflow
    assert '-OutputPath "build\\bybit-wsl-provisioning-after-repair\\evidence.json"' in workflow
