[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$SourceSha
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$ExpectedRepo = 'saladinayoubi1/lbank-research-automation'
$ExpectedRemotePattern = 'saladinayoubi1[/\\]lbank-research-automation(?:\.git)?$'
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

function Is-ServiceIdentity {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $blocked = @('NT AUTHORITY\SYSTEM','NT AUTHORITY\NETWORK SERVICE','NT AUTHORITY\LOCAL SERVICE')
    return [pscustomobject]@{
        Name = $identity
        Blocked = ($blocked -contains $identity.ToUpperInvariant())
    }
}

function Normalize([string]$Path) {
    return [IO.Path]::GetFullPath($Path).TrimEnd('\')
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
        $remote = Invoke-Git $root @('remote','get-url','origin')
        if ($remote -notmatch $ExpectedRemotePattern) { return $null }
        return $root
    }
    catch { return $null }
}

function Find-StableRepo {
    $workspace = $env:GITHUB_WORKSPACE
    $candidates = New-Object 'System.Collections.Generic.List[string]'
    $roots = @(
        (Join-Path $env:USERPROFILE 'Desktop\lbank-research-automation'),
        (Join-Path $env:USERPROFILE 'lbank-research-automation'),
        (Join-Path $env:USERPROFILE 'Documents\lbank-research-automation'),
        (Join-Path $env:LOCALAPPDATA 'NEXUS\lbank-research-automation')
    )
    foreach ($candidate in $roots) {
        $valid = Validate-StableRepo $candidate $workspace
        if ($valid -and -not $candidates.Contains($valid)) { [void]$candidates.Add($valid) }
    }
    if ($candidates.Count -eq 0) { Fail 'no stable repository checkout was found outside the GitHub Actions workspace' }
    if ($candidates.Count -gt 1) { Fail "multiple stable repository checkouts found: $($candidates -join ', ')" }
    return $candidates[0]
}

function Assert-TrackedClean([string]$Root) {
    $unstaged = & git -C $Root diff --quiet
    if ($LASTEXITCODE -ne 0) { Fail 'stable repository has tracked unstaged changes; refusing to overwrite owner work' }
    $staged = & git -C $Root diff --cached --quiet
    if ($LASTEXITCODE -ne 0) { Fail 'stable repository has staged changes; refusing to overwrite owner work' }
}

function Sync-ExactMain([string]$Root, [string]$ExpectedSha) {
    Assert-TrackedClean $Root
    [void](Invoke-Git $Root @('fetch','origin','main','--quiet'))
    [void](Invoke-Git $Root @('checkout','main'))
    [void](Invoke-Git $Root @('merge','--ff-only','origin/main'))
    $head = Invoke-Git $Root @('rev-parse','HEAD')
    if ($head.ToLowerInvariant() -ne $ExpectedSha.ToLowerInvariant()) {
        Fail "stable main SHA mismatch: expected $ExpectedSha got $head"
    }
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
$identity = Is-ServiceIdentity
if ($identity.Blocked) { Fail "self-hosted runner is executing as service identity $($identity.Name); owner-user Task Scheduler install is unsafe" }

$stableRoot = Find-StableRepo
Sync-ExactMain $stableRoot $SourceSha
Invoke-Installer $stableRoot 'scripts\nexus_windows_autostart.ps1'
Invoke-Installer $stableRoot 'scripts\nexus_github_runner_autostart.ps1'

$core = Task-Snapshot 'NEXUS-ZeroTouch-Autopilot'
$runner = Task-Snapshot 'NEXUS-GitHub-Runner-Autostart'
if (-not $core.exists -or -not $runner.exists) { Fail 'one or more scheduled tasks were not created' }

$evidence = [ordered]@{
    schema_version = 'nexus.zero-touch-remote-install.v1'
    installed = $true
    source_sha = $SourceSha.ToLowerInvariant()
    repository = $ExpectedRepo
    stable_repo_root = $stableRoot
    windows_identity = $identity.Name
    github_workspace_rejected_as_install_root = $true
    tracked_owner_changes_preserved = $true
    core_task = $core
    runner_task = $runner
    installed_at_utc = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
}
$evidence | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $EvidencePath -Encoding UTF8
Write-Host "NEXUS_ZERO_TOUCH_REMOTE_INSTALL=SUCCESS"
Write-Host "NEXUS_STABLE_REPO=$stableRoot"
Write-Host "NEXUS_AUTOSTART_EVIDENCE=$EvidencePath"
