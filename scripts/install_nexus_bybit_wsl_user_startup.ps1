[CmdletBinding()]
param(
    [ValidateSet('Install','Watch')]
    [string]$Mode = 'Install',
    [string]$Distribution = 'Ubuntu',
    [string]$RunnerRoot = '/opt/nexus-bybit-runner',
    [string]$ExpectedRunnerName = 'NEXUS-BYBIT-WSL'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

if ($Distribution -ne 'Ubuntu') { throw 'Distribution must remain pinned to Ubuntu.' }
if ($RunnerRoot -ne '/opt/nexus-bybit-runner') { throw 'RunnerRoot must remain pinned.' }
if ($ExpectedRunnerName -ne 'NEXUS-BYBIT-WSL') { throw 'ExpectedRunnerName must remain pinned.' }

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$sid = [string]$identity.User.Value
if ($sid -in @('S-1-5-18','S-1-5-19','S-1-5-20')) {
    throw 'This recovery must run from the signed-in Windows user context, not a service account.'
}
if (-not [Environment]::UserInteractive) {
    throw 'An interactive signed-in Windows user is required.'
}

$wsl = Join-Path $env:SystemRoot 'System32\wsl.exe'
if (-not (Test-Path -LiteralPath $wsl -PathType Leaf)) { throw 'wsl.exe is required.' }

$stateRoot = Join-Path $env:LOCALAPPDATA 'NEXUS\BybitWSLUserStartup'
$stableScript = Join-Path $stateRoot 'bybit-wsl-user-watchdog.ps1'
$logPath = Join-Path $stateRoot 'watchdog.log'
$evidencePath = Join-Path $stateRoot 'evidence.json'
$startupRoot = [Environment]::GetFolderPath('Startup')
$startupVbs = Join-Path $startupRoot 'NEXUS-Bybit-WSL-User-Startup.vbs'
$legacyStartupCmd = Join-Path $startupRoot 'NEXUS-Bybit-WSL-User-Startup.cmd'
$wslTimeoutMilliseconds = 10000
$watchdogGeneration = 2

function Invoke-WslNative {
    param([Parameter(Mandatory = $true)][string]$Command)

    # Invoke wsl.exe through a bounded child process. A stalled WSL interop call
    # must never pin the watchdog forever and prevent future self-heal attempts.
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Command))
    $bashCommand = "printf '%s' '$encoded' | base64 -d | bash"
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = $wsl
    $psi.Arguments = '-d ' + $Distribution + ' -u root -- bash -lc "' + $bashCommand + '"'
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $psi.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden

    $proc = New-Object Diagnostics.Process
    $proc.StartInfo = $psi
    try {
        if (-not $proc.Start()) {
            return [ordered]@{ exit_code = -1; output = 'wsl_process_start_failed' }
        }
        if (-not $proc.WaitForExit($wslTimeoutMilliseconds)) {
            try { $proc.Kill() } catch { }
            return [ordered]@{ exit_code = 124; output = 'wsl_timeout' }
        }
        $stdout = $proc.StandardOutput.ReadToEnd()
        $stderr = $proc.StandardError.ReadToEnd()
        $text = (($stdout + [Environment]::NewLine + $stderr).Trim())
        return [ordered]@{ exit_code = [int]$proc.ExitCode; output = $text }
    }
    catch {
        return [ordered]@{ exit_code = -1; output = $_.Exception.GetType().Name }
    }
    finally {
        $proc.Dispose()
    }
}

function Write-Log([string]$Message) {
    New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
    Add-Content -LiteralPath $logPath -Encoding UTF8 -Value ('[{0}] {1}' -f [DateTime]::UtcNow.ToString('o'), $Message)
}

function Test-ExistingRegistration {
    $probe = Invoke-WslNative "test -x '$RunnerRoot/run.sh' && test -f '$RunnerRoot/.runner' && grep -Eq 'agentName[^,]*$ExpectedRunnerName' '$RunnerRoot/.runner'"
    if ($probe.exit_code -ne 0) {
        throw 'Existing NEXUS-BYBIT-WSL registration was not found; this script will not create or replace it.'
    }
}

function Test-Listener {
    $probe = Invoke-WslNative "pgrep -f '$RunnerRoot/bin/[R]unner.Listener' >/dev/null 2>&1"
    if ($probe.exit_code -eq 124) {
        Write-Log 'listener_probe_timeout=true'
    }
    return ($probe.exit_code -eq 0)
}

function Start-ListenerIfMissing {
    Test-ExistingRegistration
    if (Test-Listener) { return $false }
    $start = Invoke-WslNative "cd '$RunnerRoot' && export RUNNER_ALLOW_RUNASROOT=1 && export RUNNER_TRACKING_ID= && nohup ./run.sh >>/tmp/nexus-bybit-runner.log 2>&1 </dev/null &"
    if ($start.exit_code -ne 0) {
        Write-Log ('runner_start_request_failed=' + $start.exit_code)
        return $false
    }
    Start-Sleep -Seconds 3
    return (Test-Listener)
}

function Write-Evidence([string]$Decision, [bool]$ListenerObserved) {
    New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
    $payload = [ordered]@{
        schema_version = 2
        generated_at_utc = [DateTime]::UtcNow.ToString('o')
        decision = $Decision
        windows_identity = [string]$identity.Name
        windows_user_sid = $sid
        distribution = $Distribution
        runner_root = $RunnerRoot
        expected_runner_name = $ExpectedRunnerName
        listener_observed = $ListenerObserved
        startup_path = $startupVbs
        stable_watchdog_path = $stableScript
        watchdog_generation = $watchdogGeneration
        wsl_call_timeout_seconds = [int]($wslTimeoutMilliseconds / 1000)
        administrator_required = $false
        task_scheduler_used = $false
        runner_registration_modified = $false
        runner_credentials_modified = $false
        windows_acl_modified = $false
        windows_service_modified = $false
        private_exchange_credentials_used = $false
        live_trading_authority_changed = $false
        popup_launcher_used = $false
    }
    $payload | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $evidencePath -Encoding UTF8
}

function Run-Watchdog {
    Test-ExistingRegistration
    New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
    $createdNew = $false
    # Version the mutex so a watchdog from an older implementation that is
    # already stuck inside WSL interop cannot block a repaired watchdog forever.
    $mutexName = 'Local\NEXUS-Bybit-WSL-Watchdog-v' + $watchdogGeneration + '-' + $sid
    $mutex = New-Object Threading.Mutex($true, $mutexName, [ref]$createdNew)
    if (-not $createdNew) { return }
    try {
        Write-Log ('watchdog_started=true generation=' + $watchdogGeneration)
        while ($true) {
            try {
                if (-not (Test-Listener)) {
                    $started = Start-ListenerIfMissing
                    Write-Log ('listener_recovery=' + $started.ToString().ToLowerInvariant())
                }
            }
            catch {
                Write-Log ('watchdog_iteration_error=' + $_.Exception.GetType().Name)
            }
            Start-Sleep -Seconds 15
        }
    }
    finally {
        try { $mutex.ReleaseMutex() } catch { }
        $mutex.Dispose()
    }
}

if ($Mode -eq 'Watch') {
    Run-Watchdog
    exit 0
}

Test-ExistingRegistration
New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
New-Item -ItemType Directory -Path $startupRoot -Force | Out-Null

$source = [IO.Path]::GetFullPath($PSCommandPath)
if (-not $source.Equals([IO.Path]::GetFullPath($stableScript), [StringComparison]::OrdinalIgnoreCase)) {
    Copy-Item -LiteralPath $source -Destination $stableScript -Force
}

$watchCommand = 'powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $stableScript + '" -Mode Watch'
$escapedWatchCommand = $watchCommand.Replace('"', '""')
$vbs = 'Set shell = CreateObject("WScript.Shell")' + "`r`n" + 'shell.Run "' + $escapedWatchCommand + '", 0, False' + "`r`n"
[IO.File]::WriteAllText($startupVbs, $vbs, (New-Object Text.ASCIIEncoding))
if (Test-Path -LiteralPath $legacyStartupCmd -PathType Leaf) {
    Remove-Item -LiteralPath $legacyStartupCmd -Force
}

$psi = New-Object Diagnostics.ProcessStartInfo
$psi.FileName = 'powershell.exe'
$psi.Arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $stableScript + '" -Mode Watch'
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$psi.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
$proc = New-Object Diagnostics.Process
$proc.StartInfo = $psi
if (-not $proc.Start()) { throw 'Unable to start user-context watchdog.' }

Start-Sleep -Seconds 5
$listener = Test-Listener
Write-Evidence -Decision $(if ($listener) { 'USER_CONTEXT_SELF_HEAL_ACTIVE' } else { 'WATCHDOG_STARTED_LISTENER_NOT_YET_OBSERVED' }) -ListenerObserved $listener
if (-not $listener) { throw 'Watchdog started but NEXUS-BYBIT-WSL listener was not observed.' }

Write-Host 'bybit_wsl_user_startup_recovery=PASS'
Write-Host "startup_path=$startupVbs"
Write-Host "watchdog_path=$stableScript"
Write-Host ('watchdog_generation=' + $watchdogGeneration)
Write-Host ('wsl_call_timeout_seconds=' + [int]($wslTimeoutMilliseconds / 1000))
Write-Host 'administrator_required=false'
Write-Host 'task_scheduler_used=false'
Write-Host 'runner_registration_modified=false'
Write-Host 'windows_acl_modified=false'
Write-Host 'live_trading_authority_changed=false'
Write-Host 'popup_launcher_used=false'
exit 0
