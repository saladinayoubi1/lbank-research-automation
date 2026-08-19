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
$ManagedRepoRoot = Join-Path $env:LOCALAPPDATA 'NEXUS\lbank-research-automation'
$EvidenceDir = Join-Path (Get-Location).Path 'build\autostart-install'
$EvidencePath = Join-Path $EvidenceDir 'evidence.json'

function Fail([string]$Message) {
    throw "NEXUS zero-touch remote install: $Message"
}

function Invoke-Git([string]$Root, [string[]]$Args) {
    $git = Get-Command git -ErrorAction Stop
    $output = & $git.Source -C $Root @Args 2>&1
    if ($LASTEXITCODE -ne 0) { Fail "git $($Args -join ' ') failed: $($output -join ' ')" }
    return (($output | Out-String).Trim())
}

function Invoke-GitGlobal([string[]]$Args) {
    $git = Get-Command git -ErrorAction Stop
    $output = & $git.Source @Args 2>&1
    if ($LASTEXITCODE -ne 0) { Fail "git $($Args -join ' ') failed: $($output -join ' ')" }
    return (($output | Out-String).Trim())
}

function Get-ExecutionIdentity {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $blocked = @('NT AUTHORITY\SYSTEM','NT AUTHORITY\NETWORK SERVICE','NT AUTHORITY\LOCAL SERVICE')
    return [pscustomobject]@{
        Name = $identity
        Blocked = ($blocked -contains $identity.ToUpperInvariant())
        UserInteractive = [Environment]::UserInteractive
    }
}

function Normalize([string]$Path) {
    return [IO.Path]::GetFullPath($Path).TrimEnd('\')
}

function Assert-CanonicalRemote([string]$Root) {
    $remote = Invoke-Git $Root @('remote','get-url','origin')
    if ($remote -notmatch $ExpectedRemotePattern) {
        Fail "repository origin is not the canonical NEXUS repository: $remote"
    }
}

function Validate-Workspace([string]$Workspace, [string]$ExpectedSha) {
    if (-not $Workspace -or -not (Test-Path -LiteralPath $Workspace -PathType Container)) {
        Fail 'GITHUB_WORKSPACE is missing or is not a directory'
    }
    $root = Normalize ((Resolve-Path -LiteralPath $Workspace).Path)
    $top = Invoke-Git $root @('rev-parse','--show-toplevel')
    if ((Normalize $top) -ne $root) { Fail 'GITHUB_WORKSPACE is not the repository root' }
    Assert-CanonicalRemote $root
    $head = Invoke-Git $root @('rev-parse','HEAD')
    if ($head.ToLowerInvariant() -ne $ExpectedSha.ToLowerInvariant()) {
        Fail "runner workspace SHA mismatch: expected $ExpectedSha got $head"
    }
    return $root
}

function Validate-StableRepo([string]$Path, [string]$Workspace) {
    if (-not $Path -or -not (Test-Path -LiteralPath $Path -PathType Container)) { return $null }
    try {
        $root = Normalize ((Resolve-Path -LiteralPath $Path).Path)
        if ($Workspace) {
            $workspaceRoot = Normalize ((Resolve-Path -LiteralPath $Workspace).Path)
            if ($root -eq $workspaceRoot -or $root.StartsWith($workspaceRoot + '\',[StringComparison]::OrdinalIgnoreCase)) { return $null }
        }
        if ($root -match '[\\/]_work[\\/]') { return $null }
        $top = Invoke-Git $root @('rev-parse','--show-toplevel')
        if ((Normalize $top) -ne $root) { return $null }
        Assert-CanonicalRemote $root
        return $root
    }
    catch { return $null }
}

function Get-OwnerStableRepoCandidates([string]$Workspace) {
    $candidates = New-Object 'System.Collections.Generic.List[string]'
    $roots = @(
        (Join-Path $env:USERPROFILE 'Desktop\lbank-research-automation'),
        (Join-Path $env:USERPROFILE 'lbank-research-automation'),
        (Join-Path $env:USERPROFILE 'Documents\lbank-research-automation')
    )
    foreach ($candidate in $roots) {
        $valid = Validate-StableRepo $candidate $Workspace
        if ($valid -and -not $candidates.Contains($valid)) { [void]$candidates.Add($valid) }
    }
    return @($candidates)
}

function New-ManagedStableRepo([string]$Workspace, [string]$ExpectedSha) {
    $target = $ManagedRepoRoot
    $parent = Split-Path -Parent $target
    New-Item -ItemType Directory -Force -Path $parent | Out-Null

    if (Test-Path -LiteralPath $target) {
        $valid = Validate-StableRepo $target $Workspace
        if ($valid) { return $valid }
        Fail "managed checkout path already exists but is not a valid canonical repository: $target"
    }

    [void](Invoke-GitGlobal @('clone','--no-hardlinks','--no-checkout',$Workspace,$target))
    [void](Invoke-Git $target @('remote','set-url','origin',$ExpectedGitHubUrl))
    [void](Invoke-Git $target @('checkout','-B','main',$ExpectedSha))
    Assert-CanonicalRemote $target
    $head = Invoke-Git $target @('rev-parse','HEAD')
    if ($head.ToLowerInvariant() -ne $ExpectedSha.ToLowerInvariant()) {
        Fail "managed checkout SHA mismatch: expected $ExpectedSha got $head"
    }
    return (Normalize $target)
}

function Resolve-StableRepo([string]$Workspace, [string]$ExpectedSha) {
    $ownerCandidates = @(Get-OwnerStableRepoCandidates $Workspace)

    if (Test-Path -LiteralPath $ManagedRepoRoot) {
        $managed = Validate-StableRepo $ManagedRepoRoot $Workspace
        if (-not $managed) {
            Fail "managed checkout path already exists but is not a valid canonical repository: $ManagedRepoRoot"
        }
        return [pscustomobject]@{
            Root=$managed
            ManagedCreated=$false
            OwnerCandidateCount=$ownerCandidates.Count
            Selection='existing-managed'
        }
    }

    if ($ownerCandidates.Count -eq 1) {
        return [pscustomobject]@{
            Root=$ownerCandidates[0]
            ManagedCreated=$false
            OwnerCandidateCount=1
            Selection='single-owner-checkout'
        }
    }

    $managed = New-ManagedStableRepo $Workspace $ExpectedSha
    $selection = if ($ownerCandidates.Count -eq 0) { 'managed-no-owner-checkout' } else { 'managed-ambiguous-owner-checkouts' }
    return [pscustomobject]@{
        Root=$managed
        ManagedCreated=$true
        OwnerCandidateCount=$ownerCandidates.Count
        Selection=$selection
    }
}

function Assert-TrackedClean([string]$Root) {
    & git -C $Root diff --quiet
    if ($LASTEXITCODE -ne 0) { Fail 'stable repository has tracked unstaged changes; refusing to overwrite owner work' }
    & git -C $Root diff --cached --quiet
    if ($LASTEXITCODE -ne 0) { Fail 'stable repository has staged changes; refusing to overwrite owner work' }
}

function Sync-ExactMainFromWorkspace([string]$Root, [string]$Workspace, [string]$ExpectedSha) {
    Assert-TrackedClean $Root
    $workspaceHead = Invoke-Git $Workspace @('rev-parse','HEAD')
    if ($workspaceHead.ToLowerInvariant() -ne $ExpectedSha.ToLowerInvariant()) {
        Fail "runner workspace moved before sync: expected $ExpectedSha got $workspaceHead"
    }
    [void](Invoke-Git $Root @('fetch','--no-tags','--quiet',$Workspace,'HEAD'))
    [void](Invoke-Git $Root @('checkout','main'))
    [void](Invoke-Git $Root @('merge','--ff-only','FETCH_HEAD'))
    $head = Invoke-Git $Root @('rev-parse','HEAD')
    if ($head.ToLowerInvariant() -ne $ExpectedSha.ToLowerInvariant()) {
        Fail "stable main SHA mismatch: expected $ExpectedSha got $head"
    }
    Assert-CanonicalRemote $Root
}

function Invoke-Installer([string]$Root, [string]$Script) {
    $path = Join-Path $Root $Script
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { Fail "installer missing: $Script" }
    $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if (-not (Test-Path -LiteralPath $powershell -PathType Leaf)) { $powershell = (Get-Command powershell.exe -ErrorAction Stop).Source }
    & $powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $path -Mode Install -RepoRoot $Root
    if ($LASTEXITCODE -ne 0) { Fail "installer failed: $Script" }
}

function Task-Snapshot([string]$Name) {
    $task = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
    if (-not $task) { return [ordered]@{ exists=$false; state='MISSING' } }
    $info = Get-ScheduledTaskInfo -TaskName $Name -ErrorAction SilentlyContinue
    return [ordered]@{
        exists = $true
        state = [string]$task.State
        last_run_time = if ($info) { [string]$info.LastRunTime } else { $null }
        last_task_result = if ($info) { [int]$info.LastTaskResult } else { $null }
    }
}

if ($env:OS -ne 'Windows_NT') { Fail 'Windows is required' }
New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
$identity = Get-ExecutionIdentity
if ($identity.Blocked) { Fail "self-hosted runner is executing as service identity $($identity.Name); owner-user Task Scheduler install is unsafe" }
if (-not $identity.UserInteractive) { Fail "self-hosted runner is not executing in an interactive owner session ($($identity.Name)); owner-user Task Scheduler install is unsafe" }

$workspace = Validate-Workspace $env:GITHUB_WORKSPACE $SourceSha
$stable = Resolve-StableRepo $workspace $SourceSha
$stableRoot = $stable.Root
Sync-ExactMainFromWorkspace $stableRoot $workspace $SourceSha
Invoke-Installer $stableRoot 'scripts\nexus_windows_autostart.ps1'
Invoke-Installer $stableRoot 'scripts\nexus_github_runner_autostart.ps1'

$core = Task-Snapshot 'NEXUS-ZeroTouch-Autopilot'
$runner = Task-Snapshot 'NEXUS-GitHub-Runner-Autostart'
if (-not $core.exists -or -not $runner.exists) { Fail 'one or more scheduled tasks were not created' }

$evidence = [ordered]@{
    schema_version = 'nexus.zero-touch-remote-install.v2'
    installed = $true
    source_sha = $SourceSha.ToLowerInvariant()
    repository = $ExpectedRepo
    stable_repo_root = $stableRoot
    stable_repo_selection = $stable.Selection
    owner_candidate_count = [int]$stable.OwnerCandidateCount
    managed_checkout_created = [bool]$stable.ManagedCreated
    sync_source = 'exact-github-actions-workspace'
    network_credentials_added = $false
    windows_identity = $identity.Name
    interactive_owner_session = [bool]$identity.UserInteractive
    github_workspace_rejected_as_install_root = $true
    tracked_owner_changes_preserved = $true
    core_task = $core
    runner_task = $runner
    installed_at_utc = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
}
$evidence | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $EvidencePath -Encoding UTF8
Write-Host "NEXUS_ZERO_TOUCH_REMOTE_INSTALL=SUCCESS"
Write-Host "NEXUS_STABLE_REPO=$stableRoot"
Write-Host "NEXUS_STABLE_SELECTION=$($stable.Selection)"
Write-Host "NEXUS_MANAGED_CHECKOUT_CREATED=$($stable.ManagedCreated)"
Write-Host "NEXUS_AUTOSTART_EVIDENCE=$EvidencePath"
