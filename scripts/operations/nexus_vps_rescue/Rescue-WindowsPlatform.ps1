# Local IP Helper, Service Control Manager and COM APIs; no CIM/WMI dependency.
function Get-NexusTcpListeners([int]$Port) {
    foreach ($endpoint in [Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()) {
        if ($endpoint.Port -eq $Port) { $endpoint }
    }
}
function Test-NexusNotFoundException([Exception]$ErrorValue,[uint32]$ExpectedCode) {
    $e=$ErrorValue
    while ($null -ne $e) {
        if (([int64]$e.HResult -band 4294967295) -eq $ExpectedCode) { return $true }
        if ($e -is [ComponentModel.Win32Exception] -and $e.NativeErrorCode -eq 1060 -and $ExpectedCode -eq 2147943460) { return $true }
        $e=$e.InnerException
    }
    return $false
}
function Get-NexusSshdState {
    $null=Add-Type -AssemblyName System.ServiceProcess
    $service=New-Object System.ServiceProcess.ServiceController -ArgumentList 'sshd'
    # Explicit getter preserves the SCM exception; PowerShell property access can hide it.
    try { return $service.get_Status().ToString() }
    catch { if (Test-NexusNotFoundException $_.Exception 2147943460) { return 'Absent' }; throw }
    finally { $service.Dispose() }
}
function Connect-NexusTaskService {
    $service=New-Object -ComObject 'Schedule.Service'
    $service.Connect()
    return $service
}
function Find-NexusRepairTask($TaskService) {
    try { return $TaskService.GetFolder('\').GetTask('NEXUS-Rescue-Tunnel') }
    catch { if (Test-NexusNotFoundException $_.Exception 2147942402) { return $null }; throw }
}
function New-NexusRepairTaskDefinition($TaskService,[string]$Root) {
    $task=$TaskService.NewTask(0)
    $task.RegistrationInfo.Author='NEXUS VPS Rescue'
    $task.RegistrationInfo.Description='NEXUS repair-only outbound SSH tunnel; no Paper/research/writer actions'
    $task.Principal.UserId='S-1-5-18'
    $task.Principal.LogonType=5
    $task.Principal.RunLevel=1
    $task.Settings.Enabled=$true
    $task.Settings.MultipleInstances=2
    $task.Settings.ExecutionTimeLimit='PT0S'
    $task.Settings.RestartCount=3
    $task.Settings.RestartInterval='PT1M'
    $task.Settings.StartWhenAvailable=$true
    $task.Settings.DisallowStartIfOnBatteries=$false
    $task.Settings.StopIfGoingOnBatteries=$false
    $trigger=$task.Triggers.Create(8)
    $trigger.Enabled=$true
    $action=$task.Actions.Create(0)
    $action.Path='C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
    $action.Arguments='-NoLogo -NoProfile -NonInteractive -ExecutionPolicy RemoteSigned -File '+$Root+'\Watch-RescueTunnel.ps1'
    return $task
}
function Connect-NexusFirewallPolicy { return (New-Object -ComObject 'HNetCfg.FwPolicy2') }
function Find-NexusFirewallRule($Policy,[string]$Name) {
    foreach ($rule in $Policy.Rules) { if ($rule.Name -eq $Name) { return $rule } }
    return $null
}
function Get-NexusDefaultSshAllowNames($Policy) {
    foreach ($rule in $Policy.Rules) {
        if ($rule.Name -match '^OpenSSH(-Server-In-TCP| SSH Server \(sshd\))$' -and $rule.Direction -eq 1 -and $rule.Protocol -eq 6 -and $rule.LocalPorts -eq '22' -and $rule.Action -eq 1) { $rule.Name }
    }
}
function Add-NexusPublicSshBlock($Policy) {
    $name='NEXUS-Rescue-Block-Public-SSH'
    if ($null -ne (Find-NexusFirewallRule $Policy $name)) { throw 'Owned firewall rule already exists: refuse overwrite' }
    $rule=New-Object -ComObject 'HNetCfg.FWRule'
    $rule.Name=$name
    $rule.Description='NEXUS rescue: block public inbound TCP-22'
    $rule.Protocol=6
    $rule.LocalPorts='22'
    $rule.Direction=1
    $rule.Action=0
    $rule.Profiles=2147483647
    $rule.Enabled=$true
    $Policy.Rules.Add($rule)
    $actual=Find-NexusFirewallRule $Policy $name
    if ($null -eq $actual -or $actual.Action -ne 0 -or -not $actual.Enabled -or $actual.LocalPorts -ne '22') { throw 'Owned firewall block readback failed' }
}
function Disable-NexusNewDefaultSshAllows($Policy,[string[]]$PreviousNames) {
    foreach ($name in @(Get-NexusDefaultSshAllowNames $Policy)) {
        if ($PreviousNames -notcontains $name) { (Find-NexusFirewallRule $Policy $name).Enabled=$false }
    }
}
