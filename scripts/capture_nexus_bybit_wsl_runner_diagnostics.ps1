param(
    [string]$OutputPath = "build\bybit-wsl-runner-diagnostics\evidence.json",
    [string]$Distribution = "Ubuntu",
    [string]$RunnerRoot = "/opt/nexus-bybit-runner",
    [string]$SourceRunId = "",
    [string]$SourceSha = "",
    [string]$SourceConclusion = ""
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

if ($Distribution -notmatch '^[A-Za-z0-9._-]+$') {
    throw 'Distribution must use only safe identifier characters.'
}
if ($RunnerRoot -ne '/opt/nexus-bybit-runner') {
    throw 'RunnerRoot must remain pinned to the isolated NEXUS Bybit runner root.'
}

function Invoke-WslCapture {
    param([Parameter(Mandatory = $true)][string]$Command)

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $raw = @(& "$env:SystemRoot\System32\wsl.exe" -d $Distribution -u root -- bash -lc $Command 2>&1)
        $exitCode = $LASTEXITCODE
        $text = (($raw | ForEach-Object { $_.ToString() }) | Out-String)
        return [ordered]@{
            exit_code = if ($null -eq $exitCode) { -1 } else { [int]$exitCode }
            output = ($text -replace "`0", '').Trim()
        }
    }
    catch {
        return [ordered]@{
            exit_code = -1
            output = $_.Exception.GetType().FullName
        }
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

function Protect-DiagnosticLine {
    param([Parameter(Mandatory = $true)][string]$Line)

    $value = $Line
    $value = [regex]::Replace($value, 'https?://\S+', '[url]', 'IgnoreCase')
    $value = [regex]::Replace(
        $value,
        '(?i)(authorization|bearer|token|secret|password)\s*[:=]\s*\S+',
        '$1=[redacted]'
    )
    $value = [regex]::Replace(
        $value,
        '(?<![A-Za-z0-9])[A-Za-z0-9_+/=-]{32,}(?![A-Za-z0-9])',
        '[opaque]'
    )
    if ($value.Length -gt 500) {
        $value = $value.Substring(0, 500)
    }
    return $value
}

function Protect-DiagnosticOutput {
    param([string]$Text, [int]$Limit = 200)

    if (-not $Text) {
        return @()
    }
    $lines = @(
        $Text -split "`r?`n" |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ } |
            Select-Object -Last $Limit
    )
    return @($lines | ForEach-Object { Protect-DiagnosticLine -Line $_ })
}

$sourceRun = if ($SourceRunId) { $SourceRunId } else { [string]$env:GITHUB_RUN_ID }
$sourceHead = if ($SourceSha) { $SourceSha } else { [string]$env:GITHUB_SHA }
$sourceResult = if ($SourceConclusion) { $SourceConclusion } else { 'diagnostic_push' }
$taskName = 'NEXUS Bybit WSL Runner'

$taskState = $null
$taskLastResult = $null
$taskFound = $false
$taskErrorClass = $null
try {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
    $taskInfo = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction Stop
    $taskFound = $true
    $taskState = [string]$task.State
    $taskLastResult = [int64]$taskInfo.LastTaskResult
}
catch {
    $taskErrorClass = $_.Exception.GetType().FullName
}

$wslStatus = Invoke-WslCapture -Command "printf 'kernel='; uname -r; printf 'pid1='; ps -p 1 -o comm=; printf 'runner_root='; test -d '$RunnerRoot' && echo present || echo missing"
$processStatus = Invoke-WslCapture -Command "ps -eo comm= 2>/dev/null | grep -E '^(Runner\\.(Listener|Worker)|dotnet)$' | sort | uniq -c || true"
$resourceStatus = Invoke-WslCapture -Command "df -Pk '$RunnerRoot' 2>/dev/null | tail -n 1; awk '/MemTotal:|MemAvailable:/ {print `$1, `$2}' /proc/meminfo 2>/dev/null"
$diagInventory = Invoke-WslCapture -Command "if [ -d '$RunnerRoot/_diag' ]; then find '$RunnerRoot/_diag' -maxdepth 1 -type f -name '*.log' -printf '%T@ %f %s\\n' 2>/dev/null | sort -nr | head -n 12; else echo diag_directory_missing; fi"
$diagSignals = Invoke-WslCapture -Command "if [ -d '$RunnerRoot/_diag' ]; then grep -hEia 'error|exception|failed|failure|exit code|terminated|killed|out of memory|segmentation|permission denied|no space left|resource temporarily unavailable|Runner\\.Worker|Runner\\.Listener|job message|connection' '$RunnerRoot'/_diag/*.log 2>/dev/null | tail -n 240 || true; fi"

$safeSignals = Protect-DiagnosticOutput -Text $diagSignals.output -Limit 240
$signalText = ($safeSignals -join "`n").ToLowerInvariant()
$categories = New-Object System.Collections.Generic.List[string]
$categoryPatterns = [ordered]@{
    out_of_memory = 'out of memory|outofmemoryexception|oom'
    no_space_left = 'no space left'
    permission_denied = 'permission denied|unauthorizedaccessexception'
    resource_exhaustion = 'resource temporarily unavailable|too many open files'
    segmentation_fault = 'segmentation fault|segfault'
    worker_exit = 'runner\.worker.*exit|worker.*exit code|runner worker.*exit'
    listener_failure = 'runner\.listener.*error|listener.*failed|listener.*exception'
    dotnet_exception = 'system\.[a-z0-9_.]+exception'
    connection_failure = 'connection.*failed|connection.*error|connection reset|connection refused'
    job_cancelled = 'job.*cancel|cancellationtoken'
}
foreach ($entry in $categoryPatterns.GetEnumerator()) {
    if ($signalText -match $entry.Value) {
        $categories.Add([string]$entry.Key)
    }
}

$evidence = [ordered]@{
    schema_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString('o')
    source_run_id = $sourceRun
    source_sha = $sourceHead
    source_conclusion = $sourceResult
    repository = [string]$env:GITHUB_REPOSITORY
    distribution = $Distribution
    runner_root = $RunnerRoot
    runner_name = 'NEXUS-BYBIT-WSL'
    runner_label = 'nexus-bybit-network'
    scheduled_task = [ordered]@{
        name = $taskName
        found = $taskFound
        state = $taskState
        last_result = $taskLastResult
        error_class = $taskErrorClass
    }
    wsl_status = [ordered]@{
        exit_code = $wslStatus.exit_code
        lines = Protect-DiagnosticOutput -Text $wslStatus.output -Limit 20
    }
    runner_processes = [ordered]@{
        exit_code = $processStatus.exit_code
        lines = Protect-DiagnosticOutput -Text $processStatus.output -Limit 20
    }
    resources = [ordered]@{
        exit_code = $resourceStatus.exit_code
        lines = Protect-DiagnosticOutput -Text $resourceStatus.output -Limit 20
    }
    diag_inventory = [ordered]@{
        exit_code = $diagInventory.exit_code
        lines = Protect-DiagnosticOutput -Text $diagInventory.output -Limit 20
    }
    diag_signals = [ordered]@{
        exit_code = $diagSignals.exit_code
        categories = @($categories)
        sanitized_lines = @($safeSignals)
    }
    runner_mutation_performed = $false
    windows_runner_paths_modified = $false
    bybit_private_credentials_used = $false
    raw_diagnostic_files_uploaded = $false
    decision = 'RUNNER_DIAGNOSTICS_CAPTURED'
}

$target = [IO.Path]::GetFullPath($OutputPath)
$parent = Split-Path -Parent $target
New-Item -ItemType Directory -Path $parent -Force | Out-Null
$json = $evidence | ConvertTo-Json -Depth 10
[IO.File]::WriteAllText($target, $json, (New-Object Text.UTF8Encoding($false)))
$digest = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host 'bybit_wsl_runner_diagnostics=RUNNER_DIAGNOSTICS_CAPTURED'
Write-Host "diagnostic_categories=$((@($categories) -join ','))"
Write-Host 'runner_mutation_performed=false'
Write-Host 'windows_runner_paths_modified=false'
Write-Host 'bybit_private_credentials_used=false'
Write-Host "evidence_sha256=$digest"
