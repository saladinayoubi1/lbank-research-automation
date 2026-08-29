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
    $json = $Payload | ConvertTo-Json -Depth 12
    [IO.File]::WriteAllText($Target, $json, (New-Object Text.UTF8Encoding($false)))
}

function Get-NativeProcessorFeatures {
    $result = [ordered]@{
        available = $false
        virtualization_firmware_enabled = $null
        second_level_address_translation = $null
        error = $null
    }
    try {
        if (-not ('Nexus.NativeProcessorFeatures' -as [type])) {
            Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace Nexus {
    public static class NativeProcessorFeatures {
        [DllImport("kernel32.dll")]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool IsProcessorFeaturePresent(uint processorFeature);
    }
}
'@ -ErrorAction Stop
        }
        # PF_SECOND_LEVEL_ADDRESS_TRANSLATION = 20
        # PF_VIRT_FIRMWARE_ENABLED = 21
        $result.available = $true
        $result.second_level_address_translation = [bool][Nexus.NativeProcessorFeatures]::IsProcessorFeaturePresent(20)
        $result.virtualization_firmware_enabled = [bool][Nexus.NativeProcessorFeatures]::IsProcessorFeaturePresent(21)
    }
    catch {
        $result.error = $_.Exception.ToString()
    }
    return $result
}

function Invoke-LightweightWsl2Probe {
    param([Parameter(Mandatory = $true)][string]$RunId)

    $probeName = "NEXUS-WSL2-PROBE-$RunId"
    $probeRoot = Join-Path $env:ProgramData "NEXUS\WSLProbe\$RunId"
    $rootfs = Join-Path $probeRoot 'rootfs'
    $installRoot = Join-Path $probeRoot 'install'
    $archive = Join-Path $probeRoot 'rootfs.tar'
    $tarPath = Join-Path $env:SystemRoot 'System32\tar.exe'
    $wslPath = Join-Path $env:SystemRoot 'System32\wsl.exe'

    $result = [ordered]@{
        attempted = $false
        distribution_name = $probeName
        install_root = $installRoot
        tar_available = (Test-Path -LiteralPath $tarPath)
        tar_exit_code = $null
        tar_output = $null
        import_exit_code = $null
        import_output = $null
        unregister_exit_code = $null
        unregister_output = $null
        cleanup_complete = $false
    }

    if (-not $result.tar_available) {
        return $result
    }

    try {
        Remove-Item -LiteralPath $probeRoot -Recurse -Force -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Path (Join-Path $rootfs 'etc') -Force | Out-Null
        [IO.File]::WriteAllText((Join-Path $rootfs 'etc\nexus-wsl2-probe'), "nexus-wsl2-virtualization-probe`n", (New-Object Text.UTF8Encoding($false)))

        $tar = Invoke-Native -FilePath $tarPath -Arguments @('-cf', $archive, '-C', $rootfs, '.')
        $result.tar_exit_code = $tar.exit_code
        $result.tar_output = Limit-Text -Text ([string]$tar.output) -Maximum 4000
        if ($tar.exit_code -ne 0) {
            return $result
        }

        New-Item -ItemType Directory -Path $installRoot -Force | Out-Null
        $result.attempted = $true
        $import = Invoke-Native -FilePath $wslPath -Arguments @('--import', $probeName, $installRoot, $archive, '--version', '2')
        $result.import_exit_code = $import.exit_code
        $result.import_output = Limit-Text -Text ([string]$import.output) -Maximum 8000

        if ($import.exit_code -eq 0) {
            $unregister = Invoke-Native -FilePath $wslPath -Arguments @('--unregister', $probeName)
            $result.unregister_exit_code = $unregister.exit_code
            $result.unregister_output = Limit-Text -Text ([string]$unregister.output) -Maximum 4000
        }
    }
    finally {
        Remove-Item -LiteralPath $probeRoot -Recurse -Force -ErrorAction SilentlyContinue
        $result.cleanup_complete = -not (Test-Path -LiteralPath $probeRoot)
    }
    return $result
}

$target = [IO.Path]::GetFullPath($OutputPath)
$isAdmin = Test-IsAdministrator
$evidence = [ordered]@{
    schema_version = 2
    generated_at_utc = [DateTime]::UtcNow.ToString('o')
    source_sha = $env:GITHUB_SHA
    run_id = $env:GITHUB_RUN_ID
    administrator = $isAdmin
    windows_runner_paths_modified = $false
    automatic_restart_performed = $false
    restart_required = $false
    boot_configuration_modified = $false
    transient_service_start_attempted = $false
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
$evidence.cim_processor_error = $null
$evidence.cim_computer_system_error = $null
try { $cpu = Get-CimInstance Win32_Processor -ErrorAction Stop | Select-Object -First 1 } catch { $evidence.cim_processor_error = $_.Exception.ToString() }
try { $computerSystem = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop } catch { $evidence.cim_computer_system_error = $_.Exception.ToString() }

$wmiCpu = $null
$wmiComputerSystem = $null
$evidence.wmi_processor_error = $null
$evidence.wmi_computer_system_error = $null
if ($null -eq $cpu) {
    try { $wmiCpu = Get-WmiObject -Class Win32_Processor -ErrorAction Stop | Select-Object -First 1 } catch { $evidence.wmi_processor_error = $_.Exception.ToString() }
}
if ($null -eq $computerSystem) {
    try { $wmiComputerSystem = Get-WmiObject -Class Win32_ComputerSystem -ErrorAction Stop } catch { $evidence.wmi_computer_system_error = $_.Exception.ToString() }
}

$processorObject = if ($null -ne $cpu) { $cpu } else { $wmiCpu }
$systemObject = if ($null -ne $computerSystem) { $computerSystem } else { $wmiComputerSystem }

$firmwareVirtualization = $null
$slat = $null
$vmMonitor = $null
if ($null -ne $processorObject) {
    if ($processorObject.PSObject.Properties.Name -contains 'VirtualizationFirmwareEnabled') {
        $firmwareVirtualization = [bool]$processorObject.VirtualizationFirmwareEnabled
    }
    if ($processorObject.PSObject.Properties.Name -contains 'SecondLevelAddressTranslationExtensions') {
        $slat = [bool]$processorObject.SecondLevelAddressTranslationExtensions
    }
    if ($processorObject.PSObject.Properties.Name -contains 'VMMonitorModeExtensions') {
        $vmMonitor = [bool]$processorObject.VMMonitorModeExtensions
    }
}

$nativeFeatures = Get-NativeProcessorFeatures
if ($null -eq $firmwareVirtualization -and $nativeFeatures.available) {
    $firmwareVirtualization = [bool]$nativeFeatures.virtualization_firmware_enabled
}
if ($null -eq $slat -and $nativeFeatures.available) {
    $slat = [bool]$nativeFeatures.second_level_address_translation
}
$evidence.native_processor_features = $nativeFeatures

$cpuRegistry = $null
try {
    $cpuRegistry = Get-ItemProperty 'HKLM:\HARDWARE\DESCRIPTION\System\CentralProcessor\0' -ErrorAction Stop
}
catch { }
$evidence.cpu = [ordered]@{
    name = if ($null -ne $processorObject) { [string]$processorObject.Name } elseif ($null -ne $cpuRegistry) { [string]$cpuRegistry.ProcessorNameString } else { $null }
    manufacturer = if ($null -ne $processorObject) { [string]$processorObject.Manufacturer } elseif ($null -ne $cpuRegistry) { [string]$cpuRegistry.VendorIdentifier } else { $null }
    identifier = if ($null -ne $cpuRegistry) { [string]$cpuRegistry.Identifier } else { $null }
    virtualization_firmware_enabled = $firmwareVirtualization
    second_level_address_translation = $slat
    vm_monitor_mode_extensions = $vmMonitor
}

$hypervisorPresent = $null
if ($null -ne $systemObject -and ($systemObject.PSObject.Properties.Name -contains 'HypervisorPresent')) {
    $hypervisorPresent = [bool]$systemObject.HypervisorPresent
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

$wslList = Invoke-Native -FilePath "$env:SystemRoot\System32\wsl.exe" -Arguments @('--list', '--verbose')
$evidence.wsl_list_exit_code = $wslList.exit_code
$evidence.wsl_list_output = Limit-Text -Text ([string]$wslList.output) -Maximum 8000

$systemInfo = Invoke-Native -FilePath "$env:SystemRoot\System32\systeminfo.exe"
$evidence.systeminfo_exit_code = $systemInfo.exit_code
$evidence.systeminfo_output = Limit-Text -Text ([string]$systemInfo.output) -Maximum 16000

$vmcompute = Invoke-Native -FilePath "$env:SystemRoot\System32\sc.exe" -Arguments @('query', 'vmcompute')
$lxssManager = Invoke-Native -FilePath "$env:SystemRoot\System32\sc.exe" -Arguments @('query', 'LxssManager')
$evidence.services = [ordered]@{
    vmcompute_query_exit_code = $vmcompute.exit_code
    vmcompute_query_output = Limit-Text -Text ([string]$vmcompute.output) -Maximum 6000
    lxssmanager_query_exit_code = $lxssManager.exit_code
    lxssmanager_query_output = Limit-Text -Text ([string]$lxssManager.output) -Maximum 6000
}

$hyperVEvents = Invoke-Native -FilePath "$env:SystemRoot\System32\wevtutil.exe" -Arguments @('qe', 'Microsoft-Windows-Hyper-V-Hypervisor-Admin', '/c:20', '/rd:true', '/f:text')
$evidence.hyperv_hypervisor_events_exit_code = $hyperVEvents.exit_code
$evidence.hyperv_hypervisor_events_output = Limit-Text -Text ([string]$hyperVEvents.output) -Maximum 16000

if (-not $isAdmin) {
    $evidence.decision = 'ADMINISTRATOR_TOKEN_REQUIRED'
}
elif ($wslFeature -ne 'Enabled' -or $vmFeature -ne 'Enabled') {
    $evidence.decision = 'WSL_FEATURES_NOT_READY'
}
elif ($hypervisorLaunchType -and $hypervisorLaunchType -match '^(?i:off)$') {
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
elif ($slat -eq $false) {
    $evidence.decision = 'WSL2_SLAT_UNAVAILABLE'
}
elif ($firmwareVirtualization -eq $false) {
    $evidence.decision = 'FIRMWARE_VIRTUALIZATION_DISABLED'
}
else {
    if ($vmcompute.exit_code -eq 0 -and $vmcompute.output -notmatch '(?i)STATE\s*:\s*\d+\s+RUNNING') {
        $serviceStart = Invoke-Native -FilePath "$env:SystemRoot\System32\sc.exe" -Arguments @('start', 'vmcompute')
        $evidence.transient_service_start_attempted = $true
        $evidence.vmcompute_start_exit_code = $serviceStart.exit_code
        $evidence.vmcompute_start_output = Limit-Text -Text ([string]$serviceStart.output) -Maximum 6000
        Start-Sleep -Seconds 2
        $vmcomputeAfter = Invoke-Native -FilePath "$env:SystemRoot\System32\sc.exe" -Arguments @('query', 'vmcompute')
        $evidence.vmcompute_after_start_exit_code = $vmcomputeAfter.exit_code
        $evidence.vmcompute_after_start_output = Limit-Text -Text ([string]$vmcomputeAfter.output) -Maximum 6000
    }

    if ($pendingRebootSignals.Count -gt 0 -and $hypervisorPresent -ne $true) {
        $evidence.restart_required = $true
        $evidence.decision = 'WINDOWS_RESTART_REQUIRED_FOR_VIRTUALIZATION'
    }
    else {
        $probeRunId = if ([string]::IsNullOrWhiteSpace([string]$env:GITHUB_RUN_ID)) { [Guid]::NewGuid().ToString('N') } else { [string]$env:GITHUB_RUN_ID }
        $wsl2Probe = Invoke-LightweightWsl2Probe -RunId $probeRunId
        $evidence.wsl2_probe = $wsl2Probe

        if ($wsl2Probe.attempted -and $wsl2Probe.import_exit_code -eq 0 -and $wsl2Probe.unregister_exit_code -eq 0) {
            $evidence.decision = 'VIRTUALIZATION_PREFLIGHT_READY'
        }
        elseif ($wsl2Probe.import_output -match '(?i)kernel component update|update to its kernel component') {
            $evidence.decision = 'WSL2_KERNEL_NOT_READY'
        }
        elseif ($wsl2Probe.import_output -match '(?i)virtual machine platform|virtualization is enabled in the bios|virtualization.*bios') {
            if ($firmwareVirtualization -eq $true) {
                $evidence.restart_required = $true
                $evidence.decision = 'HYPERVISOR_NOT_ACTIVE_RESTART_REQUIRED'
            }
            elseif ($firmwareVirtualization -eq $false) {
                $evidence.decision = 'FIRMWARE_VIRTUALIZATION_DISABLED'
            }
            else {
                $evidence.decision = 'VIRTUALIZATION_STATE_UNCERTAIN'
            }
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
    }
}

Write-Evidence -Target $target -Payload $evidence
$digest = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host "wsl_virtualization_decision=$($evidence.decision)"
Write-Host "restart_required=$($evidence.restart_required.ToString().ToLowerInvariant())"
Write-Host "windows_runner_paths_modified=false"
Write-Host "automatic_restart_performed=false"
Write-Host "evidence_sha256=$digest"
