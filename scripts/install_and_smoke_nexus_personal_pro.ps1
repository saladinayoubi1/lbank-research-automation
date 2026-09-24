[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string]$PackageRoot,
    [Parameter(Mandatory = $true)] [ValidatePattern('^[0-9a-fA-F]{40}$')] [string]$ExpectedSourceSha,
    [Parameter(Mandatory = $true)] [ValidatePattern('^[0-9a-fA-F]{64}$')] [string]$ExpectedUnpackedSha256,
    [Parameter(Mandatory = $true)] [long]$ArtifactRunId,
    [Parameter(Mandatory = $true)] [long]$ArtifactId,
    [string]$ArtifactName = 'nexus-windows-persistent-unpacked',
    [string]$ExpectedComputerName = 'DESKTOP-1R1081M',
    [string]$ExpectedRunnerName = 'NEXUS-LOCAL-RUNNER',
    [string]$EvidencePath = 'build\windows-app-install\evidence.json',
    [switch]$UsePreloadedPackage
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$ExpectedSourceSha = $ExpectedSourceSha.ToLowerInvariant()
$ExpectedUnpackedSha256 = $ExpectedUnpackedSha256.ToLowerInvariant()
$script:BaselineNexusProcessIds = @{}
$script:SmokeRoot = $null
$script:SmokeCleaned = $false
$script:ProgramRoot = $null
$script:InstallRoot = $null
$script:InstallStagingRoot = $null
$script:InstallCreatedThisRun = $false
$script:InstallSmokeVerified = $false
$script:PackageTransportRemoved = $false
$script:Evidence = [ordered]@{
    schema_version = 'nexus.windows-app-install-proof.v1'
    decision = 'STARTED'
    generated_at = [DateTime]::UtcNow.ToString('o')
    repository = [string]$env:GITHUB_REPOSITORY
    source_sha = $ExpectedSourceSha
    artifact_run_id = $ArtifactRunId
    artifact_id = $ArtifactId
    target = [ordered]@{
        computer_name = $ExpectedComputerName
        runner_name = $ExpectedRunnerName
        owner_user_context = $false
        interactive_desktop = $false
        elevated = $null
    }
    package = [ordered]@{
        download_transport = 'existing_owner_gh_cli'
        workflow_token_used = $false
        downloaded = $false
        unpacked_sha256 = $null
        checksum_manifest_verified = $false
    }
    install = [ordered]@{
        mode = 'versioned_side_by_side_unpacked'
        previous_install_removed = $false
        previous_app_data_removed = $false
        registry_installation_changed = $false
        executable_deployed = $false
        manifest_written = $false
        desktop_shortcut_created = $false
        start_menu_shortcut_created = $false
        startup_shortcut_created = $false
        version = '5.1.0'
        retention_cleanup_attempted = $false
        retention_cleanup_succeeded = $false
        retained_version_limit = 3
        retained_cache_limit = 2
        removed_version_count = 0
        removed_cache_count = 0
        active_version_skips = 0
        cleanup_warning = $null
    }
    smoke = [ordered]@{
        isolated_user_data = $true
        process_started = $false
        visible_window_observed = $false
        supervisor_healthy = $false
        overview_ok = $false
        paper_only = $false
        deterministic_risk_present = $false
        strategy_evidence_ok = $false
        mission_control_ok = $false
        offline_first = $false
        live_trading_authority = $null
        live_orders_allowed = $null
        ui_loaded = $false
    }
    final_launch = [ordered]@{
        status = 'NOT_ATTEMPTED'
        visible_window_observed = $false
        preexisting_app_preserved = $false
    }
    safety = [ordered]@{
        paper_only_required = $true
        live_trading_authority_required = $false
        admin_elevation_allowed = $false
        setup_executable_invoked = $false
        uninstaller_invoked = $false
        credentials_modified = $false
        runner_registration_modified = $false
    }
    error = $null
}

function Get-FullPath([string]$Path) {
    return [IO.Path]::GetFullPath($Path)
}

function Test-PathWithin([string]$Candidate, [string]$Parent) {
    $candidateFull = (Get-FullPath $Candidate).TrimEnd('\')
    $parentFull = (Get-FullPath $Parent).TrimEnd('\')
    return $candidateFull.StartsWith($parentFull + '\', [StringComparison]::OrdinalIgnoreCase)
}

function ConvertTo-SafeError([object]$Value) {
    $message = [string]$Value
    foreach ($sensitiveRoot in @($env:USERPROFILE, $env:LOCALAPPDATA, $env:APPDATA, $env:RUNNER_TEMP, $env:GITHUB_WORKSPACE)) {
        if ($sensitiveRoot) { $message = $message -replace [Regex]::Escape([string]$sensitiveRoot), '<redacted-root>' }
    }
    if ($message.Length -gt 900) { $message = $message.Substring(0, 900) }
    return $message
}

function Write-Evidence {
    $target = Get-FullPath $EvidencePath
    $parent = Split-Path -Parent $target
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $script:Evidence.generated_at = [DateTime]::UtcNow.ToString('o')
    $json = $script:Evidence | ConvertTo-Json -Depth 8
    [IO.File]::WriteAllText($target, $json, (New-Object Text.UTF8Encoding($false)))
}

function Assert-NotReparsePoint([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $item = Get-Item -LiteralPath $Path -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "$Label must not be a reparse point." }
}

function Get-NexusProcesses {
    return @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match '(?i)nexus' })
}

function Get-NewNexusProcesses {
    return @(Get-NexusProcesses | Where-Object { -not $script:BaselineNexusProcessIds.ContainsKey([int]$_.Id) })
}

function Stop-SmokeProcesses {
    if ($script:SmokeCleaned) { return }
    foreach ($process in @(Get-NewNexusProcesses)) {
        try { if ($process.MainWindowHandle -ne 0) { [void]$process.CloseMainWindow() } } catch { }
    }
    $deadline = [DateTime]::UtcNow.AddSeconds(12)
    do {
        Start-Sleep -Milliseconds 400
        $remaining = @(Get-NewNexusProcesses)
    } while ($remaining.Count -gt 0 -and [DateTime]::UtcNow -lt $deadline)
    foreach ($process in @(Get-NewNexusProcesses)) {
        try { Stop-Process -Id $process.Id -Force -ErrorAction Stop } catch { }
    }
    Start-Sleep -Milliseconds 800
    $script:SmokeCleaned = $true
}

function Remove-SmokeRoot {
    if (-not $script:SmokeRoot -or -not (Test-Path -LiteralPath $script:SmokeRoot)) { return }
    if (-not $env:RUNNER_TEMP -or -not (Test-PathWithin $script:SmokeRoot $env:RUNNER_TEMP)) {
        throw 'Refusing to remove a smoke root outside RUNNER_TEMP.'
    }
    $leaf = Split-Path -Leaf (Get-FullPath $script:SmokeRoot)
    if ($leaf -notmatch '^nexus-app-smoke-[0-9]+$') { throw 'Refusing to remove an unexpected smoke root.' }
    Remove-Item -LiteralPath $script:SmokeRoot -Recurse -Force -ErrorAction SilentlyContinue
}

function Remove-PackageTransport {
    if ($script:PackageTransportRemoved -or -not (Test-Path -LiteralPath $PackageRoot)) { return }
    if (-not $env:RUNNER_TEMP -or -not (Test-PathWithin $PackageRoot $env:RUNNER_TEMP)) {
        throw 'Refusing to remove a package transport outside RUNNER_TEMP.'
    }
    $leaf = Split-Path -Leaf (Get-FullPath $PackageRoot)
    if ($leaf -notmatch '^nexus-personal-pro-package-[0-9]+$') { throw 'Refusing to remove an unexpected package transport.' }
    Remove-Item -LiteralPath $PackageRoot -Recurse -Force
    $script:PackageTransportRemoved = $true
}

function Invoke-NexusRetention([string]$CurrentInstallRoot, [long]$CurrentArtifactId) {
    $script:Evidence.install.retention_cleanup_attempted = $true
    try {
        if (-not $script:ProgramRoot -or -not (Test-Path -LiteralPath $script:ProgramRoot -PathType Container)) {
            throw 'NEXUS program root is unavailable for retention cleanup.'
        }

        $currentInstall = Get-FullPath $CurrentInstallRoot
        if (-not (Test-PathWithin $currentInstall $script:ProgramRoot)) { throw 'Current install escaped the NEXUS program root.' }

        $activePaths = @(
            Get-NexusProcesses | ForEach-Object {
                try { if ($_.Path) { Get-FullPath ([string]$_.Path) } } catch { }
            } | Where-Object { $_ }
        )
        $versionDirs = @(
            Get-ChildItem -LiteralPath $script:ProgramRoot -Directory -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -match '^5\.1\.0-[0-9a-fA-F]{8}
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) { return $null }
    $direct = Join-Path $Root 'product-data\supervisor-state.json'
    if (Test-Path -LiteralPath $direct -PathType Leaf) { return $direct }
    return Get-ChildItem -LiteralPath $Root -Filter 'supervisor-state.json' -File -Recurse -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1 -ExpandProperty FullName
}

function Wait-ForHealthySupervisor([string]$Root, [DateTime]$NotBeforeUtc, [int]$TimeoutSeconds = 120) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $lastError = $null
    do {
        $statePath = Find-SupervisorState $Root
        if ($statePath) {
            try {
                $item = Get-Item -LiteralPath $statePath
                $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
                if ($item.LastWriteTimeUtc -ge $NotBeforeUtc.AddSeconds(-3) -and [string]$state.status -eq 'healthy' -and
                    ([string]$state.source_sha).ToLowerInvariant() -eq $ExpectedSourceSha -and
                    [string]$state.origin -match '^http://127\.0\.0\.1:[0-9]+$') { return $state }
            } catch { $lastError = $_.Exception.Message }
        }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "NEXUS supervisor did not become healthy for the expected source. $lastError"
}

function Wait-ForVisibleNewWindow([int]$TimeoutSeconds = 90) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        foreach ($process in @(Get-NewNexusProcesses)) {
            try {
                $process.Refresh()
                if ($process.MainWindowHandle -ne 0 -and [string]$process.MainWindowTitle -match '(?i)NEXUS') { return $true }
            } catch { }
        }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)
    return $false
}

function New-NexusShortcut([string]$ShortcutPath, [string]$ExecutablePath) {
    $parent = Split-Path -Parent $ShortcutPath
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($ShortcutPath)
    $shortcut.TargetPath = $ExecutablePath
    $shortcut.WorkingDirectory = Split-Path -Parent $ExecutablePath
    $shortcut.IconLocation = "$ExecutablePath,0"
    $shortcut.Description = "NEXUS Personal Pro 5.1.0 ($($ExpectedSourceSha.Substring(0, 8)))"
    $shortcut.Save()
    if (-not (Test-Path -LiteralPath $ShortcutPath -PathType Leaf)) { throw 'NEXUS shortcut creation failed.' }
}

function Invoke-ProductContract([string]$Origin) {
    $overview = Invoke-RestMethod -Uri "$Origin/api/product/overview" -TimeoutSec 10
    if ($overview.paper.active -ne $true -or $overview.live.enabled -ne $false) { throw 'Product overview authority contract failed.' }
    $script:Evidence.smoke.overview_ok = $true

    $paper = Invoke-RestMethod -Uri "$Origin/api/product/paper" -TimeoutSec 10
    if ($paper.paper_only -ne $true) { throw 'Paper-only contract failed.' }
    $script:Evidence.smoke.paper_only = $true

    $live = Invoke-RestMethod -Uri "$Origin/api/product/live" -TimeoutSec 10
    $script:Evidence.smoke.live_trading_authority = [bool]$live.live_trading_authority
    $script:Evidence.smoke.live_orders_allowed = [bool]$live.orders_allowed
    if ($live.live_trading_authority -ne $false -or $live.orders_allowed -ne $false) { throw 'Live trading authority widened during laptop smoke test.' }

    $offline = Invoke-RestMethod -Uri "$Origin/api/product/offline" -TimeoutSec 10
    if ($offline.mode -ne 'offline_first' -or $offline.live_trading_authority -ne $false) { throw 'Offline-first contract failed.' }
    $script:Evidence.smoke.offline_first = $true

    $mission = Invoke-RestMethod -Uri "$Origin/api/product/mission/full" -TimeoutSec 10
    if ($mission.paper_only -ne $true -or $mission.live_trading_authority -ne $false) { throw 'Mission Control authority contract failed.' }
    $script:Evidence.smoke.mission_control_ok = $true

    $build = Invoke-RestMethod -Uri "$Origin/api/product/build-evidence" -TimeoutSec 10
    if ($build.status -ne 'verified' -or $build.exact_source -ne $true -or ([string]$build.source_sha).ToLowerInvariant() -ne $ExpectedSourceSha) {
        throw 'Installed product exact-source evidence failed.'
    }

    $strategies = Invoke-RestMethod -Uri "$Origin/api/product/strategies/evidence" -TimeoutSec 10
    if ($strategies.paper_only -ne $true -or $strategies.profitability_claim -ne $false) { throw 'Strategy evidence boundary failed.' }
    $script:Evidence.smoke.strategy_evidence_ok = $true

    if ([string]$overview.capabilities.deterministic_risk -ne 'final_paper_authority') {
        throw 'Deterministic Risk authority is missing from product overview.'
    }
    $script:Evidence.smoke.deterministic_risk_present = $true

    $index = Invoke-WebRequest -UseBasicParsing -Uri "$Origin/" -TimeoutSec 10
    if ($index.StatusCode -ne 200 -or $index.Content -notmatch 'NEXUS Personal Pro' -or $index.Content -notmatch 'Mission Control') {
        throw 'Mission Control UI did not load.'
    }
    $script:Evidence.smoke.ui_loaded = $true
}

try {
    if ($env:GITHUB_ACTIONS -ne 'true') { throw 'This installer is restricted to GitHub Actions.' }
    if ($env:GITHUB_REPOSITORY -ne 'saladinayoubi1/lbank-research-automation') { throw 'Unexpected repository.' }
    if ($env:GITHUB_REF -ne 'refs/heads/main') { throw 'Laptop installation is restricted to main.' }
    if ($env:RUNNER_NAME -ne $ExpectedRunnerName) { throw "Unexpected runner: $($env:RUNNER_NAME)" }
    $actualComputerName = [string]$env:COMPUTERNAME
    if ([string]::IsNullOrWhiteSpace($actualComputerName)) { $actualComputerName = [Environment]::MachineName }
    if ($actualComputerName -ine $ExpectedComputerName) { throw "Unexpected computer: $actualComputerName" }

    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    if ($identity.Name -match '^(?i:NT AUTHORITY\\(?:SYSTEM|LOCAL SERVICE|NETWORK SERVICE))$') {
        throw 'Service identities cannot install the owner desktop application.'
    }
    if (-not [Environment]::UserInteractive) { throw 'An interactive owner session is required.' }
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    $elevated = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    $script:Evidence.target.elevated = [bool]$elevated
    if ($elevated) { throw 'Elevated installation is forbidden; use the normal owner session.' }
    $sessionId = (Get-Process -Id $PID).SessionId
    $explorer = @(Get-Process -Name explorer -ErrorAction SilentlyContinue | Where-Object { $_.SessionId -eq $sessionId })
    if ($explorer.Count -lt 1) { throw 'Explorer is not running in the runner session; refusing a non-visible GUI install.' }
    $script:Evidence.target.owner_user_context = $true
    $script:Evidence.target.interactive_desktop = $true

    if (-not $env:RUNNER_TEMP) { throw 'RUNNER_TEMP is required for bounded artifact transport.' }
    $packageRootFull = Get-FullPath $PackageRoot
    if (-not (Test-PathWithin $packageRootFull $env:RUNNER_TEMP)) { throw 'Package transport escaped RUNNER_TEMP.' }
    if ((Split-Path -Leaf $packageRootFull) -notmatch '^nexus-personal-pro-package-[0-9]+$') {
        throw 'Unexpected package transport leaf.'
    }
    if ($UsePreloadedPackage) {
        if (-not (Test-Path -LiteralPath $packageRootFull -PathType Container)) { throw 'Preloaded package root is missing.' }
        $script:Evidence.package.download_transport = 'actions_download_artifact'
        $script:Evidence.package.workflow_token_used = $true
        $script:Evidence.package.downloaded = $true
    } else {
        if (Test-Path -LiteralPath $packageRootFull) { throw 'Stale package transport already exists.' }
        $gh = Get-Command gh.exe -ErrorAction SilentlyContinue
        if (-not $gh) { $gh = Get-Command gh -ErrorAction SilentlyContinue }
        if (-not $gh) { throw 'Existing owner GitHub CLI is unavailable.' }
        $previousGhToken = [Environment]::GetEnvironmentVariable('GH_TOKEN', 'Process')
        $previousGitHubToken = [Environment]::GetEnvironmentVariable('GITHUB_TOKEN', 'Process')
        [Environment]::SetEnvironmentVariable('GH_TOKEN', $null, 'Process')
        [Environment]::SetEnvironmentVariable('GITHUB_TOKEN', $null, 'Process')
        try {
            & $gh.Source run download "$ArtifactRunId" --repo 'saladinayoubi1/lbank-research-automation' --name $ArtifactName --dir $packageRootFull
            if ($LASTEXITCODE -ne 0) { throw 'Existing owner GitHub CLI could not download the exact approved artifact.' }
        } finally {
            [Environment]::SetEnvironmentVariable('GH_TOKEN', $previousGhToken, 'Process')
            [Environment]::SetEnvironmentVariable('GITHUB_TOKEN', $previousGitHubToken, 'Process')
        }
        if (-not (Test-Path -LiteralPath $packageRootFull -PathType Container)) { throw 'Package root is missing after download.' }
        $script:Evidence.package.downloaded = $true
    }
    Assert-NotReparsePoint $packageRootFull 'Package root'
    $unpackedName = 'NEXUS_Personal_Pro_Unpacked_5.1.0_x64.zip'
    $unpackedPath = Join-Path $packageRootFull $unpackedName
    $sumsPath = Join-Path $packageRootFull 'SHA256SUMS.txt'
    foreach ($requiredPath in @($unpackedPath, $sumsPath)) {
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) { throw "Required package file is missing: $(Split-Path -Leaf $requiredPath)" }
        Assert-NotReparsePoint $requiredPath 'Package file'
    }
    if ((Get-Item -LiteralPath $unpackedPath).Length -lt 100MB) { throw 'Persistent NEXUS package is unexpectedly small.' }
    $unpackedSha = (Get-FileHash -LiteralPath $unpackedPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $script:Evidence.package.unpacked_sha256 = $unpackedSha
    if ($unpackedSha -ne $ExpectedUnpackedSha256) { throw 'Persistent unpacked ZIP SHA256 does not match the exact approved artifact.' }
    $sumText = Get-Content -LiteralPath $sumsPath -Raw
    $unpackedLine = "$ExpectedUnpackedSha256  $unpackedName"
    if ($sumText -notmatch [Regex]::Escape($unpackedLine)) { throw 'Package checksum manifest does not bind the exact persistent ZIP.' }
    $script:Evidence.package.checksum_manifest_verified = $true

    if (-not $env:LOCALAPPDATA -or -not $env:APPDATA) { throw 'Owner profile application paths are unavailable.' }

    $repoRoot = Get-FullPath (Join-Path $PSScriptRoot '..')
    $paperSyncSource = Join-Path $PSScriptRoot 'nexus_prospective_paper_sync.ps1'
    $paperSyncValidator = Join-Path $repoRoot 'product_prospective_paper.py'
    $paperSyncRoot = Get-FullPath (Join-Path $env:LOCALAPPDATA 'NEXUS\paper-forward-sync')
    if (-not (Test-Path -LiteralPath $paperSyncSource -PathType Leaf)) { throw 'Canonical prospective Paper sync script is missing.' }
    if (-not (Test-Path -LiteralPath $paperSyncValidator -PathType Leaf)) { throw 'Prospective Paper validator is missing.' }
    New-Item -ItemType Directory -Path $paperSyncRoot -Force | Out-Null
    Assert-NotReparsePoint $paperSyncRoot 'Prospective Paper sync root'
    Copy-Item -LiteralPath $paperSyncSource -Destination (Join-Path $paperSyncRoot 'sync.ps1') -Force
    Copy-Item -LiteralPath $paperSyncValidator -Destination (Join-Path $paperSyncRoot 'product_prospective_paper.py') -Force
    Write-Host 'NEXUS_PAPER_SYNC_SOURCE_DEPLOYED=1'

    $programRoot = Get-FullPath (Join-Path $env:LOCALAPPDATA 'Programs\NEXUS Personal Pro')
    $installRoot = Get-FullPath (Join-Path $programRoot "5.1.0-$($ExpectedSourceSha.Substring(0, 8))")
    $script:ProgramRoot = $programRoot
    $script:InstallRoot = $installRoot
    if (-not (Test-PathWithin $installRoot $programRoot)) { throw 'Versioned installation escaped the NEXUS program root.' }
    New-Item -ItemType Directory -Path $programRoot -Force | Out-Null
    Assert-NotReparsePoint $programRoot 'NEXUS program root'
    $manifestPath = Join-Path $installRoot 'install-manifest.json'
    if (-not (Test-Path -LiteralPath $installRoot -PathType Container)) {
        $stagingRoot = Get-FullPath (Join-Path $programRoot ".incoming-$($ExpectedSourceSha.Substring(0, 8))-$($env:GITHUB_RUN_ID)")
        if (-not (Test-PathWithin $stagingRoot $programRoot)) { throw 'Install staging escaped the NEXUS program root.' }
        if (Test-Path -LiteralPath $stagingRoot) { throw 'Stale exact install staging root exists.' }
        $script:InstallStagingRoot = $stagingRoot
        New-Item -ItemType Directory -Path $stagingRoot | Out-Null
        Assert-NotReparsePoint $stagingRoot 'Install staging root'
        Expand-Archive -LiteralPath $unpackedPath -DestinationPath $stagingRoot -Force
        $reparse = @(Get-ChildItem -LiteralPath $stagingRoot -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint } | Select-Object -First 1)
        if ($reparse.Count -gt 0) { throw 'Persistent package contains a reparse point.' }
        $stagedExecutable = Join-Path $stagingRoot 'NEXUS Personal Pro.exe'
        $stagedSourceSha = Join-Path $stagingRoot 'resources\source-sha.txt'
        $stagedBuildEvidence = Join-Path $stagingRoot 'resources\build-evidence.json'
        $stagedSidecar = Join-Path $stagingRoot 'resources\nexus-product-server\nexus-product-server.exe'
        foreach ($requiredPath in @($stagedExecutable, $stagedSourceSha, $stagedBuildEvidence, $stagedSidecar)) {
            if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) { throw "Extracted persistent package is incomplete: $(Split-Path -Leaf $requiredPath)" }
            Assert-NotReparsePoint $requiredPath 'Extracted package file'
        }
        if ((Get-Content -LiteralPath $stagedSourceSha -Raw).Trim().ToLowerInvariant() -ne $ExpectedSourceSha) { throw 'Extracted package source SHA mismatch.' }
        $stagedEvidence = Get-Content -LiteralPath $stagedBuildEvidence -Raw | ConvertFrom-Json
        if (([string]$stagedEvidence.source_sha).ToLowerInvariant() -ne $ExpectedSourceSha -or
            $stagedEvidence.paper_only -ne $true -or $stagedEvidence.live_trading_authority -ne $false -or
            [string]$stagedEvidence.builder -ne 'github-actions/nexus-build-verification/windows-desktop') {
            throw 'Extracted package build evidence failed exact-source or authority validation.'
        }
        Move-Item -LiteralPath $stagingRoot -Destination $installRoot
        $script:InstallCreatedThisRun = $true
        $script:InstallStagingRoot = $null
    } else {
        Assert-NotReparsePoint $installRoot 'Versioned install root'
        if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw 'Existing exact-version install is missing its manifest.' }
        $existingManifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        if (([string]$existingManifest.source_sha).ToLowerInvariant() -ne $ExpectedSourceSha -or
            ([string]$existingManifest.unpacked_sha256).ToLowerInvariant() -ne $ExpectedUnpackedSha256) {
            throw 'Existing exact-version install is not bound to the approved persistent package.'
        }
    }

    $installedExecutable = Join-Path $installRoot 'NEXUS Personal Pro.exe'
    $installedSourceSha = Join-Path $installRoot 'resources\source-sha.txt'
    $installedBuildEvidence = Join-Path $installRoot 'resources\build-evidence.json'
    $installedSidecar = Join-Path $installRoot 'resources\nexus-product-server\nexus-product-server.exe'
    foreach ($requiredPath in @($installedExecutable, $installedSourceSha, $installedBuildEvidence, $installedSidecar)) {
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) { throw "Installed persistent package is incomplete: $(Split-Path -Leaf $requiredPath)" }
        Assert-NotReparsePoint $requiredPath 'Installed package file'
    }
    if ((Get-Content -LiteralPath $installedSourceSha -Raw).Trim().ToLowerInvariant() -ne $ExpectedSourceSha) { throw 'Installed package source SHA mismatch.' }
    $installedEvidence = Get-Content -LiteralPath $installedBuildEvidence -Raw | ConvertFrom-Json
    if (([string]$installedEvidence.source_sha).ToLowerInvariant() -ne $ExpectedSourceSha -or
        $installedEvidence.paper_only -ne $true -or $installedEvidence.live_trading_authority -ne $false -or
        [string]$installedEvidence.builder -ne 'github-actions/nexus-build-verification/windows-desktop') {
        throw 'Installed package build evidence failed exact-source or authority validation.'
    }
    $script:Evidence.install.executable_deployed = $true

    $installManifest = [ordered]@{
        schema_version = 'nexus.windows-side-by-side-install.v2'
        version = '5.1.0'
        install_mode = 'persistent_unpacked'
        source_sha = $ExpectedSourceSha
        unpacked_sha256 = $ExpectedUnpackedSha256
        artifact_name = $ArtifactName
        artifact_run_id = $ArtifactRunId
        artifact_id = $ArtifactId
        executable = 'NEXUS Personal Pro.exe'
        installed_at = [DateTime]::UtcNow.ToString('o')
        paper_only = $true
        live_trading_authority = $false
        previous_install_removed = $false
    }
    [IO.File]::WriteAllText($manifestPath, ($installManifest | ConvertTo-Json -Depth 4), (New-Object Text.UTF8Encoding($false)))
    $script:Evidence.install.manifest_written = $true

    foreach ($process in @(Get-NexusProcesses)) { $script:BaselineNexusProcessIds[[int]$process.Id] = $true }
    $preexistingGuiCount = @(Get-NexusProcesses | Where-Object { $_.MainWindowHandle -ne 0 }).Count
    $script:SmokeRoot = Join-Path $env:RUNNER_TEMP "nexus-app-smoke-$($env:GITHUB_RUN_ID)"
    if (Test-Path -LiteralPath $script:SmokeRoot) { throw 'Exact smoke root already exists; refusing to reuse stale test state.' }
    New-Item -ItemType Directory -Path $script:SmokeRoot | Out-Null
    $smokeStarted = [DateTime]::UtcNow
    $smokeArguments = @("--user-data-dir=`"$($script:SmokeRoot)`"", "--nexus-install-smoke=$($env:GITHUB_RUN_ID)")
    [void](Start-Process -FilePath $installedExecutable -ArgumentList $smokeArguments -PassThru)
    $script:Evidence.smoke.process_started = $true
    $state = Wait-ForHealthySupervisor -Root $script:SmokeRoot -NotBeforeUtc $smokeStarted -TimeoutSeconds 420
    $script:Evidence.smoke.supervisor_healthy = $true
    if (-not (Wait-ForVisibleNewWindow -TimeoutSeconds 90)) { throw 'NEXUS started but no visible Mission Control window was observed.' }
    $script:Evidence.smoke.visible_window_observed = $true
    Invoke-ProductContract -Origin ([string]$state.origin)
    $script:InstallSmokeVerified = $true
    Write-Evidence

    Stop-SmokeProcesses
    Remove-SmokeRoot

    $desktopShortcut = Join-Path ([Environment]::GetFolderPath('Desktop')) 'NEXUS Personal Pro 5.1.0.lnk'
    $startMenuShortcut = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\NEXUS Personal Pro 5.1.0.lnk'
    $genericStartMenuShortcut = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\NEXUS Personal Pro.lnk'
    $startupShortcut = Join-Path ([Environment]::GetFolderPath('Startup')) 'NEXUS Personal Pro.lnk'
    New-NexusShortcut $desktopShortcut $installedExecutable
    $script:Evidence.install.desktop_shortcut_created = $true
    New-NexusShortcut $startMenuShortcut $installedExecutable
    New-NexusShortcut $genericStartMenuShortcut $installedExecutable
    $script:Evidence.install.start_menu_shortcut_created = $true
    New-NexusShortcut $startupShortcut $installedExecutable
    $script:Evidence.install.startup_shortcut_created = $true
    Write-Host "NEXUS_APP_AUTOSTART_SHORTCUT=$startupShortcut"

    if ($preexistingGuiCount -gt 0) {
        $script:Evidence.final_launch.status = 'SKIPPED_EXISTING_APP_PRESERVED'
        $script:Evidence.final_launch.preexisting_app_preserved = $true
    } else {
        $tracking = [Environment]::GetEnvironmentVariable('RUNNER_TRACKING_ID', 'Process')
        [Environment]::SetEnvironmentVariable('RUNNER_TRACKING_ID', $null, 'Process')
        try { [void](Start-Process -FilePath $installedExecutable -ArgumentList @("--nexus-installed-source=$($ExpectedSourceSha.Substring(0, 8))")) }
        finally { [Environment]::SetEnvironmentVariable('RUNNER_TRACKING_ID', $tracking, 'Process') }
        if (-not (Wait-ForVisibleNewWindow -TimeoutSeconds 300)) { throw 'Installed NEXUS final window did not become visible.' }
        $script:Evidence.final_launch.status = 'RUNNING_VISIBLE'
        $script:Evidence.final_launch.visible_window_observed = $true
    }

    Invoke-NexusRetention -CurrentInstallRoot $installRoot -CurrentArtifactId $ArtifactId
    $script:Evidence.decision = 'PASS'
    Write-Evidence
    Write-Host "NEXUS_WINDOWS_APP_INSTALL=PASS source=$ExpectedSourceSha artifact=$ArtifactId"
} catch {
    try { Stop-SmokeProcesses } catch { }
    try { Remove-SmokeRoot } catch { }
    try {
        if ($script:InstallStagingRoot -and $script:ProgramRoot -and
            (Test-Path -LiteralPath $script:InstallStagingRoot) -and
            (Test-PathWithin $script:InstallStagingRoot $script:ProgramRoot)) {
            Remove-Item -LiteralPath $script:InstallStagingRoot -Recurse -Force
        }
    } catch { }
    try {
        if ($script:InstallCreatedThisRun -and -not $script:InstallSmokeVerified -and
            $script:InstallRoot -and $script:ProgramRoot -and
            (Test-Path -LiteralPath $script:InstallRoot) -and
            (Test-PathWithin $script:InstallRoot $script:ProgramRoot)) {
            Remove-Item -LiteralPath $script:InstallRoot -Recurse -Force
        }
    } catch { }
    $script:Evidence.decision = 'FAIL_CLOSED'
    $script:Evidence.error = ConvertTo-SafeError $_.Exception.Message
    try { Write-Evidence } catch { }
    Write-Error ("NEXUS Windows app installation failed closed: " + (ConvertTo-SafeError $_.Exception.Message))
    exit 1
} finally {
    try { Remove-PackageTransport } catch { Write-Warning (ConvertTo-SafeError $_.Exception.Message) }
}
 } |
                Sort-Object LastWriteTimeUtc -Descending
        )
        $keepVersionPaths = @($currentInstall)
        foreach ($dir in $versionDirs) {
            if ($keepVersionPaths.Count -ge 3) { break }
            $full = Get-FullPath $dir.FullName
            if ($full -ine $currentInstall -and $keepVersionPaths -notcontains $full) { $keepVersionPaths += $full }
        }
        foreach ($dir in $versionDirs) {
            $full = Get-FullPath $dir.FullName
            if ($keepVersionPaths -contains $full) { continue }
            if (-not (Test-PathWithin $full $script:ProgramRoot)) { throw 'Retention candidate escaped the NEXUS program root.' }
            Assert-NotReparsePoint $full 'Retention version candidate'
            $prefix = $full.TrimEnd('\') + '\'
            $active = @($activePaths | Where-Object { $_.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) })
            if ($active.Count -gt 0) {
                $script:Evidence.install.active_version_skips += 1
                continue
            }
            Remove-Item -LiteralPath $full -Recurse -Force -ErrorAction Stop
            $script:Evidence.install.removed_version_count += 1
        }

        $cacheRoot = Get-FullPath (Join-Path $env:LOCALAPPDATA 'NEXUS\artifact-cache')
        if (Test-Path -LiteralPath $cacheRoot -PathType Container) {
            Assert-NotReparsePoint $cacheRoot 'NEXUS artifact cache root'
            $cacheDirs = @(
                Get-ChildItem -LiteralPath $cacheRoot -Directory -ErrorAction SilentlyContinue |
                    Where-Object { $_.Name -match '^nexus-windows-persistent-unpacked-[0-9]+
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) { return $null }
    $direct = Join-Path $Root 'product-data\supervisor-state.json'
    if (Test-Path -LiteralPath $direct -PathType Leaf) { return $direct }
    return Get-ChildItem -LiteralPath $Root -Filter 'supervisor-state.json' -File -Recurse -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1 -ExpandProperty FullName
}

function Wait-ForHealthySupervisor([string]$Root, [DateTime]$NotBeforeUtc, [int]$TimeoutSeconds = 120) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $lastError = $null
    do {
        $statePath = Find-SupervisorState $Root
        if ($statePath) {
            try {
                $item = Get-Item -LiteralPath $statePath
                $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
                if ($item.LastWriteTimeUtc -ge $NotBeforeUtc.AddSeconds(-3) -and [string]$state.status -eq 'healthy' -and
                    ([string]$state.source_sha).ToLowerInvariant() -eq $ExpectedSourceSha -and
                    [string]$state.origin -match '^http://127\.0\.0\.1:[0-9]+$') { return $state }
            } catch { $lastError = $_.Exception.Message }
        }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "NEXUS supervisor did not become healthy for the expected source. $lastError"
}

function Wait-ForVisibleNewWindow([int]$TimeoutSeconds = 90) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        foreach ($process in @(Get-NewNexusProcesses)) {
            try {
                $process.Refresh()
                if ($process.MainWindowHandle -ne 0 -and [string]$process.MainWindowTitle -match '(?i)NEXUS') { return $true }
            } catch { }
        }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)
    return $false
}

function New-NexusShortcut([string]$ShortcutPath, [string]$ExecutablePath) {
    $parent = Split-Path -Parent $ShortcutPath
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($ShortcutPath)
    $shortcut.TargetPath = $ExecutablePath
    $shortcut.WorkingDirectory = Split-Path -Parent $ExecutablePath
    $shortcut.IconLocation = "$ExecutablePath,0"
    $shortcut.Description = "NEXUS Personal Pro 5.1.0 ($($ExpectedSourceSha.Substring(0, 8)))"
    $shortcut.Save()
    if (-not (Test-Path -LiteralPath $ShortcutPath -PathType Leaf)) { throw 'NEXUS shortcut creation failed.' }
}

function Invoke-ProductContract([string]$Origin) {
    $overview = Invoke-RestMethod -Uri "$Origin/api/product/overview" -TimeoutSec 10
    if ($overview.paper.active -ne $true -or $overview.live.enabled -ne $false) { throw 'Product overview authority contract failed.' }
    $script:Evidence.smoke.overview_ok = $true

    $paper = Invoke-RestMethod -Uri "$Origin/api/product/paper" -TimeoutSec 10
    if ($paper.paper_only -ne $true) { throw 'Paper-only contract failed.' }
    $script:Evidence.smoke.paper_only = $true

    $live = Invoke-RestMethod -Uri "$Origin/api/product/live" -TimeoutSec 10
    $script:Evidence.smoke.live_trading_authority = [bool]$live.live_trading_authority
    $script:Evidence.smoke.live_orders_allowed = [bool]$live.orders_allowed
    if ($live.live_trading_authority -ne $false -or $live.orders_allowed -ne $false) { throw 'Live trading authority widened during laptop smoke test.' }

    $offline = Invoke-RestMethod -Uri "$Origin/api/product/offline" -TimeoutSec 10
    if ($offline.mode -ne 'offline_first' -or $offline.live_trading_authority -ne $false) { throw 'Offline-first contract failed.' }
    $script:Evidence.smoke.offline_first = $true

    $mission = Invoke-RestMethod -Uri "$Origin/api/product/mission/full" -TimeoutSec 10
    if ($mission.paper_only -ne $true -or $mission.live_trading_authority -ne $false) { throw 'Mission Control authority contract failed.' }
    $script:Evidence.smoke.mission_control_ok = $true

    $build = Invoke-RestMethod -Uri "$Origin/api/product/build-evidence" -TimeoutSec 10
    if ($build.status -ne 'verified' -or $build.exact_source -ne $true -or ([string]$build.source_sha).ToLowerInvariant() -ne $ExpectedSourceSha) {
        throw 'Installed product exact-source evidence failed.'
    }

    $strategies = Invoke-RestMethod -Uri "$Origin/api/product/strategies/evidence" -TimeoutSec 10
    if ($strategies.paper_only -ne $true -or $strategies.profitability_claim -ne $false) { throw 'Strategy evidence boundary failed.' }
    $script:Evidence.smoke.strategy_evidence_ok = $true

    if ([string]$overview.capabilities.deterministic_risk -ne 'final_paper_authority') {
        throw 'Deterministic Risk authority is missing from product overview.'
    }
    $script:Evidence.smoke.deterministic_risk_present = $true

    $index = Invoke-WebRequest -UseBasicParsing -Uri "$Origin/" -TimeoutSec 10
    if ($index.StatusCode -ne 200 -or $index.Content -notmatch 'NEXUS Personal Pro' -or $index.Content -notmatch 'Mission Control') {
        throw 'Mission Control UI did not load.'
    }
    $script:Evidence.smoke.ui_loaded = $true
}

try {
    if ($env:GITHUB_ACTIONS -ne 'true') { throw 'This installer is restricted to GitHub Actions.' }
    if ($env:GITHUB_REPOSITORY -ne 'saladinayoubi1/lbank-research-automation') { throw 'Unexpected repository.' }
    if ($env:GITHUB_REF -ne 'refs/heads/main') { throw 'Laptop installation is restricted to main.' }
    if ($env:RUNNER_NAME -ne $ExpectedRunnerName) { throw "Unexpected runner: $($env:RUNNER_NAME)" }
    $actualComputerName = [string]$env:COMPUTERNAME
    if ([string]::IsNullOrWhiteSpace($actualComputerName)) { $actualComputerName = [Environment]::MachineName }
    if ($actualComputerName -ine $ExpectedComputerName) { throw "Unexpected computer: $actualComputerName" }

    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    if ($identity.Name -match '^(?i:NT AUTHORITY\\(?:SYSTEM|LOCAL SERVICE|NETWORK SERVICE))$') {
        throw 'Service identities cannot install the owner desktop application.'
    }
    if (-not [Environment]::UserInteractive) { throw 'An interactive owner session is required.' }
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    $elevated = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    $script:Evidence.target.elevated = [bool]$elevated
    if ($elevated) { throw 'Elevated installation is forbidden; use the normal owner session.' }
    $sessionId = (Get-Process -Id $PID).SessionId
    $explorer = @(Get-Process -Name explorer -ErrorAction SilentlyContinue | Where-Object { $_.SessionId -eq $sessionId })
    if ($explorer.Count -lt 1) { throw 'Explorer is not running in the runner session; refusing a non-visible GUI install.' }
    $script:Evidence.target.owner_user_context = $true
    $script:Evidence.target.interactive_desktop = $true

    if (-not $env:RUNNER_TEMP) { throw 'RUNNER_TEMP is required for bounded artifact transport.' }
    $packageRootFull = Get-FullPath $PackageRoot
    if (-not (Test-PathWithin $packageRootFull $env:RUNNER_TEMP)) { throw 'Package transport escaped RUNNER_TEMP.' }
    if ((Split-Path -Leaf $packageRootFull) -notmatch '^nexus-personal-pro-package-[0-9]+$') {
        throw 'Unexpected package transport leaf.'
    }
    if ($UsePreloadedPackage) {
        if (-not (Test-Path -LiteralPath $packageRootFull -PathType Container)) { throw 'Preloaded package root is missing.' }
        $script:Evidence.package.download_transport = 'actions_download_artifact'
        $script:Evidence.package.workflow_token_used = $true
        $script:Evidence.package.downloaded = $true
    } else {
        if (Test-Path -LiteralPath $packageRootFull) { throw 'Stale package transport already exists.' }
        $gh = Get-Command gh.exe -ErrorAction SilentlyContinue
        if (-not $gh) { $gh = Get-Command gh -ErrorAction SilentlyContinue }
        if (-not $gh) { throw 'Existing owner GitHub CLI is unavailable.' }
        $previousGhToken = [Environment]::GetEnvironmentVariable('GH_TOKEN', 'Process')
        $previousGitHubToken = [Environment]::GetEnvironmentVariable('GITHUB_TOKEN', 'Process')
        [Environment]::SetEnvironmentVariable('GH_TOKEN', $null, 'Process')
        [Environment]::SetEnvironmentVariable('GITHUB_TOKEN', $null, 'Process')
        try {
            & $gh.Source run download "$ArtifactRunId" --repo 'saladinayoubi1/lbank-research-automation' --name $ArtifactName --dir $packageRootFull
            if ($LASTEXITCODE -ne 0) { throw 'Existing owner GitHub CLI could not download the exact approved artifact.' }
        } finally {
            [Environment]::SetEnvironmentVariable('GH_TOKEN', $previousGhToken, 'Process')
            [Environment]::SetEnvironmentVariable('GITHUB_TOKEN', $previousGitHubToken, 'Process')
        }
        if (-not (Test-Path -LiteralPath $packageRootFull -PathType Container)) { throw 'Package root is missing after download.' }
        $script:Evidence.package.downloaded = $true
    }
    Assert-NotReparsePoint $packageRootFull 'Package root'
    $unpackedName = 'NEXUS_Personal_Pro_Unpacked_5.1.0_x64.zip'
    $unpackedPath = Join-Path $packageRootFull $unpackedName
    $sumsPath = Join-Path $packageRootFull 'SHA256SUMS.txt'
    foreach ($requiredPath in @($unpackedPath, $sumsPath)) {
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) { throw "Required package file is missing: $(Split-Path -Leaf $requiredPath)" }
        Assert-NotReparsePoint $requiredPath 'Package file'
    }
    if ((Get-Item -LiteralPath $unpackedPath).Length -lt 100MB) { throw 'Persistent NEXUS package is unexpectedly small.' }
    $unpackedSha = (Get-FileHash -LiteralPath $unpackedPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $script:Evidence.package.unpacked_sha256 = $unpackedSha
    if ($unpackedSha -ne $ExpectedUnpackedSha256) { throw 'Persistent unpacked ZIP SHA256 does not match the exact approved artifact.' }
    $sumText = Get-Content -LiteralPath $sumsPath -Raw
    $unpackedLine = "$ExpectedUnpackedSha256  $unpackedName"
    if ($sumText -notmatch [Regex]::Escape($unpackedLine)) { throw 'Package checksum manifest does not bind the exact persistent ZIP.' }
    $script:Evidence.package.checksum_manifest_verified = $true

    if (-not $env:LOCALAPPDATA -or -not $env:APPDATA) { throw 'Owner profile application paths are unavailable.' }

    $repoRoot = Get-FullPath (Join-Path $PSScriptRoot '..')
    $paperSyncSource = Join-Path $PSScriptRoot 'nexus_prospective_paper_sync.ps1'
    $paperSyncValidator = Join-Path $repoRoot 'product_prospective_paper.py'
    $paperSyncRoot = Get-FullPath (Join-Path $env:LOCALAPPDATA 'NEXUS\paper-forward-sync')
    if (-not (Test-Path -LiteralPath $paperSyncSource -PathType Leaf)) { throw 'Canonical prospective Paper sync script is missing.' }
    if (-not (Test-Path -LiteralPath $paperSyncValidator -PathType Leaf)) { throw 'Prospective Paper validator is missing.' }
    New-Item -ItemType Directory -Path $paperSyncRoot -Force | Out-Null
    Assert-NotReparsePoint $paperSyncRoot 'Prospective Paper sync root'
    Copy-Item -LiteralPath $paperSyncSource -Destination (Join-Path $paperSyncRoot 'sync.ps1') -Force
    Copy-Item -LiteralPath $paperSyncValidator -Destination (Join-Path $paperSyncRoot 'product_prospective_paper.py') -Force
    Write-Host 'NEXUS_PAPER_SYNC_SOURCE_DEPLOYED=1'

    $programRoot = Get-FullPath (Join-Path $env:LOCALAPPDATA 'Programs\NEXUS Personal Pro')
    $installRoot = Get-FullPath (Join-Path $programRoot "5.1.0-$($ExpectedSourceSha.Substring(0, 8))")
    $script:ProgramRoot = $programRoot
    $script:InstallRoot = $installRoot
    if (-not (Test-PathWithin $installRoot $programRoot)) { throw 'Versioned installation escaped the NEXUS program root.' }
    New-Item -ItemType Directory -Path $programRoot -Force | Out-Null
    Assert-NotReparsePoint $programRoot 'NEXUS program root'
    $manifestPath = Join-Path $installRoot 'install-manifest.json'
    if (-not (Test-Path -LiteralPath $installRoot -PathType Container)) {
        $stagingRoot = Get-FullPath (Join-Path $programRoot ".incoming-$($ExpectedSourceSha.Substring(0, 8))-$($env:GITHUB_RUN_ID)")
        if (-not (Test-PathWithin $stagingRoot $programRoot)) { throw 'Install staging escaped the NEXUS program root.' }
        if (Test-Path -LiteralPath $stagingRoot) { throw 'Stale exact install staging root exists.' }
        $script:InstallStagingRoot = $stagingRoot
        New-Item -ItemType Directory -Path $stagingRoot | Out-Null
        Assert-NotReparsePoint $stagingRoot 'Install staging root'
        Expand-Archive -LiteralPath $unpackedPath -DestinationPath $stagingRoot -Force
        $reparse = @(Get-ChildItem -LiteralPath $stagingRoot -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint } | Select-Object -First 1)
        if ($reparse.Count -gt 0) { throw 'Persistent package contains a reparse point.' }
        $stagedExecutable = Join-Path $stagingRoot 'NEXUS Personal Pro.exe'
        $stagedSourceSha = Join-Path $stagingRoot 'resources\source-sha.txt'
        $stagedBuildEvidence = Join-Path $stagingRoot 'resources\build-evidence.json'
        $stagedSidecar = Join-Path $stagingRoot 'resources\nexus-product-server\nexus-product-server.exe'
        foreach ($requiredPath in @($stagedExecutable, $stagedSourceSha, $stagedBuildEvidence, $stagedSidecar)) {
            if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) { throw "Extracted persistent package is incomplete: $(Split-Path -Leaf $requiredPath)" }
            Assert-NotReparsePoint $requiredPath 'Extracted package file'
        }
        if ((Get-Content -LiteralPath $stagedSourceSha -Raw).Trim().ToLowerInvariant() -ne $ExpectedSourceSha) { throw 'Extracted package source SHA mismatch.' }
        $stagedEvidence = Get-Content -LiteralPath $stagedBuildEvidence -Raw | ConvertFrom-Json
        if (([string]$stagedEvidence.source_sha).ToLowerInvariant() -ne $ExpectedSourceSha -or
            $stagedEvidence.paper_only -ne $true -or $stagedEvidence.live_trading_authority -ne $false -or
            [string]$stagedEvidence.builder -ne 'github-actions/nexus-build-verification/windows-desktop') {
            throw 'Extracted package build evidence failed exact-source or authority validation.'
        }
        Move-Item -LiteralPath $stagingRoot -Destination $installRoot
        $script:InstallCreatedThisRun = $true
        $script:InstallStagingRoot = $null
    } else {
        Assert-NotReparsePoint $installRoot 'Versioned install root'
        if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw 'Existing exact-version install is missing its manifest.' }
        $existingManifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        if (([string]$existingManifest.source_sha).ToLowerInvariant() -ne $ExpectedSourceSha -or
            ([string]$existingManifest.unpacked_sha256).ToLowerInvariant() -ne $ExpectedUnpackedSha256) {
            throw 'Existing exact-version install is not bound to the approved persistent package.'
        }
    }

    $installedExecutable = Join-Path $installRoot 'NEXUS Personal Pro.exe'
    $installedSourceSha = Join-Path $installRoot 'resources\source-sha.txt'
    $installedBuildEvidence = Join-Path $installRoot 'resources\build-evidence.json'
    $installedSidecar = Join-Path $installRoot 'resources\nexus-product-server\nexus-product-server.exe'
    foreach ($requiredPath in @($installedExecutable, $installedSourceSha, $installedBuildEvidence, $installedSidecar)) {
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) { throw "Installed persistent package is incomplete: $(Split-Path -Leaf $requiredPath)" }
        Assert-NotReparsePoint $requiredPath 'Installed package file'
    }
    if ((Get-Content -LiteralPath $installedSourceSha -Raw).Trim().ToLowerInvariant() -ne $ExpectedSourceSha) { throw 'Installed package source SHA mismatch.' }
    $installedEvidence = Get-Content -LiteralPath $installedBuildEvidence -Raw | ConvertFrom-Json
    if (([string]$installedEvidence.source_sha).ToLowerInvariant() -ne $ExpectedSourceSha -or
        $installedEvidence.paper_only -ne $true -or $installedEvidence.live_trading_authority -ne $false -or
        [string]$installedEvidence.builder -ne 'github-actions/nexus-build-verification/windows-desktop') {
        throw 'Installed package build evidence failed exact-source or authority validation.'
    }
    $script:Evidence.install.executable_deployed = $true

    $installManifest = [ordered]@{
        schema_version = 'nexus.windows-side-by-side-install.v2'
        version = '5.1.0'
        install_mode = 'persistent_unpacked'
        source_sha = $ExpectedSourceSha
        unpacked_sha256 = $ExpectedUnpackedSha256
        artifact_name = $ArtifactName
        artifact_run_id = $ArtifactRunId
        artifact_id = $ArtifactId
        executable = 'NEXUS Personal Pro.exe'
        installed_at = [DateTime]::UtcNow.ToString('o')
        paper_only = $true
        live_trading_authority = $false
        previous_install_removed = $false
    }
    [IO.File]::WriteAllText($manifestPath, ($installManifest | ConvertTo-Json -Depth 4), (New-Object Text.UTF8Encoding($false)))
    $script:Evidence.install.manifest_written = $true

    foreach ($process in @(Get-NexusProcesses)) { $script:BaselineNexusProcessIds[[int]$process.Id] = $true }
    $preexistingGuiCount = @(Get-NexusProcesses | Where-Object { $_.MainWindowHandle -ne 0 }).Count
    $script:SmokeRoot = Join-Path $env:RUNNER_TEMP "nexus-app-smoke-$($env:GITHUB_RUN_ID)"
    if (Test-Path -LiteralPath $script:SmokeRoot) { throw 'Exact smoke root already exists; refusing to reuse stale test state.' }
    New-Item -ItemType Directory -Path $script:SmokeRoot | Out-Null
    $smokeStarted = [DateTime]::UtcNow
    $smokeArguments = @("--user-data-dir=`"$($script:SmokeRoot)`"", "--nexus-install-smoke=$($env:GITHUB_RUN_ID)")
    [void](Start-Process -FilePath $installedExecutable -ArgumentList $smokeArguments -PassThru)
    $script:Evidence.smoke.process_started = $true
    $state = Wait-ForHealthySupervisor -Root $script:SmokeRoot -NotBeforeUtc $smokeStarted -TimeoutSeconds 420
    $script:Evidence.smoke.supervisor_healthy = $true
    if (-not (Wait-ForVisibleNewWindow -TimeoutSeconds 90)) { throw 'NEXUS started but no visible Mission Control window was observed.' }
    $script:Evidence.smoke.visible_window_observed = $true
    Invoke-ProductContract -Origin ([string]$state.origin)
    $script:InstallSmokeVerified = $true
    Write-Evidence

    Stop-SmokeProcesses
    Remove-SmokeRoot

    $desktopShortcut = Join-Path ([Environment]::GetFolderPath('Desktop')) 'NEXUS Personal Pro 5.1.0.lnk'
    $startMenuShortcut = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\NEXUS Personal Pro 5.1.0.lnk'
    $genericStartMenuShortcut = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\NEXUS Personal Pro.lnk'
    $startupShortcut = Join-Path ([Environment]::GetFolderPath('Startup')) 'NEXUS Personal Pro.lnk'
    New-NexusShortcut $desktopShortcut $installedExecutable
    $script:Evidence.install.desktop_shortcut_created = $true
    New-NexusShortcut $startMenuShortcut $installedExecutable
    New-NexusShortcut $genericStartMenuShortcut $installedExecutable
    $script:Evidence.install.start_menu_shortcut_created = $true
    New-NexusShortcut $startupShortcut $installedExecutable
    $script:Evidence.install.startup_shortcut_created = $true
    Write-Host "NEXUS_APP_AUTOSTART_SHORTCUT=$startupShortcut"

    if ($preexistingGuiCount -gt 0) {
        $script:Evidence.final_launch.status = 'SKIPPED_EXISTING_APP_PRESERVED'
        $script:Evidence.final_launch.preexisting_app_preserved = $true
    } else {
        $tracking = [Environment]::GetEnvironmentVariable('RUNNER_TRACKING_ID', 'Process')
        [Environment]::SetEnvironmentVariable('RUNNER_TRACKING_ID', $null, 'Process')
        try { [void](Start-Process -FilePath $installedExecutable -ArgumentList @("--nexus-installed-source=$($ExpectedSourceSha.Substring(0, 8))")) }
        finally { [Environment]::SetEnvironmentVariable('RUNNER_TRACKING_ID', $tracking, 'Process') }
        if (-not (Wait-ForVisibleNewWindow -TimeoutSeconds 300)) { throw 'Installed NEXUS final window did not become visible.' }
        $script:Evidence.final_launch.status = 'RUNNING_VISIBLE'
        $script:Evidence.final_launch.visible_window_observed = $true
    }

    $script:Evidence.decision = 'PASS'
    Write-Evidence
    Write-Host "NEXUS_WINDOWS_APP_INSTALL=PASS source=$ExpectedSourceSha artifact=$ArtifactId"
} catch {
    try { Stop-SmokeProcesses } catch { }
    try { Remove-SmokeRoot } catch { }
    try {
        if ($script:InstallStagingRoot -and $script:ProgramRoot -and
            (Test-Path -LiteralPath $script:InstallStagingRoot) -and
            (Test-PathWithin $script:InstallStagingRoot $script:ProgramRoot)) {
            Remove-Item -LiteralPath $script:InstallStagingRoot -Recurse -Force
        }
    } catch { }
    try {
        if ($script:InstallCreatedThisRun -and -not $script:InstallSmokeVerified -and
            $script:InstallRoot -and $script:ProgramRoot -and
            (Test-Path -LiteralPath $script:InstallRoot) -and
            (Test-PathWithin $script:InstallRoot $script:ProgramRoot)) {
            Remove-Item -LiteralPath $script:InstallRoot -Recurse -Force
        }
    } catch { }
    $script:Evidence.decision = 'FAIL_CLOSED'
    $script:Evidence.error = ConvertTo-SafeError $_.Exception.Message
    try { Write-Evidence } catch { }
    Write-Error ("NEXUS Windows app installation failed closed: " + (ConvertTo-SafeError $_.Exception.Message))
    exit 1
} finally {
    try { Remove-PackageTransport } catch { Write-Warning (ConvertTo-SafeError $_.Exception.Message) }
}
 } |
                    Sort-Object LastWriteTimeUtc -Descending
            )
            $currentCache = Get-FullPath (Join-Path $cacheRoot "nexus-windows-persistent-unpacked-$CurrentArtifactId")
            $keepCachePaths = @($currentCache)
            foreach ($dir in $cacheDirs) {
                if ($keepCachePaths.Count -ge 2) { break }
                $full = Get-FullPath $dir.FullName
                if ($full -ine $currentCache -and $keepCachePaths -notcontains $full) { $keepCachePaths += $full }
            }
            foreach ($dir in $cacheDirs) {
                $full = Get-FullPath $dir.FullName
                if ($keepCachePaths -contains $full) { continue }
                if (-not (Test-PathWithin $full $cacheRoot)) { throw 'Artifact cache retention candidate escaped the cache root.' }
                Assert-NotReparsePoint $full 'Artifact cache retention candidate'
                Remove-Item -LiteralPath $full -Recurse -Force -ErrorAction Stop
                $script:Evidence.install.removed_cache_count += 1
            }
        }

        $script:Evidence.install.retention_cleanup_succeeded = $true
    } catch {
        $warning = ConvertTo-SafeError $_.Exception.Message
        $script:Evidence.install.cleanup_warning = $warning
        Write-Warning ("NEXUS retention cleanup was non-fatal: " + $warning)
    }
}

function Find-SupervisorState([string]$Root) {
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) { return $null }
    $direct = Join-Path $Root 'product-data\supervisor-state.json'
    if (Test-Path -LiteralPath $direct -PathType Leaf) { return $direct }
    return Get-ChildItem -LiteralPath $Root -Filter 'supervisor-state.json' -File -Recurse -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1 -ExpandProperty FullName
}

function Wait-ForHealthySupervisor([string]$Root, [DateTime]$NotBeforeUtc, [int]$TimeoutSeconds = 120) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $lastError = $null
    do {
        $statePath = Find-SupervisorState $Root
        if ($statePath) {
            try {
                $item = Get-Item -LiteralPath $statePath
                $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
                if ($item.LastWriteTimeUtc -ge $NotBeforeUtc.AddSeconds(-3) -and [string]$state.status -eq 'healthy' -and
                    ([string]$state.source_sha).ToLowerInvariant() -eq $ExpectedSourceSha -and
                    [string]$state.origin -match '^http://127\.0\.0\.1:[0-9]+$') { return $state }
            } catch { $lastError = $_.Exception.Message }
        }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "NEXUS supervisor did not become healthy for the expected source. $lastError"
}

function Wait-ForVisibleNewWindow([int]$TimeoutSeconds = 90) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        foreach ($process in @(Get-NewNexusProcesses)) {
            try {
                $process.Refresh()
                if ($process.MainWindowHandle -ne 0 -and [string]$process.MainWindowTitle -match '(?i)NEXUS') { return $true }
            } catch { }
        }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)
    return $false
}

function New-NexusShortcut([string]$ShortcutPath, [string]$ExecutablePath) {
    $parent = Split-Path -Parent $ShortcutPath
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($ShortcutPath)
    $shortcut.TargetPath = $ExecutablePath
    $shortcut.WorkingDirectory = Split-Path -Parent $ExecutablePath
    $shortcut.IconLocation = "$ExecutablePath,0"
    $shortcut.Description = "NEXUS Personal Pro 5.1.0 ($($ExpectedSourceSha.Substring(0, 8)))"
    $shortcut.Save()
    if (-not (Test-Path -LiteralPath $ShortcutPath -PathType Leaf)) { throw 'NEXUS shortcut creation failed.' }
}

function Invoke-ProductContract([string]$Origin) {
    $overview = Invoke-RestMethod -Uri "$Origin/api/product/overview" -TimeoutSec 10
    if ($overview.paper.active -ne $true -or $overview.live.enabled -ne $false) { throw 'Product overview authority contract failed.' }
    $script:Evidence.smoke.overview_ok = $true

    $paper = Invoke-RestMethod -Uri "$Origin/api/product/paper" -TimeoutSec 10
    if ($paper.paper_only -ne $true) { throw 'Paper-only contract failed.' }
    $script:Evidence.smoke.paper_only = $true

    $live = Invoke-RestMethod -Uri "$Origin/api/product/live" -TimeoutSec 10
    $script:Evidence.smoke.live_trading_authority = [bool]$live.live_trading_authority
    $script:Evidence.smoke.live_orders_allowed = [bool]$live.orders_allowed
    if ($live.live_trading_authority -ne $false -or $live.orders_allowed -ne $false) { throw 'Live trading authority widened during laptop smoke test.' }

    $offline = Invoke-RestMethod -Uri "$Origin/api/product/offline" -TimeoutSec 10
    if ($offline.mode -ne 'offline_first' -or $offline.live_trading_authority -ne $false) { throw 'Offline-first contract failed.' }
    $script:Evidence.smoke.offline_first = $true

    $mission = Invoke-RestMethod -Uri "$Origin/api/product/mission/full" -TimeoutSec 10
    if ($mission.paper_only -ne $true -or $mission.live_trading_authority -ne $false) { throw 'Mission Control authority contract failed.' }
    $script:Evidence.smoke.mission_control_ok = $true

    $build = Invoke-RestMethod -Uri "$Origin/api/product/build-evidence" -TimeoutSec 10
    if ($build.status -ne 'verified' -or $build.exact_source -ne $true -or ([string]$build.source_sha).ToLowerInvariant() -ne $ExpectedSourceSha) {
        throw 'Installed product exact-source evidence failed.'
    }

    $strategies = Invoke-RestMethod -Uri "$Origin/api/product/strategies/evidence" -TimeoutSec 10
    if ($strategies.paper_only -ne $true -or $strategies.profitability_claim -ne $false) { throw 'Strategy evidence boundary failed.' }
    $script:Evidence.smoke.strategy_evidence_ok = $true

    if ([string]$overview.capabilities.deterministic_risk -ne 'final_paper_authority') {
        throw 'Deterministic Risk authority is missing from product overview.'
    }
    $script:Evidence.smoke.deterministic_risk_present = $true

    $index = Invoke-WebRequest -UseBasicParsing -Uri "$Origin/" -TimeoutSec 10
    if ($index.StatusCode -ne 200 -or $index.Content -notmatch 'NEXUS Personal Pro' -or $index.Content -notmatch 'Mission Control') {
        throw 'Mission Control UI did not load.'
    }
    $script:Evidence.smoke.ui_loaded = $true
}

try {
    if ($env:GITHUB_ACTIONS -ne 'true') { throw 'This installer is restricted to GitHub Actions.' }
    if ($env:GITHUB_REPOSITORY -ne 'saladinayoubi1/lbank-research-automation') { throw 'Unexpected repository.' }
    if ($env:GITHUB_REF -ne 'refs/heads/main') { throw 'Laptop installation is restricted to main.' }
    if ($env:RUNNER_NAME -ne $ExpectedRunnerName) { throw "Unexpected runner: $($env:RUNNER_NAME)" }
    $actualComputerName = [string]$env:COMPUTERNAME
    if ([string]::IsNullOrWhiteSpace($actualComputerName)) { $actualComputerName = [Environment]::MachineName }
    if ($actualComputerName -ine $ExpectedComputerName) { throw "Unexpected computer: $actualComputerName" }

    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    if ($identity.Name -match '^(?i:NT AUTHORITY\\(?:SYSTEM|LOCAL SERVICE|NETWORK SERVICE))$') {
        throw 'Service identities cannot install the owner desktop application.'
    }
    if (-not [Environment]::UserInteractive) { throw 'An interactive owner session is required.' }
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    $elevated = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    $script:Evidence.target.elevated = [bool]$elevated
    if ($elevated) { throw 'Elevated installation is forbidden; use the normal owner session.' }
    $sessionId = (Get-Process -Id $PID).SessionId
    $explorer = @(Get-Process -Name explorer -ErrorAction SilentlyContinue | Where-Object { $_.SessionId -eq $sessionId })
    if ($explorer.Count -lt 1) { throw 'Explorer is not running in the runner session; refusing a non-visible GUI install.' }
    $script:Evidence.target.owner_user_context = $true
    $script:Evidence.target.interactive_desktop = $true

    if (-not $env:RUNNER_TEMP) { throw 'RUNNER_TEMP is required for bounded artifact transport.' }
    $packageRootFull = Get-FullPath $PackageRoot
    if (-not (Test-PathWithin $packageRootFull $env:RUNNER_TEMP)) { throw 'Package transport escaped RUNNER_TEMP.' }
    if ((Split-Path -Leaf $packageRootFull) -notmatch '^nexus-personal-pro-package-[0-9]+$') {
        throw 'Unexpected package transport leaf.'
    }
    if ($UsePreloadedPackage) {
        if (-not (Test-Path -LiteralPath $packageRootFull -PathType Container)) { throw 'Preloaded package root is missing.' }
        $script:Evidence.package.download_transport = 'actions_download_artifact'
        $script:Evidence.package.workflow_token_used = $true
        $script:Evidence.package.downloaded = $true
    } else {
        if (Test-Path -LiteralPath $packageRootFull) { throw 'Stale package transport already exists.' }
        $gh = Get-Command gh.exe -ErrorAction SilentlyContinue
        if (-not $gh) { $gh = Get-Command gh -ErrorAction SilentlyContinue }
        if (-not $gh) { throw 'Existing owner GitHub CLI is unavailable.' }
        $previousGhToken = [Environment]::GetEnvironmentVariable('GH_TOKEN', 'Process')
        $previousGitHubToken = [Environment]::GetEnvironmentVariable('GITHUB_TOKEN', 'Process')
        [Environment]::SetEnvironmentVariable('GH_TOKEN', $null, 'Process')
        [Environment]::SetEnvironmentVariable('GITHUB_TOKEN', $null, 'Process')
        try {
            & $gh.Source run download "$ArtifactRunId" --repo 'saladinayoubi1/lbank-research-automation' --name $ArtifactName --dir $packageRootFull
            if ($LASTEXITCODE -ne 0) { throw 'Existing owner GitHub CLI could not download the exact approved artifact.' }
        } finally {
            [Environment]::SetEnvironmentVariable('GH_TOKEN', $previousGhToken, 'Process')
            [Environment]::SetEnvironmentVariable('GITHUB_TOKEN', $previousGitHubToken, 'Process')
        }
        if (-not (Test-Path -LiteralPath $packageRootFull -PathType Container)) { throw 'Package root is missing after download.' }
        $script:Evidence.package.downloaded = $true
    }
    Assert-NotReparsePoint $packageRootFull 'Package root'
    $unpackedName = 'NEXUS_Personal_Pro_Unpacked_5.1.0_x64.zip'
    $unpackedPath = Join-Path $packageRootFull $unpackedName
    $sumsPath = Join-Path $packageRootFull 'SHA256SUMS.txt'
    foreach ($requiredPath in @($unpackedPath, $sumsPath)) {
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) { throw "Required package file is missing: $(Split-Path -Leaf $requiredPath)" }
        Assert-NotReparsePoint $requiredPath 'Package file'
    }
    if ((Get-Item -LiteralPath $unpackedPath).Length -lt 100MB) { throw 'Persistent NEXUS package is unexpectedly small.' }
    $unpackedSha = (Get-FileHash -LiteralPath $unpackedPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $script:Evidence.package.unpacked_sha256 = $unpackedSha
    if ($unpackedSha -ne $ExpectedUnpackedSha256) { throw 'Persistent unpacked ZIP SHA256 does not match the exact approved artifact.' }
    $sumText = Get-Content -LiteralPath $sumsPath -Raw
    $unpackedLine = "$ExpectedUnpackedSha256  $unpackedName"
    if ($sumText -notmatch [Regex]::Escape($unpackedLine)) { throw 'Package checksum manifest does not bind the exact persistent ZIP.' }
    $script:Evidence.package.checksum_manifest_verified = $true

    if (-not $env:LOCALAPPDATA -or -not $env:APPDATA) { throw 'Owner profile application paths are unavailable.' }

    $repoRoot = Get-FullPath (Join-Path $PSScriptRoot '..')
    $paperSyncSource = Join-Path $PSScriptRoot 'nexus_prospective_paper_sync.ps1'
    $paperSyncValidator = Join-Path $repoRoot 'product_prospective_paper.py'
    $paperSyncRoot = Get-FullPath (Join-Path $env:LOCALAPPDATA 'NEXUS\paper-forward-sync')
    if (-not (Test-Path -LiteralPath $paperSyncSource -PathType Leaf)) { throw 'Canonical prospective Paper sync script is missing.' }
    if (-not (Test-Path -LiteralPath $paperSyncValidator -PathType Leaf)) { throw 'Prospective Paper validator is missing.' }
    New-Item -ItemType Directory -Path $paperSyncRoot -Force | Out-Null
    Assert-NotReparsePoint $paperSyncRoot 'Prospective Paper sync root'
    Copy-Item -LiteralPath $paperSyncSource -Destination (Join-Path $paperSyncRoot 'sync.ps1') -Force
    Copy-Item -LiteralPath $paperSyncValidator -Destination (Join-Path $paperSyncRoot 'product_prospective_paper.py') -Force
    Write-Host 'NEXUS_PAPER_SYNC_SOURCE_DEPLOYED=1'

    $programRoot = Get-FullPath (Join-Path $env:LOCALAPPDATA 'Programs\NEXUS Personal Pro')
    $installRoot = Get-FullPath (Join-Path $programRoot "5.1.0-$($ExpectedSourceSha.Substring(0, 8))")
    $script:ProgramRoot = $programRoot
    $script:InstallRoot = $installRoot
    if (-not (Test-PathWithin $installRoot $programRoot)) { throw 'Versioned installation escaped the NEXUS program root.' }
    New-Item -ItemType Directory -Path $programRoot -Force | Out-Null
    Assert-NotReparsePoint $programRoot 'NEXUS program root'
    $manifestPath = Join-Path $installRoot 'install-manifest.json'
    if (-not (Test-Path -LiteralPath $installRoot -PathType Container)) {
        $stagingRoot = Get-FullPath (Join-Path $programRoot ".incoming-$($ExpectedSourceSha.Substring(0, 8))-$($env:GITHUB_RUN_ID)")
        if (-not (Test-PathWithin $stagingRoot $programRoot)) { throw 'Install staging escaped the NEXUS program root.' }
        if (Test-Path -LiteralPath $stagingRoot) { throw 'Stale exact install staging root exists.' }
        $script:InstallStagingRoot = $stagingRoot
        New-Item -ItemType Directory -Path $stagingRoot | Out-Null
        Assert-NotReparsePoint $stagingRoot 'Install staging root'
        Expand-Archive -LiteralPath $unpackedPath -DestinationPath $stagingRoot -Force
        $reparse = @(Get-ChildItem -LiteralPath $stagingRoot -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint } | Select-Object -First 1)
        if ($reparse.Count -gt 0) { throw 'Persistent package contains a reparse point.' }
        $stagedExecutable = Join-Path $stagingRoot 'NEXUS Personal Pro.exe'
        $stagedSourceSha = Join-Path $stagingRoot 'resources\source-sha.txt'
        $stagedBuildEvidence = Join-Path $stagingRoot 'resources\build-evidence.json'
        $stagedSidecar = Join-Path $stagingRoot 'resources\nexus-product-server\nexus-product-server.exe'
        foreach ($requiredPath in @($stagedExecutable, $stagedSourceSha, $stagedBuildEvidence, $stagedSidecar)) {
            if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) { throw "Extracted persistent package is incomplete: $(Split-Path -Leaf $requiredPath)" }
            Assert-NotReparsePoint $requiredPath 'Extracted package file'
        }
        if ((Get-Content -LiteralPath $stagedSourceSha -Raw).Trim().ToLowerInvariant() -ne $ExpectedSourceSha) { throw 'Extracted package source SHA mismatch.' }
        $stagedEvidence = Get-Content -LiteralPath $stagedBuildEvidence -Raw | ConvertFrom-Json
        if (([string]$stagedEvidence.source_sha).ToLowerInvariant() -ne $ExpectedSourceSha -or
            $stagedEvidence.paper_only -ne $true -or $stagedEvidence.live_trading_authority -ne $false -or
            [string]$stagedEvidence.builder -ne 'github-actions/nexus-build-verification/windows-desktop') {
            throw 'Extracted package build evidence failed exact-source or authority validation.'
        }
        Move-Item -LiteralPath $stagingRoot -Destination $installRoot
        $script:InstallCreatedThisRun = $true
        $script:InstallStagingRoot = $null
    } else {
        Assert-NotReparsePoint $installRoot 'Versioned install root'
        if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw 'Existing exact-version install is missing its manifest.' }
        $existingManifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        if (([string]$existingManifest.source_sha).ToLowerInvariant() -ne $ExpectedSourceSha -or
            ([string]$existingManifest.unpacked_sha256).ToLowerInvariant() -ne $ExpectedUnpackedSha256) {
            throw 'Existing exact-version install is not bound to the approved persistent package.'
        }
    }

    $installedExecutable = Join-Path $installRoot 'NEXUS Personal Pro.exe'
    $installedSourceSha = Join-Path $installRoot 'resources\source-sha.txt'
    $installedBuildEvidence = Join-Path $installRoot 'resources\build-evidence.json'
    $installedSidecar = Join-Path $installRoot 'resources\nexus-product-server\nexus-product-server.exe'
    foreach ($requiredPath in @($installedExecutable, $installedSourceSha, $installedBuildEvidence, $installedSidecar)) {
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) { throw "Installed persistent package is incomplete: $(Split-Path -Leaf $requiredPath)" }
        Assert-NotReparsePoint $requiredPath 'Installed package file'
    }
    if ((Get-Content -LiteralPath $installedSourceSha -Raw).Trim().ToLowerInvariant() -ne $ExpectedSourceSha) { throw 'Installed package source SHA mismatch.' }
    $installedEvidence = Get-Content -LiteralPath $installedBuildEvidence -Raw | ConvertFrom-Json
    if (([string]$installedEvidence.source_sha).ToLowerInvariant() -ne $ExpectedSourceSha -or
        $installedEvidence.paper_only -ne $true -or $installedEvidence.live_trading_authority -ne $false -or
        [string]$installedEvidence.builder -ne 'github-actions/nexus-build-verification/windows-desktop') {
        throw 'Installed package build evidence failed exact-source or authority validation.'
    }
    $script:Evidence.install.executable_deployed = $true

    $installManifest = [ordered]@{
        schema_version = 'nexus.windows-side-by-side-install.v2'
        version = '5.1.0'
        install_mode = 'persistent_unpacked'
        source_sha = $ExpectedSourceSha
        unpacked_sha256 = $ExpectedUnpackedSha256
        artifact_name = $ArtifactName
        artifact_run_id = $ArtifactRunId
        artifact_id = $ArtifactId
        executable = 'NEXUS Personal Pro.exe'
        installed_at = [DateTime]::UtcNow.ToString('o')
        paper_only = $true
        live_trading_authority = $false
        previous_install_removed = $false
    }
    [IO.File]::WriteAllText($manifestPath, ($installManifest | ConvertTo-Json -Depth 4), (New-Object Text.UTF8Encoding($false)))
    $script:Evidence.install.manifest_written = $true

    foreach ($process in @(Get-NexusProcesses)) { $script:BaselineNexusProcessIds[[int]$process.Id] = $true }
    $preexistingGuiCount = @(Get-NexusProcesses | Where-Object { $_.MainWindowHandle -ne 0 }).Count
    $script:SmokeRoot = Join-Path $env:RUNNER_TEMP "nexus-app-smoke-$($env:GITHUB_RUN_ID)"
    if (Test-Path -LiteralPath $script:SmokeRoot) { throw 'Exact smoke root already exists; refusing to reuse stale test state.' }
    New-Item -ItemType Directory -Path $script:SmokeRoot | Out-Null
    $smokeStarted = [DateTime]::UtcNow
    $smokeArguments = @("--user-data-dir=`"$($script:SmokeRoot)`"", "--nexus-install-smoke=$($env:GITHUB_RUN_ID)")
    [void](Start-Process -FilePath $installedExecutable -ArgumentList $smokeArguments -PassThru)
    $script:Evidence.smoke.process_started = $true
    $state = Wait-ForHealthySupervisor -Root $script:SmokeRoot -NotBeforeUtc $smokeStarted -TimeoutSeconds 420
    $script:Evidence.smoke.supervisor_healthy = $true
    if (-not (Wait-ForVisibleNewWindow -TimeoutSeconds 90)) { throw 'NEXUS started but no visible Mission Control window was observed.' }
    $script:Evidence.smoke.visible_window_observed = $true
    Invoke-ProductContract -Origin ([string]$state.origin)
    $script:InstallSmokeVerified = $true
    Write-Evidence

    Stop-SmokeProcesses
    Remove-SmokeRoot

    $desktopShortcut = Join-Path ([Environment]::GetFolderPath('Desktop')) 'NEXUS Personal Pro 5.1.0.lnk'
    $startMenuShortcut = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\NEXUS Personal Pro 5.1.0.lnk'
    $genericStartMenuShortcut = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\NEXUS Personal Pro.lnk'
    $startupShortcut = Join-Path ([Environment]::GetFolderPath('Startup')) 'NEXUS Personal Pro.lnk'
    New-NexusShortcut $desktopShortcut $installedExecutable
    $script:Evidence.install.desktop_shortcut_created = $true
    New-NexusShortcut $startMenuShortcut $installedExecutable
    New-NexusShortcut $genericStartMenuShortcut $installedExecutable
    $script:Evidence.install.start_menu_shortcut_created = $true
    New-NexusShortcut $startupShortcut $installedExecutable
    $script:Evidence.install.startup_shortcut_created = $true
    Write-Host "NEXUS_APP_AUTOSTART_SHORTCUT=$startupShortcut"

    if ($preexistingGuiCount -gt 0) {
        $script:Evidence.final_launch.status = 'SKIPPED_EXISTING_APP_PRESERVED'
        $script:Evidence.final_launch.preexisting_app_preserved = $true
    } else {
        $tracking = [Environment]::GetEnvironmentVariable('RUNNER_TRACKING_ID', 'Process')
        [Environment]::SetEnvironmentVariable('RUNNER_TRACKING_ID', $null, 'Process')
        try { [void](Start-Process -FilePath $installedExecutable -ArgumentList @("--nexus-installed-source=$($ExpectedSourceSha.Substring(0, 8))")) }
        finally { [Environment]::SetEnvironmentVariable('RUNNER_TRACKING_ID', $tracking, 'Process') }
        if (-not (Wait-ForVisibleNewWindow -TimeoutSeconds 300)) { throw 'Installed NEXUS final window did not become visible.' }
        $script:Evidence.final_launch.status = 'RUNNING_VISIBLE'
        $script:Evidence.final_launch.visible_window_observed = $true
    }

    $script:Evidence.decision = 'PASS'
    Write-Evidence
    Write-Host "NEXUS_WINDOWS_APP_INSTALL=PASS source=$ExpectedSourceSha artifact=$ArtifactId"
} catch {
    try { Stop-SmokeProcesses } catch { }
    try { Remove-SmokeRoot } catch { }
    try {
        if ($script:InstallStagingRoot -and $script:ProgramRoot -and
            (Test-Path -LiteralPath $script:InstallStagingRoot) -and
            (Test-PathWithin $script:InstallStagingRoot $script:ProgramRoot)) {
            Remove-Item -LiteralPath $script:InstallStagingRoot -Recurse -Force
        }
    } catch { }
    try {
        if ($script:InstallCreatedThisRun -and -not $script:InstallSmokeVerified -and
            $script:InstallRoot -and $script:ProgramRoot -and
            (Test-Path -LiteralPath $script:InstallRoot) -and
            (Test-PathWithin $script:InstallRoot $script:ProgramRoot)) {
            Remove-Item -LiteralPath $script:InstallRoot -Recurse -Force
        }
    } catch { }
    $script:Evidence.decision = 'FAIL_CLOSED'
    $script:Evidence.error = ConvertTo-SafeError $_.Exception.Message
    try { Write-Evidence } catch { }
    Write-Error ("NEXUS Windows app installation failed closed: " + (ConvertTo-SafeError $_.Exception.Message))
    exit 1
} finally {
    try { Remove-PackageTransport } catch { Write-Warning (ConvertTo-SafeError $_.Exception.Message) }
}
