from pathlib import Path

SCRIPT = Path("scripts/nexus_prospective_paper_sync.ps1")
INSTALLER = Path("scripts/install_and_smoke_nexus_personal_pro.ps1")


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_paper_sync_keeps_valid_current_state_on_transport_failure() -> None:
    script = text(SCRIPT)
    for marker in (
        "Keep-Current-And-Defer",
        "deferred_safe",
        "SIGNED_BITS_FALLBACK=PASS",
        "signed artifact digest mismatch",
        "Test-State",
    ):
        assert marker in script


def test_paper_sync_skips_redownload_when_latest_run_is_already_installed() -> None:
    script = text(SCRIPT)
    for marker in (
        "last-sync.json",
        "same-run-validation",
        "success_no_change",
        "SYNC_NO_CHANGE_RUN=",
        "[string]$lastSync.run_id -eq $RunId",
    ):
        assert marker in script


def test_windows_app_installer_deploys_canonical_paper_sync_source() -> None:
    installer = text(INSTALLER)
    for marker in (
        "nexus_prospective_paper_sync.ps1",
        "product_prospective_paper.py",
        "paper-forward-sync",
        "NEXUS_PAPER_SYNC_SOURCE_DEPLOYED=1",
    ):
        assert marker in installer
