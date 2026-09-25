"""Offline fault-injection coverage for resumable GitHub artifact ranges.

The Windows integration harness runs only the bounded transport section with
a local mocked Start-Process, not a real GitHub token or CDN connection.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "download_github_actions_artifact_http11.ps1"


def _transport_section() -> str:
    source = SCRIPT.read_text(encoding="utf-8-sig")
    begin = source.index("$fullDigestFailures = 0\nwhile (-not $verified) {")
    end = source.index(
        '\nif (-not $verified) { throw "Exact artifact download failed verification." }',
        begin,
    )
    return source[begin:end]


def test_range_reuse_cannot_bypass_artifact_identity_or_full_sha():
    source = SCRIPT.read_text(encoding="utf-8-sig")
    section = _transport_section()
    assert source.index("Artifact source SHA binding mismatch.") < source.index("$retainedParts = @{}")
    assert source.index("Artifact metadata digest mismatch.") < source.index("$retainedParts = @{}")
    assert "$retainedParts.ContainsKey($rangeKey)" in section
    assert "Retained artifact range changed:" in section
    assert "Artifact range changed before ordered append:" in section
    assert "Untrusted artifact range reparse point:" in section
    assert "Downloaded artifact fragment is a reparse point:" in section
    assert "$retainedParts = @{}" in section
    assert "No fragments survive a separate execution" in section
    assert "$fullDigestFailures -ge 2" in section
    assert "Get-FileHash -LiteralPath $archivePath -Algorithm SHA256" in section
    assert "if ($null -eq $signedUrl) { $signedUrl = Get-SignedArtifactUrl }" in section
    assert "Start-Sleep -Seconds ([Math]::Min(3 * $attempt, 15))" in section


def _run_mock_transport(tmp_path: Path, *, fail_one: bool = False, corrupt: bool = False,
                        stale_fragment: bool = False, fail_forever: bool = False):
    original = bytes(i % 251 for i in range(1024))
    original_path = tmp_path / "fixture.bin"
    original_path.write_bytes(original)
    expected_sha = hashlib.sha256(original).hexdigest()
    archive = tmp_path / "mock-archive.zip"
    invocations = tmp_path / "requests.json"

    # A fragment from a prior invocation is never trusted even when its size
    # matches the expected size. It must be fetched again.
    if stale_fragment:
        (tmp_path / "mock-archive.zip.part-0-255").write_bytes(b"x" * 256)

    def literal(p: Path) -> str:
        return str(p).replace("'", "''")

    powershell = rf"""
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$script:calls=@{{}}
$script:mockError=$null
$archivePath='{literal(archive)}'
$ExpectedArchiveBytes=[long]1024
$ExpectedArchiveSha256='{expected_sha}'
$chunkBytes=256
$parallelChunks=4
$MaxAttempts=3
$verified=$false
function Get-SignedArtifactUrl {{ return 'https://fixture.invalid/signed' }}
function Start-Process {{
    param(
        [string]$FilePath, [string[]]$ArgumentList,
        [switch]$NoNewWindow, [switch]$PassThru,
        [string]$RedirectStandardError
    )
    if ($FilePath -ne 'curl.exe') {{ throw 'Unexpected program in offline mock' }}
    $ri=[Array]::IndexOf($ArgumentList,'--range')
    $oi=[Array]::IndexOf($ArgumentList,'--output')
    $range=[string]$ArgumentList[$ri+1]
    $path=[string]$ArgumentList[$oi+1]
    if ($script:calls.ContainsKey($range)) {{
        $script:calls[$range]=[int]$script:calls[$range]+1
    }} else {{
        $script:calls[$range]=1
    }}
    $bounds=$range.Split('-')
    $from=[int]::Parse($bounds[0])
    $to=[int]::Parse($bounds[1])
    $data=[IO.File]::ReadAllBytes('{literal(original_path)}')
    $block=New-Object byte[] ($to-$from+1)
    [Array]::Copy($data,$from,$block,0,$block.Length)
    $exit=0
    if (($range -eq '256-511') -and (('{int(fail_one)}' -eq '1' -and $script:calls[$range] -eq 1) -or ('{int(fail_forever)}' -eq '1'))) {{
        $block=[byte[]]@(3,4,5)
        $exit=28
    }}
    if ('{int(corrupt)}' -eq '1' -and $range -eq '512-767') {{
        $block[0] = $block[0] -bxor 1
    }}
    [IO.File]::WriteAllBytes($path,$block)
    [IO.File]::WriteAllText($RedirectStandardError,'')
    $fake=[pscustomobject]@{{ ExitCode=$exit }}
    $fake | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value {{}}
    return $fake
}}
try {{
{_transport_section()}
if (-not $verified) {{ throw 'Transport did not finish' }}
}} catch {{
    $script:mockError=$_.Exception.Message
}} finally {{
    $script:calls | ConvertTo-Json -Compress |
        Set-Content -LiteralPath '{literal(invocations)}' -Encoding UTF8
}}
if ($script:mockError) {{
    [Console]::Error.WriteLine($script:mockError)
    exit 7
}}
Write-Output 'OFFLINE_TRANSPORT_PASS=1'
"""
    runner = tmp_path / "mock-test.ps1"
    runner.write_text(powershell, encoding="utf-8")
    shell = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
    assert shell, "PowerShell required"
    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(runner)],
        env=os.environ.copy(), capture_output=True, text=True, timeout=65,
    )
    assert invocations.exists(), result.stdout + result.stderr
    return result, archive, json.loads(invocations.read_text(encoding="utf-8-sig")), expected_sha


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell transport test requires Windows")
def test_failed_range_only_is_retried_and_full_sha_passes(tmp_path):
    result, archive, requests, expected_sha = _run_mock_transport(
        tmp_path, fail_one=True, stale_fragment=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OFFLINE_TRANSPORT_PASS=1" in result.stdout
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == expected_sha
    assert requests == {
        "0-255": 1,
        "256-511": 2,
        "512-767": 1,
        "768-1023": 1,
    }
    assert not list(tmp_path.glob("mock-archive.zip.part-*"))


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell transport test requires Windows")
def test_correct_size_but_corrupted_range_fails_closed_after_bounded_sha_rechecks(tmp_path):
    result, archive, requests, expected_sha = _run_mock_transport(
        tmp_path, corrupt=True
    )
    assert result.returncode != 0
    assert "Assembled artifact repeatedly failed full SHA-256 verification." in (
        result.stdout + result.stderr
    )
    assert hashlib.sha256(archive.read_bytes()).hexdigest() != expected_sha
    assert requests["512-767"] == 2
    assert not list(tmp_path.glob("mock-archive.zip.part-*"))


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell transport test requires Windows")
def test_persistently_failed_range_has_bounded_retries_without_partial_append(tmp_path):
    result, archive, requests, _ = _run_mock_transport(
        tmp_path, fail_forever=True
    )
    assert result.returncode != 0
    assert "Exact artifact range download failed after 3 bounded attempts at byte 0." in (
        result.stdout + result.stderr
    )
    assert not archive.exists()
    assert requests == {
        "0-255": 1,
        "256-511": 3,
        "512-767": 1,
        "768-1023": 1,
    }
    assert not list(tmp_path.glob("mock-archive.zip.part-*"))
