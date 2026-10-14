[CmdletBinding()]
param([string]$Root='C:\ProgramData\NEXUS-Rescue',[switch]$ValidateOnly)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
function Read-VerifiedConfiguration {
    $c = Get-Content -LiteralPath (Join-Path $Root 'installed.json') -Raw | ConvertFrom-Json
    $expected = @{ 'DESKTOP-1R1081M'=2201; 'DESKTOP-F4SA4VL'=2202 }
    if (-not $expected.ContainsKey($env:COMPUTERNAME) -or $c.hostname -ne $env:COMPUTERNAME -or $c.port -ne $expected[$env:COMPUTERNAME]) { throw 'Node identity mismatch' }
    foreach ($f in $c.files.PSObject.Properties) {
        $path = Join-Path $Root $f.Name
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $f.Value) { throw ('Installed file changed: '+$f.Name) }
    }
    if ((Get-FileHash -LiteralPath $c.ssh_client -Algorithm SHA256).Hash.ToLowerInvariant() -ne $c.ssh_client_sha256) { throw 'SSH client changed: require review' }
    return $c
}
$config = Read-VerifiedConfiguration
. (Join-Path $Root 'Rescue-WindowsPlatform.ps1')
$sshArgs = '-n -N -T -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o ExitOnForwardFailure=yes -o ConnectTimeout=10 -o ConnectionAttempts=1 -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o HostKeyAlgorithms=rsa-sha2-512,rsa-sha2-256 -o UserKnownHostsFile="'+$Root+'\vps-known-hosts" -i "'+$Root+'\forward_ed25519" -R 127.0.0.1:'+$config.port+':127.0.0.1:22 nexusrescue@87.107.5.150'
if ($ValidateOnly) { [ordered]@{valid=$true;hostname=$env:COMPUTERNAME;relay_port=$config.port;local_target='127.0.0.1:22';writer_authority=$false;live_enabled=$false} | ConvertTo-Json; exit 0 }
if ([Security.Principal.WindowsIdentity]::GetCurrent().User.Value -ne 'S-1-5-18') { throw 'Repair task must run as SYSTEM' }
Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
public sealed class NexusRescueJob : IDisposable {
    [StructLayout(LayoutKind.Sequential)] struct Basic { public long pTime,jTime; public uint flags; public UIntPtr min,max; public uint active; public UIntPtr affinity; public uint priority,schedule; }
    [StructLayout(LayoutKind.Sequential)] struct Io { public ulong a,b,c,d,e,f; }
    [StructLayout(LayoutKind.Sequential)] struct Extended { public Basic basic; public Io io; public UIntPtr processMem,jobMem,peakProcess,peakJob; }
    [DllImport("kernel32.dll",SetLastError=true)] static extern IntPtr CreateJobObject(IntPtr attrs,string name);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool SetInformationJobObject(IntPtr h,int cls,ref Extended info,uint size);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool AssignProcessToJobObject(IntPtr job,IntPtr process);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
    IntPtr h;
    public NexusRescueJob() {
        h=CreateJobObject(IntPtr.Zero,null); if(h==IntPtr.Zero) throw new Win32Exception();
        var info=new Extended(); info.basic.flags=0x2000;
        if(!SetInformationJobObject(h,9,ref info,(uint)Marshal.SizeOf(typeof(Extended)))) { CloseHandle(h); h=IntPtr.Zero; throw new Win32Exception(); }
    }
    public void Assign(IntPtr process) { if(!AssignProcessToJobObject(h,process)) throw new Win32Exception(); }
    public void Dispose() { if(h!=IntPtr.Zero) { CloseHandle(h); h=IntPtr.Zero; } }
}
'@
$mutex = New-Object Threading.Mutex($false,'Global\NEXUS-Rescue-Tunnel')
$owned = $false; $child = $null; $job=$null
try {
    try { $owned=$mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $owned=$true }
    if (-not $owned) { exit 0 }
    $job=New-Object NexusRescueJob
    $log = Join-Path $Root 'tunnel-events.log'
    $delay = 5
    while ($true) {
        $config = Read-VerifiedConfiguration
        if ((Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\sshd').ImagePath -ne $config.service_image_path) { throw 'SSH service ownership changed' }
        if ((Get-NexusSshdState) -ne 'Running') { Start-Service -Name sshd }
        if ((Test-Path -LiteralPath $log) -and (Get-Item -LiteralPath $log).Length -gt 1048576) { Move-Item -LiteralPath $log -Destination ($log+'.previous') -Force }
        $pi = New-Object Diagnostics.ProcessStartInfo
        $pi.FileName=$config.ssh_client; $pi.Arguments=$sshArgs
        $pi.UseShellExecute=$false; $pi.CreateNoWindow=$true
        $pi.RedirectStandardError=$true; $pi.RedirectStandardOutput=$true
        $child = [Diagnostics.Process]::Start($pi)
        $job.Assign($child.Handle)
        $errorRead = $child.StandardError.ReadToEndAsync()
        $outRead = $child.StandardOutput.ReadToEndAsync()
        $start = [DateTime]::UtcNow
        while (-not $child.WaitForExit(15000)) { $null=Read-VerifiedConfiguration }
        $rc=$child.ExitCode
        $message=$errorRead.GetAwaiter().GetResult()
        if ($message.Length -gt 4096) { $message=$message.Substring(0,4096) }
        [IO.File]::AppendAllText($log,([DateTime]::UtcNow.ToString('o')+' child='+$child.Id+' exit='+$rc+' '+$message+"`n"))
        if (([DateTime]::UtcNow-$start).TotalSeconds -gt 120) { $delay=5 }
        $child.Dispose(); $child=$null
        Start-Sleep -Seconds $delay
        $delay=[Math]::Min(30,$delay*2)
    }
} finally {
    if ($null -ne $child) { if (-not $child.HasExited) { $child.Kill(); $child.WaitForExit(5000) | Out-Null }; $child.Dispose() }
    if ($null -ne $job) { $job.Dispose() }
    if ($owned) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
