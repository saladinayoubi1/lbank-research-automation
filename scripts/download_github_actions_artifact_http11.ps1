[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [ValidatePattern('^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')] [string]$Repository,
    [Parameter(Mandatory = $true)] [long]$ArtifactRunId,
    [Parameter(Mandatory = $true)] [long]$ArtifactId,
    [Parameter(Mandatory = $true)] [string]$ArtifactName,
    [Parameter(Mandatory = $true)] [ValidatePattern('^[0-9a-fA-F]{40}$')] [string]$ExpectedSourceSha,
    [Parameter(Mandatory = $true)] [ValidatePattern('^[0-9a-fA-F]{64}$')] [string]$ExpectedArchiveSha256,
    [Parameter(Mandatory = $true)] [long]$ExpectedArchiveBytes,
    [Parameter(Mandatory = $true)] [string]$DestinationDirectory,
    [ValidateRange(1, 20)] [int]$MaxAttempts = 8
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$ExpectedSourceSha = $ExpectedSourceSha.ToLowerInvariant()
$ExpectedArchiveSha256 = $ExpectedArchiveSha256.ToLowerInvariant()

if (-not $env:GITHUB_TOKEN) { throw 'GITHUB_TOKEN is required for exact artifact download.' }
if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) { throw 'curl.exe is required for resilient artifact download.' }
if ($ExpectedArchiveBytes -lt 1) { throw 'Expected artifact size must be positive.' }

$apiBase = if ($env:GITHUB_API_URL) { $env:GITHUB_API_URL.TrimEnd('/') } else { 'https://api.github.com' }
$artifactApi = "$apiBase/repos/$Repository/actions/artifacts/$ArtifactId"
$metadataHeaders = @{
    Authorization = "Bearer $($env:GITHUB_TOKEN)"
    Accept = 'application/vnd.github+json'
    'X-GitHub-Api-Version' = '2022-11-28'
    'User-Agent' = 'nexus-selfhost-artifact-transport/1'
}
$metadata = Invoke-RestMethod -Method Get -Uri $artifactApi -Headers $metadataHeaders -TimeoutSec 30

if ([long]$metadata.id -ne $ArtifactId) { throw 'Artifact metadata ID mismatch.' }
if ([string]$metadata.name -ne $ArtifactName) { throw 'Artifact metadata name mismatch.' }
if ([bool]$metadata.expired) { throw 'Approved artifact is expired.' }
if ([long]$metadata.size_in_bytes -ne $ExpectedArchiveBytes) { throw 'Artifact metadata size mismatch.' }
if (([string]$metadata.digest).ToLowerInvariant() -ne "sha256:$ExpectedArchiveSha256") { throw 'Artifact metadata digest mismatch.' }
if ([long]$metadata.workflow_run.id -ne $ArtifactRunId) { throw 'Artifact workflow run binding mismatch.' }
if (([string]$metadata.workflow_run.head_sha).ToLowerInvariant() -ne $ExpectedSourceSha) { throw 'Artifact source SHA binding mismatch.' }

$runnerTemp = [IO.Path]::GetFullPath($env:RUNNER_TEMP).TrimEnd('\')
$destination = [IO.Path]::GetFullPath($DestinationDirectory).TrimEnd('\')
if (-not $destination.StartsWith($runnerTemp + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Artifact destination escaped RUNNER_TEMP.'
}
if ((Split-Path -Leaf $destination) -notmatch '^nexus-personal-pro-package-[0-9]+$') {
    throw 'Artifact destination does not match the bounded package transport name.'
}
$archivePath = Join-Path $runnerTemp "nexus-artifact-$ArtifactId.zip"

Add-Type -AssemblyName System.Net.Http
function Get-SignedArtifactUrl {
    $handler = New-Object System.Net.Http.HttpClientHandler
    $handler.AllowAutoRedirect = $false
    $client = New-Object System.Net.Http.HttpClient($handler)
    try {
        $request = New-Object System.Net.Http.HttpRequestMessage([System.Net.Http.HttpMethod]::Get, "$artifactApi/zip")
        $request.Headers.Authorization = New-Object System.Net.Http.Headers.AuthenticationHeaderValue('Bearer', $env:GITHUB_TOKEN)
        $request.Headers.Accept.ParseAdd('application/vnd.github+json')
        $request.Headers.UserAgent.ParseAdd('nexus-selfhost-artifact-transport/1')
        $response = $client.SendAsync($request).GetAwaiter().GetResult()
        try {
            if ([int]$response.StatusCode -notin @(301, 302, 307, 308)) {
                throw "Artifact redirect request failed with HTTP $([int]$response.StatusCode)."
            }
            $location = $response.Headers.Location
            if ($null -eq $location) { throw 'Artifact redirect did not provide a signed location.' }
            if (-not $location.IsAbsoluteUri) { $location = New-Object Uri(([Uri]$apiBase), $location) }
            if ($location.Scheme -ne 'https') { throw 'Artifact redirect must use HTTPS.' }
            return $location.AbsoluteUri
        }
        finally {
            $response.Dispose()
            $request.Dispose()
        }
    }
    finally {
        $client.Dispose()
        $handler.Dispose()
    }
}

$verified = $false
for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
    if (Test-Path -LiteralPath $archivePath -PathType Leaf) {
        $length = (Get-Item -LiteralPath $archivePath).Length
        if ($length -eq $ExpectedArchiveBytes) {
            $sha = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($sha -eq $ExpectedArchiveSha256) { $verified = $true; break }
            Remove-Item -LiteralPath $archivePath -Force
        }
        elseif ($length -gt $ExpectedArchiveBytes) {
            Remove-Item -LiteralPath $archivePath -Force
        }
    }

    $signedUrl = Get-SignedArtifactUrl
    try {
        & curl.exe --fail --silent --show-error --http1.1 --connect-timeout 20 --max-time 900 --retry 3 --retry-delay 2 --continue-at - --output $archivePath $signedUrl
        $curlExit = $LASTEXITCODE
    }
    finally {
        $signedUrl = $null
    }

    if (Test-Path -LiteralPath $archivePath -PathType Leaf) {
        $length = (Get-Item -LiteralPath $archivePath).Length
        if ($length -eq $ExpectedArchiveBytes) {
            $sha = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($sha -eq $ExpectedArchiveSha256) { $verified = $true; break }
            Remove-Item -LiteralPath $archivePath -Force
        }
    }
    Write-Warning "Artifact HTTP/1.1 transport attempt $attempt/$MaxAttempts incomplete (curl_exit=$curlExit)."
    if ($attempt -lt $MaxAttempts) { Start-Sleep -Seconds ([Math]::Min(5 * $attempt, 30)) }
}
if (-not $verified) { throw "Exact artifact download failed after $MaxAttempts bounded attempts." }

if (Test-Path -LiteralPath $destination) { Remove-Item -LiteralPath $destination -Recurse -Force }
New-Item -ItemType Directory -Path $destination | Out-Null
Expand-Archive -LiteralPath $archivePath -DestinationPath $destination -Force

$innerZip = Join-Path $destination 'NEXUS_Personal_Pro_Unpacked_5.1.0_x64.zip'
$sumFile = Join-Path $destination 'SHA256SUMS.txt'
if (-not (Test-Path -LiteralPath $innerZip -PathType Leaf) -or -not (Test-Path -LiteralPath $sumFile -PathType Leaf)) {
    throw 'Downloaded artifact archive did not contain the expected persistent package files.'
}

Remove-Item -LiteralPath $archivePath -Force
$env:GITHUB_TOKEN = $null
Write-Host "NEXUS_ARTIFACT_HTTP11_DOWNLOAD=PASS artifact=$ArtifactId run=$ArtifactRunId bytes=$ExpectedArchiveBytes"
