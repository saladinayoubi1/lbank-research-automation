param(
    [string]$OutputPath = "build\bybit-wsl1-fallback\evidence.json",
    [string]$Distribution = "Ubuntu",
    [string]$UbuntuRootfsUrl = "https://cloud-images.ubuntu.com/wsl/releases/24.04/current/ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz",
    [string]$UbuntuRootfsSha256 = "2a790896740b14d637dbdc583cce1ba081ac53b9e9cdb46dc09a2f73abbd9934"
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

function Invoke-Wsl {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $rawOutput = @(& "$env:SystemRoot\System32\wsl.exe" @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
        $text = (($rawOutput | ForEach-Object { $_.ToString() }) | Out-String)
        $text = ($text -replace "`0", '').Trim()
        return [ordered]@{
            exit_code = if ($null -eq $exitCode) { -1 } else { [int]$exitCode }
            output = $text
        }
    }
    catch {
        return [ordered]@{
            exit_code = -1
            output = $_.Exception.ToString()
        }
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

function Get-WslDistributions {
    $probe = Invoke-Wsl -Arguments @('--list', '--quiet')
    if ($probe.exit_code -ne 0) {
        return @()
    }
    return @(
        $probe.output -split "`r?`n" |
            ForEach-Object { $_.Trim().TrimStart('*').Trim() } |
            Where-Object { $_ }
    )
}

function Get-WslDistributionVersion {
    param([Parameter(Mandatory = $true)][string]$Name)

    $probe = Invoke-Wsl -Arguments @('--list', '--verbose')
    if ($probe.exit_code -ne 0) {
        return [ordered]@{ version = $null; output = $probe.output; exit_code = $probe.exit_code }
    }

    $escaped = [Regex]::Escape($Name)
    foreach ($line in ($probe.output -split "`r?`n")) {
        if ($line -match "^\s*\*?\s*$escaped\s+\S+\s+(\d+)\s*$") {
            return [ordered]@{ version = [int]$Matches[1]; output = $probe.output; exit_code = 0 }
        }
    }
    return [ordered]@{ version = $null; output = $probe.output; exit_code = 0 }
}

function Write-Evidence {
    param(
        [Parameter(Mandatory = $true)][string]$Target,
        [Parameter(Mandatory = $true)][System.Collections.IDictionary]$Payload
    )

    $parent = Split-Path -Parent $Target
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $json = $Payload | ConvertTo-Json -Depth 10
    [IO.File]::WriteAllText($Target, $json, (New-Object Text.UTF8Encoding($false)))
}

$target = [IO.Path]::GetFullPath($OutputPath)
$distributionInstallRoot = Join-Path $env:ProgramData "NEXUS\BybitWSL\$Distribution"
$isAdmin = Test-IsAdministrator
$evidence = [ordered]@{
    schema_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString('o')
    source_sha = $env:GITHUB_SHA
    run_id = $env:GITHUB_RUN_ID
    administrator = $isAdmin
    distribution = $Distribution
    requested_wsl_version = 1
    distribution_install_root = $distributionInstallRoot
    ubuntu_rootfs_url = $UbuntuRootfsUrl
    ubuntu_rootfs_sha256 = $UbuntuRootfsSha256
    ubuntu_rootfs_download_verified = $false
    quarantine_path = $null
    windows_runner_paths_modified = $false
    windows_runner_service_modified = $false
    automatic_restart_performed = $false
    firmware_setting_modified = $false
    default_wsl_version_modified = $false
    bybit_private_credentials_used = $false
    decision = $null
    error_class = $null
}

function Complete-Fallback {
    param(
        [Parameter(Mandatory = $true)][string]$Decision,
        [int]$ExitCode = 0,
        [string]$ErrorClass = $null
    )

    $evidence.decision = $Decision
    $evidence.error_class = $ErrorClass
    Write-Evidence -Target $target -Payload $evidence
    $digest = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Host "bybit_wsl1_fallback_decision=$Decision"
    Write-Host "windows_runner_paths_modified=false"
    Write-Host "windows_runner_service_modified=false"
    Write-Host "automatic_restart_performed=false"
    Write-Host "firmware_setting_modified=false"
    Write-Host "evidence_sha256=$digest"
    exit $ExitCode
}

trap {
    $evidence.decision = 'WSL1_FALLBACK_FAILED'
    $evidence.error_class = $_.Exception.GetType().Name
    $evidence.error = $_.Exception.ToString()
    Write-Evidence -Target $target -Payload $evidence
    $digest = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Host 'bybit_wsl1_fallback_decision=WSL1_FALLBACK_FAILED'
    Write-Host "fallback_error_class=$($evidence.error_class)"
    Write-Host 'windows_runner_paths_modified=false'
    Write-Host 'windows_runner_service_modified=false'
    Write-Host 'automatic_restart_performed=false'
    Write-Host 'firmware_setting_modified=false'
    Write-Host "evidence_sha256=$digest"
    exit 1
}

if (-not $isAdmin) {
    Complete-Fallback -Decision 'ADMINISTRATOR_TOKEN_REQUIRED' -ExitCode 1 -ErrorClass 'SecurityException'
}

if ($Distribution -notmatch '^[A-Za-z0-9._-]+$') {
    Complete-Fallback -Decision 'INVALID_DISTRIBUTION_NAME' -ExitCode 1 -ErrorClass 'ArgumentException'
}

$rootfsUri = $null
if (-not [Uri]::TryCreate($UbuntuRootfsUrl, [UriKind]::Absolute, [ref]$rootfsUri) -or
    $rootfsUri.Scheme -ne 'https' -or
    $rootfsUri.Host -ne 'cloud-images.ubuntu.com' -or
    $rootfsUri.AbsolutePath -notmatch '^/wsl/releases/24\.04/[^/]+/ubuntu-noble-wsl-amd64-24\.04lts\.rootfs\.tar\.gz$' -or
    $UbuntuRootfsSha256 -notmatch '^[a-f0-9]{64}$') {
    Complete-Fallback -Decision 'INVALID_PINNED_ROOTFS' -ExitCode 1 -ErrorClass 'ArgumentException'
}

$wslFeature = Get-FeatureState -Name 'Microsoft-Windows-Subsystem-Linux'
$vmFeature = Get-FeatureState -Name 'VirtualMachinePlatform'
$evidence.windows_features = [ordered]@{
    wsl = $wslFeature
    virtual_machine_platform = $vmFeature
}
if ($wslFeature -ne 'Enabled') {
    Complete-Fallback -Decision 'WSL_FEATURE_NOT_READY' -ExitCode 1 -ErrorClass 'InvalidOperationException'
}

$distributions = Get-WslDistributions
if ($Distribution -in $distributions) {
    $existing = Get-WslDistributionVersion -Name $Distribution
    $evidence.existing_distribution = $true
    $evidence.detected_wsl_version = $existing.version
    $evidence.wsl_list_verbose = $existing.output
    if ($existing.version -eq 1) {
        $probe = Invoke-Wsl -Arguments @('-d', $Distribution, '-u', 'root', '--', 'bash', '-lc', 'printf NEXUS_WSL1_READY; uname -a; test -x /bin/bash')
        $evidence.linux_probe_exit_code = $probe.exit_code
        $evidence.linux_probe_output = $probe.output
        if ($probe.exit_code -eq 0) {
            Complete-Fallback -Decision 'WSL1_READY_FOR_PROVISIONING'
        }
        Complete-Fallback -Decision 'WSL1_EXISTING_DISTRIBUTION_PROBE_FAILED' -ExitCode 1 -ErrorClass 'InvalidOperationException'
    }
    Complete-Fallback -Decision 'EXISTING_DISTRIBUTION_NOT_WSL1' -ExitCode 1 -ErrorClass 'InvalidOperationException'
}

$evidence.existing_distribution = $false
$installParent = Split-Path -Parent $distributionInstallRoot
New-Item -ItemType Directory -Path $installParent -Force | Out-Null
if (Test-Path -LiteralPath $distributionInstallRoot) {
    $existingItems = @(Get-ChildItem -LiteralPath $distributionInstallRoot -Force -ErrorAction Stop)
    if ($existingItems.Count -gt 0) {
        $quarantinePath = "${distributionInstallRoot}-quarantine-$([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'))"
        Move-Item -LiteralPath $distributionInstallRoot -Destination $quarantinePath -Force
        $evidence.quarantine_path = $quarantinePath
    }
}
New-Item -ItemType Directory -Path $distributionInstallRoot -Force | Out-Null

$rootfsArchive = Join-Path ([IO.Path]::GetTempPath()) ("nexus-ubuntu-wsl1-{0}.rootfs.tar.gz" -f [Guid]::NewGuid().ToString('N'))
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $UbuntuRootfsUrl -OutFile $rootfsArchive -UseBasicParsing
    $downloadedSha256 = (Get-FileHash -LiteralPath $rootfsArchive -Algorithm SHA256).Hash.ToLowerInvariant()
    $evidence.ubuntu_rootfs_downloaded_sha256 = $downloadedSha256
    if ($downloadedSha256 -ne $UbuntuRootfsSha256) {
        Complete-Fallback -Decision 'UBUNTU_ROOTFS_CHECKSUM_MISMATCH' -ExitCode 1 -ErrorClass 'InvalidDataException'
    }
    $evidence.ubuntu_rootfs_download_verified = $true

    $import = Invoke-Wsl -Arguments @('--import', $Distribution, $distributionInstallRoot, $rootfsArchive, '--version', '1')
    $evidence.import_exit_code = $import.exit_code
    $evidence.import_output = $import.output
    if ($import.exit_code -ne 0) {
        Complete-Fallback -Decision 'WSL1_DISTRIBUTION_IMPORT_FAILED' -ExitCode 1 -ErrorClass 'InvalidOperationException'
    }
}
finally {
    if (Test-Path -LiteralPath $rootfsArchive -PathType Leaf) {
        Remove-Item -LiteralPath $rootfsArchive -Force
    }
}

$distributions = Get-WslDistributions
if ($Distribution -notin $distributions) {
    Complete-Fallback -Decision 'WSL1_DISTRIBUTION_IMPORT_PENDING' -ExitCode 1 -ErrorClass 'InvalidOperationException'
}

$version = Get-WslDistributionVersion -Name $Distribution
$evidence.detected_wsl_version = $version.version
$evidence.wsl_list_verbose = $version.output
if ($version.version -ne 1) {
    Complete-Fallback -Decision 'WSL1_VERSION_VERIFICATION_FAILED' -ExitCode 1 -ErrorClass 'InvalidOperationException'
}

$probe = Invoke-Wsl -Arguments @('-d', $Distribution, '-u', 'root', '--', 'bash', '-lc', 'printf NEXUS_WSL1_READY; uname -a; test -x /bin/bash')
$evidence.linux_probe_exit_code = $probe.exit_code
$evidence.linux_probe_output = $probe.output
if ($probe.exit_code -ne 0) {
    Complete-Fallback -Decision 'WSL1_LINUX_PROBE_FAILED' -ExitCode 1 -ErrorClass 'InvalidOperationException'
}

Complete-Fallback -Decision 'WSL1_READY_FOR_PROVISIONING'
