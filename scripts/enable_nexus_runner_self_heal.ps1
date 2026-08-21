[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$TaskName = 'NEXUS-GitHub-Runner-Autostart'
$TriggerId = 'NEXUS-Self-Heal-5m'
$StateRoot = Join-Path $env:LOCALAPPDATA 'NEXUS\RunnerAutostart'
$EvidencePath = Join-Path $StateRoot 'self-heal-evidence.json'

function Write-Evidence([string]$Status, [hashtable]$Extra = @{}) {
    New-Item -ItemType Directory -Force -Path $StateRoot | Out-Null
    $payload = [ordered]@{
        contract_version = 'nexus.runner-self-heal.v1'
        status = $Status
        generated_at = [DateTime]::UtcNow.ToString('o')
        scheduled_task = $TaskName
        trigger_id = $TriggerId
        interval_minutes = 5
        creates_separate_watchdog_task = $false
        creates_background_watchdog_process = $false
        runner_registration_modified = $false
        credentials_modified = $false
        elevation_requested = $false
        service_installed = $false
        paper_only = $true
        live_trading_authority = $false
    }
    foreach ($key in $Extra.Keys) { $payload[$key] = $Extra[$key] }
    $tmp = $EvidencePath + '.tmp'
    $payload | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $tmp -Encoding UTF8
    Move-Item -LiteralPath $tmp -Destination $EvidencePath -Force
}

function Connect-TaskScheduler {
    $service = New-Object -ComObject 'Schedule.Service'
    $service.Connect()
    return $service
}

try {
    if ($env:OS -ne 'Windows_NT') { throw 'Windows is required.' }
    if (-not [Environment]::UserInteractive) { throw 'Run this helper from the signed-in Windows desktop.' }

    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    if ($identity -in @('NT AUTHORITY\SYSTEM','NT AUTHORITY\NETWORK SERVICE','NT AUTHORITY\LOCAL SERVICE')) {
        throw 'A signed-in owner account is required.'
    }

    $service = Connect-TaskScheduler
    $folder = $service.GetFolder('\')
    $task = $folder.GetTask("\$TaskName")
    if (-not $task) { throw "NEXUS runner task is missing: $TaskName" }

    $definition = $task.Definition
    if (-not $definition) { throw 'Task Scheduler did not return the runner task definition.' }
    if ($definition.Settings.MultipleInstances -ne 2) {
        throw 'Runner task is not configured with IgnoreNew multiple-instance protection.'
    }

    $triggers = $definition.Triggers
    for ($i = $triggers.Count; $i -ge 1; $i--) {
        $candidate = $triggers.Item($i)
        if ($candidate.Id -eq $TriggerId) {
            $triggers.Remove($i)
        }
    }

    # Reuse the existing runner task instead of creating a second watchdog task/process.
    # The daily trigger repeats every five minutes for one day and is recreated by the
    # next daily boundary. While Runner.Listener is alive, MultipleInstances=IgnoreNew
    # makes the trigger a no-op. If the runner has exited after exhausting its restart
    # budget, the next five-minute tick starts the same hidden task again.
    $selfHeal = $triggers.Create(2)
    $selfHeal.Id = $TriggerId
    $selfHeal.Enabled = $true
    $selfHeal.StartBoundary = [DateTime]::Now.AddMinutes(1).ToString('s')
    $selfHeal.DaysInterval = 1
    $selfHeal.Repetition.Interval = 'PT5M'
    $selfHeal.Repetition.Duration = 'P1D'
    $selfHeal.Repetition.StopAtDurationEnd = $false

    $registered = $folder.RegisterTaskDefinition("\$TaskName",$definition,6,$null,$null,3,$null)
    if (-not $registered) { throw 'Task Scheduler did not return the updated runner task.' }

    $verified = $false
    $registeredTriggers = $registered.Definition.Triggers
    for ($i = 1; $i -le $registeredTriggers.Count; $i++) {
        $candidate = $registeredTriggers.Item($i)
        if ($candidate.Id -eq $TriggerId -and
            $candidate.Repetition.Interval -eq 'PT5M' -and
            $candidate.Repetition.Duration -eq 'P1D') {
            $verified = $true
            break
        }
    }
    if (-not $verified) { throw 'Runner self-heal trigger was not verified after registration.' }

    Write-Evidence 'SUCCESS' @{ trigger_registered = $true; existing_task_reused = $true }
    Write-Host 'NEXUS runner self-heal is enabled on the existing hidden task.' -ForegroundColor Green
    exit 0
}
catch {
    $message = $_.Exception.Message
    try { Write-Evidence 'BLOCKED' @{ error = $message } } catch { }
    Write-Host "NEXUS runner self-heal setup blocked: $message" -ForegroundColor Red
    exit 1
}
