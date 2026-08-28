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
$logTarget = "$target.elevated.log"
$isAdmin = Test-IsAdministrator

if (-not $isAdmin -and -not $Elevated) {
    Write-Evidence -Target $target -Payload ([ordered]@{
        schema_version = 1
        generated_at_utc = [DateTime]::UtcNow.ToString('o')
        source_sha = $env:GITHUB_SHA
        run_id = $env:GITHUB_RUN_ID
        administrator = $false
        restart_required = $false
        automatic_restart_performed = $false
        private_credentials_used = $false
        proxy_or_vpn_configured = $false
        error_class = $null
        error_message = $null
        decision = 'UAC_PENDING'
    })
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
    if (Test-Path -LiteralPath $logTarget -PathType Leaf) {
        Write-Host 'elevated_transcript_begin=true'
        Get-Content -LiteralPath $logTarget | Select-Object -Last 160 | ForEach-Object { Write-Host $_ }
        Write-Host 'elevated_transcript_end=true'
    }
    if (Test-Path -LiteralPath $target -PathType Leaf) {
        $evidence = Get-Content -LiteralPath $target -Raw | ConvertFrom-Json
        Write-Host "bybit_wsl_enablement_decision=$($evidence.decision)"
        Write-Host "restart_required=$($evidence.restart_required.ToString().ToLowerInvariant())"
        if ($evidence.error_class) {
            Write-Host "enablement_error_class=$($evidence.error_class)"
        }
    }
    elseif ($child.ExitCode -ne 0) {
        throw "Elevated WSL enablement failed without evidence; exit code $($child.ExitCode)."
    }
    else {
        throw 'Elevated WSL enablement did not produce evidence.'
    }
    exit $child.ExitCode
}

if (-not $isAdmin) {
    throw 'Administrator authority was not obtained.'
}

$transcriptStarted = $false
try {
    $logParent = Split-Path -Parent $logTarget
    New-Item -ItemType Directory -Path $logParent -Force | Out-Null
    Start-Transcript -LiteralPath $logTarget -Force | Out-Null
    $transcriptStarted = $true
}
catch {
    Write-Host "transcript_start_error=$($_.Exception.GetType().Name)"
}

trap {
    $fatal = $_.Exception
    $fallback = [ordered]@{
        schema_version = 1
        generated_at_utc = [DateTime]::UtcNow.ToString('o')
        source_sha = $env:GITHUB_SHA
        run_id = $env:GITHUB_RUN_ID
        administrator = $true
        restart_required = $false
        automatic_restart_performed = $false
        private_credentials_used = $false
        proxy_or_vpn_configured = $false
        error_class = $fatal.GetType().Name
        error_message = [string]$fatal.Message
        decision = 'WSL_FEATURE_ENABLEMENT_FAILED'
    }
    try {
        Write-Evidence -Target $target -Payload $fallback
    }
    catch {
        $fallbackJson = $fallback | ConvertTo-Json -Depth 8
        [IO.File]::WriteAllText($target, $fallbackJson, (New-Object Text.UTF8Encoding($false)))
    }
    Write-Host "fatal_enablement_error_class=$($fatal.GetType().Name)"
    Write-Host "fatal_enablement_error_message=$($fatal.Message)"
    if ($transcriptStarted) {
        try { Stop-Transcript | Out-Null } catch { }
    }
    exit 1
}

$before = [ordered]@{
    wsl = Get-FeatureState -Name 'Microsoft-Windows-Subsystem-Linux'
    virtual_machine_platform = Get-FeatureState -Name 'VirtualMachinePlatform'
}

$wslResult = $null
$vmResult = $null
$enablementError = $null
try {
    $wslResult = Enable-WindowsOptionalFeature -Online -FeatureName 'Microsoft-Windows-Subsystem-Linux' -All -NoRestart
    $vmResult = Enable-WindowsOptionalFeature -Online -FeatureName 'VirtualMachinePlatform' -All -NoRestart
}
catch {
    $enablementError = $_.Exception
}

$after = [ordered]@{
    wsl = Get-FeatureState -Name 'Microsoft-Windows-Subsystem-Linux'
    virtual_machine_platform = Get-FeatureState -Name 'VirtualMachinePlatform'
}
$restartRequired = [bool](
    ($wslResult -and $wslResult.RestartNeeded) -or
    ($vmResult -and $vmResult.RestartNeeded)
)
$enabled = $after.wsl -in @('Enabled', 'EnablePending') -and $after.virtual_machine_platform -in @('Enabled', 'EnablePending')
$decision = if ($enablementError -or -not $enabled) {
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
    error_class = if ($enablementError) { $enablementError.GetType().Name } else { $null }
    error_message = if ($enablementError) { [string]$enablementError.Message } else { $null }
    decision = $decision
}

Write-Evidence -Target $target -Payload $payload
$digest = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()

Write-Host "bybit_wsl_enablement_decision=$decision"
Write-Host "restart_required=$($restartRequired.ToString().ToLowerInvariant())"
Write-Host 'automatic_restart_performed=false'
if ($enablementError) {
    Write-Host "enablement_error_class=$($enablementError.GetType().Name)"
    Write-Host "enablement_error_message=$($enablementError.Message)"
}
Write-Host "evidence_sha256=$digest"

if (-not $enabled) {
    if ($transcriptStarted) {
        Stop-Transcript | Out-Null
    }
    exit 1
}

if ($transcriptStarted) {
    Stop-Transcript | Out-Null
}
