[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$SourceSha,
    [string]$OutputPath = 'build\owner-autostart-proof\evidence.json'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$ExpectedRepoSuffix = '\NEXUS\lbank-research-automation'
$ServiceIdentities = @(
    'NT AUTHORITY\SYSTEM',
    'NT AUTHORITY\NETWORK SERVICE',
    'NT AUTHORITY\LOCAL SERVICE'
)

function Normalize-FullPath([string]$Value) {
    if (-not $Value) { return '' }
    try { return [IO.Path]::GetFullPath($Value.Trim('"')).TrimEnd('\') }
    catch { return $Value.Trim().TrimEnd('\') }
}

function Test-OwnerRepoWorkingDirectory([string]$Value) {
    $normalized = Normalize-FullPath $Value
    return $normalized.EndsWith($ExpectedRepoSuffix, [StringComparison]::OrdinalIgnoreCase)
}

function Sanitize-Inline([string]$Value) {
    if ($null -eq $Value) { return '' }
    return ($Value -replace '[\r\n\t]+',' ' -replace '[\u0000-\u001f\u007f]','').Trim()
}

function Get-TaskSnapshot([string]$Name, [string]$ExpectedScript) {
    $matches = @(Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue)
    if ($matches.Count -ne 1) {
        throw "scheduled task $Name count is $($matches.Count), expected exactly 1"
    }
    $task = $matches[0]
    $principal = $task.Principal
    if (-not $principal) { throw "scheduled task $Name has no principal" }
    $user = [string]$principal.UserId
    $runLevel = [string]$principal.RunLevel
    $logonType = [string]$principal.LogonType
    if (-not $user -or $ServiceIdentities -contains $user.ToUpperInvariant()) {
        throw "scheduled task $Name is not bound to a real owner-user principal"
    }
    if ($runLevel -ne 'Limited') {
        throw "scheduled task $Name run level is $runLevel, expected Limited"
    }
    if ($logonType -notmatch 'Interactive') {
        throw "scheduled task $Name logon type is $logonType, expected Interactive"
    }

    $triggers = @($task.Triggers)
    if ($triggers.Count -lt 1) { throw "scheduled task $Name has no trigger" }
    $logonTriggers = @($triggers | Where-Object { $_.CimClass.CimClassName -match 'LogonTrigger' })
    if ($logonTriggers.Count -lt 1) { throw "scheduled task $Name has no logon trigger" }
    $triggerUsers = @($logonTriggers | ForEach-Object { [string]$_.UserId } | Where-Object { $_ })
    if ($triggerUsers.Count -gt 0 -and -not ($triggerUsers -contains $user)) {
        throw "scheduled task $Name logon trigger principal mismatch"
    }

    $actions = @($task.Actions)
    if ($actions.Count -ne 1) { throw "scheduled task $Name action count is $($actions.Count), expected 1" }
    $action = $actions[0]
    $execute = Sanitize-Inline ([string]$action.Execute)
    $arguments = Sanitize-Inline ([string]$action.Arguments)
    $workingDirectory = Normalize-FullPath ([string]$action.WorkingDirectory)
    if ([IO.Path]::GetFileName($execute) -notmatch '^(?i)powershell\.exe$') {
        throw "scheduled task $Name executable is not powershell.exe"
    }
    if ($arguments -notmatch [regex]::Escape($ExpectedScript)) {
        throw "scheduled task $Name does not invoke expected script $ExpectedScript"
    }
    if ($arguments -notmatch '(?i)-Mode\s+RunDaemon') {
        throw "scheduled task $Name does not invoke RunDaemon mode"
    }
    if ($arguments -notmatch '(?i)-RepoRoot') {
        throw "scheduled task $Name is missing RepoRoot binding"
    }
    if (-not (Test-OwnerRepoWorkingDirectory $workingDirectory)) {
        throw "scheduled task $Name working directory is outside the bounded owner NEXUS checkout"
    }

    $state = [string]$task.State
    if ($state -notin @('Ready','Running','Queued')) {
        throw "scheduled task $Name state is $state"
    }
    $info = Get-ScheduledTaskInfo -TaskName $Name -ErrorAction SilentlyContinue

    return [ordered]@{
        name = $Name
        exists = $true
        state = $state
        principal_user = $user
        logon_type = $logonType
        run_level = $runLevel
        logon_trigger_users = @($triggerUsers)
        execute = $execute
        arguments = $arguments
        working_directory = $workingDirectory
        last_run_time = if ($info) { [string]$info.LastRunTime } else { $null }
        last_task_result = if ($info) { [int64]$info.LastTaskResult } else { $null }
    }
}

function Write-Evidence([string]$Status, [hashtable]$Extra = @{}) {
    $full = [IO.Path]::GetFullPath($OutputPath)
    $dir = Split-Path -Parent $full
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $payload = [ordered]@{
        contract_version = 'nexus.owner-autostart-readonly-proof.v1'
        status = $Status
        target_package_source_sha = $SourceSha.ToLowerInvariant()
        generated_at = [DateTime]::UtcNow.ToString('o')
        verifier_identity = $identity
        verifier_service_context = ($ServiceIdentities -contains $identity.ToUpperInvariant())
        task_scheduler_read_only = $true
        owner_profile_file_content_read = $false
        task_registration_modified = $false
        runner_registration_modified = $false
        execution_policy_modified = $false
        elevation_requested = $false
        live_trading_authority = $false
        paper_only = $true
    }
    foreach ($key in $Extra.Keys) { $payload[$key] = $Extra[$key] }
    $tmp = $full + '.tmp'
    $payload | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $tmp -Encoding UTF8
    Move-Item -LiteralPath $tmp -Destination $full -Force
}

try {
    if ($env:OS -ne 'Windows_NT') { throw 'owner autostart proof is Windows-only' }
    $core = Get-TaskSnapshot 'NEXUS-ZeroTouch-Autopilot' 'nexus_windows_autostart.ps1'
    $runner = Get-TaskSnapshot 'NEXUS-GitHub-Runner-Autostart' 'nexus_github_runner_autostart.ps1'
    if ($core.principal_user -ne $runner.principal_user) {
        throw 'owner autostart tasks use different principals'
    }
    if ($core.working_directory -ne $runner.working_directory) {
        throw 'owner autostart tasks use different managed checkout roots'
    }
    Write-Evidence 'SUCCESS' @{
        owner_user = $core.principal_user
        managed_checkout_root = $core.working_directory
        core_task = $core
        runner_task = $runner
        owner_task_installation_verified = $true
        reboot_resume_verified = $false
        offline_phase7_verified = $false
    }
    Write-Host 'NEXUS_OWNER_AUTOSTART_READONLY_PROOF=SUCCESS'
    exit 0
}
catch {
    try {
        Write-Evidence 'FAILURE' @{
            error = Sanitize-Inline $_.Exception.Message
            owner_task_installation_verified = $false
            reboot_resume_verified = $false
            offline_phase7_verified = $false
        }
    } catch { }
    Write-Error $_
    exit 20
}
