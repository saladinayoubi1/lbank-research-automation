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
    assert "[IO.File]::Replace($tmp,$l.path,$priorSibling)" in script
    assert "[IO.File]::Replace($tmp,$l.path,$null)" not in script
    assert '.nexus-rollback-prior.lnk' in script
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

def test_early_failure_keeps_the_healthy_previous_gui():
    script=SOURCE.read_text(encoding="utf-8")
    assert "if($t.status -in @('STARTED','BACKED_UP','ACTIVATING') -and !$existingNew.Count -and $oldWindow.Count -eq 1)" in script
    assert "if($state.status -eq 'healthy' -and $state.source_sha -eq $oldSource" in script
    assert "Finish-Rollback $t $Dir" in script
    assert "newer-paper-post-recovery.json" in script
    assert "RECOVERY_NEEDS_REVIEW" in script
    assert "if($t.status -in @('BACKED_UP','ACTIVATING')" in script
    assert "Assert ($null -eq $existing) 'A previous owner rollback watchdog still exists" in script

def test_watchdog_can_be_rehearsed_without_touching_owner_tasks():
    script=SOURCE.read_text(encoding="utf-8")
    assert "[switch]$TestScheduler" in script
    assert 'NEXUS-Activation-REHEARSAL-$sourceShort' in script
    assert 'SYNTHETIC_OWNER_WATCHDOG_COM=PASS' in script
    assert "$folder.DeleteTask($testName,0)" in script

def test_only_one_entrypoint_and_rollback_verifies_old_health():
    script=SOURCE.read_text(encoding="utf-8")
    assert script.count("function Rehearse {")==1
    assert script.count("function Rollback([string]$Dir){")==1
    assert script.count("if($Mode -eq 'Rehearse')")==1
    assert script.count("Assert ($Mode -eq 'Activate')")==1
    assert "$null=Health $oldSource 425 $prior" in script
    assert "if($t.status -in @('COMMITTED','ROLLED_BACK')){return}" in script


def test_physical_shortcut_failure_is_rehearsed_with_legal_backup():
    script=SOURCE.read_text(encoding="utf-8")
    assert "[IO.File]::Replace($linkTemp,$link,$linkPrior)" in script
    assert "Assert ((Hash $linkPrior) -eq $linkMeta.sha)" in script
    assert "RestoreLinks @($linkMeta)" in script
    assert "!(Test-Path $linkPrior)" in script
    assert ".nexus-rollback-prior.lnk" in script


def test_no_repeat_destructive_recovery_for_advanced_owner_paper():
    script=SOURCE.read_text(encoding="utf-8")
    assert "if($t.status -eq 'RECOVERY_NEEDS_REVIEW'){throw" in script
    assert "$t.status='RECOVERY_NEEDS_REVIEW'" in script
    assert "if($t.status -in @('STARTED','BACKED_UP','ACTIVATING') -and !$existingNew.Count -and $existingOld.Count -gt 0)" in script
    assert "newer-paper-post-recovery.json" in script
    assert "if((Hash $currentJournal) -eq $first and" not in script


def test_candidate_is_retired_before_old_owner_recovery_classification():
    script = SOURCE.read_text(encoding="utf-8")
    rollback = script[script.index("function Rollback([string]$Dir){"):script.index("function Rehearse {")]
    assert rollback.index("if($existingNew.Count){") < rollback.index("$oldWindow=@($existingOld")
    assert "Stop-Exact $candidate 4" in rollback
    assert "Progressing Paper journal could not be captured consistently" in rollback
    assert "Current Paper differs from activation snapshot" in rollback
    assert "unreplayed-current-paper.json" in rollback
    assert "RECOVERY_NEEDS_REVIEW" in rollback


def test_shortcut_commit_checks_targets_and_original_bytes_before_finalizing():
    script = SOURCE.read_text(encoding="utf-8")
    marker = script.index("Post-switch shortcut target mismatch")
    commit = script.index("$record.status='COMMITTED'")
    assert marker < commit
    assert "Atomic switch modified original shortcut bytes" in script[marker:commit]
    assert "Prior app restarted during shortcut commit" in script[marker:commit]
    assert "$null=Health $ExpectedSourceSha 35" in script[marker:commit]
