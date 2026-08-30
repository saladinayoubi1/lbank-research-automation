param(
    [string]$OutputPath = "build\bybit-wsl-runner-diagnostics\evidence.json",
    [string]$RunnerRoot = "/opt/nexus-bybit-runner",
    [string]$RunnerName = "NEXUS-BYBIT-WSL",
    [string]$SourceRunId = "",
    [string]$SourceSha = "",
    [string]$SourceConclusion = ""
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

if ($RunnerRoot -ne '/opt/nexus-bybit-runner') { throw 'RunnerRoot must remain pinned.' }
if ($RunnerName -ne 'NEXUS-BYBIT-WSL') { throw 'RunnerName must remain pinned.' }

$wsl = Join-Path $env:SystemRoot 'System32\wsl.exe'
if (-not (Test-Path -LiteralPath $wsl -PathType Leaf)) { throw 'wsl.exe is required.' }
$schTasks = Join-Path $env:SystemRoot 'System32\schtasks.exe'

Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class NexusWtsProbe {
    [DllImport("kernel32.dll")]
    public static extern UInt32 WTSGetActiveConsoleSessionId();

    [DllImport("wtsapi32.dll", SetLastError=true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool WTSQueryUserToken(UInt32 SessionId, out IntPtr phToken);

    [DllImport("kernel32.dll", SetLastError=true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool CloseHandle(IntPtr hObject);
}
'@

function Invoke-WslNative {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $raw = @(& $wsl @Arguments 2>&1)
        $code = $LASTEXITCODE
        $text = (($raw | ForEach-Object { $_.ToString() }) | Out-String) -replace "`0", ''
        return [ordered]@{
            exit_code = if ($null -eq $code) { -1 } else { [int]$code }
            output = $text.Trim()
        }
    }
    catch {
        return [ordered]@{ exit_code = -1; output = $_.Exception.GetType().FullName }
    }
    finally {
        $ErrorActionPreference = $previous
    }
}

function Get-VisibleRecoveryTask {
    if (-not (Test-Path -LiteralPath $schTasks -PathType Leaf)) {
        return [ordered]@{ found = $false; name = ''; query_access_denied = $false }
    }

    $accessDenied = $false
    foreach ($taskName in @('NEXUS Bybit WSL Runner Persistent', 'NEXUS Bybit WSL Runner')) {
        $previous = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            $raw = @(& $schTasks /Query /TN $taskName 2>&1)
            $code = $LASTEXITCODE
            $text = (($raw | ForEach-Object { $_.ToString() }) | Out-String).Trim()
            if ($text -match '(?i)access is denied') { $accessDenied = $true }
        }
        catch {
            $code = -1
            if ($_.Exception.Message -match '(?i)access is denied') { $accessDenied = $true }
        }
        finally {
            $ErrorActionPreference = $previous
        }
        if ($code -eq 0) {
            return [ordered]@{ found = $true; name = $taskName; query_access_denied = $accessDenied }
        }
    }

    return [ordered]@{ found = $false; name = ''; query_access_denied = $accessDenied }
}

function Get-UserContextCapability {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $sid = $identity.User.Value
    $runnerClass = switch ($sid) {
        'S-1-5-18' { 'LOCAL_SYSTEM' }
        'S-1-5-19' { 'LOCAL_SERVICE' }
        'S-1-5-20' { 'NETWORK_SERVICE' }
        default { 'OTHER_ACCOUNT' }
    }

    $sessionId = [NexusWtsProbe]::WTSGetActiveConsoleSessionId()
    $hasInteractiveSession = ($sessionId -ne [UInt32]::MaxValue)
    $tokenAvailable = $false
    $tokenError = 0
    $token = [IntPtr]::Zero
    if ($hasInteractiveSession) {
        $tokenAvailable = [NexusWtsProbe]::WTSQueryUserToken($sessionId, [ref]$token)
        if (-not $tokenAvailable) {
            $tokenError = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
        }
        elseif ($token -ne [IntPtr]::Zero) {
            [void][NexusWtsProbe]::CloseHandle($token)
        }
    }

    return [ordered]@{
        runner_identity_class = $runnerClass
        interactive_console_session_present = $hasInteractiveSession
        interactive_explorer_present = (@(Get-Process -Name explorer -ErrorAction SilentlyContinue).Count -gt 0)
        wts_user_token_available = $tokenAvailable
        wts_user_token_error = $tokenError
        bybit_watchdog_path_exists = (Test-Path -LiteralPath 'C:\ProgramData\NEXUS\BybitWSL\watchdog.ps1' -PathType Leaf)
        bybit_launcher_root_exists = (Test-Path -LiteralPath 'C:\ProgramData\NEXUS\BybitWSL' -PathType Container)
    }
}

function Get-EvidenceTarget {
    $target = [IO.Path]::GetFullPath($OutputPath)
    $parent = Split-Path -Parent $target
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    return $target
}

function Write-ResolutionFailure {
    param([string]$Decision, [int]$CandidateCount = 0, [int]$MatchCount = 0)
    $target = Get-EvidenceTarget
    $payload = [ordered]@{
        schema_version = 1
        generated_at_utc = [DateTime]::UtcNow.ToString('o')
        source_run_id = if ($SourceRunId) { $SourceRunId } else { [string]$env:GITHUB_RUN_ID }
        source_sha = if ($SourceSha) { $SourceSha } else { [string]$env:GITHUB_SHA }
        source_conclusion = if ($SourceConclusion) { $SourceConclusion } else { 'diagnostic_push' }
        repository = [string]$env:GITHUB_REPOSITORY
        runner_name = $RunnerName
        runner_root = $RunnerRoot
        distribution_candidate_count = $CandidateCount
        distribution_match_count = $MatchCount
        runner_health_verified = $false
        recovery_request_performed = $false
        runner_mutation_performed = $false
        windows_runner_paths_modified = $false
        bybit_private_credentials_used = $false
        raw_diagnostic_files_uploaded = $false
        decision = $Decision
    }
    $json = $payload | ConvertTo-Json -Depth 8
    [IO.File]::WriteAllText($target, $json, (New-Object Text.UTF8Encoding($false)))
}

function Write-ContextLimitedEvidence {
    param(
        [string]$ScheduledTaskName = '',
        [bool]$ScheduledTaskVisible = $false,
        [bool]$ScheduledTaskQueryAccessDenied = $false,
        [int]$InventoryExitCode = 0,
        [Parameter(Mandatory = $true)][System.Collections.IDictionary]$UserContext
    )
    $target = Get-EvidenceTarget
    $payload = [ordered]@{
        schema_version = 2
        generated_at_utc = [DateTime]::UtcNow.ToString('o')
        source_run_id = if ($SourceRunId) { $SourceRunId } else { [string]$env:GITHUB_RUN_ID }
        source_sha = if ($SourceSha) { $SourceSha } else { [string]$env:GITHUB_SHA }
        source_conclusion = if ($SourceConclusion) { $SourceConclusion } else { 'diagnostic_push' }
        repository = [string]$env:GITHUB_REPOSITORY
        runner_name = $RunnerName
        runner_root = $RunnerRoot
        wsl_inventory_exit_code = $InventoryExitCode
        distribution_candidate_count = 0
        distribution_match_count = 0
        scheduled_recovery_task_visible = $ScheduledTaskVisible
        scheduled_recovery_task_name = $ScheduledTaskName
        scheduled_recovery_task_query_access_denied = $ScheduledTaskQueryAccessDenied
        runner_identity_class = $UserContext.runner_identity_class
        interactive_console_session_present = $UserContext.interactive_console_session_present
        interactive_explorer_present = $UserContext.interactive_explorer_present
        wts_user_token_available = $UserContext.wts_user_token_available
        wts_user_token_error = $UserContext.wts_user_token_error
        bybit_watchdog_path_exists = $UserContext.bybit_watchdog_path_exists
        bybit_launcher_root_exists = $UserContext.bybit_launcher_root_exists
        runner_health_verified = $false
        recovery_request_performed = $false
        runner_mutation_performed = $false
        scheduled_task_mutated = $false
        windows_runner_paths_modified = $false
        bybit_private_credentials_used = $false
        raw_diagnostic_files_uploaded = $false
        decision = 'WSL_DISTRIBUTION_NOT_VISIBLE_FROM_WINDOWS_RUNNER_CONTEXT'
    }
    $json = $payload | ConvertTo-Json -Depth 8
    [IO.File]::WriteAllText($target, $json, (New-Object Text.UTF8Encoding($false)))
}

$inventory = Invoke-WslNative -Arguments @('-l', '-q')
$candidates = @()
if ($inventory.exit_code -eq 0) {
    $candidates = @(
        $inventory.output -split "`r?`n" |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ -and $_ -match '^[A-Za-z0-9._ -]+$' } |
            Select-Object -Unique
    )
}

if ($inventory.exit_code -ne 0 -or -not $candidates) {
    $recoveryTask = Get-VisibleRecoveryTask
    $userContext = Get-UserContextCapability
    Write-ContextLimitedEvidence `
        -ScheduledTaskName $recoveryTask.name `
        -ScheduledTaskVisible $recoveryTask.found `
        -ScheduledTaskQueryAccessDenied $recoveryTask.query_access_denied `
        -InventoryExitCode $inventory.exit_code `
        -UserContext $userContext

    Write-Host "runner_identity_class=$($userContext.runner_identity_class)"
    Write-Host "interactive_console_session_present=$($userContext.interactive_console_session_present.ToString().ToLowerInvariant())"
    Write-Host "interactive_explorer_present=$($userContext.interactive_explorer_present.ToString().ToLowerInvariant())"
    Write-Host "wts_user_token_available=$($userContext.wts_user_token_available.ToString().ToLowerInvariant())"
    Write-Host "wts_user_token_error=$($userContext.wts_user_token_error)"
    Write-Host "scheduled_recovery_task_visible=$($recoveryTask.found.ToString().ToLowerInvariant())"
    Write-Host "scheduled_recovery_task_query_access_denied=$($recoveryTask.query_access_denied.ToString().ToLowerInvariant())"
    Write-Host "bybit_watchdog_path_exists=$($userContext.bybit_watchdog_path_exists.ToString().ToLowerInvariant())"
    Write-Host 'diagnostic_decision=WSL_DISTRIBUTION_NOT_VISIBLE_FROM_WINDOWS_RUNNER_CONTEXT'
    Write-Host 'runner_health_verified=false'
    Write-Host 'bybit_wsl_runner_diagnostics_validation=CONTEXT_LIMITED'
    exit 0
}

$matches = New-Object System.Collections.Generic.List[string]
foreach ($candidate in $candidates) {
    $probeCommand = "test -x '$RunnerRoot/run.sh' && test -f '$RunnerRoot/.runner' && grep -Eq 'agentName[^,]*$RunnerName' '$RunnerRoot/.runner'"
    $probe = Invoke-WslNative -Arguments @('-d', $candidate, '-u', 'root', '--', 'bash', '-lc', $probeCommand)
    if ($probe.exit_code -eq 0) { $matches.Add($candidate) }
}

if ($matches.Count -ne 1) {
    Write-ResolutionFailure -Decision 'WSL_RUNNER_DISTRIBUTION_NOT_UNIQUE' -CandidateCount $candidates.Count -MatchCount $matches.Count
    throw "Expected exactly one WSL distribution containing the pinned NEXUS Bybit runner; found $($matches.Count)."
}

$resolvedDistribution = $matches[0]
$sourceRun = if ($SourceRunId) { $SourceRunId } else { [string]$env:GITHUB_RUN_ID }
$sourceHead = if ($SourceSha) { $SourceSha } else { [string]$env:GITHUB_SHA }
$sourceResult = if ($SourceConclusion) { $SourceConclusion } else { 'diagnostic_push' }

& "$PSScriptRoot\capture_nexus_bybit_wsl_runner_diagnostics.ps1" `
    -OutputPath $OutputPath `
    -Distribution $resolvedDistribution `
    -RunnerRoot $RunnerRoot `
    -SourceRunId $sourceRun `
    -SourceSha $sourceHead `
    -SourceConclusion $sourceResult

$target = [IO.Path]::GetFullPath($OutputPath)
if (-not (Test-Path -LiteralPath $target -PathType Leaf)) { throw 'Diagnostics evidence was not produced.' }
$evidence = Get-Content -LiteralPath $target -Raw | ConvertFrom-Json
if ($evidence.decision -ne 'RUNNER_DIAGNOSTICS_CAPTURED') { throw "Unexpected diagnostics decision: $($evidence.decision)" }
if ($evidence.distribution -ne $resolvedDistribution) { throw 'Resolved distribution mismatch.' }
foreach ($field in @('wsl_status','runner_processes','resources','diag_inventory','diag_signals')) {
    if ([int]$evidence.$field.exit_code -ne 0) { throw "Diagnostics probe failed: $field" }
}

Write-Host "resolved_bybit_wsl_distribution=$resolvedDistribution"
Write-Host 'bybit_wsl_runner_diagnostics_validation=PASS'
exit 0
