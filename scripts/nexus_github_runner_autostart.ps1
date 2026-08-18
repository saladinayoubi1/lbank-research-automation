[CmdletBinding()]
param(
    [ValidateSet('Install','Uninstall','Status','RunDaemon')]
    [string]$Mode = 'Status',
    [string]$RepoRoot = (Get-Location).Path
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$TaskName = 'NEXUS-GitHub-Runner-Autostart'
$ExpectedRepo = 'saladinayoubi1/lbank-research-automation'
$ExpectedGitHubUrl = 'https://github.com/saladinayoubi1/lbank-research-automation'
$StateRoot = Join-Path $env:LOCALAPPDATA 'NEXUS\RunnerAutostart'
$LogPath = Join-Path $StateRoot 'runner-autostart.log'
$RunnerRootStatePath = Join-Path $StateRoot 'runner-root.txt'
$ListenerPidPath = Join-Path $StateRoot 'runner-listener.pid'

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

function Normalize-GitHubUrl([string]$Value) {
    if (-not $Value) { return '' }
    return $Value.Trim().TrimEnd('/').ToLowerInvariant()
}

function Read-RunnerConfig([string]$Root) {
    try {
        $fullRoot = (Resolve-Path -LiteralPath $Root -ErrorAction Stop).Path
        $settingsPath = Join-Path $fullRoot '.runner'
        $credentialsPath = Join-Path $fullRoot '.credentials'
        $runCmd = Join-Path $fullRoot 'run.cmd'
        $listener = Join-Path $fullRoot 'bin\Runner.Listener.exe'
        if (-not (Test-Path -LiteralPath $settingsPath -PathType Leaf)) { return $null }
        if (-not (Test-Path -LiteralPath $credentialsPath -PathType Leaf)) { return $null }
        if (-not (Test-Path -LiteralPath $runCmd -PathType Leaf)) { return $null }
        if (-not (Test-Path -LiteralPath $listener -PathType Leaf)) { return $null }
        $config = Get-Content -LiteralPath $settingsPath -Raw -ErrorAction Stop | ConvertFrom-Json
        $urlProperty = $config.PSObject.Properties['gitHubUrl']
        if (-not $urlProperty -or -not $urlProperty.Value) { return $null }
        $url = Normalize-GitHubUrl ([string]$urlProperty.Value)
        if ($url -ne (Normalize-GitHubUrl $ExpectedGitHubUrl)) { return $null }
        $nameProperty = $config.PSObject.Properties['agentName']
        $agentName = if ($nameProperty) { [string]$nameProperty.Value } else { '' }
        return [pscustomobject]@{
            Root = $fullRoot
            GitHubUrl = [string]$urlProperty.Value
            AgentName = $agentName
            RunCmd = $runCmd
            Listener = $listener
        }
    }
    catch { return $null }
}

function Convert-ExecutableToRunnerRoot([string]$ExecutablePath) {
    if (-not $ExecutablePath) { return $null }
    try {
        $full = [IO.Path]::GetFullPath($ExecutablePath.Trim('"'))
        $bin = Split-Path -Parent $full
        if ((Split-Path -Leaf $bin) -ne 'bin') { return $null }
        return (Split-Path -Parent $bin)
    }
    catch { return $null }
}

function Get-ServiceExecutable([string]$PathName) {
    if (-not $PathName) { return $null }
    $value = $PathName.Trim()
    $quoted = [regex]::Match($value, '^"([^"]+\.exe)"')
    if ($quoted.Success) { return $quoted.Groups[1].Value }
    $plain = [regex]::Match($value, '^([^\s]+\.exe)')
    if ($plain.Success) { return $plain.Groups[1].Value }
    return $null
}

function Add-Candidate([System.Collections.Generic.List[string]]$List, [string]$Path) {
    if (-not $Path) { return }
    try {
        if (Test-Path -LiteralPath $Path -PathType Container) {
            $full = (Resolve-Path -LiteralPath $Path).Path
            if (-not $List.Contains($full)) { [void]$List.Add($full) }
        }
    }
    catch { }
}

function Get-RunnerServices {
    $services = @()
    try {
        $services = @(Get-CimInstance Win32_Service -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'actions.runner.*' })
    }
    catch { }
    return @($services)
}

function Get-CandidateRunnerRoots([string]$Root) {
    $candidates = New-Object 'System.Collections.Generic.List[string]'

    if (Test-Path -LiteralPath $RunnerRootStatePath -PathType Leaf) {
        try { Add-Candidate $candidates ((Get-Content -LiteralPath $RunnerRootStatePath -Raw).Trim()) } catch { }
    }

    foreach ($svc in Get-RunnerServices) {
        $exe = Get-ServiceExecutable ([string]$svc.PathName)
        $candidate = Convert-ExecutableToRunnerRoot $exe
        Add-Candidate $candidates $candidate
    }

    try {
        foreach ($process in Get-CimInstance Win32_Process -Filter "Name='Runner.Listener.exe'" -ErrorAction SilentlyContinue) {
            $candidate = Convert-ExecutableToRunnerRoot ([string]$process.ExecutablePath)
            Add-Candidate $candidates $candidate
        }
    }
    catch { }

    $known = @(
        (Join-Path $env:SystemDrive 'actions-runner'),
        (Join-Path $env:USERPROFILE 'actions-runner'),
        (Join-Path $env:USERPROFILE 'Desktop\actions-runner'),
        (Join-Path $env:USERPROFILE 'Downloads\actions-runner'),
        (Join-Path $env:LOCALAPPDATA 'NEXUS\actions-runner'),
        (Join-Path $Root 'actions-runner'),
        (Join-Path (Split-Path -Parent $Root) 'actions-runner')
    )
    foreach ($path in $known) { Add-Candidate $candidates $path }

    foreach ($parent in @($env:SystemDrive + '\', $env:USERPROFILE, (Join-Path $env:USERPROFILE 'Desktop'), (Join-Path $env:USERPROFILE 'Downloads'))) {
        if (-not (Test-Path -LiteralPath $parent -PathType Container)) { continue }
        try {
            foreach ($dir in Get-ChildItem -LiteralPath $parent -Directory -Filter 'actions-runner*' -ErrorAction SilentlyContinue) {
                Add-Candidate $candidates $dir.FullName
            }
        }
        catch { }
    }

    return @($candidates)
}

function Find-RunnerInstallation([string]$Root) {
    $valid = @()
    foreach ($candidate in Get-CandidateRunnerRoots $Root) {
        $config = Read-RunnerConfig $candidate
        if ($config) { $valid += $config }
    }
    $unique = @($valid | Group-Object Root | ForEach-Object { $_.Group[0] })
    if ($unique.Count -eq 0) { return $null }
    if ($unique.Count -gt 1) {
        Write-Log "runner_fail_closed_multiple_configured_installations count=$($unique.Count)"
        return $null
    }
    Ensure-StateRoot
    Set-Content -LiteralPath $RunnerRootStatePath -Encoding UTF8 -Value $unique[0].Root
    return $unique[0]
}

function Get-ServiceForRunner([pscustomobject]$Runner) {
    $matches = @()
    foreach ($svc in Get-RunnerServices) {
        $exe = Get-ServiceExecutable ([string]$svc.PathName)
        $candidate = Convert-ExecutableToRunnerRoot $exe
        if (-not $candidate) { continue }
        try {
            if ((Resolve-Path -LiteralPath $candidate).Path -eq $Runner.Root) { $matches += $svc }
        }
        catch { }
    }
    if ($matches.Count -gt 1) {
        Write-Log "runner_fail_closed_multiple_services root=$($Runner.Root) count=$($matches.Count)"
        return $null
    }
    if ($matches.Count -eq 1) { return $matches[0] }
    return $null
}

function Get-ListenerProcess([pscustomobject]$Runner) {
    if (Test-Path -LiteralPath $ListenerPidPath -PathType Leaf) {
        try {
            $pidValue = [int](Get-Content -LiteralPath $ListenerPidPath -Raw)
            $row = Get-CimInstance Win32_Process -Filter "ProcessId=$pidValue" -ErrorAction SilentlyContinue
            if ($row -and $row.Name -eq 'Runner.Listener.exe') {
                $root = Convert-ExecutableToRunnerRoot ([string]$row.ExecutablePath)
                if ($root -and (Resolve-Path -LiteralPath $root).Path -eq $Runner.Root) {
                    return (Get-Process -Id $pidValue -ErrorAction SilentlyContinue)
                }
            }
        }
        catch { }
    }

    try {
        foreach ($row in Get-CimInstance Win32_Process -Filter "Name='Runner.Listener.exe'" -ErrorAction SilentlyContinue) {
            $root = Convert-ExecutableToRunnerRoot ([string]$row.ExecutablePath)
            if (-not $root) { continue }
            if ((Resolve-Path -LiteralPath $root).Path -eq $Runner.Root) {
                Set-Content -LiteralPath $ListenerPidPath -Encoding ASCII -Value $row.ProcessId
                return (Get-Process -Id $row.ProcessId -ErrorAction SilentlyContinue)
            }
        }
    }
    catch { }
    return $null
}

function Start-InteractiveRunner([pscustomobject]$Runner) {
    $existing = Get-ListenerProcess $Runner
    if ($existing) { return $true }

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $env:ComSpec
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.WorkingDirectory = $Runner.Root
    $psi.Arguments = '/d /s /c ""' + $Runner.RunCmd + '""'
    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    [void]$proc.Start()
    Write-Log "runner_listener_start_requested root=$($Runner.Root) bootstrap_pid=$($proc.Id)"
    Start-Sleep -Seconds 5
    $listener = Get-ListenerProcess $Runner
    if ($listener) {
        Write-Log "runner_listener_running root=$($Runner.Root) pid=$($listener.Id) agent=$($Runner.AgentName)"
        return $true
    }
    Write-Log "runner_listener_start_pending root=$($Runner.Root)"
    return $false
}

function Reconcile-Runner([string]$Root, [ref]$LastStartAttempt) {
    $runner = Find-RunnerInstallation $Root
    if (-not $runner) {
        Write-Log 'runner_unavailable_no_unique_configured_installation'
        return 'UNAVAILABLE'
    }

    $service = Get-ServiceForRunner $runner
    if ($service) {
        if ([string]$service.State -eq 'Running') {
            Write-Log "runner_service_running service=$($service.Name) start_mode=$($service.StartMode) root=$($runner.Root)"
            return 'SERVICE_RUNNING'
        }
        try {
            Start-Service -Name ([string]$service.Name) -ErrorAction Stop
            Start-Sleep -Seconds 2
            $refreshed = Get-CimInstance Win32_Service -Filter "Name='$($service.Name.Replace("'","''"))'" -ErrorAction SilentlyContinue
            if ($refreshed -and [string]$refreshed.State -eq 'Running') {
                Write-Log "runner_service_started service=$($service.Name) start_mode=$($refreshed.StartMode) root=$($runner.Root)"
                return 'SERVICE_RUNNING'
            }
        }
        catch {
            Write-Log "runner_service_stopped_requires_admin service=$($service.Name) start_mode=$($service.StartMode) error=$($_.Exception.Message)"
        }
        return 'SERVICE_STOPPED'
    }

    $listener = Get-ListenerProcess $runner
    if ($listener) {
        Write-Log "runner_listener_healthy pid=$($listener.Id) root=$($runner.Root) agent=$($runner.AgentName)"
        return 'LISTENER_RUNNING'
    }

    $now = [DateTime]::UtcNow
    if (($now - $LastStartAttempt.Value).TotalSeconds -lt 60) {
        return 'LISTENER_START_COOLDOWN'
    }
    $LastStartAttempt.Value = $now
    if (Start-InteractiveRunner $runner) { return 'LISTENER_RUNNING' }
    return 'LISTENER_STARTING'
}

function Install-Autostart {
    if ($env:OS -ne 'Windows_NT') { throw 'NEXUS GitHub runner autostart can only be installed on Windows' }
    $root = Resolve-RepoRoot
    Ensure-StateRoot
    $runner = Find-RunnerInstallation $root
    if ($runner) {
        Write-Log "runner_installation_detected root=$($runner.Root) agent=$($runner.AgentName)"
    } else {
        Write-Log 'runner_installation_not_detected_task_will_wait_fail_closed'
    }

    $script = (Resolve-Path -LiteralPath $PSCommandPath).Path
    $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if (-not (Test-Path -LiteralPath $powershell -PathType Leaf)) {
        $powershell = (Get-Command powershell.exe -ErrorAction Stop).Source
    }
    $user = "$env:USERDOMAIN\$env:USERNAME"
    $taskArgs = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`" -Mode RunDaemon -RepoRoot `"$root`""
    $action = New-ScheduledTaskAction -Execute $powershell -Argument $taskArgs -WorkingDirectory $root
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
    $task = New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Keeps the configured NEXUS GitHub Actions self-hosted runner listener available after Windows logon without a visible shell.'
    Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
    Start-ScheduledTask -TaskName $TaskName
    Write-Log "runner_autostart_installed task=$TaskName user=$user repo=$root"
    if ($runner) {
        Write-Host "NEXUS GitHub runner autostart installed: $TaskName"
        Write-Host "Runner: $($runner.AgentName) @ $($runner.Root)"
    } else {
        Write-Host "NEXUS GitHub runner autostart installed, but no unique configured runner was found."
    }
}

function Uninstall-Autostart {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }
    Write-Log "runner_autostart_uninstalled task=$TaskName registration_preserved=true"
    Write-Host "NEXUS GitHub runner autostart removed. Runner registration was preserved."
}

function Show-Status {
    $root = Resolve-RepoRoot
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) {
        $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue
        Write-Host "Autostart task: $($task.State)"
        if ($info) {
            Write-Host "LastRunTime: $($info.LastRunTime)"
            Write-Host "LastTaskResult: $($info.LastTaskResult)"
        }
    } else {
        Write-Host 'Autostart task: NOT INSTALLED'
    }

    $runner = Find-RunnerInstallation $root
    if (-not $runner) {
        Write-Host 'GitHub runner: UNAVAILABLE (no unique configured runner bound to this repository)'
        Write-Host "Log: $LogPath"
        return
    }
    $service = Get-ServiceForRunner $runner
    if ($service) {
        Write-Host "GitHub runner: SERVICE $($service.State) / StartMode=$($service.StartMode)"
    } else {
        $listener = Get-ListenerProcess $runner
        if ($listener) { Write-Host "GitHub runner: LISTENER RUNNING (PID $($listener.Id))" }
        else { Write-Host 'GitHub runner: LISTENER STOPPED' }
    }
    Write-Host "Runner root: $($runner.Root)"
    Write-Host "Runner name: $($runner.AgentName)"
    Write-Host "Log: $LogPath"
}

function Run-Daemon {
    if ($env:OS -ne 'Windows_NT') { throw 'RunDaemon is Windows-only' }
    $root = Resolve-RepoRoot
    Ensure-StateRoot
    $created = $false
    $mutexName = 'Local\NEXUS-GitHub-Runner-Autostart-' + $env:USERNAME
    $mutex = New-Object System.Threading.Mutex($true, $mutexName, [ref]$created)
    if (-not $created) {
        Write-Log 'duplicate_runner_daemon_rejected'
        return
    }

    Write-Log "runner_daemon_started repo=$root pid=$PID"
    try {
        $lastStartAttempt = [DateTime]::MinValue
        while ($true) {
            try {
                $status = Reconcile-Runner $root ([ref]$lastStartAttempt)
            }
            catch {
                Write-Log "runner_reconcile_error=$($_.Exception.Message)"
            }
            Start-Sleep -Seconds 15
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
