param([switch]$ValidateOnly)
$ErrorActionPreference='Stop'
$operationRoot='E:\NEXUS-QA\rdc-active-handoff-20261014T0150Z'
$scriptPath=Join-Path $operationRoot 'active_handoff.ps1'
$plan=ConvertFrom-Json ([IO.File]::ReadAllText((Join-Path $operationRoot 'PLAN.json')))
$state=[ordered]@{schema='nexus.rdc-active-handoff.v1';source_sha=$plan.merged_source;operation_sha256=$plan.operation_sha256;host=[string]$env:COMPUTERNAME;worker_pid=$PID;phase='VALIDATING';old_processes_stopped=$false;existing_startup_started=$false;active_process_adopted=$false;live_enabled=$false}
$statusPath=Join-Path $operationRoot $(if($ValidateOnly){'READ_ONLY_VALIDATION.json'}else{'ACTIVATION_STATUS.json'})
$heldProcesses=@()
$mutex=$null
function Save-State {
  $state.updated_utc=[DateTime]::UtcNow.ToString('o')
  $pending=$statusPath+'.tmp.'+$PID
  [IO.File]::WriteAllText($pending,($state|ConvertTo-Json -Depth 6),[Text.UTF8Encoding]::new($false))
  if([IO.File]::Exists($statusPath)){[IO.File]::Replace($pending,$statusPath,$null)}else{[IO.File]::Move($pending,$statusPath)}
}
function Hash-Text([string]$value){[BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($value))).Replace('-','').ToLowerInvariant()}
function All-Processes { @(Get-CimInstance Win32_Process) }
function Remote-Rows($rows){ @($rows|Where-Object {$_.Name -eq 'node.exe' -and $_.CommandLine -match '(?i)index\.js"?\s+remote\b'}) }
function Ancestor-Is($row,[int]$ancestor,$rows){
  for($level=0;$level -lt 10 -and $null -ne $row;$level++){
    if([int]$row.ProcessId -eq $ancestor){return $true}
    $parentNumber=[int]$row.ParentProcessId
    $row=$rows|Where-Object {[int]$_.ProcessId -eq $parentNumber}|Select-Object -First 1
  }
  return $false
}
try {
  if($env:COMPUTERNAME -ne 'DESKTOP-F4SA4VL'){throw 'Wrong physical host'}
  if((Get-FileHash -Algorithm SHA256 -LiteralPath $scriptPath).Hash.ToLowerInvariant() -ne $plan.operation_sha256){throw 'Operation source differs'}
  foreach($bound in $plan.bound_files){if((Get-FileHash -Algorithm SHA256 -LiteralPath $bound.path).Hash.ToLowerInvariant() -ne $bound.sha256){throw 'Bound launcher or Startup differs'}}
  $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
  if($identity.User.Value -ne $plan.owner_sid -or (Get-Process -Id $PID).SessionId -ne 1){throw 'Wrong Windows owner/session'}
  if(@(Get-Process -Name Runner.Listener -ErrorAction SilentlyContinue).Count -ne 1 -or @(Get-Process -Name Runner.Worker -ErrorAction SilentlyContinue).Count -ne 0){throw 'Research lane changed or work active'}
  $taskService=New-Object -ComObject Schedule.Service
  $taskService.Connect()
  foreach($taskName in @('NEXUS-Local-Failover-Autostart','NEXUS-Bybit-Failover-Autostart')){if($taskService.GetFolder('\').GetTask($taskName).Enabled){throw 'Failover task must stay disabled'}}
  $rows=All-Processes
  $clients=Remote-Rows $rows
  if($clients.Count -ne 1 -or [int]$clients[0].ProcessId -ne 10416){throw 'Active remote changed'}
  if(@($rows|Where-Object {$_.Name -eq 'cmd.exe' -and $_.CommandLine -match '(?i)remote-supervisor\.cmd'}).Count -ne 0){throw 'A launcher loop already exists'}
  foreach($expected in $plan.targets){
    $row=$rows|Where-Object {[int]$_.ProcessId -eq [int]$expected.pid}|Select-Object -First 1
    if($null -eq $row -or [int]$row.ParentProcessId -ne [int]$expected.ppid -or $row.CreationDate.ToUniversalTime().ToString('o') -ne $expected.created -or (Hash-Text ([string]$row.CommandLine)) -ne $expected.command_sha256){throw 'Frozen process identity differs'}
    $owner=Invoke-CimMethod -InputObject $row -MethodName GetOwnerSid
    if($owner.ReturnValue -ne 0 -or $owner.Sid -ne $plan.owner_sid -or [int]$row.SessionId -ne 1){throw 'Frozen process owner/session differs'}
    $handle=[Diagnostics.Process]::GetProcessById([int]$expected.pid)
    if([Math]::Abs(($handle.StartTime.ToUniversalTime()-[DateTime]::Parse($expected.created).ToUniversalTime()).TotalMilliseconds) -gt 1){throw 'PID identity changed while opening handle'}
    $null=$handle.Handle
    $heldProcesses+=,$handle
  }
  if($ValidateOnly){$state.phase='READ_ONLY_PASS';$state.preconditions_verified=$true;Save-State;exit 0}
  $self=$rows|Where-Object {[int]$_.ProcessId -eq $PID}|Select-Object -First 1
  $parent=$rows|Where-Object {[int]$_.ProcessId -eq [int]$self.ParentProcessId}|Select-Object -First 1
  if($parent.Name -ne 'WmiPrvSE.exe' -or (Ancestor-Is $self 8520 $rows)){throw 'Worker is not independent of RDC'}
  if([IO.File]::Exists($statusPath)){throw 'Existing handoff receipt forbids repeated execution'}
  $mutex=[Threading.Mutex]::new($false,'Local\NEXUS_RDC_L2_ACTIVE_HANDOFF')
  if(-not $mutex.WaitOne(0)){throw 'Another handoff is active'}
  $state.worker_parent=[string]$parent.Name
  $state.phase='PRECONDITIONS_VERIFIED';Save-State
  Start-Sleep -Seconds 5
  foreach($handle in $heldProcesses){if(-not $handle.HasExited){$handle.Kill()}}
  foreach($handle in $heldProcesses){if(-not $handle.WaitForExit(10000)){throw 'Old process exit was not proven'}}
  $rows=All-Processes
  if((Remote-Rows $rows).Count -ne 0){throw 'A remote remains active; no new client will be started'}
  $state.old_processes_stopped=$true;$state.phase='OLD_PROCESSES_EXITED';Save-State
  foreach($bound in $plan.bound_files){if((Get-FileHash -Algorithm SHA256 -LiteralPath $bound.path).Hash.ToLowerInvariant() -ne $bound.sha256){throw 'Bound file changed before launch'}}
  $start=[Diagnostics.ProcessStartInfo]::new()
  $start.FileName=$env:ComSpec
  $start.Arguments='/d /c call "'+$plan.startup_path+'"'
  $start.WorkingDirectory=$operationRoot
  $start.UseShellExecute=$false
  $start.CreateNoWindow=$true
  $wrapper=[Diagnostics.Process]::Start($start)
  $state.startup_wrapper_pid=$wrapper.Id
  if(-not $wrapper.WaitForExit(10000) -or $wrapper.ExitCode -ne 0){throw 'Existing Startup did not return success'}
  $state.existing_startup_started=$true;$state.phase='EXISTING_STARTUP_STARTED';Save-State
  $deadline=[DateTime]::UtcNow.AddSeconds(90)
  do {
    $rows=All-Processes
    $loops=@($rows|Where-Object {$_.Name -eq 'cmd.exe' -and $_.CommandLine -match '(?i)remote-supervisor\.cmd'})
    $clients=Remote-Rows $rows
    if($loops.Count -gt 1 -or $clients.Count -gt 1){throw 'Duplicate remote/loop detected; no further launch attempted'}
    if($loops.Count -eq 1 -and $clients.Count -eq 1 -and [int]$clients[0].ProcessId -ne 10416 -and (Ancestor-Is $clients[0] ([int]$loops[0].ProcessId) $rows)){
      $state.new_loop_pid=[int]$loops[0].ProcessId;$state.new_remote_pid=[int]$clients[0].ProcessId
      $state.remote_client_count=1;$state.active_process_adopted=$true;$state.phase='ACTIVE_PROCESS_SWITCHED';Save-State;exit 0
    }
    Start-Sleep -Milliseconds 500
  } while([DateTime]::UtcNow -lt $deadline)
  $state.phase='STARTED_AWAITING_CLIENT';$state.no_second_launch_attempted=$true;Save-State;exit 2
} catch {
  $state.phase='FAILED_CLOSED';$state.error=[string]$_.Exception.Message
  Save-State
  exit 1
} finally {
  foreach($handle in $heldProcesses){$handle.Dispose()}
  if($null -ne $mutex){try{$mutex.ReleaseMutex()}catch{};$mutex.Dispose()}
}
