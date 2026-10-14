[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$nodes=@{ 'DESKTOP-1R1081M'=@{node='LAPTOP1';port=2201;local=18761;denied=2202}; 'DESKTOP-F4SA4VL'=@{node='LAPTOP2';port=2202;local=18762;denied=2201} }
if (-not $nodes.ContainsKey($env:COMPUTERNAME) -or $env:USERNAME -ne 'afaq') { throw 'Unexpected laptop/user' }
$c=$nodes[$env:COMPUTERNAME]
$watch=[IO.File]::ReadAllText((Join-Path $PSScriptRoot 'Watch-RescueTunnel.ps1'))
$match=[regex]::Match($watch,"(?s)Add-Type -TypeDefinition @'\r?\n(.*?)\r?\n'@")
if (-not $match.Success) { throw 'Expected owned job implementation' }
Add-Type -TypeDefinition $match.Groups[1].Value
$job=New-Object NexusRescueJob
$key=Join-Path $env:USERPROFILE '.ssh\nexus-vps-rescue\forward_ed25519'
$pin=Join-Path $PSScriptRoot 'vps-known-hosts'
$base='-n -N -T -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o ExitOnForwardFailure=yes -o ConnectTimeout=10 -o ConnectionAttempts=1 -o ServerAliveInterval=5 -o ServerAliveCountMax=2 -o HostKeyAlgorithms=rsa-sha2-512,rsa-sha2-256 -o UserKnownHostsFile="'+$pin+'" -i "'+$key+'"'
function Start-OwnedSsh([int]$Port) {
    $pi=New-Object Diagnostics.ProcessStartInfo
    $pi.FileName='C:\Program Files\Git\usr\bin\ssh.exe'
    $pi.Arguments=$base+' -R 127.0.0.1:'+$Port+':127.0.0.1:'+$c.local+' nexusrescue@87.107.5.150'
    $pi.UseShellExecute=$false; $pi.CreateNoWindow=$true
    $pi.RedirectStandardOutput=$true; $pi.RedirectStandardError=$true
    $p=[Diagnostics.Process]::Start($pi)
    try { $job.Assign($p.Handle) } catch { $p.Kill(); throw }
    return $p
}
$listener=$null; $denied=$null; $allowed=$null
$receipt=[ordered]@{schema='nexus-rescue-transport-smoke-v1';hostname=$env:COMPUTERNAME;node=$c.node;relay_port=$c.port;status='RUNNING';cross_node_port_rejected=$false;marker_served=$false;windows_ssh_acceptance=$false;private_key_exported=$false;writer_authority=$false;live_enabled=$false}
try {
    $denied=Start-OwnedSsh $c.denied
    $deniedErr=$denied.StandardError.ReadToEndAsync()
    $deniedOut=$denied.StandardOutput.ReadToEndAsync()
    if (-not $denied.WaitForExit(25000)) { throw 'Denied forwarding unexpectedly stayed connected' }
    $denial=$deniedErr.GetAwaiter().GetResult()
    if ($denied.ExitCode -eq 0 -or $denial -notmatch 'remote port forwarding failed') { throw ('Expected per-key port denial, got: '+$denial) }
    $receipt.cross_node_port_rejected=$true
    $denied.Dispose(); $denied=$null
    $listener=New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback,$c.local)
    $listener.Start()
    $allowed=Start-OwnedSsh $c.port
    $allowedErr=$allowed.StandardError.ReadToEndAsync()
    $allowedOut=$allowed.StandardOutput.ReadToEndAsync()
    Write-Output ('TRANSPORT_PROBE_READY '+$c.node+' relay='+$c.port+' target=127.0.0.1:'+$c.local)
    $deadline=[DateTime]::UtcNow.AddSeconds(210)
    while (-not $listener.Pending()) {
        if ($allowed.HasExited) { throw ('Allowed forwarding failed: '+$allowedErr.GetAwaiter().GetResult()) }
        if ([DateTime]::UtcNow -ge $deadline) { throw 'VPS marker probe did not arrive before deadline' }
        Start-Sleep -Milliseconds 250
    }
    $peer=$listener.AcceptTcpClient()
    try {
        $data=[Text.Encoding]::ASCII.GetBytes('NEXUS-RESCUE-'+$c.node+' TRANSPORT_ONLY'+"`n")
        $stream=$peer.GetStream(); $stream.Write($data,0,$data.Length); $stream.Flush()
    } finally { $peer.Close() }
    $receipt.marker_served=$true
    $receipt.status='TRANSPORT_ONLY_PASSED_PENDING_WINDOWS_ADMIN'
} catch {
    $receipt.status='FAILED'; $receipt.error=$_.Exception.Message
    throw
} finally {
    if ($null -ne $listener) { $listener.Stop() }
    $job.Dispose()
    foreach ($p in @($denied,$allowed)) { if ($null -ne $p) { $p.WaitForExit(5000)|Out-Null; $p.Dispose() } }
    $json=$receipt|ConvertTo-Json
    [IO.File]::WriteAllText((Join-Path $PSScriptRoot 'public\transport-result.json'),$json+"`n",(New-Object Text.UTF8Encoding($false)))
    Write-Output $json
}
