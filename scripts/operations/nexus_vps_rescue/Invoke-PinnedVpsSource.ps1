[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$InputPath,[Parameter(Mandatory=$true)][string]$ExpectedSha256,[int]$TimeoutSeconds=180)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if ($env:COMPUTERNAME -ne 'DESKTOP-1R1081M' -or $env:USERNAME -ne 'afaq') { throw 'Expected existing management laptop/user' }
if ((Get-FileHash -LiteralPath $InputPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedSha256) { throw 'Transport source hash mismatch' }
$pi=New-Object Diagnostics.ProcessStartInfo
$pi.FileName='C:\Program Files\Git\usr\bin\ssh.exe'
$pi.Arguments='-T -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=C:\Users\afaq\.ssh\known_hosts_nexus_arbiter -o ConnectTimeout=8 -o ConnectionAttempts=1 -o ServerAliveInterval=5 -o ServerAliveCountMax=2 -i C:\Users\afaq\.ssh\nexus_vps_arbiter_ed25519 root@87.107.5.150 python3 -'
$pi.UseShellExecute=$false; $pi.CreateNoWindow=$true
$pi.RedirectStandardInput=$true; $pi.RedirectStandardOutput=$true; $pi.RedirectStandardError=$true
$p=[Diagnostics.Process]::Start($pi)
try {
    $stdout=$p.StandardOutput.ReadToEndAsync(); $stderr=$p.StandardError.ReadToEndAsync()
    $p.StandardInput.Write([IO.File]::ReadAllText($InputPath))
    $p.StandardInput.Close()
    if (-not $p.WaitForExit($TimeoutSeconds*1000)) { $p.Kill(); throw 'SSH source execution timeout: inspect VPS before retrying' }
    $rc=$p.ExitCode
    Write-Output $stdout.GetAwaiter().GetResult()
    $errorText=$stderr.GetAwaiter().GetResult()
    if ($errorText) { Write-Output $errorText }
    Write-Output ('SSH_EXIT='+$rc)
    exit $rc
} finally {
    if (-not $p.HasExited) { $p.Kill() }
    $p.Dispose()
}
