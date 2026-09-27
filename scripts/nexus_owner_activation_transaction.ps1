# NEXUS owner GUI cutover. No Live authority. No GitHub token or reboot.
[CmdletBinding()]
param(
  [ValidateSet('Preflight','Rehearse','Activate','Recover')][string]$Mode='Preflight',
  [string]$ExpectedSourceSha='931a95b079682955cecb29a9eb404ec2e067ac7d',
  [string]$OldVersion='1931871b',
  [string]$StageProof='E:\NEXUS\proofs\stage-931a95b0-36327451730\official-stage-evidence.json',
  [string]$CloneProof='E:\NEXUS\proofs\stage-931a95b0-36327451730\private-clone-smoke-sanitized.json',
  [string]$PrivateRoot='E:\NEXUS\NEXUS_OWNER_PAPER_PRIVATE',
  [string]$TransactionDir=''
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
  $p=@(ExactProcs $Root)
  foreach($x in $p){if($x.MainWindowHandle -ne 0){try{$null=$x.CloseMainWindow()}catch{}}}
  $limit=[DateTime]::UtcNow.AddSeconds($GraceSeconds)
  do { $left=@(ExactProcs $Root);if(!$left.Count){break};Start-Sleep -Milliseconds 500 }
  while([DateTime]::UtcNow -lt $limit)
  foreach($x in @(ExactProcs $Root)) {
    $again=Get-Process -Id $x.Id -ErrorAction SilentlyContinue
    if($again -and $again.Path -and (IsWithin $again.Path $Root)){Stop-Process -Id $again.Id -Force -ErrorAction Stop}
  }
  Start-Sleep -Seconds 2
  Assert (@(ExactProcs $Root).Count -eq 0) 'Exact-version processes did not quiesce'
}
function ProfileFiles([string]$Root) {
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
  Assert ($b.decision -eq 'PASS_NO_OWNER_ACTIVATION' -and $b.source_sha -eq $ExpectedSourceSha -and $b.clone_visible -eq $true -and $b.old_visible -eq $true) 'Real-profile clone proof not exact'
  $m=JsonFile (Join-Path $candidate 'install-manifest.json')
  Assert ($m.source_sha -eq $ExpectedSourceSha -and $m.paper_only -eq $true -and $m.live_trading_authority -eq $false) 'Candidate manifest untrusted'
  Assert ((Test-Path (Join-Path $prior 'NEXUS Personal Pro.exe') -PathType Leaf) -and (Test-Path (Join-Path $candidate 'NEXUS Personal Pro.exe') -PathType Leaf)) 'Old or candidate executable missing'
  Assert (@(ExactProcs $candidate).Count -eq 0) 'Candidate must not be running at cutover'
  $old=@(ExactProcs $prior)
  Assert (@($old|Where-Object {$_.ProcessName -eq 'NEXUS Personal Pro' -and $_.MainWindowHandle -ne 0}).Count -eq 1) 'Exactly one visible prior GUI required'
  Assert ($old.Count -ge 2 -and $old.Count -le 15) 'Unexpected prior process population'
  $null=ValidPaper (Join-Path $owner 'product-data' '..') # read from owner root
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
  return ,$result
}
function RestoreLinks([object[]]$LinksData) {
  foreach($x in $LinksData) {
    if($x.existed){Assert ((Hash $x.copy) -eq $x.sha) 'Shortcut backup digest failed';Copy-Item -LiteralPath $x.copy -Destination $x.path -Force}
    elseif(Test-Path $x.path){Remove-Item -LiteralPath $x.path -Force}
  }
}
function Health([string]$Expected,[int]$Timeout=425){
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
        $win=@(ExactProcs $candidate|Where-Object {$_.ProcessName -eq 'NEXUS Personal Pro' -and $_.MainWindowHandle -ne 0})
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
function Rollback([string]$Dir){
  $t=JsonFile (Join-Path $Dir 'transaction.json')
  if($t.status -eq 'COMMITTED'){return}
  Stop-Exact $candidate 4
  if(@(ExactProcs $prior).Count){Stop-Exact $prior 3}
  if(Test-Path (Join-Path $Dir 'profile')){RestoreProfile $Dir}
  if($t.links){RestoreLinks @($t.links)}
  $env:RUNNER_TRACKING_ID=$null
  $null=Start-Process -FilePath (Join-Path $prior 'NEXUS Personal Pro.exe')
  $t.status='ROLLED_BACK';$t.rolled_back_at=[DateTime]::UtcNow.ToString('o');Write-Json (Join-Path $Dir 'transaction.json') $t
}
function Rehearse {
  $r=Join-Path $env:TEMP ('nexus-activation-synthetic-'+[guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Force -Path $r|Out-Null
  try{
    $original=Join-Path $r 'owner.txt';$backup=Join-Path $r 'backup.txt'
    [IO.File]::WriteAllText($original,'original-paper-only-state')
    $sha=Hash $original;Copy-Item $original $backup
    [IO.File]::WriteAllText($original,'synthetic-failed-activation')
    Assert ((Hash $backup) -eq $sha) 'Synthetic backup damaged'
    Copy-Item $backup $original -Force
    Assert ((Hash $original) -eq $sha) 'Synthetic rollback failed'
    'SYNTHETIC_OWNER_ACTIVATION_REHEARSAL=PASS no real profile or processes touched'
  }finally{Remove-Item -LiteralPath $r -Force -Recurse -ErrorAction SilentlyContinue}
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
  $record=[ordered]@{schema='nexus.owner-activation-transaction.v1';expected_sha=$ExpectedSourceSha;old_version=$OldVersion;status='STARTED';files=@();links=@();created_at=[DateTime]::UtcNow.ToString('o')}
  Write-Json (Join-Path $transaction 'transaction.json') $record
  # Pre-arm owner-session watchdog before changing any owner process or state.
  $def=$scheduler.NewTask(0);$def.RegistrationInfo.Description='NEXUS failed-closed owner rollback'
  $def.Principal.LogonType=3;$def.Principal.RunLevel=0;$def.Principal.UserId=[Security.Principal.WindowsIdentity]::GetCurrent().Name
  $tr=$def.Triggers.Create(1);$tr.StartBoundary=[DateTime]::Now.AddMinutes(14).ToString('s');$tr.Enabled=$true
  $act=$def.Actions.Create(0);$act.Path=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
  $act.Arguments='-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+(Join-Path $transaction 'recovery.ps1')+'" -Mode Recover -ExpectedSourceSha '+$ExpectedSourceSha+' -OldVersion '+$OldVersion+' -PrivateRoot "'+$PrivateRoot+'" -TransactionDir "'+$transaction+'"'
  $def.Settings.Enabled=$true;$def.Settings.StartWhenAvailable=$true
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
  $null=Start-Process -FilePath (Join-Path $candidate 'NEXUS Personal Pro.exe')
  $null=Health $ExpectedSourceSha 425
  Assert (@(ExactProcs $prior).Count -eq 0) 'Prior app unexpectedly relaunched'
  # Switch shortcuts only after real owner profile and exact new GUI are healthy.
  $shell=New-Object -ComObject WScript.Shell
  foreach($l in $record.links){
    $tmp="$($l.path).nexus-new"
    $shortcut=$shell.CreateShortcut($tmp);$shortcut.TargetPath=Join-Path $candidate 'NEXUS Personal Pro.exe'
    $shortcut.WorkingDirectory=$candidate;$shortcut.Save()
    Move-Item -LiteralPath $tmp -Destination $l.path -Force
  }
  $record.status='COMMITTED';$record.committed_at=[DateTime]::UtcNow.ToString('o')
  Write-Json (Join-Path $transaction 'transaction.json') $record
  $sync.Enabled=$oldSyncEnabled
  try{$folder.DeleteTask($taskName,0)}catch{}
  'EXACT_OWNER_ACTIVATION=PASS new owner GUI verified; rollback backup retained'
}catch{
  $reason=$_.Exception.Message
  if($transaction -and (Test-Path (Join-Path $transaction 'transaction.json'))){
    try{Rollback $transaction}catch{Write-Warning ('RECOVERY_REQUIRED private transaction='+$transaction)}
  }
  if($oldSyncEnabled -ne $null){try{$sync.Enabled=$oldSyncEnabled}catch{}}
  throw "Owner activation failed closed: $reason"
}finally{if($locked){$mutex.ReleaseMutex()};$mutex.Dispose()}
