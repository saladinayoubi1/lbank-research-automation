[CmdletBinding()]
param(
    [ValidateSet('Install','Watch')]
    [string]$Mode = 'Install',
    [string]$Distribution = 'Ubuntu',
    [string]$RunnerRoot = '/opt/nexus-bybit-runner',
    [string]$ExpectedRunnerName = 'NEXUS-BYBIT-WSL',
    [int]$Generation = 9
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

if ($Distribution -ne 'Ubuntu') { throw 'Distribution must remain pinned to Ubuntu.' }
if ($RunnerRoot -ne '/opt/nexus-bybit-runner') { throw 'RunnerRoot must remain pinned.' }
if ($ExpectedRunnerName -ne 'NEXUS-BYBIT-WSL') { throw 'ExpectedRunnerName must remain pinned.' }
if ($Generation -ne 9) { throw 'Generation must remain pinned to the reviewed watchdog generation.' }

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
$wslTimeoutMilliseconds = 30000
$watchdogGeneration = $Generation
$managedRunnerLog = '/tmp/nexus-bybit-runner.log'
$managedChildMissingListenerThreshold = 3

function ConvertTo-WslBashWrapper {
    param([Parameter(Mandatory = $true)][string]$Command)

    # WSL1 on the Lenovo host can block indefinitely when a bash script is sent
    # through redirected stdin. Carry the exact UTF-8 script as base64 in argv;
    # this is the same transport already proven by the earlier physical wake.
    $normalizedCommand = $Command.Replace("`r`n", "`n").Replace("`r", "`n")
    $encodedCommand = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($normalizedCommand))
    return "printf '%s' '$encodedCommand' | base64 -d | bash"
}

function New-WslProcessStartInfo {
    param([Parameter(Mandatory = $true)][string]$Command)

    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = $wsl
    $wrappedCommand = ConvertTo-WslBashWrapper -Command $Command
    $psi.Arguments = '-d ' + $Distribution + ' -u root -- bash -lc "' + $wrappedCommand + '"'
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
    return $psi
}

function Invoke-WslNative {
    param([Parameter(Mandatory = $true)][string]$Command)

    # All probes are bounded and encode state solely in their exit code. WSL1
    # on the Lenovo host has now hung with both redirected stdin and redirected
    # stdout/stderr, while its unredirected long-lived launch was proven. Keep
    # every standard stream unredirected to avoid that interop failure mode.
    $psi = New-WslProcessStartInfo -Command $Command
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
        $exitCode = [int]$proc.ExitCode
        $detail = if ($exitCode -eq 0) { '' } else { 'wsl_exit_' + $exitCode }
        return [ordered]@{ exit_code = $exitCode; output = $detail }
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
    $command = @'
test -x '__RUNNER_ROOT__/run.sh' || exit 10
test -f '__RUNNER_ROOT__/.runner' || exit 11
found=0
while IFS= read -r line; do
  case "$line" in
    *'"agentName"'*'__EXPECTED_RUNNER_NAME__'*) found=1 ;;
  esac
done < '__RUNNER_ROOT__/.runner'
if [ "$found" -ne 1 ]; then exit 12; fi
exit 0
'@
    $command = $command.Replace('__RUNNER_ROOT__', $RunnerRoot).Replace('__EXPECTED_RUNNER_NAME__', $ExpectedRunnerName)
    $probe = Invoke-WslNative $command
    if ($probe.exit_code -ne 0) {
        $detail = switch ([int]$probe.exit_code) {
            10 { 'run_sh_missing' }
            11 { 'runner_config_missing' }
            12 { 'runner_name_mismatch' }
            default { [string]$probe.output }
        }
        throw ('Existing NEXUS-BYBIT-WSL registration could not be verified without mutation; ' +
            'this script will not create or replace it. probe_exit=' + $probe.exit_code +
            ' detail=' + $detail)
    }
}

function Get-RunnerProcessState {
    # Read exact argv[0] values directly from procfs. The WSL1 host has shown
    # intermittent failures launching external userland tools such as pgrep, so
    # runner liveness must not depend on those tools. The probe remains bounded
    # by Invoke-WslNative and fails closed when procfs itself cannot be read.
    $command = @'
self_exe=''
if ! IFS= read -r -d '' self_exe < /proc/self/cmdline; then
  exit 20
fi
listener=0
worker=0
for proc in /proc/[0-9]*; do
  [ -r "$proc/cmdline" ] || continue
  exe=''
  IFS= read -r -d '' exe < "$proc/cmdline" || continue
  case "$exe" in
    '__RUNNER_ROOT__/bin/Runner.Listener') listener=1 ;;
    '__RUNNER_ROOT__/bin/Runner.Worker') worker=1 ;;
  esac
done
if [ "$listener" -eq 1 ] && [ "$worker" -eq 1 ]; then exit 3; fi
if [ "$listener" -eq 1 ]; then exit 1; fi
if [ "$worker" -eq 1 ]; then exit 2; fi
exit 0
'@
    $command = $command.Replace('__RUNNER_ROOT__', $RunnerRoot)
    $probe = Invoke-WslNative $command
    if ($probe.exit_code -eq 124) {
        Write-Log 'runner_process_probe_timeout=true'
        return [ordered]@{ known = $false; listener = $false; worker = $false }
    }
    if ([int]$probe.exit_code -notin @(0,1,2,3)) {
        Write-Log ('runner_process_probe_failed=' + $probe.exit_code)
        return [ordered]@{ known = $false; listener = $false; worker = $false }
    }
    $listenerSeen = ([int]$probe.exit_code -in @(1,3))
    $workerSeen = ([int]$probe.exit_code -in @(2,3))
    return [ordered]@{
        known = $true
        listener = $listenerSeen
        worker = $workerSeen
    }
}

function Test-Listener {
    $state = Get-RunnerProcessState
    return ($state.known -and $state.listener)
}

function Stop-IdleExternalListener {
    # Never recycle a listener while a Runner.Worker is active. Use exact
    # procfs argv[0] matching and re-check Worker immediately before each kill
    # so a Worker that appears after the first scan still blocks interruption.
    $command = @'
self_exe=''
if ! IFS= read -r -d '' self_exe < /proc/self/cmdline; then
  exit 23
fi
worker_present() {
  for proc in /proc/[0-9]*; do
    [ -r "$proc/cmdline" ] || continue
    exe=''
    IFS= read -r -d '' exe < "$proc/cmdline" || continue
    case "$exe" in
      '__RUNNER_ROOT__/bin/Runner.Worker') return 0 ;;
    esac
  done
  return 1
}
if worker_present; then
  exit 3
fi
for proc in /proc/[0-9]*; do
  [ -r "$proc/cmdline" ] || continue
  exe=''
  IFS= read -r -d '' exe < "$proc/cmdline" || continue
  case "$exe" in
    '__RUNNER_ROOT__/bin/Runner.Listener') ;;
    *) continue ;;
  esac
  if worker_present; then
    exit 3
  fi
  pid=${proc##*/}
  kill -TERM "$pid" >/dev/null 2>&1 || exit 24
done
exit 0
'@
    $command = $command.Replace('__RUNNER_ROOT__', $RunnerRoot)
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
    $psi = New-WslProcessStartInfo -Command $command
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

function Get-WatchdogMutexName {
    return 'Local\NEXUS-Bybit-WSL-Watchdog-v' + $watchdogGeneration + '-' + $sid
}

function Test-UserWatchdogActive {
    # Win32_Process/WMI is not a reliable inventory source on the Lenovo host.
    # The watchdog already owns this named mutex for its entire lifetime, so
    # mutex ownership is the exact same-user, same-generation liveness proof.
    $createdNew = $false
    $mutex = New-Object Threading.Mutex($false, (Get-WatchdogMutexName), [ref]$createdNew)
    try {
        if ($createdNew) { return $false }
        $acquired = $false
        try {
            $acquired = $mutex.WaitOne(0)
        }
        catch [Threading.AbandonedMutexException] {
            $acquired = $true
        }
        if ($acquired) {
            try { $mutex.ReleaseMutex() } catch { }
            return $false
        }
        return $true
    }
    finally {
        $mutex.Dispose()
    }
}

function Write-Evidence([string]$Decision, [bool]$ListenerObserved) {
    New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
    $payload = [ordered]@{
        schema_version = 7
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
        wsl_command_transport = 'BASE64_ARGV'
        wsl_standard_stream_redirection = $false
        administrator_required = $false
        task_scheduler_used = $false
        runner_registration_modified = $false
        runner_credentials_modified = $false
        windows_acl_modified = $false
        windows_service_modified = $false
        private_exchange_credentials_used = $false
        live_trading_authority_changed = $false
        popup_launcher_used = $false
        actions_process_tracking_detached = $true
    }
    $payload | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $evidencePath -Encoding UTF8
}

function Write-RecoverySuccessOutput([bool]$ReusedCurrentWatchdog) {
    Write-Host 'bybit_wsl_user_startup_recovery=PASS'
    Write-Host "startup_path=$startupVbs"
    Write-Host "watchdog_path=$stableScript"
    Write-Host ('watchdog_generation=' + $watchdogGeneration)
    Write-Host ('current_watchdog_reused=' + $ReusedCurrentWatchdog.ToString().ToLowerInvariant())
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
    Write-Host 'actions_process_tracking_detached=true'
}

function Run-Watchdog {
    Test-ExistingRegistration
    New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
    $createdNew = $false
    $mutexName = Get-WatchdogMutexName
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
$stableWasCurrent = $false
if (Test-Path -LiteralPath $stableScript -PathType Leaf) {
    $sourceHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
    $stableHash = (Get-FileHash -LiteralPath $stableScript -Algorithm SHA256).Hash
    $stableWasCurrent = ($sourceHash -eq $stableHash)
}
if (-not $source.Equals([IO.Path]::GetFullPath($stableScript), [StringComparison]::OrdinalIgnoreCase) -and
    -not $stableWasCurrent) {
    Copy-Item -LiteralPath $source -Destination $stableScript -Force
}

$watchCommand = 'powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $stableScript + '" -Mode Watch -Generation ' + $watchdogGeneration
$escapedWatchCommand = $watchCommand.Replace('"', '""')
$vbs = 'Set shell = CreateObject("WScript.Shell")' + "`r`n" + 'shell.Run "' + $escapedWatchCommand + '", 0, False' + "`r`n"
[IO.File]::WriteAllText($startupVbs, $vbs, (New-Object Text.ASCIIEncoding))
if (Test-Path -LiteralPath $legacyStartupCmd -PathType Leaf) {
    Remove-Item -LiteralPath $legacyStartupCmd -Force
}

$watchdogActive = Test-UserWatchdogActive
if ($watchdogActive) {
    $listener = Test-Listener
    Write-Evidence -Decision $(if ($listener) { 'USER_CONTEXT_MANAGED_CHILD_LIVENESS_SELF_HEAL_ACTIVE' } else { 'CURRENT_WATCHDOG_RUNNING_LISTENER_NOT_OBSERVED' }) -ListenerObserved $listener
    if (-not $listener) { throw 'Current detached watchdog is running but NEXUS-BYBIT-WSL listener was not observed.' }
    if (-not $stableWasCurrent) {
        Write-Log 'watchdog_upgrade_deferred_until_next_start=true'
    }
    Write-RecoverySuccessOutput -ReusedCurrentWatchdog $true
    exit 0
}


$psi = New-Object Diagnostics.ProcessStartInfo
$psi.FileName = 'powershell.exe'
$psi.Arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $stableScript + '" -Mode Watch -Generation ' + $watchdogGeneration
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$psi.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
$proc = New-Object Diagnostics.Process
$proc.StartInfo = $psi
$previousTrackingId = [Environment]::GetEnvironmentVariable('RUNNER_TRACKING_ID', 'Process')
[Environment]::SetEnvironmentVariable('RUNNER_TRACKING_ID', $null, 'Process')
try {
    if (-not $proc.Start()) { throw 'Unable to start user-context watchdog.' }
}
finally {
    [Environment]::SetEnvironmentVariable('RUNNER_TRACKING_ID', $previousTrackingId, 'Process')
}
$proc.Dispose()

Start-Sleep -Seconds 10
$listener = Test-Listener
Write-Evidence -Decision $(if ($listener) { 'USER_CONTEXT_MANAGED_CHILD_LIVENESS_SELF_HEAL_ACTIVE' } else { 'WATCHDOG_STARTED_LISTENER_NOT_YET_OBSERVED' }) -ListenerObserved $listener
if (-not $listener) { throw 'Watchdog started but NEXUS-BYBIT-WSL listener was not observed.' }

Write-RecoverySuccessOutput -ReusedCurrentWatchdog $false
exit 0
