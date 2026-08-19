[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$SourceSha
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$ExpectedGitHubUrl = 'https://github.com/saladinayoubi1/lbank-research-automation'
$TaskName = 'NEXUS-GitHub-Runner-Autostart'
$StateRoot = Join-Path $env:LOCALAPPDATA 'NEXUS\GuiRunnerBootstrap'
$EvidencePath = Join-Path $StateRoot 'evidence.json'
$LogPath = Join-Path $StateRoot 'bootstrap.log'

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
        contract_version = 'nexus.gui-runner-bootstrap.v1'
        status = $Status
        source_sha = $SourceSha.ToLowerInvariant()
        generated_at = [DateTime]::UtcNow.ToString('o')
        expected_repository = $ExpectedGitHubUrl
        interactive_user = "$env:USERDOMAIN\$env:USERNAME"
        credentials_modified = $false
        runner_registered = $false
        config_cmd_invoked = $false
        live_trading_authority = $false
        paper_only = $true
    }
    foreach ($key in $Extra.Keys) { $payload[$key] = $Extra[$key] }
    $tmp = $EvidencePath + '.tmp'
    $payload | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $tmp -Encoding UTF8
    Move-Item -LiteralPath $tmp -Destination $EvidencePath -Force
    Write-Log "status=$Status source_sha=$($SourceSha.ToLowerInvariant())"
}

function Normalize-GitHubUrl([string]$Value) {
    if (-not $Value) { return '' }
    return $Value.Trim().TrimEnd('/').ToLowerInvariant()
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
        $config = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
        $urlProperty = $config.PSObject.Properties['gitHubUrl']
        if (-not $urlProperty -or -not $urlProperty.Value) { return $null }
        if ((Normalize-GitHubUrl ([string]$urlProperty.Value)) -ne (Normalize-GitHubUrl $ExpectedGitHubUrl)) { return $null }
        $nameProperty = $config.PSObject.Properties['agentName']
        return [pscustomobject]@{
            Root = $fullRoot
            AgentName = if ($nameProperty) { [string]$nameProperty.Value } else { '' }
            RunCmd = $runCmd
            Listener = $listener
        }
    }
    catch { return $null }
}

function Add-Candidate([System.Collections.Generic.List[string]]$List, [string]$Candidate) {
    if (-not $Candidate) { return }
    try {
        if (Test-Path -LiteralPath $Candidate -PathType Container) {
            $full = (Resolve-Path -LiteralPath $Candidate).Path
            if (-not $List.Contains($full)) { [void]$List.Add($full) }
        }
    }
    catch { }
}

function Get-RunnerServices {
    try { return @(Get-CimInstance Win32_Service -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'actions.runner.*' }) }
    catch { return @() }
}

function Get-CandidateRunnerRoots {
    $candidates = New-Object 'System.Collections.Generic.List[string]'

    foreach ($svc in Get-RunnerServices) {
        Add-Candidate $candidates (Convert-ExecutableToRunnerRoot (Get-ServiceExecutable ([string]$svc.PathName)))
    }

    try {
        foreach ($process in Get-CimInstance Win32_Process -Filter "Name='Runner.Listener.exe'" -ErrorAction SilentlyContinue) {
            Add-Candidate $candidates (Convert-ExecutableToRunnerRoot ([string]$process.ExecutablePath))
        }
    }
    catch { }

    foreach ($known in @(
        (Join-Path $env:SystemDrive 'actions-runner'),
        (Join-Path $env:USERPROFILE 'actions-runner'),
        (Join-Path $env:USERPROFILE 'Desktop\actions-runner'),
        (Join-Path $env:USERPROFILE 'Downloads\actions-runner'),
        (Join-Path $env:LOCALAPPDATA 'NEXUS\actions-runner')
    )) { Add-Candidate $candidates $known }

    foreach ($parent in @(
        ($env:SystemDrive + '\'),
        $env:USERPROFILE,
        (Join-Path $env:USERPROFILE 'Desktop'),
        (Join-Path $env:USERPROFILE 'Downloads'),
        (Join-Path $env:LOCALAPPDATA 'NEXUS')
    )) {
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

function Find-UniqueRunner {
    $valid = @()
    foreach ($candidate in Get-CandidateRunnerRoots) {
        $runner = Read-RunnerConfig $candidate
        if ($runner) { $valid += $runner }
    }
    $unique = @($valid | Group-Object Root | ForEach-Object { $_.Group[0] })
    if ($unique.Count -eq 0) { return [pscustomobject]@{ Status='NONE'; Runner=$null; Count=0 } }
    if ($unique.Count -gt 1) { return [pscustomobject]@{ Status='MULTIPLE'; Runner=$null; Count=$unique.Count } }
    return [pscustomobject]@{ Status='ONE'; Runner=$unique[0]; Count=1 }
}

function Get-RunnerService([pscustomobject]$Runner) {
    $matches = @()
    foreach ($svc in Get-RunnerServices) {
        $root = Convert-ExecutableToRunnerRoot (Get-ServiceExecutable ([string]$svc.PathName))
        if (-not $root) { continue }
        try {
            if ((Resolve-Path -LiteralPath $root).Path -eq $Runner.Root) { $matches += $svc }
        }
        catch { }
    }
    if ($matches.Count -eq 1) { return $matches[0] }
    if ($matches.Count -gt 1) { throw 'multiple runner services map to the configured runner root' }
    return $null
}

function Get-Listener([pscustomobject]$Runner) {
    try {
        foreach ($row in Get-CimInstance Win32_Process -Filter "Name='Runner.Listener.exe'" -ErrorAction SilentlyContinue) {
            $root = Convert-ExecutableToRunnerRoot ([string]$row.ExecutablePath)
            if (-not $root) { continue }
            if ((Resolve-Path -LiteralPath $root).Path -eq $Runner.Root) { return $row }
        }
    }
    catch { }
    return $null
}

function Wait-ForListener([pscustomobject]$Runner, [int]$Seconds = 20) {
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    do {
        $listener = Get-Listener $Runner
        if ($listener) { return $listener }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)
    return $null
}

function Start-InteractiveRunnerFallback([pscustomobject]$Runner, [string]$Reason = 'unspecified') {
    $existing = Get-Listener $Runner
    if ($existing) { return [int]$existing.ProcessId }

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $env:ComSpec
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.WorkingDirectory = $Runner.Root
    $psi.Arguments = '/d /s /c ""' + $Runner.RunCmd + '""'
    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    [void]$proc.Start()
    Write-Log "user_fallback_start_requested reason=$Reason root=$($Runner.Root) bootstrap_pid=$($proc.Id)"
    return [int]$proc.Id
}

function Install-InteractiveRunnerTask([pscustomobject]$Runner) {
    $user = "$env:USERDOMAIN\$env:USERNAME"
    $quotedRun = '"' + $Runner.RunCmd.Replace('"','') + '"'
    $taskArgs = '/d /s /c "' + $quotedRun + '"'
    $action = New-ScheduledTaskAction -Execute $env:ComSpec -Argument $taskArgs -WorkingDirectory $Runner.Root
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
    $task = New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Starts the already-configured NEXUS GitHub Actions self-hosted runner after Windows logon without a visible terminal.'
    Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
    Start-ScheduledTask -TaskName $TaskName
}

try {
    Ensure-StateRoot
    if ($env:OS -ne 'Windows_NT') { throw 'GUI runner bootstrap is Windows-only' }
    if (-not [Environment]::UserInteractive) { throw 'GUI runner bootstrap requires an interactive owner session' }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    if ($identity -in @('NT AUTHORITY\SYSTEM','NT AUTHORITY\NETWORK SERVICE','NT AUTHORITY\LOCAL SERVICE')) {
        throw 'service identities are not allowed to perform GUI runner bootstrap'
    }

    $selection = Find-UniqueRunner
    if ($selection.Status -eq 'NONE') {
        Write-Evidence 'RUNNER_NOT_FOUND' @{ configured_runner_count = 0 }
        exit 10
    }
    if ($selection.Status -eq 'MULTIPLE') {
        Write-Evidence 'MULTIPLE_RUNNERS_REJECTED' @{ configured_runner_count = $selection.Count }
        exit 11
    }

    $runner = $selection.Runner
    $listener = Get-Listener $runner
    if ($listener) {
        Write-Evidence 'LISTENER_ALREADY_RUNNING' @{
            configured_runner_count = 1
            runner_root = $runner.Root
            agent_name = $runner.AgentName
            listener_pid = [int]$listener.ProcessId
            scheduled_task_changed = $false
        }
        exit 0
    }

    $service = Get-RunnerService $runner
    if ($service) {
        $serviceStartError = $null
        $serviceWasRunning = ([string]$service.State -eq 'Running')
        if (-not $serviceWasRunning) {
            try { Start-Service -Name ([string]$service.Name) -ErrorAction Stop }
            catch { $serviceStartError = $_.Exception.Message }
        }

        if ($serviceStartError) {
            $listener = Get-Listener $runner
            $fallbackPid = $null
            if (-not $listener) {
                $fallbackPid = Start-InteractiveRunnerFallback $runner 'service_start_denied'
                $listener = Wait-ForListener $runner
            }
            if (-not $listener) {
                Write-Evidence 'SERVICE_STOPPED_USER_FALLBACK_LISTENER_NOT_OBSERVED' @{
                    configured_runner_count = 1
                    runner_root = $runner.Root
                    agent_name = $runner.AgentName
                    service_name = [string]$service.Name
                    service_state = [string]$service.State
                    scheduled_task_changed = $false
                    fallback_transport = 'current_user_hidden_process'
                    fallback_bootstrap_pid = $fallbackPid
                    service_start_error = $serviceStartError
                }
                exit 12
            }
            Write-Evidence 'SERVICE_STOPPED_USER_FALLBACK_RUNNING' @{
                configured_runner_count = 1
                runner_root = $runner.Root
                agent_name = $runner.AgentName
                service_name = [string]$service.Name
                service_state = [string]$service.State
                listener_pid = [int]$listener.ProcessId
                scheduled_task_changed = $false
                fallback_transport = 'current_user_hidden_process'
                fallback_bootstrap_pid = $fallbackPid
                service_start_error = $serviceStartError
            }
            exit 0
        }

        # A Windows Service that merely reports Running is not proof that the
        # GitHub Runner.Listener is healthy. Give an already-running service a
        # short bounded grace period, then re-check immediately before starting
        # the existing configured run.cmd in the interactive owner context.
        # This preserves the no-elevation/no-registration boundary and avoids a
        # second listener whenever the service recovers during the grace period.
        $listener = if ($serviceWasRunning) { Wait-ForListener $runner 8 } else { Wait-ForListener $runner }
        if (-not $listener -and $serviceWasRunning) {
            $fallbackPid = Start-InteractiveRunnerFallback $runner 'service_running_listener_absent'
            $listener = Wait-ForListener $runner
            if (-not $listener) {
                Write-Evidence 'SERVICE_RUNNING_STALE_USER_FALLBACK_LISTENER_NOT_OBSERVED' @{
                    configured_runner_count = 1
                    runner_root = $runner.Root
                    agent_name = $runner.AgentName
                    service_name = [string]$service.Name
                    service_state = [string]$service.State
                    service_was_running = $true
                    scheduled_task_changed = $false
                    fallback_transport = 'current_user_hidden_process'
                    fallback_bootstrap_pid = $fallbackPid
                }
                exit 13
            }
            Write-Evidence 'SERVICE_RUNNING_STALE_USER_FALLBACK_RUNNING' @{
                configured_runner_count = 1
                runner_root = $runner.Root
                agent_name = $runner.AgentName
                service_name = [string]$service.Name
                service_state = [string]$service.State
                service_was_running = $true
                listener_pid = [int]$listener.ProcessId
                scheduled_task_changed = $false
                fallback_transport = 'current_user_hidden_process'
                fallback_bootstrap_pid = $fallbackPid
            }
            exit 0
        }
        if (-not $listener) {
            Write-Evidence 'SERVICE_STARTED_LISTENER_NOT_OBSERVED' @{
                configured_runner_count = 1
                runner_root = $runner.Root
                agent_name = $runner.AgentName
                service_name = [string]$service.Name
                service_was_running = $false
                scheduled_task_changed = $false
            }
            exit 13
        }
        Write-Evidence 'SERVICE_RUNNING' @{
            configured_runner_count = 1
            runner_root = $runner.Root
            agent_name = $runner.AgentName
            service_name = [string]$service.Name
            service_was_running = $serviceWasRunning
            listener_pid = [int]$listener.ProcessId
            scheduled_task_changed = $false
        }
        exit 0
    }

    Install-InteractiveRunnerTask $runner
    $listener = Wait-ForListener $runner
    if (-not $listener) {
        Write-Evidence 'TASK_INSTALLED_LISTENER_NOT_OBSERVED' @{
            configured_runner_count = 1
            runner_root = $runner.Root
            agent_name = $runner.AgentName
            scheduled_task = $TaskName
            scheduled_task_changed = $true
        }
        exit 14
    }

    Write-Evidence 'TASK_INSTALLED_LISTENER_RUNNING' @{
        configured_runner_count = 1
        runner_root = $runner.Root
        agent_name = $runner.AgentName
        listener_pid = [int]$listener.ProcessId
        scheduled_task = $TaskName
        scheduled_task_changed = $true
    }
    exit 0
}
catch {
    try { Write-Evidence 'BLOCKED' @{ error = $_.Exception.Message } } catch { }
    try { Write-Log "blocked error=$($_.Exception.Message)" } catch { }
    exit 20
}
