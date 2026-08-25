from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "phase7_offline_laptop.ps1"
CORE = ROOT / "scripts" / "phase7_offline_laptop_core.ps1"


def test_phase7_wrapper_preserves_public_contract_and_core():
    wrapper = WRAPPER.read_text(encoding="utf-8-sig")
    core = CORE.read_text(encoding="utf-8-sig")

    assert "ValidateSet('PrepareOnline','ExecuteOffline','SubmitReturn')" in wrapper
    assert "& $CoreScript -Mode $Mode -SessionId $SessionId -Repo $Repo -RepoRoot $RepoRoot" in wrapper
    assert "function Submit-Return" in core
    assert "$s.completed_at = UtcNow" in core  # historical PS5.1 failure remains isolated in the core


def test_phase7_wrapper_recovers_only_verified_ps51_bookkeeping_failure():
    wrapper = WRAPPER.read_text(encoding="utf-8-sig")

    assert "$Mode -eq 'SubmitReturn'" in wrapper
    assert "property 'completed_at' cannot be found" in wrapper
    assert "if (-not $isKnownPs51BookkeepingFailure) { throw }" in wrapper
    assert "verified proof artifact is missing; refusing bookkeeping recovery" in wrapper
    assert "hardware_proof_complete -ne $true" in wrapper
    assert "verified_progress_percent -ne 100.0" in wrapper
    assert "Laptop.classification -ne 'EXECUTED'" in wrapper
    assert "internet_unavailable_pre -ne $true" in wrapper
    assert "internet_unavailable_post -ne $true" in wrapper
    assert "paper_only -ne $true" in wrapper
    assert "live_trading_authority -ne $false" in wrapper


def test_phase7_wrapper_uses_ps51_safe_dynamic_property_persistence():
    wrapper = WRAPPER.read_text(encoding="utf-8-sig")

    assert "Add-Member -NotePropertyName $Name -NotePropertyValue $Value -Force" in wrapper
    assert "Set-Or-AddProperty $session 'completed_at'" in wrapper
    assert "Set-Or-AddProperty $session 'verified_artifact_dir'" in wrapper
    assert "$session | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $tmp -Encoding UTF8" in wrapper
    assert "Move-Item -LiteralPath $tmp -Destination $sessionPath -Force" in wrapper
    assert "$session.completed_at =" not in wrapper
    assert "$session.verified_artifact_dir =" not in wrapper
