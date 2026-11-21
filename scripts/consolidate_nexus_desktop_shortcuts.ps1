[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ActiveExecutable,
    [Parameter(Mandatory=$true)][string]$ExpectedSourceSha,
    [Parameter(Mandatory=$true)][string]$OwnerProfileRoot,
    [Parameter(Mandatory=$true)][string]$ArchiveRoot,
    [switch]$Apply
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

function Full([string]$Path) { return [IO.Path]::GetFullPath($Path).TrimEnd('\') }
function Plain([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Reparse point rejected: $Path" }
    return $item
}
function Hash([string]$Path) { return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }

$desktop = Full ([Environment]::GetFolderPath('Desktop'))
$exe = Full $ActiveExecutable
$profile = Full $OwnerProfileRoot
$archive = Full $ArchiveRoot
if ($exe -notmatch '\\NEXUS Personal Pro\.exe$') { throw 'Unexpected executable name' }
if ($ExpectedSourceSha -notmatch '\A[0-9a-f]{40}\z') { throw 'Full source SHA required' }
if ($exe.StartsWith($desktop+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Active install must be outside Desktop' }
if ($archive.StartsWith($desktop+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Archive must be outside Desktop' }
if ($archive.Equals($profile,[StringComparison]::OrdinalIgnoreCase) -or
    $archive.StartsWith($profile+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Archive must not use the owner profile' }
$null = Plain $exe
$null = Plain $profile
$sourceFile = Join-Path (Split-Path -Parent $exe) 'resources\source-sha.txt'
$null = Plain $sourceFile
if ((Get-Content -LiteralPath $sourceFile -Raw).Trim().ToLowerInvariant() -ne $ExpectedSourceSha) { throw 'Packaged source binding mismatch' }
$journal = Join-Path $profile 'product-data\product_runtime\paper-events.jsonl'
$null = Plain $journal
$journalBefore = Hash $journal
$arguments = '--user-data-dir="'+$profile+'" --nexus-installed-source='+$ExpectedSourceSha
$canonical = Join-Path $desktop 'NEXUS Personal Pro.lnk'
$shell = New-Object -ComObject WScript.Shell
$links = @(Get-ChildItem -LiteralPath $desktop -File | Where-Object {
    $_.Name -like 'NEXUS Personal Pro*.lnk' -or $_.Name -like 'NEXUS Personal Pro*.lnk*.bak'
})
$plan = @($links | ForEach-Object {
    $target = $null
    if ($_.Extension -eq '.lnk') { $target = $shell.CreateShortcut($_.FullName).TargetPath }
    [pscustomobject]@{path=$_.FullName;sha256=(Hash $_.FullName);old_target=$target}
})
if (-not $Apply) {
    [pscustomobject]@{status='DRY_RUN';canonical=$canonical;target=$exe;arguments=$arguments;archive=$archive;obsolete_shortcuts=$plan;journal_sha256=$journalBefore} | ConvertTo-Json -Depth 6
    return
}
if (Test-Path -LiteralPath $archive) { throw 'Use a new archive directory for each cleanup' }
$null = New-Item -ItemType Directory -Path $archive
$removed = @()
$receipt = Join-Path $archive 'cleanup-receipt.json'
$outcome = 'INCOMPLETE'
try {
    # Preserve and verify every old shortcut before changing Desktop. Profiles,
    # research directories, installations and remote-recovery launchers are excluded.
    foreach ($row in $plan) {
        $backup = Join-Path $archive (Split-Path -Leaf $row.path)
        Copy-Item -LiteralPath $row.path -Destination $backup
        if ((Hash $backup) -ne $row.sha256) { throw 'Shortcut backup mismatch' }
    }
    $shortcut = $shell.CreateShortcut($canonical)
    $shortcut.TargetPath = $exe
    $shortcut.Arguments = $arguments
    $shortcut.WorkingDirectory = Split-Path -Parent $exe
    $shortcut.Description = 'NEXUS Personal Pro - preserved owner Paper account'
    $shortcut.Save()
    $check = $shell.CreateShortcut($canonical)
    if ((Full $check.TargetPath) -ne $exe -or $check.Arguments -ne $arguments) { throw 'Canonical shortcut verification failed' }
    foreach ($row in $plan) {
        if ($row.path.Equals($canonical,[StringComparison]::OrdinalIgnoreCase)) { continue }
        if ((Hash $row.path) -ne $row.sha256) { throw 'Shortcut changed during cleanup' }
        Remove-Item -LiteralPath $row.path
        $removed += $row.path
    }
    $remaining = @(Get-ChildItem -LiteralPath $desktop -File -Filter 'NEXUS Personal Pro*.lnk')
    if ($remaining.Count -ne 1 -or $remaining[0].FullName -ne $canonical) { throw 'Desktop shortcut reconciliation failed' }
    if (-not (Test-Path -LiteralPath $journal -PathType Leaf)) { throw 'Owner journal missing after cleanup' }
    $outcome = 'VERIFIED'
} finally {
    [pscustomobject]@{status=$outcome;at_utc=[DateTime]::UtcNow.ToString('o');canonical=$canonical;target=$exe;arguments=$arguments;source_sha=$ExpectedSourceSha;owner_profile=$profile;removed=$removed;backups=$plan;journal_sha256_before=$journalBefore;journal_sha256_after=(Hash $journal);live_trading_authority=$false;paper_only=$true} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $receipt -Encoding UTF8
}
Get-Content -LiteralPath $receipt -Raw
