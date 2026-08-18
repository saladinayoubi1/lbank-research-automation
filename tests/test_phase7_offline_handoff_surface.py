from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PS = ROOT / "scripts" / "phase7_offline_laptop.ps1"
WF = ROOT / ".github" / "workflows" / "nexus-mission-queue.yml"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_powershell_handoff_has_three_explicit_modes_and_no_runner_dependency():
    text = read(PS)
    for marker in (
        "PrepareOnline", "ExecuteOffline", "SubmitReturn",
        "offline_agent_courier", "phase7_build_return_manifest", "phase7_return_package",
        "gh' @('workflow','run'", "gh' @('run','download'", "gh' @('pr','create'",
    ):
        assert marker in text
    assert "self-hosted" not in text.casefold()
    assert "actions-runner" not in text.casefold()


def test_courier_key_is_dpapi_protected_stdin_only_and_cleaned_after_verified_completion():
    text = read(PS)
    for marker in (
        "ProtectedData]::Protect", "DataProtectionScope]::CurrentUser",
        "RedirectStandardInput = $true", "$p.StandardInput.Write($SecretValue)",
        "courier-key.dpapi", "secret','delete", "hardware_proof_complete",
        "verified_progress_percent", "Laptop.classification",
    ):
        assert marker in text
    assert "--body" not in text
    assert "Write-Host $secret" not in text
    assert "Set-Content -LiteralPath $keyPath" not in text
    assert "Copy-Item -LiteralPath $s.key_path" not in text


def test_offline_execution_requires_reboot_and_dual_target_unreachable_before_and_after():
    text = read(PS)
    for marker in (
        "LastBootUpTime", "Windows must be rebooted after PrepareOnline",
        "Test-TcpTarget 'api.github.com' 443", "Test-TcpTarget '1.1.1.1' 443",
        "internet is still reachable", "internet became reachable during offline execution",
        "reboot_after_prepare = $true", "bounded_tcp_connect_dual_target_v1",
        "result_sha256 = $resultSha",
    ):
        assert marker in text
    assert text.count("Get-NetworkObservation") >= 3


def test_return_branch_is_data_only_and_is_never_merged_by_helper():
    text = read(PS)
    for marker in (
        "phase7/return-$($s.session_id)", ".nexus/phase7-return/$($s.session_id)",
        "return branch contains non-data change", "gh' @('pr','checks'",
        "nexus-phase7-return-verified-$($s.session_id)", "gh' @('pr','close'",
        "--delete-branch",
    ):
        assert marker in text
    assert "pr','merge" not in text
    assert "gh pr merge" not in text


def test_workflow_return_path_guards_same_repo_owner_data_only_and_trusted_ancestor_before_secret_use():
    text = read(WF)
    guard_pos = text.index("Guard data-only returned-laptop PR")
    secret_pos = text.index("Independently finalize returned laptop proof")
    assert guard_pos < secret_pos
    for marker in (
        ".nexus/phase7-return/**", "startsWith(github.head_ref, 'phase7/return-')",
        "test \"$HEAD_REPO\" = \"$GITHUB_REPOSITORY\"", "test \"$PR_AUTHOR\" = \"$REPO_OWNER\"",
        "test \"$GITHUB_ACTOR\" = \"$REPO_OWNER\"", "non-data return change rejected",
        "git merge-base --is-ancestor \"$source_sha\" \"$BASE_SHA\"",
        "git worktree add --detach \"$trusted\"", "Validate returned-laptop package before secret access",
        "phase7_return_package", "NEXUS_OFFLINE_COURIER_KEY: ${{ secrets.NEXUS_OFFLINE_COURIER_KEY }}",
        "phase7_resource_ledger_finalize", "--offline-network-proof",
        "hardware_proof_complete'] is True", "verified_progress_percent'] == 100.0",
    ):
        assert marker in text


def test_workflow_permissions_and_job_inventory_remain_frozen():
    text = read(WF)
    assert "permissions:\n  contents: read" in text
    assert text.count("\n  validate-mission-queue:\n") == 1
    assert "contents: write" not in text
    assert "pull-requests: write" not in text
    assert "actions: write" not in text
