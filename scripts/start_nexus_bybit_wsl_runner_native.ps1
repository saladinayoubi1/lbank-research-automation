param(
    [string]$OutputPath = "build\bybit-wsl-provisioning-after-repair\evidence.json",
    [string]$Distribution = "Ubuntu",
    [string]$RunnerName = "NEXUS-BYBIT-WSL",
    [string]$RunnerLabel = "nexus-bybit-network"
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $rawOutput = @(& $FilePath @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
        $text = (($rawOutput | ForEach-Object { $_.ToString() }) | Out-String).Trim()
        return [ordered]@{
            exit_code = if ($null -eq $exitCode) { -1 } else { [int]$exitCode }
            output = $text
        }
    }
    catch {
        return [ordered]@{
            exit_code = -1
            output = $_.Exception.ToString()
        }
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

function Invoke-Wsl {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    return Invoke-Native -FilePath (Join-Path $env:SystemRoot 'System32\wsl.exe') -Arguments $Arguments
}

function Resolve-Gh {
    $candidates = @()
    $command = Get-Command gh.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command) {
        $candidates += $command.Source
    }
    $candidates += @(
        (Join-Path $env:ProgramFiles 'GitHub CLI\gh.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\GitHub CLI\gh.exe')
    )
    return @($candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -Unique)[0]
}

function Write-Evidence {
    param(
        [Parameter(Mandatory = $true)][string]$Target,
        [Parameter(Mandatory = $true)][System.Collections.IDictionary]$Payload
    )

    $parent = Split-Path -Parent $Target
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $json = $Payload | ConvertTo-Json -Depth 10
    [IO.File]::WriteAllText($Target, $json, (New-Object Text.UTF8Encoding($false)))
}

$target = [IO.Path]::GetFullPath($OutputPath)
$repository = [string]$env:GITHUB_REPOSITORY
$runnerRoot = '/opt/nexus-bybit-runner'
$taskName = 'NEXUS Bybit WSL Runner'
$launcherRoot = Join-Path $env:ProgramData 'NEXUS\BybitWSL'
$launcherPath = Join-Path $launcherRoot 'start-nexus-bybit-wsl-runner.cmd'
$schtasks = Join-Path $env:SystemRoot 'System32\schtasks.exe'
$isAdmin = Test-IsAdministrator

if ($repository -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') {
    throw 'GITHUB_REPOSITORY is missing or invalid.'
}
foreach ($value in @($Distribution, $RunnerName, $RunnerLabel)) {
    if ($value -notmatch '^[A-Za-z0-9._-]+$') {
        throw 'Distribution, runner name, and runner label must use only safe identifier characters.'
    }
}

$evidence = [ordered]@{
    schema_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString('o')
    source_sha = $env:GITHUB_SHA
    run_id = $env:GITHUB_RUN_ID
    repository = $repository
    administrator = $isAdmin
    distribution = $Distribution
    runner_name = $RunnerName
    runner_label = $RunnerLabel
    wsl_runner_root = $runnerRoot
    launcher_path = $launcherPath
    task_name = $taskName
    task_scheduler_backend = 'schtasks.exe'
    runner_package_installed = $false
    runner_registered = $false
    autostart_installed = $false
    task_create_exit_code = $null
    task_run_exit_code = $null
    task_query_exit_code = $null
    task_state = $null
    github_runner_status = $null
    github_runner_busy = $null
    github_runner_labels = @()
    github_registration_token_persisted = $false
    bybit_private_credentials_used = $false
    windows_runner_paths_modified = $false
    windows_runner_service_modified = $false
    automatic_restart_performed = $false
    error_class = $null
    decision = $null
}

function Complete-Start {
    param(
        [Parameter(Mandatory = $true)][string]$Decision,
        [int]$ExitCode = 0,
        [string]$ErrorClass = $null
    )

    $evidence.decision = $Decision
    $evidence.error_class = $ErrorClass
    Write-Evidence -Target $target -Payload $evidence
    $digest = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Host "bybit_wsl_native_start_decision=$Decision"
    Write-Host "task_scheduler_backend=$($evidence.task_scheduler_backend)"
    Write-Host "github_runner_status=$($evidence.github_runner_status)"
    Write-Host 'windows_runner_paths_modified=false'
    Write-Host 'windows_runner_service_modified=false'
    Write-Host 'github_registration_token_persisted=false'
    Write-Host "evidence_sha256=$digest"
    exit $ExitCode
}

trap {
    $evidence.decision = 'WSL_RUNNER_NATIVE_START_FAILED'
    $evidence.error_class = $_.Exception.GetType().Name
    Write-Evidence -Target $target -Payload $evidence
    $digest = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Host 'bybit_wsl_native_start_decision=WSL_RUNNER_NATIVE_START_FAILED'
    Write-Host "native_start_error_class=$($evidence.error_class)"
    Write-Host 'windows_runner_paths_modified=false'
    Write-Host 'windows_runner_service_modified=false'
    Write-Host 'github_registration_token_persisted=false'
    Write-Host "evidence_sha256=$digest"
    exit 1
}

if (-not $isAdmin) {
    Complete-Start -Decision 'ADMINISTRATOR_TOKEN_REQUIRED' -ExitCode 1 -ErrorClass 'SecurityException'
}
if (-not (Test-Path -LiteralPath $schtasks -PathType Leaf)) {
    Complete-Start -Decision 'SCHTASKS_REQUIRED' -ExitCode 1 -ErrorClass 'FileNotFoundException'
}

$configuredProbe = Invoke-Wsl -Arguments @(
    '-d', $Distribution, '-u', 'root', '--', 'bash', '-lc',
    "test -x '$runnerRoot/run.sh' && test -f '$runnerRoot/.runner'"
)
if ($configuredProbe.exit_code -ne 0) {
    Complete-Start -Decision 'REGISTERED_RUNNER_FILES_REQUIRED' -ExitCode 1 -ErrorClass 'InvalidOperationException'
}
$evidence.runner_package_installed = $true
$evidence.runner_registered = $true

New-Item -ItemType Directory -Path $launcherRoot -Force | Out-Null
$launcher = @"
@echo off
set "RUNNER_TRACKING_ID="
"$env:SystemRoot\System32\wsl.exe" -d $Distribution -u root -- bash -lc "cd $runnerRoot && export RUNNER_ALLOW_RUNASROOT=1 && exec ./run.sh"
"@
[IO.File]::WriteAllText($launcherPath, $launcher, (New-Object Text.ASCIIEncoding))

$create = Invoke-Native -FilePath $schtasks -Arguments @(
    '/Create',
    '/TN', $taskName,
    '/TR', $launcherPath,
    '/SC', 'ONLOGON',
    '/RL', 'HIGHEST',
    '/F'
)
$evidence.task_create_exit_code = $create.exit_code
if ($create.output) {
    $evidence.task_create_output = if ($create.output.Length -gt 2048) { $create.output.Substring(0, 2048) } else { $create.output }
}
if ($create.exit_code -ne 0) {
    Complete-Start -Decision 'SCHTASKS_CREATE_FAILED' -ExitCode 1 -ErrorClass 'InvalidOperationException'
}
$evidence.autostart_installed = $true

$runTask = Invoke-Native -FilePath $schtasks -Arguments @('/Run', '/TN', $taskName)
$evidence.task_run_exit_code = $runTask.exit_code
if ($runTask.output) {
    $evidence.task_run_output = if ($runTask.output.Length -gt 2048) { $runTask.output.Substring(0, 2048) } else { $runTask.output }
}
if ($runTask.exit_code -ne 0) {
    Complete-Start -Decision 'SCHTASKS_RUN_FAILED' -ExitCode 1 -ErrorClass 'InvalidOperationException'
}
$evidence.task_state = 'start_requested'

Start-Sleep -Seconds 5
$queryTask = Invoke-Native -FilePath $schtasks -Arguments @('/Query', '/TN', $taskName, '/FO', 'LIST', '/V')
$evidence.task_query_exit_code = $queryTask.exit_code
if ($queryTask.output) {
    $evidence.task_query_output = if ($queryTask.output.Length -gt 4096) { $queryTask.output.Substring(0, 4096) } else { $queryTask.output }
}
if ($queryTask.exit_code -ne 0) {
    Complete-Start -Decision 'SCHTASKS_QUERY_FAILED' -ExitCode 1 -ErrorClass 'InvalidOperationException'
}
$evidence.task_state = 'registered_and_started'

$gh = Resolve-Gh
if (-not $gh) {
    Complete-Start -Decision 'GH_CLI_REQUIRED_FOR_RUNNER_STATUS' -ExitCode 1 -ErrorClass 'FileNotFoundException'
}
& $gh auth status --hostname github.com 1>$null 2>$null
if ($LASTEXITCODE -ne 0) {
    Complete-Start -Decision 'GH_AUTH_REQUIRED_FOR_RUNNER_STATUS' -ExitCode 1 -ErrorClass 'SecurityException'
}

for ($attempt = 1; $attempt -le 8; $attempt++) {
    try {
        $runnerPayload = & $gh api --hostname github.com "repos/$repository/actions/runners?per_page=100" 2>$null | ConvertFrom-Json
        $matchedRunner = @($runnerPayload.runners | Where-Object { $_.name -eq $RunnerName } | Select-Object -First 1)
        if ($matchedRunner.Count -eq 1) {
            $evidence.github_runner_status = [string]$matchedRunner[0].status
            $evidence.github_runner_busy = [bool]$matchedRunner[0].busy
            $labels = @($matchedRunner[0].labels | ForEach-Object { [string]$_.name })
            $evidence.github_runner_labels = $labels
            if ($matchedRunner[0].status -eq 'online' -and $RunnerLabel -in $labels) {
                Complete-Start -Decision 'READY_FOR_GITHUB_VALIDATION'
            }
        }
    }
    catch {
        $evidence.github_status_probe_error = $_.Exception.GetType().Name
    }
    Start-Sleep -Seconds 5
}

Complete-Start -Decision 'RUNNER_NOT_ONLINE_AFTER_NATIVE_START' -ExitCode 1 -ErrorClass 'InvalidOperationException'
