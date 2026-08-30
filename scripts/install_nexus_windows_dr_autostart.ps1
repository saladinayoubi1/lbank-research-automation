[CmdletBinding()]
param(
    [ValidateSet('Install','Run')]
    [string]$Mode = 'Install',
    [string]$RunnerRoot = 'C:\actions-runner\actions-runner',
    [string]$ExpectedRunnerName = 'NEXUS-WINDOWS-DR',
    [string]$ExpectedGitHubUrl = 'https://github.com/saladinayoubi1/lbank-research-automation',
    [string]$OutputPath = 'build\windows-dr-autostart\evidence.json'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$TaskName = 'NEXUS-WINDOWS-DR-Autostart'
$StateRoot = Join-Path $env:LOCALAPPDATA 'NEXUS\WindowsDRAutostart'
$StableScript = Join-Path $StateRoot 'windows-dr-autostart.ps1'
$LogPath = Join-Path $StateRoot 'windows-dr-autostart.log'

function Normalize-Url([string]$Value) {
    if (-not $Value) { return '' }
    return $Value.Trim().TrimEnd('/').ToLowerInvariant()
}

function Ensure-StateRoot {
    New-Item -ItemType Directory -Path $StateRoot -Force | Out-Null
}

function Write-Log([string]$Message) {
    Ensure-StateRoot
    Add-Content -LiteralPath $LogPath -Encoding UTF8 -Value ('[{0}] {1}' -f [DateTime]::UtcNow.ToString('o'), $Message)
}

function Write-Evidence([string]$Decision, [hashtable]$Extra = @{}) {
    $target = [IO.Path]::GetFullPath($OutputPath)
    $parent = Split-Path -Parent $target
    if ($parent) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $payload = [ordered]@{
        schema_version = 1
        generated_at_utc = [DateTime]::UtcNow.ToString('o')
        decision = $Decision
        runner_root = [IO.Path]::GetFullPath($RunnerRoot)
        expected_runner_name = $ExpectedRunnerName
        current_runner_name = [string]$env:RUNNER_NAME
        scheduled_task = $TaskName
        runner_registration_modified = $false
        runner_credentials_modified = $false
        other_runner_paths_modified = $false
        service_installed = $false
        elevation_requested = $false
        paper_only = $true
        live_trading_authority = $false
    }
    foreach ($key in $Extra.Keys) { $payload[$key] = $Extra[$key] }
    $payload | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $target -Encoding UTF8
}

function Assert-TargetRunnerFiles {
    if ($env:OS -ne 'Windows_NT') { throw 'Windows is required.' }
    $fullRoot = [IO.Path]::GetFullPath($RunnerRoot).TrimEnd('\')
    $required = @(
        (Join-Path $fullRoot '.runner'),
        (Join-Path $fullRoot 'run.cmd'),
        (Join-Path $fullRoot 'bin\Runner.Listener.exe')
    )
    foreach ($path in $required) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Target runner file is missing: $path" }
    }
    $config = Get-Content -LiteralPath (Join-Path $fullRoot '.runner') -Raw | ConvertFrom-Json
    $agentName = [string]$config.agentName
    $gitHubUrl = [string]$config.gitHubUrl
    if ($agentName -ne $ExpectedRunnerName) { throw "Target runner name mismatch: $agentName" }
    if ((Normalize-Url $gitHubUrl) -ne (Normalize-Url $ExpectedGitHubUrl)) { throw 'Target runner repository binding mismatch.' }
    return $fullRoot
}

function Get-TargetListener {
    $fullRoot = [IO.Path]::GetFullPath($RunnerRoot).TrimEnd('\') + '\'
    foreach ($proc in Get-Process -Name 'Runner.Listener' -ErrorAction SilentlyContinue) {
        try {
            $path = [string]$proc.Path
            if ($path -and ([IO.Path]::GetFullPath($path)).StartsWith($fullRoot, [StringComparison]::OrdinalIgnoreCase)) {
                return $proc
            }
        }
        catch { }
    }
    return $null
}

function Start-TargetRunnerHidden {
    $fullRoot = Assert-TargetRunnerFiles
    if (Get-TargetListener) { return $false }
    $runCmd = Join-Path $fullRoot 'run.cmd'
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $env:ComSpec
    $psi.Arguments = '/d /s /c ""' + $runCmd + '""'
    $psi.WorkingDirectory = $fullRoot
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    if (-not $proc.Start()) { throw 'Failed to start the target runner.' }
    Write-Log "target_runner_start_requested pid=$($proc.Id)"
    return $true
}

function Run-Supervisor {
    [void](Assert-TargetRunnerFiles)
    Write-Log 'supervisor_started=true'
    while ($true) {
        try {
            if (-not (Get-TargetListener)) {
                [void](Start-TargetRunnerHidden)
            }
        }
        catch {
            Write-Log ('supervisor_iteration_error=' + $_.Exception.GetType().Name)
        }
        Start-Sleep -Seconds 15
    }
}

function Install-TargetTask {
    if (-not [Environment]::UserInteractive) { throw 'An interactive signed-in Windows user is required.' }
    if ([string]$env:RUNNER_NAME -ne $ExpectedRunnerName) {
        Write-Evidence 'SKIPPED_WRONG_RUNNER' @{ target_task_registered = $false; target_task_started = $false }
        Write-Host "windows_dr_autostart_decision=SKIPPED_WRONG_RUNNER current=$env:RUNNER_NAME expected=$ExpectedRunnerName"
        return
    }

    $fullRoot = Assert-TargetRunnerFiles
    Ensure-StateRoot
    $source = (Resolve-Path -LiteralPath $PSCommandPath).Path
    if (-not $source.Equals([IO.Path]::GetFullPath($StableScript), [StringComparison]::OrdinalIgnoreCase)) {
        Copy-Item -LiteralPath $source -Destination $StableScript -Force
    }

    $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if (-not (Test-Path -LiteralPath $powershell -PathType Leaf)) {
        $powershell = (Get-Command powershell.exe -ErrorAction Stop).Source
    }
    $user = "$env:USERDOMAIN\$env:USERNAME"
    $service = New-Object -ComObject 'Schedule.Service'
    $service.Connect()
    $folder = $service.GetFolder('\')
    $definition = $service.NewTask(0)
    $definition.RegistrationInfo.Description = 'Keeps only the existing NEXUS-WINDOWS-DR GitHub Actions runner available without modifying registration or credentials.'
    $definition.RegistrationInfo.Author = 'NEXUS'
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
    $action.Path = $powershell
    $action.Arguments = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$StableScript`" -Mode Run -RunnerRoot `"$fullRoot`" -ExpectedRunnerName `"$ExpectedRunnerName`" -ExpectedGitHubUrl `"$ExpectedGitHubUrl`""
    $action.WorkingDirectory = $fullRoot

    $registered = $folder.RegisterTaskDefinition("\$TaskName", $definition, 6, $null, $null, 3, $null)
    if (-not $registered) { throw 'Task Scheduler did not return the target task.' }
    [void]$registered.Run($null)
    Start-Sleep -Seconds 2

    Write-Evidence 'SUCCESS' @{
        target_task_registered = $true
        target_task_started = $true
        stable_script = $StableScript
        target_listener_observed = [bool](Get-TargetListener)
    }
    Write-Log 'install_decision=SUCCESS'
    Write-Host 'windows_dr_autostart_decision=SUCCESS'
}

try {
    if ($Mode -eq 'Run') {
        Run-Supervisor
        exit 0
    }
    Install-TargetTask
    exit 0
}
catch {
    $message = $_.Exception.Message
    try { Write-Log ('install_decision=BLOCKED error=' + $message) } catch { }
    try { Write-Evidence 'BLOCKED' @{ error = $message; target_task_registered = $false } } catch { }
    Write-Host ('windows_dr_autostart_decision=BLOCKED error=' + $message)
    exit 1
}
