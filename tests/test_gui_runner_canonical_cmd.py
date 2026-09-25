from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "scripts" / "bootstrap_nexus_runner_from_gui.ps1"


def _isolated_resolver() -> str:
    script = BOOTSTRAP.read_text(encoding="utf-8")
    start = script.index("function Get-CanonicalSystemCmd {")
    end = script.index("\n}\n", start) + 2
    return script[start:end]


def test_gui_runner_never_uses_missing_or_poisoned_comspec() -> None:
    script = BOOTSTRAP.read_text(encoding="utf-8")
    assert "$env:ComSpec" not in script
    assert "$psi.FileName = Get-CanonicalSystemCmd" in script
    assert "$action.Path = Get-CanonicalSystemCmd" in script
    assert "[Environment]::GetFolderPath" in _isolated_resolver()
    assert "[IO.FileAttributes]::ReparsePoint" in _isolated_resolver()


def test_canonical_cmd_resolves_without_comspec_on_windows() -> None:
    if os.name != "nt":
        return
    resolver = _isolated_resolver()
    command = (
        "$ErrorActionPreference='Stop'; $env:ComSpec=$null;\n"
        + resolver
        + "\n$path=Get-CanonicalSystemCmd; "
        + "$expected=Join-Path ([Environment]::GetFolderPath("
        + "[Environment+SpecialFolder]::Windows)) 'System32\\cmd.exe'; "
        + "if(-not [string]::Equals($path,$expected,"
        + "[StringComparison]::OrdinalIgnoreCase)) {throw 'Unexpected command path'}; "
        + "if(-not (Test-Path -LiteralPath $path -PathType Leaf)){throw 'Missing command'}; "
        + "Write-Output 'CANONICAL_CMD_WITHOUT_COMSPEC=PASS'"
    )
    env = dict(os.environ)
    env.pop("ComSpec", None)
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True, timeout=30, env=env, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "CANONICAL_CMD_WITHOUT_COMSPEC=PASS" in result.stdout
