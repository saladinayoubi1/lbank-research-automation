[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$SourceSha,
    [string]$RegistrationToken = $env:NEXUS_GITHUB_RUNNER_REGISTRATION_TOKEN,
    [string]$RunnerName = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$ExpectedGitHubUrl = 'https://github.com/saladinayoubi1/lbank-research-automation'
$RunnerVersion = '2.336.0'
$RunnerArchiveName = "actions-runner-win-x64-$RunnerVersion.zip"
$RunnerArchiveSha256 = 'd59123a43003e357b0805b5d0f611d0bd2f65ab67d51bd070dd4e7a0f685c162'
$RunnerArchiveUrl = "https://github.com/actions/runner/releases/download/v$RunnerVersion/$RunnerArchiveName"
$NexusRoot = Join-Path $env:LOCALAPPDATA 'NEXUS'
$RunnerRoot = Join-Path $NexusRoot 'actions-runner'
$CacheRoot = Join-Path $NexusRoot 'runner-cache'
$StateRoot = Join-Path $NexusRoot 'RunnerProvision'
$EvidencePath = Join-Path $StateRoot 'evidence.json'
$LogPath = Join-Path $StateRoot 'provision.log'
$ManagedMarker = Join-Path $RunnerRoot '.nexus-managed-runner.json'
$BootstrapScript = Join-Path $PSScriptRoot 'bootstrap_nexus_runner_from_gui.ps1'

function Ensure-StateRoot {
    New-Item -ItemType Directory -Force -Path $StateRoot | Out-Null
}

function Write-Log([string]$Message) {
    Ensure-StateRoot
    $stamp = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
    Add-Content -LiteralPath $LogPath -Encoding UTF8 -Value "[$stamp] $Message"
}

function Write-Evidence([string]$Status, [hashtable]$Extra = @{}) {
    Ensure-StateRoot
    $payload = [ordered]@{
        contract_version = 'nexus.runner-provision.v1'
        status = $Status
        source_sha = $SourceSha.ToLowerInvariant()
        generated_at = [DateTime]::UtcNow.ToString('o')
        expected_repository = $ExpectedGitHubUrl
        runner_version = $RunnerVersion
        runner_archive_sha256 = $RunnerArchiveSha256
        registration_token_persisted = $false
        registration_token_logged = $false
        machine_execution_policy_modified = $false
        elevation_requested = $false
        service_installed = $false
        live_trading_authority = $false
        paper_only = $true
    }
    foreach ($key in $Extra.Keys) { $payload[$key] = $Extra[$key] }
    $tmp = $EvidencePath + '.tmp'
    $payload | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $tmp -Encoding UTF8
    Move-Item -LiteralPath $tmp -Destination $EvidencePath -Force
    Write-Log "status=$Status source_sha=$($SourceSha.ToLowerInvariant())"
}

function Fail([string]$Status, [string]$Message) {
    Write-Evidence $Status @{ error = $Message }
    throw "NEXUS runner provision: $Message"
}

function Assert-OwnerSession {
    if ($env:OS -ne 'Windows_NT') { Fail 'WINDOWS_REQUIRED' 'runner provisioning is Windows-only' }
    if (-not [Environment]::UserInteractive) { Fail 'INTERACTIVE_OWNER_REQUIRED' 'interactive owner session is required' }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    if ($identity -in @('NT AUTHORITY\SYSTEM','NT AUTHORITY\NETWORK SERVICE','NT AUTHORITY\LOCAL SERVICE')) {
        Fail 'SERVICE_IDENTITY_REJECTED' 'service identities may not provision runner registration'
    }
    if (-not [Environment]::Is64BitOperatingSystem) { Fail 'X64_WINDOWS_REQUIRED' '64-bit Windows is required' }
}

function Get-DefaultRunnerName {
    $machine = ([Environment]::MachineName -replace '[^A-Za-z0-9._-]','-').Trim('-')
    if (-not $machine) { $machine = 'WINDOWS' }
    $name = "NEXUS-LOCAL-RUNNER-$machine"
    if ($name.Length -gt 80) { $name = $name.Substring(0,80) }
    return $name
}

function Test-ConfiguredRunner {
    $settings = Join-Path $RunnerRoot '.runner'
    $credentials = Join-Path $RunnerRoot '.credentials'
    $runCmd = Join-Path $RunnerRoot 'run.cmd'
    $listener = Join-Path $RunnerRoot 'bin\Runner.Listener.exe'
    if (-not ((Test-Path -LiteralPath $settings -PathType Leaf) -and
              (Test-Path -LiteralPath $credentials -PathType Leaf) -and
              (Test-Path -LiteralPath $runCmd -PathType Leaf) -and
              (Test-Path -LiteralPath $listener -PathType Leaf))) { return $false }
    try {
        $config = Get-Content -LiteralPath $settings -Raw | ConvertFrom-Json
        $urlProperty = $config.PSObject.Properties['gitHubUrl']
        if (-not $urlProperty -or -not $urlProperty.Value) { return $false }
        return ([string]$urlProperty.Value).Trim().TrimEnd('/').ToLowerInvariant() -eq $ExpectedGitHubUrl.ToLowerInvariant()
    }
    catch { return $false }
}

function Assert-ManagedOrEmptyRunnerRoot {
    if (-not (Test-Path -LiteralPath $RunnerRoot -PathType Container)) { return }
    if (Test-ConfiguredRunner) { return }
    if (Test-Path -LiteralPath $ManagedMarker -PathType Leaf) { return }
    $entries = @(Get-ChildItem -LiteralPath $RunnerRoot -Force -ErrorAction Stop | Select-Object -First 1)
    if ($entries.Count -gt 0) {
        Fail 'UNMANAGED_RUNNER_ROOT_REJECTED' "refusing to alter non-empty unmanaged runner directory: $RunnerRoot"
    }
}

function Get-VerifiedRunnerArchive {
    New-Item -ItemType Directory -Force -Path $CacheRoot | Out-Null
    $archive = Join-Path $CacheRoot $RunnerArchiveName
    $valid = $false
    if (Test-Path -LiteralPath $archive -PathType Leaf) {
        try {
            $hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
            $valid = ($hash -eq $RunnerArchiveSha256)
        }
        catch { $valid = $false }
    }
    if (-not $valid) {
        $tmp = $archive + '.tmp'
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri $RunnerArchiveUrl -OutFile $tmp -TimeoutSec 120
        $hash = (Get-FileHash -LiteralPath $tmp -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($hash -ne $RunnerArchiveSha256) {
            Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
            Fail 'RUNNER_ARCHIVE_HASH_MISMATCH' 'official runner archive SHA-256 mismatch'
        }
        Move-Item -LiteralPath $tmp -Destination $archive -Force
    }
    return $archive
}

function Install-RunnerFiles([string]$Archive) {
    if (Test-ConfiguredRunner) { return }
    Assert-ManagedOrEmptyRunnerRoot
    New-Item -ItemType Directory -Force -Path $RunnerRoot | Out-Null
    if (-not (Test-Path -LiteralPath $ManagedMarker -PathType Leaf)) {
        $marker = [ordered]@{
            contract_version = 'nexus.managed-runner-root.v1'
            created_at = [DateTime]::UtcNow.ToString('o')
            runner_version = $RunnerVersion
            archive_sha256 = $RunnerArchiveSha256
        }
        $marker | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $ManagedMarker -Encoding UTF8
    }
    $config = Join-Path $RunnerRoot 'config.cmd'
    $listener = Join-Path $RunnerRoot 'bin\Runner.Listener.exe'
    if ((Test-Path -LiteralPath $config -PathType Leaf) -and (Test-Path -LiteralPath $listener -PathType Leaf)) { return }
    Expand-Archive -LiteralPath $Archive -DestinationPath $RunnerRoot -Force
    if (-not (Test-Path -LiteralPath $config -PathType Leaf)) { Fail 'RUNNER_EXTRACT_FAILED' 'config.cmd missing after verified archive extraction' }
    if (-not (Test-Path -LiteralPath $listener -PathType Leaf)) { Fail 'RUNNER_EXTRACT_FAILED' 'Runner.Listener.exe missing after verified archive extraction' }
}

function Register-Runner([string]$Token, [string]$Name) {
    if (Test-ConfiguredRunner) { return }
    if (-not $Token) {
        Write-Evidence 'REGISTRATION_TOKEN_REQUIRED' @{
            runner_root = $RunnerRoot
            token_source = 'NEXUS_GITHUB_RUNNER_REGISTRATION_TOKEN'
        }
        exit 20
    }
    if ($Token.Length -lt 10 -or $Token -match '\s') { Fail 'REGISTRATION_TOKEN_REJECTED' 'registration token format is invalid' }
    $configCmd = Join-Path $RunnerRoot 'config.cmd'
    $arguments = @(
        '--unattended',
        '--url', $ExpectedGitHubUrl,
        '--token', $Token,
        '--name', $Name,
        '--work', '_work',
        '--labels', 'nexus-local'
    )
    try {
        & $configCmd @arguments
        $exitCode = $LASTEXITCODE
    }
    finally {
        $Token = $null
        $RegistrationToken = $null
        Remove-Item Env:NEXUS_GITHUB_RUNNER_REGISTRATION_TOKEN -ErrorAction SilentlyContinue
    }
    if ($exitCode -ne 0) { Fail 'RUNNER_REGISTRATION_FAILED' "config.cmd failed with exit code $exitCode" }
    if (-not (Test-ConfiguredRunner)) { Fail 'RUNNER_REGISTRATION_INVALID' 'runner registration files were not created or target repository did not match' }
}

function Start-AndPersistRunner {
    if (-not (Test-Path -LiteralPath $BootstrapScript -PathType Leaf)) {
        Fail 'GUI_BOOTSTRAP_MISSING' "packaged runner bootstrap missing: $BootstrapScript"
    }
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $BootstrapScript -SourceSha $SourceSha
    if ($LASTEXITCODE -ne 0) { Fail 'GUI_BOOTSTRAP_FAILED' "runner bootstrap failed with exit code $LASTEXITCODE" }
}

try {
    Ensure-StateRoot
    Assert-OwnerSession
    if (-not $env:LOCALAPPDATA) { Fail 'LOCALAPPDATA_REQUIRED' 'LOCALAPPDATA is unavailable' }
    if (-not $RunnerName) { $RunnerName = Get-DefaultRunnerName }

    if (Test-ConfiguredRunner) {
        Start-AndPersistRunner
        Write-Evidence 'RUNNER_ALREADY_CONFIGURED' @{
            runner_root = $RunnerRoot
            runner_name = $RunnerName
        }
        exit 0
    }

    if (-not $RegistrationToken) {
        Write-Evidence 'REGISTRATION_TOKEN_REQUIRED' @{
            runner_root = $RunnerRoot
            runner_name = $RunnerName
            token_source = 'NEXUS_GITHUB_RUNNER_REGISTRATION_TOKEN'
        }
        exit 20
    }

    Assert-ManagedOrEmptyRunnerRoot
    $archive = Get-VerifiedRunnerArchive
    Install-RunnerFiles $archive
    Register-Runner $RegistrationToken $RunnerName
    Start-AndPersistRunner
    Write-Evidence 'RUNNER_PROVISIONED' @{
        runner_root = $RunnerRoot
        runner_name = $RunnerName
        runner_registered = $true
        listener_bootstrap_requested = $true
    }
    exit 0
}
catch {
    try { Write-Evidence 'PROVISION_FAILED' @{ error = $_.Exception.Message } } catch { }
    try { Write-Log "error=$($_.Exception.Message)" } catch { }
    exit 1
}
