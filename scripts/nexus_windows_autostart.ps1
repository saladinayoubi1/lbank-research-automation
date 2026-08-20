[CmdletBinding()]
param(
    [ValidateSet('Install','Uninstall','Status','RunDaemon')]
    [string]$Mode = 'Status',
    [string]$RepoRoot = (Get-Location).Path
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$TaskName = 'NEXUS-ZeroTouch-Autopilot'
$ExpectedRepo = 'saladinayoubi1/lbank-research-automation'
$StateRoot = Join-Path $env:LOCALAPPDATA 'NEXUS\Autopilot'
$LogPath = Join-Path $StateRoot 'autopilot.log'
$SupervisorPidPath = Join-Path $StateRoot 'local-node-supervisor.pid'
$Phase7StateRoot = Join-Path $env:LOCALAPPDATA 'NEXUS\Phase7'
$Phase7HelperRelative = 'scripts\phase7_offline_laptop.ps1'
$SupervisorRelative = 'local_node_supervisor.py'

function Ensure-StateRoot {
    New-Item -ItemType Directory -Force -Path $StateRoot | Out-Null
}

function Write-Log([string]$Message) {
    Ensure-StateRoot
    if (Test-Path -LiteralPath $LogPath -PathType Leaf) {
        try {
            $item = Get-Item -LiteralPath $LogPath
            if ($item.Length -gt 5MB) {
                $old = $LogPath + '.1'
                Remove-Item -LiteralPath $old -Force -ErrorAction SilentlyContinue
                Move-Item -LiteralPath $LogPath -Destination $old -Force
            }
        } catch { }
    }
    $stamp = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
    Add-Content -LiteralPath $LogPath -Encoding UTF8 -Value "[$stamp] $Message"
}

function Resolve-RepoRoot {
    $root = (Resolve-Path -LiteralPath $RepoRoot).Path
    $git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $git) { throw 'git is required' }
    $top = (& $git.Source -C $root rev-parse --show-toplevel 2>$null).Trim()
    if (-not $top) { throw 'RepoRoot is not a git repository' }
    if ((Resolve-Path -LiteralPath $top).Path -ne $root) { throw 'RepoRoot must be the repository root' }
    $remote = (& $git.Source -C $root remote get-url origin 2>$null).Trim()
    if ($remote -notmatch 'saladinayoubi1[/\\]lbank-research-automation(?:\.git)?$') {
        throw "repository must remain $ExpectedRepo"
    }
    return $root
}

function Ensure-LocalVenv([string]$Root) {
    $venvPython = Join-Path $Root '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) { return $venvPython }

    $python = Get-Command python -ErrorAction SilentlyContinue
    $venvArgs = @('-m','venv',(Join-Path $Root '.venv'))
    if ($python) {
        & $python.Source @venvArgs
    } else {
        $py = Get-Command py -ErrorAction SilentlyContinue
        if (-not $py) { throw 'Python 3 is required for first-time NEXUS autostart installation' }
        & $py.Source -3 @venvArgs
    }
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        throw 'failed to create .venv for NEXUS autostart'
    }
    & $venvPython -m pip install -r (Join-Path $Root 'requirements-dev.lock')
    if ($LASTEXITCODE -ne 0) { throw 'failed to install locked NEXUS dependencies' }
    & $venvPython -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'NEXUS dependency consistency check failed' }
    return $venvPython
}

function Get-PowerShellExe {
    $candidate = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    $cmd = Get-Command powershell.exe -ErrorAction Stop
    return $cmd.Source
}

function Test-TcpTarget([string]$HostName, [int]$Port, [int]$TimeoutMs = 1500) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) { return $false }
        $client.EndConnect($async)
        return $true
    }
    catch { return $false }
    finally { $client.Close() }
}

function Get-NetworkState {
    $github = Test-TcpTarget 'api.github.com' 443
    $secondary = Test-TcpTarget '1.1.1.1' 443
    return [ordered]@{
        github_reachable = $github
        secondary_reachable = $secondary
        internet_unavailable = (-not $github -and -not $secondary)
    }
}

function Get-ActivePhase7Sessions([string]$Root) {
    if (-not (Test-Path -LiteralPath $Phase7StateRoot -PathType Container)) { return @() }
    $active = @()
    foreach ($file in Get-ChildItem -LiteralPath $Phase7StateRoot -Filter session.json -File -Recurse -ErrorAction SilentlyContinue) {
        try {
            $session = Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json
            if ($session.schema_version -ne 'nexus.phase7-local-session.v1') { continue }
            if ($session.repository -ne $ExpectedRepo) { continue }
            if ($session.completed -eq $true) { continue }
            if ((Resolve-Path -LiteralPath $session.repo_root).Path -ne $Root) { continue }
            $active += [pscustomobject]@{ Path=$file.FullName; Data=$session }
        }
        catch {
            Write-Log "phase7_session_read_rejected path=$($file.FullName) error=$($_.Exception.Message)"
        }
    }
    return @($active)
}

function Invoke-Phase7Mode([string]$Root, [string]$PhaseMode, [string]$SessionId) {
    $helper = Join-Path $Root $Phase7HelperRelative
    if (-not (Test-Path -LiteralPath $helper -PathType Leaf)) {
        Write-Log "phase7_helper_missing path=$helper"
        return $false
    }
    $ps = Get-PowerShellExe
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $ps
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $psi.WorkingDirectory = $Root
    $psi.Arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$helper`" -Mode $PhaseMode -SessionId `"$SessionId`" -RepoRoot `"$Root`""
    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    [void]$proc.Start()
    $stdout = $proc.StandardOutput.ReadToEnd()
    $stderr = $proc.StandardError.ReadToEnd()
    $proc.WaitForExit()
    if ($stdout) { Write-Log "phase7_$($PhaseMode)_stdout=$($stdout -replace '[\r\n]+',' | ')" }
    if ($stderr) { Write-Log "phase7_$($PhaseMode)_stderr=$($stderr -replace '[\r\n]+',' | ')" }
    Write-Log "phase7_mode=$PhaseMode session=$SessionId exit_code=$($proc.ExitCode)"
    return ($proc.ExitCode -eq 0)
}

function Test-SupervisorCommandLine([string]$CommandLine, [string]$Root) {
    if (-not $CommandLine) { return $false }
    $expectedScript = [IO.Path]::GetFullPath((Join-Path $Root $SupervisorRelative))
    return $CommandLine.IndexOf($expectedScript, [StringComparison]::OrdinalIgnoreCase) -ge 0
}

function Get-SupervisorProcess([string]$Root) {
    if (Test-Path -LiteralPath $SupervisorPidPath -PathType Leaf) {
        try {
            $pidValue = [int](Get-Content -LiteralPath $SupervisorPidPath -Raw)
            $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
            if ($proc) {
                $wmi = Get-CimInstance Win32_Process -Filter "ProcessId=$pidValue" -ErrorAction SilentlyContinue
                if ($wmi -and (Test-SupervisorCommandLine ([string]$wmi.CommandLine) $Root)) { return $proc }
            }
        } catch { }
    }

    try {
        foreach ($row in Get-CimInstance Win32_Process -ErrorAction SilentlyContinue) {
            if ($row.CommandLine -and (Test-SupervisorCommandLine ([string]$row.CommandLine) $Root)) {
                $proc = Get-Process -Id $row.ProcessId -ErrorAction SilentlyContinue
                if ($proc) {
                    Set-Content -LiteralPath $SupervisorPidPath -Encoding ASCII -Value $proc.Id
                    return $proc
                }
            }
        }
    } catch { }
    return $null
}

function Start-LocalSupervisor([string]$Root) {
    $existing = Get-SupervisorProcess $Root
    if ($existing) { return $existing }

    $python = Ensure-LocalVenv $Root
    $pythonw = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
    $exe = if (Test-Path -LiteralPath $pythonw -PathType Leaf) { $pythonw } else { $python }
    $script = [IO.Path]::GetFullPath((Join-Path $Root $SupervisorRelative))
    if (-not (Test-Path -LiteralPath $script -PathType Leaf)) { throw 'local_node_supervisor.py is missing' }

    $quotedScript = '"' + $script.Replace('"','\"') + '"'
    $proc = Start-Process -FilePath $exe -ArgumentList @($quotedScript,'--poll-seconds','20','--with-dashboard') -WorkingDirectory $Root -WindowStyle Hidden -PassThru
    Set-Content -LiteralPath $SupervisorPidPath -Encoding ASCII -Value $proc.Id
    Write-Log "local_supervisor_started pid=$($proc.Id) script=$script"
    return $proc
}

function Handle-Phase7([string]$Root) {
    $sessions = @(Get-ActivePhase7Sessions $Root)
    if ($sessions.Count -eq 0) { return }
    if ($sessions.Count -gt 1) {
        Write-Log "phase7_fail_closed_multiple_active_sessions count=$($sessions.Count)"
        return
    }

    $session = $sessions[0].Data
    $id = [string]$session.session_id
    if (-not $id) { return }

    if (-not $session.offline_result) {
        try {
            $boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime()
            $prepared = [DateTime]::Parse([string]$session.prepared_at).ToUniversalTime()
            if ($boot -le $prepared) {
                Write-Log "phase7_waiting_for_required_reboot session=$id"
                return
            }
        }
        catch {
            Write-Log "phase7_reboot_check_rejected session=$id error=$($_.Exception.Message)"
            return
        }

        $network = Get-NetworkState
        if ($network.internet_unavailable -eq $true) {
            Write-Log "phase7_offline_conditions_satisfied session=$id"
            [void](Invoke-Phase7Mode $Root 'ExecuteOffline' $id)
        } else {
            Write-Log "phase7_waiting_for_full_disconnect session=$id"
        }
        return
    }

    if ($session.return_pr) {
        Write-Log "phase7_return_pr_already_exists_no_duplicate_submit session=$id pr=$($session.return_pr)"
        return
    }

    $network = Get-NetworkState
    if ($network.github_reachable -eq $true) {
        Write-Log "phase7_online_return_conditions_satisfied session=$id"
        [void](Invoke-Phase7Mode $Root 'SubmitReturn' $id)
    } else {
        Write-Log "phase7_waiting_for_github_reconnect session=$id"
    }
}

function Install-Autostart {
    if ($env:OS -ne 'Windows_NT') { throw 'NEXUS Windows autostart can only be installed on Windows' }
    $root = Resolve-RepoRoot
    Ensure-StateRoot

    # Persistence must not depend on first-run Python/venv hydration. The daemon owns
    # prerequisite reconciliation and retries supervisor startup without losing the task.
    $script = (Resolve-Path -LiteralPath $PSCommandPath).Path
    $ps = Get-PowerShellExe
    $user = "$env:USERDOMAIN\$env:USERNAME"
    $taskArgs = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`" -Mode RunDaemon -RepoRoot `"$root`""
    $action = New-ScheduledTaskAction -Execute $ps -Argument $taskArgs -WorkingDirectory $root
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
    $task = New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Starts the NEXUS local supervisor and safely resumes Phase 7 offline handoff after Windows logon.'
    Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
    Start-ScheduledTask -TaskName $TaskName
    Write-Log "autostart_installed task=$TaskName user=$user repo=$root runtime_hydration=daemon_managed"
    Write-Host "NEXUS zero-touch autostart installed: $TaskName"
}

function Uninstall-Autostart {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }
    Write-Log "autostart_uninstalled task=$TaskName"
    Write-Host "NEXUS zero-touch autostart removed: $TaskName"
}

function Show-Status {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) {
        Write-Host 'NEXUS zero-touch autostart: NOT INSTALLED'
        return
    }
    $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue
    Write-Host "NEXUS zero-touch autostart: $($task.State)"
    if ($info) {
        Write-Host "LastRunTime: $($info.LastRunTime)"
        Write-Host "LastTaskResult: $($info.LastTaskResult)"
    }
    Write-Host "Log: $LogPath"
}

function Run-Daemon {
    if ($env:OS -ne 'Windows_NT') { throw 'RunDaemon is Windows-only' }
    $root = Resolve-RepoRoot
    Ensure-StateRoot

    $created = $false
    $mutexName = 'Local\NEXUS-ZeroTouch-Autopilot-' + $env:USERNAME
    $mutex = New-Object System.Threading.Mutex($true, $mutexName, [ref]$created)
    if (-not $created) {
        Write-Log 'duplicate_daemon_rejected'
        return
    }

    Write-Log "daemon_started repo=$root pid=$PID"
    try {
        $lastPhase7 = [DateTime]::MinValue
        while ($true) {
            try {
                $supervisor = Get-SupervisorProcess $root
                if (-not $supervisor) {
                    [void](Start-LocalSupervisor $root)
                }
            }
            catch {
                Write-Log "local_supervisor_start_failed error=$($_.Exception.Message)"
            }

            if (([DateTime]::UtcNow - $lastPhase7).TotalSeconds -ge 30) {
                try { Handle-Phase7 $root }
                catch { Write-Log "phase7_autopilot_error=$($_.Exception.Message)" }
                $lastPhase7 = [DateTime]::UtcNow
            }
            Start-Sleep -Seconds 10
        }
    }
    finally {
        try { $mutex.ReleaseMutex() } catch { }
        $mutex.Dispose()
    }
}

switch ($Mode) {
    'Install' { Install-Autostart }
    'Uninstall' { Uninstall-Autostart }
    'Status' { Show-Status }
    'RunDaemon' { Run-Daemon }
    default { throw 'unsupported mode' }
}
