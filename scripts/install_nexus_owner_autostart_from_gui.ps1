[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$SourceSha
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$ExpectedRepo = 'saladinayoubi1/lbank-research-automation'
$ExpectedGitHubUrl = 'https://github.com/saladinayoubi1/lbank-research-automation.git'
$ExpectedRemotePattern = '(?i)github\.com[:/]saladinayoubi1/lbank-research-automation(?:\.git)?$'
$PackageRef = 'refs/heads/nexus-package-source'
$ResourcesRoot = Split-Path -Parent $PSScriptRoot
$BundlePath = Join-Path $ResourcesRoot 'nexus-source.bundle'
$ManagedRepoRoot = Join-Path $env:LOCALAPPDATA 'NEXUS\lbank-research-automation'
$StateRoot = Join-Path $env:LOCALAPPDATA 'NEXUS\OwnerAutostartBootstrap'
$EvidencePath = Join-Path $StateRoot 'evidence.json'
$LogPath = Join-Path $StateRoot 'bootstrap.log'

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
        contract_version = 'nexus.owner-autostart-bootstrap.v1'
        status = $Status
        source_sha = $SourceSha.ToLowerInvariant()
        generated_at = [DateTime]::UtcNow.ToString('o')
        repository = $ExpectedRepo
        managed_repo_root = $ManagedRepoRoot
        interactive_user = "$env:USERDOMAIN\$env:USERNAME"
        bundle_verified = $false
        network_credentials_added = $false
        runner_registration_modified = $false
        machine_execution_policy_modified = $false
        elevation_requested = $false
        live_trading_authority = $false
        paper_only = $true
    }
    foreach ($key in $Extra.Keys) { $payload[$key] = $Extra[$key] }
    $tmp = $EvidencePath + '.tmp'
    $payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $tmp -Encoding UTF8
    Move-Item -LiteralPath $tmp -Destination $EvidencePath -Force
    Write-Log "status=$Status source_sha=$($SourceSha.ToLowerInvariant())"
}

function Get-Git {
    $git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $git) { throw 'Git is required for exact-source local bootstrap' }
    return $git.Source
}

function Invoke-Git([string]$Root, [string[]]$Args) {
    $git = Get-Git
    $output = & $git -C $Root @Args 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Args -join ' ') failed: $(($output | Out-String).Trim())"
    }
    return (($output | Out-String).Trim())
}

function Invoke-GitGlobal([string[]]$Args) {
    $git = Get-Git
    $output = & $git @Args 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Args -join ' ') failed: $(($output | Out-String).Trim())"
    }
    return (($output | Out-String).Trim())
}

function Assert-InteractiveOwner {
    if ($env:OS -ne 'Windows_NT') { throw 'owner autostart bootstrap is Windows-only' }
    if (-not [Environment]::UserInteractive) { throw 'owner autostart bootstrap requires an interactive user session' }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    if ($identity -in @('NT AUTHORITY\SYSTEM','NT AUTHORITY\NETWORK SERVICE','NT AUTHORITY\LOCAL SERVICE')) {
        throw "service identity is not allowed to install owner-user autostart: $identity"
    }
    return $identity
}

function Assert-BundleSource {
    if (-not (Test-Path -LiteralPath $BundlePath -PathType Leaf)) { throw 'packaged exact-source Git bundle is missing' }
    $git = Get-Git
    & $git bundle verify $BundlePath *> $null
    if ($LASTEXITCODE -ne 0) { throw 'packaged exact-source Git bundle verification failed' }
    $heads = & $git bundle list-heads $BundlePath $PackageRef 2>&1
    if ($LASTEXITCODE -ne 0) { throw 'packaged exact-source Git bundle head lookup failed' }
    $line = (($heads | Out-String).Trim())
    if ($line -notmatch '^([0-9a-fA-F]{40})\s+refs/heads/nexus-package-source$') {
        throw 'packaged exact-source Git bundle does not expose the expected bounded ref'
    }
    $bundleSha = $Matches[1].ToLowerInvariant()
    if ($bundleSha -ne $SourceSha.ToLowerInvariant()) {
        throw "packaged source mismatch: expected $($SourceSha.ToLowerInvariant()) got $bundleSha"
    }
    return $bundleSha
}

function Assert-CanonicalRemote([string]$Root) {
    $remote = Invoke-Git $Root @('remote','get-url','origin')
    if ($remote -notmatch $ExpectedRemotePattern) {
        throw "managed checkout origin is not canonical: $remote"
    }
}

function Assert-TrackedClean([string]$Root) {
    $status = Invoke-Git $Root @('status','--porcelain=v1','--untracked-files=no')
    if ($status) { throw 'managed checkout has tracked owner changes; refusing automatic update' }
}

function Initialize-ManagedRepo {
    $parent = Split-Path -Parent $ManagedRepoRoot
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    if (Test-Path -LiteralPath $ManagedRepoRoot) {
        throw "managed checkout path already exists but is not a valid canonical repository: $ManagedRepoRoot"
    }

    [void](Invoke-GitGlobal @('clone','--no-checkout','--branch','nexus-package-source',$BundlePath,$ManagedRepoRoot))
    [void](Invoke-Git $ManagedRepoRoot @('remote','set-url','origin',$ExpectedGitHubUrl))
    [void](Invoke-Git $ManagedRepoRoot @('checkout','-B','main',$SourceSha.ToLowerInvariant()))
    Assert-CanonicalRemote $ManagedRepoRoot
}

function Update-ManagedRepo {
    $top = Invoke-Git $ManagedRepoRoot @('rev-parse','--show-toplevel')
    if ((Resolve-Path -LiteralPath $top).Path -ne (Resolve-Path -LiteralPath $ManagedRepoRoot).Path) {
        throw 'managed checkout root validation failed'
    }
    Assert-CanonicalRemote $ManagedRepoRoot
    Assert-TrackedClean $ManagedRepoRoot

    [void](Invoke-Git $ManagedRepoRoot @('fetch','--no-tags',$BundlePath,$PackageRef))
    $fetched = Invoke-Git $ManagedRepoRoot @('rev-parse','FETCH_HEAD')
    if ($fetched.ToLowerInvariant() -ne $SourceSha.ToLowerInvariant()) {
        throw "bundle fetch SHA mismatch: expected $($SourceSha.ToLowerInvariant()) got $fetched"
    }
    $branch = Invoke-Git $ManagedRepoRoot @('branch','--show-current')
    if ($branch -ne 'main') { [void](Invoke-Git $ManagedRepoRoot @('checkout','main')) }
    $head = Invoke-Git $ManagedRepoRoot @('rev-parse','HEAD')
    if ($head.ToLowerInvariant() -ne $SourceSha.ToLowerInvariant()) {
        [void](Invoke-Git $ManagedRepoRoot @('merge','--ff-only','FETCH_HEAD'))
    }
}

function Prepare-ManagedRepo {
    if (-not (Test-Path -LiteralPath $ManagedRepoRoot -PathType Container)) {
        Initialize-ManagedRepo
        return $true
    }
    if (-not (Test-Path -LiteralPath (Join-Path $ManagedRepoRoot '.git') -PathType Container)) {
        throw "managed checkout path exists without a Git repository: $ManagedRepoRoot"
    }
    Update-ManagedRepo
    return $false
}

function Get-PowerShellExe {
    $fixed = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if (Test-Path -LiteralPath $fixed -PathType Leaf) { return $fixed }
    return (Get-Command powershell.exe -ErrorAction Stop).Source
}

function Invoke-Installer([string]$RelativeScript) {
    $path = Join-Path $ManagedRepoRoot $RelativeScript
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "required installer missing: $RelativeScript" }
    $ps = Get-PowerShellExe
    & $ps -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $path -Mode Install -RepoRoot $ManagedRepoRoot
    if ($LASTEXITCODE -ne 0) { throw "installer failed: $RelativeScript" }
}

function Task-Snapshot([string]$Name) {
    $task = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
    if (-not $task) { return [ordered]@{ exists=$false; state='MISSING' } }
    $info = Get-ScheduledTaskInfo -TaskName $Name -ErrorAction SilentlyContinue
    return [ordered]@{
        exists = $true
        state = [string]$task.State
        user = [string]$task.Principal.UserId
        run_level = [string]$task.Principal.RunLevel
        last_run_time = if ($info) { [string]$info.LastRunTime } else { $null }
        last_task_result = if ($info) { [int]$info.LastTaskResult } else { $null }
    }
}

try {
    Ensure-StateRoot
    $identity = Assert-InteractiveOwner
    $bundleSha = Assert-BundleSource
    $managedCreated = Prepare-ManagedRepo
    $head = Invoke-Git $ManagedRepoRoot @('rev-parse','HEAD')
    if ($head.ToLowerInvariant() -ne $SourceSha.ToLowerInvariant()) {
        throw "managed checkout exact-source verification failed: $head"
    }

    Invoke-Installer 'scripts\nexus_windows_autostart.ps1'
    Invoke-Installer 'scripts\nexus_github_runner_autostart.ps1'

    $core = Task-Snapshot 'NEXUS-ZeroTouch-Autopilot'
    $runner = Task-Snapshot 'NEXUS-GitHub-Runner-Autostart'
    if (-not $core.exists -or -not $runner.exists) { throw 'required owner-user scheduled tasks were not created' }
    if ($core.run_level -ne 'Limited' -or $runner.run_level -ne 'Limited') { throw 'owner-user scheduled tasks are not limited-runlevel' }

    Write-Evidence 'SUCCESS' @{
        bundle_verified = $true
        bundle_sha = $bundleSha
        windows_identity = $identity
        managed_checkout_created = [bool]$managedCreated
        managed_head = $head.ToLowerInvariant()
        core_task = $core
        runner_task = $runner
        installed = $true
    }
    Write-Host 'NEXUS_OWNER_AUTOSTART_BOOTSTRAP=SUCCESS'
    exit 0
}
catch {
    try {
        Write-Evidence 'BLOCKED' @{
            error = $_.Exception.Message
            installed = $false
        }
    } catch { }
    try { Write-Log "blocked error=$($_.Exception.Message)" } catch { }
    exit 20
}
