"""Fail-closed source contract for the owner-specific Windows desktop cutover.
Physical GUI acceptance and the COM watchdog must be evidenced separately.
"""
from pathlib import Path

SOURCE=Path(__file__).resolve().parents[1]/"scripts"/"nexus_owner_activation_transaction.ps1"

def test_transactional_path_does_not_touch_broad_processes():
    script=SOURCE.read_text(encoding="utf-8")
    assert "function ExactProcs" in script
    assert "IsWithin $_.Path $Root" in script
    assert "function Stop-Exact" in script
    assert "Only the two bound installation roots can be stopped" in script
    assert "Stop-Process -Id $again.Id -Force" in script
    assert "taskkill" not in script.lower()
    assert "stop-process -name" not in script.lower()
    assert "remove-item -literalpath $program" not in script.lower()

def test_activation_is_separate_and_stage_gated():
    script=SOURCE.read_text(encoding="utf-8")
    assert "'Preflight','Rehearse','Activate','Recover'" in script
    assert "STAGED_ONLY_OWNER_PRESERVED" in script
    assert "PASS_NO_OWNER_ACTIVATION" in script
    assert "Live-locked" in script
    assert "Assert (@(ExactProcs $candidate).Count -eq 0)" in script
    assert script.index("Assert ($Mode -eq 'Activate')") < script.index("Stop-Exact $prior 15")
    assert script.index("CheckStage\n  $scheduler=")<script.index("Stop-Exact $prior 15")
    assert script.index("RegisterTaskDefinition($taskName")<script.index("Stop-Exact $prior 15")

def test_backup_health_atomic_switch_and_rollback_order():
    script=SOURCE.read_text(encoding="utf-8")
    assert script.index("Stop-Exact $prior 15")<script.index("$files=@(ProfileFiles $owner)")
    assert script.index("foreach($x in $files){")<script.index("$record.status='BACKED_UP'")
    assert script.index("Write-Json (Join-Path $transaction 'transaction.json') $record")<script.index("$null=Start-Process -FilePath (Join-Path $candidate")
    assert script.index("$null=Health $ExpectedSourceSha 425")<script.index("$shortcut=$shell.CreateShortcut")
    assert "[IO.File]::Replace($tmp,$l.path,$null)" in script
    assert "$record.status='COMMITTED'" in script
    assert "Rollback $TransactionDir" in script
    assert "RestoreProfile $Dir" in script
    assert "RestoreLinks @($t.links)" in script
    assert "failed-candidate-profile" in script
    assert "sync_was_enabled" in script

def test_rehearsal_operates_only_on_disposable_synthetic_state():
    script=SOURCE.read_text(encoding="utf-8")
    start=script.index("function Rehearse")
    end=script.index("if($Mode -eq 'Rehearse')")
    rehearsal=script[start:end]
    assert "nexus-activation-synthetic" in rehearsal
    assert "$script:owner=Join-Path $r 'synthetic-owner'" in rehearsal
    assert "RestoreProfile $txn" in rehearsal
    assert "RestoreLinks @($linkMeta)" in rehearsal
    assert "Remove-Item -LiteralPath $r" in rehearsal
    assert "$script:owner=$actualOwner" in rehearsal
