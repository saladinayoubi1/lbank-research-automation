[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$BundleDirectory)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$nodes = @{ 'DESKTOP-1R1081M'='LAPTOP1'; 'DESKTOP-F4SA4VL'='LAPTOP2' }
if (-not $nodes.ContainsKey($env:COMPUTERNAME) -or $env:USERNAME -ne 'afaq') { throw 'Unexpected laptop/user' }
$sshDir = Join-Path $env:USERPROFILE '.ssh\nexus-vps-rescue'
$key = Join-Path $sshDir 'forward_ed25519'
$keygen = 'C:\Program Files\Git\usr\bin\ssh-keygen.exe'
if (-not (Test-Path -LiteralPath $keygen)) { throw 'Expected installed Git OpenSSH client' }
if (-not (Test-Path -LiteralPath $sshDir)) {
    New-Item -ItemType Directory -Path $sshDir | Out-Null
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true,$false)
    foreach ($sid in @([Security.Principal.WindowsIdentity]::GetCurrent().User.Value,'S-1-5-18','S-1-5-32-544')) {
        $id = New-Object Security.Principal.SecurityIdentifier($sid)
        $rule = New-Object Security.AccessControl.FileSystemAccessRule($id,'FullControl','ContainerInherit,ObjectInherit','None','Allow')
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $sshDir -AclObject $acl
}
if (((Get-Item -LiteralPath $sshDir).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Unexpected reparse point' }
if ((Test-Path -LiteralPath $key) -ne (Test-Path -LiteralPath ($key+'.pub'))) { throw 'Partial identity: do not overwrite' }
if (-not (Test-Path -LiteralPath $key)) {
    $pi = New-Object Diagnostics.ProcessStartInfo
    $pi.FileName = $keygen
    $pi.Arguments = '-q -t ed25519 -N "" -C NEXUS-RESCUE-'+$nodes[$env:COMPUTERNAME]+' -f "'+$key+'"'
    $pi.UseShellExecute=$false; $pi.CreateNoWindow=$true
    $p = [Diagnostics.Process]::Start($pi)
    if (-not $p.WaitForExit(15000)) { $p.Kill(); throw 'Key generation timed out' }
    if ($p.ExitCode -ne 0) { throw 'Key generation failed' }
}
$public = [IO.File]::ReadAllText($key+'.pub').Trim()
if ($public -notmatch '^ssh-ed25519 [A-Za-z0-9+/]+={0,2} NEXUS-RESCUE-LAPTOP[12]$') { throw 'Unexpected public identity' }
$derived = & $keygen -y -f $key
if ($LASTEXITCODE -ne 0 -or (($derived -split ' ')[0..1] -join ' ') -ne (($public -split ' ')[0..1] -join ' ')) { throw 'Identity mismatch' }
$publicDir = Join-Path $BundleDirectory 'public'
New-Item -ItemType Directory -Force -Path $publicDir | Out-Null
$export = [ordered]@{schema='nexus-rescue-forward-key-v1';node=$nodes[$env:COMPUTERNAME];hostname=$env:COMPUTERNAME;user='afaq';forward_public_key=$public;private_key_exported=$false;writer_authority=$false;live_enabled=$false}
$json = $export | ConvertTo-Json
[IO.File]::WriteAllText((Join-Path $publicDir 'forward-key.json'),$json+"`n",(New-Object Text.UTF8Encoding($false)))
Write-Output $json
Write-Output ('FINGERPRINT=' + (& $keygen -l -f ($key+'.pub')))
