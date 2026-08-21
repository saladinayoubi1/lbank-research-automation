[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$SourceSha
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$ManagedRepoRoot = Join-Path $env:LOCALAPPDATA 'NEXUS\lbank-research-automation'
$CoreBootstrap = Join-Path $PSScriptRoot 'install_nexus_owner_autostart_core.ps1'
$SelfHealRelative = 'scripts\enable_nexus_runner_self_heal.ps1'

function Resolve-WindowsPowerShell {
    $fixed = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if (Test-Path -LiteralPath $fixed -PathType Leaf) { return $fixed }
    return (Get-Command powershell.exe -ErrorAction Stop).Source
}

function Invoke-HiddenPowerShell([string]$ScriptPath, [string[]]$Arguments, [string]$WorkingDirectory) {
    if (-not (Test-Path -LiteralPath $ScriptPath -PathType Leaf)) {
        throw "required NEXUS script is missing: $ScriptPath"
    }
    $ps = Resolve-WindowsPowerShell
    $quoted = @('-NoProfile','-NonInteractive','-WindowStyle','Hidden','-ExecutionPolicy','Bypass','-File',"`"$ScriptPath`"")
    foreach ($arg in $Arguments) { $quoted += "`"$arg`"" }
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $ps
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    $psi.WorkingDirectory = $WorkingDirectory
    $psi.Arguments = ($quoted -join ' ')
    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    if (-not $proc.Start()) { throw "failed to start NEXUS helper: $ScriptPath" }
    $proc.WaitForExit()
    return [int]$proc.ExitCode
}

try {
    if ($env:OS -ne 'Windows_NT') { throw 'Windows is required.' }
    if (-not [Environment]::UserInteractive) { throw 'interactive owner session is required.' }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    if ($identity -in @('NT AUTHORITY\SYSTEM','NT AUTHORITY\NETWORK SERVICE','NT AUTHORITY\LOCAL SERVICE')) {
        throw 'service identities cannot install owner autostart.'
    }

    $coreRc = Invoke-HiddenPowerShell -ScriptPath $CoreBootstrap -Arguments @('-SourceSha',$SourceSha) -WorkingDirectory $PSScriptRoot
    if ($coreRc -ne 0) { throw "owner autostart core bootstrap failed with exit $coreRc" }

    $selfHeal = Join-Path $ManagedRepoRoot $SelfHealRelative
    $healRc = Invoke-HiddenPowerShell -ScriptPath $selfHeal -Arguments @() -WorkingDirectory $ManagedRepoRoot
    if ($healRc -ne 0) { throw "runner self-heal activation failed with exit $healRc" }

    Write-Host 'NEXUS_OWNER_AUTOSTART_AND_SELF_HEAL=SUCCESS' -ForegroundColor Green
    exit 0
}
catch {
    Write-Host "NEXUS owner autostart+self-heal blocked: $($_.Exception.Message)" -ForegroundColor Red
    exit 20
}
