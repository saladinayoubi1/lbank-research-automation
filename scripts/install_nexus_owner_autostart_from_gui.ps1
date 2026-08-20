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
$SeedRepoPath = Join-Path $ResourcesRoot 'nexus-source-seed.git'
$ManagedRepoRoot = Join-Path $env:LOCALAPPDATA 'NEXUS\lbank-research-automation'
$StateRoot = Join-Path $env:LOCALAPPDATA 'NEXUS\OwnerAutostartBootstrap'
$EvidencePath = Join-Path $StateRoot 'evidence.json'
$LogPath = Join-Path $StateRoot 'bootstrap.log'
$CurrentStage = 'startup'

function Ensure-StateRoot {
    New-Item -ItemType Directory -Force -Path $StateRoot | Out-Null
}

function Write-Log([string]$Message) {
    Ensure-StateRoot
    $stamp = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
    Add-Content -LiteralPath $LogPath -Encoding UTF8 -Value "[$stamp] $Message"
}

function Sanitize-Inline([string]$Value) {
    if ($null -eq $Value) { return '' }
    return ($Value -replace '[\r\n\t]+',' ' -replace '[\u0000-\u001f\u007f]','').Trim()
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
        stage = $CurrentStage
        seed_verified = $false
        managed_checkout_updated_from_package_seed = $false
        native_commands_judged_by_exit_code = $true
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
    Write-Log "status=$Status stage=$CurrentStage source_sha=$($SourceSha.ToLowerInvariant())"
}

function Invoke-NativeCapture([string]$Executable, [string]$WorkingDirectory, [string[]]$Arguments, [string]$Label) {
    # Windows PowerShell 5.1 represents native stderr as ErrorRecord objects when
    # redirected with 2>&1. Git writes normal progress/advice to stderr even on
    # success, so temporarily use Continue and decide success only by exit code.
    $previous = $ErrorActionPreference
    $rows = @()
    $exitCode = -1
    try {
        $ErrorActionPreference = 'Continue'
        if ($WorkingDirectory) {
            Push-Location -LiteralPath $WorkingDirectory
            try {
                $rows = @(& $Executable @Arguments 2>&1)
                $exitCode = $LASTEXITCODE
            }
            finally { Pop-Location }
        }
        else {
            $rows = @(& $Executable @Arguments 2>&1)
            $exitCode = $LASTEXITCODE
        }
    }
    finally {
        $ErrorActionPreference = $previous
    }
    $text = (($rows | ForEach-Object { [string]$_ }) -join [Environment]::NewLine).Trim()
    if ($exitCode -ne 0) {
        throw "$Label failed exit=$exitCode output=$(Sanitize-Inline $text)"
    }
    return [pscustomobject]@{ ExitCode = $exitCode; Text = $text }
}

function Get-Git {
    $git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $git) { throw 'Git is required for exact-source local bootstrap' }
    return $git.Source
}

function Invoke-Git([string]$Root, [string[]]$GitArguments) {
    $git = Get-Git
    $result = Invoke-NativeCapture -Executable $git -WorkingDirectory $Root -Arguments $GitArguments -Label ("git " + ($GitArguments -join ' '))
    return $result.Text
}

function Invoke-GitGlobal([string[]]$GitArguments) {
    $git = Get-Git
    $result = Invoke-NativeCapture -Executable $git -WorkingDirectory '' -Arguments $GitArguments -Label ("git " + ($GitArguments -join ' '))
    return $result.Text
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

function Assert-SeedSource {
    if (-not (Test-Path -LiteralPath $SeedRepoPath -PathType Container)) { throw 'packaged exact-source Git seed is missing' }
    if (-not (Test-Path -LiteralPath (Join-Path $SeedRepoPath 'shallow') -PathType Leaf)) { throw 'packaged exact-source Git seed is not shallow bounded' }
    $seedSha = Invoke-GitGlobal -GitArguments @('--git-dir',$SeedRepoPath,'rev-parse',$PackageRef)
    if ($seedSha.ToLowerInvariant() -ne $SourceSha.ToLowerInvariant()) {
        throw "packaged source mismatch: expected $($SourceSha.ToLowerInvariant()) got $seedSha"
    }
    [void](Invoke-GitGlobal -GitArguments @('--git-dir',$SeedRepoPath,'fsck','--no-dangling'))
    return $seedSha.ToLowerInvariant()
}

function Assert-CanonicalRemote([string]$Root) {
    $remote = Invoke-Git -Root $Root -GitArguments @('remote','get-url','origin')
    if ($remote -notmatch $ExpectedRemotePattern) {
        throw "managed checkout origin is not canonical: $remote"
    }
}

function Assert-TrackedClean([string]$Root) {
    $status = Invoke-Git -Root $Root -GitArguments @('status','--porcelain=v1','--untracked-files=no')
    if ($status) { throw 'managed checkout has tracked owner changes; refusing automatic replacement' }
}

function Initialize-ManagedRepo {
    $parent = Split-Path -Parent $ManagedRepoRoot
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    if (Test-Path -LiteralPath $ManagedRepoRoot) {
        throw "managed checkout path already exists but is not a valid canonical repository: $ManagedRepoRoot"
    }

    # --no-local prevents hardlinks back into a Portable package that may disappear
    # after process exit; the managed checkout must own its object database.
    [void](Invoke-GitGlobal -GitArguments @('clone','--no-local','--no-checkout','--branch','nexus-package-source',$SeedRepoPath,$ManagedRepoRoot))
    [void](Invoke-Git -Root $ManagedRepoRoot -GitArguments @('remote','set-url','origin',$ExpectedGitHubUrl))
    [void](Invoke-Git -Root $ManagedRepoRoot -GitArguments @('checkout','-B','main',$SourceSha.ToLowerInvariant()))
    Assert-CanonicalRemote $ManagedRepoRoot
}

function Validate-ExistingManagedRepo {
    if (-not (Test-Path -LiteralPath (Join-Path $ManagedRepoRoot '.git') -PathType Container)) {
        throw "managed checkout path exists without a Git repository: $ManagedRepoRoot"
    }
    $top = Invoke-Git -Root $ManagedRepoRoot -GitArguments @('rev-parse','--show-toplevel')
    if ((Resolve-Path -LiteralPath $top).Path -ne (Resolve-Path -LiteralPath $ManagedRepoRoot).Path) {
        throw 'managed checkout root validation failed'
    }
    Assert-CanonicalRemote $ManagedRepoRoot
    Assert-TrackedClean $ManagedRepoRoot
    return (Invoke-Git -Root $ManagedRepoRoot -GitArguments @('rev-parse','HEAD')).ToLowerInvariant()
}

function Reconcile-ExistingManagedRepo([string]$CurrentHead) {
    $target = $SourceSha.ToLowerInvariant()
    if ($CurrentHead.ToLowerInvariant() -eq $target) { return $false }

    # The package seed is the only source used for reconciliation. No origin/network
    # fetch is performed and no credential is added. --update-shallow allows the exact
    # packaged shallow commit to be imported into an older managed checkout.
    Write-Log "reconcile managed checkout prior_sha=$CurrentHead target_sha=$target source=packaged_seed"
    [void](Invoke-Git -Root $ManagedRepoRoot -GitArguments @('fetch','--no-tags','--update-shallow',$SeedRepoPath,$PackageRef))
    $fetched = Invoke-Git -Root $ManagedRepoRoot -GitArguments @('rev-parse','FETCH_HEAD')
    if ($fetched.ToLowerInvariant() -ne $target) {
        throw "packaged seed fetch mismatch: expected $target got $fetched"
    }

    # checkout -B updates only this clean managed checkout. Git itself refuses an
    # untracked-file collision; we do not delete, clean, or hard-reset owner data.
    [void](Invoke-Git -Root $ManagedRepoRoot -GitArguments @('checkout','-B','main','FETCH_HEAD'))
    Assert-CanonicalRemote $ManagedRepoRoot
    Assert-TrackedClean $ManagedRepoRoot
    $head = Invoke-Git -Root $ManagedRepoRoot -GitArguments @('rev-parse','HEAD')
    if ($head.ToLowerInvariant() -ne $target) {
        throw "managed checkout reconciliation failed: expected $target got $head"
    }
    return $true
}

function Prepare-ManagedRepo {
    if (-not (Test-Path -LiteralPath $ManagedRepoRoot -PathType Container)) {
        Initialize-ManagedRepo
        return [ordered]@{
            created = $true
            updated_from_package_seed = $false
            previous_head = $null
        }
    }

    $previousHead = Validate-ExistingManagedRepo
    $updated = Reconcile-ExistingManagedRepo $previousHead
    return [ordered]@{
        created = $false
        updated_from_package_seed = [bool]$updated
        previous_head = $previousHead
    }
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
    $installerArguments = @('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',$path,'-Mode','Install','-RepoRoot',$ManagedRepoRoot)
    [void](Invoke-NativeCapture -Executable $ps -WorkingDirectory $ManagedRepoRoot -Arguments $installerArguments -Label ("installer $RelativeScript"))
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
    $CurrentStage = 'identity'
    $identity = Assert-InteractiveOwner

    $CurrentStage = 'seed'
    $seedSha = Assert-SeedSource

    $CurrentStage = 'managed_checkout'
    $managed = Prepare-ManagedRepo
    $head = Invoke-Git -Root $ManagedRepoRoot -GitArguments @('rev-parse','HEAD')
    if ($head.ToLowerInvariant() -ne $SourceSha.ToLowerInvariant()) {
        throw "managed checkout exact-source verification failed: $head"
    }

    $CurrentStage = 'core_autostart_install'
    Invoke-Installer 'scripts\nexus_windows_autostart.ps1'

    $CurrentStage = 'runner_autostart_install'
    Invoke-Installer 'scripts\nexus_github_runner_autostart.ps1'

    $CurrentStage = 'task_verify'
    $core = Task-Snapshot 'NEXUS-ZeroTouch-Autopilot'
    $runner = Task-Snapshot 'NEXUS-GitHub-Runner-Autostart'
    if (-not $core.exists -or -not $runner.exists) { throw 'required owner-user scheduled tasks were not created' }
    if ($core.run_level -ne 'Limited' -or $runner.run_level -ne 'Limited') { throw 'owner-user scheduled tasks are not limited-runlevel' }

    $CurrentStage = 'complete'
    Write-Evidence 'SUCCESS' @{
        seed_verified = $true
        seed_sha = $seedSha
        windows_identity = $identity
        managed_checkout_created = [bool]$managed.created
        managed_checkout_updated_from_package_seed = [bool]$managed.updated_from_package_seed
        managed_previous_head = $managed.previous_head
        managed_head = $head.ToLowerInvariant()
        core_task = $core
        runner_task = $runner
        installed = $true
    }
    Write-Host 'NEXUS_OWNER_AUTOSTART_BOOTSTRAP=SUCCESS'
    exit 0
}
catch {
    $message = Sanitize-Inline $_.Exception.Message
    try {
        Write-Evidence 'BLOCKED' @{
            error = $message
            installed = $false
        }
    } catch { }
    try { Write-Log "blocked stage=$CurrentStage error=$message" } catch { }
    exit 20
}
