from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PS = ROOT / "scripts" / "install_nexus_autostart_from_runner.ps1"
WF = ROOT / ".github" / "workflows" / "nexus-local-runner.yml"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_remote_installer_refuses_service_identities_and_ephemeral_workspace():
    text = read(PS)
    for marker in (
        "NT AUTHORITY\\SYSTEM",
        "NT AUTHORITY\\NETWORK SERVICE",
        "NT AUTHORITY\\LOCAL SERVICE",
        "GITHUB_WORKSPACE",
        "$root -match",
        "_work",
        "no stable repository checkout was found outside the GitHub Actions workspace",
        "multiple stable repository checkouts found",
    ):
        assert marker in text


def test_remote_installer_uses_bounded_stable_repo_candidates_and_exact_origin():
    text = read(PS)
    for marker in (
        "Desktop\\lbank-research-automation",
        "Documents\\lbank-research-automation",
        "LOCALAPPDATA 'NEXUS\\lbank-research-automation'",
        "remote','get-url','origin",
        "$ExpectedRemotePattern",
        "saladinayoubi1",
        "lbank-research-automation",
    ):
        assert marker in text
    assert "-Recurse" not in text


def test_remote_installer_preserves_owner_changes_and_requires_exact_fast_forward_main():
    text = read(PS)
    for marker in (
        "diff --quiet",
        "diff --cached --quiet",
        "tracked unstaged changes",
        "staged changes",
        "fetch','origin','main','--quiet",
        "checkout','main",
        "merge','--ff-only','origin/main",
        "stable main SHA mismatch",
    ):
        assert marker in text
    assert "reset --hard" not in text
    assert "clean -fd" not in text


def test_remote_installer_installs_both_existing_versioned_autostart_helpers_and_emits_evidence():
    text = read(PS)
    for marker in (
        "scripts\\nexus_windows_autostart.ps1",
        "scripts\\nexus_github_runner_autostart.ps1",
        "NEXUS-ZeroTouch-Autopilot",
        "NEXUS-GitHub-Runner-Autostart",
        "nexus.zero-touch-remote-install.v1",
        "NEXUS_ZERO_TOUCH_REMOTE_INSTALL=SUCCESS",
        "build\\autostart-install",
    ):
        assert marker in text
    lowered = text.casefold()
    assert "gh auth login" not in lowered
    assert "config.cmd" not in lowered
    assert "personalaccesstoken" not in lowered


def test_local_runner_install_trigger_is_main_push_marker_only_and_evidence_backed():
    text = read(WF)
    assert "runs-on: [self-hosted, Windows, X64]" in text
    assert "if: github.ref == 'refs/heads/main'" in text
    assert "scripts/install_nexus_autostart_from_runner.ps1" in text
    marker = "github.event_name == 'push' && contains(github.event.head_commit.message, '[install-autostart]')"
    assert text.count(marker) == 2
    assert "-SourceSha \"$env:GITHUB_SHA\"" in text
    assert "nexus-zero-touch-install-${{ github.run_id }}" in text
    assert "build/autostart-install/evidence.json" in text
    assert "install-autostart" not in text.split("options:", 1)[1].split("push:", 1)[0]
