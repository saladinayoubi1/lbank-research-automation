[CmdletBinding()]
param(
    [string]$RunnerName = 'NEXUS-LOCAL-RUNNER'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$Repository = 'saladinayoubi1/lbank-research-automation'
$RepositoryUrl = 'https://github.com/' + $Repository
$RunnerVersion = '2.336.0'
$RunnerArchiveName = "actions-runner-win-x64-$RunnerVersion.zip"
$RunnerArchiveSha256 = 'd59123a43003e357b0805b5d0f611d0bd2f65ab67d51bd070dd4e7a0f685c162'
$RunnerArchiveUrl = "https://github.com/actions/runner/releases/download/v$RunnerVersion/$RunnerArchiveName"
$NexusRoot = Join-Path $env:LOCALAPPDATA 'NEXUS'
$RunnerRoot = Join-Path $NexusRoot 'actions-runner'
$CacheRoot = Join-Path $NexusRoot 'runner-cache'
$StateRoot = Join-Path $NexusRoot 'RunnerRegistration'
$EvidencePath = Join-Path $StateRoot 'evidence.json'
$LogPath = Join-Path $StateRoot 'registration.log'
$ManagedMarker = Join-Path $RunnerRoot '.nexus-managed-runner.json'
$TaskName = 'NEXUS-GitHub-Runner-Autostart'

function Ensure-StateRoot {
    New-Item -ItemType Directory -Force -Path $StateRoot | Out-Null
}

function Write-Log([string]$Message) {
    Ensure-StateRoot
    $stamp = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
    Add-Content -LiteralPath $LogPath -Encoding UTF8 -Value "[$stamp] $Message"
}

function Write-Evidence([string]$Status, [hashtable]$Extra = @{}) {
    Ensure-StateRoot
    $payload = [ordered]@{
        contract_version = 'nexus.runner-interactive-registration.v1'
        status = $Status
        generated_at = [DateTime]::UtcNow.ToString('o')
        repository = $Repository
        runner_name = $RunnerName
        runner_root = $RunnerRoot
        runner_version = $RunnerVersion
        registration_token_persisted = $false
        registration_token_logged = $false
        registration_token_written_to_disk = $false
        machine_execution_policy_modified = $false
        elevation_requested = $false
        service_installed = $false
        task_scheduler_transport = 'COM'
        paper_only = $true
        live_trading_authority = $false
    }
    foreach ($key in $Extra.Keys) { $payload[$key] = $Extra[$key] }
    $tmp = $EvidencePath + '.tmp'
    $payload | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $tmp -Encoding UTF8
    Move-Item -LiteralPath $tmp -Destination $EvidencePath -Force
}

function Fail([string]$Status, [string]$Message) {
    try { Write-Evidence $Status @{ error = $Message } } catch { }
    try { Write-Log "status=$Status error=$Message" } catch { }
    throw $Message
}

function Assert-OwnerSession {
    if ($env:OS -ne 'Windows_NT') { Fail 'WINDOWS_REQUIRED' 'This registration helper is Windows-only.' }
    if (-not [Environment]::UserInteractive) { Fail 'INTERACTIVE_OWNER_REQUIRED' 'Run this helper from the signed-in Windows desktop.' }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    if ($identity -in @('NT AUTHORITY\SYSTEM','NT AUTHORITY\NETWORK SERVICE','NT AUTHORITY\LOCAL SERVICE')) {
        Fail 'SERVICE_IDENTITY_REJECTED' 'A signed-in owner account is required.'
    }
    if (-not [Environment]::Is64BitOperatingSystem) { Fail 'X64_WINDOWS_REQUIRED' '64-bit Windows is required.' }
    if (-not $env:LOCALAPPDATA) { Fail 'LOCALAPPDATA_REQUIRED' 'LOCALAPPDATA is unavailable.' }
}

function Normalize-GitHubUrl([string]$Value) {
    if (-not $Value) { return '' }
    return $Value.Trim().TrimEnd('/').ToLowerInvariant()
}

function Test-ConfiguredRunner {
    $settings = Join-Path $RunnerRoot '.runner'
    $credentials = Join-Path $RunnerRoot '.credentials'
    $runCmd = Join-Path $RunnerRoot 'run.cmd'
    $listener = Join-Path $RunnerRoot 'bin\Runner.Listener.exe'
    if (-not ((Test-Path -LiteralPath $settings -PathType Leaf) -and
              (Test-Path -LiteralPath $credentials -PathType Leaf) -and
              (Test-Path -LiteralPath $runCmd -PathType Leaf) -and
              (Test-Path -LiteralPath $listener -PathType Leaf))) { return $false }
    try {
        $config = Get-Content -LiteralPath $settings -Raw | ConvertFrom-Json
        $urlProperty = $config.PSObject.Properties['gitHubUrl']
        if (-not $urlProperty -or -not $urlProperty.Value) { return $false }
        return (Normalize-GitHubUrl ([string]$urlProperty.Value)) -eq (Normalize-GitHubUrl $RepositoryUrl)
    }
    catch { return $false }
}

function Assert-ManagedOrEmptyRunnerRoot {
    if (-not (Test-Path -LiteralPath $RunnerRoot -PathType Container)) { return }
    if (Test-ConfiguredRunner) { return }
    if (Test-Path -LiteralPath $ManagedMarker -PathType Leaf) { return }
    $entries = @(Get-ChildItem -LiteralPath $RunnerRoot -Force -ErrorAction Stop | Select-Object -First 1)
    if ($entries.Count -gt 0) {
        Fail 'UNMANAGED_RUNNER_ROOT_REJECTED' "Refusing to alter non-empty unmanaged runner directory: $RunnerRoot"
    }
}

function Get-VerifiedRunnerArchive {
    New-Item -ItemType Directory -Force -Path $CacheRoot | Out-Null
    $archive = Join-Path $CacheRoot $RunnerArchiveName
    $valid = $false
    if (Test-Path -LiteralPath $archive -PathType Leaf) {
        try {
            $hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
            $valid = ($hash -eq $RunnerArchiveSha256)
        }
        catch { $valid = $false }
    }
    if (-not $valid) {
        $tmp = $archive + '.tmp'
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Write-Host 'Downloading the pinned official GitHub Actions runner...'
        Invoke-WebRequest -UseBasicParsing -Uri $RunnerArchiveUrl -OutFile $tmp -TimeoutSec 180
        $hash = (Get-FileHash -LiteralPath $tmp -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($hash -ne $RunnerArchiveSha256) {
            Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
            Fail 'RUNNER_ARCHIVE_HASH_MISMATCH' 'Official GitHub Actions runner SHA-256 verification failed.'
        }
        Move-Item -LiteralPath $tmp -Destination $archive -Force
    }
    return $archive
}

function Install-RunnerFiles([string]$Archive) {
    if (Test-ConfiguredRunner) { return }
    Assert-ManagedOrEmptyRunnerRoot
    New-Item -ItemType Directory -Force -Path $RunnerRoot | Out-Null
    if (-not (Test-Path -LiteralPath $ManagedMarker -PathType Leaf)) {
        [ordered]@{
            contract_version = 'nexus.managed-runner-root.v1'
            created_at = [DateTime]::UtcNow.ToString('o')
            runner_version = $RunnerVersion
            archive_sha256 = $RunnerArchiveSha256
        } | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $ManagedMarker -Encoding UTF8
    }
    $config = Join-Path $RunnerRoot 'config.cmd'
    $listener = Join-Path $RunnerRoot 'bin\Runner.Listener.exe'
    if ((Test-Path -LiteralPath $config -PathType Leaf) -and (Test-Path -LiteralPath $listener -PathType Leaf)) { return }
    Expand-Archive -LiteralPath $Archive -DestinationPath $RunnerRoot -Force
    if (-not (Test-Path -LiteralPath $config -PathType Leaf)) { Fail 'RUNNER_EXTRACT_FAILED' 'config.cmd is missing after runner extraction.' }
    if (-not (Test-Path -LiteralPath $listener -PathType Leaf)) { Fail 'RUNNER_EXTRACT_FAILED' 'Runner.Listener.exe is missing after runner extraction.' }
}

function Find-GhExecutable {
    $cmd = Get-Command gh -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($candidate in @(
        (Join-Path $env:ProgramFiles 'GitHub CLI\gh.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\GitHub CLI\gh.exe')
    )) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) { return $candidate }
    }
    return $null
}

function Install-PortableGh {
    $toolRoot = Join-Path $NexusRoot 'tools\gh'
    New-Item -ItemType Directory -Force -Path $toolRoot | Out-Null
    Write-Host 'GitHub CLI is not installed. Downloading the official portable GitHub CLI...'
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $response = Invoke-WebRequest -UseBasicParsing -Uri 'https://api.github.com/repos/cli/cli/releases/latest' -TimeoutSec 60 -Headers @{ 'User-Agent'='NEXUS-Runner-Registration' }
    $release = $response.Content | ConvertFrom-Json
    $zipAsset = @($release.assets | Where-Object { $_.name -match '^gh_[0-9.]+_windows_amd64\.zip$' })
    $sumAsset = @($release.assets | Where-Object { $_.name -match '^gh_[0-9.]+_checksums\.txt$' })
    if ($zipAsset.Count -ne 1 -or $sumAsset.Count -ne 1) { Fail 'GH_RELEASE_ASSET_NOT_FOUND' 'Could not resolve official GitHub CLI Windows assets.' }
    $versionRoot = Join-Path $toolRoot ([string]$release.tag_name)
    $zipPath = Join-Path $toolRoot ([string]$zipAsset[0].name)
    $sumPath = Join-Path $toolRoot ([string]$sumAsset[0].name)
    Invoke-WebRequest -UseBasicParsing -Uri ([string]$zipAsset[0].browser_download_url) -OutFile $zipPath -TimeoutSec 180
    Invoke-WebRequest -UseBasicParsing -Uri ([string]$sumAsset[0].browser_download_url) -OutFile $sumPath -TimeoutSec 60
    $line = Get-Content -LiteralPath $sumPath | Where-Object { $_ -match ([regex]::Escape([string]$zipAsset[0].name) + '$') } | Select-Object -First 1
    if (-not $line) { Fail 'GH_CHECKSUM_NOT_FOUND' 'GitHub CLI checksum entry was not found.' }
    $expected = ($line -split '\s+')[0].Trim().ToLowerInvariant()
    $actual = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected) { Fail 'GH_ARCHIVE_HASH_MISMATCH' 'Official GitHub CLI SHA-256 verification failed.' }
    Remove-Item -LiteralPath $versionRoot -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $versionRoot | Out-Null
    Expand-Archive -LiteralPath $zipPath -DestinationPath $versionRoot -Force
    $matches = @(Get-ChildItem -LiteralPath $versionRoot -Filter gh.exe -File -Recurse -ErrorAction Stop)
    if ($matches.Count -ne 1) { Fail 'GH_EXTRACT_FAILED' 'Could not resolve exactly one gh.exe from the verified GitHub CLI archive.' }
    return $matches[0].FullName
}

function Ensure-GhAuth([string]$Gh) {
    & $Gh auth status --hostname github.com 1>$null 2>$null
    if ($LASTEXITCODE -eq 0) { return }
    Write-Host ''
    Write-Host 'GitHub authorization is required once. Your browser will open; approve the GitHub CLI request.' -ForegroundColor Yellow
    & $Gh auth login --hostname github.com --git-protocol https --web --scopes repo
    if ($LASTEXITCODE -ne 0) { Fail 'GITHUB_AUTH_FAILED' 'GitHub CLI authorization did not complete.' }
    & $Gh auth status --hostname github.com 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) { Fail 'GITHUB_AUTH_FAILED' 'GitHub CLI is still not authenticated.' }
}

function Get-RegistrationToken([string]$Gh) {
    $token = $null
    try {
        $token = (& $Gh api --method POST "repos/$Repository/actions/runners/registration-token" --jq '.token' 2>$null | Select-Object -First 1)
    }
    catch { $token = $null }
    if (-not $token) {
        Write-Host 'Refreshing GitHub authorization for repository administration...' -ForegroundColor Yellow
        & $Gh auth refresh --hostname github.com --scopes repo
        if ($LASTEXITCODE -ne 0) { Fail 'RUNNER_TOKEN_PERMISSION_DENIED' 'GitHub authorization does not permit runner registration.' }
        $token = (& $Gh api --method POST "repos/$Repository/actions/runners/registration-token" --jq '.token' 2>$null | Select-Object -First 1)
    }
    $value = [string]$token
    $value = $value.Trim()
    if ($value.Length -lt 10 -or $value -match '\s') { Fail 'RUNNER_TOKEN_PERMISSION_DENIED' 'GitHub did not return a valid short-lived runner registration token.' }
    return $value
}

function Register-Runner([string]$Token) {
    if (Test-ConfiguredRunner) { return }
    $config = Join-Path $RunnerRoot 'config.cmd'
    Push-Location $RunnerRoot
    try {
        & $config --unattended --url $RepositoryUrl --token $Token --name $RunnerName --work '_work' --labels 'nexus-local' --replace
        $exitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
        $Token = $null
    }
    if ($exitCode -ne 0) { Fail 'RUNNER_REGISTRATION_FAILED' "config.cmd failed with exit code $exitCode." }
    if (-not (Test-ConfiguredRunner)) { Fail 'RUNNER_REGISTRATION_INVALID' 'Runner registration files were not created for the expected repository.' }
}

function Connect-TaskScheduler {
    $service = New-Object -ComObject 'Schedule.Service'
    $service.Connect()
    return $service
}

function Install-RunnerAutostartTask {
    $runCmd = Join-Path $RunnerRoot 'run.cmd'
    if (-not (Test-Path -LiteralPath $runCmd -PathType Leaf)) { Fail 'RUN_CMD_MISSING' 'run.cmd is missing.' }
    $user = "$env:USERDOMAIN\$env:USERNAME"
    $service = Connect-TaskScheduler
    $folder = $service.GetFolder('\')
    $definition = $service.NewTask(0)
    $definition.RegistrationInfo.Description = 'Keeps the configured NEXUS GitHub Actions self-hosted runner listener available after Windows logon.'
    $definition.RegistrationInfo.Author = 'NEXUS Personal Pro'
    $definition.Principal.UserId = $user
    $definition.Principal.LogonType = 3
    $definition.Principal.RunLevel = 0
    $definition.Settings.Enabled = $true
    $definition.Settings.StartWhenAvailable = $true
    $definition.Settings.DisallowStartIfOnBatteries = $false
    $definition.Settings.StopIfGoingOnBatteries = $false
    $definition.Settings.MultipleInstances = 2
    $definition.Settings.RestartInterval = 'PT1M'
    $definition.Settings.RestartCount = 999
    $definition.Settings.ExecutionTimeLimit = 'PT0S'
    $trigger = $definition.Triggers.Create(9)
    $trigger.Enabled = $true
    $trigger.UserId = $user
    $action = $definition.Actions.Create(0)
    $action.Path = $env:ComSpec
    $action.Arguments = '/d /s /c ""' + $runCmd + '""'
    $action.WorkingDirectory = $RunnerRoot
    $registered = $folder.RegisterTaskDefinition("\$TaskName", $definition, 6, $null, $null, 3, $null)
    if (-not $registered) { Fail 'RUNNER_AUTOSTART_FAILED' 'Task Scheduler did not return the registered runner task.' }
    [void]$registered.Run($null)
}

function Get-RunnerListener {
    $expectedRoot = [IO.Path]::GetFullPath($RunnerRoot)

    try {
        foreach ($proc in Get-Process -Name 'Runner.Listener' -ErrorAction SilentlyContinue) {
            try {
                $path = [string]$proc.Path
                if ($path -and ([IO.Path]::GetFullPath($path)).StartsWith($expectedRoot, [StringComparison]::OrdinalIgnoreCase)) {
                    return $proc
                }
            }
            catch { }
        }
    }
    catch { }

    try {
        foreach ($row in Get-CimInstance Win32_Process -Filter "Name='Runner.Listener.exe'" -ErrorAction Stop) {
            $path = [string]$row.ExecutablePath
            if ($path -and ([IO.Path]::GetFullPath($path)).StartsWith($expectedRoot, [StringComparison]::OrdinalIgnoreCase)) {
                return $row
            }
        }
    }
    catch {
        Write-Log 'runner_listener_cim_probe_unavailable_using_process_probe_only=true'
    }
    return $null
}

function Wait-ForRunner([int]$Seconds = 45) {
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    do {
        $listener = Get-RunnerListener
        if ($listener) { return $listener }
        Start-Sleep -Milliseconds 750
    } while ([DateTime]::UtcNow -lt $deadline)
    return $null
}

try {
    Ensure-StateRoot
    Assert-OwnerSession
    Write-Host 'NEXUS runner registration started.' -ForegroundColor Cyan

    $githubCliAuthUsed = $false
    if (-not (Test-ConfiguredRunner)) {
        $archive = Get-VerifiedRunnerArchive
        Install-RunnerFiles $archive
        $gh = Find-GhExecutable
        if (-not $gh) { $gh = Install-PortableGh }
        Ensure-GhAuth $gh
        $githubCliAuthUsed = $true
        $registrationToken = Get-RegistrationToken $gh
        try {
            Register-Runner $registrationToken
        }
        finally {
            $registrationToken = $null
            Remove-Item Env:NEXUS_GITHUB_RUNNER_REGISTRATION_TOKEN -ErrorAction SilentlyContinue
        }
    }

    Install-RunnerAutostartTask
    $listener = Wait-ForRunner
    if (-not $listener) {
        Fail 'RUNNER_LISTENER_NOT_OBSERVED' 'Runner registration completed, but Runner.Listener.exe was not observed after starting the autostart task.'
    }

    $pidValue = if ($listener.PSObject.Properties['ProcessId']) { [int]$listener.ProcessId } elseif ($listener.PSObject.Properties['Id']) { [int]$listener.Id } else { $null }
    Write-Evidence 'SUCCESS' @{
        configured_runner = $true
        listener_observed = $true
        listener_pid = $pidValue
        scheduled_task = $TaskName
        github_cli_auth_used = [bool]$githubCliAuthUsed
    }
    Write-Log "status=SUCCESS runner=$RunnerName root=$RunnerRoot listener_pid=$pidValue"
    Write-Host ''
    Write-Host 'NEXUS RUNNER REGISTERED AND RUNNING' -ForegroundColor Green
    Write-Host "Runner: $RunnerName"
    Write-Host 'You can close this window. No output needs to be sent back.'
    Start-Sleep -Seconds 4
    exit 0
}
catch {
    $message = $_.Exception.Message
    Write-Host ''
    Write-Host "NEXUS RUNNER REGISTRATION BLOCKED: $message" -ForegroundColor Red
    Write-Host "Evidence: $EvidencePath"
    Write-Host 'Leave this window open only if you want to photograph the error.'
    try { Read-Host 'Press Enter to close' | Out-Null } catch { }
    exit 1
}
