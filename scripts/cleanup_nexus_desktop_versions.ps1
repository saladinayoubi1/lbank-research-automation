[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string]$ProgramRoot,
    [Parameter(Mandatory = $true)] [string]$CurrentInstallRoot,
    [ValidateRange(1, 5)] [int]$MaxVersions = 3
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

function Get-FullPath([string]$Path) {
    return [IO.Path]::GetFullPath($Path)
}

function Test-PathWithin([string]$Candidate, [string]$Parent) {
    $candidateFull = (Get-FullPath $Candidate).TrimEnd('\')
    $parentFull = (Get-FullPath $Parent).TrimEnd('\')
    return $candidateFull.Equals($parentFull, [StringComparison]::OrdinalIgnoreCase) -or
        $candidateFull.StartsWith($parentFull + '\', [StringComparison]::OrdinalIgnoreCase)
}

function Assert-NotReparsePoint([string]$Path, [string]$Label) {
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "$Label cannot be a reparse point."
    }
}

$expectedRoot = Get-FullPath (Join-Path $env:LOCALAPPDATA 'Programs\NEXUS Personal Pro')
$root = (Get-FullPath $ProgramRoot).TrimEnd('\')
$current = (Get-FullPath $CurrentInstallRoot).TrimEnd('\')
if (-not $root.Equals($expectedRoot.TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Retention root must be the owner-local NEXUS program directory.'
}
if (-not (Test-Path -LiteralPath $root -PathType Container)) { throw 'NEXUS program root is missing.' }
Assert-NotReparsePoint $root 'NEXUS program root'
if (-not (Test-PathWithin $current $root)) { throw 'Current install root escaped the NEXUS program root.' }
if (-not (Test-Path -LiteralPath $current -PathType Container)) { throw 'Current install root is missing.' }

$runningRoots = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
foreach ($process in @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
    $_.ProcessName -in @('NEXUS Personal Pro', 'nexus-product-server')
})) {
    try {
        $processPath = (Get-FullPath ([string]$process.Path)).TrimEnd('\')
        if (-not (Test-PathWithin $processPath $root)) { continue }
        $relative = $processPath.Substring($root.Length).TrimStart('\')
        $leaf = ($relative -split '\\')[0]
        if ([regex]::IsMatch($leaf, '\A5[.]1[.]0-[0-9a-fA-F]{8}\z')) {
            [void]$runningRoots.Add((Get-FullPath (Join-Path $root $leaf)).TrimEnd('\'))
        }
    } catch { }
}

$removed = @()
$skippedRunning = @()
$skippedUnverified = @()
$candidates = @()
foreach ($dir in @(Get-ChildItem -LiteralPath $root -Directory -Force -ErrorAction SilentlyContinue)) {
    if (-not [regex]::IsMatch($dir.Name, '\A5[.]1[.]0-[0-9a-fA-F]{8}\z')) { continue }
    $dirPath = (Get-FullPath $dir.FullName).TrimEnd('\')
    if (-not (Test-PathWithin $dirPath $root)) { continue }
    if ($dir.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        $skippedUnverified += $dir.Name
        continue
    }

    $manifestPath = Join-Path $dirPath 'install-manifest.json'
    $exePath = Join-Path $dirPath 'NEXUS Personal Pro.exe'
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $exePath -PathType Leaf)) {
        $skippedUnverified += $dir.Name
        continue
    }

    try {
        Assert-NotReparsePoint $manifestPath 'Installed version manifest'
        Assert-NotReparsePoint $exePath 'Installed version executable'
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        $shaOk = [regex]::IsMatch([string]$manifest.source_sha, '\A[0-9a-fA-F]{40}\z')
        if ([string]$manifest.schema_version -ne 'nexus.windows-side-by-side-install.v2' -or
            [string]$manifest.version -ne '5.1.0' -or -not $shaOk -or
            $manifest.paper_only -ne $true -or $manifest.live_trading_authority -ne $false) {
            throw 'manifest contract mismatch'
        }
        $installedAt = [DateTime]::Parse([string]$manifest.installed_at).ToUniversalTime()
        $candidates += [pscustomobject]@{ Path = $dirPath; Name = $dir.Name; InstalledAt = $installedAt }
    } catch {
        $skippedUnverified += $dir.Name
    }
}

$protected = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
[void]$protected.Add($current)
foreach ($running in $runningRoots) {
    [void]$protected.Add($running)
    $skippedRunning += (Split-Path -Leaf $running)
}

$remainingSlots = [Math]::Max(0, $MaxVersions - $protected.Count)
foreach ($candidate in @($candidates | Where-Object { -not $protected.Contains($_.Path) } | Sort-Object InstalledAt -Descending | Select-Object -First $remainingSlots)) {
    [void]$protected.Add($candidate.Path)
}

foreach ($candidate in @($candidates | Sort-Object InstalledAt -Descending)) {
    if ($protected.Contains($candidate.Path)) { continue }
    if ($candidate.Path -eq $current -or $runningRoots.Contains($candidate.Path)) { continue }
    if (-not (Test-PathWithin $candidate.Path $root)) { continue }
    Remove-Item -LiteralPath $candidate.Path -Recurse -Force -ErrorAction Stop
    $removed += $candidate.Name
    Write-Host "NEXUS_VERSION_RETENTION_REMOVED=$($candidate.Name)"
}

$result = [ordered]@{
    schema_version = 'nexus.windows-version-retention.v1'
    max_versions = $MaxVersions
    current_version = Split-Path -Leaf $current
    removed = @($removed)
    skipped_running = @($skippedRunning | Sort-Object -Unique)
    skipped_unverified = @($skippedUnverified | Sort-Object -Unique)
    retained_valid_count = @($candidates | Where-Object { Test-Path -LiteralPath $_.Path -PathType Container }).Count
}
$result | ConvertTo-Json -Depth 4 -Compress
