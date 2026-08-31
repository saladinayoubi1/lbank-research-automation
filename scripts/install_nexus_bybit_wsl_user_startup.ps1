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
$watchdogGeneration = 4
$managedRunnerLog = '/tmp/nexus-bybit-runner.log'
$managedChildMissingListenerThreshold = 3

function New-WslProcessStartInfo {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [bool]$RedirectOutput = $false
    )

    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Command))
    $bashCommand = "printf '%s' '$encoded' | base64 -d | bash"
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = $wsl
    $psi.Arguments = '-d ' + $Distribution + ' -u root -- bash -lc "' + $bashCommand + '"'
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
    if ($RedirectOutput) {
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
    }
    return $psi
}

function Invoke-WslNative {
    param([Parameter(Mandatory = $true)][string]$Command)

    # All probe/mutation calls are bounded. The long-lived managed runner uses a
    # separate watchdog-owned wsl.exe child and is never routed through here.
    $psi = New-WslProcessStartInfo -Command $Command -RedirectOutput $true
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

function Get-RunnerProcessState {
    $probe = Invoke-WslNative "if pgrep -f '$RunnerRoot/bin/[R]unner.Listener' >/dev/null 2>&1; then echo listener=1; else echo listener=0; fi; if pgrep -f '$RunnerRoot/bin/[R]unner.Worker' >/dev/null 2>&1; then echo worker=1; else echo worker=0; fi"
    if ($probe.exit_code -eq 124) {
        Write-Log 'runner_process_probe_timeout=true'
        return [ordered]@{ known = $false; listener = $false; worker = $false }
    }
    if ($probe.exit_code -ne 0) {
        Write-Log ('runner_process_probe_failed=' + $probe.exit_code)
        return [ordered]@{ known = $false; listener = $false; worker = $false }
    }
    return [ordered]@{
        known = $true
        listener = ($probe.output -match '(?m)^listener=1$')
        worker = ($probe.output -match '(?m)^worker=1$')
    }
}

function Test-Listener {
    $state = Get-RunnerProcessState
    return ($state.known -and $state.listener)
}

function Stop-IdleExternalListener {
    # Never recycle a listener while a Runner.Worker is active. This prevents a
    # watchdog upgrade from interrupting a physical Paper job already in flight.
    $command = "if pgrep -f '$RunnerRoot/bin/[R]unner.Worker' >/dev/null 2>&1; then exit 3; fi; for p in `$(pgrep -f '$RunnerRoot/bin/[R]unner.Listener' 2>/dev/null || true); do kill -TERM `$p || true; done; exit 0"
    $result = Invoke-WslNative $command
    if ($result.exit_code -eq 3) { return 'BUSY' }
    if ($result.exit_code -ne 0) {
        Write-Log ('listener_recycle_failed=' + $result.exit_code)
        return 'FAILED'
    }
    Start-Sleep -Seconds 2
    return 'STOPPED'
}

function Start-ManagedRunnerProcess {
    Test-ExistingRegistration
    $command = "cd '$RunnerRoot' && export RUNNER_ALLOW_RUNASROOT=1 && export RUNNER_TRACKING_ID= && exec ./run.sh >>'$managedRunnerLog' 2>&1"
    $psi = New-WslProcessStartInfo -Command $command -RedirectOutput $false
    $proc = New-Object Diagnostics.Process
    $proc.StartInfo = $psi
    try {
        if (-not $proc.Start()) {
            $proc.Dispose()
            return $null
        }
        Start-Sleep -Seconds 5
        if ($proc.HasExited) {
            Write-Log ('managed_runner_early_exit=' + $proc.ExitCode)
            $proc.Dispose()
            return $null
        }
        Write-Log ('managed_runner_started=true windows_pid=' + $proc.Id)
        return $proc
    }
    catch {
        Write-Log ('managed_runner_start_error=' + $_.Exception.GetType().Name)
        $proc.Dispose()
        return $null
    }
}

function Stop-PreviousUserWatchdogs {
    # The stable watchdog path is reused across upgrades. Kill only same-user
    # PowerShell processes whose command line explicitly points at that script
    # in -Mode Watch. This is process cleanup only; no task/service/ACL mutation.
    try {
        $query = "SELECT ProcessId, CommandLine FROM Win32_Process WHERE Name='powershell.exe'"
        $searcher = New-Object System.Management.ManagementObjectSearcher($query)
        foreach ($item in @($searcher.Get())) {
            $pidValue = [int]$item.ProcessId
            $commandLine = [string]$item.CommandLine
            if ($pidValue -eq $PID) { continue }
            if (-not $commandLine) { continue }
            if ($commandLine.IndexOf($stableScript, [StringComparison]::OrdinalIgnoreCase) -lt 0) { continue }
            if ($commandLine -notmatch '(?i)-Mode\s+Watch') { continue }
            try {
                [Diagnostics.Process]::GetProcessById($pidValue).Kill()
                Write-Log ('previous_watchdog_terminated_pid=' + $pidValue)
            }
            catch {
                Write-Log ('previous_watchdog_terminate_failed_pid=' + $pidValue)
            }
        }
        $searcher.Dispose()
    }
    catch {
        Write-Log ('previous_watchdog_inventory_error=' + $_.Exception.GetType().Name)
    }
}

function Write-Evidence([string]$Decision, [bool]$ListenerObserved) {
    New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
    $payload = [ordered]@{
        schema_version = 4
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
        watchdog_owns_wsl_child = $true
        managed_child_liveness_probe = $true
        missing_listener_recycle_after_probes = $managedChildMissingListenerThreshold
        stale_idle_listener_recycle = $true
        active_worker_interrupt_allowed = $false
        unknown_probe_interrupt_allowed = $false
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
    $mutexName = 'Local\NEXUS-Bybit-WSL-Watchdog-v' + $watchdogGeneration + '-' + $sid
    $mutex = New-Object Threading.Mutex($true, $mutexName, [ref]$createdNew)
    if (-not $createdNew) { return }

    $managedRunner = $null
    $managedMissingListenerProbes = 0
    try {
        Write-Log ('watchdog_started=true generation=' + $watchdogGeneration + ' managed_child=true liveness_probe=true')
        while ($true) {
            try {
                if ($null -ne $managedRunner) {
                    if ($managedRunner.HasExited) {
                        Write-Log ('managed_runner_exit=' + $managedRunner.ExitCode)
                        $managedRunner.Dispose()
                        $managedRunner = $null
                        $managedMissingListenerProbes = 0
                    }
                    else {
                        # A Windows wsl.exe child can remain alive even when the
                        # pinned Linux runner is no longer listening. Verify the
                        # actual Listener/Worker state on every watchdog cycle.
                        $managedState = Get-RunnerProcessState
                        if (-not $managedState.known) {
                            # Fail closed: an unknown probe must never interrupt a
                            # potentially active Worker.
                            $managedMissingListenerProbes = 0
                            Write-Log 'managed_child_state_unknown_no_interrupt=true'
                        }
                        elseif ($managedState.worker) {
                            $managedMissingListenerProbes = 0
                            Write-Log 'managed_child_worker_active_no_interrupt=true'
                        }
                        elseif ($managedState.listener) {
                            $managedMissingListenerProbes = 0
                        }
                        else {
                            $managedMissingListenerProbes += 1
                            Write-Log ('managed_child_missing_listener_probe=' + $managedMissingListenerProbes)
                            if ($managedMissingListenerProbes -ge $managedChildMissingListenerThreshold) {
                                Write-Log 'managed_child_stale_recycle=true'
                                try {
                                    $managedRunner.Kill()
                                    [void]$managedRunner.WaitForExit(5000)
                                }
                                catch {
                                    Write-Log ('managed_child_stale_recycle_error=' + $_.Exception.GetType().Name)
                                }
                                try { $managedRunner.Dispose() } catch { }
                                $managedRunner = $null
                                $managedMissingListenerProbes = 0
                            }
                        }
                    }
                }

                if ($null -eq $managedRunner) {
                    $state = Get-RunnerProcessState
                    if (-not $state.known) {
                        Write-Log 'runner_state_unknown_waiting=true'
                    }
                    elseif ($state.worker) {
                        Write-Log 'existing_runner_worker_active_waiting=true'
                    }
                    else {
                        if ($state.listener) {
                            $recycle = Stop-IdleExternalListener
                            Write-Log ('external_listener_recycle=' + $recycle.ToLowerInvariant())
                            if ($recycle -eq 'BUSY') {
                                Start-Sleep -Seconds 15
                                continue
                            }
                        }
                        $managedRunner = Start-ManagedRunnerProcess
                        Write-Log ('managed_runner_recovery=' + (($null -ne $managedRunner).ToString().ToLowerInvariant()))
                    }
                }
            }
            catch {
                Write-Log ('watchdog_iteration_error=' + $_.Exception.GetType().Name)
                if ($null -ne $managedRunner) {
                    # Do not kill a child in the generic error path. A probe or
                    # bookkeeping error is not proof that Runner.Worker is idle.
                    try { $managedRunner.Dispose() } catch { }
                    $managedRunner = $null
                }
                $managedMissingListenerProbes = 0
            }
            Start-Sleep -Seconds 15
        }
    }
    finally {
        if ($null -ne $managedRunner) {
            try {
                if (-not $managedRunner.HasExited) { $managedRunner.Kill() }
            }
            catch { }
            try { $managedRunner.Dispose() } catch { }
        }
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

Stop-PreviousUserWatchdogs
Start-Sleep -Seconds 1

$psi = New-Object Diagnostics.ProcessStartInfo
$psi.FileName = 'powershell.exe'
$psi.Arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $stableScript + '" -Mode Watch'
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$psi.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
$proc = New-Object Diagnostics.Process
$proc.StartInfo = $psi
if (-not $proc.Start()) { throw 'Unable to start user-context watchdog.' }
$proc.Dispose()

Start-Sleep -Seconds 10
$listener = Test-Listener
Write-Evidence -Decision $(if ($listener) { 'USER_CONTEXT_MANAGED_CHILD_LIVENESS_SELF_HEAL_ACTIVE' } else { 'WATCHDOG_STARTED_LISTENER_NOT_YET_OBSERVED' }) -ListenerObserved $listener
if (-not $listener) { throw 'Watchdog started but NEXUS-BYBIT-WSL listener was not observed.' }

Write-Host 'bybit_wsl_user_startup_recovery=PASS'
Write-Host "startup_path=$startupVbs"
Write-Host "watchdog_path=$stableScript"
Write-Host ('watchdog_generation=' + $watchdogGeneration)
Write-Host 'watchdog_owns_wsl_child=true'
Write-Host 'managed_child_liveness_probe=true'
Write-Host ('missing_listener_recycle_after_probes=' + $managedChildMissingListenerThreshold)
Write-Host 'stale_idle_listener_recycle=true'
Write-Host 'active_worker_interrupt_allowed=false'
Write-Host 'unknown_probe_interrupt_allowed=false'
Write-Host ('wsl_call_timeout_seconds=' + [int]($wslTimeoutMilliseconds / 1000))
Write-Host 'administrator_required=false'
Write-Host 'task_scheduler_used=false'
Write-Host 'runner_registration_modified=false'
Write-Host 'windows_acl_modified=false'
Write-Host 'live_trading_authority_changed=false'
Write-Host 'popup_launcher_used=false'
exit 0
