param(
    [string]$OutputPath = "build\wsl-virtualization\evidence.json"
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-FeatureState {
    param([Parameter(Mandatory = $true)][string]$Name)
    try {
        return [string](Get-WindowsOptionalFeature -Online -FeatureName $Name -ErrorAction Stop).State
    }
    catch {
        return 'Unknown'
    }
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @()
    )

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $rawOutput = @(& $FilePath @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
        $text = (($rawOutput | ForEach-Object { $_.ToString() }) | Out-String)
        $text = ($text -replace "`0", '').Trim()
        return [ordered]@{
            exit_code = if ($null -eq $exitCode) { -1 } else { [int]$exitCode }
            output = $text
        }
    }
    catch {
        return [ordered]@{
            exit_code = -1
            output = $_.Exception.ToString()
        }
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

function Test-PendingReboot {
    $signals = New-Object System.Collections.Generic.List[string]
    if (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending') {
        $signals.Add('ComponentBasedServicing')
    }
    if (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired') {
        $signals.Add('WindowsUpdate')
    }
    try {
        $sessionManager = Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager' -Name PendingFileRenameOperations -ErrorAction Stop
        if ($null -ne $sessionManager.PendingFileRenameOperations) {
            $signals.Add('PendingFileRenameOperations')
        }
    }
    catch { }
    return @($signals)
}

function Limit-Text {
    param([string]$Text, [int]$Maximum = 12000)
    if ($null -eq $Text) { return '' }
    if ($Text.Length -le $Maximum) { return $Text }
    return $Text.Substring(0, $Maximum)
}

function Write-Evidence {
    param(
        [Parameter(Mandatory = $true)][string]$Target,
        [Parameter(Mandatory = $true)][System.Collections.IDictionary]$Payload
    )
    $parent = Split-Path -Parent $Target
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $json = $Payload | ConvertTo-Json -Depth 10
    [IO.File]::WriteAllText($Target, $json, (New-Object Text.UTF8Encoding($false)))
}

$target = [IO.Path]::GetFullPath($OutputPath)
$isAdmin = Test-IsAdministrator
$evidence = [ordered]@{
    schema_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString('o')
    source_sha = $env:GITHUB_SHA
    run_id = $env:GITHUB_RUN_ID
    administrator = $isAdmin
    windows_runner_paths_modified = $false
    automatic_restart_performed = $false
    restart_required = $false
    boot_configuration_modified = $false
    decision = $null
}

$wslFeature = Get-FeatureState -Name 'Microsoft-Windows-Subsystem-Linux'
$vmFeature = Get-FeatureState -Name 'VirtualMachinePlatform'
$evidence.windows_features = [ordered]@{
    wsl = $wslFeature
    virtual_machine_platform = $vmFeature
}

$cpu = $null
$computerSystem = $null
try { $cpu = Get-CimInstance Win32_Processor -ErrorAction Stop | Select-Object -First 1 } catch { }
try { $computerSystem = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop } catch { }

$firmwareVirtualization = $null
$slat = $null
$vmMonitor = $null
if ($null -ne $cpu) {
    if ($cpu.PSObject.Properties.Name -contains 'VirtualizationFirmwareEnabled') {
        $firmwareVirtualization = [bool]$cpu.VirtualizationFirmwareEnabled
    }
    if ($cpu.PSObject.Properties.Name -contains 'SecondLevelAddressTranslationExtensions') {
        $slat = [bool]$cpu.SecondLevelAddressTranslationExtensions
    }
    if ($cpu.PSObject.Properties.Name -contains 'VMMonitorModeExtensions') {
        $vmMonitor = [bool]$cpu.VMMonitorModeExtensions
    }
}

$hypervisorPresent = $null
if ($null -ne $computerSystem -and ($computerSystem.PSObject.Properties.Name -contains 'HypervisorPresent')) {
    $hypervisorPresent = [bool]$computerSystem.HypervisorPresent
}

$evidence.cpu = [ordered]@{
    name = if ($null -ne $cpu) { [string]$cpu.Name } else { $null }
    manufacturer = if ($null -ne $cpu) { [string]$cpu.Manufacturer } else { $null }
    virtualization_firmware_enabled = $firmwareVirtualization
    second_level_address_translation = $slat
    vm_monitor_mode_extensions = $vmMonitor
}
$evidence.hypervisor_present = $hypervisorPresent

$bcd = Invoke-Native -FilePath "$env:SystemRoot\System32\bcdedit.exe" -Arguments @('/enum', '{current}')
$evidence.bcdedit_exit_code = $bcd.exit_code
$evidence.bcdedit_output = Limit-Text -Text ([string]$bcd.output) -Maximum 8000
$hypervisorLaunchType = $null
if ($bcd.output -match '(?im)^\s*hypervisorlaunchtype\s+(\S+)') {
    $hypervisorLaunchType = [string]$Matches[1]
}
$evidence.hypervisor_launch_type = $hypervisorLaunchType

$pendingRebootSignals = @(Test-PendingReboot)
$evidence.pending_reboot = ($pendingRebootSignals.Count -gt 0)
$evidence.pending_reboot_signals = $pendingRebootSignals

$wslStatus = Invoke-Native -FilePath "$env:SystemRoot\System32\wsl.exe" -Arguments @('--status')
$evidence.wsl_status_exit_code = $wslStatus.exit_code
$evidence.wsl_status_output = Limit-Text -Text ([string]$wslStatus.output) -Maximum 8000

$systemInfo = Invoke-Native -FilePath "$env:SystemRoot\System32\systeminfo.exe"
$evidence.systeminfo_exit_code = $systemInfo.exit_code
$evidence.systeminfo_output = Limit-Text -Text ([string]$systemInfo.output) -Maximum 16000

if (-not $isAdmin) {
    $evidence.decision = 'ADMINISTRATOR_TOKEN_REQUIRED'
}
elseif ($wslFeature -ne 'Enabled' -or $vmFeature -ne 'Enabled') {
    $evidence.decision = 'WSL_FEATURES_NOT_READY'
}
elseif ($firmwareVirtualization -eq $false -and $hypervisorPresent -ne $true) {
    $evidence.decision = 'FIRMWARE_VIRTUALIZATION_DISABLED'
}
elseif ($hypervisorLaunchType -and $hypervisorLaunchType -match '^(?i:off)$') {
    $repair = Invoke-Native -FilePath "$env:SystemRoot\System32\bcdedit.exe" -Arguments @('/set', 'hypervisorlaunchtype', 'auto')
    $evidence.hypervisor_boot_repair_attempted = $true
    $evidence.hypervisor_boot_repair_exit_code = $repair.exit_code
    $evidence.hypervisor_boot_repair_output = Limit-Text -Text ([string]$repair.output) -Maximum 4000
    if ($repair.exit_code -eq 0) {
        $evidence.boot_configuration_modified = $true
        $evidence.restart_required = $true
        $evidence.decision = 'HYPERVISOR_BOOT_FLAG_REPAIRED_RESTART_REQUIRED'
    }
    else {
        $evidence.decision = 'HYPERVISOR_BOOT_FLAG_REPAIR_FAILED'
    }
}
elseif ($pendingRebootSignals.Count -gt 0 -and $hypervisorPresent -ne $true) {
    $evidence.restart_required = $true
    $evidence.decision = 'WINDOWS_RESTART_REQUIRED_FOR_VIRTUALIZATION'
}
elseif ($hypervisorPresent -eq $true) {
    $evidence.decision = 'VIRTUALIZATION_PREFLIGHT_READY'
}
elseif ($firmwareVirtualization -eq $true) {
    $evidence.restart_required = $true
    $evidence.decision = 'HYPERVISOR_NOT_ACTIVE_RESTART_REQUIRED'
}
else {
    $evidence.decision = 'VIRTUALIZATION_STATE_UNCERTAIN'
}

Write-Evidence -Target $target -Payload $evidence
$digest = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host "wsl_virtualization_decision=$($evidence.decision)"
Write-Host "restart_required=$($evidence.restart_required.ToString().ToLowerInvariant())"
Write-Host "windows_runner_paths_modified=false"
Write-Host "automatic_restart_performed=false"
Write-Host "evidence_sha256=$digest"
