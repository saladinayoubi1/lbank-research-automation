param(
    [Parameter(Mandatory = $true)]
    [string]$BundleRoot,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedSourceSha,

    [string]$OutputPath = "build/windows-sidecar-physical-compat/evidence.json",

    [ValidateRange(1024, 65535)]
    [int]$Port = 18767
)

$ErrorActionPreference = "Stop"

if ($ExpectedSourceSha -notmatch '^[0-9a-f]{40}$') {
    throw "ExpectedSourceSha must be a lowercase 40-character commit SHA"
}

$bundle = (Resolve-Path -LiteralPath $BundleRoot -ErrorAction Stop).Path
$exe = Join-Path $bundle "nexus-product-server\nexus-product-server.exe"
$registry = Join-Path $bundle "market-data-source-registry.yaml"
$agent = Join-Path $bundle "nexus-agent-manager.json"
$buildEvidence = Join-Path $bundle "build-evidence.json"
$sourceShaPath = Join-Path $bundle "source-sha.txt"

foreach ($path in @($exe, $registry, $agent, $buildEvidence, $sourceShaPath)) {
    if (!(Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "diagnostic bundle missing required file"
    }
}

$bundleSha = (Get-Content -LiteralPath $sourceShaPath -Raw -ErrorAction Stop).Trim()
$build = Get-Content -LiteralPath $buildEvidence -Raw -ErrorAction Stop | ConvertFrom-Json
if ($bundleSha -ne $ExpectedSourceSha -or $build.source_sha -ne $ExpectedSourceSha) {
    throw "diagnostic bundle source SHA does not match the trusted main build"
}
if ($build.paper_only -ne $true -or $build.live_trading_authority -ne $false) {
    throw "diagnostic bundle authority evidence is not Paper-only"
}

$probeRoot = Join-Path $env:RUNNER_TEMP ("nexus-sidecar-probe-" + $env:GITHUB_RUN_ID)
Remove-Item -LiteralPath $probeRoot -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $probeRoot -Force | Out-Null
$market = Join-Path $probeRoot "market"
New-Item -ItemType Directory -Path $market -Force | Out-Null
$stdout = Join-Path $probeRoot "stdout.txt"
$stderr = Join-Path $probeRoot "stderr.txt"
$startedAt = (Get-Date).ToUniversalTime()

$env:NEXUS_SOURCE_SHA = $ExpectedSourceSha
$env:NEXUS_MARKET_REGISTRY_PATH = $registry
$env:NEXUS_AGENT_MANAGER_CONFIG = $agent
$env:NEXUS_BUILD_EVIDENCE_PATH = $buildEvidence

$status = "UNKNOWN"
$exitCode = $null
$overviewOk = $false
$server = $null
$spawnError = $null

try {
    $server = Start-Process -FilePath $exe -ArgumentList @(
        "--host", "127.0.0.1",
        "--port", [string]$Port,
        "--data-root", $market
    ) -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr

    for ($i = 0; $i -lt 80; $i++) {
        if ($server.HasExited) {
            $exitCode = [int64]$server.ExitCode
            $status = "EXITED_BEFORE_READY"
            break
        }
        try {
            $payload = Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/api/product/overview" -f $Port) -TimeoutSec 2
            if ($payload.paper.active -eq $true -and $payload.live.enabled -eq $false) {
                $overviewOk = $true
                $status = "SUCCESS"
                break
            }
        } catch {
            # Startup polling is intentionally bounded and local-only.
        }
        Start-Sleep -Milliseconds 250
    }
    if ($status -eq "UNKNOWN") {
        $status = "TIMEOUT"
    }
} catch {
    $status = "SPAWN_ERROR"
    $spawnError = $_.Exception.GetType().Name
} finally {
    if ($server -and -not $server.HasExited) {
        Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
    }
    if ($server -and $server.HasExited -and $null -eq $exitCode) {
        $exitCode = [int64]$server.ExitCode
    }
}

$fault = $null
try {
    $event = Get-WinEvent -FilterHashtable @{
        LogName = 'Application'
        Id = 1000
        StartTime = $startedAt.AddMinutes(-1)
    } -ErrorAction Stop |
        Where-Object { $_.Message -match 'nexus-product-server\.exe' } |
        Select-Object -First 1

    if ($event) {
        [xml]$xml = $event.ToXml()
        $values = @($xml.Event.EventData.Data | ForEach-Object { [string]$_.'#text' })
        $fault = [ordered]@{
            event_id = [int]$event.Id
            application = if ($values.Count -gt 0) { $values[0] } else { $null }
            application_version = if ($values.Count -gt 1) { $values[1] } else { $null }
            faulting_module = if ($values.Count -gt 3) { $values[3] } else { $null }
            faulting_module_version = if ($values.Count -gt 4) { $values[4] } else { $null }
            exception_code = if ($values.Count -gt 6) { $values[6] } else { $null }
            exception_offset = if ($values.Count -gt 7) { $values[7] } else { $null }
        }
    }
} catch {
    # Event Log access is advisory. The process result remains authoritative.
}

$osVersion = [Environment]::OSVersion.Version.ToString()
$osBuild = [string][Environment]::OSVersion.Version.Build
$osArchitecture = [string]$env:PROCESSOR_ARCHITECTURE
$totalVisibleMemoryMb = $null
$freePhysicalMemoryMb = $null
$osProbe = "environment-fallback"
try {
    $os = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
    if ($os) {
        $osVersion = [string]$os.Version
        $osBuild = [string]$os.BuildNumber
        $osArchitecture = [string]$os.OSArchitecture
        $totalVisibleMemoryMb = [Math]::Round(([double]$os.TotalVisibleMemorySize / 1024), 0)
        $freePhysicalMemoryMb = [Math]::Round(([double]$os.FreePhysicalMemory / 1024), 0)
        $osProbe = "cim"
    }
} catch {
    # Some owner Windows images have a broken WMI/CIM repository. Do not lose
    # the native crash evidence because optional OS metadata is unavailable.
}

$exitHex = $null
if ($null -ne $exitCode) {
    $unsignedExit = [uint64]([int64]$exitCode -band 0xffffffffL)
    $exitHex = ('0x{0:X8}' -f $unsignedExit)
}

$stderrText = ''
if (Test-Path -LiteralPath $stderr -PathType Leaf) {
    $stderrText = (Get-Content -LiteralPath $stderr -Tail 80 -ErrorAction SilentlyContinue | Out-String)
    if ($null -eq $stderrText) {
        $stderrText = ''
    }
}
foreach ($sensitiveRoot in @($env:USERPROFILE, $env:RUNNER_TEMP, $env:GITHUB_WORKSPACE)) {
    if (![string]::IsNullOrWhiteSpace($sensitiveRoot)) {
        $stderrText = $stderrText -replace [regex]::Escape($sensitiveRoot), '<redacted-path>'
    }
}
$stderrText = $stderrText -replace '[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', ''
if ($stderrText.Length -gt 1600) {
    $stderrText = $stderrText.Substring($stderrText.Length - 1600)
}

$result = [ordered]@{
    contract_version = "nexus.windows-sidecar-physical-compat.v1"
    source_sha = $ExpectedSourceSha
    status = $status
    overview_ok = $overviewOk
    process_exit_code = $exitCode
    process_exit_hex = $exitHex
    spawn_error_type = $spawnError
    stderr_tail = $stderrText
    fault = $fault
    os_probe = $osProbe
    os_version = $osVersion
    os_build = $osBuild
    os_architecture = $osArchitecture
    total_visible_memory_mb = $totalVisibleMemoryMb
    free_physical_memory_mb = $freePhysicalMemoryMb
    paper_only = $true
    live_trading_authority = $false
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
}

$output = [IO.Path]::GetFullPath((Join-Path (Get-Location) $OutputPath))
$outputParent = Split-Path -Parent $output
New-Item -ItemType Directory -Path $outputParent -Force | Out-Null
$result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $output -Encoding utf8
Get-Content -LiteralPath $output

if ($status -ne "SUCCESS" -or $overviewOk -ne $true) {
    throw "physical sidecar compatibility failed: status=$status exit=$exitHex module=$($fault.faulting_module)"
}
