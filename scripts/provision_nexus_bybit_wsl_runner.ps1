param(
    [string]$OutputPath = "build\bybit-wsl-provisioning\evidence.json",
    [string]$Distribution = "Ubuntu",
    [string]$RunnerName = "NEXUS-BYBIT-WSL",
    [string]$RunnerLabel = "nexus-bybit-network",
    [string]$RunnerVersion = "2.336.0",
    [string]$RunnerSha256 = "04cf0be1aff4c3ec3554466c39124ca250e3effd8873bb7e8d68535aa9505d5d",
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

    try {
        $text = (& "$env:SystemRoot\System32\wsl.exe" @Arguments 2>&1 | Out-String).Replace([char]0, '').Trim()
        return [ordered]@{
            exit_code = $LASTEXITCODE
            output = $text
        }
    }
    catch {
        return [ordered]@{
            exit_code = -1
            output = $_.Exception.GetType().Name
        }
    }
}

function Get-WslDistributions {
    $probe = Invoke-Wsl -Arguments @('--list', '--quiet')
    if ($probe.exit_code -ne 0) {
        return @()
    }
    return @(
        $probe.output -split "`r?`n" |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ }
    )
}

function Resolve-Gh {
    $candidates = @()
    $command = Get-Command gh.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command) {
        $candidates += $command.Source
    }
    $candidates += @(
        (Join-Path $env:ProgramFiles 'GitHub CLI\gh.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\GitHub CLI\gh.exe')
    )
    return @($candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -Unique)[0]
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
$repository = [string]$env:GITHUB_REPOSITORY
$repositoryUrl = if ($repository) { "https://github.com/$repository" } else { $null }
$taskName = 'NEXUS Bybit WSL Runner'
$runnerRoot = '/opt/nexus-bybit-runner'
$distributionInstallRoot = Join-Path $env:ProgramData "NEXUS\BybitWSL\$Distribution"
$packageName = "actions-runner-linux-x64-$RunnerVersion.tar.gz"
$packageUrl = "https://github.com/actions/runner/releases/download/v$RunnerVersion/$packageName"
$isAdmin = Test-IsAdministrator

if ($repository -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') {
    throw 'GITHUB_REPOSITORY is missing or invalid.'
}
foreach ($value in @($Distribution, $RunnerName, $RunnerLabel)) {
    if ($value -notmatch '^[A-Za-z0-9._-]+$') {
        throw 'Distribution, runner name, and runner label must use only safe identifier characters.'
    }
}
if ($RunnerVersion -notmatch '^\d+\.\d+\.\d+$' -or $RunnerSha256 -notmatch '^[a-f0-9]{64}$') {
    throw 'The pinned runner version or SHA-256 is invalid.'
}
$rootfsUri = $null
if (-not [Uri]::TryCreate($UbuntuRootfsUrl, [UriKind]::Absolute, [ref]$rootfsUri) -or
    $rootfsUri.Scheme -ne 'https' -or
    $rootfsUri.Host -ne 'cloud-images.ubuntu.com' -or
    $rootfsUri.AbsolutePath -notmatch '^/wsl/releases/24\.04/[^/]+/ubuntu-noble-wsl-amd64-24\.04lts\.rootfs\.tar\.gz$' -or
    $UbuntuRootfsSha256 -notmatch '^[a-f0-9]{64}$') {
    throw 'The pinned Ubuntu WSL rootfs URL or SHA-256 is invalid.'
}

$evidence = [ordered]@{
    schema_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString('o')
    source_sha = $env:GITHUB_SHA
    run_id = $env:GITHUB_RUN_ID
    repository = $repository
    administrator = $isAdmin
    distribution = $Distribution
    runner_name = $RunnerName
    runner_label = $RunnerLabel
    runner_version = $RunnerVersion
    runner_package_sha256 = $RunnerSha256
    runner_package_url = $packageUrl
    ubuntu_rootfs_url = $UbuntuRootfsUrl
    ubuntu_rootfs_sha256 = $UbuntuRootfsSha256
    ubuntu_rootfs_download_verified = $false
    distribution_install_method = $null
    distribution_install_root = $distributionInstallRoot
    wsl_runner_root = $runnerRoot
    windows_runner_paths_modified = $false
    automatic_restart_performed = $false
    restart_required = $false
    bybit_private_credentials_used = $false
    github_registration_token_persisted = $false
    github_runner_status = $null
    task_state = $null
    error_class = $null
    decision = $null
}

function Complete-Provisioning {
    param(
        [Parameter(Mandatory = $true)][string]$Decision,
        [int]$ExitCode = 0,
        [string]$ErrorClass = $null
    )

    $evidence.decision = $Decision
    $evidence.error_class = $ErrorClass
    Write-Evidence -Target $target -Payload $evidence
    $digest = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Host "bybit_wsl_provisioning_decision=$Decision"
    Write-Host "restart_required=$($evidence.restart_required.ToString().ToLowerInvariant())"
    Write-Host "windows_runner_paths_modified=false"
    Write-Host "github_registration_token_persisted=false"
    Write-Host "evidence_sha256=$digest"
    exit $ExitCode
}

trap {
    $evidence.decision = 'WSL_RUNNER_PROVISIONING_FAILED'
    $evidence.error_class = $_.Exception.GetType().Name
    Write-Evidence -Target $target -Payload $evidence
    $digest = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Host 'bybit_wsl_provisioning_decision=WSL_RUNNER_PROVISIONING_FAILED'
    Write-Host "provisioning_error_class=$($evidence.error_class)"
    Write-Host 'automatic_restart_performed=false'
    Write-Host 'windows_runner_paths_modified=false'
    Write-Host 'github_registration_token_persisted=false'
    Write-Host "evidence_sha256=$digest"
    exit 1
}

if (-not $isAdmin) {
    Complete-Provisioning -Decision 'ADMINISTRATOR_TOKEN_REQUIRED' -ExitCode 1 -ErrorClass 'SecurityException'
}

$wslFeature = Get-FeatureState -Name 'Microsoft-Windows-Subsystem-Linux'
$vmFeature = Get-FeatureState -Name 'VirtualMachinePlatform'
$evidence.windows_features = [ordered]@{
    wsl = $wslFeature
    virtual_machine_platform = $vmFeature
}
if ($wslFeature -ne 'Enabled' -or $vmFeature -ne 'Enabled') {
    Complete-Provisioning -Decision 'WSL_FEATURES_NOT_READY' -ExitCode 1 -ErrorClass 'InvalidOperationException'
}

$distributions = Get-WslDistributions
if ($Distribution -notin $distributions) {
    $help = Invoke-Wsl -Arguments @('--help')
    if ($help.output -match '--install' -and $help.output -match '--no-launch') {
        $evidence.distribution_install_method = 'wsl_install_no_launch'
        $installArguments = @('--install', '--distribution', $Distribution, '--no-launch')
        if ($help.output -match '--web-download') {
            $installArguments += '--web-download'
        }
        $install = Invoke-Wsl -Arguments $installArguments
    }
    elseif ($help.output -match '--import') {
        $evidence.distribution_install_method = 'pinned_ubuntu_rootfs_import'
        $installParent = Split-Path -Parent $distributionInstallRoot
        New-Item -ItemType Directory -Path $installParent -Force | Out-Null
        if (Test-Path -LiteralPath $distributionInstallRoot) {
            $existingItems = @(Get-ChildItem -LiteralPath $distributionInstallRoot -Force -ErrorAction Stop)
            if ($existingItems.Count -gt 0) {
                Complete-Provisioning -Decision 'WSL_IMPORT_LOCATION_NOT_EMPTY' -ExitCode 1 -ErrorClass 'InvalidOperationException'
            }
        }
        else {
            New-Item -ItemType Directory -Path $distributionInstallRoot -Force | Out-Null
        }

        $rootfsArchive = Join-Path ([IO.Path]::GetTempPath()) ("nexus-ubuntu-wsl-{0}.rootfs.tar.gz" -f [Guid]::NewGuid().ToString('N'))
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri $UbuntuRootfsUrl -OutFile $rootfsArchive -UseBasicParsing
            $downloadedRootfsSha256 = (Get-FileHash -LiteralPath $rootfsArchive -Algorithm SHA256).Hash.ToLowerInvariant()
            $evidence.ubuntu_rootfs_downloaded_sha256 = $downloadedRootfsSha256
            if ($downloadedRootfsSha256 -ne $UbuntuRootfsSha256) {
                Complete-Provisioning -Decision 'UBUNTU_ROOTFS_CHECKSUM_MISMATCH' -ExitCode 1 -ErrorClass 'InvalidDataException'
            }
            $evidence.ubuntu_rootfs_download_verified = $true
            $install = Invoke-Wsl -Arguments @('--import', $Distribution, $distributionInstallRoot, $rootfsArchive, '--version', '2')
        }
        finally {
            if (Test-Path -LiteralPath $rootfsArchive -PathType Leaf) {
                Remove-Item -LiteralPath $rootfsArchive -Force
            }
        }
    }
    else {
        Complete-Provisioning -Decision 'WSL_NONINTERACTIVE_INSTALL_UNAVAILABLE' -ExitCode 1 -ErrorClass 'NotSupportedException'
    }

    $evidence.distribution_install_exit_code = $install.exit_code
    if ($install.exit_code -ne 0) {
        Complete-Provisioning -Decision 'WSL_DISTRIBUTION_INSTALL_FAILED' -ExitCode 1 -ErrorClass 'InvalidOperationException'
    }

    $distributions = Get-WslDistributions
    if ($Distribution -notin $distributions) {
        $evidence.restart_required = ($install.output -match '(?i)restart|reboot')
        Complete-Provisioning -Decision 'WSL_DISTRIBUTION_INSTALL_PENDING'
    }
}

$evidence.distribution_installed = $true
$initialize = Invoke-Wsl -Arguments @('-d', $Distribution, '-u', 'root', '--', 'sh', '-lc', 'printf NEXUS_WSL_READY')
if ($initialize.exit_code -ne 0 -or $initialize.output -notmatch 'NEXUS_WSL_READY') {
    Complete-Provisioning -Decision 'WSL_DISTRIBUTION_INITIALIZATION_FAILED' -ExitCode 1 -ErrorClass 'InvalidOperationException'
}

$dependencyCommand = 'export DEBIAN_FRONTEND=noninteractive; apt-get update; apt-get install -y ca-certificates curl tar gzip git libicu-dev'
$dependencies = Invoke-Wsl -Arguments @('-d', $Distribution, '-u', 'root', '--', 'bash', '-lc', $dependencyCommand)
if ($dependencies.exit_code -ne 0) {
    Complete-Provisioning -Decision 'WSL_DEPENDENCY_INSTALL_FAILED' -ExitCode 1 -ErrorClass 'InvalidOperationException'
}
$evidence.linux_dependencies_installed = $true

$configuredProbe = Invoke-Wsl -Arguments @('-d', $Distribution, '-u', 'root', '--', 'bash', '-lc', "test -f '$runnerRoot/.runner'")
$runnerConfigured = $configuredProbe.exit_code -eq 0
if (-not $runnerConfigured) {
    $installRunnerCommand = @"
set -euo pipefail
runner_root='$runnerRoot'
archive='/tmp/$packageName'
install -d -m 0755 "`$runner_root"
find "`$runner_root" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
curl --fail --location --retry 3 --output "`$archive" '$packageUrl'
printf '%s  %s\n' '$RunnerSha256' "`$archive" | sha256sum --check --status
tar --extract --gzip --file "`$archive" --directory "`$runner_root"
rm -f -- "`$archive"
"@
    $runnerInstall = Invoke-Wsl -Arguments @('-d', $Distribution, '-u', 'root', '--', 'bash', '-lc', $installRunnerCommand)
    if ($runnerInstall.exit_code -ne 0) {
        Complete-Provisioning -Decision 'LINUX_RUNNER_PACKAGE_INSTALL_FAILED' -ExitCode 1 -ErrorClass 'InvalidOperationException'
    }
    $evidence.runner_package_installed = $true

    $gh = Resolve-Gh
    if (-not $gh) {
        Complete-Provisioning -Decision 'GH_CLI_REQUIRED'
    }
    & $gh auth status --hostname github.com 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) {
        Complete-Provisioning -Decision 'GH_AUTH_REQUIRED'
    }

    $registrationToken = $null
    try {
        $registrationToken = [string](& $gh api --hostname github.com --method POST "repos/$repository/actions/runners/registration-token" --jq '.token' 2>$null | Select-Object -First 1)
        $registrationToken = $registrationToken.Trim()
    }
    catch {
        $registrationToken = $null
    }
    if (-not $registrationToken -or $registrationToken.Length -lt 10 -or $registrationToken -match '\s') {
        Complete-Provisioning -Decision 'RUNNER_TOKEN_PERMISSION_REQUIRED'
    }

    $oldToken = $env:NEXUS_RUNNER_TOKEN
    $oldUrl = $env:NEXUS_REPOSITORY_URL
    $oldName = $env:NEXUS_RUNNER_NAME
    $oldLabel = $env:NEXUS_RUNNER_LABEL
    $oldWslEnv = $env:WSLENV
    try {
        $env:NEXUS_RUNNER_TOKEN = $registrationToken
        $env:NEXUS_REPOSITORY_URL = $repositoryUrl
        $env:NEXUS_RUNNER_NAME = $RunnerName
        $env:NEXUS_RUNNER_LABEL = $RunnerLabel
        $wslEnvPrefix = 'NEXUS_RUNNER_TOKEN/w:NEXUS_REPOSITORY_URL/w:NEXUS_RUNNER_NAME/w:NEXUS_RUNNER_LABEL/w'
        $env:WSLENV = if ($oldWslEnv) { "$wslEnvPrefix`:$oldWslEnv" } else { $wslEnvPrefix }
        $configureCommand = @'
set -euo pipefail
cd /opt/nexus-bybit-runner
export RUNNER_ALLOW_RUNASROOT=1
./config.sh --unattended --url "$NEXUS_REPOSITORY_URL" --token "$NEXUS_RUNNER_TOKEN" --name "$NEXUS_RUNNER_NAME" --work '_work' --labels "$NEXUS_RUNNER_LABEL" --replace
unset NEXUS_RUNNER_TOKEN
'@
        $configure = Invoke-Wsl -Arguments @('-d', $Distribution, '-u', 'root', '--', 'bash', '-lc', $configureCommand)
    }
    finally {
        $registrationToken = $null
        if ($null -eq $oldToken) { Remove-Item Env:NEXUS_RUNNER_TOKEN -ErrorAction SilentlyContinue } else { $env:NEXUS_RUNNER_TOKEN = $oldToken }
        if ($null -eq $oldUrl) { Remove-Item Env:NEXUS_REPOSITORY_URL -ErrorAction SilentlyContinue } else { $env:NEXUS_REPOSITORY_URL = $oldUrl }
        if ($null -eq $oldName) { Remove-Item Env:NEXUS_RUNNER_NAME -ErrorAction SilentlyContinue } else { $env:NEXUS_RUNNER_NAME = $oldName }
        if ($null -eq $oldLabel) { Remove-Item Env:NEXUS_RUNNER_LABEL -ErrorAction SilentlyContinue } else { $env:NEXUS_RUNNER_LABEL = $oldLabel }
        if ($null -eq $oldWslEnv) { Remove-Item Env:WSLENV -ErrorAction SilentlyContinue } else { $env:WSLENV = $oldWslEnv }
    }
    if ($configure.exit_code -ne 0) {
        Complete-Provisioning -Decision 'LINUX_RUNNER_REGISTRATION_FAILED' -ExitCode 1 -ErrorClass 'InvalidOperationException'
    }
    $evidence.runner_registered = $true
}
else {
    $evidence.runner_package_installed = $true
    $evidence.runner_registered = $true
}

$userId = "$env:USERDOMAIN\$env:USERNAME"
$taskArguments = "-d $Distribution -u root -- bash -lc `"cd $runnerRoot && export RUNNER_ALLOW_RUNASROOT=1 && exec ./run.sh`""
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\wsl.exe" -Argument $taskArguments
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650) `
    -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 8
$taskInfo = Get-ScheduledTaskInfo -TaskName $taskName
$evidence.task_state = [string](Get-ScheduledTask -TaskName $taskName).State
$evidence.task_last_result = [int]$taskInfo.LastTaskResult
$evidence.autostart_installed = $true

$ghForStatus = Resolve-Gh
if ($ghForStatus) {
    & $ghForStatus auth status --hostname github.com 1>$null 2>$null
    if ($LASTEXITCODE -eq 0) {
        for ($attempt = 0; $attempt -lt 4; $attempt++) {
            try {
                $runnerPayload = & $ghForStatus api --hostname github.com "repos/$repository/actions/runners?per_page=100" 2>$null | ConvertFrom-Json
                $matchedRunner = @($runnerPayload.runners | Where-Object { $_.name -eq $RunnerName } | Select-Object -First 1)
                if ($matchedRunner.Count -eq 1) {
                    $evidence.github_runner_status = [string]$matchedRunner[0].status
                    $evidence.github_runner_busy = [bool]$matchedRunner[0].busy
                    if ($matchedRunner[0].status -eq 'online') {
                        Complete-Provisioning -Decision 'READY_FOR_GITHUB_VALIDATION'
                    }
                }
            }
            catch { }
            Start-Sleep -Seconds 5
        }
    }
}

Complete-Provisioning -Decision 'LINUX_RUNNER_START_PENDING'
