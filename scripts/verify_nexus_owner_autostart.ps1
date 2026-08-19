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
$TaskXmlNamespace = 'http://schemas.microsoft.com/windows/2004/02/mit/task'
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

function Get-XmlNodeText([xml]$Document, [Xml.XmlNamespaceManager]$NamespaceManager, [string]$XPath) {
    $node = $Document.SelectSingleNode($XPath, $NamespaceManager)
    if ($null -eq $node) { return '' }
    return [string]$node.InnerText
}

function Get-TaskXml([string]$Name) {
    $schtasks = Join-Path $env:SystemRoot 'System32\schtasks.exe'
    if (-not (Test-Path -LiteralPath $schtasks -PathType Leaf)) {
        throw 'schtasks.exe is unavailable'
    }

    # Windows PowerShell can surface native stderr as ErrorRecord objects. Keep this
    # query read-only and capture the native exit/output explicitly so a missing task
    # produces deterministic evidence rather than an unrelated terminating error.
    $previousErrorActionPreference = $ErrorActionPreference
    $output = @()
    $exitCode = -1
    try {
        $ErrorActionPreference = 'Continue'
        $output = @(& $schtasks /Query /TN $Name /XML 2>&1)
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    if ($exitCode -ne 0) {
        $detail = Sanitize-Inline (($output | ForEach-Object { [string]$_ }) -join ' ')
        if (-not $detail) { $detail = "exit code $exitCode" }
        throw "scheduled task query failed for $Name exit=$exitCode output=$detail"
    }

    $text = ($output | ForEach-Object { [string]$_ }) -join [Environment]::NewLine
    if (-not $text.Trim()) {
        throw "scheduled task $Name returned empty XML"
    }
    try { return [xml]$text }
    catch { throw "scheduled task $Name returned invalid XML: $(Sanitize-Inline $_.Exception.Message)" }
}

function Get-TaskSnapshot([string]$Name, [string]$ExpectedScript) {
    $taskXml = Get-TaskXml $Name
    $ns = New-Object Xml.XmlNamespaceManager($taskXml.NameTable)
    $ns.AddNamespace('t', $TaskXmlNamespace)

    $principalNode = $taskXml.SelectSingleNode('/t:Task/t:Principals/t:Principal[1]', $ns)
    if ($null -eq $principalNode) { throw "scheduled task $Name has no principal" }

    $user = Get-XmlNodeText $taskXml $ns '/t:Task/t:Principals/t:Principal[1]/t:UserId'
    $xmlRunLevel = Get-XmlNodeText $taskXml $ns '/t:Task/t:Principals/t:Principal[1]/t:RunLevel'
    $xmlLogonType = Get-XmlNodeText $taskXml $ns '/t:Task/t:Principals/t:Principal[1]/t:LogonType'
    if (-not $user -or $ServiceIdentities -contains $user.ToUpperInvariant()) {
        throw "scheduled task $Name is not bound to a real owner-user principal"
    }
    if ($xmlRunLevel -ne 'LeastPrivilege') {
        throw "scheduled task $Name run level is $xmlRunLevel, expected Limited/LeastPrivilege"
    }
    if ($xmlLogonType -notmatch '^InteractiveToken') {
        throw "scheduled task $Name logon type is $xmlLogonType, expected Interactive"
    }

    $logonTriggers = @($taskXml.SelectNodes('/t:Task/t:Triggers/t:LogonTrigger', $ns))
    if ($logonTriggers.Count -lt 1) { throw "scheduled task $Name has no logon trigger" }
    $triggerUsers = @()
    foreach ($trigger in $logonTriggers) {
        $node = $trigger.SelectSingleNode('t:UserId', $ns)
        if ($null -ne $node -and [string]$node.InnerText) { $triggerUsers += [string]$node.InnerText }
    }
    if ($triggerUsers.Count -gt 0 -and -not ($triggerUsers -contains $user)) {
        throw "scheduled task $Name logon trigger principal mismatch"
    }

    $actions = @($taskXml.SelectNodes('/t:Task/t:Actions/t:Exec', $ns))
    if ($actions.Count -ne 1) { throw "scheduled task $Name action count is $($actions.Count), expected 1" }
    $action = $actions[0]
    $commandNode = $action.SelectSingleNode('t:Command', $ns)
    $argumentsNode = $action.SelectSingleNode('t:Arguments', $ns)
    $workingDirectoryNode = $action.SelectSingleNode('t:WorkingDirectory', $ns)
    $execute = if ($null -ne $commandNode) { Sanitize-Inline ([string]$commandNode.InnerText) } else { '' }
    $arguments = if ($null -ne $argumentsNode) { Sanitize-Inline ([string]$argumentsNode.InnerText) } else { '' }
    $workingDirectory = if ($null -ne $workingDirectoryNode) { Normalize-FullPath ([string]$workingDirectoryNode.InnerText) } else { '' }

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

    return [ordered]@{
        name = $Name
        exists = $true
        scheduler_source = 'schtasks_xml'
        configuration_state = 'Configured'
        principal_user = $user
        logon_type = 'Interactive'
        xml_logon_type = $xmlLogonType
        run_level = 'Limited'
        xml_run_level = $xmlRunLevel
        logon_trigger_users = @($triggerUsers)
        execute = $execute
        arguments = $arguments
        working_directory = $workingDirectory
        last_run_time = $null
        last_task_result = $null
    }
}

function Write-Evidence([string]$Status, [hashtable]$Extra = @{}) {
    $full = [IO.Path]::GetFullPath($OutputPath)
    $dir = Split-Path -Parent $full
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $payload = [ordered]@{
        contract_version = 'nexus.owner-autostart-readonly-proof.v2'
        status = $Status
        target_package_source_sha = $SourceSha.ToLowerInvariant()
        generated_at = [DateTime]::UtcNow.ToString('o')
        verifier_identity = $identity
        verifier_service_context = ($ServiceIdentities -contains $identity.ToUpperInvariant())
        task_scheduler_read_only = $true
        task_scheduler_query_transport = 'schtasks_xml'
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
