param(
    [string]$OutputPath = "build\bybit-wsl-package-repair\evidence.json",
    [string]$Distribution = "Ubuntu",
    [string]$RunnerName = "NEXUS-BYBIT-WSL",
    [string]$RunnerLabel = "nexus-bybit-network",
    [string]$RunnerVersion = "2.336.0",
    [string]$RunnerSha256 = "04cf0be1aff4c3ec3554466c39124ca250e3effd8873bb7e8d68535aa9505d5d"
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$script:hostPackagePath = $null

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

function Invoke-EncodedWslBash {
    param(
        [Parameter(Mandatory = $true)][string]$DistributionName,
        [Parameter(Mandatory = $true)][string]$Script
    )

    # Multiline Bash is opaque across Windows PowerShell 5.1 -> wsl.exe.
    $normalized = $Script.Replace("`r`n", "`n").Replace("`r", "`n")
    $payload = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($normalized))
    $launcher = "printf '%s' '$payload' | base64 -d | bash"
    return Invoke-Wsl -Arguments @('-d', $DistributionName, '-u', 'root', '--', 'bash', '-lc', $launcher)
}

function Resolve-Gh {
    $candidates = @()
    $command = Get-Command gh.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command) { $candidates += $command.Source }
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
    $json = $Payload | ConvertTo-Json -Depth 8
    [IO.File]::WriteAllText($Target, $json, (New-Object Text.UTF8Encoding($false)))
}

$target = [IO.Path]::GetFullPath($OutputPath)
$repository = [string]$env:GITHUB_REPOSITORY
$repositoryUrl = if ($repository) { "https://github.com/$repository" } else { $null }
$runnerRoot = '/opt/nexus-bybit-runner'
$packageName = "actions-runner-linux-x64-$RunnerVersion.tar.gz"
$packageUrl = "https://github.com/actions/runner/releases/download/v$RunnerVersion/$packageName"

$evidence = [ordered]@{
    schema_version = 2
    generated_at_utc = [DateTime]::UtcNow.ToString('o')
    source_sha = $env:GITHUB_SHA
    run_id = $env:GITHUB_RUN_ID
    run_attempt = $env:GITHUB_RUN_ATTEMPT
    repository = $repository
    distribution = $Distribution
    runner_name = $RunnerName
    runner_label = $RunnerLabel
    runner_version = $RunnerVersion
    runner_package_url = $packageUrl
    runner_package_sha256 = $RunnerSha256
    bash_transport = 'base64_utf8_single_line_launcher'
    package_transport = 'windows_host_stage_then_wsl_mount'
    wslenv_direction = 'windows_to_wsl_u'
    github_registration_token_persisted = $false
    host_package_path_persisted = $false
    host_package_downloaded = $false
    host_package_verified = $false
    package_installed = $false
    runner_registered = $false
    decision = $null
    error_class = $null
}

function Complete-Repair {
    param(
        [Parameter(Mandatory = $true)][string]$Decision,
        [int]$ExitCode = 0,
        [string]$ErrorClass = $null,
        [string]$Detail = $null
    )

    if ($script:hostPackagePath -and (Test-Path -LiteralPath $script:hostPackagePath -PathType Leaf)) {
        Remove-Item -LiteralPath $script:hostPackagePath -Force -ErrorAction SilentlyContinue
    }
    $evidence.host_package_path_persisted = $false
    $evidence.decision = $Decision
    $evidence.error_class = $ErrorClass
    if ($Detail) {
        if ($Detail.Length -gt 2048) { $Detail = $Detail.Substring(0, 2048) }
        $evidence.detail = $Detail
    }
    Write-Evidence -Target $target -Payload $evidence
    $digest = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Host "bybit_wsl_package_repair_decision=$Decision"
    Write-Host 'github_registration_token_persisted=false'
    Write-Host 'host_package_path_persisted=false'
    Write-Host "evidence_sha256=$digest"
    exit $ExitCode
}

trap {
    Complete-Repair -Decision 'RUNNER_PACKAGE_REPAIR_FAILED' -ExitCode 1 -ErrorClass $_.Exception.GetType().Name -Detail $_.Exception.Message
}

if ($repository -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') {
    throw 'GITHUB_REPOSITORY is missing or invalid.'
}
foreach ($value in @($Distribution, $RunnerName, $RunnerLabel)) {
    if ($value -notmatch '^[A-Za-z0-9._-]+$') { throw 'Unsafe runner identifier.' }
}
if ($RunnerVersion -notmatch '^\d+\.\d+\.\d+$' -or $RunnerSha256 -notmatch '^[a-f0-9]{64}$') {
    throw 'Pinned runner package metadata is invalid.'
}

# WSL1 evidence shows GitHub release downloads inside WSL are too slow for a bounded
# provisioning job. Stage the pinned archive on the Windows host, verify it there,
# then consume the same bytes through the normal /mnt/<drive> WSL mount.
$tempRoot = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [IO.Path]::GetTempPath() }
$script:hostPackagePath = Join-Path $tempRoot ("nexus-{0}" -f $packageName)
$curl = Get-Command curl.exe -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $curl) {
    Complete-Repair -Decision 'WINDOWS_CURL_REQUIRED' -ExitCode 1 -ErrorClass 'FileNotFoundException'
}

$packageReady = $false
if (Test-Path -LiteralPath $script:hostPackagePath -PathType Leaf) {
    $existingHash = (Get-FileHash -LiteralPath $script:hostPackagePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($existingHash -eq $RunnerSha256) {
        $packageReady = $true
    }
}

for ($attempt = 1; -not $packageReady -and $attempt -le 4; $attempt++) {
    Write-Host "windows_runner_package_download_attempt=$attempt"
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $curl.Source `
            --fail `
            --location `
            --retry 5 `
            --retry-delay 2 `
            --connect-timeout 20 `
            --max-time 900 `
            --continue-at - `
            --output $script:hostPackagePath `
            $packageUrl
        $curlExit = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    if ($curlExit -eq 0 -and (Test-Path -LiteralPath $script:hostPackagePath -PathType Leaf)) {
        $downloadedHash = (Get-FileHash -LiteralPath $script:hostPackagePath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($downloadedHash -eq $RunnerSha256) {
            $packageReady = $true
            break
        }
        Remove-Item -LiteralPath $script:hostPackagePath -Force -ErrorAction SilentlyContinue
    }
}

if (-not $packageReady) {
    $bytes = if (Test-Path -LiteralPath $script:hostPackagePath -PathType Leaf) { (Get-Item -LiteralPath $script:hostPackagePath).Length } else { 0 }
    $evidence.host_package_bytes = [int64]$bytes
    Complete-Repair -Decision 'WINDOWS_HOST_RUNNER_PACKAGE_DOWNLOAD_FAILED' -ExitCode 1 -ErrorClass 'InvalidOperationException'
}
$evidence.host_package_downloaded = $true
$evidence.host_package_verified = $true
$evidence.host_package_bytes = [int64](Get-Item -LiteralPath $script:hostPackagePath).Length

# Avoid relying on the distro's wslpath helper: physical WSL1 evidence showed that
# helper can fail even though the standard /mnt/<drive> automount is available.
$hostFullPath = [IO.Path]::GetFullPath($script:hostPackagePath)
if ($hostFullPath -notmatch '^(?<drive>[A-Za-z]):\\(?<rest>.+)$') {
    Complete-Repair -Decision 'WINDOWS_PACKAGE_WSL_PATH_FAILED' -ExitCode 1 -ErrorClass 'InvalidOperationException' -Detail 'Host package path is not drive-rooted.'
}
$drive = $Matches['drive'].ToLowerInvariant()
$rest = $Matches['rest'].Replace('\', '/')
$wslArchivePath = "/mnt/$drive/$rest"
if (-not $wslArchivePath -or $wslArchivePath -match "[`r`n']") {
    Complete-Repair -Decision 'WINDOWS_PACKAGE_WSL_PATH_UNSAFE' -ExitCode 1 -ErrorClass 'InvalidDataException'
}

$installScript = @"
set -euo pipefail
runner_root='$runnerRoot'
archive='$wslArchivePath'
test -r "`$archive"
printf '%s  %s\n' '$RunnerSha256' "`$archive" | sha256sum --check --status
install -d -m 0755 "`$runner_root"
find "`$runner_root" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
tar --extract --gzip --file "`$archive" --directory "`$runner_root"
"@
$install = Invoke-EncodedWslBash -DistributionName $Distribution -Script $installScript
if ($install.exit_code -ne 0) {
    Complete-Repair -Decision 'RUNNER_PACKAGE_REPAIR_INSTALL_FAILED' -ExitCode 1 -ErrorClass 'InvalidOperationException' -Detail $install.output
}
$evidence.package_installed = $true
Remove-Item -LiteralPath $script:hostPackagePath -Force -ErrorAction SilentlyContinue
$script:hostPackagePath = $null

$gh = Resolve-Gh
if (-not $gh) { Complete-Repair -Decision 'GH_CLI_REQUIRED' -ExitCode 1 -ErrorClass 'FileNotFoundException' }
& $gh auth status --hostname github.com 1>$null 2>$null
if ($LASTEXITCODE -ne 0) { Complete-Repair -Decision 'GH_AUTH_REQUIRED' -ExitCode 1 -ErrorClass 'SecurityException' }

$registrationToken = $null
try {
    $registrationToken = [string](& $gh api --hostname github.com --method POST "repos/$repository/actions/runners/registration-token" --jq '.token' 2>$null | Select-Object -First 1)
    $registrationToken = $registrationToken.Trim()
}
catch {
    $registrationToken = $null
}
if (-not $registrationToken -or $registrationToken.Length -lt 10 -or $registrationToken -match '\s') {
    Complete-Repair -Decision 'RUNNER_TOKEN_PERMISSION_REQUIRED' -ExitCode 1 -ErrorClass 'SecurityException'
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
    # /u is the Win32 -> WSL direction; /w is the inverse direction.
    $wslEnvPrefix = 'NEXUS_RUNNER_TOKEN/u:NEXUS_REPOSITORY_URL/u:NEXUS_RUNNER_NAME/u:NEXUS_RUNNER_LABEL/u'
    $env:WSLENV = if ($oldWslEnv) { "$wslEnvPrefix`:$oldWslEnv" } else { $wslEnvPrefix }
    $configureScript = @'
set -euo pipefail
cd /opt/nexus-bybit-runner
export RUNNER_ALLOW_RUNASROOT=1
./config.sh --unattended --url "$NEXUS_REPOSITORY_URL" --token "$NEXUS_RUNNER_TOKEN" --name "$NEXUS_RUNNER_NAME" --work '_work' --labels "$NEXUS_RUNNER_LABEL" --replace
unset NEXUS_RUNNER_TOKEN
'@
    $configure = Invoke-EncodedWslBash -DistributionName $Distribution -Script $configureScript
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
    Complete-Repair -Decision 'RUNNER_PACKAGE_REPAIR_REGISTRATION_FAILED' -ExitCode 1 -ErrorClass 'InvalidOperationException'
}

$probe = Invoke-Wsl -Arguments @('-d', $Distribution, '-u', 'root', '--', 'bash', '-lc', "test -f '$runnerRoot/.runner'")
if ($probe.exit_code -ne 0) {
    Complete-Repair -Decision 'RUNNER_PACKAGE_REPAIR_VERIFY_FAILED' -ExitCode 1 -ErrorClass 'InvalidOperationException' -Detail $probe.output
}
$evidence.runner_registered = $true
Complete-Repair -Decision 'RUNNER_PACKAGE_AND_REGISTRATION_REPAIRED'
