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
    [switch]$UsePreloadedPackage,
    [switch]$ActivateInstalledBuild
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
        retention_max_versions = 3
        retention_status = 'NOT_RUN'
        versions_removed = @()
        versions_skipped_running = @()
        versions_skipped_unverified = @()
        retention_error = $null
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
        activation_requested = [bool]$ActivateInstalledBuild
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
    # Never sweep unrelated owner processes that happened to restart during smoke.
    if (-not $script:InstallRoot) { return @() }
    return @(Get-InstalledNexusProductProcesses -ProgramRoot $script:InstallRoot |
        Where-Object { -not $script:BaselineNexusProcessIds.ContainsKey([int]$_.Id) })
}


function Get-InstalledNexusProductProcesses([string]$ProgramRoot) {
    $root = (Get-FullPath $ProgramRoot).TrimEnd('\')
    $matches = @()
    foreach ($process in @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ProcessName -in @('NEXUS Personal Pro', 'nexus-product-server')
    })) {
        try {
            $processPath = [string]$process.Path
            if ($processPath -and (Test-PathWithin $processPath $root)) { $matches += $process }
        } catch { }
    }
    return @($matches)
}

function Stop-InstalledNexusProductProcesses([string]$ProgramRoot) {
    $targets = @(Get-InstalledNexusProductProcesses -ProgramRoot $ProgramRoot)
    foreach ($process in $targets) {
        try {
            if ($process.MainWindowHandle -ne 0) { [void]$process.CloseMainWindow() }
        } catch { }
    }

    $deadline = [DateTime]::UtcNow.AddSeconds(12)
    do {
        Start-Sleep -Milliseconds 400
        $remaining = @(Get-InstalledNexusProductProcesses -ProgramRoot $ProgramRoot)
    } while ($remaining.Count -gt 0 -and [DateTime]::UtcNow -lt $deadline)

    foreach ($process in $remaining) {
        try { Stop-Process -Id $process.Id -Force -ErrorAction Stop } catch { }
    }

    $deadline = [DateTime]::UtcNow.AddSeconds(6)
    do {
        Start-Sleep -Milliseconds 300
        $remaining = @(Get-InstalledNexusProductProcesses -ProgramRoot $ProgramRoot)
    } while ($remaining.Count -gt 0 -and [DateTime]::UtcNow -lt $deadline)

    if ($remaining.Count -gt 0) {
        throw 'Existing NEXUS product processes did not stop inside the bounded activation window.'
    }
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

    # The legacy activation branch changes owner sync and shortcuts before
    # the old app has quiesced and has no transactional rollback. Never enter
    # it until a separate, independently tested activation gate replaces it.
    if ($ActivateInstalledBuild) {
        throw 'UNSAFE_LEGACY_OWNER_ACTIVATION_DISABLED: use verified stage-only installation pending transactional activation.'
    }

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
    # The gateway is source-verified above; do not mistake delayed renderer
    # first paint on the physical owner laptop for a failed application.
    # Still require an actual visible exact-install window, fail closed at 300s.
    if (-not (Wait-ForVisibleNewWindow -TimeoutSeconds 300)) { throw 'NEXUS started but no visible Mission Control window was observed.' }
    $script:Evidence.smoke.visible_window_observed = $true
    Invoke-ProductContract -Origin ([string]$state.origin)
    $script:InstallSmokeVerified = $true
    Write-Evidence

    Stop-SmokeProcesses
    Remove-SmokeRoot

    # Staging is never permission to replace owner shortcuts or stop the healthy app.
    # Only an explicit separate activation run may perform owner-visible changes.
    if (-not $ActivateInstalledBuild) {
        $script:Evidence.final_launch.status = 'STAGED_ONLY_OWNER_PRESERVED'
        $script:Evidence.final_launch.preexisting_app_preserved = $true
        $script:Evidence.install.retention_status = 'SKIPPED_UNTIL_EXPLICIT_ACTIVATION'
        $script:Evidence.decision = 'PASS'
        Write-Evidence
        Write-Host "NEXUS_WINDOWS_APP_INSTALL=PASS source=$ExpectedSourceSha artifact=$ArtifactId staged_only=true"
        return
    }

    # Stage-only verification cannot mutate global owner Paper sync scripts.
    # Explicit activation remains separately guarded and requires owner rollback proof.
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

    if ($preexistingGuiCount -gt 0 -and -not $ActivateInstalledBuild) {
        $script:Evidence.final_launch.status = 'SKIPPED_EXISTING_APP_PRESERVED'
        $script:Evidence.final_launch.preexisting_app_preserved = $true
    } else {
        if ($ActivateInstalledBuild) {
            Stop-InstalledNexusProductProcesses -ProgramRoot $programRoot
        }
        $tracking = [Environment]::GetEnvironmentVariable('RUNNER_TRACKING_ID', 'Process')
        [Environment]::SetEnvironmentVariable('RUNNER_TRACKING_ID', $null, 'Process')
        try { [void](Start-Process -FilePath $installedExecutable -ArgumentList @("--nexus-installed-source=$($ExpectedSourceSha.Substring(0, 8))")) }
        finally { [Environment]::SetEnvironmentVariable('RUNNER_TRACKING_ID', $tracking, 'Process') }
        if (-not (Wait-ForVisibleNewWindow -TimeoutSeconds 300)) { throw 'Installed NEXUS final window did not become visible.' }
        if ($ActivateInstalledBuild) {
            $script:Evidence.final_launch.status = 'RUNNING_VISIBLE_ACTIVATED'
        } else {
            $script:Evidence.final_launch.status = 'RUNNING_VISIBLE'
        }
        $script:Evidence.final_launch.visible_window_observed = $true
        $script:Evidence.final_launch.preexisting_app_preserved = $false
    }

    try {
        $retentionScript = Join-Path $PSScriptRoot 'cleanup_nexus_desktop_versions.ps1'
        if (-not (Test-Path -LiteralPath $retentionScript -PathType Leaf)) { throw 'NEXUS version retention helper is missing.' }
        Assert-NotReparsePoint $retentionScript 'Version retention helper'
        $retentionOutput = @(& $retentionScript -ProgramRoot $programRoot -CurrentInstallRoot $installRoot -MaxVersions 3)
        $retentionJson = @($retentionOutput | Where-Object { $_ -is [string] -and $_.TrimStart().StartsWith('{') } | Select-Object -Last 1)
        if ($retentionJson.Count -ne 1) { throw 'NEXUS version retention did not return one JSON result.' }
        $retention = $retentionJson[0] | ConvertFrom-Json
        if ([string]$retention.schema_version -ne 'nexus.windows-version-retention.v1') { throw 'NEXUS version retention result schema mismatch.' }
        $script:Evidence.install.retention_status = 'PASS'
        $script:Evidence.install.versions_removed = @($retention.removed)
        $script:Evidence.install.versions_skipped_running = @($retention.skipped_running)
        $script:Evidence.install.versions_skipped_unverified = @($retention.skipped_unverified)
    } catch {
        $script:Evidence.install.retention_status = 'WARNING'
        $script:Evidence.install.retention_error = ConvertTo-SafeError $_.Exception.Message
        Write-Warning "NEXUS version retention skipped: $($script:Evidence.install.retention_error)"
    }

    $script:Evidence.decision = 'PASS'
    Write-Evidence
    Write-Host "NEXUS_WINDOWS_APP_INSTALL=PASS source=$ExpectedSourceSha artifact=$ArtifactId"
} catch {
    # Before normal fail-closed removal, record ONLY a categorical receipt
    # from THIS RUN's isolated smoke profile. Never publish the raw state,
    # startup log, exception reason or original owner profile.
    $diag = [ordered]@{
        isolated_state_seen = $false
        supervisor_status = 'unavailable'
        source_matches = $false
        failure_class = 'unknown'
    }
    try {
        if ($script:SmokeRoot -and $env:RUNNER_TEMP -and
            (Test-PathWithin $script:SmokeRoot $env:RUNNER_TEMP) -and
            (Split-Path -Leaf $script:SmokeRoot) -match '^nexus-app-smoke-[0-9]+
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
) {
            $dataDir = Join-Path $script:SmokeRoot 'product-data'
            $stateFile = Join-Path $dataDir 'supervisor-state.json'
            if ((Test-Path -LiteralPath $dataDir -PathType Container) -and
                (Test-Path -LiteralPath $stateFile -PathType Leaf)) {
                $rootInfo = Get-Item -LiteralPath $script:SmokeRoot -Force
                $dirInfo = Get-Item -LiteralPath $dataDir -Force
                $stateInfo = Get-Item -LiteralPath $stateFile -Force
                if ((-not ($rootInfo.Attributes -band [IO.FileAttributes]::ReparsePoint)) -and
                    (-not ($dirInfo.Attributes -band [IO.FileAttributes]::ReparsePoint)) -and
                    (-not ($stateInfo.Attributes -band [IO.FileAttributes]::ReparsePoint)) -and
                    $stateInfo.Length -le 65536) {
                    $state = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
                    $diag.isolated_state_seen = $true
                    if ($null -ne $state.PSObject.Properties['status'] -and
                        [string]$state.status -in @('starting', 'healthy', 'blocked', 'restarting',
                            'restart_failed', 'startup_failed', 'stopping')) {
                        $diag.supervisor_status = [string]$state.status
                    }
                    if ($null -ne $state.PSObject.Properties['source_sha']) {
                        $diag.source_matches = ([string]$state.source_sha).ToLowerInvariant() -eq $ExpectedSourceSha
                    }
                    $reason = ''
                    if ($null -ne $state.PSObject.Properties['reason']) { $reason = [string]$state.reason }
                    if ($reason.Length -gt 4096) { $reason = $reason.Substring(0, 4096) }
                    if ($reason -match 'ModuleNotFoundError|No module named|ImportError') {
                        $diag.failure_class = 'module_import'
                    } elseif ($reason -match 'FileNotFoundError|file not found|system cannot find') {
                        $diag.failure_class = 'missing_file'
                    } elseif ($reason -match 'permission denied|access is denied') {
                        $diag.failure_class = 'permission'
                    } elseif ($reason -match 'address already in use|EADDRINUSE') {
                        $diag.failure_class = 'port_collision'
                    } elseif ($reason -match 'timeout|did not become ready') {
                        $diag.failure_class = 'gateway_timeout'
                    } elseif ($reason -match 'bounded_restart_limit') {
                        $diag.failure_class = 'restart_limit'
                    } elseif ($reason -match 'unexpected_sidecar_exit|engine exited before startup|spawn error') {
                        $diag.failure_class = 'sidecar_exit'
                    }
                } else { $diag.failure_class = 'untrusted_state_file' }
            }
        }
    } catch { $diag.failure_class = 'diagnostic_unavailable' }
    $script:Evidence['smoke_failure_diagnostic'] = $diag
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
