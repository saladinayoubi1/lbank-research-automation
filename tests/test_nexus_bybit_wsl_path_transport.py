from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REPAIR_SCRIPT = REPO_ROOT / "scripts" / "repair_nexus_bybit_wsl_runner_package.ps1"


def _script_text() -> str:
    return REPAIR_SCRIPT.read_text(encoding="utf-8")


def test_host_package_path_is_not_sent_to_wslpath() -> None:
    text = _script_text()
    assert "function Convert-WindowsPathToWslMountPath" in text
    assert "wslpath', '-u', $script:hostPackagePath" not in text
    assert "Convert-WindowsPathToWslMountPath -WindowsPath $script:hostPackagePath" in text


def test_windows_drive_path_maps_to_default_wsl_mount_fail_closed() -> None:
    text = _script_text()
    assert "'^([A-Za-z]):\\\\(.+)$'" in text
    assert 'return "/mnt/$drive/$relativePath"' in text
    assert "Only rooted local-drive Windows paths can be mapped into WSL." in text
    assert "WINDOWS_PACKAGE_WSL_PATH_FAILED" in text
    assert "WINDOWS_PACKAGE_WSL_PATH_UNSAFE" in text
