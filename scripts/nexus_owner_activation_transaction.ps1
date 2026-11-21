# NEXUS owner GUI cutover. No Live authority. No GitHub token or reboot.
[CmdletBinding()]
param(
  [ValidateSet('Preflight','Rehearse','Activate','Recover')][string]$Mode='Preflight',
  [string]$ExpectedSourceSha='931a95b079682955cecb29a9eb404ec2e067ac7d',
  [string]$OldVersion='1931871b',
  [string]$StageProof='E:\NEXUS\proofs\stage-931a95b0-36327451730\official-stage-evidence.json',
  [string]$CloneProof='E:\NEXUS\proofs\stage-931a95b0-36327451730\private-clone-smoke-sanitized.json',
  [string]$PrivateRoot='E:\NEXUS\NEXUS_OWNER_PAPER_PRIVATE',
  [string]$TransactionDir='',
  [switch]$TestScheduler,
  [ValidateSet('SharedPortfolio','DeviceJournal')][string]$AccountSurface='SharedPortfolio',
  [string]$CandidateInstallRoot='',
  [string]$PriorInstallRoot='',
  [string]$PriorSourceSha='',
  [string]$OwnerProfileRoot='',
  [string]$ExpectedJournalSha256='',
  [long]$ExpectedArtifactId=0,
  [long]$ExpectedArtifactRunId=0,
  [string]$ExpectedUnpackedSha256='',
  [string]$ExpectedStageProofSha256='',
  [string]$ExpectedCloneProofSha256='',
  [string]$RehearsalProof='',
  [string]$ExpectedRehearsalProofSha256='',
  [string]$JournalPython=''
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$expectedRepo='saladinayoubi1/lbank-research-automation'
$sourceShort=$ExpectedSourceSha.Substring(0,8)
$program=Join-Path $env:LOCALAPPDATA 'Programs\NEXUS Personal Pro'
$candidate=Join-Path $program "5.1.0-$sourceShort"
$prior=Join-Path $program "5.1.0-$OldVersion"
$owner=Join-Path $env:APPDATA 'nexus-personal-pro-product'
$syncTask='NEXUS Prospective Paper Sync'
$taskName="NEXUS-Activation-Rollback-$sourceShort"
$mutex=New-Object System.Threading.Mutex($false,'Local\NEXUS-OwnerActivation')
$script:DeviceVerifierRoot=$null
$script:DeviceBaseline=$null
function Assert([bool]$Condition,[string]$Reason) { if(-not $Condition){throw $Reason} }
function JsonFile([string]$Path){Get-Content -LiteralPath $Path -Raw -ErrorAction Stop | ConvertFrom-Json}
function Write-Json([string]$Path,[object]$Object) {
  $temp="$Path.tmp";[IO.File]::WriteAllText($temp,($Object|ConvertTo-Json -Depth 7),(New-Object Text.UTF8Encoding($false)))
  Move-Item -LiteralPath $temp -Destination $Path -Force
}
function Hash([string]$Path){(Get-FileHash -LiteralPath $Path -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()}
function IsWithin([string]$File,[string]$Root){
  $r=[IO.Path]::GetFullPath($Root).TrimEnd('\')+'\'
  [IO.Path]::GetFullPath($File).StartsWith($r,[StringComparison]::OrdinalIgnoreCase)
}
function ExactProcs([string]$Root){
  @(Get-Process -Name 'NEXUS Personal Pro','nexus-product-server' -ErrorAction SilentlyContinue |
    Where-Object {$_.Path -and (IsWithin $_.Path $Root)})
}
function Stop-Exact([string]$Root,[int]$GraceSeconds=12) {
  Assert ($Root -in @($candidate,$prior)) 'Only the two bound installation roots can be stopped'
  $scope=Split-Path -Leaf $Root
  # Electron's healthy GUI supervises the Python sidecar: killing the sidecar
  # before the GUI host has exited can trigger an immediate replacement child.
  # Request a normal owner-window close first; NEVER signal an unrelated app.
  foreach($x in @(ExactProcs $Root)){
    if($x.ProcessName -eq 'NEXUS Personal Pro' -and $x.MainWindowHandle -ne 0){
      try{$null=$x.CloseMainWindow()}catch{}
    }
  }
  $graceUntil=[DateTime]::UtcNow.AddSeconds([Math]::Max(0,$GraceSeconds))
  do {
    if(@(ExactProcs $Root).Count -eq 0){break}
    Start-Sleep -Milliseconds 500
  }while([DateTime]::UtcNow -lt $graceUntil)

  # The prior one-snapshot stop loop could leave an engine re-created between
  # signals and the final check. Re-enumerate exact paths every bounded pass,
  # retire GUI hosts FIRST, then retire only orphaned exact-root sidecars.
  for($pass=1;$pass -le 4;$pass++){
    $hosts=@(ExactProcs $Root | Where-Object {$_.ProcessName -eq 'NEXUS Personal Pro'} | Sort-Object Id)
    foreach($x in $hosts){
      $again=Get-Process -Id $x.Id -ErrorAction SilentlyContinue
      if($again -and $again.ProcessName -eq 'NEXUS Personal Pro' -and $again.Path -and (IsWithin $again.Path $Root)){
        try{Stop-Process -Id $again.Id -Force -ErrorAction Stop}
        catch{
          $still=Get-Process -Id $x.Id -ErrorAction SilentlyContinue
          if($still -and $still.Path -and (IsWithin $still.Path $Root)){throw}
        }
      }
    }
    $hostDeadline=[DateTime]::UtcNow.AddSeconds(2)
    do {
      $hosts=@(ExactProcs $Root | Where-Object {$_.ProcessName -eq 'NEXUS Personal Pro'})
      if($hosts.Count -eq 0){break}
      Start-Sleep -Milliseconds 250
    }while([DateTime]::UtcNow -lt $hostDeadline)
    # Never kill an engine while its host is still alive and able to respawn it.
    if($hosts.Count -eq 0){
      foreach($x in @(ExactProcs $Root | Where-Object {$_.ProcessName -eq 'nexus-product-server'})){
        $again=Get-Process -Id $x.Id -ErrorAction SilentlyContinue
        if($again -and $again.ProcessName -eq 'nexus-product-server' -and $again.Path -and
          (IsWithin $again.Path $Root) -and
          @(ExactProcs $Root | Where-Object {$_.ProcessName -eq 'NEXUS Personal Pro'}).Count -eq 0){
          try{Stop-Process -Id $again.Id -Force -ErrorAction Stop}
          catch{
            $still=Get-Process -Id $x.Id -ErrorAction SilentlyContinue
            if($still -and $still.Path -and (IsWithin $still.Path $Root)){throw}
          }
        }
      }
    }
    # Several consecutive absent checks, not one transient empty snapshot.
    $stable=0
    while($stable -lt 5){
      if(@(ExactProcs $Root).Count -ne 0){break}
      $stable++
      Start-Sleep -Milliseconds 500
    }
    if($stable -eq 5){
      Write-Host "NEXUS_EXACT_QUIESCENCE=PASS scope=$scope passes=$pass"
      return
    }
    $left=@(ExactProcs $Root)
    $gui=@($left | Where-Object {$_.ProcessName -eq 'NEXUS Personal Pro'}).Count
    $engine=@($left | Where-Object {$_.ProcessName -eq 'nexus-product-server'}).Count
    Write-Host "NEXUS_EXACT_QUIESCENCE_RETRY scope=$scope pass=$pass gui=$gui engine=$engine"
  }
  $remaining=@(ExactProcs $Root)
  $gui=@($remaining | Where-Object {$_.ProcessName -eq 'NEXUS Personal Pro'}).Count
  $engine=@($remaining | Where-Object {$_.ProcessName -eq 'nexus-product-server'}).Count
  throw "Exact-version processes did not quiesce scope=$scope gui=$gui engine=$engine; no other install was signaled"
}
function ProfileFiles([string]$Root) {
  Assert (@(Get-ChildItem -LiteralPath $Root -Recurse -Force -ErrorAction Stop|Where-Object {$_.Attributes -band [IO.FileAttributes]::ReparsePoint}).Count -eq 0) 'Owner profile has reparse content'
  @(Get-ChildItem -LiteralPath $Root -File -Recurse -Force -ErrorAction Stop |
    ForEach-Object {
      Assert (($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) 'Profile contains a reparse file'
      [pscustomobject]@{rel=$_.FullName.Substring($Root.Length+1);sha=Hash $_.FullName;bytes=$_.Length}
    })
}
function PaperPath([string]$Root) {
  if($AccountSurface -eq 'DeviceJournal'){return Join-Path $Root 'product-data\product_runtime\paper-events.jsonl'}
  return Join-Path $Root 'product-data\shared_paper\terminal.json'
}
function DevicePlain([string]$Path) {
  $full=[IO.Path]::GetFullPath($Path).TrimEnd('\')
  Assert ($full -match '^[A-Za-z]:\\' -and $full -notmatch '["\r\n]') 'Device path must be an explicit local absolute path'
  $cursor=$full
  while($cursor){
    $item=Get-Item -LiteralPath $cursor -Force -ErrorAction Stop
    Assert (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) 'Device path contains a reparse point'
    $parent=Split-Path -Parent $cursor
    if(!$parent -or $parent -eq $cursor){break}
    $cursor=$parent
  }
  return $full
}
function InitializeDeviceContext {
  Assert ($env:OS -eq 'Windows_NT' -and $env:COMPUTERNAME -eq 'DESKTOP-1R1081M') 'DeviceJournal target host mismatch'
  $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
  $principal=New-Object Security.Principal.WindowsPrincipal($identity)
  Assert ($identity.Name -notmatch '^(?i:NT AUTHORITY\\(?:SYSTEM|LOCAL SERVICE|NETWORK SERVICE))$' -and [Environment]::UserInteractive -and !$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) 'DeviceJournal requires the normal interactive owner'
  $session=(Get-Process -Id $PID).SessionId
  Assert (@(Get-Process -Name explorer -ErrorAction SilentlyContinue|Where-Object {$_.SessionId -eq $session}).Count -ge 1) 'DeviceJournal owner desktop session missing'
  Assert ($ExpectedSourceSha -cmatch '^[a-f0-9]{40}$' -and $PriorSourceSha -cmatch '^[a-f0-9]{40}$' -and $PriorSourceSha -ne $ExpectedSourceSha) 'DeviceJournal requires distinct full source pins'
  foreach($hash in @($ExpectedJournalSha256,$ExpectedUnpackedSha256,$ExpectedStageProofSha256,$ExpectedCloneProofSha256)){
    Assert ($hash -cmatch '^[a-f0-9]{64}$') 'DeviceJournal requires complete journal/artifact/proof hash pins'
  }
  Assert ($ExpectedArtifactId -gt 0 -and $ExpectedArtifactRunId -gt 0) 'DeviceJournal artifact identity missing'
  foreach($value in @($CandidateInstallRoot,$PriorInstallRoot,$OwnerProfileRoot,$PrivateRoot,$JournalPython)){
    Assert ($value -match '^[A-Za-z]:\\' -and $value -notmatch '["\r\n]' -and [IO.Path]::GetFullPath($value).TrimEnd('\').Length -gt 3) 'DeviceJournal explicit local roots required'
  }
  $script:candidate=[IO.Path]::GetFullPath($CandidateInstallRoot).TrimEnd('\')
  $script:prior=[IO.Path]::GetFullPath($PriorInstallRoot).TrimEnd('\')
  $script:owner=[IO.Path]::GetFullPath($OwnerProfileRoot).TrimEnd('\')
  Assert ($owner -notmatch '(?i)(^|[\\/_-])(smoke|clone|synthetic)([\\/_-]|$)' -and !(IsWithin $owner $env:TEMP)) 'Disposable/smoke profile cannot be the owner'
  $roots=@($candidate,$prior,$owner,[IO.Path]::GetFullPath($PrivateRoot).TrimEnd('\'))
  for($i=0;$i -lt $roots.Count;$i++){for($j=$i+1;$j -lt $roots.Count;$j++){
    Assert (!($roots[$i].Equals($roots[$j],[StringComparison]::OrdinalIgnoreCase)) -and !(IsWithin $roots[$i] $roots[$j]) -and !(IsWithin $roots[$j] $roots[$i])) 'DeviceJournal roots overlap'
  }}
}
function DeviceLaunchArgs([string]$Source){
  Assert ($Source -cmatch '^[a-f0-9]{40}$') 'Device launch source invalid'
  return '--user-data-dir="'+$owner+'" --nexus-installed-source='+$Source
}
function StartDeviceGui([string]$InstallRoot,[string]$Source){
  Assert ($InstallRoot -in @($candidate,$prior)) 'Unbound device launch root'
  $bound=if($InstallRoot -eq $candidate){$ExpectedSourceSha}else{$PriorSourceSha}
  $null=DevicePlain (Join-Path $InstallRoot 'NEXUS Personal Pro.exe')
  Assert ($Source -ceq $bound -and (Get-Content -LiteralPath (Join-Path $InstallRoot 'resources\source-sha.txt') -Raw).Trim() -ceq $bound) 'Device launch installation/source mismatch'
  $env:RUNNER_TRACKING_ID=$null
  $null=Start-Process -FilePath (Join-Path $InstallRoot 'NEXUS Personal Pro.exe') -ArgumentList (DeviceLaunchArgs $Source)
}
function DeviceVerifierModule {
  if($script:DeviceVerifierRoot -and (Test-Path (Join-Path $script:DeviceVerifierRoot 'paper_event_store.py'))){return $script:DeviceVerifierRoot}
  $seed=Join-Path $candidate 'resources\nexus-source-seed.git'
  $null=DevicePlain $seed
  Assert ((Get-Content -LiteralPath (Join-Path $candidate 'resources\source-sha.txt') -Raw).Trim() -ceq $ExpectedSourceSha) 'Device verifier package source mismatch'
  $work=Join-Path $env:TEMP ('nexus-device-journal-verifier-'+[guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Path $work|Out-Null
  $zip=Join-Path $work 'verifier.zip'
  & git --git-dir="$seed" archive --format=zip --output="$zip" $ExpectedSourceSha paper_event_store.py
  Assert ($LASTEXITCODE -eq 0 -and (Test-Path $zip -PathType Leaf)) 'Exact-source verifier extraction failed'
  Expand-Archive -LiteralPath $zip -DestinationPath $work
  $null=DevicePlain (Join-Path $work 'paper_event_store.py')
  $script:DeviceVerifierRoot=$work
  return $work
}
function DeviceReplay([string]$Root) {
  $journal=PaperPath $Root
  $null=DevicePlain $journal
  $null=DevicePlain $JournalPython
  $module=DeviceVerifierModule
  $code=@'
import hashlib,json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from paper_event_store import replay
path=Path(sys.argv[2])
if not 0<path.stat().st_size<=100_000_000: raise ValueError('journal size outside bound')
raw=path.read_bytes()
events=[json.loads(line) for line in raw.decode('utf-8').splitlines()]
result=replay(events); state=result.state
if result.applied_events<2 or state.aggregate_id is None: raise ValueError('existing account required')
print(json.dumps({'journal_sha256':hashlib.sha256(raw).hexdigest(),'aggregate_id':state.aggregate_id,'event_count':result.applied_events,'head_event_digest':state.last_event_digest,'cash':str(state.cash),'equity':str(state.equity),'realized_pnl':str(state.realized_pnl),'unrealized_pnl':str(state.unrealized_pnl),'position_count':len(state.positions),'session_open':state.session_open,'kill_switch_enabled':state.kill_switch_enabled,'paper_only':True,'live_trading_authority':False},separators=(',',':')))
'@
  $raw=& $JournalPython -c $code $module $journal
  Assert ($LASTEXITCODE -eq 0 -and $raw) 'Device journal event chain/replay failed'
  return ($raw|ConvertFrom-Json)
}
function AssertDeviceJournalPin([string]$Root){
  $r=DeviceReplay $Root
  Assert ($r.journal_sha256 -ceq $ExpectedJournalSha256) 'Device journal changed from pinned baseline; never reset or replay it'
  return $r
}
function AssertDeviceApiAccount([object]$Paper,[object]$Baseline){
  Assert ($Paper.paper_only -eq $true -and $Paper.live_trading_authority -eq $false -and $Paper.active -eq $true) 'Device API authority failed'
  $a=$Paper.account
  Assert ($a.aggregate_id -ceq $Baseline.aggregate_id -and [long]$Paper.event_count -eq [long]$Baseline.event_count -and $Paper.head_event_digest -ceq $Baseline.head_event_digest) 'Device API journal identity/count/head mismatch'
  foreach($field in @('cash','equity','realized_pnl','unrealized_pnl')){Assert ([decimal]$a.$field -eq [decimal]$Baseline.$field) 'Device API financial baseline mismatch'}
  Assert (@($a.positions).Count -eq [int]$Baseline.position_count -and $a.session_open -eq $Baseline.session_open -and $a.kill_switch_enabled -eq $Baseline.kill_switch_enabled) 'Device API account state mismatch'
}
function AssertDeviceRunningProfile([object]$Gui) {
  if(!('NexusDeviceActivation.Native' -as [type])){
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace NexusDeviceActivation {
 public static class Native {
  [DllImport("kernel32.dll",SetLastError=true)] static extern IntPtr OpenProcess(uint a,bool i,uint p);
  [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
  [DllImport("ntdll.dll")] static extern int NtQueryInformationProcess(IntPtr h,int c,IntPtr p,int l,out int r);
  [DllImport("shell32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern IntPtr CommandLineToArgvW(string c,out int n);
  [DllImport("kernel32.dll")] static extern IntPtr LocalFree(IntPtr p);
  [StructLayout(LayoutKind.Sequential)] struct US { public ushort Length; public ushort MaximumLength; public IntPtr Buffer; }
  public static string[] Args(uint pid) {
   IntPtr h=OpenProcess(0x1000,false,pid),mem=IntPtr.Zero,argv=IntPtr.Zero;
   if(h==IntPtr.Zero)throw new Exception("Exact owner command line unavailable");
   try { int size; NtQueryInformationProcess(h,60,IntPtr.Zero,0,out size);
    if(size<8||size>131072)throw new Exception("Command line outside bound");
    mem=Marshal.AllocHGlobal(size); int needed;
    if(NtQueryInformationProcess(h,60,mem,size,out needed)!=0)throw new Exception("Command line query rejected");
    US text=(US)Marshal.PtrToStructure(mem,typeof(US));
    string command=Marshal.PtrToStringUni(text.Buffer,text.Length/2); int n;
    argv=CommandLineToArgvW(command,out n);
    if(argv==IntPtr.Zero||n<1||n>128)throw new Exception("Invalid exact owner arguments");
    string[] result=new string[n];for(int i=0;i<n;i++)result[i]=Marshal.PtrToStringUni(Marshal.ReadIntPtr(argv,i*IntPtr.Size));return result;
   } finally { if(argv!=IntPtr.Zero)LocalFree(argv);if(mem!=IntPtr.Zero)Marshal.FreeHGlobal(mem);CloseHandle(h); }
  }
 }
}
'@
  }
  $argv=@([NexusDeviceActivation.Native]::Args([uint32]$Gui.Id));$profiles=@()
  for($i=1;$i -lt $argv.Count;$i++){
    Assert ($argv[$i] -notmatch '(?i)^--nexus-(install|clone)-smoke(?:=|$)') 'Smoke/clone GUI cannot become owner'
    if($argv[$i] -match '(?i)^--user-data-dir='){$profiles+=@($argv[$i].Substring(16))}
    elseif($argv[$i] -ieq '--user-data-dir'){Assert ($i+1 -lt $argv.Count) 'Owner profile argument missing';$i++;$profiles+=@($argv[$i])}
  }
  Assert ($profiles.Count -eq 1 -and [IO.Path]::GetFullPath($profiles[0]).TrimEnd('\').Equals($owner,[StringComparison]::OrdinalIgnoreCase)) 'Actual running GUI profile differs from pinned owner'
}
function DeviceHealth([string]$Expected,[int]$Timeout,[string]$InstallRoot) {
  $end=[DateTime]::UtcNow.AddSeconds($Timeout)
  do {try{
    $super=JsonFile (Join-Path $owner 'product-data\supervisor-state.json')
    Assert ($super.status -eq 'healthy' -and $super.source_sha -ceq $Expected -and $super.live_trading_authority -eq $false) 'Device supervisor not exact/healthy'
    $uri=[uri]$super.origin
    Assert ($uri.Scheme -eq 'http' -and $uri.Host -in @('127.0.0.1','localhost','::1') -and $uri.Port -ge 1024 -and $uri.AbsolutePath -eq '/' -and !$uri.Query -and !$uri.Fragment -and !$uri.UserInfo) 'Untrusted gateway origin'
    $gui=@(ExactProcs $InstallRoot|Where-Object {$_.ProcessName -eq 'NEXUS Personal Pro' -and $_.MainWindowHandle -ne 0})
    Assert ($gui.Count -eq 1) 'Device requires exactly one visible bound GUI'
    AssertDeviceRunningProfile $gui[0]
    $listeners=@(netstat -ano -p tcp | Where-Object {$_ -match 'LISTENING' -and $_ -match (':'+$uri.Port+'\s')})
    $bound=@($listeners|ForEach-Object { $parts=$_.Trim() -split '\s+'; if($parts.Count -eq 5){$proc=Get-Process -Id ([int]$parts[4]) -ErrorAction Stop;if($proc.ProcessName -eq 'nexus-product-server' -and $proc.Path -and (IsWithin $proc.Path $InstallRoot)){$proc}}})
    Assert ($bound.Count -ge 1) 'Device gateway is not served by exact installed sidecar'
    $base=$uri.AbsoluteUri.TrimEnd('/')
    $paper=Invoke-RestMethod ($base+'/api/product/paper') -TimeoutSec 5
    $live=Invoke-RestMethod ($base+'/api/product/live') -TimeoutSec 5
    $build=Invoke-RestMethod ($base+'/api/product/build-evidence') -TimeoutSec 5
    $baseline=AssertDeviceJournalPin $owner
    AssertDeviceApiAccount $paper $baseline
    Assert ($live.live_trading_authority -eq $false -and $live.orders_allowed -eq $false -and $build.source_sha -ceq $Expected -and $build.exact_source -eq $true) 'Device source/Live safety contract failed'
    return $baseline
  }catch{if($_.Exception.Message -match 'Untrusted gateway|Actual running GUI profile|journal changed|financial baseline|API journal|authority failed|Smoke/clone'){throw}}
    Start-Sleep -Seconds 2
  }while([DateTime]::UtcNow -lt $end)
  throw 'DeviceJournal exact GUI/API health did not become ready within bound'
}
function DeviceBinding([switch]$Transaction) {
  $binding=[ordered]@{account_surface='DeviceJournal';host='DESKTOP-1R1081M';owner_profile=$owner;prior_install_root=$prior;prior_source_sha=$PriorSourceSha;candidate_install_root=$candidate;candidate_source_sha=$ExpectedSourceSha;journal_sha256=$ExpectedJournalSha256;artifact_id=$ExpectedArtifactId;artifact_run_id=$ExpectedArtifactRunId;unpacked_sha256=$ExpectedUnpackedSha256;stage_proof_sha256=$ExpectedStageProofSha256}
  # The clone cannot contain its own digest. Only the private transaction binds all proofs.
  if($Transaction){$binding.clone_proof_sha256=$ExpectedCloneProofSha256;$binding.rehearsal_proof_sha256=$ExpectedRehearsalProofSha256}
  return $binding
}
function AssertDeviceBinding([object]$Value,[switch]$Transaction){
  $expected=DeviceBinding -Transaction:$Transaction
  foreach($key in $expected.Keys){Assert ([string]($Value.$key) -ceq [string]($expected[$key])) ('Device binding mismatch: '+$key)}
}
function AssertDeviceInstalledFiles([object]$Proof){
  Assert ($Proof.installed_files_verified_against_unpacked -eq $true -and $Proof.installed_files_unpacked_sha256 -ceq $ExpectedUnpackedSha256) 'Device clone files are not bound to verified unpacked artifact'
  $rows=@($Proof.installed_files)
  Assert ($rows.Count -ge 6 -and $rows.Count -lt 100000) 'Device installed-file manifest outside bound'
  $pins=@{}
  foreach($row in $rows){
    Assert ($row.rel -is [string] -and $row.rel -notmatch '(^[\\/]|[:"\r\n]|(^|[\\/])\.{1,2}([\\/]|$))' -and $row.rel -notmatch '\\\\|//' -and $row.rel -ne 'install-manifest.json' -and $row.sha -cmatch '^[a-f0-9]{64}$' -and [long]$row.bytes -ge 0 -and !$pins.ContainsKey($row.rel)) 'Unsafe/duplicate device installed-file entry'
    $pins[$row.rel]=$row
  }
  foreach($required in @('NEXUS Personal Pro.exe','resources\app.asar','resources\nexus-product-server\nexus-product-server.exe','resources\source-sha.txt','resources\build-evidence.json')){Assert ($pins.ContainsKey($required)) ('Device artifact file missing: '+$required)}
  Assert (@($pins.Keys|Where-Object {$_ -like 'resources\nexus-source-seed.git\*'}).Count -gt 0) 'Device artifact source seed missing'
  $current=@(ProfileFiles $candidate|Where-Object {$_.rel -ne 'install-manifest.json'})
  Assert ($current.Count -eq $rows.Count) 'Device installed-file inventory changed since verified clone'
  foreach($entry in $current){Assert ($pins.ContainsKey($entry.rel) -and $pins[$entry.rel].sha -ceq $entry.sha -and [long]$pins[$entry.rel].bytes -eq $entry.bytes) ('Device installed artifact bytes changed: '+$entry.rel)}
}
function AssertDeviceLinkPath([string]$Path){
  $full=[IO.Path]::GetFullPath($Path)
  Assert ($Path -ceq $full -and $full -notmatch '["\r\n]') 'Untrusted device shortcut path'
  $desktop=Join-Path ([Environment]::GetFolderPath('Desktop')) 'NEXUS Personal Pro.lnk'
  $programs=Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
  $startup=[Environment]::GetFolderPath('Startup')
  $underMenu=(IsWithin $full $programs) -or (IsWithin $full $startup)
  Assert ($full.Equals($desktop,[StringComparison]::OrdinalIgnoreCase) -or ($underMenu -and (Split-Path -Leaf $full) -match '^NEXUS Personal Pro[^\\/:]*\.lnk$' -and $full -notmatch '\.nexus-(new|rollback-prior)\.lnk$')) 'Shortcut is outside the owner GUI inventory'
  $null=DevicePlain (Split-Path -Parent $full)
  if(Test-Path -LiteralPath $full){$null=DevicePlain $full}
}
function AssertDeviceGuiLinks([object]$Proof){
  $paths=@(Links);$rows=@($Proof.gui_links)
  Assert ($rows.Count -eq $paths.Count -and $rows.Count -ge 1 -and $rows.Count -le 50) 'Device clone GUI shortcut inventory differs'
  $shell=New-Object -ComObject WScript.Shell
  $shortArgs=(DeviceLaunchArgs $PriorSourceSha).Replace($PriorSourceSha,$PriorSourceSha.Substring(0,8))
  for($i=0;$i -lt $paths.Count;$i++){
    $p=$paths[$i];$row=$rows[$i];AssertDeviceLinkPath $p
    Assert ($row.path -ceq $p -and $row.sha -cmatch '^[a-f0-9]{64}$' -and (Hash $p) -ceq $row.sha) 'Device shortcut bytes/inventory differ from clone proof'
    $link=$shell.CreateShortcut($p)
    Assert ($link.TargetPath.Equals((Join-Path $prior 'NEXUS Personal Pro.exe'),[StringComparison]::OrdinalIgnoreCase) -and $link.TargetPath -ceq $row.target -and $link.Arguments -ceq $row.arguments) 'Device shortcut target/arguments differ from clone proof'
    Assert ($link.Arguments -ceq (DeviceLaunchArgs $PriorSourceSha) -or ($p -cne $paths[0] -and $link.Arguments -ceq $shortArgs)) 'Device shortcut does not retain the exact prior owner profile/source'
  }
  return $rows
}
function CheckDeviceStage {
  foreach($path in @($candidate,$prior,$owner,$PrivateRoot,$StageProof,$CloneProof)){ $null=DevicePlain $path }
  Assert ((Hash $StageProof) -ceq $ExpectedStageProofSha256 -and (Hash $CloneProof) -ceq $ExpectedCloneProofSha256) 'Device stage/clone proof hash mismatch'
  $a=JsonFile $StageProof;$b=JsonFile $CloneProof;$m=JsonFile (Join-Path $candidate 'install-manifest.json')
  Assert ($a.decision -eq 'PASS' -and $a.source_sha -ceq $ExpectedSourceSha -and [long]$a.artifact_id -eq $ExpectedArtifactId -and [long]$a.artifact_run_id -eq $ExpectedArtifactRunId -and $a.package.unpacked_sha256 -ceq $ExpectedUnpackedSha256 -and $a.final_launch.status -eq 'STAGED_ONLY_OWNER_PRESERVED') 'Device official stage artifact not exact'
  Assert ($a.repository -ceq $expectedRepo -and $a.target.computer_name -eq 'DESKTOP-1R1081M' -and $a.target.runner_name -ceq 'NEXUS-LOCAL-RUNNER' -and $a.target.owner_user_context -eq $true -and $a.target.interactive_desktop -eq $true -and $a.target.elevated -eq $false -and $a.package.checksum_manifest_verified -eq $true -and $a.smoke.visible_window_observed -eq $true -and $a.smoke.supervisor_healthy -eq $true -and $a.smoke.live_orders_allowed -eq $false) 'Device stage smoke/host/owner gate failed'
  Assert ($b.decision -eq 'PASS_NO_OWNER_ACTIVATION' -and $b.source_sha -ceq $ExpectedSourceSha -and $b.clone_visible_gui -eq $true -and $b.old_visible_gui_preserved -eq $true) 'Device clone physical proof failed'
  AssertDeviceBinding $b.owner_binding
  AssertDeviceInstalledFiles $b
  Assert ($m.source_sha -ceq $ExpectedSourceSha -and [long]$m.artifact_id -eq $ExpectedArtifactId -and [long]$m.artifact_run_id -eq $ExpectedArtifactRunId -and $m.unpacked_sha256 -ceq $ExpectedUnpackedSha256 -and $m.paper_only -eq $true -and $m.live_trading_authority -eq $false) 'Device candidate installation binding failed'
  Assert ((Get-Content -LiteralPath (Join-Path $prior 'resources\source-sha.txt') -Raw).Trim() -ceq $PriorSourceSha) 'Device prior source mismatch'
  Assert (@(ExactProcs $candidate).Count -eq 0) 'Candidate must not be running at cutover'
  $acl=Get-Acl -LiteralPath $PrivateRoot
  Assert (@($acl.Access|Where-Object {$_.AccessControlType -eq 'Allow' -and $_.IdentityReference.Value -match 'Everyone|BUILTIN\\Users|Authenticated Users'}).Count -eq 0) 'Private ACL too broad'
  # Bind the candidate to the live default branch; CI on a feature head is not main acceptance.
  $main=Invoke-RestMethod 'https://api.github.com/repos/saladinayoubi1/lbank-research-automation/branches/main' -TimeoutSec 15
  Assert ($main.commit.sha -ceq $ExpectedSourceSha) 'Device candidate is not current main'
  $baseline=DeviceHealth $PriorSourceSha 20 $prior
  Assert ($b.owner_journal.event_count -eq $baseline.event_count -and $b.owner_journal.head_event_digest -ceq $baseline.head_event_digest -and $b.owner_journal.aggregate_id -ceq $baseline.aggregate_id -and [decimal]$b.owner_journal.cash -eq [decimal]$baseline.cash -and [decimal]$b.owner_journal.equity -eq [decimal]$baseline.equity -and $b.owner_journal.position_count -eq $baseline.position_count) 'Device clone journal/baseline mismatch'
  $null=AssertDeviceGuiLinks $b
  $desktop=Join-Path ([Environment]::GetFolderPath('Desktop')) 'NEXUS Personal Pro.lnk'
  $shortcut=(New-Object -ComObject WScript.Shell).CreateShortcut($desktop)
  Assert ($shortcut.TargetPath.Equals((Join-Path $prior 'NEXUS Personal Pro.exe'),[StringComparison]::OrdinalIgnoreCase) -and $shortcut.Arguments -ceq (DeviceLaunchArgs $PriorSourceSha)) 'Canonical device shortcut/profile changed'
  $script:DeviceBaseline=$baseline
  return $baseline
}
function ValidPaper([string]$Root) {
  if($AccountSurface -eq 'DeviceJournal'){return AssertDeviceJournalPin $Root}
  $p=PaperPath $Root
  $j=JsonFile $p
  Assert ($j.read_only -eq $true -and $j.live_trading_authority -eq $false) 'Owner journal is not read-only and Live-locked'
  Assert ([decimal]$j.account.initial_balance -eq 500) 'Unexpected Paper initial balance'
  return $j
}
function CheckStage {
  if($AccountSurface -eq 'DeviceJournal'){return CheckDeviceStage}
  Assert ($ExpectedSourceSha -match '^[a-f0-9]{40}$') 'Invalid source SHA'
  Assert ((Test-Path -LiteralPath $PrivateRoot -PathType Container) -and (Test-Path $StageProof) -and (Test-Path $CloneProof)) 'Private durability or stage evidence missing'
  $acl=Get-Acl -LiteralPath $PrivateRoot
  Assert (@($acl.Access|Where-Object {$_.AccessControlType -eq 'Allow' -and $_.IdentityReference.Value -match 'Everyone|BUILTIN\\Users|Authenticated Users'}).Count -eq 0) 'Private ACL too broad'
  $a=JsonFile $StageProof;$b=JsonFile $CloneProof
  Assert ($a.decision -eq 'PASS' -and $a.source_sha -eq $ExpectedSourceSha -and $a.final_launch.status -eq 'STAGED_ONLY_OWNER_PRESERVED') 'Official stage proof not exact'
  Assert ($a.smoke.visible_window_observed -eq $true -and $a.smoke.supervisor_healthy -eq $true -and $a.smoke.live_orders_allowed -eq $false) 'Official stage smoke incomplete'
  Assert ($b.decision -eq 'PASS_NO_OWNER_ACTIVATION' -and $b.source_sha -eq $ExpectedSourceSha -and $b.clone_visible_gui -eq $true -and $b.old_visible_gui_preserved -eq $true) 'Real-profile clone proof not exact'
  $m=JsonFile (Join-Path $candidate 'install-manifest.json')
  Assert ($m.source_sha -eq $ExpectedSourceSha -and $m.paper_only -eq $true -and $m.live_trading_authority -eq $false) 'Candidate manifest untrusted'
  Assert ((Test-Path (Join-Path $prior 'NEXUS Personal Pro.exe') -PathType Leaf) -and (Test-Path (Join-Path $candidate 'NEXUS Personal Pro.exe') -PathType Leaf)) 'Old or candidate executable missing'
  Assert (@(ExactProcs $candidate).Count -eq 0) 'Candidate must not be running at cutover'
  $old=@(ExactProcs $prior)
  Assert (@($old|Where-Object {$_.ProcessName -eq 'NEXUS Personal Pro' -and $_.MainWindowHandle -ne 0}).Count -eq 1) 'Exactly one visible prior GUI required'
  Assert ($old.Count -ge 2 -and $old.Count -le 15) 'Unexpected prior process population'
  $null=ValidPaper $owner # read from owner root
  $super=JsonFile (Join-Path $owner 'product-data\supervisor-state.json')
  Assert ($super.status -eq 'healthy' -and $super.live_trading_authority -eq $false) 'Current owner must be healthy and Live-locked'
  $sw=New-Object -ComObject WScript.Shell
  $shortcut=Join-Path ([Environment]::GetFolderPath('Desktop')) 'NEXUS Personal Pro 5.1.0.lnk'
  Assert ((Test-Path $shortcut) -and ($sw.CreateShortcut($shortcut).TargetPath).Equals((Join-Path $prior 'NEXUS Personal Pro.exe'),[StringComparison]::OrdinalIgnoreCase)) 'Owner desktop shortcut changed'
  return $true
}
function Links {
  if($AccountSurface -eq 'DeviceJournal'){
    $paths=@((Join-Path ([Environment]::GetFolderPath('Desktop')) 'NEXUS Personal Pro.lnk'))
    foreach($dir in @((Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'),[Environment]::GetFolderPath('Startup'))){
      if(Test-Path -LiteralPath $dir){$paths+=@(Get-ChildItem -LiteralPath $dir -File -Filter 'NEXUS Personal Pro*.lnk' -Recurse|Select-Object -ExpandProperty FullName)}
    }
    $paths=@($paths|Select-Object -Unique)
    Assert ($paths.Count -ge 1 -and $paths.Count -le 50) 'Device GUI shortcut inventory outside bound'
    return $paths
  }
  @((Join-Path ([Environment]::GetFolderPath('Desktop')) 'NEXUS Personal Pro 5.1.0.lnk'),
    (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\NEXUS Personal Pro 5.1.0.lnk'),
    (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\NEXUS Personal Pro.lnk'),
    (Join-Path ([Environment]::GetFolderPath('Startup')) 'NEXUS Personal Pro.lnk'))
}
function BackupLinks([string]$Dir) {
  $result=@()
  foreach($p in @(Links)){ $i=$result.Count;$copy=Join-Path $Dir "link-$i.lnk"
    $exists=Test-Path -LiteralPath $p -PathType Leaf
    if($exists){Copy-Item -LiteralPath $p -Destination $copy -ErrorAction Stop}
    $result+=@{path=$p;existed=$exists;sha=if($exists){Hash $p}else{''};copy=$copy}
  }
  return $result
}
function RestoreLinks([object[]]$LinksData) {
  foreach($x in $LinksData) {
    if($x.existed){Assert ((Hash $x.copy) -eq $x.sha) 'Shortcut backup digest failed';Copy-Item -LiteralPath $x.copy -Destination $x.path -Force}
    elseif(Test-Path $x.path){Remove-Item -LiteralPath $x.path -Force}
    foreach($suffix in @('.nexus-new.lnk','.nexus-rollback-prior.lnk')){
      $orphan="$($x.path)$suffix"
      if(Test-Path -LiteralPath $orphan){Remove-Item -LiteralPath $orphan -Force -ErrorAction Stop}
    }
  }
}
function Health([string]$Expected,[int]$Timeout=425,[string]$InstallRoot=$candidate){
  if($AccountSurface -eq 'DeviceJournal'){return DeviceHealth $Expected $Timeout $InstallRoot}
  $file=Join-Path $owner 'product-data\supervisor-state.json';$end=[DateTime]::UtcNow.AddSeconds($Timeout)
  do {
    try {
      $s=JsonFile $file
      if($s.status -eq 'healthy' -and $s.source_sha -eq $Expected -and $s.live_trading_authority -eq $false){
        $u=[uri]$s.origin
        Assert ($u.Host -in @('127.0.0.1','localhost','::1')) 'Untrusted gateway origin'
        $url=$u.AbsoluteUri.TrimEnd('/')
        $p=Invoke-RestMethod "$url/api/product/paper" -TimeoutSec 5
        $live=Invoke-RestMethod "$url/api/product/live" -TimeoutSec 5
        $build=Invoke-RestMethod "$url/api/product/build-evidence" -TimeoutSec 5
        $st=Invoke-RestMethod "$url/api/product/strategies/evidence" -TimeoutSec 5
        $ov=Invoke-RestMethod "$url/api/product/overview" -TimeoutSec 5
        $mission=Invoke-RestMethod "$url/api/product/mission/full" -TimeoutSec 5
        Assert ($p.paper_only -eq $true -and $live.live_trading_authority -eq $false -and $live.orders_allowed -eq $false) 'Paper/Live safety contract failed'
        Assert ($build.source_sha -eq $Expected -and $build.exact_source -eq $true -and $st.paper_only -eq $true -and $st.profitability_claim -eq $false) 'Source/strategy contract failed'
        Assert ($ov.capabilities.deterministic_risk -eq 'final_paper_authority' -and $mission.live_trading_authority -eq $false) 'Risk/Mission authority failed'
        $null=ValidPaper $owner
        $win=@(ExactProcs $InstallRoot|Where-Object {$_.ProcessName -eq 'NEXUS Personal Pro' -and $_.MainWindowHandle -ne 0})
        if($win.Count -eq 1){return $true}
      }
    }catch { if($_.Exception.Message -match 'Untrusted gateway|safety contract|authority failed'){throw} }
    Start-Sleep -Seconds 5
  }while([DateTime]::UtcNow -lt $end)
  throw 'Exact owner GUI or health endpoint did not become ready in bounded window'
}
function RestoreProfile([string]$Dir){
  $meta=JsonFile (Join-Path $Dir 'transaction.json');$backup=Join-Path $Dir 'profile'
  foreach($x in @($meta.files)) {Assert ((Hash (Join-Path $backup $x.rel)) -eq $x.sha) 'Owner profile backup checksum failed'}
  if(Test-Path $owner){$quarantine=Join-Path $Dir 'failed-candidate-profile';if(!(Test-Path $quarantine)){Copy-Item -LiteralPath $owner -Destination $quarantine -Recurse}}
  if(Test-Path $owner){Remove-Item -LiteralPath $owner -Recurse -Force}
  Copy-Item -LiteralPath $backup -Destination $owner -Recurse
  foreach($x in @($meta.files)){Assert ((Hash (Join-Path $owner $x.rel)) -eq $x.sha) 'Owner profile rollback checksum failed'}
}
function Finish-Rollback([object]$Transaction,[string]$Dir){
  $Transaction.status='ROLLED_BACK'
  $Transaction|Add-Member -NotePropertyName rolled_back_at -NotePropertyValue ([DateTime]::UtcNow.ToString('o')) -Force
  Write-Json (Join-Path $Dir 'transaction.json') $Transaction
}
function Rollback([string]$Dir){
  $t=JsonFile (Join-Path $Dir 'transaction.json')
  if($t.status -in @('COMMITTED','ROLLED_BACK')){return}
  if($t.status -eq 'RECOVERY_NEEDS_REVIEW'){throw 'Prior recovery needs independent owner review; will not overwrite newer Paper'}
  # A previous rollback may already have restarted the old GUI and generated
  # newer Paper events. The timed watchdog must NEVER overwrite those events.
  $existingOld=@(ExactProcs $prior)
  $existingNew=@(ExactProcs $candidate)
  # Stop only the exact candidate before assessing an unexpectedly revived old owner.
  # A healthy old GUI may already have added newer Paper events: never stop it
  # or replay an older snapshot merely because a candidate also lingered.
  if($existingNew.Count){
    Stop-Exact $candidate 4
    $existingNew=@(ExactProcs $candidate)
  }
  $existingOld=@(ExactProcs $prior)
  $oldWindow=@($existingOld|Where-Object {$_.ProcessName -eq 'NEXUS Personal Pro' -and $_.MainWindowHandle -ne 0})
  if($t.status -in @('STARTED','BACKED_UP','ACTIVATING') -and !$existingNew.Count -and $oldWindow.Count -eq 1){
    $oldSource=(Get-Content -LiteralPath (Join-Path $prior 'resources\source-sha.txt') -Raw -ErrorAction Stop).Trim()
    $state=JsonFile (Join-Path $owner 'product-data\supervisor-state.json')
    if($state.status -eq 'healthy' -and $state.source_sha -eq $oldSource -and $state.live_trading_authority -eq $false){
      $null=ValidPaper $owner
      if($t.links){RestoreLinks @($t.links)}
      if($t.sync_was_enabled -eq $true){
        $service=New-Object -ComObject Schedule.Service;$service.Connect()
        $service.GetFolder('\').GetTask($syncTask).Enabled=$true
      }
      $currentJournal=PaperPath $owner
      $newerCopy=Join-Path $Dir 'newer-paper-post-recovery.json'
      $captured=$false
      for($attempt=0;$attempt -lt 5;$attempt++){
        $first=Hash $currentJournal
        Copy-Item -LiteralPath $currentJournal -Destination $newerCopy -Force
        if((Hash $currentJournal) -eq $first -and (Hash $newerCopy) -eq $first){$captured=$true;break}
        Start-Sleep -Milliseconds 250
      }
      if(!$captured){
        $t.status='RECOVERY_NEEDS_REVIEW';Write-Json (Join-Path $Dir 'transaction.json') $t
        throw 'Progressing Paper journal could not be captured consistently; never replay the old snapshot'
      }
      Finish-Rollback $t $Dir
      return
    }
  }
  # If old is already running but not yet healthy, do not destroy its possible
  # new writes. An operator can diagnose instead of replaying stale account data.
  if($t.status -in @('STARTED','BACKED_UP','ACTIVATING') -and !$existingNew.Count -and $existingOld.Count -gt 0){
    $t.status='RECOVERY_NEEDS_REVIEW';Write-Json (Join-Path $Dir 'transaction.json') $t
    throw 'Existing previous GUI is starting: refusing repeated destructive rollback'
  }
  Stop-Exact $candidate 4
  if(@(ExactProcs $prior).Count){Stop-Exact $prior 3}
  if($t.status -in @('BACKED_UP','ACTIVATING') -and (Test-Path (Join-Path $Dir 'profile'))){
    $savedPaper=PaperPath (Join-Path $Dir 'profile')
    $currentPaper=PaperPath $owner
    if((Test-Path $savedPaper) -and (Test-Path $currentPaper) -and ((Hash $currentPaper) -ne (Hash $savedPaper))){
      $copy=Join-Path $Dir 'unreplayed-current-paper.json'
      $before=Hash $currentPaper
      Copy-Item -LiteralPath $currentPaper -Destination $copy -Force
      $t.status='RECOVERY_NEEDS_REVIEW';Write-Json (Join-Path $Dir 'transaction.json') $t
      Assert ((Hash $currentPaper) -eq $before -and (Hash $copy) -eq $before) 'Paper journal changed during safety capture'
      throw 'Current Paper differs from activation snapshot: newer events quarantined; obsolete rollback prohibited'
    }
    RestoreProfile $Dir
  }
  if($t.links){RestoreLinks @($t.links)}
  $env:RUNNER_TRACKING_ID=$null
  $null=Start-Process -FilePath (Join-Path $prior 'NEXUS Personal Pro.exe')
  $oldSource=(Get-Content -LiteralPath (Join-Path $prior 'resources\source-sha.txt') -Raw -ErrorAction Stop).Trim()
  Assert ($oldSource -match '^[0-9a-f]{40}$') 'Previous source binding is invalid'
  try{$null=Health $oldSource 425 $prior}
  catch {
    $t.status='RECOVERY_NEEDS_REVIEW';Write-Json (Join-Path $Dir 'transaction.json') $t
    throw 'Previous GUI needs independent recovery review; refusing future automatic overwrite'
  }
  if($t.sync_was_enabled -eq $true){
    $service=New-Object -ComObject Schedule.Service;$service.Connect()
    $service.GetFolder('\').GetTask($syncTask).Enabled=$true
  }
  Finish-Rollback $t $Dir
}
function Rehearse {
  $r=Join-Path $env:TEMP ('nexus-activation-synthetic-'+[guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Force -Path $r|Out-Null
  $actualOwner=$script:owner
  try{
    $script:owner=Join-Path $r 'synthetic-owner'
    $work=Join-Path $script:owner 'product-data\\shared_paper'
    New-Item -ItemType Directory -Path $work -Force|Out-Null
    $journal=Join-Path $work 'terminal.json'
    [IO.File]::WriteAllText($journal,'{"read_only":true,"live_trading_authority":false,"account":{"initial_balance":500}}')
    $orig=Hash $journal
    $files=@(ProfileFiles $script:owner)
    $txn=Join-Path $r 'transaction';New-Item -ItemType Directory $txn|Out-Null
    $b=Join-Path $txn 'profile';Copy-Item $script:owner $b -Recurse
    Assert ((Hash (Join-Path $b 'product-data\\shared_paper\\terminal.json')) -eq $orig) 'Synthetic snapshot copy failed'
    $link=Join-Path $r 'synthetic-shortcut.lnk';$linkBackup=Join-Path $r 'old-link.lnk'
    [IO.File]::WriteAllText($link,'old-executable');Copy-Item $link $linkBackup
    $linkMeta=@{path=$link;existed=$true;copy=$linkBackup;sha=Hash $link}
    $meta=[ordered]@{status='BACKED_UP';files=$files;links=@($linkMeta)}
    Write-Json (Join-Path $txn 'transaction.json') $meta
    [IO.File]::WriteAllText($journal,'{"read_only":true,"live_trading_authority":false,"account":{"initial_balance":1}}')
    [IO.File]::WriteAllText($link,'failed-new-executable')
    RestoreProfile $txn
    RestoreLinks @($linkMeta)
    Assert ((Hash $journal) -eq $orig -and (Hash $link) -eq $linkMeta.sha) 'Synthetic profile/shortcut rollback failed'
    $linkTemp="$link.nexus-new.lnk";$linkPrior="$link.nexus-rollback-prior.lnk"
    [IO.File]::WriteAllText($linkTemp,'synthetic-candidate-shortcut')
    [IO.File]::Replace($linkTemp,$link,$linkPrior)
    Assert ((Get-Content $link -Raw) -eq 'synthetic-candidate-shortcut') 'Atomic synthetic shortcut switch failed'
    Assert ((Hash $linkPrior) -eq $linkMeta.sha) 'Atomic shortcut prior backup was damaged'
    RestoreLinks @($linkMeta)
    Assert ((Hash $link) -eq $linkMeta.sha -and !(Test-Path $linkPrior)) 'Atomic shortcut rollback/cleanup failed'
    'SYNTHETIC_OWNER_ACTIVATION_REHEARSAL=PASS profile-copy, corruption detection, shortcut rollback; no real state'
    if($TestScheduler){
      $testName="NEXUS-Activation-REHEARSAL-$sourceShort"
      $service=New-Object -ComObject Schedule.Service;$service.Connect();$folder=$service.GetFolder('\')
      try{
        $d=$service.NewTask(0);$d.Principal.LogonType=3;$d.Principal.RunLevel=0
        $d.Principal.UserId=[Security.Principal.WindowsIdentity]::GetCurrent().Name
        $t=$d.Triggers.Create(1);$t.StartBoundary=[DateTime]::Now.AddMinutes(20).ToString('s')
        $a=$d.Actions.Create(0);$a.Path=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $a.Arguments='-NoProfile -NonInteractive -Command "exit 0"'
        $d.Settings.Enabled=$true
        $registered=$folder.RegisterTaskDefinition($testName,$d,6,$null,$null,3,$null)
        Assert ($registered.Enabled -eq $true) 'Owner COM watchdog registration rehearsal failed'
        'SYNTHETIC_OWNER_WATCHDOG_COM=PASS disposable task registered'
      }finally{try{$folder.DeleteTask($testName,0)}catch{}}
    }
  }finally{$script:owner=$actualOwner;Remove-Item -LiteralPath $r -Force -Recurse -ErrorAction SilentlyContinue}
}
function DeviceRecoveryArguments([string]$Dir) {
  $values=[ordered]@{AccountSurface='DeviceJournal';Mode='Recover';ExpectedSourceSha=$ExpectedSourceSha;CandidateInstallRoot=$candidate;PriorInstallRoot=$prior;PriorSourceSha=$PriorSourceSha;OwnerProfileRoot=$owner;ExpectedJournalSha256=$ExpectedJournalSha256;ExpectedArtifactId=$ExpectedArtifactId;ExpectedArtifactRunId=$ExpectedArtifactRunId;ExpectedUnpackedSha256=$ExpectedUnpackedSha256;StageProof=$StageProof;ExpectedStageProofSha256=$ExpectedStageProofSha256;CloneProof=$CloneProof;ExpectedCloneProofSha256=$ExpectedCloneProofSha256;PrivateRoot=$PrivateRoot;TransactionDir=$Dir;RehearsalProof=$RehearsalProof;ExpectedRehearsalProofSha256=$ExpectedRehearsalProofSha256;JournalPython=$JournalPython}
  $parts=@()
  foreach($key in $values.Keys){$value=[string]$values[$key];Assert ($value -notmatch '["\r\n]') 'Unsafe recovery argument';$parts+=@('-'+$key,'"'+$value+'"')}
  return $parts -join ' '
}
function DeviceSetReview([object]$Record,[string]$Dir,[string]$Reason) {
  $Record.status='RECOVERY_NEEDS_REVIEW';$Record|Add-Member -NotePropertyName recovery_reason -NotePropertyValue $Reason -Force
  Write-Json (Join-Path $Dir 'transaction.json') $Record
}
function DeviceCheckRecord([object]$Record,[string]$Dir) {
  AssertDeviceRehearsal
  $null=DevicePlain $Dir
  if(Test-Path -LiteralPath $owner){$null=DevicePlain $owner}
  if(Test-Path -LiteralPath (PaperPath $owner)){$null=DevicePlain (PaperPath $owner)}
  Assert (IsWithin $Dir (Join-Path $PrivateRoot 'activation-transactions')) 'Untrusted device transaction directory'
  Assert ($Record.schema -eq 'nexus.owner-device-journal-activation.v1') 'Device recovery schema mismatch'
  Assert ($Record.status -in @('STARTED','BACKED_UP','ACTIVATING','COMMITTED','ROLLED_BACK','RECOVERY_NEEDS_REVIEW')) 'Unknown device recovery status'
  AssertDeviceBinding $Record.binding -Transaction
  Assert ((Hash (Join-Path $Dir 'recovery.ps1')) -ceq $Record.recovery_script_sha256 -and $Record.recovery_script_sha256 -ceq (Hash $PSCommandPath)) 'Device recovery script hash mismatch'
  $null=DevicePlain $CloneProof;$null=DevicePlain $StageProof
  Assert ((Hash $CloneProof) -ceq $ExpectedCloneProofSha256 -and (Hash $StageProof) -ceq $ExpectedStageProofSha256) 'Device recovery proof pins changed'
  $proof=JsonFile $CloneProof;$expected=@($proof.gui_links);$inventory=@($Record.link_inventory);$links=@($Record.links)
  Assert ($inventory.Count -eq $expected.Count -and $inventory.Count -ge 1 -and $inventory.Count -le 50) 'Device recovery shortcut inventory mismatch'
  for($i=0;$i -lt $inventory.Count;$i++){
    AssertDeviceLinkPath $inventory[$i].path
    Assert ($inventory[$i].path -ceq $expected[$i].path -and $inventory[$i].sha -ceq $expected[$i].sha -and $inventory[$i].target -ceq $expected[$i].target -and $inventory[$i].arguments -ceq $expected[$i].arguments) 'Device recovery shortcut inventory is not pinned'
  }
  Assert (($Record.status -in @('STARTED','ROLLED_BACK','RECOVERY_NEEDS_REVIEW') -and $links.Count -eq 0) -or $links.Count -eq $inventory.Count) 'Device recovery backup inventory incomplete'
  for($i=0;$i -lt $links.Count;$i++){
    $entry=$links[$i];$copy=Join-Path $Dir ('link-'+$i+'.lnk')
    Assert ($entry.path -ceq $inventory[$i].path -and $entry.copy -ceq $copy -and $entry.existed -eq $true -and $entry.sha -ceq $inventory[$i].sha -and $entry.sha -cmatch '^[a-f0-9]{64}$') 'Untrusted device shortcut restoration entry'
    $null=DevicePlain $copy
    Assert ((Hash $copy) -ceq $entry.sha) 'Device shortcut backup bytes changed'
  }
}
function DeviceRecover([string]$Dir) {
  $txn=JsonFile (Join-Path $Dir 'transaction.json');DeviceCheckRecord $txn $Dir
  RecoverDeviceRecord $txn $Dir
}
function RecoverDeviceRecord([object]$txn,[string]$Dir) {
  if($txn.status -in @('COMMITTED','ROLLED_BACK')){return}
  Assert ($txn.status -ne 'RECOVERY_NEEDS_REVIEW') 'Device recovery previously fenced for review; no repeated mutation'
  # Retire only this candidate. A revived previous owner may already hold newer events.
  if(@(ExactProcs $candidate).Count){Stop-Exact $candidate 4}
  $journal=PaperPath $owner
  if(!(Test-Path -LiteralPath $journal -PathType Leaf) -or (Hash $journal) -cne $ExpectedJournalSha256){
    DeviceSetReview $txn $Dir 'Existing journal changed or disappeared; current bytes must never be replayed from backup'
    throw 'Device journal advanced/changed; recovery preserved current profile and requires review'
  }
  try{if($txn.links){RestoreLinks @($txn.links)}}catch{DeviceSetReview $txn $Dir 'Shortcut restoration failed; owner profile preserved';throw}
  # DeviceJournal recovery intentionally NEVER calls RestoreProfile or deletes an owner directory.
  # Even unchanged financial bytes do not authorize replacing newer cookies/preferences.
  if(@(ExactProcs $prior).Count -eq 0){StartDeviceGui $prior $PriorSourceSha}
  try{$null=DeviceHealth $PriorSourceSha 425 $prior}
  catch{DeviceSetReview $txn $Dir 'Previous GUI/profile requires independent recovery review';throw}
  $txn.status='ROLLED_BACK';$txn|Add-Member -NotePropertyName rolled_back_at -NotePropertyValue ([DateTime]::UtcNow.ToString('o')) -Force
  Write-Json (Join-Path $Dir 'transaction.json') $txn
}
function AssertDeviceRehearsal {
  Assert ($ExpectedRehearsalProofSha256 -cmatch '^[a-f0-9]{64}$') 'Device physical rehearsal proof pin missing'
  $null=DevicePlain $RehearsalProof
  Assert ((Hash $RehearsalProof) -ceq $ExpectedRehearsalProofSha256) 'Device rehearsal proof hash mismatch'
  $r=JsonFile $RehearsalProof
  Assert ($r.decision -eq 'PASS_DEVICE_JOURNAL_REHEARSAL' -and $r.host -eq 'DESKTOP-1R1081M' -and $r.source_sha -ceq $ExpectedSourceSha -and $r.transaction_script_sha256 -ceq (Hash $PSCommandPath) -and $r.real_owner_touched -eq $false -and $r.journal_advanced_fenced -eq $true -and $r.repeat_recovery_fenced -eq $true -and $r.locked_profile_copy_refused -eq $true -and $r.atomic_shortcut_restore_verified -eq $true -and $r.owner_watchdog_com_verified -eq $true) 'Device physical fault rehearsal is not exact'
}
function RehearseDeviceJournal {
  Assert ($RehearsalProof -match '^[A-Za-z]:\\' -and (IsWithin $RehearsalProof $PrivateRoot) -and !(Test-Path -LiteralPath $RehearsalProof)) 'New private rehearsal proof path required'
  $r=Join-Path $env:TEMP ('nexus-device-activation-synthetic-'+[guid]::NewGuid().ToString('N'))
  $originalOwner=$script:owner;$originalPin=$script:ExpectedJournalSha256;$originalCandidate=$script:candidate;$originalPrior=$script:prior
  New-Item -ItemType Directory -Path $r|Out-Null
  try {
    $script:owner=Join-Path $r 'synthetic-owner'
    $journal=PaperPath $script:owner
    New-Item -ItemType Directory -Path (Split-Path -Parent $journal) -Force|Out-Null
    $module=DeviceVerifierModule
    $code=@'
import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from paper_event_store import build_event,GENESIS_DIGEST
path=Path(sys.argv[2]);events=[]
provenance={'kind':'manual','source_id':'device-rehearsal','source_timestamp':'2020-01-01T00:00:00Z','received_timestamp':'2020-01-01T00:00:00Z','confidence':'1','policy_version':'synthetic-v1','strategy_version':'synthetic-v1','timeframe':'session'}
rows=[('demo_account_opened',{'currency':'USDT','opening_cash':'500'}),('session_boundary_recorded',{'boundary':'open'}),('fee_recorded',{'currency':'USDT','amount':'0.57'}),('equity_snapshot_recorded',{'cash':'499.43','equity':'499.43','unrealized_pnl':'0'})]+[('session_boundary_recorded',{'boundary':'open'})]*16
for i,(kind,payload) in enumerate(rows):
 events.append(build_event(event_id='synthetic:'+str(i),event_type=kind,aggregate_id='synthetic-device-paper',sequence=i+1,occurred_at='2020-01-01T00:00:00Z',correlation_id='synthetic-cutover',causation_id='synthetic-cutover',provenance=provenance,previous_event_digest=events[-1]['event_digest'] if events else GENESIS_DIGEST,payload=payload))
path.write_text(''.join(json.dumps(e,separators=(',',':'),sort_keys=True)+'\n' for e in events),encoding='utf-8')
'@
    & $JournalPython -c $code $module $journal
    Assert ($LASTEXITCODE -eq 0) 'Synthetic journal generation failed'
    $script:ExpectedJournalSha256=Hash $journal
    $baseline=AssertDeviceJournalPin $script:owner
    Assert ($baseline.cash -eq '499.43' -and $baseline.equity -eq '499.43' -and $baseline.event_count -eq 20 -and $baseline.position_count -eq 0) 'Synthetic non-500 baseline replay failed'
    $cookie=Join-Path $script:owner 'Cookies';[IO.File]::WriteAllText($cookie,'synthetic-cookie')
    $stream=[IO.File]::Open($cookie,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    $lockedRefused=$false
    try{try{$null=@(ProfileFiles $script:owner)}catch{$lockedRefused=$true}}finally{$stream.Dispose()}
    Assert $lockedRefused 'Locked profile file was not refused'
    $items=@(ProfileFiles $script:owner);$copy=Join-Path $r 'profile-backup';Copy-Item -LiteralPath $script:owner -Destination $copy -Recurse
    foreach($x in $items){Assert ((Hash (Join-Path $copy $x.rel)) -eq $x.sha) 'Synthetic profile copy hash mismatch'}
    $link=Join-Path $r 'synthetic-gui.lnk';$backup=Join-Path $r 'old-link.lnk';$shell=New-Object -ComObject WScript.Shell
    $old=$shell.CreateShortcut($link);$old.TargetPath=Join-Path $prior 'NEXUS Personal Pro.exe';$old.Arguments=DeviceLaunchArgs $PriorSourceSha;$old.Save()
    Copy-Item -LiteralPath $link -Destination $backup
    $meta=@{path=$link;existed=$true;copy=$backup;sha=Hash $link}
    $temp="$link.nexus-new.lnk";$replacement=$shell.CreateShortcut($temp);$replacement.TargetPath=Join-Path $candidate 'NEXUS Personal Pro.exe';$replacement.Arguments=DeviceLaunchArgs $ExpectedSourceSha;$replacement.Save()
    [IO.File]::Replace($temp,$link,"$link.nexus-rollback-prior.lnk")
    Assert ($shell.CreateShortcut($link).Arguments -ceq (DeviceLaunchArgs $ExpectedSourceSha)) 'Synthetic shortcut profile lost'
    RestoreLinks @($meta)
    Assert ((Hash $link) -ceq $meta.sha) 'Synthetic shortcut rollback changed original bytes'
    $append=@'
import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from paper_event_store import build_event
path=Path(sys.argv[2]);last=json.loads(path.read_text(encoding='utf-8').splitlines()[-1])
event=build_event(event_id='synthetic:20',event_type='session_boundary_recorded',aggregate_id=last['aggregate_id'],sequence=last['sequence']+1,occurred_at=last['occurred_at'],correlation_id='synthetic-cutover',causation_id=last['event_id'],provenance=last['provenance'],previous_event_digest=last['event_digest'],payload={'boundary':'close'})
with path.open('a',encoding='utf-8',newline='\n') as stream: stream.write(json.dumps(event,separators=(',',':'),sort_keys=True)+'\n')
'@
    & $JournalPython -c $append $module $journal
    Assert ($LASTEXITCODE -eq 0 -and (DeviceReplay $script:owner).event_count -eq 21) 'Synthetic valid journal advance failed'
    $advanced=Hash $journal
    # Exercise the exact production recovery core, using only absent disposable install roots.
    # Its proof/record wrapper is separately checked before every real recovery mutation.
    $script:candidate=Join-Path $r 'absent-candidate';$script:prior=Join-Path $r 'absent-prior'
    $syntheticTxn=Join-Path $r 'transaction';New-Item -ItemType Directory -Path $syntheticTxn|Out-Null
    $syntheticState=[pscustomobject]@{status='STARTED';links=@()}
    Write-Json (Join-Path $syntheticTxn 'transaction.json') $syntheticState
    $fenced=$false
    try{RecoverDeviceRecord $syntheticState $syntheticTxn}catch{$fenced=$_.Exception.Message -match 'journal advanced/changed'}
    Assert ($fenced -and $syntheticState.status -eq 'RECOVERY_NEEDS_REVIEW' -and (Hash $journal) -ceq $advanced -and (Hash (PaperPath $copy)) -ceq $ExpectedJournalSha256) 'Advanced synthetic journal was not preserved'
    $before=@(ProfileFiles $r);$repeatFenced=$false
    try{RecoverDeviceRecord (JsonFile (Join-Path $syntheticTxn 'transaction.json')) $syntheticTxn}catch{$repeatFenced=$_.Exception.Message -match 'no repeated mutation'}
    foreach($entry in $before){Assert ((Hash (Join-Path $r $entry.rel)) -ceq $entry.sha) 'Repeated synthetic recovery mutated state'}
    Assert $repeatFenced 'Repeated recovery was not fenced'
    $testName='NEXUS-DeviceActivation-REHEARSAL-'+[guid]::NewGuid().ToString('N')
    $service=New-Object -ComObject Schedule.Service;$service.Connect();$folder=$service.GetFolder('\')
    try{
      $d=$service.NewTask(0);$d.Principal.LogonType=3;$d.Principal.RunLevel=0;$d.Principal.UserId=[Security.Principal.WindowsIdentity]::GetCurrent().Name
      $t=$d.Triggers.Create(1);$t.StartBoundary=[DateTime]::Now.AddMinutes(20).ToString('s')
      $a=$d.Actions.Create(0);$a.Path=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe';$a.Arguments='-NoProfile -NonInteractive -Command "exit 0"'
      $d.Settings.Enabled=$true;$registered=$folder.RegisterTaskDefinition($testName,$d,6,$null,$null,3,$null)
      Assert ($registered.Enabled -eq $true) 'Device owner watchdog COM rehearsal failed'
    }finally{try{$folder.DeleteTask($testName,0)}catch{}}
    $proof=[ordered]@{decision='PASS_DEVICE_JOURNAL_REHEARSAL';host=$env:COMPUTERNAME;source_sha=$ExpectedSourceSha;transaction_script_sha256=(Hash $PSCommandPath);real_owner_touched=$false;journal_advanced_fenced=$true;repeat_recovery_fenced=$repeatFenced;locked_profile_copy_refused=$lockedRefused;atomic_shortcut_restore_verified=$true;owner_watchdog_com_verified=$true;synthetic_event_count=$baseline.event_count;synthetic_advanced_event_count=21;synthetic_cash=$baseline.cash;paper_only=$true;live_trading_authority=$false}
    New-Item -ItemType Directory -Path (Split-Path -Parent $RehearsalProof) -Force|Out-Null
    Write-Json $RehearsalProof $proof
    'DEVICE_JOURNAL_PHYSICAL_REHEARSAL=PASS disposable file/COM faults; no owner activation'
  }finally{$script:owner=$originalOwner;$script:ExpectedJournalSha256=$originalPin;$script:candidate=$originalCandidate;$script:prior=$originalPrior;Remove-Item -LiteralPath $r -Recurse -Force -ErrorAction SilentlyContinue}
}
function InvokeDeviceJournalTransaction {
  InitializeDeviceContext
  if($Mode -ceq 'Rehearse'){RehearseDeviceJournal;return}
  if($Mode -eq 'Preflight'){$null=CheckDeviceStage;AssertDeviceRehearsal;'DEVICE_JOURNAL_PREFLIGHT=PASS no owner mutation';return}
  $locked=$false;$txnDir=$null;$scheduler=$null;$folder=$null
  try {
    try{$locked=$mutex.WaitOne([TimeSpan]::FromSeconds(2))}catch [Threading.AbandonedMutexException]{$locked=$true}
    Assert $locked 'Owner activation already running'
    if($Mode -eq 'Recover'){
      DeviceRecover $TransactionDir
      $oldState=JsonFile (Join-Path $TransactionDir 'transaction.json')
      if($oldState.status -in @('COMMITTED','ROLLED_BACK')){try{$service=New-Object -ComObject Schedule.Service;$service.Connect();$service.GetFolder('\').DeleteTask($taskName,0)}catch{}}
      return
    }
    Assert ($Mode -ceq 'Activate') 'Unknown device transaction operation'
    $baseline=CheckDeviceStage;AssertDeviceRehearsal
    $scheduler=New-Object -ComObject Schedule.Service;$scheduler.Connect();$folder=$scheduler.GetFolder('\')
    try{$existing=$folder.GetTask($taskName)}catch{$existing=$null}
    Assert ($null -eq $existing) 'A previous owner rollback watchdog still exists: investigate first'
    $store=Join-Path $PrivateRoot 'activation-transactions';New-Item -ItemType Directory -Path $store -Force|Out-Null
    $txnDir=Join-Path $store ('device-'+$sourceShort+'-'+[guid]::NewGuid().ToString('N'));New-Item -ItemType Directory -Path $txnDir|Out-Null
    Copy-Item -LiteralPath $PSCommandPath -Destination (Join-Path $txnDir 'recovery.ps1')
    $linkInventory=@(AssertDeviceGuiLinks (JsonFile $CloneProof))
    $txnState=[ordered]@{schema='nexus.owner-device-journal-activation.v1';binding=(DeviceBinding -Transaction);baseline=$baseline;status='STARTED';files=@();links=@();link_inventory=$linkInventory;recovery_script_sha256=(Hash (Join-Path $txnDir 'recovery.ps1'));created_at=[DateTime]::UtcNow.ToString('o');financial_writer_added=$false;owner_profile_replayed=$false}
    Write-Json (Join-Path $txnDir 'transaction.json') $txnState
    # Arm the same bounded transaction watchdog before any process cutover.
    $definition=$scheduler.NewTask(0);$definition.Principal.LogonType=3;$definition.Principal.RunLevel=0;$definition.Principal.UserId=[Security.Principal.WindowsIdentity]::GetCurrent().Name
    $trigger=$definition.Triggers.Create(1);$trigger.StartBoundary=[DateTime]::Now.AddMinutes(14).ToString('s');$trigger.Enabled=$true
    $action=$definition.Actions.Create(0);$action.Path=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $action.Arguments='-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+(Join-Path $txnDir 'recovery.ps1')+'" '+(DeviceRecoveryArguments $txnDir)
    $definition.Settings.Enabled=$true;$definition.Settings.StartWhenAvailable=$true;$definition.Settings.MultipleInstances=2
    $guard=$folder.RegisterTaskDefinition($taskName,$definition,6,$null,$null,3,$null)
    Assert ($guard.Enabled -eq $true) 'Device rollback watchdog could not be armed'
    Stop-Exact $prior -GraceSeconds 15
    Assert (@(ExactProcs $prior).Count -eq 0) 'Device prior process relaunched before capture'
    $null=AssertDeviceJournalPin $owner
    $inventory=@(ProfileFiles $owner);Assert ($inventory.Count -gt 0 -and $inventory.Count -lt 100000) 'Device profile inventory outside bound'
    $profileBackup=Join-Path $txnDir 'profile';Copy-Item -LiteralPath $owner -Destination $profileBackup -Recurse
    foreach($entry in $inventory){Assert ((Hash (Join-Path $profileBackup $entry.rel)) -ceq $entry.sha -and (Hash (Join-Path $owner $entry.rel)) -ceq $entry.sha) ('Device profile changed/locked during capture: '+$entry.rel)}
    $after=@(ProfileFiles $owner);Assert ($after.Count -eq $inventory.Count) 'Device profile inventory changed during capture'
    $pins=@{};foreach($entry in $inventory){$pins[$entry.rel]=$entry}
    foreach($entry in $after){Assert ($pins.ContainsKey($entry.rel) -and $pins[$entry.rel].sha -ceq $entry.sha -and $pins[$entry.rel].bytes -eq $entry.bytes) ('Device profile changed after capture: '+$entry.rel)}
    $null=AssertDeviceJournalPin $owner
    $null=AssertDeviceGuiLinks (JsonFile $CloneProof)
    $txnState.files=$inventory;$txnState.links=@(BackupLinks $txnDir);$txnState.status='BACKED_UP';Write-Json (Join-Path $txnDir 'transaction.json') $txnState
    DeviceCheckRecord (JsonFile (Join-Path $txnDir 'transaction.json')) $txnDir
    Assert (@(ExactProcs $prior).Count -eq 0) 'Device prior process revived during profile copy'
    $txnState.status='ACTIVATING';Write-Json (Join-Path $txnDir 'transaction.json') $txnState
    StartDeviceGui $candidate $ExpectedSourceSha
    $null=DeviceHealth $ExpectedSourceSha 425 $candidate
    Assert (@(ExactProcs $prior).Count -eq 0) 'Device previous app revived during candidate health'
    $shell=New-Object -ComObject WScript.Shell
    foreach($linkMeta in @($txnState.links)){
      $temp="$($linkMeta.path).nexus-new.lnk";$linkObject=$shell.CreateShortcut($temp)
      $linkObject.TargetPath=Join-Path $candidate 'NEXUS Personal Pro.exe';$linkObject.Arguments=DeviceLaunchArgs $ExpectedSourceSha;$linkObject.WorkingDirectory=$candidate;$linkObject.Save()
      Assert (!(Test-Path "$($linkMeta.path).nexus-rollback-prior.lnk")) 'Unexpected old shortcut transaction sibling'
      [IO.File]::Replace($temp,$linkMeta.path,"$($linkMeta.path).nexus-rollback-prior.lnk")
    }
    foreach($linkMeta in @($txnState.links)){
      $committed=$shell.CreateShortcut($linkMeta.path)
      Assert ($committed.TargetPath.Equals((Join-Path $candidate 'NEXUS Personal Pro.exe'),[StringComparison]::OrdinalIgnoreCase) -and $committed.Arguments -ceq (DeviceLaunchArgs $ExpectedSourceSha)) 'Device shortcut target/profile verification failed'
      Assert ((Hash "$($linkMeta.path).nexus-rollback-prior.lnk") -ceq $linkMeta.sha) 'Device shortcut rollback bytes changed'
    }
    $null=DeviceHealth $ExpectedSourceSha 35 $candidate
    $null=AssertDeviceJournalPin $owner
    $txnState.status='COMMITTED';$txnState.committed_at=[DateTime]::UtcNow.ToString('o');Write-Json (Join-Path $txnDir 'transaction.json') $txnState
    foreach($linkMeta in @($txnState.links)){foreach($suffix in @('.nexus-new.lnk','.nexus-rollback-prior.lnk')){if(Test-Path -LiteralPath ($linkMeta.path+$suffix)){Remove-Item -LiteralPath ($linkMeta.path+$suffix) -Force}}}
    try{$folder.DeleteTask($taskName,0)}catch{}
    'DEVICE_JOURNAL_ACTIVATION=PASS exact preserved profile/journal; no financial writer or promotion'
  }catch {
    $reason=$_.Exception.Message
    if($txnDir -and (Test-Path (Join-Path $txnDir 'transaction.json'))){try{DeviceRecover $txnDir;if((JsonFile (Join-Path $txnDir 'transaction.json')).status -eq 'ROLLED_BACK'){$folder.DeleteTask($taskName,0)}}catch{Write-Warning ('Device recovery requires review: '+$txnDir)}}
    throw ('DeviceJournal activation failed closed: '+$reason)
  }finally {
    if($locked){$mutex.ReleaseMutex()};$mutex.Dispose()
    if($script:DeviceVerifierRoot -and (Test-Path $script:DeviceVerifierRoot)){Remove-Item -LiteralPath $script:DeviceVerifierRoot -Recurse -Force -ErrorAction SilentlyContinue}
  }
}
if($AccountSurface -eq 'DeviceJournal'){try{InvokeDeviceJournalTransaction}finally{if($script:DeviceVerifierRoot -and (Test-Path $script:DeviceVerifierRoot)){Remove-Item -LiteralPath $script:DeviceVerifierRoot -Recurse -Force -ErrorAction SilentlyContinue}};exit 0}
if($Mode -eq 'Rehearse'){Rehearse;exit 0}
if($Mode -eq 'Preflight'){ $null=CheckStage;'EXACT_OWNER_PREFLIGHT=PASS no mutation';exit 0 }
if($Mode -eq 'Recover'){
  Assert ($TransactionDir -and (IsWithin $TransactionDir (Join-Path $PrivateRoot 'activation-transactions'))) 'Untrusted recovery transaction'
  $t=JsonFile (Join-Path $TransactionDir 'transaction.json')
  Assert ($t.expected_sha -eq $ExpectedSourceSha -and $t.old_version -eq $OldVersion) 'Recovery manifest mismatch'
  if($t.status -eq 'COMMITTED'){exit 0}
  Rollback $TransactionDir;'AUTOMATIC_OWNER_ROLLBACK=PASS';exit 0
}
Assert ($Mode -eq 'Activate') 'Unknown operation'
$locked=$false;$transaction=$null;$scheduled=$null;$oldSyncEnabled=$null
try{
  $locked=$mutex.WaitOne([TimeSpan]::FromSeconds(2))
  Assert $locked 'Owner activation already running'
  $null=CheckStage
  $scheduler=New-Object -ComObject Schedule.Service;$scheduler.Connect()
  $folder=$scheduler.GetFolder('\');$sync=$folder.GetTask($syncTask)
  Assert ($sync.State -eq 3 -and $sync.Enabled) 'Prospective sync must be idle and enabled'
  $oldSyncEnabled=$sync.Enabled
  $store=Join-Path $PrivateRoot 'activation-transactions'
  if(!(Test-Path $store)){New-Item -ItemType Directory -Path $store|Out-Null}
  $transaction=Join-Path $store ("$sourceShort-"+[DateTime]::UtcNow.ToString('yyyyMMddHHmmss'))
  New-Item -ItemType Directory -Path $transaction -ErrorAction Stop|Out-Null
  Copy-Item -LiteralPath $PSCommandPath -Destination (Join-Path $transaction 'recovery.ps1')
  $record=[ordered]@{schema='nexus.owner-activation-transaction.v1';expected_sha=$ExpectedSourceSha;old_version=$OldVersion;status='STARTED';sync_was_enabled=$oldSyncEnabled;files=@();links=@();created_at=[DateTime]::UtcNow.ToString('o')}
  Write-Json (Join-Path $transaction 'transaction.json') $record
  # Pre-arm owner-session watchdog before changing any owner process or state.
  $def=$scheduler.NewTask(0);$def.RegistrationInfo.Description='NEXUS failed-closed owner rollback'
  $def.Principal.LogonType=3;$def.Principal.RunLevel=0;$def.Principal.UserId=[Security.Principal.WindowsIdentity]::GetCurrent().Name
  $tr=$def.Triggers.Create(1);$tr.StartBoundary=[DateTime]::Now.AddMinutes(14).ToString('s');$tr.Enabled=$true
  $act=$def.Actions.Create(0);$act.Path=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
  $act.Arguments='-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+(Join-Path $transaction 'recovery.ps1')+'" -Mode Recover -ExpectedSourceSha '+$ExpectedSourceSha+' -OldVersion '+$OldVersion+' -PrivateRoot "'+$PrivateRoot+'" -TransactionDir "'+$transaction+'"'
  $def.Settings.Enabled=$true;$def.Settings.StartWhenAvailable=$true
  $def.Settings.MultipleInstances=2
  try{$existing=$folder.GetTask($taskName)}catch{$existing=$null}
  Assert ($null -eq $existing) 'A previous owner rollback watchdog still exists: investigate first'
  $scheduled=$folder.RegisterTaskDefinition($taskName,$def,6,$null,$null,3,$null)
  Assert ($scheduled.Enabled -eq $true) 'Rollback watchdog could not be armed'
  $sync.Enabled=$false
  Stop-Exact $prior 15
  Assert (@(ExactProcs $prior).Count -eq 0) 'Old process relaunch during quiescence'
  $null=ValidPaper $owner
  $files=@(ProfileFiles $owner)
  Assert ($files.Count -gt 0 -and $files.Count -lt 100000) 'Owner profile file count invalid'
  $copy=Join-Path $transaction 'profile'
  Copy-Item -LiteralPath $owner -Destination $copy -Recurse -ErrorAction Stop
  foreach($x in $files){
    Assert ((Hash (Join-Path $copy $x.rel)) -eq $x.sha -and (Hash (Join-Path $owner $x.rel)) -eq $x.sha) 'Owner backup or live source drift'
  }
  $record.files=$files;$record.links=@(BackupLinks $transaction);$record.status='BACKED_UP'
  Write-Json (Join-Path $transaction 'transaction.json') $record
  Assert (@(ExactProcs $prior).Count -eq 0) 'Old version relaunched before candidate'
  $env:RUNNER_TRACKING_ID=$null
  $record.status='ACTIVATING';Write-Json (Join-Path $transaction 'transaction.json') $record
  $null=Start-Process -FilePath (Join-Path $candidate 'NEXUS Personal Pro.exe')
  $null=Health $ExpectedSourceSha 425
  Assert (@(ExactProcs $prior).Count -eq 0) 'Prior app unexpectedly relaunched'
  # Switch shortcuts only after real owner profile and exact new GUI are healthy.
  $shell=New-Object -ComObject WScript.Shell
  foreach($l in $record.links){
    $tmp="$($l.path).nexus-new.lnk"
    $shortcut=$shell.CreateShortcut($tmp);$shortcut.TargetPath=Join-Path $candidate 'NEXUS Personal Pro.exe'
    $shortcut.WorkingDirectory=$candidate;$shortcut.Save()
    if(Test-Path -LiteralPath $l.path){
      $priorSibling="$($l.path).nexus-rollback-prior.lnk"
      Assert (!(Test-Path -LiteralPath $priorSibling)) 'Unexpected previous shortcut sibling: investigate first'
      [IO.File]::Replace($tmp,$l.path,$priorSibling)
    }
    else {Move-Item -LiteralPath $tmp -Destination $l.path}
  }
  # Read each committed shortcut back through Windows COM, and retain its
  # exact pre-activation hash via the named File.Replace sibling until commit.
  $newExecutable=Join-Path $candidate 'NEXUS Personal Pro.exe'
  foreach($l in $record.links){
    Assert ((Test-Path -LiteralPath $l.path -PathType Leaf) -and
      $shell.CreateShortcut($l.path).TargetPath.Equals($newExecutable,[StringComparison]::OrdinalIgnoreCase)) 'Post-switch shortcut target mismatch'
    if($l.existed){
      $sibling="$($l.path).nexus-rollback-prior.lnk"
      Assert ((Test-Path -LiteralPath $sibling -PathType Leaf) -and
        (Hash $sibling) -eq $l.sha) 'Atomic switch modified original shortcut bytes'
    }
  }
  Assert (@(ExactProcs $prior).Count -eq 0) 'Prior app restarted during shortcut commit'
  $null=Health $ExpectedSourceSha 35
  $sync.Enabled=$oldSyncEnabled
  $record.status='COMMITTED';$record.committed_at=[DateTime]::UtcNow.ToString('o')
  Write-Json (Join-Path $transaction 'transaction.json') $record
  foreach($l in $record.links){
    foreach($suffix in @('.nexus-new.lnk','.nexus-rollback-prior.lnk')){
      $extra="$($l.path)$suffix"
      if(Test-Path -LiteralPath $extra){Remove-Item -LiteralPath $extra -Force -ErrorAction SilentlyContinue}
    }
  }
  try{$folder.DeleteTask($taskName,0)}catch{}
  'EXACT_OWNER_ACTIVATION=PASS new owner GUI verified; rollback backup retained'
}catch{
  $reason=$_.Exception.Message
  if($transaction -and (Test-Path (Join-Path $transaction 'transaction.json'))){
    try{
      Rollback $transaction
      if((JsonFile (Join-Path $transaction 'transaction.json')).status -eq 'ROLLED_BACK'){
        try{$folder.DeleteTask($taskName,0)}catch{}
      }
    }catch{Write-Warning ('RECOVERY_REQUIRED private transaction='+$transaction)}
  }
  if($oldSyncEnabled -ne $null){try{$sync.Enabled=$oldSyncEnabled}catch{}}
  throw "Owner activation failed closed: $reason"
}finally{if($locked){$mutex.ReleaseMutex()};$mutex.Dispose()}
