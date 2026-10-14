[CmdletBinding()]
param([switch]$SkipInspection)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$files=@('Prepare-RescueKey.ps1','Install-NexusRescue.ps1','Watch-RescueTunnel.ps1','Rescue-WindowsPlatform.ps1','Validate-RescueBundle.ps1')
foreach ($name in $files) {
    $tokens=$null; $errors=$null
    $null=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot $name),[ref]$tokens,[ref]$errors)
    if ($errors.Count -gt 0) { throw ('PowerShell syntax error in '+$name+': '+($errors|Out-String)) }
}
. (Join-Path $PSScriptRoot 'Rescue-WindowsPlatform.ps1')
$tcpProbe=New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback,0)
$tcpProbe.Start()
$probePort=$tcpProbe.LocalEndpoint.Port
try {
    $observed=@(Get-NexusTcpListeners $probePort)
    if ($observed.Count -ne 1 -or $observed[0].Address.ToString() -ne '127.0.0.1') { throw 'Native listener guard did not detect the owned loopback socket' }
} finally { $tcpProbe.Stop() }
if (@(Get-NexusTcpListeners $probePort).Count -ne 0) { throw 'Native listener guard reported a closed socket as listening' }
$scheduler=Connect-NexusTaskService
$definition=New-NexusRepairTaskDefinition $scheduler 'C:\ProgramData\NEXUS-Rescue'
# COM returns a localized account name for a SID; validate the resolved identity.
$taskPrincipalSid=$definition.Principal.UserId
if ($taskPrincipalSid -notmatch '^S-1-') { $taskPrincipalSid=(New-Object Security.Principal.NTAccount($taskPrincipalSid)).Translate([Security.Principal.SecurityIdentifier]).Value }
if ($definition.Settings.MultipleInstances -ne 2 -or $definition.Principal.LogonType -ne 5 -or $taskPrincipalSid -ne 'S-1-5-18' -or $definition.Principal.RunLevel -ne 1 -or $definition.Triggers.Count -ne 1 -or $definition.Triggers.Item(1).Type -ne 8 -or $definition.Actions.Count -ne 1) { throw 'Native task definition violates singleton/service-account/boot contract' }
$policy=Connect-NexusFirewallPolicy
$firewallRulesCount=$policy.Rules.Count
$manifest=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'bundle-manifest.json') -Raw | ConvertFrom-Json
foreach ($f in $manifest.files.PSObject.Properties) {
    if ((Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $f.Name) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $f.Value) { throw ('Readback hash mismatch: '+$f.Name) }
}
$watch=[IO.File]::ReadAllText((Join-Path $PSScriptRoot 'Watch-RescueTunnel.ps1'))
$match=[regex]::Match($watch,"(?s)Add-Type -TypeDefinition @'\r?\n(.*?)\r?\n'@")
if (-not $match.Success) { throw 'Job containment code missing' }
Add-Type -TypeDefinition $match.Groups[1].Value
$job=New-Object NexusRescueJob
$pi=New-Object Diagnostics.ProcessStartInfo
$pi.FileName='C:\Windows\System32\cmd.exe'
$pi.Arguments='/c ping -n 20 127.0.0.1 > nul'
$pi.UseShellExecute=$false; $pi.CreateNoWindow=$true
$child=[Diagnostics.Process]::Start($pi)
try {
    $job.Assign($child.Handle)
    $job.Dispose()
    if (-not $child.WaitForExit(5000)) { throw 'Owned job child survived parent cleanup' }
} finally {
    $job.Dispose()
    if (-not $child.HasExited) { $child.Kill() }
    $child.Dispose()
}
if (-not $SkipInspection) { & (Join-Path $PSScriptRoot 'Install-NexusRescue.ps1') -InspectOnly }
[ordered]@{powershell_syntax_pass=$true;bundle_hashes_pass=$true;owned_child_cleanup_pass=$true;native_tcp_guard_pass=$true;task_com_definition_pass=$true;firewall_com_read_pass=$true;cim_required=$false;ssh_service_started=$false;task_created=$false;hostname=$env:COMPUTERNAME;writer_authority=$false;live_enabled=$false} | ConvertTo-Json
