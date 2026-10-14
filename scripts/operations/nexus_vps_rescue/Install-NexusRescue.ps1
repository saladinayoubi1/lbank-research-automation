[CmdletBinding()]
param([switch]$InspectOnly,[string]$BundleDirectory=$PSScriptRoot)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$Root='C:\ProgramData\NEXUS-Rescue'
$TaskName='NEXUS-Rescue-Tunnel'
$FirewallName='NEXUS-Rescue-Block-Public-SSH'
$nodes=@{ 'DESKTOP-1R1081M'=@{node='LAPTOP1';port=2201}; 'DESKTOP-F4SA4VL'=@{node='LAPTOP2';port=2202} }
if (-not $nodes.ContainsKey($env:COMPUTERNAME)) { throw 'Unexpected laptop' }
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$principal=New-Object Security.Principal.WindowsPrincipal($identity)
$admin=$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$manifest=Get-Content -LiteralPath (Join-Path $BundleDirectory 'bundle-manifest.json') -Raw | ConvertFrom-Json
foreach ($item in $manifest.files.PSObject.Properties) {
    if ($item.Name -notmatch '^[A-Za-z0-9_.-]+$') { throw 'Invalid bundle path' }
    $path=Join-Path $BundleDirectory $item.Name
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $item.Value) { throw ('Bundle hash mismatch: '+$item.Name) }
}
$forward=Join-Path $env:USERPROFILE '.ssh\nexus-vps-rescue\forward_ed25519'
$client='C:\Program Files\Git\usr\bin\ssh.exe'
$keygen='C:\Program Files\Git\usr\bin\ssh-keygen.exe'
foreach ($path in @($forward,($forward+'.pub'),$client,$keygen)) { if (-not (Test-Path -LiteralPath $path)) { throw ('Required file absent: '+$path) } }
$platformBytes=[IO.File]::ReadAllBytes((Join-Path $BundleDirectory 'Rescue-WindowsPlatform.ps1'))
$platformHasher=[Security.Cryptography.SHA256]::Create()
try { $platformDigest=([BitConverter]::ToString($platformHasher.ComputeHash($platformBytes))).Replace('-','').ToLowerInvariant() } finally { $platformHasher.Dispose() }
if ($platformDigest -ne $manifest.files.'Rescue-WindowsPlatform.ps1') { throw 'Platform helper changed before load' }
. ([ScriptBlock]::Create([Text.Encoding]::UTF8.GetString($platformBytes)))
$existing=Get-NexusSshdState
$installedBefore=Test-Path -LiteralPath 'C:\Windows\System32\OpenSSH\sshd.exe'
if ($existing -ne 'Absent' -or $installedBefore -or (Test-Path -LiteralPath $Root)) { throw 'Existing SSH/rescue installation: inspect before adoption; never overwrite' }
$portListeners=@(Get-NexusTcpListeners 22)
$taskService=Connect-NexusTaskService
$existingTask=Find-NexusRepairTask $taskService
$firewallPolicy=Connect-NexusFirewallPolicy
$existingBlock=Find-NexusFirewallRule $firewallPolicy $FirewallName
if ($portListeners.Count) { throw 'Port 22 already owned' }
if ($null -ne $existingTask) { throw 'Task already exists' }
if ($null -ne $existingBlock) { throw 'Firewall rule already exists' }
$previousDefaultAllows=@(Get-NexusDefaultSshAllowNames $firewallPolicy)
if ($InspectOnly) {
    [ordered]@{schema='nexus-rescue-inspection-v2';bundle_verified=$true;hostname=$env:COMPUTERNAME;node=$nodes[$env:COMPUTERNAME].node;administrator=$admin;ssh_server_absent=$true;relay_port=$nodes[$env:COMPUTERNAME].port;ip_helper_query_pass=$true;task_com_query_pass=$true;firewall_com_query_pass=$true;cim_required=$false;mutation_performed=$false;writer_authority=$false;live_enabled=$false} | ConvertTo-Json
    return
}
if (-not $admin) { throw 'Run this reviewed installer as Administrator and accept Windows UAC' }
if ($env:USERNAME -ne 'afaq') { throw 'Use the existing afaq Administrator account' }
function Write-Utf8([string]$Path,[string]$Content) { [IO.File]::WriteAllText($Path,$Content,(New-Object Text.UTF8Encoding($false))) }
function Invoke-Checked([string]$Exe,[string]$Arguments,[int]$Timeout=15000) {
    $pi=New-Object Diagnostics.ProcessStartInfo
    $pi.FileName=$Exe; $pi.Arguments=$Arguments; $pi.UseShellExecute=$false; $pi.CreateNoWindow=$true
    $pi.RedirectStandardOutput=$true; $pi.RedirectStandardError=$true
    $p=[Diagnostics.Process]::Start($pi)
    $o=$p.StandardOutput.ReadToEndAsync(); $e=$p.StandardError.ReadToEndAsync()
    if (-not $p.WaitForExit($Timeout)) { $p.Kill(); throw ('Timed out: '+$Exe) }
    if ($p.ExitCode -ne 0) { throw ('Failed: '+$Exe+' '+$e.GetAwaiter().GetResult()) }
    return $o.GetAwaiter().GetResult()
}
New-Item -ItemType Directory -Path $Root | Out-Null
$acl=New-Object Security.AccessControl.DirectorySecurity
$acl.SetAccessRuleProtection($true,$false)
$acl.SetOwner((New-Object Security.Principal.SecurityIdentifier('S-1-5-32-544')))
foreach ($sid in @('S-1-5-18','S-1-5-32-544')) {
    $id=New-Object Security.Principal.SecurityIdentifier($sid)
    $rule=New-Object Security.AccessControl.FileSystemAccessRule($id,'FullControl','ContainerInherit,ObjectInherit','None','Allow')
    $acl.AddAccessRule($rule)
}
Set-Acl -LiteralPath $Root -AclObject $acl
$receipt=[ordered]@{schema='nexus-rescue-install-v1';hostname=$env:COMPUTERNAME;node=$nodes[$env:COMPUTERNAME].node;port=$nodes[$env:COMPUTERNAME].port;status='INSTALLING';writer_authority=$false;live_enabled=$false}
Write-Utf8 (Join-Path $Root 'install-receipt.json') (($receipt|ConvertTo-Json)+"`n")
$ownedTask=$null
try {
    # Capture verified bytes into the private directory before installing capabilities.
    foreach ($name in @('Watch-RescueTunnel.ps1','Rescue-WindowsPlatform.ps1','vps-known-hosts','operator-authorized-key')) {
        $bytes=[IO.File]::ReadAllBytes((Join-Path $BundleDirectory $name))
        $hasher=[Security.Cryptography.SHA256]::Create()
        try { $digest=([BitConverter]::ToString($hasher.ComputeHash($bytes))).Replace('-','').ToLowerInvariant() } finally { $hasher.Dispose() }
        if ($digest -ne $manifest.files.$name) { throw ('Bundle changed before private capture: '+$name) }
        [IO.File]::WriteAllBytes((Join-Path $Root $name),$bytes)
    }
    [IO.File]::WriteAllBytes((Join-Path $Root 'forward_ed25519'),[IO.File]::ReadAllBytes($forward))
    $expectedForward=@{ 'DESKTOP-1R1081M'='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIi16VZdDqz1qMcQT4ot6Uaj41ydb8UU18QxYTWbrZMD NEXUS-RESCUE-LAPTOP1'; 'DESKTOP-F4SA4VL'='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJ9t7dxIob2PVoyDUejkKoLQDCkDcu+IMFvk0eEQdj11 NEXUS-RESCUE-LAPTOP2' }
    $derived=(Invoke-Checked $keygen ('-y -P "" -f '+$Root+'\forward_ed25519')).Trim()
    if ((($derived -split ' ')[0..1] -join ' ') -ne (($expectedForward[$env:COMPUTERNAME] -split ' ')[0..1] -join ' ')) { throw 'Copied forward identity differs from VPS registry' }
    Write-Utf8 (Join-Path $Root 'forward_ed25519.pub') ($expectedForward[$env:COMPUTERNAME]+"`n")
    Add-NexusPublicSshBlock $firewallPolicy
    $feature=Add-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0'
    if ($feature.RestartNeeded) { $receipt.status='REBOOT_REQUIRED_NO_REBOOT_PERFORMED'; throw 'Windows reports reboot required; stop for owner action' }
    Stop-Service -Name sshd -ErrorAction SilentlyContinue
    Set-Service -Name sshd -StartupType Disabled
    Disable-NexusNewDefaultSshAllows $firewallPolicy $previousDefaultAllows
    Write-Utf8 (Join-Path $Root 'authorized_keys') ('restrict '+[IO.File]::ReadAllText((Join-Path $Root 'operator-authorized-key')).Trim()+"`n")
    $hostKey=Join-Path $Root 'rescue_host_ed25519'
    $null=Invoke-Checked $keygen ('-q -t ed25519 -N "" -C NEXUS-RESCUE-HOST-'+$receipt.node+' -f "'+$hostKey+'"')
    $sshd='C:\Windows\System32\OpenSSH\sshd.exe'
    $sshdConfig=@'
Port 22
AddressFamily inet
ListenAddress 127.0.0.1
HostKey C:/ProgramData/NEXUS-Rescue/rescue_host_ed25519
AuthorizedKeysFile C:/ProgramData/NEXUS-Rescue/authorized_keys
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
AuthenticationMethods publickey
PermitEmptyPasswords no
AllowUsers afaq
StrictModes yes
AllowTcpForwarding no
AllowStreamLocalForwarding no
AllowAgentForwarding no
PermitTTY no
X11Forwarding no
MaxAuthTries 3
LoginGraceTime 20
LogLevel VERBOSE
Subsystem sftp C:/Windows/System32/OpenSSH/sftp-server.exe
'@
    Write-Utf8 (Join-Path $Root 'sshd_config') ($sshdConfig+"`n")
    $null=Invoke-Checked $sshd ('-t -f '+$Root+'\sshd_config')
    $imagePath=$sshd+' -f '+$Root+'\sshd_config'
    $null=Invoke-Checked 'C:\Windows\System32\sc.exe' ('config sshd binPath= "'+$imagePath+'" start= auto')
    $actualImage=(Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\sshd').ImagePath
    if ($actualImage -ne $imagePath) { throw 'SSH service path mismatch' }
    $files=[ordered]@{}
    foreach ($name in @('Watch-RescueTunnel.ps1','Rescue-WindowsPlatform.ps1','vps-known-hosts','forward_ed25519','forward_ed25519.pub','sshd_config','authorized_keys','rescue_host_ed25519','rescue_host_ed25519.pub')) { $files[$name]=(Get-FileHash -LiteralPath (Join-Path $Root $name) -Algorithm SHA256).Hash.ToLowerInvariant() }
    $installed=[ordered]@{schema='nexus-rescue-owned-v1';hostname=$env:COMPUTERNAME;port=$receipt.port;ssh_client=$client;ssh_client_sha256=(Get-FileHash -LiteralPath $client -Algorithm SHA256).Hash.ToLowerInvariant();service_image_path=$imagePath;files=$files;writer_authority=$false;live_enabled=$false}
    Write-Utf8 (Join-Path $Root 'installed.json') (($installed|ConvertTo-Json -Depth 8)+"`n")
    $null=& (Join-Path $Root 'Watch-RescueTunnel.ps1') -Root $Root -ValidateOnly
    Start-Service -Name sshd
    $listeners=@(Get-NexusTcpListeners 22)
    if ($listeners.Count -ne 1 -or $listeners[0].Address.ToString() -ne '127.0.0.1') { throw 'Unexpected SSH listener: stop installation' }
    $taskDefinition=New-NexusRepairTaskDefinition $taskService $Root
    # TASK_CREATE=2 refuses an existing task; service-account logon=5 stores no password.
    $ownedTask=$taskService.GetFolder('\').RegisterTaskDefinition($TaskName,$taskDefinition,2,'S-1-5-18',$null,5,$null)
    $runningTask=$ownedTask.Run($null)
    $receipt.status='INSTALLED_PENDING_VPS_SSH_ACCEPTANCE'
    $receipt.forward_public_key=[IO.File]::ReadAllText((Join-Path $Root 'forward_ed25519.pub')).Trim()
    $receipt.host_public_key=[IO.File]::ReadAllText(($hostKey+'.pub')).Trim()
    $receipt.host_fingerprint=(Invoke-Checked $keygen ('-l -f "'+$hostKey+'.pub"')).Trim()
    $publicDir=Join-Path $BundleDirectory 'public'
    New-Item -ItemType Directory -Force -Path $publicDir | Out-Null
    Write-Utf8 (Join-Path $publicDir 'installed-public.json') (($receipt|ConvertTo-Json -Depth 8)+"`n")
    Write-Output 'Installed repair SSH and tunnel. Actual VPS-to-laptop SSH acceptance is still required.'
} catch {
    if ($receipt.status -eq 'INSTALLING') { $receipt.status='FAILED_STOPPED_REVIEW_REQUIRED' }
    $receipt.error=$_.Exception.Message
    if ($null -ne $ownedTask) { try { $ownedTask.Stop(0) } catch { Write-Warning 'Owned repair task stop requires inspection' } }
    Stop-Service -Name sshd -ErrorAction SilentlyContinue
    Set-Service -Name sshd -StartupType Disabled -ErrorAction SilentlyContinue
    throw
} finally {
    Write-Utf8 (Join-Path $Root 'install-receipt.json') (($receipt|ConvertTo-Json -Depth 8)+"`n")
    $publicDir=Join-Path $BundleDirectory 'public'
    New-Item -ItemType Directory -Force -Path $publicDir | Out-Null
    Write-Utf8 (Join-Path $publicDir 'installed-public.json') (($receipt|ConvertTo-Json -Depth 8)+"`n")
}
