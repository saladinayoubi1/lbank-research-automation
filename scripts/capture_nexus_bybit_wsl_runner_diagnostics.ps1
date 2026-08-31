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

# The physical Bybit WSL instance can be intentionally minimal. Keep every Linux
# diagnostic probe read-only and dependent only on bash builtins plus procfs so
# missing coreutils cannot hide the runner state we are trying to observe.
$wslStatusCommand = @'
printf 'kernel='
if [ -r /proc/sys/kernel/osrelease ] && IFS= read -r kernel < /proc/sys/kernel/osrelease; then printf '%s\n' "$kernel"; else printf 'unknown\n'; fi
printf 'pid1='
if [ -r /proc/1/comm ] && IFS= read -r pid1 < /proc/1/comm; then printf '%s\n' "$pid1"; else printf 'unknown\n'; fi
printf 'runner_root='
if [ -d '__RUNNER_ROOT__' ]; then printf 'present\n'; else printf 'missing\n'; fi
'@
$wslStatusCommand = $wslStatusCommand.Replace('__RUNNER_ROOT__', $RunnerRoot)

$processStatusCommand = @'
found=0
for proc in /proc/[0-9]*; do
    [ -r "$proc/comm" ] || continue
    comm=''
    IFS= read -r comm < "$proc/comm" || true
    case "$comm" in
        Runner.Listener|Runner.Worker|dotnet)
            pid=${proc##*/}
            printf '%s pid=%s\n' "$comm" "$pid"
            found=1
            ;;
    esac
done
if [ "$found" -eq 0 ]; then printf 'no_runner_processes_detected\n'; fi
'@

$resourceStatusCommand = @'
printf '[loadavg]\n'
if [ -r /proc/loadavg ] && IFS= read -r line < /proc/loadavg; then printf '%s\n' "$line"; else printf 'unavailable\n'; fi
printf '[uptime]\n'
if [ -r /proc/uptime ] && IFS= read -r line < /proc/uptime; then printf '%s\n' "$line"; else printf 'unavailable\n'; fi
printf '[meminfo]\n'
if [ -r /proc/meminfo ]; then
    count=0
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in
            MemTotal:*|MemAvailable:*|MemFree:*|SwapTotal:*|SwapFree:*)
                printf '%s\n' "$line"
                count=$((count + 1))
                ;;
        esac
        [ "$count" -ge 5 ] && break
    done < /proc/meminfo
else
    printf 'unavailable\n'
fi
printf 'runner_root_writable='
if [ -w '__RUNNER_ROOT__' ]; then printf 'yes\n'; else printf 'no\n'; fi
'@
$resourceStatusCommand = $resourceStatusCommand.Replace('__RUNNER_ROOT__', $RunnerRoot)

$diagInventoryCommand = @'
if [ -d '__RUNNER_ROOT__/_diag' ]; then
    count=0
    for file in '__RUNNER_ROOT__'/_diag/*.log; do
        [ -f "$file" ] || continue
        printf '%s\n' "${file##*/}"
        count=$((count + 1))
        [ "$count" -ge 300 ] && break
    done
    if [ "$count" -eq 0 ]; then printf 'diag_logs_missing\n'; fi
else
    printf 'diag_directory_missing\n'
fi
'@
$diagInventoryCommand = $diagInventoryCommand.Replace('__RUNNER_ROOT__', $RunnerRoot)

$diagSignalsCommand = @'
shopt -s nocasematch
signals=()
if [ -d '__RUNNER_ROOT__/_diag' ]; then
    for file in '__RUNNER_ROOT__'/_diag/*.log; do
        [ -f "$file" ] || continue
        while IFS= read -r line || [ -n "$line" ]; do
            if [[ "$line" =~ error|exception|failed|failure|exit[[:space:]]+code|terminated|killed|out[[:space:]]+of[[:space:]]+memory|segmentation|permission[[:space:]]+denied|no[[:space:]]+space[[:space:]]+left|resource[[:space:]]+temporarily[[:space:]]+unavailable|Runner\.Worker|Runner\.Listener|job[[:space:]]+message|connection ]]; then
                signals+=("$line")
                if [ "${#signals[@]}" -gt 240 ]; then
                    signals=("${signals[@]:1}")
                fi
            fi
        done < "$file"
    done
fi
if [ "${#signals[@]}" -gt 0 ]; then printf '%s\n' "${signals[@]}"; fi
'@
$diagSignalsCommand = $diagSignalsCommand.Replace('__RUNNER_ROOT__', $RunnerRoot)

$wslStatus = Invoke-WslCapture -Command $wslStatusCommand
$processStatus = Invoke-WslCapture -Command $processStatusCommand
$resourceStatus = Invoke-WslCapture -Command $resourceStatusCommand
$diagInventory = Invoke-WslCapture -Command $diagInventoryCommand
$diagSignals = Invoke-WslCapture -Command $diagSignalsCommand

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
