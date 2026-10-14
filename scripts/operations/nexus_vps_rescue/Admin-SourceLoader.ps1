$ErrorActionPreference='Stop'
if((Get-ExecutionPolicy -Scope MachinePolicy) -ne 'Undefined' -or (Get-ExecutionPolicy -Scope UserPolicy) -ne 'Undefined'){throw 'Managed script policy: owner review required'}
$stage='E:\NEXUS-QA\vps-rescue-20261014'
if((Get-FileHash -LiteralPath ($stage+'\bundle-manifest.json') -Algorithm SHA256).Hash.ToLowerInvariant() -ne 'a252f6b11ded9505c00be5aa5c1a83388d6c28168a9bd961f62a4da589a59772'){throw 'Manifest changed before elevation: stop for review'}
$bytes=[IO.File]::ReadAllBytes($stage+'\Install-NexusRescue.ps1')
$h=[Security.Cryptography.SHA256]::Create()
try{$digest=([BitConverter]::ToString($h.ComputeHash($bytes))).Replace('-','').ToLowerInvariant()}finally{$h.Dispose()}
if($digest -ne '3b4060007f8c4e6b94020ce7fc22eff7a74ee966a5255002e1512f4a27567f51'){throw 'Installer changed before elevation: stop for review'}
$body=[Text.Encoding]::UTF8.GetString($bytes)
& ([ScriptBlock]::Create($body)) -BundleDirectory $stage
