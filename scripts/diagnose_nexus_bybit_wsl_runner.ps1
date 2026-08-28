param(
    [string]$OutputPath = "build\bybit-wsl-runner-diagnostic\evidence.json"
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Get-OptionalFeatureState {
    param([Parameter(Mandatory = $true)][string]$Name)

    try {
        $feature = Get-WindowsOptionalFeature -Online -FeatureName $Name -ErrorAction Stop
        return [string]$feature.State
    }
    catch {
        return 'Unknown'
    }
}

function Invoke-WslProbe {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    try {
        $text = (& wsl.exe @Arguments 2>&1 | Out-String).Trim()
        $code = $LASTEXITCODE
        return [ordered]@{
            exit_code = $code
            output = $text
        }
    }
    catch {
        return [ordered]@{
            exit_code = -1
            output = $_.Exception.GetType().Name
        }
    }
}

function Invoke-BybitPublicProbe {
    $uri = 'https://api.bybit.com/v5/market/time'
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $response = Invoke-WebRequest -Uri $uri -UseBasicParsing -TimeoutSec 20 -Headers @{
            'User-Agent' = 'NEXUS-public-paper-network-probe/1.0'
        }
        $payload = $response.Content | ConvertFrom-Json
        $retCode = [int]$payload.retCode
        return [ordered]@{
            endpoint = $uri
            http_status = [int]$response.StatusCode
            ret_code = $retCode
            reachable = ($response.StatusCode -eq 200 -and $retCode -eq 0)
            error_class = $null
        }
    }
    catch {
        $status = $null
        if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
            $status = [int]$_.Exception.Response.StatusCode
        }
        return [ordered]@{
            endpoint = $uri
            http_status = $status
            ret_code = $null
            reachable = $false
            error_class = $_.Exception.GetType().Name
        }
    }
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$serviceSidPrefixes = @('S-1-5-18', 'S-1-5-19', 'S-1-5-20')
$isServiceIdentity = $serviceSidPrefixes -contains $identity.User.Value

$wslFeature = Get-OptionalFeatureState -Name 'Microsoft-Windows-Subsystem-Linux'
$vmFeature = Get-OptionalFeatureState -Name 'VirtualMachinePlatform'
$wslStatus = Invoke-WslProbe -Arguments @('--status')
$wslList = Invoke-WslProbe -Arguments @('--list', '--verbose')
$bybit = Invoke-BybitPublicProbe

$wslReady = (
    $wslFeature -eq 'Enabled' -and
    $vmFeature -eq 'Enabled' -and
    $wslStatus.exit_code -eq 0 -and
    $wslList.exit_code -eq 0
)

$decision = if (-not $bybit.reachable) {
    'BYBIT_NETWORK_NOT_ELIGIBLE'
}
elseif ($wslReady) {
    'READY_FOR_LINUX_RUNNER_REGISTRATION'
}
elseif (-not $isAdmin) {
    'ADMIN_REQUIRED_FOR_WSL_ENABLEMENT'
}
else {
    'WSL_ENABLEMENT_REQUIRED'
}

$evidence = [ordered]@{
    schema_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString('o')
    source_sha = $env:GITHUB_SHA
    run_id = $env:GITHUB_RUN_ID
    runner = [ordered]@{
        os = $env:RUNNER_OS
        architecture = $env:RUNNER_ARCH
        environment = $env:RUNNER_ENVIRONMENT
        administrator = $isAdmin
        service_identity = $isServiceIdentity
    }
    windows = [ordered]@{
        wsl_feature = $wslFeature
        virtual_machine_platform = $vmFeature
    }
    wsl = [ordered]@{
        ready = $wslReady
        status = $wslStatus
        distributions = $wslList
    }
    bybit_public_mainnet = $bybit
    private_credentials_used = $false
    proxy_or_vpn_configured = $false
    decision = $decision
}

$target = [IO.Path]::GetFullPath($OutputPath)
$parent = Split-Path -Parent $target
New-Item -ItemType Directory -Path $parent -Force | Out-Null
$json = $evidence | ConvertTo-Json -Depth 8
[IO.File]::WriteAllText($target, $json, (New-Object Text.UTF8Encoding($false)))
$digest = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()

Write-Host "bybit_wsl_runner_decision=$decision"
Write-Host "bybit_public_reachable=$($bybit.reachable.ToString().ToLowerInvariant())"
Write-Host "wsl_ready=$($wslReady.ToString().ToLowerInvariant())"
Write-Host "administrator=$($isAdmin.ToString().ToLowerInvariant())"
Write-Host "evidence_sha256=$digest"

