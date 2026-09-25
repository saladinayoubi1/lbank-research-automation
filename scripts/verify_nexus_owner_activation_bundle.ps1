[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-fA-F0-9]{40}$')][string]$ExpectedOwnerSourceSha,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$ExpectedOwnerJournalSha256,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-fA-F0-9]{40}$')][string]$ExpectedStageSourceSha,
    [Parameter(Mandatory=$true)][long]$ExpectedStageArtifactId,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$ExpectedStageProofSha256,
    [Parameter(Mandatory=$true)][string]$BackupRoot,
    [Parameter(Mandatory=$true)][string]$StageProofPath,
    [string]$ProgramRoot = (Join-Path $env:LOCALAPPDATA 'Programs\NEXUS Personal Pro'),
    [string]$GlobalPaperSyncRoot = (Join-Path $env:LOCALAPPDATA 'NEXUS\paper-forward-sync'),
    [string]$OwnerProductDataRoot = (Join-Path $env:APPDATA 'nexus-personal-pro-product\product-data')
)
Set-StrictMode -Version 2
$ErrorActionPreference = 'Stop'
# Independent, read-only backup/provenance gate. This script NEVER authorizes activation.
function Require([bool]$Condition, [string]$Code) {
    if (-not $Condition) { throw $Code }
}
function ExactHash([string]$Path, [string]$Expected, [string]$Code) {
    Require (Test-Path -LiteralPath $Path -PathType Leaf) ($Code + '_MISSING')
    Require ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -ieq $Expected) ($Code + '_HASH_MISMATCH')
}
function UnderRoot([string]$Root, [string]$Relative) {
    Require (-not [string]::IsNullOrWhiteSpace($Relative)) 'EMPTY_BACKUP_RELATIVE_PATH'
    Require (-not [IO.Path]::IsPathRooted($Relative)) 'ABSOLUTE_BACKUP_RELATIVE_PATH'
    Require ($Relative -notmatch '(^|[\\/])\.\.([\\/]|$)') 'BACKUP_PATH_TRAVERSAL'
    Require ($Relative -notmatch '(^|[\\/])\.([\\/]|$)') 'BACKUP_DOT_PATH'
    $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    $full = [IO.Path]::GetFullPath((Join-Path $rootFull $Relative))
    Require ($full.StartsWith($rootFull + '\', [StringComparison]::OrdinalIgnoreCase)) 'BACKUP_PATH_OUTSIDE_ROOT'
    $cursor = $full
    while ($cursor.Length -gt $rootFull.Length) {
        if (Test-Path -LiteralPath $cursor) {
            $attributes = (Get-Item -LiteralPath $cursor -Force).Attributes
            Require (-not [bool]($attributes -band [IO.FileAttributes]::ReparsePoint)) 'BACKUP_REPARSE_POINT'
        }
        $cursor = Split-Path -Parent $cursor
    }
    return $full
}
function Read-Manifest([string]$Name, [int]$ExactCount) {
    $path = UnderRoot $BackupRoot $Name
    Require (Test-Path -LiteralPath $path -PathType Leaf) 'BACKUP_MANIFEST_MISSING'
    $items = @(Get-Content -LiteralPath $path -Raw | ConvertFrom-Json)
    Require ($items.Count -eq $ExactCount) 'BACKUP_MANIFEST_COUNT_MISMATCH'
    return $items
}
$ExpectedOwnerSourceSha = $ExpectedOwnerSourceSha.ToLowerInvariant()
$ExpectedStageSourceSha = $ExpectedStageSourceSha.ToLowerInvariant()
$ownerExe = Join-Path $ProgramRoot ('5.1.0-' + $ExpectedOwnerSourceSha.Substring(0,8) + '\NEXUS Personal Pro.exe')
$stageRoot = Join-Path $ProgramRoot ('5.1.0-' + $ExpectedStageSourceSha.Substring(0,8))
$stageExe = Join-Path $stageRoot 'NEXUS Personal Pro.exe'
Require (Test-Path -LiteralPath $ownerExe -PathType Leaf) 'EXPECTED_OWNER_EXECUTABLE_MISSING'
Require (Test-Path -LiteralPath $stageExe -PathType Leaf) 'EXPECTED_STAGE_EXECUTABLE_MISSING'
$stageManifest = Get-Content -LiteralPath (Join-Path $stageRoot 'install-manifest.json') -Raw | ConvertFrom-Json
$buildEvidence = Get-Content -LiteralPath (Join-Path $stageRoot 'resources\build-evidence.json') -Raw | ConvertFrom-Json
$sourceText = (Get-Content -LiteralPath (Join-Path $stageRoot 'resources\source-sha.txt') -Raw).Trim()
Require (([string]$stageManifest.source_sha -ieq $ExpectedStageSourceSha) -and
    ([long]$stageManifest.artifact_id -eq $ExpectedStageArtifactId) -and
    ($stageManifest.paper_only -eq $true) -and ($stageManifest.live_trading_authority -eq $false) -and
    ([string]$buildEvidence.source_sha -ieq $ExpectedStageSourceSha) -and
    ($buildEvidence.paper_only -eq $true) -and ($buildEvidence.live_trading_authority -eq $false) -and
    ($sourceText -ieq $ExpectedStageSourceSha)) 'STAGE_SOURCE_OR_AUTHORITY_MISMATCH'
ExactHash $StageProofPath $ExpectedStageProofSha256 'STAGE_PROOF'
$proof = Get-Content -LiteralPath $StageProofPath -Raw | ConvertFrom-Json
Require ($proof.decision -eq 'PASS' -and ([string]$proof.source_sha -ieq $ExpectedStageSourceSha) -and
    ([long]$proof.artifact_id -eq $ExpectedStageArtifactId) -and
    $proof.final_launch.status -eq 'STAGED_ONLY_OWNER_PRESERVED' -and
    $proof.final_launch.activation_requested -eq $false -and
    $proof.smoke.paper_only -eq $true -and
    $proof.smoke.live_trading_authority -eq $false -and
    $proof.smoke.live_orders_allowed -eq $false) 'STAGE_PHYSICAL_PROOF_INVALID'
$expectedRelative = @(
    'product-data\supervisor-state.json',
    'product-data\agent_coordination\imported_mission_snapshot.json',
    'product-data\demo-account-archives\before-500-2a4de7c7d5b34db3bcd349dd3fb087be.jsonl',
    'product-data\demo-account-archives\reset-proof-2a4de7c7d5b34db3bcd349dd3fb087be.json',
    'product-data\product_runtime\paper-events.jsonl',
    'product-data\prospective_paper\bybit_prospective_paper_forward_v1.json',
    'product-data\prospective_paper\runtime_attestation.json'
)
$data = @(Read-Manifest 'product-data-sha256-manifest.json' 7)
Require (@($data | Select-Object -ExpandProperty relative -Unique).Count -eq 7) 'DUPLICATE_BACKUP_DATA_ENTRY'
foreach ($entry in $data) {
    Require ($expectedRelative -contains [string]$entry.relative) 'UNEXPECTED_BACKUP_DATA_ENTRY'
    $file = UnderRoot $BackupRoot ([string]$entry.relative)
    ExactHash $file ([string]$entry.sha256) 'BACKUP_DATA'
    Require ((Get-Item -LiteralPath $file).Length -eq [long]$entry.bytes) 'BACKUP_DATA_LENGTH_MISMATCH'
}
$backupJournal = UnderRoot $BackupRoot 'product-data\product_runtime\paper-events.jsonl'
ExactHash $backupJournal $ExpectedOwnerJournalSha256 'BACKUP_JOURNAL'
ExactHash (Join-Path $OwnerProductDataRoot 'product_runtime\paper-events.jsonl') $ExpectedOwnerJournalSha256 'ORIGINAL_OWNER_JOURNAL'
$expectedShortcuts = @(
    (Join-Path ([Environment]::GetFolderPath('Desktop')) 'NEXUS Personal Pro 5.1.0.lnk'),
    (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\NEXUS Personal Pro 5.1.0.lnk'),
    (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\NEXUS Personal Pro.lnk'),
    (Join-Path ([Environment]::GetFolderPath('Startup')) 'NEXUS Personal Pro.lnk')
)
$shortcuts = @(Read-Manifest 'shortcuts-manifest.json' 4)
Require (@($shortcuts | Select-Object -ExpandProperty original_path -Unique).Count -eq 4) 'DUPLICATE_SHORTCUT_ENTRY'
Require (@($shortcuts | Select-Object -ExpandProperty backup_file -Unique).Count -eq 4) 'DUPLICATE_BACKUP_SHORTCUT_FILE'
$shell = New-Object -ComObject WScript.Shell
foreach ($link in $shortcuts) {
    Require ($expectedShortcuts -contains [string]$link.original_path) 'UNEXPECTED_SHORTCUT_PATH'
    Require ([string]$link.target -ieq $ownerExe) 'BACKUP_SHORTCUT_TARGET_MISMATCH'
    Require ([string]$link.backup_file -match '^owner-shortcut-[0-3]\.lnk$') 'UNEXPECTED_BACKUP_SHORTCUT_FILE'
    ExactHash (UnderRoot $BackupRoot ('shortcuts\' + $link.backup_file)) ([string]$link.sha256) 'BACKUP_SHORTCUT'
    Require (Test-Path -LiteralPath $link.original_path -PathType Leaf) 'LIVE_SHORTCUT_MISSING'
    Require ($shell.CreateShortcut($link.original_path).TargetPath -ieq $ownerExe) 'LIVE_SHORTCUT_RETARGETED'
}
$sync = @(Read-Manifest 'global-paper-sync-manifest.json' 2)
Require (@($sync | Select-Object -ExpandProperty file -Unique).Count -eq 2) 'DUPLICATE_PAPER_SYNC_ENTRY'
foreach ($item in $sync) {
    Require ([string]$item.file -in @('sync.ps1','product_prospective_paper.py')) 'UNEXPECTED_GLOBAL_SYNC_FILE'
    ExactHash (UnderRoot $BackupRoot ('paper-forward-sync\' + $item.file)) ([string]$item.sha256) 'BACKUP_PAPER_SYNC'
    ExactHash (Join-Path $GlobalPaperSyncRoot $item.file) ([string]$item.sha256) 'LIVE_PAPER_SYNC'
}
[ordered]@{
    schema = 'nexus.owner-activation-bundle-gate.v1'
    decision = 'READ_ONLY_BUNDLE_PASS_NOT_ACTIVATION'
    owner_source_sha = $ExpectedOwnerSourceSha
    stage_source_sha = $ExpectedStageSourceSha
    stage_artifact_id = $ExpectedStageArtifactId
    backed_up_data_files = 7
    backed_up_shortcuts = 4
    backed_up_global_sync_files = 2
    journal_hash_consistent = $true
    official_main_provenance_externally_verified = $false
    full_real_owner_profile_tested = $false
    process_quiescence_tested = $false
    rollback_tested = $false
    activation_authorized = $false
    owner_modified = $false
} | ConvertTo-Json -Depth 3
