$ErrorActionPreference = 'Stop'
$Repo = 'saladinayoubi1/lbank-research-automation'
$Workflow = 'bybit_prospective_paper_forward_v1.yml'
$Artifact = 'bybit-prospective-paper-forward-v1-state'
$Root = Join-Path $env:LOCALAPPDATA 'NEXUS\paper-forward-sync'
$Validator = Join-Path $Root 'product_prospective_paper.py'
$Dest = Join-Path $env:APPDATA 'nexus-personal-pro-product\product-data\prospective_paper'
$StateName = 'bybit_prospective_paper_forward_v1.json'
$StatusPath = Join-Path $Root 'sync-status.json'
New-Item -ItemType Directory -Force -Path $Root,$Dest | Out-Null

function Write-SyncStatus([string]$status,[string]$detail,[object]$runId=$null) {
  @{
    status = $status
    detail = $detail
    run_id = $runId
    at_utc = [DateTime]::UtcNow.ToString('o')
  } | ConvertTo-Json | Set-Content -LiteralPath $StatusPath -Encoding UTF8
}

function Test-State([string]$rootPath) {
  $env:NEXUS_SYNC_VALIDATOR = $Validator
  $env:NEXUS_SYNC_ROOT = $rootPath
  python -c "import os,sys; from pathlib import Path; sys.path.insert(0,str(Path(os.environ['NEXUS_SYNC_VALIDATOR']).parent)); from product_prospective_paper import load_prospective_paper_snapshot; x=load_prospective_paper_snapshot(Path(os.environ['NEXUS_SYNC_ROOT'])); raise SystemExit(0 if x['available'] else 2)"
  return ($LASTEXITCODE -eq 0)
}

function Keep-Current-And-Defer([string]$reason) {
  $currentRoot = Join-Path $Root 'current-validation'
  $currentDir = Join-Path $currentRoot 'prospective_paper'
  if (Test-Path $currentRoot) { Remove-Item $currentRoot -Recurse -Force -ErrorAction SilentlyContinue }
  New-Item -ItemType Directory -Force -Path $currentDir | Out-Null
  $currentState = Join-Path $Dest $StateName
  if (Test-Path $currentState) {
    Copy-Item $currentState (Join-Path $currentDir $StateName) -Force
    if (Test-State $currentRoot) {
      Write-SyncStatus 'deferred_safe' $reason
      Write-Host "SYNC_DEFERRED_SAFE=$reason"
      exit 0
    }
  }
  Write-SyncStatus 'failed_no_valid_snapshot' $reason
  throw $reason
}

$Info = $null
for ($attempt = 1; $attempt -le 6 -and -not $Info; $attempt++) {
  $previousEap = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  $raw = & gh run list --repo $Repo --workflow $Workflow --status success --limit 1 --json databaseId,headSha,updatedAt 2>$null
  $ghExit = $LASTEXITCODE
  $ErrorActionPreference = $previousEap
  if ($ghExit -eq 0 -and $raw) {
    try {
      $parsed = @($raw | ConvertFrom-Json)
      if ($parsed.Count -gt 0) { $Info = $parsed[0] }
    } catch {}
  }
  if (-not $Info) { Start-Sleep -Seconds ([Math]::Min(20, 2 * $attempt)) }
}
if (-not $Info) { Keep-Current-And-Defer 'latest successful Paper run discovery failed after retries' }

$RunId = [string]$Info.databaseId
$LastSyncPath = Join-Path $Root 'last-sync.json'
if (Test-Path -LiteralPath $LastSyncPath) {
  try {
    $lastSync = Get-Content -LiteralPath $LastSyncPath -Raw | ConvertFrom-Json
    if ([string]$lastSync.run_id -eq $RunId) {
      $sameRunRoot = Join-Path $Root 'same-run-validation'
      $sameRunDir = Join-Path $sameRunRoot 'prospective_paper'
      if (Test-Path -LiteralPath $sameRunRoot) { Remove-Item -LiteralPath $sameRunRoot -Recurse -Force -ErrorAction SilentlyContinue }
      New-Item -ItemType Directory -Force -Path $sameRunDir | Out-Null
      $currentState = Join-Path $Dest $StateName
      $currentAttestation = Join-Path $Dest 'runtime_attestation.json'
      if (Test-Path -LiteralPath $currentState) {
        Copy-Item -LiteralPath $currentState -Destination (Join-Path $sameRunDir $StateName) -Force
        if (Test-Path -LiteralPath $currentAttestation) { Copy-Item -LiteralPath $currentAttestation -Destination (Join-Path $sameRunDir 'runtime_attestation.json') -Force }
        if (Test-State $sameRunRoot) {
          Remove-Item -LiteralPath $sameRunRoot -Recurse -Force -ErrorAction SilentlyContinue
          Write-SyncStatus 'success_no_change' "latest successful Paper run $RunId already validated and installed" $RunId
          Write-Host "SYNC_NO_CHANGE_RUN=$RunId"
          exit 0
        }
      }
      Remove-Item -LiteralPath $sameRunRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
  } catch {
    Write-Host ("SAME_RUN_FASTPATH=DEFER reason=" + $_.Exception.Message)
  }
}

$Tmp = Join-Path $Root ('run-' + $RunId)
if (Test-Path $Tmp) { Remove-Item $Tmp -Recurse -Force -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Force -Path $Tmp | Out-Null

$downloaded = $false
for ($attempt = 1; $attempt -le 6 -and -not $downloaded; $attempt++) {
  $previousEap = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  & gh run download $RunId --repo $Repo -n $Artifact -D $Tmp 1>$null 2>$null
  $ghExit = $LASTEXITCODE
  $ErrorActionPreference = $previousEap
  if ($ghExit -eq 0 -and (Test-Path (Join-Path $Tmp $StateName))) {
    $downloaded = $true
  } else {
    Start-Sleep -Seconds ([Math]::Min(20, 2 * $attempt))
  }
}

if (-not $downloaded) {
  try {
    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $artifactRaw = & gh api "repos/$Repo/actions/runs/$RunId/artifacts?per_page=100" 2>$null
    $artifactApiExit = $LASTEXITCODE
    $ErrorActionPreference = $previousEap
    if ($artifactApiExit -eq 0 -and $artifactRaw) {
      $artifactList = $artifactRaw | ConvertFrom-Json
      $artifactInfo = @($artifactList.artifacts | Where-Object { $_.name -eq $Artifact })[0]
      if ($artifactInfo -and $artifactInfo.id) {
        $token = (& gh auth token).Trim()
        if (-not $token) { throw 'GitHub auth token unavailable for signed artifact fallback' }
        Add-Type -AssemblyName System.Net.Http
        $handler = New-Object System.Net.Http.HttpClientHandler
        $handler.AllowAutoRedirect = $false
        $client = New-Object System.Net.Http.HttpClient($handler)
        $client.DefaultRequestHeaders.Authorization = New-Object System.Net.Http.Headers.AuthenticationHeaderValue('Bearer',$token)
        $client.DefaultRequestHeaders.UserAgent.ParseAdd('NEXUS-Paper-Sync/1.0')
        $client.DefaultRequestHeaders.Accept.Add((New-Object System.Net.Http.Headers.MediaTypeWithQualityHeaderValue('application/vnd.github+json')))
        $downloadApi = "https://api.github.com/repos/$Repo/actions/artifacts/$($artifactInfo.id)/zip"
        $resp = $client.GetAsync($downloadApi).Result
        if ([int]$resp.StatusCode -ne 302 -or -not $resp.Headers.Location) {
          throw "signed artifact redirect failed status=$([int]$resp.StatusCode)"
        }
        $outerZip = Join-Path $Tmp ($Artifact + '.zip')
        Start-BitsTransfer -Source $resp.Headers.Location.AbsoluteUri -Destination $outerZip -TransferType Download -Priority Foreground
        if ($artifactInfo.digest -and ([string]$artifactInfo.digest).StartsWith('sha256:')) {
          $expectedOuter = ([string]$artifactInfo.digest).Substring(7).ToLowerInvariant()
          $actualOuter = (Get-FileHash -LiteralPath $outerZip -Algorithm SHA256).Hash.ToLowerInvariant()
          if ($actualOuter -ne $expectedOuter) { throw 'signed artifact digest mismatch' }
        }
        Expand-Archive -LiteralPath $outerZip -DestinationPath $Tmp -Force
        if (Test-Path (Join-Path $Tmp $StateName)) {
          $downloaded = $true
          Write-Host "SIGNED_BITS_FALLBACK=PASS artifact_id=$($artifactInfo.id)"
        }
      }
    }
  } catch {
    Write-Host ("SIGNED_BITS_FALLBACK=DEFER reason=" + $_.Exception.Message)
  }
}
if (-not $downloaded) { Keep-Current-And-Defer "artifact download failed after gh retries and signed BITS fallback for run $RunId" }

$State = Join-Path $Tmp $StateName
$Attestation = Join-Path $Tmp 'runtime_attestation.json'
$ValidationRoot = Join-Path $Tmp 'validation'
$ValidationDir = Join-Path $ValidationRoot 'prospective_paper'
New-Item -ItemType Directory -Force -Path $ValidationDir | Out-Null
Copy-Item $State (Join-Path $ValidationDir $StateName) -Force
if (-not (Test-State $ValidationRoot)) {
  Write-SyncStatus 'rejected_invalid_snapshot' "validation failed for run $RunId" $RunId
  throw "Prospective Paper validation failed for run $RunId"
}

$StateTmp = Join-Path $Dest ($StateName + '.tmp')
Copy-Item $State $StateTmp -Force
Move-Item $StateTmp (Join-Path $Dest $StateName) -Force
if (Test-Path $Attestation) {
  $AttTmp = Join-Path $Dest 'runtime_attestation.json.tmp'
  Copy-Item $Attestation $AttTmp -Force
  Move-Item $AttTmp (Join-Path $Dest 'runtime_attestation.json') -Force
}
@{
  run_id = [long]$Info.databaseId
  head_sha = [string]$Info.headSha
  updated_at = [string]$Info.updatedAt
  synced_at = [DateTime]::UtcNow.ToString('o')
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Root 'last-sync.json') -Encoding UTF8
Write-SyncStatus 'success' "validated and installed run $RunId" $RunId
Write-Host "SYNC_SUCCESS_RUN=$RunId"
