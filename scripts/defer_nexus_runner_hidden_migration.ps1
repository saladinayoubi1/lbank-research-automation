[CmdletBinding()]
param(
    [int]$TimeoutMinutes = 75,
    [int]$PollSeconds = 5
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$ExpectedGitHubUrl = 'https://github.com/saladinayoubi1/lbank-research-automation'
$NexusRoot = Join-Path $env:LOCALAPPDATA 'NEXUS'
$RunnerRoot = Join-Path $NexusRoot 'actions-runner'
$StateRoot = Join-Path $NexusRoot 'RunnerAutostart'
$EvidencePath = Join-Path $StateRoot 'deferred-hidden-migration-evidence.json'
$LogPath = Join-Path $StateRoot 'deferred-hidden-migration.log'
$HiddenRepairScript = Join-Path (Split-Path -Parent $PSCommandPath) 'install_nexus_runner_hidden_autostart.ps1'
$MutexName = 'Local\NEXUS-Runner-Hidden-Migration'

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
        contract_version = 'nexus.runner-hidden-migration-deferred.v1'
        status = $Status
        generated_at = [DateTime]::UtcNow.ToString('o')
        runner_root = $RunnerRoot
        timeout_minutes = $TimeoutMinutes
        poll_seconds = $PollSeconds
        active_job_interrupted = $false
        runner_registration_modified = $false
        credentials_modified = $false
        service_installed = $false
        elevation_requested = $false
        paper_only = $true
        live_trading_authority = $false
    }
    foreach ($key in $Extra.Keys) { $payload[$key] = $Extra[$key] }
    $tmp = $EvidencePath + '.tmp'
    $payload | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $tmp -Encoding UTF8
    Move-Item -LiteralPath $tmp -Destination $EvidencePath -Force
}

function Normalize-GitHubUrl([string]$Value) {
    if (-not $Value) { return '' }
    return $Value.Trim().TrimEnd('/').ToLowerInvariant()
}

function Assert-ConfiguredRunner {
    if ($env:OS -ne 'Windows_NT') { throw 'Windows is required.' }
    if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA is unavailable.' }
    if (-not (Test-Path -LiteralPath $HiddenRepairScript -PathType Leaf)) {
        throw 'Hidden runner autostart repair script is missing.'
    }
    $settings = Join-Path $RunnerRoot '.runner'
    $credentials = Join-Path $RunnerRoot '.credentials'
    $runCmd = Join-Path $RunnerRoot 'run.cmd'
    $listener = Join-Path $RunnerRoot 'bin\Runner.Listener.exe'
    foreach ($path in @($settings,$credentials,$runCmd,$listener)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Configured NEXUS runner file is missing: $path"
        }
    }
    $config = Get-Content -LiteralPath $settings -Raw -ErrorAction Stop | ConvertFrom-Json
    $urlProperty = $config.PSObject.Properties['gitHubUrl']
    if (-not $urlProperty -or -not $urlProperty.Value) { throw 'Runner repository binding is missing.' }
    if ((Normalize-GitHubUrl ([string]$urlProperty.Value)) -ne (Normalize-GitHubUrl $ExpectedGitHubUrl)) {
        throw 'Runner is not bound to the expected NEXUS repository.'
    }
}

function Get-ManagedWorker {
    $expectedRoot = [IO.Path]::GetFullPath($RunnerRoot).TrimEnd('\') + '\'
    foreach ($proc in Get-Process -Name 'Runner.Worker' -ErrorAction SilentlyContinue) {
        try {
            $path = [string]$proc.Path
            if ($path -and ([IO.Path]::GetFullPath($path)).StartsWith($expectedRoot,[StringComparison]::OrdinalIgnoreCase)) {
                return $proc
            }
        }
        catch { }
    }
    return $null
}

function Resolve-WindowsPowerShell {
    $candidate = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    return (Get-Command powershell.exe -ErrorAction Stop).Source
}

function Invoke-HiddenRepair {
    $powershell = Resolve-WindowsPowerShell
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $powershell
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    $psi.Arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$HiddenRepairScript`" -Mode Install"
    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    if (-not $proc.Start()) { throw 'Failed to start hidden runner migration repair.' }
    $proc.WaitForExit()
    return [int]$proc.ExitCode
}

$mutex = $null
$ownsMutex = $false
try {
    if ($TimeoutMinutes -lt 1 -or $TimeoutMinutes -gt 180) { throw 'TimeoutMinutes must be between 1 and 180.' }
    if ($PollSeconds -lt 1 -or $PollSeconds -gt 60) { throw 'PollSeconds must be between 1 and 60.' }
    Ensure-StateRoot
    Assert-ConfiguredRunner

    $mutex = New-Object System.Threading.Mutex($false, $MutexName)
    $ownsMutex = $mutex.WaitOne(0)
    if (-not $ownsMutex) {
        Write-Evidence 'ALREADY_RUNNING' @{ deferred = $true }
        Write-Log 'deferred_hidden_migration_already_running=true'
        exit 0
    }

    $deadline = [DateTime]::UtcNow.AddMinutes($TimeoutMinutes)
    Write-Evidence 'WAITING_FOR_ACTIVE_JOB' @{ deferred = $true }
    Write-Log "deferred_hidden_migration_started timeout_minutes=$TimeoutMinutes"

    while ([DateTime]::UtcNow -lt $deadline) {
        $worker = Get-ManagedWorker
        if ($worker) {
            Write-Log "active_runner_worker_observed pid=$($worker.Id); migration_deferred=true"
            Start-Sleep -Seconds $PollSeconds
            continue
        }

        Write-Log 'no_active_runner_worker_observed attempting_hidden_migration=true'
        $exitCode = Invoke-HiddenRepair
        if ($exitCode -eq 0) {
            Write-Evidence 'SUCCESS' @{ deferred = $true; hidden_migration_completed = $true }
            Write-Log 'status=SUCCESS deferred_hidden_migration=true'
            exit 0
        }

        # A new GitHub job may race with the quiet interval. Retry without interrupting it.
        Write-Log "hidden_migration_attempt_exit=$exitCode retrying_without_interrupt=true"
        Start-Sleep -Seconds ([Math]::Max($PollSeconds, 10))
    }

    Write-Evidence 'TIMEOUT_WAITING_FOR_ACTIVE_JOB' @{ deferred = $true; hidden_migration_completed = $false }
    Write-Log 'status=TIMEOUT_WAITING_FOR_ACTIVE_JOB'
    exit 3
}
catch {
    $message = $_.Exception.Message
    try { Write-Evidence 'BLOCKED' @{ error = $message; deferred = $true } } catch { }
    try { Write-Log "status=BLOCKED error=$message" } catch { }
    exit 1
}
finally {
    if ($ownsMutex -and $mutex) {
        try { $mutex.ReleaseMutex() | Out-Null } catch { }
    }
    if ($mutex) { $mutex.Dispose() }
}
