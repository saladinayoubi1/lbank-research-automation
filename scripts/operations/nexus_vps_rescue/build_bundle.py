"""Freeze locally authored Windows bytes and the elevated source loader."""
from pathlib import Path
import base64
import hashlib
import json

p=Path(__file__).resolve().parent
names=['Prepare-RescueKey.ps1','Install-NexusRescue.ps1','Watch-RescueTunnel.ps1','Validate-RescueBundle.ps1','vps-known-hosts','operator-authorized-key']
files={name:hashlib.sha256((p/name).read_bytes()).hexdigest() for name in names}
manifest={'schema':'nexus-rescue-bundle-v1','files':files,'writer_authority':False,'live_enabled':False}
raw=(json.dumps(manifest,indent=2)+'\n').encode()
(p/'bundle-manifest.json').write_bytes(raw)
manifest_digest=hashlib.sha256(raw).hexdigest()
loader="""$ErrorActionPreference='Stop'
if((Get-ExecutionPolicy -Scope MachinePolicy) -ne 'Undefined' -or (Get-ExecutionPolicy -Scope UserPolicy) -ne 'Undefined'){throw 'Managed script policy: owner review required'}
$stage='E:\\NEXUS-QA\\vps-rescue-20261014'
if((Get-FileHash -LiteralPath ($stage+'\\bundle-manifest.json') -Algorithm SHA256).Hash.ToLowerInvariant() -ne 'MANIFEST_DIGEST'){throw 'Manifest changed before elevation: stop for review'}
$bytes=[IO.File]::ReadAllBytes($stage+'\\Install-NexusRescue.ps1')
$h=[Security.Cryptography.SHA256]::Create()
try{$digest=([BitConverter]::ToString($h.ComputeHash($bytes))).Replace('-','').ToLowerInvariant()}finally{$h.Dispose()}
if($digest -ne 'INSTALLER_DIGEST'){throw 'Installer changed before elevation: stop for review'}
$body=[Text.Encoding]::UTF8.GetString($bytes)
& ([ScriptBlock]::Create($body)) -BundleDirectory $stage
""".replace('MANIFEST_DIGEST',manifest_digest).replace('INSTALLER_DIGEST',files['Install-NexusRescue.ps1'])
(p/'Admin-SourceLoader.ps1').write_text(loader)
encoded=base64.b64encode(loader.encode('utf-16le')).decode()
launcher='@echo off\npowershell.exe -NoLogo -NoProfile -Command "$ErrorActionPreference=\'Stop\'; Start-Process \'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe\' -Verb RunAs -ArgumentList \'-NoLogo -NoProfile -NoExit -ExecutionPolicy RemoteSigned -EncodedCommand '+encoded+'\'"\nif errorlevel 1 pause\n'
(p/'NEXUS-Enable-Rescue.cmd').write_text(launcher)
print(json.dumps({'manifest_sha256':manifest_digest,'installer_sha256':files['Install-NexusRescue.ps1'],'launcher_sha256':hashlib.sha256(launcher.encode()).hexdigest(),'loader_sha256':hashlib.sha256(loader.encode()).hexdigest()}))
