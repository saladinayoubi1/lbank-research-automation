[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Source,
    [Parameter(Mandatory=$true)][string]$StateRoot,
    [Parameter(Mandatory=$true)][string]$Python,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{40}$')][string]$SourceSha,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ManifestSha
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$taskName = 'NEXUS-MR40-LBank-Research-Paper-v1'
$scriptPath = Join-Path $Source 'research\nexus_mr40_lbank_isolated_paper_v1.py'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if ($identity.IsSystem) { throw 'Interactive owner identity is required; refusing SYSTEM registration' }
$service = New-Object -ComObject 'Schedule.Service'
$service.Connect()
$folder = $service.GetFolder('\')
$existing = $null
try { $existing = $folder.GetTask($taskName) } catch { }
if ($existing) { throw 'This research task already exists; refusing replacement' }
if (-not (Test-Path -LiteralPath $Python) -or -not (Test-Path -LiteralPath $scriptPath)) { throw 'Pinned Python/source missing' }
$windowless = Join-Path (Split-Path -Parent $Python) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $windowless)) { throw 'Windowless Python missing' }
$runnerArgs = @($scriptPath,'--source',$Source,'--state-root',$StateRoot,'--source-sha',$SourceSha,'--manifest-sha',$ManifestSha)
& $Python @runnerArgs
if ($LASTEXITCODE -ne 0) { throw 'First real public-data Paper activation failed; no task installed' }
$state = Get-Content -Raw -LiteralPath (Join-Path $StateRoot 'state.json') | ConvertFrom-Json
if ($state.policy.live_enabled -ne $false -or $state.policy.provider -ne 'LBank' -or $state.policy.initial_cash_usdt -ne '500') { throw 'Research Paper identity mismatch' }
$definition = $service.NewTask(0)
$definition.RegistrationInfo.Description = 'Owner-requested isolated MR40 Momentum30 research Paper; LBank public data, 500 virtual USDT, zero exchange orders.'
$definition.Principal.UserId = $identity.User.Value
$definition.Principal.LogonType = 3
$definition.Principal.RunLevel = 0
$definition.Settings.Enabled = $true
$definition.Settings.StartWhenAvailable = $true
$definition.Settings.DisallowStartIfOnBatteries = $false
$definition.Settings.StopIfGoingOnBatteries = $false
$definition.Settings.MultipleInstances = 2
$definition.Settings.ExecutionTimeLimit = 'PT1M'
$definition.Settings.AllowDemandStart = $true
$expiry = [DateTimeOffset]::FromUnixTimeMilliseconds([long]$state.trial_end_ms+120000).UtcDateTime.ToString("yyyy-MM-ddTHH:mm:ss'Z'")
$timer = $definition.Triggers.Create(1)
$timer.Enabled = $true
$timer.StartBoundary = (Get-Date).AddSeconds(10).ToString('yyyy-MM-ddTHH:mm:ss')
$timer.EndBoundary = $expiry
$timer.Repetition.Interval = 'PT1M'
$timer.Repetition.Duration = 'P31D'
$timer.Repetition.StopAtDurationEnd = $false
$logon = $definition.Triggers.Create(9)
$logon.Enabled = $true
$logon.UserId = $identity.User.Value
$logon.EndBoundary = $expiry
$action = $definition.Actions.Create(0)
$action.Path = $windowless
$action.Arguments = (($runnerArgs | ForEach-Object { '"'+$_+'"' }) -join ' ')
$action.WorkingDirectory = $Source
$task = $folder.RegisterTaskDefinition($taskName,$definition,2,$null,$null,3,$null)
if (-not $task -or [int]$task.Definition.Principal.RunLevel -ne 0) { throw 'Limited interactive task verification failed' }
$desktop = [Environment]::GetFolderPath('Desktop')
$shell = New-Object -ComObject 'WScript.Shell'
$shortcut = $shell.CreateShortcut((Join-Path $desktop 'NEXUS MR40 LBank Paper.lnk'))
$shortcut.TargetPath = (Join-Path $env:WINDIR 'explorer.exe')
$shortcut.Arguments = '"'+(Join-Path $StateRoot 'dashboard.html')+'"'
$shortcut.WorkingDirectory = $StateRoot
$shortcut.Description = 'Isolated research Paper, 500 virtual USDT, LBank BTC/USDT 4h'
$shortcut.Save()
Set-Content -LiteralPath (Join-Path $StateRoot 'STOP_PAPER.cmd') -Encoding ASCII -Value @('@echo off',('echo owner_request>"'+(Join-Path $StateRoot 'STOP')+'"'),('schtasks /Change /TN "'+$taskName+'" /DISABLE'))
[void]$task.Run($null)
Start-Process -FilePath (Join-Path $StateRoot 'dashboard.html')
[pscustomobject]@{Installed=$true;TaskName=$taskName;TaskEnabled=$task.Enabled;TaskRunLevel=[int]$task.Definition.Principal.RunLevel;TimerInterval=$timer.Repetition.Interval;LogonResume=$true;DesktopShortcutCreated=$true;PaperInitialCash='500';SourceSha=$SourceSha;ManifestSha256=$ManifestSha;FirstExecutionBarMs=$state.first_execution_bar_ms;TrialEndMs=$state.trial_end_ms;LiveEnabled=$false;ExchangeOrders=0} | ConvertTo-Json -Compress
