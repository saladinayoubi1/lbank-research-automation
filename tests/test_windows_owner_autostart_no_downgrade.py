from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "install_nexus_owner_autostart_from_gui.ps1"


def test_gui_owner_bootstrap_never_downgrades_newer_managed_checkout() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")
    assert "function Test-GitAncestor" in text
    assert "merge-base --is-ancestor" in text
    assert "managed checkout newer than packaged seed; preserving" in text
    assert "PreservedNewer=$true" in text
    assert "divergent history" in text
    assert "preserved_newer_managed_checkout" in text


def test_gui_owner_bootstrap_uses_runtime_windows_detection() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")
    assert "RuntimeInformation]::IsOSPlatform" in text
    assert "OSPlatform]::Windows" in text
    assert "$env:OS -ne 'Windows_NT'" not in text
