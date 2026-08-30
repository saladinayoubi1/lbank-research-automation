param(
    [string]$OutputPath = "build\bybit-wsl-runner-wake\evidence.json",
    [string]$RunnerName = "NEXUS-BYBIT-WSL",
    [string]$RunnerLabel = "nexus-bybit-network"
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$runnerRoot = '/opt/nexus-bybit-runner'
$wsl = Join-Path $env:SystemRoot 'System32\wsl.exe'

if ($RunnerName -ne 'NEXUS-BYBIT-WSL') { throw 'RunnerName must remain pinned.' }
if ($RunnerLabel -ne 'nexus-bybit-network') { throw 'RunnerLabel must remain pinned.' }
if (-not (Test-Path -LiteralPath $wsl -PathType Leaf)) { throw 'wsl.exe is required.' }

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
        return [ordered]@{
            exit_code = -1
            output = $_.Exception.GetType().FullName
        }
    }
    finally {
        $ErrorActionPreference = $previous
    }
}

function Write-ResolutionFailure {
    param(
        [Parameter(Mandatory = $true)][string]$Decision,
        [int]$CandidateCount = 0,
        [int]$MatchCount = 0
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
        runner_name = $RunnerName
        runner_label = $RunnerLabel
        wsl_runner_root = $runnerRoot
        distribution_candidate_count = $CandidateCount
        distribution_match_count = $MatchCount
        runner_mutation_performed = $false
        windows_runner_paths_modified = $false
        windows_runner_service_modified = $false
        github_registration_token_persisted = $false
        bybit_private_credentials_used = $false
        decision = $Decision
    }

    $json = $payload | ConvertTo-Json -Depth 8
    [IO.File]::WriteAllText($target, $json, (New-Object Text.UTF8Encoding($false)))
}

$inventory = Invoke-WslNative -Arguments @('-l', '-q')
if ($inventory.exit_code -ne 0) {
    Write-ResolutionFailure -Decision 'WSL_DISTRIBUTION_INVENTORY_FAILED'
    throw 'Unable to enumerate WSL distributions.'
}

$candidates = @(
    $inventory.output -split "`r?`n" |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ -and $_ -match '^[A-Za-z0-9._-]+$' } |
        Select-Object -Unique
)
if (-not $candidates) {
    Write-ResolutionFailure -Decision 'WSL_DISTRIBUTION_INVENTORY_EMPTY'
    throw 'No safe WSL distribution identifiers were found.'
}

$matches = New-Object System.Collections.Generic.List[string]
foreach ($candidate in $candidates) {
    $probeCommand = "test -x '$runnerRoot/run.sh' && test -f '$runnerRoot/.runner' && grep -Eq 'agentName[^,]*$RunnerName' '$runnerRoot/.runner'"
    $probe = Invoke-WslNative -Arguments @('-d', $candidate, '-u', 'root', '--', 'bash', '-lc', $probeCommand)
    if ($probe.exit_code -eq 0) {
        $matches.Add($candidate)
    }
}

if ($matches.Count -ne 1) {
    Write-ResolutionFailure -Decision 'WSL_RUNNER_DISTRIBUTION_NOT_UNIQUE' -CandidateCount $candidates.Count -MatchCount $matches.Count
    throw "Expected exactly one WSL distribution containing the pinned NEXUS Bybit runner; found $($matches.Count)."
}

$resolvedDistribution = $matches[0]
Write-Host "resolved_bybit_wsl_distribution=$resolvedDistribution"

& "$PSScriptRoot\start_nexus_bybit_wsl_runner_native.ps1" `
    -OutputPath $OutputPath `
    -Distribution $resolvedDistribution `
    -RunnerName $RunnerName `
    -RunnerLabel $RunnerLabel

$nativeExitCode = $LASTEXITCODE
if ($null -ne $nativeExitCode -and [int]$nativeExitCode -ne 0) {
    exit [int]$nativeExitCode
}

$target = [IO.Path]::GetFullPath($OutputPath)
if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
    throw 'Wake evidence was not produced.'
}

$evidence = Get-Content -LiteralPath $target -Raw | ConvertFrom-Json
if ($evidence.distribution -ne $resolvedDistribution) {
    throw 'Resolved WSL distribution does not match wake evidence.'
}
if ($evidence.runner_name -ne $RunnerName) {
    throw 'Wake evidence runner name mismatch.'
}
if ($evidence.bybit_private_credentials_used -ne $false) {
    throw 'Wake evidence violated private-credential invariant.'
}
if ($evidence.windows_runner_paths_modified -ne $false) {
    throw 'Wake evidence violated Windows runner path invariant.'
}
if ($evidence.windows_runner_service_modified -ne $false) {
    throw 'Wake evidence violated Windows runner service invariant.'
}

Write-Host 'bybit_wsl_runner_wake_resolution=PASS'
exit 0
