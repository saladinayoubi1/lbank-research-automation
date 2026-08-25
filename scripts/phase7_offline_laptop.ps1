[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('PrepareOnline','ExecuteOffline','SubmitReturn')]
    [string]$Mode,

    [string]$SessionId,
    [string]$Repo = 'saladinayoubi1/lbank-research-automation',
    [string]$RepoRoot = (Get-Location).Path
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$CoreScript = Join-Path $PSScriptRoot 'phase7_offline_laptop_core.ps1'
$StateBase = Join-Path $env:LOCALAPPDATA 'NEXUS\Phase7'
$ExpectedRepo = 'saladinayoubi1/lbank-research-automation'

function Fail([string]$Message) {
    throw "NEXUS Phase 7: $Message"
}

function Set-Or-AddProperty([pscustomobject]$Object, [string]$Name, $Value) {
    $existing = $Object.PSObject.Properties[$Name]
    if ($null -ne $existing) {
        $Object.$Name = $Value
    }
    else {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value -Force
    }
}

function Complete-VerifiedSession([string]$Id) {
    if (-not $Id) { Fail 'SessionId is required for SubmitReturn completion recovery' }
    $sessionRoot = Join-Path $StateBase $Id
    $sessionPath = Join-Path $sessionRoot 'session.json'
    $verifiedDir = Join-Path $sessionRoot 'verified-proof'
    $finalRunPath = Join-Path $verifiedDir 'phase7-proof-mission-run.json'

    if (-not (Test-Path -LiteralPath $sessionPath -PathType Leaf)) { Fail "session '$Id' was not found" }
    if (-not (Test-Path -LiteralPath $finalRunPath -PathType Leaf)) { Fail 'verified proof artifact is missing; refusing bookkeeping recovery' }

    $session = Get-Content -LiteralPath $sessionPath -Raw | ConvertFrom-Json
    if ($session.schema_version -ne 'nexus.phase7-local-session.v1') { Fail 'local session schema mismatch' }
    if ($session.repository -ne $ExpectedRepo) { Fail 'local session repository mismatch' }
    if (-not $session.return_pr) { Fail 'return PR was not persisted before bookkeeping failure' }

    $final = Get-Content -LiteralPath $finalRunPath -Raw | ConvertFrom-Json
    if ($final.source_sha -ne $session.source_sha) { Fail 'verified artifact source SHA does not match session source SHA' }
    if ($final.paper_only -ne $true -or $final.live_trading_authority -ne $false) { Fail 'verified artifact widened authority' }
    if ($final.hardware_proof_complete -ne $true -or [double]$final.manager_summary.verified_progress_percent -ne 100.0) { Fail 'hardware proof did not reach verified 100%' }
    if ($final.resource_classification.Laptop.classification -ne 'EXECUTED') { Fail 'Laptop resource was not classified EXECUTED' }
    if ($final.offline_network_proof.reboot_after_prepare -ne $true -or $final.offline_network_proof.internet_unavailable_pre -ne $true -or $final.offline_network_proof.internet_unavailable_post -ne $true) { Fail 'verified artifact lacks real offline evidence' }

    Set-Or-AddProperty $session 'completed' $true
    Set-Or-AddProperty $session 'completed_at' ([DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffZ'))
    Set-Or-AddProperty $session 'verified_artifact_dir' $verifiedDir

    $tmp = $sessionPath + '.tmp'
    $session | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $tmp -Encoding UTF8
    Move-Item -LiteralPath $tmp -Destination $sessionPath -Force

    $check = Get-Content -LiteralPath $sessionPath -Raw | ConvertFrom-Json
    if ($check.completed -ne $true -or -not $check.completed_at -or $check.verified_artifact_dir -ne $verifiedDir) {
        Fail 'verified local bookkeeping did not persist atomically'
    }

    Write-Host 'NEXUS Phase 7 laptop proof VERIFIED: 100% (PowerShell 5.1-safe bookkeeping recovery)'
}

if (-not (Test-Path -LiteralPath $CoreScript -PathType Leaf)) { Fail 'Phase 7 core helper is missing' }
if ($Repo -ne $ExpectedRepo) { Fail "repository must remain $ExpectedRepo" }

try {
    & $CoreScript -Mode $Mode -SessionId $SessionId -Repo $Repo -RepoRoot $RepoRoot
}
catch {
    $message = $_.Exception.Message
    $isKnownPs51BookkeepingFailure = (
        $Mode -eq 'SubmitReturn' -and
        $message -match "property 'completed_at' cannot be found" -and
        $message -match 'can be set'
    )
    if (-not $isKnownPs51BookkeepingFailure) { throw }

    Complete-VerifiedSession $SessionId
}
