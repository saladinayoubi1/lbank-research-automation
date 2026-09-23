from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "install_nexus_autostart_from_runner.ps1"


def test_git_helpers_capture_native_stderr_without_fail_fast() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")
    assert "$previousErrorActionPreference = $ErrorActionPreference" in text
    assert "$ErrorActionPreference = 'Continue'" in text
    assert "$exitCode = $LASTEXITCODE" in text
    assert "$ErrorActionPreference = $previousErrorActionPreference" in text
    assert "if ($exitCode -ne 0)" in text
