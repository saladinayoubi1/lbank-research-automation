# NEXUS Task Scheduler compatibility helpers.
#
# Windows PowerShell's ScheduledTasks cmdlets are implemented over CIM. Some owner
# laptops have a healthy Task Scheduler service while the local CIM/WMI provider is
# unavailable. These helpers talk to the Task Scheduler 2.0 COM API directly so
# NEXUS persistence remains current-user, limited-runlevel and fail-closed without
# requiring CIM, elevation, credentials, or machine policy changes.

function Connect-NexusTaskScheduler {
    $service = New-Object -ComObject 'Schedule.Service'
    $service.Connect()
    return $service
}

function Get-NexusTaskStateName([int]$State) {
    switch ($State) {
        0 { return 'Unknown' }
        1 { return 'Disabled' }
        2 { return 'Queued' }
        3 { return 'Ready' }
        4 { return 'Running' }
        default { return "State$State" }
    }
}

function Get-NexusScheduledTask([string]$Name) {
    if (-not $Name) { throw 'scheduled task name is required' }
    $service = Connect-NexusTaskScheduler
    $folder = $service.GetFolder('\')
    try {
        return $folder.GetTask("\$Name")
    }
    catch {
        # 0x80070002 is the ordinary "task not found" path. Treat any lookup
        # failure as absent here; callers performing installation still fail closed
        # if task registration itself cannot be completed.
        return $null
    }
}

function Get-NexusScheduledTaskSnapshot([string]$Name) {
    $task = Get-NexusScheduledTask $Name
    if (-not $task) {
        return [ordered]@{
            exists = $false
            state = 'MISSING'
            user = $null
            run_level = $null
            last_run_time = $null
            last_task_result = $null
        }
    }

    $definition = $task.Definition
    $principal = $definition.Principal
    $runLevel = if ([int]$principal.RunLevel -eq 0) { 'Limited' } else { 'Highest' }
    return [ordered]@{
        exists = $true
        state = Get-NexusTaskStateName ([int]$task.State)
        user = [string]$principal.UserId
        run_level = $runLevel
        last_run_time = [string]$task.LastRunTime
        last_task_result = [int64]$task.LastTaskResult
    }
}

function New-NexusInteractiveLogonTask {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][string]$Name,
        [Parameter(Mandatory=$true)][string]$Execute,
        [Parameter(Mandatory=$true)][string]$Arguments,
        [Parameter(Mandatory=$true)][string]$WorkingDirectory,
        [Parameter(Mandatory=$true)][string]$User,
        [Parameter(Mandatory=$true)][string]$Description,
        [switch]$StartNow
    )

    if (-not (Test-Path -LiteralPath $Execute -PathType Leaf)) {
        throw "scheduled task executable is missing: $Execute"
    }
    if (-not (Test-Path -LiteralPath $WorkingDirectory -PathType Container)) {
        throw "scheduled task working directory is missing: $WorkingDirectory"
    }

    # Task Scheduler 2.0 constants.
    $TASK_TRIGGER_LOGON = 9
    $TASK_ACTION_EXEC = 0
    $TASK_CREATE_OR_UPDATE = 6
    $TASK_LOGON_INTERACTIVE_TOKEN = 3
    $TASK_RUNLEVEL_LUA = 0
    $TASK_INSTANCES_IGNORE_NEW = 2

    $service = Connect-NexusTaskScheduler
    $folder = $service.GetFolder('\')
    $definition = $service.NewTask(0)
    $definition.RegistrationInfo.Description = $Description
    $definition.RegistrationInfo.Author = 'NEXUS Personal Pro'

    $definition.Principal.UserId = $User
    $definition.Principal.LogonType = $TASK_LOGON_INTERACTIVE_TOKEN
    $definition.Principal.RunLevel = $TASK_RUNLEVEL_LUA

    $settings = $definition.Settings
    $settings.Enabled = $true
    $settings.StartWhenAvailable = $true
    $settings.DisallowStartIfOnBatteries = $false
    $settings.StopIfGoingOnBatteries = $false
    $settings.MultipleInstances = $TASK_INSTANCES_IGNORE_NEW
    $settings.RestartInterval = 'PT1M'
    $settings.RestartCount = 999
    $settings.ExecutionTimeLimit = 'PT0S'

    $trigger = $definition.Triggers.Create($TASK_TRIGGER_LOGON)
    $trigger.Enabled = $true
    $trigger.UserId = $User

    $action = $definition.Actions.Create($TASK_ACTION_EXEC)
    $action.Path = $Execute
    $action.Arguments = $Arguments
    $action.WorkingDirectory = $WorkingDirectory

    $registered = $folder.RegisterTaskDefinition(
        "\$Name",
        $definition,
        $TASK_CREATE_OR_UPDATE,
        $null,
        $null,
        $TASK_LOGON_INTERACTIVE_TOKEN,
        $null
    )
    if (-not $registered) { throw "Task Scheduler did not return a registered task: $Name" }

    if ($StartNow) {
        [void]$registered.Run($null)
    }

    $snapshot = Get-NexusScheduledTaskSnapshot $Name
    if (-not $snapshot.exists) { throw "scheduled task registration verification failed: $Name" }
    if ($snapshot.run_level -ne 'Limited') { throw "scheduled task unexpectedly requested elevated run level: $Name" }
    return $snapshot
}

function Start-NexusScheduledTask([string]$Name) {
    $task = Get-NexusScheduledTask $Name
    if (-not $task) { throw "scheduled task is not installed: $Name" }
    [void]$task.Run($null)
}

function Remove-NexusScheduledTask([string]$Name) {
    $service = Connect-NexusTaskScheduler
    $folder = $service.GetFolder('\')
    $task = $null
    try { $task = $folder.GetTask("\$Name") } catch { }
    if ($task) {
        try { $task.Stop(0) } catch { }
        $folder.DeleteTask("\$Name", 0)
    }
}
