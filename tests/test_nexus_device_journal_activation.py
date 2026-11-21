"""DeviceJournal opt-in tests; simulations never authorize an owner cutover."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "nexus_owner_activation_transaction.ps1"


def _journal(count=20):
    from paper_event_store import GENESIS_DIGEST, build_event

    provenance = dict(kind="manual", source_id="synthetic-cutover", source_timestamp="2020-01-01T00:00:00Z",
                      received_timestamp="2020-01-01T00:00:00Z", confidence="1", policy_version="synthetic-v1",
                      strategy_version="synthetic-v1", timeframe="session")
    rows = [("demo_account_opened", {"currency": "USDT", "opening_cash": "500"}),
            ("session_boundary_recorded", {"boundary": "open"}),
            ("fee_recorded", {"currency": "USDT", "amount": "0.57"}),
            ("equity_snapshot_recorded", {"cash": "499.43", "equity": "499.43", "unrealized_pnl": "0"})]
    rows += [("session_boundary_recorded", {"boundary": "open"})] * 16
    if count == 21:
        rows.append(("session_boundary_recorded", {"boundary": "close"}))
    events = []
    for index, (kind, payload) in enumerate(rows):
        events.append(build_event(event_id=f"synthetic:{index}", event_type=kind,
                                  aggregate_id="synthetic-device-paper", sequence=index + 1,
                                  occurred_at="2020-01-01T00:00:00Z", correlation_id="synthetic-cutover",
                                  causation_id="synthetic-cutover", provenance=provenance,
                                  previous_event_digest=events[-1]["event_digest"] if events else GENESIS_DIGEST,
                                  payload=payload))
    return b"".join((json.dumps(event, separators=(",", ":"), sort_keys=True) + "\n").encode() for event in events)


def _replay_code():
    source = SOURCE.read_text(encoding="utf-8")
    function = source[source.index("function DeviceReplay("):source.index("function AssertDeviceJournalPin(")]
    return re.search(r"\$code=@'\n(.*?)\n'@", function, re.S).group(1)


def _run_replay(path):
    return subprocess.run([sys.executable, "-c", _replay_code(), str(ROOT), str(path)],
                          capture_output=True, text=True, encoding="utf-8", timeout=15, check=False)


def test_existing_non_500_journal_is_verified_without_a_runtime_or_write():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "paper-events.jsonl"
        raw = _journal()
        path.write_bytes(raw)
        result = _run_replay(path)
        assert result.returncode == 0, result.stderr
        receipt = json.loads(result.stdout)
        assert receipt["cash"] == receipt["equity"] == "499.43"
        assert receipt["event_count"] == 20 and receipt["position_count"] == 0
        assert receipt["aggregate_id"] == "synthetic-device-paper"
        assert receipt["journal_sha256"] == hashlib.sha256(raw).hexdigest()
        assert receipt["head_event_digest"] == json.loads(raw.splitlines()[-1])["event_digest"]
        assert receipt["paper_only"] is True and receipt["live_trading_authority"] is False
        assert path.read_bytes() == raw
        assert list(Path(directory).iterdir()) == [path]


def test_corrupt_incomplete_or_absent_journal_never_creates_or_repairs_an_account():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "paper-events.jsonl"
        result = _run_replay(path)
        assert result.returncode != 0 and not path.exists()
        raw = _journal()
        altered = [json.loads(line) for line in raw.splitlines()]
        altered[-1]["payload"]["boundary"] = "close"  # deliberately invalid checksum
        fixtures = [b"", b"\0" * 100, raw.splitlines()[0] + b"\n",
                    b"\n".join(raw.splitlines()[1:]) + b"\n",
                    b"".join((json.dumps(row) + "\n").encode() for row in altered)]
        for broken in fixtures:
            path.write_bytes(broken)
            result = _run_replay(path)
            assert result.returncode != 0
            assert path.read_bytes() == broken
            assert list(Path(directory).iterdir()) == [path]


def test_a_valid_advanced_journal_has_distinct_identity_and_keeps_its_balance():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "paper-events.jsonl"
        raw = _journal(21)
        path.write_bytes(raw)
        result = _run_replay(path)
        assert result.returncode == 0, result.stderr
        receipt = json.loads(result.stdout)
        assert receipt["event_count"] == 21 and receipt["cash"] == "499.43"
        assert receipt["session_open"] is False
        assert receipt["journal_sha256"] != hashlib.sha256(_journal()).hexdigest()
        assert path.read_bytes() == raw


def test_device_opt_in_preserves_legacy_guards_and_binds_every_recovery_argument():
    source = SOURCE.read_text(encoding="utf-8")
    assert "[string]$AccountSurface='SharedPortfolio'" in source
    assert "Assert ([decimal]$j.account.initial_balance -eq 500)" in source
    assert "Device candidate is not current main" in source
    assert "DeviceJournal target host mismatch" in source
    assert "DeviceJournal roots overlap" in source
    assert "[Threading.AbandonedMutexException]{$locked=$true}" in source
    assert "function RestoreProfile" in source  # unchanged legacy recovery still exists
    recovery = source[source.index("function RecoverDeviceRecord("):source.index("function AssertDeviceRehearsal")]
    recovery_code = "\n".join(line for line in recovery.splitlines() if not line.lstrip().startswith("#"))
    assert "RestoreProfile " not in recovery_code and "Remove-Item " not in recovery_code
    assert recovery.index("no repeated mutation") < recovery.index("Stop-Exact $candidate")
    assert "Stop-Exact $prior" not in recovery
    assert recovery.index("Device journal advanced/changed") < recovery.index("RestoreLinks @($txn.links)")
    arguments = source[source.index("function DeviceRecoveryArguments("):source.index("function DeviceSetReview(")]
    for key in ("AccountSurface", "CandidateInstallRoot", "PriorInstallRoot", "PriorSourceSha", "OwnerProfileRoot",
                "ExpectedJournalSha256", "ExpectedArtifactId", "ExpectedArtifactRunId", "ExpectedUnpackedSha256",
                "StageProof", "ExpectedStageProofSha256", "CloneProof", "ExpectedCloneProofSha256",
                "RehearsalProof", "ExpectedRehearsalProofSha256", "JournalPython", "TransactionDir", "PrivateRoot"):
        assert key + "=" in arguments
    activate = source[source.index("function InvokeDeviceJournalTransaction"):source.index("if($AccountSurface -eq 'DeviceJournal'){try")]
    assert activate.index("$baseline=CheckDeviceStage;AssertDeviceRehearsal") < activate.index("Stop-Exact $prior -GraceSeconds 15")
    assert activate.index("DeviceCheckRecord (JsonFile") < activate.index("StartDeviceGui $candidate")
    assert "linkObject.Arguments=DeviceLaunchArgs $ExpectedSourceSha" in activate
    assert "committed.Arguments -ceq (DeviceLaunchArgs $ExpectedSourceSha)" in activate


def test_windows_device_journal_protocol_and_faults(tmp_path):
    if sys.platform != "win32":
        return
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    assert powershell, "Windows acceptance requires native PowerShell"
    original = tmp_path / "original.jsonl"
    advanced = tmp_path / "advanced.jsonl"
    original.write_bytes(_journal())
    advanced.write_bytes(_journal(21))
    harness = tmp_path / "device-journal-faults.ps1"
    harness.write_text(r'''
param([string]$Production,[string]$Original,[string]$Advanced,[string]$Scratch)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Production,[ref]$tokens,[ref]$errors)
if(@($errors).Count){throw ($errors|Out-String)}
foreach($f in $ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)){
  Invoke-Expression $f.Extent.Text
}
$script:AccountSurface='DeviceJournal';$script:ExpectedSourceSha='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
$script:PriorSourceSha='bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';$script:expectedRepo='saladinayoubi1/lbank-research-automation'
$script:candidate=Join-Path $Scratch 'candidate';$script:prior=Join-Path $Scratch 'prior'
$script:owner=Join-Path $Scratch 'owner';$script:PrivateRoot=Join-Path $Scratch 'private'
$script:ExpectedArtifactId=101;$script:ExpectedArtifactRunId=202;$script:ExpectedUnpackedSha256='1'*64
$script:StageProof=Join-Path $PrivateRoot 'stage.json';$script:CloneProof=Join-Path $PrivateRoot 'clone.json'
$script:RehearsalProof=Join-Path $PrivateRoot 'rehearsal.json'
$script:JournalPython='C:\synthetic\python.exe'
New-Item -ItemType Directory -Path $candidate,$prior,$owner,$PrivateRoot|Out-Null
$journal=PaperPath $owner;New-Item -ItemType Directory -Path (Split-Path -Parent $journal) -Force|Out-Null
Copy-Item -LiteralPath $Original -Destination $journal
$script:ExpectedJournalSha256=Hash $journal
$script:ops=@();$script:candidateAlive=$false
function ExactProcs([string]$Root){if($Root -eq $candidate -and $script:candidateAlive){return [pscustomobject]@{Id=123}};return @()}
function Stop-Exact([string]$Root,[int]$GraceSeconds){Assert ($Root -ceq $candidate) 'Prior/unrelated stop attempted';$script:ops+=@('stop-candidate');$script:candidateAlive=$false}
function StartDeviceGui([string]$Root,[string]$Source){Assert ($Root -ceq $prior -and $Source -ceq $PriorSourceSha) 'Incorrect rollback launch';$script:ops+=@('start-prior:'+(DeviceLaunchArgs $Source))}
function DeviceHealth([string]$Expected,[int]$Timeout,[string]$InstallRoot){Assert ($Expected -ceq $PriorSourceSha -and $InstallRoot -ceq $prior) 'Incorrect rollback health';$script:ops+=@('health-prior')}
function RestoreProfile {throw 'Device recovery tried to replay profile'}
function Refused([scriptblock]$Action,[string]$Message){$caught=$false;try{& $Action}catch{$caught=$true};Assert $caught $Message}
# The wrong host must refuse before identity/process operations.
$oldHost=$env:COMPUTERNAME;try{$env:COMPUTERNAME='WRONG-HOST';Refused {InitializeDeviceContext} 'Wrong host accepted'}finally{$env:COMPUTERNAME=$oldHost}
Refused {AssertDeviceLinkPath 'C:\unrelated\arbitrary.lnk'} 'Untrusted GUI link allowed'
# Keep fixture link I/O under Scratch while retaining production record/proof validation.
function AssertDeviceLinkPath([string]$Path){Assert ($Path -ceq (Join-Path $Scratch 'NEXUS Personal Pro.lnk')) 'Fixture GUI path not allowed'}
$link=Join-Path $Scratch 'NEXUS Personal Pro.lnk';$shell=New-Object -ComObject WScript.Shell
$shortcut=$shell.CreateShortcut($link);$shortcut.TargetPath=Join-Path $prior 'NEXUS Personal Pro.exe';$shortcut.Arguments=DeviceLaunchArgs $PriorSourceSha;$shortcut.Save()
function Links {return @($link)}
$linkRow=[pscustomobject]@{path=$link;sha=(Hash $link);target=$shortcut.TargetPath;arguments=$shortcut.Arguments}
$clone=[ordered]@{gui_links=@($linkRow)}
Write-Json $StageProof @{decision='synthetic-stage'};$script:ExpectedStageProofSha256=Hash $StageProof
Write-Json $CloneProof $clone;$script:ExpectedCloneProofSha256=Hash $CloneProof
$rehearsal=@{decision='PASS_DEVICE_JOURNAL_REHEARSAL';host='DESKTOP-1R1081M';source_sha=$ExpectedSourceSha;transaction_script_sha256=(Hash $PSCommandPath);real_owner_touched=$false;journal_advanced_fenced=$true;repeat_recovery_fenced=$true;locked_profile_copy_refused=$true;atomic_shortcut_restore_verified=$true;owner_watchdog_com_verified=$true}
Write-Json $RehearsalProof $rehearsal;$script:ExpectedRehearsalProofSha256=Hash $RehearsalProof
$null=AssertDeviceGuiLinks ([pscustomobject]$clone)
[IO.File]::AppendAllText($link,'changed')
Refused {AssertDeviceGuiLinks ([pscustomobject]$clone)} 'Changed GUI inventory accepted'
Assert ($ops.Count -eq 0) 'Shortcut rejection stopped a process'
$shortcut.Save();$linkRow.sha=Hash $link;Write-Json $CloneProof $clone;$script:ExpectedCloneProofSha256=Hash $CloneProof
# Verify installed artifact bytes, including packed UI and source seed, without starting it.
$required=@('NEXUS Personal Pro.exe','resources\app.asar','resources\nexus-product-server\nexus-product-server.exe','resources\source-sha.txt','resources\build-evidence.json','resources\nexus-source-seed.git\HEAD')
foreach($rel in $required){$p=Join-Path $candidate $rel;New-Item -ItemType Directory -Path (Split-Path -Parent $p) -Force|Out-Null;[IO.File]::WriteAllText($p,'synthetic-'+$rel)}
$fileProof=[pscustomobject]@{installed_files_verified_against_unpacked=$true;installed_files_unpacked_sha256=$ExpectedUnpackedSha256;installed_files=@(ProfileFiles $candidate)}
AssertDeviceInstalledFiles $fileProof
[IO.File]::AppendAllText((Join-Path $candidate 'NEXUS Personal Pro.exe'),'tampered')
Refused {AssertDeviceInstalledFiles $fileProof} 'Changed installed artifact accepted'
Assert ($ops.Count -eq 0) 'Installed-byte rejection stopped a process'
$store=Join-Path $PrivateRoot 'activation-transactions';$dir=Join-Path $store 'synthetic';New-Item -ItemType Directory -Path $dir -Force|Out-Null
Copy-Item -LiteralPath $PSCommandPath -Destination (Join-Path $dir 'recovery.ps1')
$backup=Join-Path $dir 'link-0.lnk';Copy-Item -LiteralPath $link -Destination $backup
$record=[pscustomobject]@{schema='nexus.owner-device-journal-activation.v1';binding=(DeviceBinding -Transaction);status='ACTIVATING';link_inventory=@($linkRow);links=@([pscustomobject]@{path=$link;existed=$true;sha=$linkRow.sha;copy=$backup});recovery_script_sha256=(Hash $PSCommandPath)}
Write-Json (Join-Path $dir 'transaction.json') $record
DeviceCheckRecord $record $dir
$args=DeviceRecoveryArguments $dir
foreach($pin in @($owner,$candidate,$prior,$PriorSourceSha,$ExpectedSourceSha,$ExpectedJournalSha256,$ExpectedCloneProofSha256,$ExpectedRehearsalProofSha256)){Assert ($args.Contains('"'+$pin+'"')) 'Watchdog dropped an identity argument'}
$record.status='UNKNOWN';Refused {DeviceCheckRecord $record $dir} 'Unknown recovery status accepted';$record.status='ACTIVATING'
$record.links[0].path=Join-Path $Scratch 'arbitrary.lnk';Refused {DeviceCheckRecord $record $dir} 'Arbitrary recovery destination accepted';$record.links[0].path=$link
$record.links[0].copy=Join-Path $Scratch 'outside-backup.lnk';Refused {DeviceCheckRecord $record $dir} 'External shortcut backup accepted';$record.links[0].copy=$backup
$savedPin=$ExpectedCloneProofSha256;$script:ExpectedCloneProofSha256='9'*64
Refused {DeviceCheckRecord $record $dir} 'Wrong clone proof pin accepted';$script:ExpectedCloneProofSha256=$savedPin
Assert ($ops.Count -eq 0) 'Invalid record/proof stopped a process'
# Candidate failure restores links and relaunches only the prior source/profile.
[IO.File]::WriteAllText($link,'candidate-shortcut');$script:candidateAlive=$true
DeviceRecover $dir
Assert ((Hash $link) -ceq $linkRow.sha -and (Hash $journal) -ceq $ExpectedJournalSha256) 'Rollback changed financial bytes or lost old link'
Assert ($ops.Count -eq 3 -and $ops[0] -eq 'stop-candidate' -and $ops[1] -ceq ('start-prior:'+(DeviceLaunchArgs $PriorSourceSha)) -and $ops[2] -eq 'health-prior') 'Rollback process/profile sequence differs'
$count=$ops.Count;DeviceRecover $dir;Assert ($ops.Count -eq $count) 'Completed recovery mutated again'
# A genuine next event fences both the first recovery and every later invocation.
$record.status='ACTIVATING';Write-Json (Join-Path $dir 'transaction.json') $record
Copy-Item -LiteralPath $Advanced -Destination $journal -Force;$advancedHash=Hash $journal
$script:ops=@();$script:candidateAlive=$true
Refused {DeviceRecover $dir} 'Advanced journal was replayed'
Assert ((JsonFile (Join-Path $dir 'transaction.json')).status -eq 'RECOVERY_NEEDS_REVIEW') 'Advanced journal not fenced'
Assert ((Hash $journal) -ceq $advancedHash -and $ops.Count -eq 1 -and $ops[0] -eq 'stop-candidate') 'Recovery touched journal/prior app'
$snapshot=@(ProfileFiles $Scratch);$count=$ops.Count
Refused {DeviceRecover $dir} 'Repeated advanced-journal recovery accepted'
Assert ($ops.Count -eq $count) 'Repeated recovery stopped a process'
foreach($entry in $snapshot){Assert ((Hash (Join-Path $Scratch $entry.rel)) -ceq $entry.sha) 'Repeated recovery mutated files'}
'DEVICE_JOURNAL_PROTOCOL_FAULTS=PASS'
''', encoding="utf-8")
    result = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                             str(harness), "-Production", str(SOURCE), "-Original", str(original),
                             "-Advanced", str(advanced), "-Scratch", str(tmp_path / "fixture")],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "DEVICE_JOURNAL_PROTOCOL_FAULTS=PASS" in result.stdout
