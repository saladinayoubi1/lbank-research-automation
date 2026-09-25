[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$ExpectedSourceSha,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^http://127\.0\.0\.1:[0-9]{2,5}$')]
    [string]$Origin,

    [string]$Repository = 'saladinayoubi1/lbank-research-automation',
    [string]$WorkflowFile = 'fast-agent-coordinator.yml'
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$ExpectedSourceSha = $ExpectedSourceSha.ToLowerInvariant()

$root = Join-Path $env:LOCALAPPDATA 'NEXUS\MissionSync'
$statePath = Join-Path $root 'state.json'
$logPath = Join-Path $root 'mission-sync.log'
New-Item -ItemType Directory -Force -Path $root | Out-Null

function Write-SyncLog([string]$Message) {
    try {
        if (Test-Path -LiteralPath $logPath -PathType Leaf) {
            $info = Get-Item -LiteralPath $logPath
            if ($info.Length -gt 524288) {
                $archive = "$logPath.1"
                Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
                Move-Item -LiteralPath $logPath -Destination $archive -Force
            }
        }
        Add-Content -LiteralPath $logPath -Encoding utf8 -Value ('[{0}] {1}' -f [DateTime]::UtcNow.ToString('o'), $Message)
    } catch {}
}

function Read-JsonObject([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $info = Get-Item -LiteralPath $Path
    if (($info.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "reparse-point file rejected: $Path" }
    if ($info.Length -lt 2 -or $info.Length -gt 2097152) { throw "bounded JSON file rejected: $Path" }
    $value = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    if ($null -eq $value) { throw "JSON object missing: $Path" }
    return $value
}

function Write-State([hashtable]$Payload) {
    $tmp = "$statePath.tmp"
    [IO.File]::WriteAllText($tmp, ($Payload | ConvertTo-Json -Depth 6), (New-Object Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $tmp -Destination $statePath -Force
}

function Invoke-GhJson([string[]]$Arguments) {
    $gh = Get-Command gh.exe -ErrorAction Stop
    $raw = & $gh.Source @Arguments
    if ($LASTEXITCODE -ne 0) { throw "gh command failed: $($Arguments[0])" }
    return ($raw | Out-String | ConvertFrom-Json)
}

try {
    $uri = [Uri]$Origin
    if ($uri.Scheme -ne 'http' -or $uri.Host -ne '127.0.0.1' -or $uri.AbsolutePath -ne '/') {
        throw 'Mission sync origin must be loopback HTTP root only.'
    }

    $gh = Get-Command gh.exe -ErrorAction Stop
    & $gh.Source auth status --hostname github.com *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-SyncLog 'status=DEGRADED reason=gh_auth_unavailable'
        Write-Output 'NEXUS_MISSION_SYNC=DEGRADED reason=gh_auth_unavailable'
        exit 20
    }

    $runsResponse = Invoke-GhJson @(
        'api',
        "repos/$Repository/actions/workflows/$WorkflowFile/runs?branch=main&status=success&per_page=20"
    )
    $runs = @(
        $runsResponse.workflow_runs |
            Where-Object {
                $_.conclusion -eq 'success' -and
                $_.head_branch -eq 'main' -and
                ([string]$_.head_sha).ToLowerInvariant() -eq $ExpectedSourceSha
            } |
            Sort-Object { [DateTime]$_.created_at } -Descending
    )
    if ($runs.Count -lt 1) {
        Write-SyncLog "status=WAITING reason=no_exact_source_snapshot source=$ExpectedSourceSha"
        Write-Output "NEXUS_MISSION_SYNC=WAITING source=$ExpectedSourceSha"
        exit 0
    }

    $run = $runs[0]
    $runId = [long]$run.id
    $artifactName = "fast-agent-status-$runId"
    $artifactResponse = Invoke-GhJson @('api', "repos/$Repository/actions/runs/$runId/artifacts?per_page=100")
    $matches = @(
        $artifactResponse.artifacts |
            Where-Object {
                $_.name -eq $artifactName -and
                -not [bool]$_.expired -and
                [long]$_.workflow_run.id -eq $runId
            }
    )
    if ($matches.Count -ne 1) { throw "exact Fast Agent artifact is missing or ambiguous for run $runId" }
    $artifact = $matches[0]
    if ([long]$artifact.size_in_bytes -lt 1 -or [long]$artifact.size_in_bytes -gt 5242880) {
        throw 'Fast Agent artifact exceeds bounded sync size.'
    }

    $previous = Read-JsonObject $statePath
    if ($null -ne $previous -and [string]$previous.last_run_id -eq [string]$runId -and
        ([string]$previous.source_sha).ToLowerInvariant() -eq $ExpectedSourceSha) {
        Write-Output "NEXUS_MISSION_SYNC=NOOP run=$runId source=$ExpectedSourceSha"
        exit 0
    }

    $downloadRoot = Join-Path $env:TEMP "nexus-mission-sync-$runId"
    Remove-Item -LiteralPath $downloadRoot -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $downloadRoot | Out-Null

    & $gh.Source run download $runId --repo $Repository --name $artifactName --dir $downloadRoot
    if ($LASTEXITCODE -ne 0) { throw "Fast Agent artifact download failed for run $runId" }

    $snapshotPath = Join-Path $downloadRoot 'nexus-mission-control-snapshot.json'
    $snapshot = Read-JsonObject $snapshotPath
    if ($snapshot.contract_version -ne 'nexus.agent-manager-snapshot.v1') { throw 'mission snapshot contract mismatch' }
    if ($snapshot.paper_only -ne $true -or $snapshot.live_trading_authority -ne $false) { throw 'mission snapshot widened trading authority' }
    if ($snapshot.source -ne 'github-cloud-coordinator') { throw 'mission snapshot source mismatch' }
    if ($null -eq $snapshot.runtime -or $snapshot.runtime.schema_version -ne 1) { throw 'mission snapshot lacks real Agent Manager runtime' }
    if ($snapshot.config.schema_version -ne 1 -or $null -eq $snapshot.config.workers -or $null -eq $snapshot.config.tasks) {
        throw 'mission snapshot configuration is invalid'
    }
    $generatedAt = [DateTimeOffset]::Parse([string]$snapshot.generated_at)
    if ($generatedAt -gt [DateTimeOffset]::UtcNow.AddMinutes(5)) { throw 'mission snapshot timestamp is in the future' }

    $localImport = Join-Path $env:APPDATA 'nexus-personal-pro-product\product-data\agent_coordination\imported_mission_snapshot.json'
    $existing = Read-JsonObject $localImport
    if ($null -ne $existing -and $existing.contract_version -eq 'nexus.agent-manager-snapshot.v1') {
        try {
            $existingAt = [DateTimeOffset]::Parse([string]$existing.generated_at)
            if ($existingAt -gt $generatedAt) {
                Write-SyncLog "status=NOOP reason=local_snapshot_newer candidate_run=$runId"
                Write-Output "NEXUS_MISSION_SYNC=NOOP reason=local_snapshot_newer run=$runId"
                exit 0
            }
        } catch {}
    }

    $raw = Get-Content -LiteralPath $snapshotPath -Raw
    $imported = Invoke-RestMethod -Method Post -Uri "$Origin/api/product/mission/import" -ContentType 'application/json' -Body $raw -TimeoutSec 20
    if ($imported.status -ne 'imported' -or $imported.contract_version -ne 'nexus.product-mission-control.v1') {
        throw 'product Mission Control rejected canonical snapshot'
    }

    $full = Invoke-RestMethod -Method Get -Uri "$Origin/api/product/mission/full" -TimeoutSec 15
    if ($full.source -ne 'imported_snapshot' -or $full.control_plane.runtime_present -ne $true) {
        throw 'Mission Control did not expose imported runtime'
    }
    if ($full.paper_only -ne $true -or $full.live_trading_authority -ne $false) {
        throw 'Mission Control widened authority after import'
    }
    if ([string]$full.generated_at -ne [string]$snapshot.generated_at) {
        throw 'Mission Control generated_at does not match imported snapshot'
    }

    Write-State @{
        schema_version = 'nexus.mission-sync.v1'
        synced_at = [DateTime]::UtcNow.ToString('o')
        source_sha = $ExpectedSourceSha
        last_run_id = [string]$runId
        artifact_id = [string]$artifact.id
        snapshot_generated_at = [string]$snapshot.generated_at
        workers = @($full.workers).Count
        resources = @($full.resources).Count
        paper_only = $true
        live_trading_authority = $false
    }
    Write-SyncLog "status=PASS run=$runId artifact=$($artifact.id) source=$ExpectedSourceSha workers=$(@($full.workers).Count)"
    Write-Output "NEXUS_MISSION_SYNC=PASS run=$runId artifact=$($artifact.id) source=$ExpectedSourceSha"
    Remove-Item -LiteralPath $downloadRoot -Recurse -Force -ErrorAction SilentlyContinue
    exit 0
}
catch {
    $message = [string]$_.Exception.Message
    Write-SyncLog ('status=FAILED reason=' + ($message -replace '[\r\n]+',' '))
    Write-Error "NEXUS_MISSION_SYNC=FAILED $message"
    exit 1
}
