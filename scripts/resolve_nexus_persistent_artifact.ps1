[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [ValidatePattern('^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')] [string]$Repository,
    [Parameter(Mandatory = $true)] [ValidatePattern('^[0-9a-fA-F]{40}$')] [string]$SourceSha,
    [string]$WorkflowFile = 'nexus-build-verification.yml',
    [string]$ArtifactName = 'nexus-windows-persistent-unpacked'
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$SourceSha = $SourceSha.ToLowerInvariant()
$repositoryOwner = ($Repository -split '/', 2)[0]

if (-not $env:GITHUB_TOKEN) { throw 'GITHUB_TOKEN is required for exact artifact resolution.' }
if (-not $env:GITHUB_OUTPUT) { throw 'GITHUB_OUTPUT is required for exact artifact resolution.' }

$apiBase = if ($env:GITHUB_API_URL) { $env:GITHUB_API_URL.TrimEnd('/') } else { 'https://api.github.com' }
$headers = @{
    Authorization = "Bearer $($env:GITHUB_TOKEN)"
    Accept = 'application/vnd.github+json'
    'X-GitHub-Api-Version' = '2022-11-28'
    'User-Agent' = 'nexus-selfhost-artifact-resolver/1'
}

$workflowSegment = [Uri]::EscapeDataString($WorkflowFile)
$runsUrl = "$apiBase/repos/$Repository/actions/workflows/$workflowSegment/runs?head_sha=$SourceSha&status=success&per_page=20"
$runsResponse = Invoke-RestMethod -Method Get -Uri $runsUrl -Headers $headers -TimeoutSec 30
$runs = @(
    $runsResponse.workflow_runs |
        Where-Object {
            ([string]$_.head_sha).ToLowerInvariant() -eq $SourceSha -and
            [string]$_.conclusion -eq 'success' -and
            [string]$_.event -in @('push', 'workflow_dispatch') -and
            [string]$_.head_branch -eq 'main' -and
            [string]$_.actor.login -eq $repositoryOwner
        } |
        Sort-Object { [DateTime]$_.created_at } -Descending
)
if ($runs.Count -lt 1) {
    throw "No successful owner-triggered main $WorkflowFile run exists for exact source $SourceSha."
}

$selectedRun = $null
$selectedArtifact = $null
foreach ($run in $runs) {
    $artifactsUrl = "$apiBase/repos/$Repository/actions/runs/$($run.id)/artifacts?per_page=100"
    $artifactsResponse = Invoke-RestMethod -Method Get -Uri $artifactsUrl -Headers $headers -TimeoutSec 30
    $matches = @(
        $artifactsResponse.artifacts |
            Where-Object {
                [string]$_.name -eq $ArtifactName -and
                -not [bool]$_.expired -and
                ([string]$_.workflow_run.head_sha).ToLowerInvariant() -eq $SourceSha
            }
    )
    if ($matches.Count -eq 1) {
        $selectedRun = $run
        $selectedArtifact = $matches[0]
        break
    }
    if ($matches.Count -gt 1) {
        throw "Multiple non-expired $ArtifactName artifacts exist for exact source $SourceSha in run $($run.id)."
    }
}

if ($null -eq $selectedRun -or $null -eq $selectedArtifact) {
    throw "No non-expired $ArtifactName artifact exists for exact source $SourceSha."
}

$digest = ([string]$selectedArtifact.digest).ToLowerInvariant()
if ($digest -notmatch '^sha256:([0-9a-f]{64})$') { throw 'Resolved artifact digest is not a valid SHA-256 digest.' }
$archiveSha256 = $Matches[1]
$archiveBytes = [long]$selectedArtifact.size_in_bytes
if ($archiveBytes -lt 1) { throw 'Resolved artifact size must be positive.' }
if ([long]$selectedArtifact.workflow_run.id -ne [long]$selectedRun.id) { throw 'Resolved artifact run binding mismatch.' }

$outputs = [ordered]@{
    artifact_run_id = [string]$selectedRun.id
    artifact_id = [string]$selectedArtifact.id
    artifact_name = [string]$selectedArtifact.name
    source_sha = $SourceSha
    archive_sha256 = $archiveSha256
    archive_bytes = [string]$archiveBytes
}
foreach ($entry in $outputs.GetEnumerator()) {
    Add-Content -LiteralPath $env:GITHUB_OUTPUT -Value "$($entry.Key)=$($entry.Value)" -Encoding utf8
}

Write-Host "NEXUS_PERSISTENT_ARTIFACT_RESOLVE=PASS source=$SourceSha run=$($selectedRun.id) artifact=$($selectedArtifact.id) bytes=$archiveBytes"
