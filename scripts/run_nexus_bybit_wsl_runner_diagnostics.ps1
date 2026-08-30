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
        return [ordered]@{ found = $false; name = '' }
    }

    foreach ($taskName in @('NEXUS Bybit WSL Runner Persistent', 'NEXUS Bybit WSL Runner')) {
        $previous = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            $null = @(& $schTasks /Query /TN $taskName 2>&1)
            $code = $LASTEXITCODE
        }
        catch {
            $code = -1
        }
        finally {
            $ErrorActionPreference = $previous
        }
        if ($code -eq 0) {
            return [ordered]@{ found = $true; name = $taskName }
        }
    }

    return [ordered]@{ found = $false; name = '' }
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
        [Parameter(Mandatory = $true)][string]$ScheduledTaskName,
        [int]$InventoryExitCode = 0
    )
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
        wsl_inventory_exit_code = $InventoryExitCode
        distribution_candidate_count = 0
        distribution_match_count = 0
        scheduled_recovery_task_visible = $true
        scheduled_recovery_task_name = $ScheduledTaskName
        runner_health_verified = $false
        recovery_request_performed = $false
        runner_mutation_performed = $false
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
    # WSL distributions are registered per Windows user. NEXUS-WINDOWS-DR runs
    # as a Windows service, so an empty inventory does not prove that the
    # interactive user's Ubuntu/Bybit runner is absent. In that context we only
    # record the visibility boundary and the pre-existing Scheduled Task that
    # owns recovery. We do not claim runner health and we do not mutate it here.
    $recoveryTask = Get-VisibleRecoveryTask
    if ($recoveryTask.found) {
        Write-ContextLimitedEvidence -ScheduledTaskName $recoveryTask.name -InventoryExitCode $inventory.exit_code
        Write-Host "scheduled_recovery_task=$($recoveryTask.name)"
        Write-Host 'diagnostic_decision=WSL_DISTRIBUTION_NOT_VISIBLE_FROM_WINDOWS_RUNNER_CONTEXT'
        Write-Host 'runner_health_verified=false'
        Write-Host 'bybit_wsl_runner_diagnostics_validation=CONTEXT_LIMITED'
        exit 0
    }

    if ($inventory.exit_code -ne 0) {
        Write-ResolutionFailure -Decision 'WSL_DISTRIBUTION_INVENTORY_FAILED'
        throw 'Unable to enumerate WSL distributions and no approved recovery task is visible.'
    }

    Write-ResolutionFailure -Decision 'WSL_DISTRIBUTION_INVENTORY_EMPTY'
    throw 'No WSL distributions or approved recovery tasks were found.'
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
