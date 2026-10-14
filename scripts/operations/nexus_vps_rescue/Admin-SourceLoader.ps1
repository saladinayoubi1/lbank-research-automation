$ErrorActionPreference='Stop'
if((Get-ExecutionPolicy -Scope MachinePolicy) -ne 'Undefined' -or (Get-ExecutionPolicy -Scope UserPolicy) -ne 'Undefined'){throw 'Managed script policy: owner review required'}
$stage='E:\NEXUS-QA\vps-rescue-20261014'
if((Get-FileHash -LiteralPath ($stage+'\bundle-manifest.json') -Algorithm SHA256).Hash.ToLowerInvariant() -ne '26ffd6330ba02d5c9d0179f30da57c226123238fda6a7ee37d74aac7816cc355'){throw 'Manifest changed before elevation: stop for review'}
$bytes=[IO.File]::ReadAllBytes($stage+'\Install-NexusRescue.ps1')
$h=[Security.Cryptography.SHA256]::Create()
try{$digest=([BitConverter]::ToString($h.ComputeHash($bytes))).Replace('-','').ToLowerInvariant()}finally{$h.Dispose()}
if($digest -ne '6641befad8bc8dd1d21ecb7d315fdb2d79857491d629d53eee19a56fe93d3d43'){throw 'Installer changed before elevation: stop for review'}
$body=[Text.Encoding]::UTF8.GetString($bytes)
& ([ScriptBlock]::Create($body)) -BundleDirectory $stage
