from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bootstrap_nexus_runner_from_gui.ps1"


def read() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_gui_runner_prefers_canonical_managed_root_when_legacy_runner_coexists() -> None:
    text = read()
    for marker in (
        "$ManagedRunnerRoot = Join-Path $env:LOCALAPPDATA 'NEXUS\\actions-runner'",
        "$ManagedRunnerMarkerName = '.nexus-managed-runner.json'",
        "function Test-IsNexusManagedRunner",
        "selected_nexus_managed_root",
        "SelectedBy='nexus-managed-root'",
        "discovered_runner_count",
        "runner_selection_policy",
    ):
        assert marker in text


def test_gui_runner_keeps_ambiguous_nonmanaged_duplicates_fail_closed() -> None:
    text = read()
    assert "Status='MULTIPLE'" in text
    assert "SelectedBy='ambiguous'" in text
    assert "MULTIPLE_RUNNERS_REJECTED" in text
    lowered = text.casefold()
    for forbidden in (
        "config.cmd --unattended",
        "--token",
        "remove-item -recurse",
        "set-executionpolicy",
        "runlevel highest",
    ):
        assert forbidden not in lowered
