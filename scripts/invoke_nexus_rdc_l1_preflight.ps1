param([Parameter(Mandatory=$true)][string]$SourceSha,[Parameter(Mandatory=$true)][string]$CodeSha)
$ErrorActionPreference='Stop'
if($env:COMPUTERNAME -ne 'DESKTOP-1R1081M'){throw 'Wrong host'}
if($SourceSha -cnotmatch '^[0-9a-f]{40}$' -or $CodeSha -cnotmatch '^[0-9a-f]{64}$'){throw 'Immutable source required'}
$probe=Join-Path $PSScriptRoot 'probe_nexus_rdc_l1_preflight.py'
if((Get-FileHash -Algorithm SHA256 -LiteralPath $probe).Hash.ToLowerInvariant() -ne $CodeSha){throw 'Probe source changed'}
$run=Join-Path $PSScriptRoot 'run'
New-Item -ItemType Directory -Path $run -ErrorAction Stop | Out-Null
$checks=@(
    @{path='C:\Users\afaq\AppData\Local\NEXUS\desktop-commander-remote\remote-supervisor.cjs'; expected='d762b259a74aa0b31188dcc02e259bbf9f2c7cd61952bc858297554c2412e35d'},
    @{path='C:\Users\afaq\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\NEXUS-Remote-Desktop-Commander.vbs'; expected='a8fdc21df5a315308768376cc22f704b316101016e2445abbdd6ccd4b3b29887'},
    @{path='C:\Users\afaq\AppData\Local\NEXUS\RemoteCommander\LEGACY_DISABLED.flag'; expected='862595a01549b7b44a920a99670fd99d996584bbae3e44d868efc530c5195944'},
    @{path='C:\Users\afaq\AppData\Local\NEXUS\RemoteCommander\nexus-remote-commander-watchdog.ps1'; expected='c5b185ed07e1894b8fb6ce1c373c5cde5dbbadabb12d87581e333fcdee9b25f7'}
)
$files=@()
foreach($check in $checks){
    $actual=(Get-FileHash -Algorithm SHA256 -LiteralPath $check.path).Hash.ToLowerInvariant()
    if($actual -ne $check.expected){throw ('Guard file changed: '+$check.path)}
    $files+=@{path=$check.path;sha256=$actual}
}
$service=New-Object -ComObject 'Schedule.Service'
$service.Connect()
$task=$service.GetFolder('\').GetTask('NEXUS-Remote-Commander-Recovery')
$xml=[string]$task.Xml
$utf8=New-Object System.Text.UTF8Encoding($false)
$xmlPath=Join-Path $run 'task-current.xml'
[IO.File]::WriteAllText($xmlPath,$xml,$utf8)
$xmlSha=(Get-FileHash -Algorithm SHA256 -LiteralPath $xmlPath).Hash.ToLowerInvariant()
if($xmlSha -ne '284b39bd04f936372d30f42c798bae76382882b8b84cea22b7338a5ebb8e2c74'){throw 'Existing task XML changed'}
$receipt=@{schema='nexus.rdc-l1-task-settings-read.v1';observed_utc=[DateTime]::UtcNow.ToString('o');source_sha=$SourceSha;probe_sha256=$CodeSha;wrapper_sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath $PSCommandPath).Hash.ToLowerInvariant();host=$env:COMPUTERNAME;files=$files;task_name=$task.Name;task_enabled=$task.Enabled;task_state=$task.State;task_last_result=$task.LastTaskResult;task_xml_sha256=$xmlSha;supervisor_lock_present=(Test-Path -LiteralPath 'C:\Users\afaq\AppData\Local\NEXUS\desktop-commander-remote\supervisor.json');task_retargeted=$false;startup_changed=$false;credential_files_read=$false;live_enabled=$false}
$receiptPath=Join-Path $run 'task-settings.json'
[IO.File]::WriteAllText($receiptPath,($receipt|ConvertTo-Json -Depth 12),$utf8)
& 'C:\Users\afaq\AppData\Local\Programs\Python\Python312\python.exe' $probe --source-sha $SourceSha --output-dir $run
$queryExit=$LASTEXITCODE
Write-Output ('ACTUAL_PREFLIGHT_QUERY_EXIT='+$queryExit)
exit $queryExit
