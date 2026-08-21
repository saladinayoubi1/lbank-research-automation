[CmdletBinding()]
param(
    [ValidateSet('Install','Run')]
    [string]$Mode = 'Install'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$ExpectedGitHubUrl = 'https://github.com/saladinayoubi1/lbank-research-automation'
$NexusRoot = Join-Path $env:LOCALAPPDATA 'NEXUS'
$RunnerRoot = Join-Path $NexusRoot 'actions-runner'
$StateRoot = Join-Path $NexusRoot 'RunnerAutostart'
$StableHostPath = Join-Path $StateRoot 'hidden-runner-host.ps1'
$EvidencePath = Join-Path $StateRoot 'hidden-autostart-evidence.json'
$LogPath = Join-Path $StateRoot 'hidden-autostart.log'
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
        contract_version = 'nexus.runner-hidden-autostart.v1'
        status = $Status
        generated_at = [DateTime]::UtcNow.ToString('o')
        runner_root = $RunnerRoot
        scheduled_task = $TaskName
        task_scheduler_transport = 'COM'
        visible_console_required = $false
        child_console_suppressed = $true
        runner_registration_modified = $false
        credentials_modified = $false
        elevation_requested = $false
        machine_execution_policy_modified = $false
        service_installed = $false
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

function Get-ManagedProcess([string]$Name) {
    $expectedRoot = [IO.Path]::GetFullPath($RunnerRoot).TrimEnd('\') + '\'
    foreach ($proc in Get-Process -Name $Name -ErrorAction SilentlyContinue) {
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

function Ensure-ProcessTreeApi {
    if ('Nexus.RunnerProcessTree' -as [type]) { return }
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

namespace Nexus {
    public static class RunnerProcessTree {
        private const uint TH32CS_SNAPPROCESS = 0x00000002;

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Auto)]
        private struct PROCESSENTRY32 {
            public uint dwSize;
            public uint cntUsage;
            public uint th32ProcessID;
            public IntPtr th32DefaultHeapID;
            public uint th32ModuleID;
            public uint cntThreads;
            public uint th32ParentProcessID;
            public int pcPriClassBase;
            public uint dwFlags;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)]
            public string szExeFile;
        }

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern IntPtr CreateToolhelp32Snapshot(uint dwFlags, uint th32ProcessID);

        [DllImport("kernel32.dll", CharSet = CharSet.Auto, SetLastError = true)]
        private static extern bool Process32First(IntPtr hSnapshot, ref PROCESSENTRY32 lppe);

        [DllImport("kernel32.dll", CharSet = CharSet.Auto, SetLastError = true)]
        private static extern bool Process32Next(IntPtr hSnapshot, ref PROCESSENTRY32 lppe);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool CloseHandle(IntPtr hObject);

        public static int GetParentProcessId(int processId) {
            IntPtr snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
            if (snapshot == new IntPtr(-1)) return 0;
            try {
                PROCESSENTRY32 entry = new PROCESSENTRY32();
                entry.dwSize = (uint)Marshal.SizeOf(typeof(PROCESSENTRY32));
                if (!Process32First(snapshot, ref entry)) return 0;
                do {
                    if (entry.th32ProcessID == (uint)processId) {
                        return (int)entry.th32ParentProcessID;
                    }
                } while (Process32Next(snapshot, ref entry));
                return 0;
            }
            finally {
                CloseHandle(snapshot);
            }
        }
    }
}
'@
}

function Stop-ManagedLauncherTree {
    $listener = Get-ManagedProcess 'Runner.Listener'
    if (-not $listener) { return $false }

    Ensure-ProcessTreeApi
    $parentPid = [Nexus.RunnerProcessTree]::GetParentProcessId([int]$listener.Id)
    if ($parentPid -le 0) {
        throw 'Could not resolve the launcher process for the managed runner listener.'
    }

    $parent = Get-Process -Id $parentPid -ErrorAction SilentlyContinue
    if (-not $parent) {
        throw 'Managed runner launcher exited before it could be retired.'
    }
    if ($parent.ProcessName -ine 'cmd') {
        throw "Refusing to terminate unexpected managed runner parent process: $($parent.ProcessName) (PID $parentPid)."
    }

    $taskkill = Join-Path $env:SystemRoot 'System32\taskkill.exe'
    if (-not (Test-Path -LiteralPath $taskkill -PathType Leaf)) {
        $taskkill = (Get-Command taskkill.exe -ErrorAction Stop).Source
    }
    & $taskkill /PID $parentPid /T /F 1>$null 2>$null
    $taskkillExit = $LASTEXITCODE

    $deadline = [DateTime]::UtcNow.AddSeconds(12)
    while ((Get-ManagedProcess 'Runner.Listener') -and [DateTime]::UtcNow -lt $deadline) {
        Start-Sleep -Milliseconds 500
    }
    if (Get-ManagedProcess 'Runner.Listener') {
        throw "Visible managed runner launcher did not exit after targeted process-tree retirement (taskkill exit $taskkillExit)."
    }

    Write-Log "legacy_runner_launcher_retired parent_pid=$parentPid taskkill_exit=$taskkillExit"
    return $true
}

function Invoke-HiddenRunner {
    Assert-ConfiguredRunner
    $runCmd = Join-Path $RunnerRoot 'run.cmd'
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $env:ComSpec
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    $psi.WorkingDirectory = $RunnerRoot
    $psi.Arguments = '/d /s /c ""' + $runCmd + '""'
    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    if (-not $proc.Start()) { throw 'Failed to start hidden GitHub Actions runner host.' }
    Write-Log "hidden_runner_host_started bootstrap_pid=$($proc.Id)"
    $proc.WaitForExit()
    $exitCode = $proc.ExitCode
    Write-Log "hidden_runner_host_exited exit_code=$exitCode"
    exit $exitCode
}

function Connect-TaskScheduler {
    $service = New-Object -ComObject 'Schedule.Service'
    $service.Connect()
    return $service
}

function Resolve-WindowsPowerShell {
    $candidate = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    return (Get-Command powershell.exe -ErrorAction Stop).Source
}

function Install-HiddenAutostart {
    Assert-ConfiguredRunner
    if (-not [Environment]::UserInteractive) { throw 'Run this repair from the signed-in Windows desktop.' }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    if ($identity -in @('NT AUTHORITY\SYSTEM','NT AUTHORITY\NETWORK SERVICE','NT AUTHORITY\LOCAL SERVICE')) {
        throw 'A signed-in owner account is required.'
    }

    Ensure-StateRoot
    $sourcePath = (Resolve-Path -LiteralPath $PSCommandPath).Path
    $stableFull = [IO.Path]::GetFullPath($StableHostPath)
    if (-not $sourcePath.Equals($stableFull,[StringComparison]::OrdinalIgnoreCase)) {
        Copy-Item -LiteralPath $sourcePath -Destination $StableHostPath -Force
    }

    $powershell = Resolve-WindowsPowerShell
    $user = "$env:USERDOMAIN\$env:USERNAME"
    $service = Connect-TaskScheduler
    $folder = $service.GetFolder('\')

    $existing = $null
    try { $existing = $folder.GetTask("\$TaskName") } catch { $existing = $null }

    $definition = $service.NewTask(0)
    $definition.RegistrationInfo.Description = 'Keeps the configured NEXUS GitHub Actions runner available without visible CMD or Node console windows.'
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
    $action.Path = $powershell
    $action.Arguments = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$StableHostPath`" -Mode Run"
    $action.WorkingDirectory = $RunnerRoot

    # Do not interrupt a running GitHub Actions job. Wait for the managed worker to finish.
    $deadline = [DateTime]::UtcNow.AddMinutes(15)
    while ((Get-ManagedProcess 'Runner.Worker') -and [DateTime]::UtcNow -lt $deadline) {
        Start-Sleep -Seconds 3
    }
    if (Get-ManagedProcess 'Runner.Worker') {
        Write-Evidence 'MIGRATION_PENDING_ACTIVE_JOB' @{ hidden_task_registered = $false; hidden_task_started = $false }
        Write-Log 'hidden_autostart_migration_pending_active_job=true'
        throw 'A GitHub Actions job is still active after 15 minutes; the current listener was not interrupted.'
    }

    # Stop the existing task instance before replacing its definition. Replacing first can leave
    # the old visible cmd.exe launcher orphaned; killing Runner.Listener alone lets run.cmd restart it.
    if ($existing) {
        try { $existing.Stop(0) } catch { }
        Start-Sleep -Seconds 3
    }

    $legacyLauncherRetired = $false
    if (Get-ManagedProcess 'Runner.Listener') {
        $legacyLauncherRetired = Stop-ManagedLauncherTree
    }

    $registered = $folder.RegisterTaskDefinition("\$TaskName",$definition,6,$null,$null,3,$null)
    if (-not $registered) { throw 'Task Scheduler did not return the updated runner task.' }

    [void]$registered.Run($null)
    $listenerReady = $false
    $readyDeadline = [DateTime]::UtcNow.AddSeconds(30)
    do {
        Start-Sleep -Milliseconds 750
        if (Get-ManagedProcess 'Runner.Listener') { $listenerReady = $true; break }
    } while ([DateTime]::UtcNow -lt $readyDeadline)
    if (-not $listenerReady) { throw 'Hidden runner task was installed, but Runner.Listener.exe was not observed.' }

    Write-Evidence 'SUCCESS' @{
        hidden_task_registered = $true
        hidden_task_started = $true
        legacy_launcher_retired = [bool]$legacyLauncherRetired
    }
    Write-Log "status=SUCCESS hidden_runner_autostart=true visible_console_required=false legacy_launcher_retired=$legacyLauncherRetired"
    Write-Host 'NEXUS runner autostart is now hidden. You can close this repair window.' -ForegroundColor Green
}

try {
    if ($Mode -eq 'Run') {
        Invoke-HiddenRunner
    }
    Install-HiddenAutostart
    exit 0
}
catch {
    $message = $_.Exception.Message
    try { Write-Log "status=BLOCKED error=$message" } catch { }
    if ($Mode -eq 'Install') {
        try { Write-Evidence 'BLOCKED' @{ error = $message } } catch { }
        Write-Host "NEXUS hidden runner autostart repair blocked: $message" -ForegroundColor Red
    }
    exit 1
}
