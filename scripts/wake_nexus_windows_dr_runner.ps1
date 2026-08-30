[CmdletBinding()]
param(
    [string]$RunnerRoot = 'C:\actions-runner\actions-runner',
    [string]$ExpectedRunnerName = 'NEXUS-WINDOWS-DR',
    [string]$ExpectedGitHubUrl = 'https://github.com/saladinayoubi1/lbank-research-automation',
    [int]$WaitSeconds = 30,
    [string]$OutputPath = 'build\windows-dr-bootstrap\evidence.json'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

function Normalize-Url([string]$Value) {
    if (-not $Value) { return '' }
    return $Value.Trim().TrimEnd('/').ToLowerInvariant()
}

function Write-Evidence([string]$Decision, [hashtable]$Extra = @{}) {
    $target = [IO.Path]::GetFullPath($OutputPath)
    $parent = Split-Path -Parent $target
    if ($parent) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $payload = [ordered]@{
        schema_version = 1
        generated_at_utc = [DateTime]::UtcNow.ToString('o')
        decision = $Decision
        current_runner_name = [string]$env:RUNNER_NAME
        runner_root = [IO.Path]::GetFullPath($RunnerRoot)
        expected_runner_name = $ExpectedRunnerName
        expected_github_url = $ExpectedGitHubUrl
        runner_registration_modified = $false
        runner_credentials_modified = $false
        other_runner_paths_modified = $false
        service_installed = $false
        scheduled_task_modified = $false
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
    foreach ($relative in @('.runner','run.cmd','bin\Runner.Listener.exe')) {
        $path = Join-Path $fullRoot $relative
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Target runner file is missing: $path"
        }
    }
    $config = Get-Content -LiteralPath (Join-Path $fullRoot '.runner') -Raw | ConvertFrom-Json
    if ([string]$config.agentName -ne $ExpectedRunnerName) {
        throw "Target runner name mismatch: $($config.agentName)"
    }
    if ((Normalize-Url ([string]$config.gitHubUrl)) -ne (Normalize-Url $ExpectedGitHubUrl)) {
        throw 'Target runner repository binding mismatch.'
    }
    return $fullRoot
}

function Get-TargetListener {
    $prefix = [IO.Path]::GetFullPath($RunnerRoot).TrimEnd('\') + '\'
    foreach ($proc in Get-Process -Name 'Runner.Listener' -ErrorAction SilentlyContinue) {
        try {
            $path = [string]$proc.Path
            if ($path -and ([IO.Path]::GetFullPath($path)).StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
                return $proc
            }
        }
        catch { }
    }
    return $null
}

try {
    $fullRoot = Assert-TargetRunnerFiles
    $existing = Get-TargetListener
    if ($existing) {
        Write-Evidence 'ALREADY_RUNNING' @{ target_listener_observed = $true; target_pid = $existing.Id }
        Write-Host "windows_dr_bootstrap_decision=ALREADY_RUNNING pid=$($existing.Id)"
        exit 0
    }

    if ([string]$env:RUNNER_NAME -eq $ExpectedRunnerName) {
        Write-Evidence 'TARGET_ALREADY_ACTIVE' @{ target_listener_observed = $true }
        Write-Host 'windows_dr_bootstrap_decision=TARGET_ALREADY_ACTIVE'
        exit 0
    }

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
    if (-not $proc.Start()) { throw 'Failed to start the target runner process.' }

    $deadline = [DateTime]::UtcNow.AddSeconds([Math]::Max(5, $WaitSeconds))
    $listener = $null
    while ([DateTime]::UtcNow -lt $deadline) {
        Start-Sleep -Seconds 1
        $listener = Get-TargetListener
        if ($listener) { break }
    }
    if (-not $listener) { throw 'Target runner listener was not observed before timeout.' }

    Write-Evidence 'STARTED' @{
        target_listener_observed = $true
        launcher_pid = $proc.Id
        target_pid = $listener.Id
    }
    Write-Host "windows_dr_bootstrap_decision=STARTED target_pid=$($listener.Id)"
    exit 0
}
catch {
    $message = $_.Exception.Message
    try { Write-Evidence 'BLOCKED' @{ error = $message; target_listener_observed = $false } } catch { }
    Write-Host "windows_dr_bootstrap_decision=BLOCKED error=$message"
    exit 1
}
