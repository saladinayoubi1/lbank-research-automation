# NEXUS owner GUI cutover. No Live authority. No GitHub token or reboot.
[CmdletBinding()]
param(
  [ValidateSet('Preflight','Rehearse','Activate','Recover')][string]$Mode='Preflight',
  [string]$ExpectedSourceSha='931a95b079682955cecb29a9eb404ec2e067ac7d',
  [string]$OldVersion='1931871b',
  [string]$StageProof='E:\NEXUS\proofs\stage-931a95b0-36327451730\official-stage-evidence.json',
  [string]$CloneProof='E:\NEXUS\proofs\stage-931a95b0-36327451730\private-clone-smoke-sanitized.json',
  [string]$PrivateRoot='E:\NEXUS\NEXUS_OWNER_PAPER_PRIVATE',
  [string]$TransactionDir='',
  [switch]$TestScheduler
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$expectedRepo='saladinayoubi1/lbank-research-automation'
$sourceShort=$ExpectedSourceSha.Substring(0,8)
$program=Join-Path $env:LOCALAPPDATA 'Programs\NEXUS Personal Pro'
$candidate=Join-Path $program "5.1.0-$sourceShort"
$prior=Join-Path $program "5.1.0-$OldVersion"
$owner=Join-Path $env:APPDATA 'nexus-personal-pro-product'
$syncTask='NEXUS Prospective Paper Sync'
$taskName="NEXUS-Activation-Rollback-$sourceShort"
$mutex=New-Object System.Threading.Mutex($false,'Local\NEXUS-OwnerActivation')
function Assert([bool]$Condition,[string]$Reason) { if(-not $Condition){throw $Reason} }
function JsonFile([string]$Path){Get-Content -LiteralPath $Path -Raw -ErrorAction Stop | ConvertFrom-Json}
function Write-Json([string]$Path,[object]$Object) {
  $temp="$Path.tmp";[IO.File]::WriteAllText($temp,($Object|ConvertTo-Json -Depth 7),(New-Object Text.UTF8Encoding($false)))
  Move-Item -LiteralPath $temp -Destination $Path -Force
}
function Hash([string]$Path){(Get-FileHash -LiteralPath $Path -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()}
function IsWithin([string]$File,[string]$Root){
  $r=[IO.Path]::GetFullPath($Root).TrimEnd('\')+'\'
  [IO.Path]::GetFullPath($File).StartsWith($r,[StringComparison]::OrdinalIgnoreCase)
}
function ExactProcs([string]$Root){
  @(Get-Process -Name 'NEXUS Personal Pro','nexus-product-server' -ErrorAction SilentlyContinue |
    Where-Object {$_.Path -and (IsWithin $_.Path $Root)})
}
function Stop-Exact([string]$Root,[int]$GraceSeconds=12) {
  Assert ($Root -in @($candidate,$prior)) 'Only the two bound installation roots can be stopped'
  $scope=Split-Path -Leaf $Root
  # Electron's healthy GUI supervises the Python sidecar: killing the sidecar
  # before the GUI host has exited can trigger an immediate replacement child.
  # Request a normal owner-window close first; NEVER signal an unrelated app.
  foreach($x in @(ExactProcs $Root)){
    if($x.ProcessName -eq 'NEXUS Personal Pro' -and $x.MainWindowHandle -ne 0){
      try{$null=$x.CloseMainWindow()}catch{}
    }
  }
  $graceUntil=[DateTime]::UtcNow.AddSeconds([Math]::Max(0,$GraceSeconds))
  do {
    if(@(ExactProcs $Root).Count -eq 0){break}
    Start-Sleep -Milliseconds 500
  }while([DateTime]::UtcNow -lt $graceUntil)

  # The prior one-snapshot stop loop could leave an engine re-created between
  # signals and the final check. Re-enumerate exact paths every bounded pass,
  # retire GUI hosts FIRST, then retire only orphaned exact-root sidecars.
  for($pass=1;$pass -le 4;$pass++){
    $hosts=@(ExactProcs $Root | Where-Object {$_.ProcessName -eq 'NEXUS Personal Pro'} | Sort-Object Id)
    foreach($x in $hosts){
      $again=Get-Process -Id $x.Id -ErrorAction SilentlyContinue
      if($again -and $again.ProcessName -eq 'NEXUS Personal Pro' -and $again.Path -and (IsWithin $again.Path $Root)){
        try{Stop-Process -Id $again.Id -Force -ErrorAction Stop}
        catch{
          $still=Get-Process -Id $x.Id -ErrorAction SilentlyContinue
          if($still -and $still.Path -and (IsWithin $still.Path $Root)){throw}
        }
      }
    }
    $hostDeadline=[DateTime]::UtcNow.AddSeconds(2)
    do {
      $hosts=@(ExactProcs $Root | Where-Object {$_.ProcessName -eq 'NEXUS Personal Pro'})
      if($hosts.Count -eq 0){break}
      Start-Sleep -Milliseconds 250
    }while([DateTime]::UtcNow -lt $hostDeadline)
    # Never kill an engine while its host is still alive and able to respawn it.
    if($hosts.Count -eq 0){
      foreach($x in @(ExactProcs $Root | Where-Object {$_.ProcessName -eq 'nexus-product-server'})){
        $again=Get-Process -Id $x.Id -ErrorAction SilentlyContinue
        if($again -and $again.ProcessName -eq 'nexus-product-server' -and $again.Path -and
          (IsWithin $again.Path $Root) -and
          @(ExactProcs $Root | Where-Object {$_.ProcessName -eq 'NEXUS Personal Pro'}).Count -eq 0){
          try{Stop-Process -Id $again.Id -Force -ErrorAction Stop}
          catch{
            $still=Get-Process -Id $x.Id -ErrorAction SilentlyContinue
            if($still -and $still.Path -and (IsWithin $still.Path $Root)){throw}
          }
        }
      }
    }
    # Several consecutive absent checks, not one transient empty snapshot.
    $stable=0
    while($stable -lt 5){
      if(@(ExactProcs $Root).Count -ne 0){break}
      $stable++
      Start-Sleep -Milliseconds 500
    }
    if($stable -eq 5){
      Write-Host "NEXUS_EXACT_QUIESCENCE=PASS scope=$scope passes=$pass"
      return
    }
    $left=@(ExactProcs $Root)
    $gui=@($left | Where-Object {$_.ProcessName -eq 'NEXUS Personal Pro'}).Count
    $engine=@($left | Where-Object {$_.ProcessName -eq 'nexus-product-server'}).Count
    Write-Host "NEXUS_EXACT_QUIESCENCE_RETRY scope=$scope pass=$pass gui=$gui engine=$engine"
  }
  $remaining=@(ExactProcs $Root)
  $gui=@($remaining | Where-Object {$_.ProcessName -eq 'NEXUS Personal Pro'}).Count
  $engine=@($remaining | Where-Object {$_.ProcessName -eq 'nexus-product-server'}).Count
  throw "Exact-version processes did not quiesce scope=$scope gui=$gui engine=$engine; no other install was signaled"
}
function ProfileFiles([string]$Root) {
  Assert (@(Get-ChildItem -LiteralPath $Root -Recurse -Force -ErrorAction Stop|Where-Object {$_.Attributes -band [IO.FileAttributes]::ReparsePoint}).Count -eq 0) 'Owner profile has reparse content'
  @(Get-ChildItem -LiteralPath $Root -File -Recurse -Force -ErrorAction Stop |
    ForEach-Object {
      Assert (($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) 'Profile contains a reparse file'
      [pscustomobject]@{rel=$_.FullName.Substring($Root.Length+1);sha=Hash $_.FullName;bytes=$_.Length}
    })
}
function ValidPaper([string]$Root) {
  $p=Join-Path $Root 'product-data\shared_paper\terminal.json'
  $j=JsonFile $p
  Assert ($j.read_only -eq $true -and $j.live_trading_authority -eq $false) 'Owner journal is not read-only and Live-locked'
  Assert ([decimal]$j.account.initial_balance -eq 500) 'Unexpected Paper initial balance'
  return $j
}
function CheckStage {
  Assert ($ExpectedSourceSha -match '^[a-f0-9]{40}$') 'Invalid source SHA'
  Assert ((Test-Path -LiteralPath $PrivateRoot -PathType Container) -and (Test-Path $StageProof) -and (Test-Path $CloneProof)) 'Private durability or stage evidence missing'
  $acl=Get-Acl -LiteralPath $PrivateRoot
  Assert (@($acl.Access|Where-Object {$_.AccessControlType -eq 'Allow' -and $_.IdentityReference.Value -match 'Everyone|BUILTIN\\Users|Authenticated Users'}).Count -eq 0) 'Private ACL too broad'
  $a=JsonFile $StageProof;$b=JsonFile $CloneProof
  Assert ($a.decision -eq 'PASS' -and $a.source_sha -eq $ExpectedSourceSha -and $a.final_launch.status -eq 'STAGED_ONLY_OWNER_PRESERVED') 'Official stage proof not exact'
  Assert ($a.smoke.visible_window_observed -eq $true -and $a.smoke.supervisor_healthy -eq $true -and $a.smoke.live_orders_allowed -eq $false) 'Official stage smoke incomplete'
  Assert ($b.decision -eq 'PASS_NO_OWNER_ACTIVATION' -and $b.source_sha -eq $ExpectedSourceSha -and $b.clone_visible_gui -eq $true -and $b.old_visible_gui_preserved -eq $true) 'Real-profile clone proof not exact'
  $m=JsonFile (Join-Path $candidate 'install-manifest.json')
  Assert ($m.source_sha -eq $ExpectedSourceSha -and $m.paper_only -eq $true -and $m.live_trading_authority -eq $false) 'Candidate manifest untrusted'
  Assert ((Test-Path (Join-Path $prior 'NEXUS Personal Pro.exe') -PathType Leaf) -and (Test-Path (Join-Path $candidate 'NEXUS Personal Pro.exe') -PathType Leaf)) 'Old or candidate executable missing'
  Assert (@(ExactProcs $candidate).Count -eq 0) 'Candidate must not be running at cutover'
  $old=@(ExactProcs $prior)
  Assert (@($old|Where-Object {$_.ProcessName -eq 'NEXUS Personal Pro' -and $_.MainWindowHandle -ne 0}).Count -eq 1) 'Exactly one visible prior GUI required'
  Assert ($old.Count -ge 2 -and $old.Count -le 15) 'Unexpected prior process population'
  $null=ValidPaper $owner # read from owner root
  $super=JsonFile (Join-Path $owner 'product-data\supervisor-state.json')
  Assert ($super.status -eq 'healthy' -and $super.live_trading_authority -eq $false) 'Current owner must be healthy and Live-locked'
  $sw=New-Object -ComObject WScript.Shell
  $shortcut=Join-Path ([Environment]::GetFolderPath('Desktop')) 'NEXUS Personal Pro 5.1.0.lnk'
  Assert ((Test-Path $shortcut) -and ($sw.CreateShortcut($shortcut).TargetPath).Equals((Join-Path $prior 'NEXUS Personal Pro.exe'),[StringComparison]::OrdinalIgnoreCase)) 'Owner desktop shortcut changed'
  return $true
}
function Links {
  @((Join-Path ([Environment]::GetFolderPath('Desktop')) 'NEXUS Personal Pro 5.1.0.lnk'),
    (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\NEXUS Personal Pro 5.1.0.lnk'),
    (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\NEXUS Personal Pro.lnk'),
    (Join-Path ([Environment]::GetFolderPath('Startup')) 'NEXUS Personal Pro.lnk'))
}
function BackupLinks([string]$Dir) {
  $result=@()
  foreach($p in @(Links)){ $i=$result.Count;$copy=Join-Path $Dir "link-$i.lnk"
    $exists=Test-Path -LiteralPath $p -PathType Leaf
    if($exists){Copy-Item -LiteralPath $p -Destination $copy -ErrorAction Stop}
    $result+=@{path=$p;existed=$exists;sha=if($exists){Hash $p}else{''};copy=$copy}
  }
  return $result
}
function RestoreLinks([object[]]$LinksData) {
  foreach($x in $LinksData) {
    if($x.existed){Assert ((Hash $x.copy) -eq $x.sha) 'Shortcut backup digest failed';Copy-Item -LiteralPath $x.copy -Destination $x.path -Force}
    elseif(Test-Path $x.path){Remove-Item -LiteralPath $x.path -Force}
    foreach($suffix in @('.nexus-new.lnk','.nexus-rollback-prior.lnk')){
      $orphan="$($x.path)$suffix"
      if(Test-Path -LiteralPath $orphan){Remove-Item -LiteralPath $orphan -Force -ErrorAction Stop}
    }
  }
}
function Health([string]$Expected,[int]$Timeout=425,[string]$InstallRoot=$candidate){
  $file=Join-Path $owner 'product-data\supervisor-state.json';$end=[DateTime]::UtcNow.AddSeconds($Timeout)
  do {
    try {
      $s=JsonFile $file
      if($s.status -eq 'healthy' -and $s.source_sha -eq $Expected -and $s.live_trading_authority -eq $false){
        $u=[uri]$s.origin
        Assert ($u.Host -in @('127.0.0.1','localhost','::1')) 'Untrusted gateway origin'
        $url=$u.AbsoluteUri.TrimEnd('/')
        $p=Invoke-RestMethod "$url/api/product/paper" -TimeoutSec 5
        $live=Invoke-RestMethod "$url/api/product/live" -TimeoutSec 5
        $build=Invoke-RestMethod "$url/api/product/build-evidence" -TimeoutSec 5
        $st=Invoke-RestMethod "$url/api/product/strategies/evidence" -TimeoutSec 5
        $ov=Invoke-RestMethod "$url/api/product/overview" -TimeoutSec 5
        $mission=Invoke-RestMethod "$url/api/product/mission/full" -TimeoutSec 5
        Assert ($p.paper_only -eq $true -and $live.live_trading_authority -eq $false -and $live.orders_allowed -eq $false) 'Paper/Live safety contract failed'
        Assert ($build.source_sha -eq $Expected -and $build.exact_source -eq $true -and $st.paper_only -eq $true -and $st.profitability_claim -eq $false) 'Source/strategy contract failed'
        Assert ($ov.capabilities.deterministic_risk -eq 'final_paper_authority' -and $mission.live_trading_authority -eq $false) 'Risk/Mission authority failed'
        $null=ValidPaper $owner
        $win=@(ExactProcs $InstallRoot|Where-Object {$_.ProcessName -eq 'NEXUS Personal Pro' -and $_.MainWindowHandle -ne 0})
        if($win.Count -eq 1){return $true}
      }
    }catch { if($_.Exception.Message -match 'Untrusted gateway|safety contract|authority failed'){throw} }
    Start-Sleep -Seconds 5
  }while([DateTime]::UtcNow -lt $end)
  throw 'Exact owner GUI or health endpoint did not become ready in bounded window'
}
function RestoreProfile([string]$Dir){
  $meta=JsonFile (Join-Path $Dir 'transaction.json');$backup=Join-Path $Dir 'profile'
  foreach($x in @($meta.files)) {Assert ((Hash (Join-Path $backup $x.rel)) -eq $x.sha) 'Owner profile backup checksum failed'}
  if(Test-Path $owner){$quarantine=Join-Path $Dir 'failed-candidate-profile';if(!(Test-Path $quarantine)){Copy-Item -LiteralPath $owner -Destination $quarantine -Recurse}}
  if(Test-Path $owner){Remove-Item -LiteralPath $owner -Recurse -Force}
  Copy-Item -LiteralPath $backup -Destination $owner -Recurse
  foreach($x in @($meta.files)){Assert ((Hash (Join-Path $owner $x.rel)) -eq $x.sha) 'Owner profile rollback checksum failed'}
}
function Finish-Rollback([object]$Transaction,[string]$Dir){
  $Transaction.status='ROLLED_BACK'
  $Transaction|Add-Member -NotePropertyName rolled_back_at -NotePropertyValue ([DateTime]::UtcNow.ToString('o')) -Force
  Write-Json (Join-Path $Dir 'transaction.json') $Transaction
}
function Rollback([string]$Dir){
  $t=JsonFile (Join-Path $Dir 'transaction.json')
  if($t.status -in @('COMMITTED','ROLLED_BACK')){return}
  if($t.status -eq 'RECOVERY_NEEDS_REVIEW'){throw 'Prior recovery needs independent owner review; will not overwrite newer Paper'}
  # A previous rollback may already have restarted the old GUI and generated
  # newer Paper events. The timed watchdog must NEVER overwrite those events.
  $existingOld=@(ExactProcs $prior)
  $existingNew=@(ExactProcs $candidate)
  # Stop only the exact candidate before assessing an unexpectedly revived old owner.
  # A healthy old GUI may already have added newer Paper events: never stop it
  # or replay an older snapshot merely because a candidate also lingered.
  if($existingNew.Count){
    Stop-Exact $candidate 4
    $existingNew=@(ExactProcs $candidate)
  }
  $existingOld=@(ExactProcs $prior)
  $oldWindow=@($existingOld|Where-Object {$_.ProcessName -eq 'NEXUS Personal Pro' -and $_.MainWindowHandle -ne 0})
  if($t.status -in @('STARTED','BACKED_UP','ACTIVATING') -and !$existingNew.Count -and $oldWindow.Count -eq 1){
    $oldSource=(Get-Content -LiteralPath (Join-Path $prior 'resources\source-sha.txt') -Raw -ErrorAction Stop).Trim()
    $state=JsonFile (Join-Path $owner 'product-data\supervisor-state.json')
    if($state.status -eq 'healthy' -and $state.source_sha -eq $oldSource -and $state.live_trading_authority -eq $false){
      $null=ValidPaper $owner
      if($t.links){RestoreLinks @($t.links)}
      if($t.sync_was_enabled -eq $true){
        $service=New-Object -ComObject Schedule.Service;$service.Connect()
        $service.GetFolder('\').GetTask($syncTask).Enabled=$true
      }
      $currentJournal=Join-Path $owner 'product-data\shared_paper\terminal.json'
      $newerCopy=Join-Path $Dir 'newer-paper-post-recovery.json'
      $captured=$false
      for($attempt=0;$attempt -lt 5;$attempt++){
        $first=Hash $currentJournal
        Copy-Item -LiteralPath $currentJournal -Destination $newerCopy -Force
        if((Hash $currentJournal) -eq $first -and (Hash $newerCopy) -eq $first){$captured=$true;break}
        Start-Sleep -Milliseconds 250
      }
      if(!$captured){
        $t.status='RECOVERY_NEEDS_REVIEW';Write-Json (Join-Path $Dir 'transaction.json') $t
        throw 'Progressing Paper journal could not be captured consistently; never replay the old snapshot'
      }
      Finish-Rollback $t $Dir
      return
    }
  }
  # If old is already running but not yet healthy, do not destroy its possible
  # new writes. An operator can diagnose instead of replaying stale account data.
  if($t.status -in @('STARTED','BACKED_UP','ACTIVATING') -and !$existingNew.Count -and $existingOld.Count -gt 0){
    $t.status='RECOVERY_NEEDS_REVIEW';Write-Json (Join-Path $Dir 'transaction.json') $t
    throw 'Existing previous GUI is starting: refusing repeated destructive rollback'
  }
  Stop-Exact $candidate 4
  if(@(ExactProcs $prior).Count){Stop-Exact $prior 3}
  if($t.status -in @('BACKED_UP','ACTIVATING') -and (Test-Path (Join-Path $Dir 'profile'))){
    $savedPaper=Join-Path $Dir 'profile\product-data\shared_paper\terminal.json'
    $currentPaper=Join-Path $owner 'product-data\shared_paper\terminal.json'
    if((Test-Path $savedPaper) -and (Test-Path $currentPaper) -and ((Hash $currentPaper) -ne (Hash $savedPaper))){
      $copy=Join-Path $Dir 'unreplayed-current-paper.json'
      $before=Hash $currentPaper
      Copy-Item -LiteralPath $currentPaper -Destination $copy -Force
      $t.status='RECOVERY_NEEDS_REVIEW';Write-Json (Join-Path $Dir 'transaction.json') $t
      Assert ((Hash $currentPaper) -eq $before -and (Hash $copy) -eq $before) 'Paper journal changed during safety capture'
      throw 'Current Paper differs from activation snapshot: newer events quarantined; obsolete rollback prohibited'
    }
    RestoreProfile $Dir
  }
  if($t.links){RestoreLinks @($t.links)}
  $env:RUNNER_TRACKING_ID=$null
  $null=Start-Process -FilePath (Join-Path $prior 'NEXUS Personal Pro.exe')
  $oldSource=(Get-Content -LiteralPath (Join-Path $prior 'resources\source-sha.txt') -Raw -ErrorAction Stop).Trim()
  Assert ($oldSource -match '^[0-9a-f]{40}$') 'Previous source binding is invalid'
  try{$null=Health $oldSource 425 $prior}
  catch {
    $t.status='RECOVERY_NEEDS_REVIEW';Write-Json (Join-Path $Dir 'transaction.json') $t
    throw 'Previous GUI needs independent recovery review; refusing future automatic overwrite'
  }
  if($t.sync_was_enabled -eq $true){
    $service=New-Object -ComObject Schedule.Service;$service.Connect()
    $service.GetFolder('\').GetTask($syncTask).Enabled=$true
  }
  Finish-Rollback $t $Dir
}
function Rehearse {
  $r=Join-Path $env:TEMP ('nexus-activation-synthetic-'+[guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Force -Path $r|Out-Null
  $actualOwner=$script:owner
  try{
    $script:owner=Join-Path $r 'synthetic-owner'
    $work=Join-Path $script:owner 'product-data\\shared_paper'
    New-Item -ItemType Directory -Path $work -Force|Out-Null
    $journal=Join-Path $work 'terminal.json'
    [IO.File]::WriteAllText($journal,'{"read_only":true,"live_trading_authority":false,"account":{"initial_balance":500}}')
    $orig=Hash $journal
    $files=@(ProfileFiles $script:owner)
    $txn=Join-Path $r 'transaction';New-Item -ItemType Directory $txn|Out-Null
    $b=Join-Path $txn 'profile';Copy-Item $script:owner $b -Recurse
    Assert ((Hash (Join-Path $b 'product-data\\shared_paper\\terminal.json')) -eq $orig) 'Synthetic snapshot copy failed'
    $link=Join-Path $r 'synthetic-shortcut.lnk';$linkBackup=Join-Path $r 'old-link.lnk'
    [IO.File]::WriteAllText($link,'old-executable');Copy-Item $link $linkBackup
    $linkMeta=@{path=$link;existed=$true;copy=$linkBackup;sha=Hash $link}
    $meta=[ordered]@{status='BACKED_UP';files=$files;links=@($linkMeta)}
    Write-Json (Join-Path $txn 'transaction.json') $meta
    [IO.File]::WriteAllText($journal,'{"read_only":true,"live_trading_authority":false,"account":{"initial_balance":1}}')
    [IO.File]::WriteAllText($link,'failed-new-executable')
    RestoreProfile $txn
    RestoreLinks @($linkMeta)
    Assert ((Hash $journal) -eq $orig -and (Hash $link) -eq $linkMeta.sha) 'Synthetic profile/shortcut rollback failed'
    $linkTemp="$link.nexus-new.lnk";$linkPrior="$link.nexus-rollback-prior.lnk"
    [IO.File]::WriteAllText($linkTemp,'synthetic-candidate-shortcut')
    [IO.File]::Replace($linkTemp,$link,$linkPrior)
    Assert ((Get-Content $link -Raw) -eq 'synthetic-candidate-shortcut') 'Atomic synthetic shortcut switch failed'
    Assert ((Hash $linkPrior) -eq $linkMeta.sha) 'Atomic shortcut prior backup was damaged'
    RestoreLinks @($linkMeta)
    Assert ((Hash $link) -eq $linkMeta.sha -and !(Test-Path $linkPrior)) 'Atomic shortcut rollback/cleanup failed'
    'SYNTHETIC_OWNER_ACTIVATION_REHEARSAL=PASS profile-copy, corruption detection, shortcut rollback; no real state'
    if($TestScheduler){
      $testName="NEXUS-Activation-REHEARSAL-$sourceShort"
      $service=New-Object -ComObject Schedule.Service;$service.Connect();$folder=$service.GetFolder('\')
      try{
        $d=$service.NewTask(0);$d.Principal.LogonType=3;$d.Principal.RunLevel=0
        $d.Principal.UserId=[Security.Principal.WindowsIdentity]::GetCurrent().Name
        $t=$d.Triggers.Create(1);$t.StartBoundary=[DateTime]::Now.AddMinutes(20).ToString('s')
        $a=$d.Actions.Create(0);$a.Path=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $a.Arguments='-NoProfile -NonInteractive -Command "exit 0"'
        $d.Settings.Enabled=$true
        $registered=$folder.RegisterTaskDefinition($testName,$d,6,$null,$null,3,$null)
        Assert ($registered.Enabled -eq $true) 'Owner COM watchdog registration rehearsal failed'
        'SYNTHETIC_OWNER_WATCHDOG_COM=PASS disposable task registered'
      }finally{try{$folder.DeleteTask($testName,0)}catch{}}
    }
  }finally{$script:owner=$actualOwner;Remove-Item -LiteralPath $r -Force -Recurse -ErrorAction SilentlyContinue}
}
if($Mode -eq 'Rehearse'){Rehearse;exit 0}
if($Mode -eq 'Preflight'){ $null=CheckStage;'EXACT_OWNER_PREFLIGHT=PASS no mutation';exit 0 }
if($Mode -eq 'Recover'){
  Assert ($TransactionDir -and (IsWithin $TransactionDir (Join-Path $PrivateRoot 'activation-transactions'))) 'Untrusted recovery transaction'
  $t=JsonFile (Join-Path $TransactionDir 'transaction.json')
  Assert ($t.expected_sha -eq $ExpectedSourceSha -and $t.old_version -eq $OldVersion) 'Recovery manifest mismatch'
  if($t.status -eq 'COMMITTED'){exit 0}
  Rollback $TransactionDir;'AUTOMATIC_OWNER_ROLLBACK=PASS';exit 0
}
Assert ($Mode -eq 'Activate') 'Unknown operation'
$locked=$false;$transaction=$null;$scheduled=$null;$oldSyncEnabled=$null
try{
  $locked=$mutex.WaitOne([TimeSpan]::FromSeconds(2))
  Assert $locked 'Owner activation already running'
  $null=CheckStage
  $scheduler=New-Object -ComObject Schedule.Service;$scheduler.Connect()
  $folder=$scheduler.GetFolder('\');$sync=$folder.GetTask($syncTask)
  Assert ($sync.State -eq 3 -and $sync.Enabled) 'Prospective sync must be idle and enabled'
  $oldSyncEnabled=$sync.Enabled
  $store=Join-Path $PrivateRoot 'activation-transactions'
  if(!(Test-Path $store)){New-Item -ItemType Directory -Path $store|Out-Null}
  $transaction=Join-Path $store ("$sourceShort-"+[DateTime]::UtcNow.ToString('yyyyMMddHHmmss'))
  New-Item -ItemType Directory -Path $transaction -ErrorAction Stop|Out-Null
  Copy-Item -LiteralPath $PSCommandPath -Destination (Join-Path $transaction 'recovery.ps1')
  $record=[ordered]@{schema='nexus.owner-activation-transaction.v1';expected_sha=$ExpectedSourceSha;old_version=$OldVersion;status='STARTED';sync_was_enabled=$oldSyncEnabled;files=@();links=@();created_at=[DateTime]::UtcNow.ToString('o')}
  Write-Json (Join-Path $transaction 'transaction.json') $record
  # Pre-arm owner-session watchdog before changing any owner process or state.
  $def=$scheduler.NewTask(0);$def.RegistrationInfo.Description='NEXUS failed-closed owner rollback'
  $def.Principal.LogonType=3;$def.Principal.RunLevel=0;$def.Principal.UserId=[Security.Principal.WindowsIdentity]::GetCurrent().Name
  $tr=$def.Triggers.Create(1);$tr.StartBoundary=[DateTime]::Now.AddMinutes(14).ToString('s');$tr.Enabled=$true
  $act=$def.Actions.Create(0);$act.Path=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
  $act.Arguments='-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+(Join-Path $transaction 'recovery.ps1')+'" -Mode Recover -ExpectedSourceSha '+$ExpectedSourceSha+' -OldVersion '+$OldVersion+' -PrivateRoot "'+$PrivateRoot+'" -TransactionDir "'+$transaction+'"'
  $def.Settings.Enabled=$true;$def.Settings.StartWhenAvailable=$true
  $def.Settings.MultipleInstances=2
  try{$existing=$folder.GetTask($taskName)}catch{$existing=$null}
  Assert ($null -eq $existing) 'A previous owner rollback watchdog still exists: investigate first'
  $scheduled=$folder.RegisterTaskDefinition($taskName,$def,6,$null,$null,3,$null)
  Assert ($scheduled.Enabled -eq $true) 'Rollback watchdog could not be armed'
  $sync.Enabled=$false
  Stop-Exact $prior 15
  Assert (@(ExactProcs $prior).Count -eq 0) 'Old process relaunch during quiescence'
  $null=ValidPaper $owner
  $files=@(ProfileFiles $owner)
  Assert ($files.Count -gt 0 -and $files.Count -lt 100000) 'Owner profile file count invalid'
  $copy=Join-Path $transaction 'profile'
  Copy-Item -LiteralPath $owner -Destination $copy -Recurse -ErrorAction Stop
  foreach($x in $files){
    Assert ((Hash (Join-Path $copy $x.rel)) -eq $x.sha -and (Hash (Join-Path $owner $x.rel)) -eq $x.sha) 'Owner backup or live source drift'
  }
  $record.files=$files;$record.links=@(BackupLinks $transaction);$record.status='BACKED_UP'
  Write-Json (Join-Path $transaction 'transaction.json') $record
  Assert (@(ExactProcs $prior).Count -eq 0) 'Old version relaunched before candidate'
  $env:RUNNER_TRACKING_ID=$null
  $record.status='ACTIVATING';Write-Json (Join-Path $transaction 'transaction.json') $record
  $null=Start-Process -FilePath (Join-Path $candidate 'NEXUS Personal Pro.exe')
  $null=Health $ExpectedSourceSha 425
  Assert (@(ExactProcs $prior).Count -eq 0) 'Prior app unexpectedly relaunched'
  # Switch shortcuts only after real owner profile and exact new GUI are healthy.
  $shell=New-Object -ComObject WScript.Shell
  foreach($l in $record.links){
    $tmp="$($l.path).nexus-new.lnk"
    $shortcut=$shell.CreateShortcut($tmp);$shortcut.TargetPath=Join-Path $candidate 'NEXUS Personal Pro.exe'
    $shortcut.WorkingDirectory=$candidate;$shortcut.Save()
    if(Test-Path -LiteralPath $l.path){
      $priorSibling="$($l.path).nexus-rollback-prior.lnk"
      Assert (!(Test-Path -LiteralPath $priorSibling)) 'Unexpected previous shortcut sibling: investigate first'
      [IO.File]::Replace($tmp,$l.path,$priorSibling)
    }
    else {Move-Item -LiteralPath $tmp -Destination $l.path}
  }
  # Read each committed shortcut back through Windows COM, and retain its
  # exact pre-activation hash via the named File.Replace sibling until commit.
  $newExecutable=Join-Path $candidate 'NEXUS Personal Pro.exe'
  foreach($l in $record.links){
    Assert ((Test-Path -LiteralPath $l.path -PathType Leaf) -and
      $shell.CreateShortcut($l.path).TargetPath.Equals($newExecutable,[StringComparison]::OrdinalIgnoreCase)) 'Post-switch shortcut target mismatch'
    if($l.existed){
      $sibling="$($l.path).nexus-rollback-prior.lnk"
      Assert ((Test-Path -LiteralPath $sibling -PathType Leaf) -and
        (Hash $sibling) -eq $l.sha) 'Atomic switch modified original shortcut bytes'
    }
  }
  Assert (@(ExactProcs $prior).Count -eq 0) 'Prior app restarted during shortcut commit'
  $null=Health $ExpectedSourceSha 35
  $sync.Enabled=$oldSyncEnabled
  $record.status='COMMITTED';$record.committed_at=[DateTime]::UtcNow.ToString('o')
  Write-Json (Join-Path $transaction 'transaction.json') $record
  foreach($l in $record.links){
    foreach($suffix in @('.nexus-new.lnk','.nexus-rollback-prior.lnk')){
      $extra="$($l.path)$suffix"
      if(Test-Path -LiteralPath $extra){Remove-Item -LiteralPath $extra -Force -ErrorAction SilentlyContinue}
    }
  }
  try{$folder.DeleteTask($taskName,0)}catch{}
  'EXACT_OWNER_ACTIVATION=PASS new owner GUI verified; rollback backup retained'
}catch{
  $reason=$_.Exception.Message
  if($transaction -and (Test-Path (Join-Path $transaction 'transaction.json'))){
    try{
      Rollback $transaction
      if((JsonFile (Join-Path $transaction 'transaction.json')).status -eq 'ROLLED_BACK'){
        try{$folder.DeleteTask($taskName,0)}catch{}
      }
    }catch{Write-Warning ('RECOVERY_REQUIRED private transaction='+$transaction)}
  }
  if($oldSyncEnabled -ne $null){try{$sync.Enabled=$oldSyncEnabled}catch{}}
  throw "Owner activation failed closed: $reason"
}finally{if($locked){$mutex.ReleaseMutex()};$mutex.Dispose()}
