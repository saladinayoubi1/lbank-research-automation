from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
PIN = ROOT / "scripts" / "verify_nexus_owner_manifest_pins.ps1"


def test_manifest_pinning_is_independent_and_read_only() -> None:
    source = PIN.read_text(encoding="utf-8")
    for marker in (
        "ExpectedDataManifestSha256", "ExpectedShortcutManifestSha256",
        "ExpectedSyncManifestSha256", "MANIFEST_PIN_MISMATCH_",
        "MANIFEST_ENTRY_COUNT_MISMATCH_", "BACKUP_ROOT_REPARSE_POINT",
        "MANIFEST_REPARSE_POINT", "MANIFEST_PIN_PASS_NOT_ACTIVATION",
        "activation_authorized=$false", "paired_bundle_preflight_required=$true",
        "independent_source_for_expected_pins_verified=$false",
    ):
        assert marker in source
    assert "[Security.Cryptography.SHA256]::Create()" in source
    assert "Get-FileHash" not in source
    for forbidden in (
        "Start-Process", "Stop-Process", "Remove-Item", "Move-Item", "Copy-Item",
        "Set-Content", "CloseMainWindow", "Restart-Computer",
    ):
        assert forbidden not in source
    installer = (ROOT / "scripts" / "install_and_smoke_nexus_personal_pro.ps1").read_text(encoding="utf-8")
    assert PIN.name not in installer
    assert "UNSAFE_LEGACY_OWNER_ACTIVATION_DISABLED" in installer


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell parser and sandbox fixtures")
def test_manifest_pins_parse_and_reject_sandbox_tampering(tmp_path: Path) -> None:
    ps = shutil.which("powershell.exe") or shutil.which("powershell")
    assert ps
    escaped = str(PIN).replace("'", "''")
    check = (
        "$tokens=$null;$errors=$null;"
        f"[System.Management.Automation.Language.Parser]::ParseFile('{escaped}',"
        "[ref]$tokens,[ref]$errors)|Out-Null;"
        "if(@($errors).Count){$errors|ForEach-Object{$_.Message};exit 1}"
    )
    subprocess.run([ps, "-NoProfile", "-NonInteractive", "-Command", check],
                   text=True, capture_output=True, check=True)
    manifest_items = (
        ("product-data-sha256-manifest.json", 7),
        ("shortcuts-manifest.json", 4),
        ("global-paper-sync-manifest.json", 2),
    )
    hashes = []
    for name, count in manifest_items:
        data = [{"id": n} for n in range(count)]
        content = json.dumps(data, sort_keys=True)
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        hashes.append(hashlib.sha256(path.read_bytes()).hexdigest())
    args = [
        ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(PIN),
        "-BackupRoot", str(tmp_path),
        "-ExpectedDataManifestSha256", hashes[0],
        "-ExpectedShortcutManifestSha256", hashes[1],
        "-ExpectedSyncManifestSha256", hashes[2],
    ]
    good = subprocess.run(args, text=True, capture_output=True)
    assert good.returncode == 0, good.stdout + "\n" + good.stderr
    result = json.loads(good.stdout)
    assert result["decision"] == "MANIFEST_PIN_PASS_NOT_ACTIVATION"
    assert result["activation_authorized"] is False
    assert result["independent_source_for_expected_pins_verified"] is False

    (tmp_path / "shortcuts-manifest.json").write_text('[{"changed":true}]', encoding="utf-8")
    bad = subprocess.run(args, text=True, capture_output=True)
    assert bad.returncode != 0
    assert "MANIFEST_PIN_MISMATCH_shortcuts-manifest.json" in (bad.stdout + bad.stderr)
