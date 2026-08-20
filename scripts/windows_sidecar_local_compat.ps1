param(
    [Parameter(Mandatory = $true)]
    [string]$SourceSha,

    [string]$OutputPath = "build/windows-sidecar-local-compat/evidence.json",

    [ValidateRange(1024, 65535)]
    [int]$Port = 18767
)

$ErrorActionPreference = "Stop"

if ($SourceSha -notmatch '^[0-9a-f]{40}$') {
    throw "SourceSha must be a lowercase 40-character commit SHA"
}

$actualSha = (& git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $actualSha -ne $SourceSha) {
    throw "physical diagnostic checkout SHA mismatch"
}

$workspace = [IO.Path]::GetFullPath((Get-Location).Path).TrimEnd('\')
$userHome = [IO.Path]::GetFullPath($env:USERPROFILE).TrimEnd('\')
if ($workspace -eq $userHome -or $workspace.StartsWith($userHome + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw "physical diagnostic workspace must not be the user profile or a descendant of it"
}

$root = Join-Path $workspace "build\windows-sidecar-local-compat"
$dist = Join-Path $root "dist"
$market = Join-Path $root "market"
$stdout = Join-Path $root "stdout.txt"
$stderr = Join-Path $root "stderr.txt"
$output = [IO.Path]::GetFullPath((Join-Path $workspace $OutputPath))
$outputParent = Split-Path -Parent $output
$productUi = Join-Path $workspace "product_ui"
$phase6Checkpoint = Join-Path $workspace ".nexus\phase6-checkpoint.json"
$projectMemoryState = Join-Path $workspace "docs\project_memory\STATE.json"
$entrypoint = Join-Path $workspace "product_offline_web_server.py"
$specFile = Join-Path $workspace "nexus-product-server.spec"

Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $specFile -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $root -Force | Out-Null
New-Item -ItemType Directory -Path $market -Force | Out-Null
New-Item -ItemType Directory -Path $outputParent -Force | Out-Null

foreach ($required in @($productUi, $phase6Checkpoint, $projectMemoryState, $entrypoint)) {
    if (!(Test-Path -LiteralPath $required)) {
        throw "physical diagnostic required source path missing"
    }
}

$buildStatus = "NOT_STARTED"
$buildErrorType = $null
try {
    & python -m pip install --disable-pip-version-check --no-input --retries 2 --timeout 30 -r requirements-dev.lock
    if ($LASTEXITCODE -ne 0) { throw "requirements-dev.lock installation failed" }
    & python -m pip install --disable-pip-version-check --no-input --retries 2 --timeout 30 -r requirements-product-build.lock
    if ($LASTEXITCODE -ne 0) { throw "requirements-product-build.lock installation failed" }

    & python -m PyInstaller `
        --noconfirm `
        --clean `
        --onedir `
        --distpath $dist `
        --workpath (Join-Path $root "pyinstaller-work") `
        --specpath $workspace `
        --name nexus-product-server `
        --add-data "product_ui;product_ui" `
        --add-data ".nexus\phase6-checkpoint.json;.nexus" `
        --add-data "docs\project_memory\STATE.json;docs/project_memory" `
        "product_offline_web_server.py"
    $pyInstallerExit = $LASTEXITCODE
    Remove-Item -LiteralPath $specFile -Force -ErrorAction SilentlyContinue
    if ($pyInstallerExit -ne 0) { throw "PyInstaller sidecar build failed" }
    $buildStatus = "SUCCESS"
} catch {
    Remove-Item -LiteralPath $specFile -Force -ErrorAction SilentlyContinue
    $buildStatus = "FAILURE"
    $buildErrorType = $_.Exception.GetType().Name
}

$exe = Join-Path $dist "nexus-product-server\nexus-product-server.exe"
$status = if ($buildStatus -eq "SUCCESS") { "UNKNOWN" } else { "BUILD_FAILURE" }
$exitCode = $null
$overviewOk = $false
$spawnErrorType = $null
$server = $null
$startedAt = (Get-Date).ToUniversalTime()

if ($buildStatus -eq "SUCCESS") {
    if (!(Test-Path -LiteralPath $exe -PathType Leaf)) {
        $status = "BUILD_OUTPUT_MISSING"
    } else {
        $env:NEXUS_SOURCE_SHA = $SourceSha
        $env:NEXUS_MARKET_REGISTRY_PATH = Join-Path $workspace "docs\architecture\market-data-source-registry.yaml"
        $env:NEXUS_AGENT_MANAGER_CONFIG = Join-Path $workspace "config\nexus-agent-manager.json"
        Remove-Item Env:NEXUS_BUILD_EVIDENCE_PATH -ErrorAction SilentlyContinue

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
                    # Bounded loopback startup polling only.
                }
                Start-Sleep -Milliseconds 250
            }
            if ($status -eq "UNKNOWN") { $status = "TIMEOUT" }
        } catch {
            $status = "SPAWN_ERROR"
            $spawnErrorType = $_.Exception.GetType().Name
        } finally {
            if ($server -and -not $server.HasExited) {
                Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
            }
            if ($server -and $server.HasExited -and $null -eq $exitCode) {
                $exitCode = [int64]$server.ExitCode
            }
        }
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
    # Application Event Log metadata is advisory only.
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
    # A broken CIM/WMI repository must not erase native process evidence.
}

$exitHex = $null
if ($null -ne $exitCode) {
    $unsignedExit = [uint64]([int64]$exitCode -band 0xffffffffL)
    $exitHex = ('0x{0:X8}' -f $unsignedExit)
}

$stderrText = ''
if (Test-Path -LiteralPath $stderr -PathType Leaf) {
    $stderrText = (Get-Content -LiteralPath $stderr -Tail 80 -ErrorAction SilentlyContinue | Out-String)
    if ($null -eq $stderrText) { $stderrText = '' }
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
    contract_version = "nexus.windows-sidecar-local-compat.v1"
    source_sha = $SourceSha
    build_status = $buildStatus
    build_error_type = $buildErrorType
    status = $status
    overview_ok = $overviewOk
    process_exit_code = $exitCode
    process_exit_hex = $exitHex
    spawn_error_type = $spawnErrorType
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
    exact_source_checkout = $true
    binary_origin = "physical-runner-local-build"
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
}

$result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $output -Encoding utf8
Get-Content -LiteralPath $output

if ($status -ne "SUCCESS" -or $overviewOk -ne $true) {
    throw "physical sidecar compatibility failed: build=$buildStatus status=$status exit=$exitHex module=$($fault.faulting_module)"
}
