# Exact-main, owner-only artifact preload: no install and no profile mutation.
[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-fA-F]{40}$')][string]$SourceSha,
  [Parameter(Mandatory=$true)][long]$ArtifactRunId,
  [Parameter(Mandatory=$true)][long]$ArtifactId,
  [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$OuterSha256,
  [Parameter(Mandatory=$true)][long]$OuterBytes,
  [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$InnerSha256
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
if(!$env:GITHUB_TOKEN -or !$env:RUNNER_TEMP -or !$env:GITHUB_RUN_ID -or !$env:GITHUB_SHA -or !$env:GITHUB_REPOSITORY) {
  throw 'Authorized GitHub Actions context is required'
}
if($env:GITHUB_SHA.ToLowerInvariant() -ne $SourceSha.ToLowerInvariant() -or
   $env:GITHUB_REF -ne 'refs/heads/main' -or
   $env:GITHUB_REPOSITORY -ne 'saladinayoubi1/lbank-research-automation') {
  throw 'Refuse non-main or source-unbound artifact preload'
}
if($OuterBytes -lt 1){throw 'Invalid official artifact size'}
$root=Join-Path $env:LOCALAPPDATA 'NEXUS\artifact-cache'
$cache=Join-Path $root "nexus-windows-persistent-unpacked-$ArtifactId"
if(Test-Path -LiteralPath $cache){
  Write-Host 'Existing cache preserved; the independent next step validates every source and hash.'
  exit 0
}
$transport=Join-Path $env:RUNNER_TEMP "nexus-personal-pro-package-$env:GITHUB_RUN_ID"
if(Test-Path -LiteralPath $transport){throw 'Existing package transport requires manual review'}
& scripts\download_github_actions_artifact_http11.ps1 -Repository $env:GITHUB_REPOSITORY -ArtifactRunId $ArtifactRunId -ArtifactId $ArtifactId -ArtifactName 'nexus-windows-persistent-unpacked' -ExpectedSourceSha $SourceSha -ExpectedArchiveSha256 $OuterSha256 -ExpectedArchiveBytes $OuterBytes -DestinationDirectory $transport -MaxAttempts 4
if(!$?){throw 'Bounded official artifact transport failed'}
$inner=Join-Path $transport 'NEXUS_Personal_Pro_Unpacked_5.1.0_x64.zip'
$sums=Join-Path $transport 'SHA256SUMS.txt'
foreach($file in @($inner,$sums)){
  if(!(Test-Path -LiteralPath $file -PathType Leaf)){throw 'Artifact package/sums missing'}
  if(((Get-Item -LiteralPath $file -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0){
    throw 'Package member cannot be reparse point'
  }
}
$hash=(Get-FileHash -LiteralPath $inner -Algorithm SHA256).Hash.ToLowerInvariant()
if($hash -ne $InnerSha256.ToLowerInvariant()){throw 'Downloaded inner package SHA-256 mismatch'}
$entries=@(Get-Content -LiteralPath $sums|Where-Object {$_ -match '(?i)NEXUS_Personal_Pro_Unpacked_5\.1\.0_x64\.zip$'})
if($entries.Count -ne 1 -or $entries[0] -notmatch '^([0-9a-fA-F]{64})\s+\*?NEXUS_Personal_Pro_Unpacked_5\.1\.0_x64\.zip$'){
  throw 'Artifact SHA256SUMS missing or ambiguous'
}
if($Matches[1].ToLowerInvariant() -ne $hash){throw 'Inner SHA256SUMS disagrees with package bytes'}
New-Item -ItemType Directory -Path $root -Force|Out-Null
$pending="$cache.incoming-$env:GITHUB_RUN_ID"
if(Test-Path -LiteralPath $pending){throw 'Unreviewed incoming cache exists'}
New-Item -ItemType Directory -Path $pending -ErrorAction Stop|Out-Null
try{
  Copy-Item -LiteralPath @($inner,$sums) -Destination $pending -ErrorAction Stop
  if((Get-FileHash (Join-Path $pending 'NEXUS_Personal_Pro_Unpacked_5.1.0_x64.zip') -Algorithm SHA256).Hash.ToLowerInvariant() -ne $hash){
    throw 'Preloaded cache copy SHA-256 mismatch'
  }
  $manifest=[ordered]@{
    schema_version='nexus.preloaded-persistent-cache.v1'
    repository=$env:GITHUB_REPOSITORY
    source_sha=$env:GITHUB_SHA
    artifact_run_id=$ArtifactRunId
    artifact_id=$ArtifactId
    artifact_name='nexus-windows-persistent-unpacked'
    archive_sha256=$OuterSha256.ToLowerInvariant()
    archive_bytes=$OuterBytes
    inner_sha256=$hash
  }
  [IO.File]::WriteAllText((Join-Path $pending 'cache-manifest.json'),
    ($manifest|ConvertTo-Json -Depth 4),(New-Object Text.UTF8Encoding($false)))
  if(Test-Path -LiteralPath $cache){throw 'Concurrent verified cache publication forbidden'}
  Move-Item -LiteralPath $pending -Destination $cache -ErrorAction Stop
  Write-Host "NEXUS_FASTPATH_PRELOAD=PASS source=$env:GITHUB_SHA artifact=$ArtifactId"
}finally{
  if(Test-Path -LiteralPath $pending){Remove-Item -LiteralPath $pending -Recurse -Force -ErrorAction SilentlyContinue}
}
