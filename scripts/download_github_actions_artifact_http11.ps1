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

$chunkBytes = 1MB
$parallelChunks = 4
$verified = $false

if (Test-Path -LiteralPath $archivePath -PathType Leaf) {
    $existingLength = [long](Get-Item -LiteralPath $archivePath).Length
    if ($existingLength -gt $ExpectedArchiveBytes) {
        Remove-Item -LiteralPath $archivePath -Force
    }
    elseif ($existingLength -gt 0 -and $existingLength -lt $ExpectedArchiveBytes) {
        $alignedLength = [long]([Math]::Floor($existingLength / $chunkBytes) * $chunkBytes)
        if ($alignedLength -ne $existingLength) {
            $stream = [IO.File]::Open($archivePath, [IO.FileMode]::Open, [IO.FileAccess]::Write, [IO.FileShare]::Read)
            try { $stream.SetLength($alignedLength) } finally { $stream.Dispose() }
        }
    }
}

while (-not $verified) {
    $currentLength = if (Test-Path -LiteralPath $archivePath -PathType Leaf) {
        [long](Get-Item -LiteralPath $archivePath).Length
    } else {
        0L
    }

    if ($currentLength -eq $ExpectedArchiveBytes) {
        $sha = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($sha -eq $ExpectedArchiveSha256) {
            $verified = $true
            break
        }
        Remove-Item -LiteralPath $archivePath -Force
        $currentLength = 0L
    }
    elseif ($currentLength -gt $ExpectedArchiveBytes) {
        Remove-Item -LiteralPath $archivePath -Force
        $currentLength = 0L
    }

    $batchSucceeded = $false
    for ($attempt = 1; $attempt -le $MaxAttempts -and -not $batchSucceeded; $attempt++) {
        $signedUrl = Get-SignedArtifactUrl
        $parts = @()
        try {
            for ($index = 0; $index -lt $parallelChunks; $index++) {
                $rangeStart = $currentLength + ([long]$index * $chunkBytes)
                if ($rangeStart -ge $ExpectedArchiveBytes) { break }
                $rangeEnd = [Math]::Min($rangeStart + $chunkBytes - 1, $ExpectedArchiveBytes - 1)
                $partPath = "$archivePath.part-$rangeStart-$rangeEnd"
                Remove-Item -LiteralPath $partPath -Force -ErrorAction SilentlyContinue
                $stderrPath = "$partPath.stderr"
                Remove-Item -LiteralPath $stderrPath -Force -ErrorAction SilentlyContinue
                $arguments = @(
                    '--fail',
                    '--silent',
                    '--show-error',
                    '--http1.1',
                    '--connect-timeout', '15',
                    '--max-time', '90',
                    '--speed-time', '20',
                    '--speed-limit', '1024',
                    '--range', "$rangeStart-$rangeEnd",
                    '--output', $partPath,
                    $signedUrl
                )
                $process = Start-Process -FilePath 'curl.exe' -ArgumentList $arguments -NoNewWindow -PassThru -RedirectStandardError $stderrPath
                $parts += [pscustomobject]@{
                    Start = [long]$rangeStart
                    End = [long]$rangeEnd
                    Path = $partPath
                    Stderr = $stderrPath
                    Process = $process
                }
            }

            $batchSucceeded = $true
            foreach ($part in $parts) {
                $part.Process.WaitForExit()
                $exitCode = $part.Process.ExitCode
                $exitCodeKnown = $null -ne $exitCode
                $expectedPartBytes = [long]($part.End - $part.Start + 1)
                $actualPartBytes = if (Test-Path -LiteralPath $part.Path -PathType Leaf) {
                    [long](Get-Item -LiteralPath $part.Path).Length
                } else {
                    -1L
                }
                $partFailed = ($actualPartBytes -ne $expectedPartBytes) -or ($exitCodeKnown -and [int]$exitCode -ne 0)
                if ($partFailed) {
                    $stderr = ''
                    if (Test-Path -LiteralPath $part.Stderr -PathType Leaf) {
                        $stderrRaw = Get-Content -LiteralPath $part.Stderr -Raw -ErrorAction SilentlyContinue
                        if ($null -ne $stderrRaw) { $stderr = $stderrRaw.Trim() }
                    }
                    $exitCodeText = if ($exitCodeKnown) { [string]$exitCode } else { 'unavailable' }
                    Write-Warning "Artifact range $($part.Start)-$($part.End) attempt $attempt/$MaxAttempts failed (curl_exit=$exitCodeText, bytes=$actualPartBytes, stderr=$stderr)."
                    $batchSucceeded = $false
                }
            }

            if ($batchSucceeded) {
                $output = [IO.File]::Open($archivePath, [IO.FileMode]::Append, [IO.FileAccess]::Write, [IO.FileShare]::Read)
                try {
                    foreach ($part in ($parts | Sort-Object Start)) {
                        $input = [IO.File]::OpenRead($part.Path)
                        try { $input.CopyTo($output) } finally { $input.Dispose() }
                    }
                }
                finally {
                    $output.Dispose()
                }
                $currentLength = [long](Get-Item -LiteralPath $archivePath).Length
                Write-Host "NEXUS_ARTIFACT_RANGE_PROGRESS bytes=$currentLength/$ExpectedArchiveBytes"
            }
        }
        finally {
            $signedUrl = $null
            foreach ($part in $parts) {
                Remove-Item -LiteralPath $part.Path -Force -ErrorAction SilentlyContinue
                Remove-Item -LiteralPath $part.Stderr -Force -ErrorAction SilentlyContinue
            }
        }

        if (-not $batchSucceeded -and $attempt -lt $MaxAttempts) {
            Start-Sleep -Seconds ([Math]::Min(3 * $attempt, 15))
        }
    }

    if (-not $batchSucceeded) {
        throw "Exact artifact range download failed after $MaxAttempts bounded attempts at byte $currentLength."
    }
}

if (-not $verified) { throw "Exact artifact download failed verification." }

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
