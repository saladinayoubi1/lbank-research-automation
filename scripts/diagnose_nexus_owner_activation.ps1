[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-fA-F]{40}$')][string]$ExpectedOwnerSourceSha,
  [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ExpectedOwnerJournalSha256,
  [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-fA-F]{40}$')][string]$ExpectedStageSourceSha,
  [Parameter(Mandatory=$true)][long]$ExpectedStageArtifactId,
  [string]$StageProofPath,
  [string]$BackupRoot
)
Set-StrictMode -Version 2.0
$ErrorActionPreference='Stop'
# Strictly read-only: this diagnostic never activates, terminates, retargets, or backs up.
$ExpectedOwnerSourceSha=$ExpectedOwnerSourceSha.ToLowerInvariant()
$ExpectedStageSourceSha=$ExpectedStageSourceSha.ToLowerInvariant()
$ExpectedOwnerJournalSha256=$ExpectedOwnerJournalSha256.ToLowerInvariant()
$program=Join-Path $env:LOCALAPPDATA 'Programs\NEXUS Personal Pro'
$ownerRoot=Join-Path $program ('5.1.0-'+$ExpectedOwnerSourceSha.Substring(0,8))
$ownerExe=Join-Path $ownerRoot 'NEXUS Personal Pro.exe'
$stageRoot=Join-Path $program ('5.1.0-'+$ExpectedStageSourceSha.Substring(0,8))
$stateFile=Join-Path $env:APPDATA 'nexus-personal-pro-product\product-data\supervisor-state.json'
$journal=Join-Path $env:APPDATA 'nexus-personal-pro-product\product-data\product_runtime\paper-events.jsonl'
function Assert-File([string]$Path,[string]$Message) {
  if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){throw $Message}
}
Assert-File $ownerExe 'EXPECTED_OWNER_EXECUTABLE_MISSING'
Assert-File $stateFile 'OWNER_STATE_MISSING'
Assert-File $journal 'OWNER_JOURNAL_MISSING'
$hash=(Get-FileHash -LiteralPath $journal -Algorithm SHA256).Hash.ToLowerInvariant()
if($hash -ne $ExpectedOwnerJournalSha256){throw 'OWNER_JOURNAL_SHA_MISMATCH'}
$state=Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
if($state.status -ne 'healthy' -or ([string]$state.source_sha).ToLowerInvariant() -ne $ExpectedOwnerSourceSha){throw 'OWNER_SUPERVISOR_NOT_EXACT_HEALTHY'}
$origin=[string]$state.origin
if($origin -notmatch '^http://127\.0\.0\.1:[0-9]+$'){throw 'OWNER_ORIGIN_NOT_LOOPBACK'}
$paper=Invoke-RestMethod -Uri ($origin+'/api/product/paper') -TimeoutSec 10
$live=Invoke-RestMethod -Uri ($origin+'/api/product/live') -TimeoutSec 10
if($paper.paper_only -ne $true -or [string]$paper.account.cash -ne '500' -or [string]$paper.account.equity -ne '500' -or
  @($paper.account.positions).Count -gt 0 -or $live.live_trading_authority -ne $false -or $live.orders_allowed -ne $false){
  throw 'OWNER_PAPER_OR_LIVE_CONTRACT_UNSAFE'
}
$w=New-Object -ComObject WScript.Shell
$links=@(
  (Join-Path ([Environment]::GetFolderPath('Desktop')) 'NEXUS Personal Pro 5.1.0.lnk'),
  (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\NEXUS Personal Pro 5.1.0.lnk'),
  (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\NEXUS Personal Pro.lnk'),
  (Join-Path ([Environment]::GetFolderPath('Startup')) 'NEXUS Personal Pro.lnk')
)
foreach($link in $links){
  Assert-File $link 'OWNER_SHORTCUT_MISSING'
  if($w.CreateShortcut($link).TargetPath -ine $ownerExe){throw 'OWNER_SHORTCUT_TARGET_MISMATCH'}
}
function Get-OwnerProcessSnapshot {
  $all=@(Get-Process 'NEXUS Personal Pro','nexus-product-server' -ErrorAction SilentlyContinue)
  $ownerGui=@($all|Where-Object {try{$_.ProcessName -eq 'NEXUS Personal Pro' -and $_.Path -ieq $ownerExe}catch{$false}})
  $otherProduct=@($all|Where-Object {try{$_.Path -and $_.Path.StartsWith($program+'\',[StringComparison]::OrdinalIgnoreCase) -and
    -not $_.Path.StartsWith($ownerRoot+'\',[StringComparison]::OrdinalIgnoreCase)}catch{$false}})
  return [pscustomobject]@{owner_gui=$ownerGui; other_installs=$otherProduct;
    pids=@($ownerGui|Select-Object -ExpandProperty Id|Sort-Object)}
}
$s1=Get-OwnerProcessSnapshot
Start-Sleep -Seconds 2
$s2=Get-OwnerProcessSnapshot
if($s1.owner_gui.Count -eq 0 -or @($s2.owner_gui|Where-Object {$_.MainWindowHandle -ne 0}).Count -eq 0){throw 'OWNER_VISIBLE_GUI_MISSING'}
$pidsStable=([string]::Join(',',@($s1.pids)) -eq [string]::Join(',',@($s2.pids)))
$taskClass='UNKNOWN'
$taskState='UNAVAILABLE'
try{
  $svc=New-Object -ComObject Schedule.Service
  $svc.Connect()
  $t=$svc.GetFolder('\').GetTask('NEXUS-ZeroTouch-Autopilot')
  $taskState=if($t.Enabled){'ENABLED'}else{'DISABLED'}
  $actions=@($t.Definition.Actions)
  if($actions.Count -eq 1 -and [string]$actions[0].Arguments -match 'nexus_windows_autostart\.ps1' -and
    [string]$actions[0].Arguments -match '\-Mode RunDaemon'){
    $taskClass='PYTHON_LOCAL_SUPERVISOR_NOT_DIRECT_GUI'
  }else{$taskClass='UNRECOGNIZED_REVIEW_REQUIRED'}
}catch{$taskState='UNAVAILABLE'}
$stageStatus='NOT_STAGED'
if(Test-Path -LiteralPath $stageRoot){
  $manifestPath=Join-Path $stageRoot 'install-manifest.json'
  $srcPath=Join-Path $stageRoot 'resources\source-sha.txt'
  $buildPath=Join-Path $stageRoot 'resources\build-evidence.json'
  foreach($p in @($manifestPath,$srcPath,$buildPath,(Join-Path $stageRoot 'NEXUS Personal Pro.exe'))){
    Assert-File $p 'STAGED_PACKAGE_INCOMPLETE'
  }
  $manifest=Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
  $build=Get-Content -LiteralPath $buildPath -Raw | ConvertFrom-Json
  $src=(Get-Content -LiteralPath $srcPath -Raw).Trim().ToLowerInvariant()
  if($src -ne $ExpectedStageSourceSha -or ([string]$manifest.source_sha).ToLowerInvariant() -ne $ExpectedStageSourceSha -or
    [long]$manifest.artifact_id -ne $ExpectedStageArtifactId -or
    ([string]$build.source_sha).ToLowerInvariant() -ne $ExpectedStageSourceSha -or
    $build.paper_only -ne $true -or $build.live_trading_authority -ne $false){
    throw 'STAGED_PACKAGE_PROVENANCE_OR_AUTHORITY_MISMATCH'
  }
  $stageStatus='LOCAL_MANIFEST_SOURCE_BOUND_NOT_OFFICIALLY_APPROVED'
  if($StageProofPath){
    Assert-File $StageProofPath 'OFFICIAL_STAGE_PROOF_MISSING'
    $proof=Get-Content -LiteralPath $StageProofPath -Raw | ConvertFrom-Json
    if($proof.decision -ne 'PASS' -or $proof.final_launch.status -ne 'STAGED_ONLY_OWNER_PRESERVED' -or
      $proof.final_launch.activation_requested -ne $false -or
      ([string]$proof.source_sha).ToLowerInvariant() -ne $ExpectedStageSourceSha -or
      [long]$proof.artifact_id -ne $ExpectedStageArtifactId -or
      $proof.smoke.paper_only -ne $true -or
      $proof.smoke.live_trading_authority -ne $false -or $proof.smoke.live_orders_allowed -ne $false){
      throw 'STAGE_PROOF_NOT_TRUSTED'
    }
    $stageStatus='LOCAL_STAGE_AND_PROOF_CONSISTENT_REQUIRES_EXTERNAL_MAIN_CHECK'
  }
}
$backupStatus='NOT_SUPPLIED'
if($BackupRoot){
  $backupJournal=Join-Path $BackupRoot 'product-data\product_runtime\paper-events.jsonl'
  Assert-File $backupJournal 'BACKUP_JOURNAL_MISSING'
  if((Get-FileHash -LiteralPath $backupJournal -Algorithm SHA256).Hash.ToLowerInvariant() -ne $hash){throw 'BACKUP_JOURNAL_MISMATCH'}
  $backupStatus='PAPER_JOURNAL_VERIFIED_SHORTCUT_ROLLBACK_NOT_VERIFIED'
}
[ordered]@{
  schema='nexus.owner-activation-readonly-diagnostic.v1'; collected_at=[DateTime]::UtcNow.ToString('o')
  owner_source_sha=$ExpectedOwnerSourceSha; owner_journal_sha256=$hash; owner_paper_cash='500'
  owner_paper_equity='500'; owner_positions=0; owner_live_authority=$false; owner_orders_allowed=$false
  owner_gui_processes=$s2.owner_gui.Count; owner_gui_pids_stable_at_rest=$pidsStable
  unrelated_version_processes=$s2.other_installs.Count; owner_shortcuts_exact=4
  owner_autostart_task_state=$taskState; owner_autostart_action_class=$taskClass
  expected_stage_source_sha=$ExpectedStageSourceSha; expected_stage_artifact_id=$ExpectedStageArtifactId
  stage_status=$stageStatus; backup_status=$backupStatus
  shutdown_or_respawn_experiment_performed=$false; official_main_provenance_externally_verified=$false
  activation_authorized=$false; owner_processes_mutated=$false; owner_files_mutated=$false
  decision='READ_ONLY_DIAGNOSTIC_NOT_ACTIVATION'
} | ConvertTo-Json -Depth 5
