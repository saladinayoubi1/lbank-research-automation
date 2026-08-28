param(
    [string]$OutputPath = "build\bybit-wsl-enablement\evidence.json",
    [switch]$Elevated
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-FeatureState {
    param([Parameter(Mandatory = $true)][string]$Name)

    try {
        return [string](Get-WindowsOptionalFeature -Online -FeatureName $Name -ErrorAction Stop).State
    }
    catch {
        return 'Unknown'
    }
}

function Write-Evidence {
    param(
        [Parameter(Mandatory = $true)][string]$Target,
        [Parameter(Mandatory = $true)][System.Collections.IDictionary]$Payload
    )

    $parent = Split-Path -Parent $Target
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $json = $Payload | ConvertTo-Json -Depth 8
    [IO.File]::WriteAllText($Target, $json, (New-Object Text.UTF8Encoding($false)))
}

$target = [IO.Path]::GetFullPath($OutputPath)
$isAdmin = Test-IsAdministrator

if (-not $isAdmin -and -not $Elevated) {
    $scriptPath = [IO.Path]::GetFullPath($MyInvocation.MyCommand.Path)
    $arguments = @(
        '-NoProfile',
        '-NonInteractive',
        '-ExecutionPolicy', 'Bypass',
        '-File', ('"{0}"' -f $scriptPath),
        '-OutputPath', ('"{0}"' -f $target),
        '-Elevated'
    ) -join ' '

    Write-Host 'uac_approval_required=true'
    $child = Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -Verb RunAs -Wait -PassThru
    if ($child.ExitCode -ne 0) {
        throw "Elevated WSL enablement failed with exit code $($child.ExitCode)."
    }
    if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
        throw 'Elevated WSL enablement did not produce evidence.'
    }
    $evidence = Get-Content -LiteralPath $target -Raw | ConvertFrom-Json
    Write-Host "bybit_wsl_enablement_decision=$($evidence.decision)"
    Write-Host "restart_required=$($evidence.restart_required.ToString().ToLowerInvariant())"
    exit 0
}

if (-not $isAdmin) {
    throw 'Administrator authority was not obtained.'
}

$before = [ordered]@{
    wsl = Get-FeatureState -Name 'Microsoft-Windows-Subsystem-Linux'
    virtual_machine_platform = Get-FeatureState -Name 'VirtualMachinePlatform'
}

$wslResult = Enable-WindowsOptionalFeature -Online -FeatureName 'Microsoft-Windows-Subsystem-Linux' -All -NoRestart
$vmResult = Enable-WindowsOptionalFeature -Online -FeatureName 'VirtualMachinePlatform' -All -NoRestart

$after = [ordered]@{
    wsl = Get-FeatureState -Name 'Microsoft-Windows-Subsystem-Linux'
    virtual_machine_platform = Get-FeatureState -Name 'VirtualMachinePlatform'
}
$restartRequired = [bool]($wslResult.RestartNeeded -or $vmResult.RestartNeeded)
$enabled = $after.wsl -in @('Enabled', 'EnablePending') -and $after.virtual_machine_platform -in @('Enabled', 'EnablePending')
$decision = if (-not $enabled) {
    'WSL_FEATURE_ENABLEMENT_FAILED'
}
elseif ($restartRequired -or $after.wsl -eq 'EnablePending' -or $after.virtual_machine_platform -eq 'EnablePending') {
    'RESTART_REQUIRED'
}
else {
    'WSL_FEATURES_ENABLED'
}

$payload = [ordered]@{
    schema_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString('o')
    source_sha = $env:GITHUB_SHA
    run_id = $env:GITHUB_RUN_ID
    administrator = $true
    before = $before
    after = $after
    restart_required = $restartRequired
    automatic_restart_performed = $false
    private_credentials_used = $false
    proxy_or_vpn_configured = $false
    decision = $decision
}

Write-Evidence -Target $target -Payload $payload
$digest = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()

Write-Host "bybit_wsl_enablement_decision=$decision"
Write-Host "restart_required=$($restartRequired.ToString().ToLowerInvariant())"
Write-Host 'automatic_restart_performed=false'
Write-Host "evidence_sha256=$digest"

if (-not $enabled) {
    exit 1
}
