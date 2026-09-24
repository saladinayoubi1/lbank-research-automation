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


def test_runner_supervisor_uses_cached_healthy_evidence_and_five_minute_reconcile():
    text = BOOTSTRAP_MAIN.read_text(encoding="utf-8")
    assert "const RUNNER_SUPERVISOR_INTERVAL_MS = 5 * 60 * 1000;" in text
    assert "function runnerStateIsHealthy(state)" in text
    assert "if (!force && runnerStateIsHealthy(cached)) return { status: 'HEALTHY_CACHED'" in text
    assert "reconcileRunnerFromGui({ force: true })" in text
