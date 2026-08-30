param(
    [string]$OutputPath = "build\bybit-wsl-runner-wake\evidence.json",
    [string]$PreferredTask = "NEXUS Bybit WSL Runner Persistent",
    [string]$FallbackTask = "NEXUS Bybit WSL Runner"
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

if ($PreferredTask -ne 'NEXUS Bybit WSL Runner Persistent') { throw 'PreferredTask must remain pinned.' }
if ($FallbackTask -ne 'NEXUS Bybit WSL Runner') { throw 'FallbackTask must remain pinned.' }

$schtasks = Join-Path $env:SystemRoot 'System32\schtasks.exe'
if (-not (Test-Path -LiteralPath $schtasks -PathType Leaf)) { throw 'schtasks.exe is required.' }

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $raw = @(& $FilePath @Arguments 2>&1)
        $code = $LASTEXITCODE
        return [ordered]@{
            exit_code = if ($null -eq $code) { -1 } else { [int]$code }
        }
    }
    catch {
        return [ordered]@{ exit_code = -1 }
    }
    finally {
        $ErrorActionPreference = $previous
    }
}

function Write-Evidence {
    param(
        [Parameter(Mandatory = $true)][string]$Decision,
        [string]$SelectedTask = $null,
        [int]$PreferredQueryExitCode = -1,
        [int]$FallbackQueryExitCode = -1,
        [int]$RunExitCode = -1,
        [int]$PostQueryExitCode = -1
    )

    $target = [IO.Path]::GetFullPath($OutputPath)
    $parent = Split-Path -Parent $target
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $payload = [ordered]@{
        schema_version = 1
        generated_at_utc = [DateTime]::UtcNow.ToString('o')
        source_sha = [string]$env:GITHUB_SHA
        run_id = [string]$env:GITHUB_RUN_ID
        repository = [string]$env:GITHUB_REPOSITORY
        preferred_task = $PreferredTask
        fallback_task = $FallbackTask
        selected_task = $SelectedTask
        preferred_query_exit_code = $PreferredQueryExitCode
        fallback_query_exit_code = $FallbackQueryExitCode
        task_run_exit_code = $RunExitCode
        task_post_query_exit_code = $PostQueryExitCode
        task_definition_modified = $false
        runner_registration_modified = $false
        windows_runner_paths_modified = $false
        bybit_private_credentials_used = $false
        direct_wsl_invocation_performed = $false
        decision = $Decision
    }
    $json = $payload | ConvertTo-Json -Depth 6
    [IO.File]::WriteAllText($target, $json, (New-Object Text.UTF8Encoding($false)))
}

$preferredQuery = Invoke-Native -FilePath $schtasks -Arguments @('/Query', '/TN', $PreferredTask)
$fallbackQuery = [ordered]@{ exit_code = -1 }
$selectedTask = $null

if ($preferredQuery.exit_code -eq 0) {
    $selectedTask = $PreferredTask
}
else {
    $fallbackQuery = Invoke-Native -FilePath $schtasks -Arguments @('/Query', '/TN', $FallbackTask)
    if ($fallbackQuery.exit_code -eq 0) {
        $selectedTask = $FallbackTask
    }
}

if (-not $selectedTask) {
    Write-Evidence `
        -Decision 'NO_REGISTERED_BYBIT_WSL_TASK' `
        -PreferredQueryExitCode $preferredQuery.exit_code `
        -FallbackQueryExitCode $fallbackQuery.exit_code
    throw 'Neither pinned Bybit WSL scheduled task is registered.'
}

$run = Invoke-Native -FilePath $schtasks -Arguments @('/Run', '/TN', $selectedTask)
if ($run.exit_code -ne 0) {
    Write-Evidence `
        -Decision 'BYBIT_WSL_TASK_RUN_FAILED' `
        -SelectedTask $selectedTask `
        -PreferredQueryExitCode $preferredQuery.exit_code `
        -FallbackQueryExitCode $fallbackQuery.exit_code `
        -RunExitCode $run.exit_code
    throw 'Unable to request the pinned Bybit WSL scheduled task.'
}

Start-Sleep -Seconds 3
$postQuery = Invoke-Native -FilePath $schtasks -Arguments @('/Query', '/TN', $selectedTask)
if ($postQuery.exit_code -ne 0) {
    Write-Evidence `
        -Decision 'BYBIT_WSL_TASK_POST_QUERY_FAILED' `
        -SelectedTask $selectedTask `
        -PreferredQueryExitCode $preferredQuery.exit_code `
        -FallbackQueryExitCode $fallbackQuery.exit_code `
        -RunExitCode $run.exit_code `
        -PostQueryExitCode $postQuery.exit_code
    throw 'Pinned Bybit WSL task disappeared after the wake request.'
}

Write-Evidence `
    -Decision 'BYBIT_WSL_TASK_WAKE_REQUESTED' `
    -SelectedTask $selectedTask `
    -PreferredQueryExitCode $preferredQuery.exit_code `
    -FallbackQueryExitCode $fallbackQuery.exit_code `
    -RunExitCode $run.exit_code `
    -PostQueryExitCode $postQuery.exit_code

Write-Host "selected_bybit_wsl_task=$selectedTask"
Write-Host 'direct_wsl_invocation_performed=false'
Write-Host 'task_definition_modified=false'
Write-Host 'runner_registration_modified=false'
Write-Host 'bybit_wsl_task_wake_validation=PASS'
exit 0
