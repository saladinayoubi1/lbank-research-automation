from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PS = ROOT / "scripts" / "install_nexus_autostart_from_runner.ps1"
WF = ROOT / ".github" / "workflows" / "nexus-local-runner.yml"
POLICY = ROOT / "security" / "workflow-permissions-policy-v1.json"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_remote_installer_refuses_service_or_noninteractive_identity_and_ephemeral_install_root():
    text = read(PS)
    for marker in (
        "NT AUTHORITY\\SYSTEM",
        "NT AUTHORITY\\NETWORK SERVICE",
        "NT AUTHORITY\\LOCAL SERVICE",
        "[Environment]::UserInteractive",
        "not executing in an interactive owner session",
        "GITHUB_WORKSPACE",
        "$root -match",
        "_work",
    ):
        assert marker in text


def test_remote_installer_uses_bounded_candidates_and_managed_localappdata_fallback():
    text = read(PS)
    for marker in (
        "Desktop\\lbank-research-automation",
        "Documents\\lbank-research-automation",
        "NEXUS\\lbank-research-automation",
        "$ManagedRepoRoot",
        "New-ManagedStableRepo",
        "Resolve-StableRepo",
        "managed checkout path already exists but is not a valid canonical repository",
        "clone','--no-hardlinks','--no-checkout'",
        "remote','set-url','origin'",
        "checkout','-B','main'",
    ):
        assert marker in text
    assert "-Recurse" not in text


def test_ambiguous_owner_checkouts_are_not_touched_and_use_managed_checkout():
    text = read(PS)
    for marker in (
        "Get-OwnerStableRepoCandidates",
        "$ownerCandidates.Count -eq 1",
        "Selection='single-owner-checkout'",
        "Selection='existing-managed'",
        "'managed-no-owner-checkout'",
        "'managed-ambiguous-owner-checkouts'",
        "OwnerCandidateCount=$ownerCandidates.Count",
    ):
        assert marker in text
    assert "multiple stable repository checkouts found" not in text


def test_remote_installer_validates_exact_workspace_sha_and_canonical_origin():
    text = read(PS)
    for marker in (
        "Validate-Workspace",
        "GITHUB_WORKSPACE is not the repository root",
        "runner workspace SHA mismatch",
        "$ExpectedRemotePattern",
        "repository origin is not the canonical NEXUS repository",
        "rev-parse','HEAD",
    ):
        assert marker in text


def test_remote_installer_preserves_owner_changes_and_fast_forwards_from_exact_local_workspace():
    text = read(PS)
    for marker in (
        "diff --quiet",
        "diff --cached --quiet",
        "tracked unstaged changes",
        "staged changes",
        "Sync-ExactMainFromWorkspace",
        "fetch','--no-tags','--quiet',$Workspace,'HEAD'",
        "checkout','main",
        "merge','--ff-only','FETCH_HEAD",
        "runner workspace moved before sync",
        "stable main SHA mismatch",
    ):
        assert marker in text
    assert "fetch','origin','main" not in text
    assert "reset --hard" not in text
    assert "clean -fd" not in text


def test_remote_installer_does_not_add_network_credentials_and_emits_v2_evidence():
    text = read(PS)
    for marker in (
        "scripts\\nexus_windows_autostart.ps1",
        "scripts\\nexus_github_runner_autostart.ps1",
        "NEXUS-ZeroTouch-Autopilot",
        "NEXUS-GitHub-Runner-Autostart",
        "nexus.zero-touch-remote-install.v2",
        "stable_repo_selection",
        "owner_candidate_count",
        "sync_source = 'exact-github-actions-workspace'",
        "network_credentials_added = $false",
        "managed_checkout_created",
        "interactive_owner_session",
        "NEXUS_ZERO_TOUCH_REMOTE_INSTALL=SUCCESS",
        "NEXUS_STABLE_SELECTION",
        "NEXUS_MANAGED_CHECKOUT_CREATED",
        "build\\autostart-install",
    ):
        assert marker in text
    lowered = text.casefold()
    assert "gh auth login" not in lowered
    assert "config.cmd" not in lowered
    assert "personalaccesstoken" not in lowered
    assert "github_token" not in lowered


def test_local_runner_install_trigger_is_main_push_marker_only_and_evidence_backed():
    text = read(WF)
    assert "runs-on: [self-hosted, Windows, X64]" in text
    assert "if: github.ref == 'refs/heads/main'" in text
    assert "scripts/install_nexus_autostart_from_runner.ps1" in text
    marker = "github.event_name == 'push' && contains(github.event.head_commit.message, '[install-autostart]')"
    assert text.count(marker) == 3
    assert 'id: install_autostart' in text
    assert "-SourceSha \"$env:GITHUB_SHA\"" in text
    assert "nexus-zero-touch-install-${{ github.run_id }}" in text
    assert "build/autostart-install/evidence.json" in text
    assert "install-autostart" not in text.split("options:", 1)[1].split("push:", 1)[0]


def test_local_runner_status_handshake_is_fixed_exact_sha_and_narrowly_authorized():
    workflow = read(WF)
    policy = read(POLICY)
    for marker in (
        "statuses: write",
        "always() && github.event_name == 'push'",
        "NEXUS_INSTALL_OUTCOME: ${{ steps.install_autostart.outcome }}",
        "NEXUS_STATUS_TOKEN: ${{ github.token }}",
        "nexus/local-autostart-install",
        "$env:GITHUB_API_URL/repos/$env:GITHUB_REPOSITORY/statuses/$env:GITHUB_SHA",
        "NEXUS_LOCAL_AUTOSTART_STATUS=$state",
    ):
        assert marker in workflow
    assert workflow.count("statuses: write") == 1
    assert "contents: write" not in workflow
    assert "issues: write" not in workflow
    assert "actions: write" not in workflow
    assert '"contents":"read","statuses":"write"' in policy
    assert "Required only to report the fixed nexus/local-autostart-install commit status" in policy
