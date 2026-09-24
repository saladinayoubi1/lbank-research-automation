from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "desktop" / "nexus-product" / "main.js"
BOOTSTRAP_MAIN = ROOT / "desktop" / "nexus-product" / "bootstrap-main.js"
RUNNER_BOOTSTRAP = ROOT / "scripts" / "bootstrap_nexus_runner_from_gui.ps1"


def test_ui_preferences_do_not_collide_with_chromium_preferences_file():
    text = MAIN.read_text(encoding="utf-8")
    block = text[text.index("function preferencesPath()") : text.index("function normalizeUiPreferences")]
    assert "path.join(app.getPath('userData'), 'product-data')" in block
    assert "path.join(app.getPath('userData'), 'preferences')" not in block
    assert "return path.join(root, 'ui-preferences.json')" in block


def test_gui_runner_windows_detection_does_not_depend_on_optional_os_env_var():
    text = RUNNER_BOOTSTRAP.read_text(encoding="utf-8")
    assert "RuntimeInformation]::IsOSPlatform" in text
    assert "OSPlatform]::Windows" in text
    assert "$env:OS -ne 'Windows_NT'" not in text


def test_packaged_app_runs_validated_paper_sync_on_startup_and_bounded_interval():
    text = BOOTSTRAP_MAIN.read_text(encoding="utf-8")
    for marker in (
        "PAPER_SYNC_INTERVAL_MS = 15 * 60 * 1000",
        "PAPER_SYNC_TIMEOUT_MS = 3 * 60 * 1000",
        "function prospectivePaperSyncPath()",
        "paper-forward-sync', 'sync.ps1",
        "function runProspectivePaperSync()",
        "if (paperSyncInFlight)",
        "function startProspectivePaperSyncSupervisor()",
        "startProspectivePaperSyncSupervisor();",
    ):
        assert marker in text
    block = text[text.index("function runProspectivePaperSync()"):text.index("function startOwnerAutostartBootstrap")]
    assert "live_trading" not in block
