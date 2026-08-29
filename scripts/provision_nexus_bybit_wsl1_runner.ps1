param(
    [string]$Distribution = 'Ubuntu',
    [string]$OutputPath = 'build\bybit-wsl1-runner\evidence.json',
    [string]$RunnerName = 'NEXUS-BYBIT-WSL',
    [string]$RunnerLabel = 'nexus-bybit-network',
    [string]$RunnerVersion = '2.336.0',
    [string]$RunnerSha256 = '04cf0be1aff4c3ec3554466c39124ca250e3effd8873bb7e8d68535aa9505d5d'
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Write-Evidence {
    param([Parameter(Mandatory = $true)][System.Collections.IDictionary]$Payload)
    $parent = Split-Path -Parent $OutputPath
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    $json = $Payload | ConvertTo-Json -Depth 10
    [IO.File]::WriteAllText([IO.Path]::GetFullPath($OutputPath), $json, (New-Object Text.UTF8Encoding($false)))
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

function Invoke-Wsl {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $raw = @(& "$env:SystemRoot\System32\wsl.exe" @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
        $text = (($raw | ForEach-Object { $_.ToString() }) | Out-String)
        $text = ($text -replace "`0", '').Trim()
        return [ordered]@{
            exit_code = if ($null -eq $exitCode) { -1 } else { [int]$exitCode }
            output = $text
        }
    }
    catch {
        return [ordered]@{ exit_code = -1; output = $_.Exception.ToString() }
    }
    finally {
        $ErrorActionPreference = $previous
    }
}

function Invoke-WslEncodedBash {
    param([Parameter(Mandatory = $true)][string]$Script)
    $normalized = ($Script -replace "`r", '')
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($normalized))
    if ($encoded -notmatch '^[A-Za-z0-9+/=]+$') { throw 'Unexpected Base64 payload characters.' }
    $bootstrap = "printf %s $encoded | base64 --decode | bash"
    return Invoke-Wsl -Arguments @('-d', $Distribution, '-u', 'root', '--', 'bash', '-lc', $bootstrap)
}

function Clip-Text {
    param([string]$Text, [int]$Maximum = 4096)
    if ($null -eq $Text) { return $null }
    if ($Text.Length -le $Maximum) { return $Text }
    return $Text.Substring(0, $Maximum)
}

foreach ($value in @($Distribution, $RunnerName, $RunnerLabel)) {
    if ($value -notmatch '^[A-Za-z0-9._-]+$') { throw 'Unsafe distribution, runner name, or label.' }
}
if ($RunnerVersion -notmatch '^\d+\.\d+\.\d+$' -or $RunnerSha256 -notmatch '^[a-f0-9]{64}$') {
    throw 'Pinned runner version or SHA-256 is invalid.'
}
$repository = [string]$env:GITHUB_REPOSITORY
if ($repository -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') { throw 'GITHUB_REPOSITORY is missing or invalid.' }

$runnerRoot = '/opt/nexus-bybit-runner'
$packageName = "actions-runner-linux-x64-$RunnerVersion.tar.gz"
$packageUrl = "https://github.com/actions/runner/releases/download/v$RunnerVersion/$packageName"
$repositoryUrl = "https://github.com/$repository"
$taskName = 'NEXUS Bybit WSL Runner'

$evidence = [ordered]@{
    schema_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString('o')
    source_sha = $env:GITHUB_SHA
    run_id = $env:GITHUB_RUN_ID
    repository = $repository
    administrator = (Test-IsAdministrator)
    distribution = $Distribution
    runner_name = $RunnerName
    runner_label = $RunnerLabel
    runner_version = $RunnerVersion
    runner_package_url = $packageUrl
    runner_package_sha256 = $RunnerSha256
    transport = 'base64_utf8_lf_to_wsl_bash'
    windows_runner_paths_modified = $false
    windows_runner_service_modified = $false
    automatic_restart_performed = $false
    firmware_setting_modified = $false
    bybit_private_credentials_used = $false
    github_registration_token_persisted = $false
    decision = $null
    error_class = $null
}

function Complete-Bootstrap {
    param([Parameter(Mandatory = $true)][string]$Decision, [int]$ExitCode = 0, [string]$ErrorClass = $null)
    $evidence.decision = $Decision
    $evidence.error_class = $ErrorClass
    Write-Evidence -Payload $evidence
    $digest = (Get-FileHash -LiteralPath ([IO.Path]::GetFullPath($OutputPath)) -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Host "bybit_wsl1_runner_decision=$Decision"
    Write-Host 'windows_runner_paths_modified=false'
    Write-Host 'windows_runner_service_modified=false'
    Write-Host 'automatic_restart_performed=false'
    Write-Host 'firmware_setting_modified=false'
    Write-Host 'github_registration_token_persisted=false'
    Write-Host "evidence_sha256=$digest"
    exit $ExitCode
}

trap {
    $evidence.error_detail = Clip-Text -Text $_.Exception.ToString()
    Complete-Bootstrap -Decision 'WSL1_RUNNER_BOOTSTRAP_FAILED' -ExitCode 1 -ErrorClass $_.Exception.GetType().Name
}

if (-not $evidence.administrator) {
    Complete-Bootstrap -Decision 'ADMINISTRATOR_TOKEN_REQUIRED' -ExitCode 1 -ErrorClass 'SecurityException'
}

$versionProbe = Invoke-Wsl -Arguments @('--list', '--verbose')
$evidence.wsl_list_exit_code = $versionProbe.exit_code
$evidence.wsl_list_output = Clip-Text -Text $versionProbe.output
if ($versionProbe.exit_code -ne 0 -or $versionProbe.output -notmatch "(?im)^\*?\s*$([regex]::Escape($Distribution))\s+\S+\s+1\s*$") {
    Complete-Bootstrap -Decision 'WSL1_DISTRIBUTION_REQUIRED' -ExitCode 1 -ErrorClass 'InvalidOperationException'
}

$dependencyProbe = Invoke-WslEncodedBash -Script @'
set -euo pipefail
for command in curl sha256sum tar gzip git base64; do
  command -v "$command" >/dev/null
 done
printf NEXUS_WSL1_DEPENDENCIES_READY
'@
$evidence.dependency_probe_exit_code = $dependencyProbe.exit_code
$evidence.dependency_probe_output = Clip-Text -Text $dependencyProbe.output
if ($dependencyProbe.exit_code -ne 0 -or $dependencyProbe.output -notmatch 'NEXUS_WSL1_DEPENDENCIES_READY') {
    Complete-Bootstrap -Decision 'WSL1_DEPENDENCIES_NOT_READY' -ExitCode 1 -ErrorClass 'InvalidOperationException'
}

$configuredProbe = Invoke-WslEncodedBash -Script @'
test -s /opt/nexus-bybit-runner/.runner && test -x /opt/nexus-bybit-runner/run.sh
'@
$runnerConfigured = $configuredProbe.exit_code -eq 0
$evidence.runner_preconfigured = $runnerConfigured

if (-not $runnerConfigured) {
    $installScript = @"
set -euo pipefail
runner_root='$runnerRoot'
archive='/tmp/$packageName'
install -d -m 0755 "`$runner_root"
find "`$runner_root" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
rm -f -- "`$archive"
curl --fail --location --retry 3 --connect-timeout 20 --max-time 600 --output "`$archive" '$packageUrl'
printf '%s  %s\n' '$RunnerSha256' "`$archive" | sha256sum --check --status
tar --extract --gzip --file "`$archive" --directory "`$runner_root"
rm -f -- "`$archive"
test -x "`$runner_root/config.sh"
test -x "`$runner_root/run.sh"
printf NEXUS_RUNNER_PACKAGE_READY
"@
    $install = Invoke-WslEncodedBash -Script $installScript
    $evidence.runner_package_install_exit_code = $install.exit_code
    $evidence.runner_package_install_output = Clip-Text -Text $install.output
    if ($install.exit_code -ne 0 -or $install.output -notmatch 'NEXUS_RUNNER_PACKAGE_READY') {
        Complete-Bootstrap -Decision 'LINUX_RUNNER_PACKAGE_INSTALL_FAILED' -ExitCode 1 -ErrorClass 'InvalidOperationException'
    }
    $evidence.runner_package_installed = $true

    $gh = Resolve-Gh
    if (-not $gh) { Complete-Bootstrap -Decision 'GH_CLI_REQUIRED' }
    & $gh auth status --hostname github.com 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) { Complete-Bootstrap -Decision 'GH_AUTH_REQUIRED' }

    $registrationToken = $null
    try {
        $registrationToken = [string](& $gh api --hostname github.com --method POST "repos/$repository/actions/runners/registration-token" --jq '.token' 2>$null | Select-Object -First 1)
        $registrationToken = $registrationToken.Trim()
    }
    catch { $registrationToken = $null }
    if (-not $registrationToken -or $registrationToken.Length -lt 10 -or $registrationToken -match '\s') {
        Complete-Bootstrap -Decision 'RUNNER_TOKEN_PERMISSION_REQUIRED'
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
        $prefix = 'NEXUS_RUNNER_TOKEN:NEXUS_REPOSITORY_URL:NEXUS_RUNNER_NAME:NEXUS_RUNNER_LABEL'
        $env:WSLENV = if ($oldWslEnv) { "$prefix`:$oldWslEnv" } else { $prefix }
        $configureScript = @'
set -euo pipefail
cd /opt/nexus-bybit-runner
export RUNNER_ALLOW_RUNASROOT=1
./config.sh --unattended --url "$NEXUS_REPOSITORY_URL" --token "$NEXUS_RUNNER_TOKEN" --name "$NEXUS_RUNNER_NAME" --work _work --labels "$NEXUS_RUNNER_LABEL" --replace
cat > /opt/nexus-bybit-runner/nexus-runner-start.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
export RUNNER_ALLOW_RUNASROOT=1
cd /opt/nexus-bybit-runner
exec ./run.sh
EOF
chmod 0755 /opt/nexus-bybit-runner/nexus-runner-start.sh
unset NEXUS_RUNNER_TOKEN
printf NEXUS_RUNNER_CONFIGURED
'@
        $configure = Invoke-WslEncodedBash -Script $configureScript
    }
    finally {
        $registrationToken = $null
        if ($null -eq $oldToken) { Remove-Item Env:NEXUS_RUNNER_TOKEN -ErrorAction SilentlyContinue } else { $env:NEXUS_RUNNER_TOKEN = $oldToken }
        if ($null -eq $oldUrl) { Remove-Item Env:NEXUS_REPOSITORY_URL -ErrorAction SilentlyContinue } else { $env:NEXUS_REPOSITORY_URL = $oldUrl }
        if ($null -eq $oldName) { Remove-Item Env:NEXUS_RUNNER_NAME -ErrorAction SilentlyContinue } else { $env:NEXUS_RUNNER_NAME = $oldName }
        if ($null -eq $oldLabel) { Remove-Item Env:NEXUS_RUNNER_LABEL -ErrorAction SilentlyContinue } else { $env:NEXUS_RUNNER_LABEL = $oldLabel }
        if ($null -eq $oldWslEnv) { Remove-Item Env:WSLENV -ErrorAction SilentlyContinue } else { $env:WSLENV = $oldWslEnv }
    }
    $evidence.runner_configuration_exit_code = $configure.exit_code
    $evidence.runner_configuration_output = Clip-Text -Text $configure.output
    if ($configure.exit_code -ne 0 -or $configure.output -notmatch 'NEXUS_RUNNER_CONFIGURED') {
        Complete-Bootstrap -Decision 'LINUX_RUNNER_REGISTRATION_FAILED' -ExitCode 1 -ErrorClass 'InvalidOperationException'
    }
    $evidence.runner_registered = $true
}
else {
    $evidence.runner_package_installed = $true
    $evidence.runner_registered = $true
}

$startProbe = Invoke-WslEncodedBash -Script @'
test -x /opt/nexus-bybit-runner/nexus-runner-start.sh || { cat > /opt/nexus-bybit-runner/nexus-runner-start.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
export RUNNER_ALLOW_RUNASROOT=1
cd /opt/nexus-bybit-runner
exec ./run.sh
EOF
chmod 0755 /opt/nexus-bybit-runner/nexus-runner-start.sh
}
printf NEXUS_RUNNER_START_WRAPPER_READY
'@
if ($startProbe.exit_code -ne 0) {
    Complete-Bootstrap -Decision 'LINUX_RUNNER_START_WRAPPER_FAILED' -ExitCode 1 -ErrorClass 'InvalidOperationException'
}

$userId = "$env:USERDOMAIN\$env:USERNAME"
$taskArguments = "-d $Distribution -u root -- $runnerRoot/nexus-runner-start.sh"
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\wsl.exe" -Argument $taskArguments
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 3650) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
$evidence.autostart_installed = $true
Start-Sleep -Seconds 8
$task = Get-ScheduledTask -TaskName $taskName
$taskInfo = Get-ScheduledTaskInfo -TaskName $taskName
$evidence.task_state = [string]$task.State
$evidence.task_last_result = [int]$taskInfo.LastTaskResult

$ghStatus = Resolve-Gh
if ($ghStatus) {
    & $ghStatus auth status --hostname github.com 1>$null 2>$null
    if ($LASTEXITCODE -eq 0) {
        for ($attempt = 0; $attempt -lt 6; $attempt++) {
            try {
                $payload = & $ghStatus api --hostname github.com "repos/$repository/actions/runners?per_page=100" 2>$null | ConvertFrom-Json
                $matched = @($payload.runners | Where-Object { $_.name -eq $RunnerName } | Select-Object -First 1)
                if ($matched.Count -eq 1) {
                    $evidence.github_runner_status = [string]$matched[0].status
                    $evidence.github_runner_busy = [bool]$matched[0].busy
                    if ($matched[0].status -eq 'online') {
                        Complete-Bootstrap -Decision 'READY_FOR_GITHUB_VALIDATION'
                    }
                }
            }
            catch { }
            Start-Sleep -Seconds 5
        }
    }
}

Complete-Bootstrap -Decision 'LINUX_RUNNER_START_PENDING'
