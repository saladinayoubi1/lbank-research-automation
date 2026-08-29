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

    # Keep multiline Bash opaque across the Windows PowerShell 5.1 -> wsl.exe argv boundary.
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
    schema_version = 1
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
    transport = 'base64_utf8_single_line_launcher'
    wslenv_direction = 'windows_to_wsl_u'
    github_registration_token_persisted = $false
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

$installScript = @"
set -euo pipefail
runner_root='$runnerRoot'
archive='/tmp/$packageName'
install -d -m 0755 "`$runner_root"
find "`$runner_root" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
curl --fail --location --retry 3 --retry-all-errors --connect-timeout 20 --max-time 300 --output "`$archive" '$packageUrl'
printf '%s  %s\n' '$RunnerSha256' "`$archive" | sha256sum --check --status
tar --extract --gzip --file "`$archive" --directory "`$runner_root"
rm -f -- "`$archive"
"@
$install = Invoke-EncodedWslBash -DistributionName $Distribution -Script $installScript
if ($install.exit_code -ne 0) {
    Complete-Repair -Decision 'RUNNER_PACKAGE_REPAIR_INSTALL_FAILED' -ExitCode 1 -ErrorClass 'InvalidOperationException' -Detail $install.output
}
$evidence.package_installed = $true

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
    # /u is the documented Win32 -> WSL direction. /w is the inverse direction.
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
    Complete-Repair -Decision 'RUNNER_PACKAGE_REPAIR_REGISTRATION_FAILED' -ExitCode 1 -ErrorClass 'InvalidOperationException' -Detail $configure.output
}

$probe = Invoke-Wsl -Arguments @('-d', $Distribution, '-u', 'root', '--', 'bash', '-lc', "test -f '$runnerRoot/.runner'")
if ($probe.exit_code -ne 0) {
    Complete-Repair -Decision 'RUNNER_PACKAGE_REPAIR_VERIFY_FAILED' -ExitCode 1 -ErrorClass 'InvalidOperationException' -Detail $probe.output
}
$evidence.runner_registered = $true
Complete-Repair -Decision 'RUNNER_PACKAGE_AND_REGISTRATION_REPAIRED'
