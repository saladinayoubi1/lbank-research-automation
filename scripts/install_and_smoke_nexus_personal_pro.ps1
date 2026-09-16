[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string]$PackageRoot,
    [Parameter(Mandatory = $true)] [ValidatePattern('^[0-9a-fA-F]{40}$')] [string]$ExpectedSourceSha,
    [Parameter(Mandatory = $true)] [ValidatePattern('^[0-9a-fA-F]{64}$')] [string]$ExpectedSetupSha256,
    [Parameter(Mandatory = $true)] [ValidatePattern('^[0-9a-fA-F]{64}$')] [string]$ExpectedPortableSha256,
    [Parameter(Mandatory = $true)] [long]$ArtifactRunId,
    [Parameter(Mandatory = $true)] [long]$ArtifactId,
    [string]$ExpectedComputerName = 'DESKTOP-1R1081M',
    [string]$ExpectedRunnerName = 'NEXUS-LOCAL-RUNNER',
    [string]$EvidencePath = 'build\windows-app-install\evidence.json'
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$ExpectedSourceSha = $ExpectedSourceSha.ToLowerInvariant()
$ExpectedSetupSha256 = $ExpectedSetupSha256.ToLowerInvariant()
$ExpectedPortableSha256 = $ExpectedPortableSha256.ToLowerInvariant()
$script:BaselineNexusProcessIds = @{}
$script:SmokeRoot = $null
$script:SmokeCleaned = $false
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
        setup_sha256 = $null
        portable_sha256 = $null
        checksum_manifest_verified = $false
    }
    install = [ordered]@{
        mode = 'versioned_side_by_side_portable'
        previous_install_removed = $false
        previous_app_data_removed = $false
        registry_installation_changed = $false
        executable_deployed = $false
        manifest_written = $false
        desktop_shortcut_created = $false
        start_menu_shortcut_created = $false
        version = '5.1.0'
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
    if ($env:COMPUTERNAME -ine $ExpectedComputerName) { throw "Unexpected computer: $($env:COMPUTERNAME)" }

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

    $packageRootFull = Get-FullPath $PackageRoot
    if (-not (Test-Path -LiteralPath $packageRootFull -PathType Container)) { throw 'Package root is missing.' }
    Assert-NotReparsePoint $packageRootFull 'Package root'
    $setupName = 'NEXUS_Personal_Pro_Setup_5.1.0_x64.exe'
    $portableName = 'NEXUS_Personal_Pro_Portable_5.1.0_x64.exe'
    $setupPath = Join-Path $packageRootFull $setupName
    $portablePath = Join-Path $packageRootFull $portableName
    $sumsPath = Join-Path $packageRootFull 'SHA256SUMS.txt'
    foreach ($requiredPath in @($setupPath, $portablePath, $sumsPath)) {
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) { throw "Required package file is missing: $(Split-Path -Leaf $requiredPath)" }
        Assert-NotReparsePoint $requiredPath 'Package file'
    }
    if ((Get-Item -LiteralPath $setupPath).Length -lt 100MB -or (Get-Item -LiteralPath $portablePath).Length -lt 100MB) {
        throw 'NEXUS executable package is unexpectedly small.'
    }

    $setupSha = (Get-FileHash -LiteralPath $setupPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $portableSha = (Get-FileHash -LiteralPath $portablePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $script:Evidence.package.setup_sha256 = $setupSha
    $script:Evidence.package.portable_sha256 = $portableSha
    if ($setupSha -ne $ExpectedSetupSha256) { throw 'Setup SHA256 does not match the exact approved artifact.' }
    if ($portableSha -ne $ExpectedPortableSha256) { throw 'Portable SHA256 does not match the exact approved artifact.' }
    $sumText = Get-Content -LiteralPath $sumsPath -Raw
    $setupLine = "$ExpectedSetupSha256  $setupName"
    $portableLine = "$ExpectedPortableSha256  $portableName"
    if ($sumText -notmatch [Regex]::Escape($setupLine) -or $sumText -notmatch [Regex]::Escape($portableLine)) {
        throw 'Package checksum manifest does not bind both exact executables.'
    }
    $script:Evidence.package.checksum_manifest_verified = $true

    if (-not $env:LOCALAPPDATA -or -not $env:APPDATA) { throw 'Owner profile application paths are unavailable.' }
    $programRoot = Get-FullPath (Join-Path $env:LOCALAPPDATA 'Programs\NEXUS Personal Pro')
    $installRoot = Get-FullPath (Join-Path $programRoot "5.1.0-$($ExpectedSourceSha.Substring(0, 8))")
    if (-not (Test-PathWithin $installRoot $programRoot)) { throw 'Versioned installation escaped the NEXUS program root.' }
    New-Item -ItemType Directory -Path $programRoot -Force | Out-Null
    Assert-NotReparsePoint $programRoot 'NEXUS program root'
    New-Item -ItemType Directory -Path $installRoot -Force | Out-Null
    Assert-NotReparsePoint $installRoot 'Versioned install root'

    $installedExecutable = Join-Path $installRoot $portableName
    if (Test-Path -LiteralPath $installedExecutable -PathType Leaf) {
        Assert-NotReparsePoint $installedExecutable 'Installed executable'
        $existingHash = (Get-FileHash -LiteralPath $installedExecutable -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($existingHash -ne $ExpectedPortableSha256) { throw 'A different file already occupies the exact versioned install target.' }
    } else {
        $temporaryExecutable = Join-Path $installRoot ($portableName + '.incoming')
        Copy-Item -LiteralPath $portablePath -Destination $temporaryExecutable
        if ((Get-FileHash -LiteralPath $temporaryExecutable -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedPortableSha256) {
            Remove-Item -LiteralPath $temporaryExecutable -Force -ErrorAction SilentlyContinue
            throw 'Deployed executable failed post-copy SHA256 verification.'
        }
        Move-Item -LiteralPath $temporaryExecutable -Destination $installedExecutable
    }
    $script:Evidence.install.executable_deployed = $true

    $installManifest = [ordered]@{
        schema_version = 'nexus.windows-side-by-side-install.v1'
        version = '5.1.0'
        source_sha = $ExpectedSourceSha
        portable_sha256 = $ExpectedPortableSha256
        artifact_run_id = $ArtifactRunId
        artifact_id = $ArtifactId
        installed_at = [DateTime]::UtcNow.ToString('o')
        paper_only = $true
        live_trading_authority = $false
        previous_install_removed = $false
    }
    $manifestPath = Join-Path $installRoot 'install-manifest.json'
    [IO.File]::WriteAllText($manifestPath, ($installManifest | ConvertTo-Json -Depth 4), (New-Object Text.UTF8Encoding($false)))
    $script:Evidence.install.manifest_written = $true

    $desktopShortcut = Join-Path ([Environment]::GetFolderPath('Desktop')) 'NEXUS Personal Pro 5.1.0.lnk'
    $startMenuShortcut = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\NEXUS Personal Pro 5.1.0.lnk'
    New-NexusShortcut $desktopShortcut $installedExecutable
    $script:Evidence.install.desktop_shortcut_created = $true
    New-NexusShortcut $startMenuShortcut $installedExecutable
    $script:Evidence.install.start_menu_shortcut_created = $true

    foreach ($process in @(Get-NexusProcesses)) { $script:BaselineNexusProcessIds[[int]$process.Id] = $true }
    $preexistingGuiCount = @(Get-NexusProcesses | Where-Object { $_.MainWindowHandle -ne 0 }).Count
    $script:SmokeRoot = Join-Path $env:RUNNER_TEMP "nexus-app-smoke-$($env:GITHUB_RUN_ID)"
    if (Test-Path -LiteralPath $script:SmokeRoot) { throw 'Exact smoke root already exists; refusing to reuse stale test state.' }
    New-Item -ItemType Directory -Path $script:SmokeRoot | Out-Null
    $smokeStarted = [DateTime]::UtcNow
    $smokeArguments = @("--user-data-dir=`"$($script:SmokeRoot)`"", "--nexus-install-smoke=$($env:GITHUB_RUN_ID)")
    [void](Start-Process -FilePath $installedExecutable -ArgumentList $smokeArguments -PassThru)
    $script:Evidence.smoke.process_started = $true
    $state = Wait-ForHealthySupervisor -Root $script:SmokeRoot -NotBeforeUtc $smokeStarted -TimeoutSeconds 150
    $script:Evidence.smoke.supervisor_healthy = $true
    if (-not (Wait-ForVisibleNewWindow -TimeoutSeconds 90)) { throw 'NEXUS started but no visible Mission Control window was observed.' }
    $script:Evidence.smoke.visible_window_observed = $true
    Invoke-ProductContract -Origin ([string]$state.origin)
    Write-Evidence

    Stop-SmokeProcesses
    Remove-SmokeRoot

    if ($preexistingGuiCount -gt 0) {
        $script:Evidence.final_launch.status = 'SKIPPED_EXISTING_APP_PRESERVED'
        $script:Evidence.final_launch.preexisting_app_preserved = $true
    } else {
        $tracking = [Environment]::GetEnvironmentVariable('RUNNER_TRACKING_ID', 'Process')
        [Environment]::SetEnvironmentVariable('RUNNER_TRACKING_ID', $null, 'Process')
        try { [void](Start-Process -FilePath $installedExecutable -ArgumentList @("--nexus-installed-source=$($ExpectedSourceSha.Substring(0, 8))")) }
        finally { [Environment]::SetEnvironmentVariable('RUNNER_TRACKING_ID', $tracking, 'Process') }
        if (-not (Wait-ForVisibleNewWindow -TimeoutSeconds 120)) { throw 'Installed NEXUS final window did not become visible.' }
        $script:Evidence.final_launch.status = 'RUNNING_VISIBLE'
        $script:Evidence.final_launch.visible_window_observed = $true
    }

    $script:Evidence.decision = 'PASS'
    Write-Evidence
    Write-Host "NEXUS_WINDOWS_APP_INSTALL=PASS source=$ExpectedSourceSha artifact=$ArtifactId"
} catch {
    try { Stop-SmokeProcesses } catch { }
    try { Remove-SmokeRoot } catch { }
    $script:Evidence.decision = 'FAIL_CLOSED'
    $script:Evidence.error = ConvertTo-SafeError $_.Exception.Message
    try { Write-Evidence } catch { }
    Write-Error ("NEXUS Windows app installation failed closed: " + (ConvertTo-SafeError $_.Exception.Message))
    exit 1
} finally {
    try { Remove-PackageTransport } catch { Write-Warning (ConvertTo-SafeError $_.Exception.Message) }
}
