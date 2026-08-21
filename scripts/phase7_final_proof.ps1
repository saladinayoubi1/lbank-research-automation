[CmdletBinding()]
param(
    [ValidateSet('Next','PrepareOnline','ExecuteOffline','SubmitReturn','Status')]
    [string]$Mode = 'Next',
    [string]$SessionId,
    [string]$Repo = 'saladinayoubi1/lbank-research-automation',
    [string]$RepoRoot = (Join-Path $env:LOCALAPPDATA 'NEXUS\lbank-research-automation')
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$ExpectedRepo = 'saladinayoubi1/lbank-research-automation'
$StateBase = Join-Path $env:LOCALAPPDATA 'NEXUS\Phase7'
$Helper = Join-Path $PSScriptRoot 'phase7_offline_laptop.ps1'

function Fail([string]$Message) {
    throw "NEXUS Phase 7 final proof: $Message"
}

function Require-Command([string]$Name) {
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $cmd) { Fail "required command '$Name' was not found" }
    return $cmd.Source
}

function Invoke-Capture([string]$File, [string[]]$Arguments, [string]$WorkingDirectory = $null) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $File
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    if ($WorkingDirectory) { $psi.WorkingDirectory = $WorkingDirectory }
    $psi.Arguments = ($Arguments | ForEach-Object {
        if ($_ -match '[\s"]') { '"' + ($_ -replace '"','\"') + '"' } else { $_ }
    }) -join ' '
    $p = New-Object System.Diagnostics.Process
    $p.StartInfo = $psi
    [void]$p.Start()
    $stdout = $p.StandardOutput.ReadToEnd()
    $stderr = $p.StandardError.ReadToEnd()
    $p.WaitForExit()
    if ($p.ExitCode -ne 0) {
        Fail "command failed ($File $($Arguments -join ' ')): $stderr$stdout"
    }
    return $stdout.Trim()
}

function Resolve-RepoRoot {
    if ($Repo -ne $ExpectedRepo) { Fail "repository must remain $ExpectedRepo" }
    if (-not (Test-Path -LiteralPath $RepoRoot -PathType Container)) {
        Fail "managed repository is missing: $RepoRoot"
    }
    $git = Require-Command 'git'
    $resolved = (Resolve-Path -LiteralPath $RepoRoot).Path
    $top = Invoke-Capture $git @('-C',$resolved,'rev-parse','--show-toplevel')
    if ((Resolve-Path -LiteralPath $top).Path -ne $resolved) { Fail 'RepoRoot must be the repository root' }
    $origin = Invoke-Capture $git @('-C',$resolved,'remote','get-url','origin')
    if ($origin -notmatch '(?i)github\.com[:/]saladinayoubi1/lbank-research-automation(?:\.git)?$') {
        Fail "managed repository origin is not canonical: $origin"
    }
    return @{ Root=$resolved; Git=$git }
}

function Sync-ExactMain([hashtable]$RepoState) {
    $status = Invoke-Capture $RepoState.Git @('-C',$RepoState.Root,'status','--porcelain=v1','--untracked-files=no')
    if ($status) { Fail 'managed repository has tracked local changes; nothing was overwritten' }
    $branch = Invoke-Capture $RepoState.Git @('-C',$RepoState.Root,'branch','--show-current')
    if ($branch -ne 'main') { Fail 'managed repository must be on main' }
    [void](Invoke-Capture $RepoState.Git @('-C',$RepoState.Root,'fetch','origin','main','--quiet'))
    $head = Invoke-Capture $RepoState.Git @('-C',$RepoState.Root,'rev-parse','HEAD')
    $origin = Invoke-Capture $RepoState.Git @('-C',$RepoState.Root,'rev-parse','origin/main')
    if ($head -ne $origin) {
        [void](Invoke-Capture $RepoState.Git @('-C',$RepoState.Root,'merge-base','--is-ancestor',$head,$origin))
        [void](Invoke-Capture $RepoState.Git @('-C',$RepoState.Root,'merge','--ff-only','origin/main'))
        $head = Invoke-Capture $RepoState.Git @('-C',$RepoState.Root,'rev-parse','HEAD')
    }
    if ($head -ne $origin -or $head -notmatch '^[0-9a-f]{40}$') { Fail 'managed repository did not converge to exact origin/main' }
    return $head
}

function Get-NexusBootTimeUtc {
    if (-not ('NexusPhase7Kernel32' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class NexusPhase7Kernel32 {
    [DllImport("kernel32.dll")]
    public static extern ulong GetTickCount64();
}
'@
    }
    $uptimeMs = [NexusPhase7Kernel32]::GetTickCount64()
    return [DateTime]::UtcNow.AddMilliseconds(-[double]$uptimeMs)
}

function Test-TcpTarget([string]$HostName, [int]$Port, [int]$TimeoutMs = 1800) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) { return $false }
        $client.EndConnect($async)
        return $true
    }
    catch { return $false }
    finally { $client.Close() }
}

function Test-InternetReachable {
    return ((Test-TcpTarget 'api.github.com' 443) -or (Test-TcpTarget '1.1.1.1' 443))
}

function Read-Session([string]$Path) {
    try { $row = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json }
    catch { Fail "invalid Phase 7 session file: $Path" }
    if ($row.schema_version -ne 'nexus.phase7-local-session.v1') { Fail "unsupported Phase 7 session schema: $Path" }
    if ($row.repository -ne $ExpectedRepo) { Fail "Phase 7 session belongs to another repository: $Path" }
    return $row
}

function Get-SessionInfo([string]$RequestedId = $null, [switch]$AllowNone) {
    if ($RequestedId) {
        $path = Join-Path (Join-Path $StateBase $RequestedId) 'session.json'
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { Fail "session '$RequestedId' was not found" }
        return @{ Id=$RequestedId; Path=$path; Data=(Read-Session $path) }
    }
    if (-not (Test-Path -LiteralPath $StateBase -PathType Container)) {
        if ($AllowNone) { return $null }
        Fail 'no Phase 7 session exists'
    }
    $rows = @()
    foreach ($dir in Get-ChildItem -LiteralPath $StateBase -Directory -ErrorAction SilentlyContinue) {
        $path = Join-Path $dir.FullName 'session.json'
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { continue }
        try {
            $data = Read-Session $path
            if ($data.completed -eq $true) { continue }
            $prepared = [DateTime]::Parse([string]$data.prepared_at).ToUniversalTime()
            $rows += [pscustomobject]@{ Id=$dir.Name; Path=$path; Data=$data; Prepared=$prepared }
        }
        catch { continue }
    }
    $selected = $rows | Sort-Object Prepared -Descending | Select-Object -First 1
    if (-not $selected) {
        if ($AllowNone) { return $null }
        Fail 'no incomplete Phase 7 session exists'
    }
    return @{ Id=$selected.Id; Path=$selected.Path; Data=$selected.Data }
}

function Invoke-Helper([string]$HelperMode, [string]$Id = $null) {
    if (-not (Test-Path -LiteralPath $Helper -PathType Leaf)) { Fail "required helper is missing: $Helper" }
    $arguments = @{ Mode=$HelperMode; Repo=$Repo; RepoRoot=$RepoRoot }
    if ($Id) { $arguments['SessionId'] = $Id }
    & $Helper @arguments
}

function Invoke-ExecuteOfflineCimIndependent([string]$Id) {
    # The owner laptop previously exhibited a broken CIM provider. The canonical
    # helper only needs Win32_OperatingSystem.LastBootUpTime, so provide that one
    # read-only value from kernel uptime while leaving the helper's proof contract
    # unchanged. No WMI/CIM repair, service, elevation or machine setting is used.
    function global:Get-CimInstance {
        param([Parameter(Position=0)]$ClassName)
        if ([string]$ClassName -ne 'Win32_OperatingSystem') {
            throw "NEXUS Phase 7 CIM compatibility shim only permits Win32_OperatingSystem"
        }
        return [pscustomobject]@{ LastBootUpTime = (Get-NexusBootTimeUtc) }
    }
    try { Invoke-Helper 'ExecuteOffline' $Id }
    finally { Remove-Item Function:\Get-CimInstance -Force -ErrorAction SilentlyContinue }
}

function Write-Action([string]$Action, [string]$Id = '') {
    Write-Host "NEXUS_PHASE7_ACTION=$Action" -ForegroundColor Yellow
    if ($Id) { Write-Host "NEXUS_PHASE7_SESSION=$Id" }
}

function Invoke-Next {
    $session = Get-SessionInfo -RequestedId $SessionId -AllowNone
    if (-not $session) {
        $repoState = Resolve-RepoRoot
        $sha = Sync-ExactMain $repoState
        Write-Host "NEXUS_PHASE7_EXACT_MAIN=$sha"
        Invoke-Helper 'PrepareOnline'
        $session = Get-SessionInfo -AllowNone
        if (-not $session) { Fail 'PrepareOnline returned without creating a session' }
        Write-Action 'DISCONNECT_INTERNET_AND_REBOOT' $session.Id
        return
    }

    $s = $session.Data
    if ($s.completed -eq $true) {
        Write-Host 'NEXUS_PHASE7_FINAL_PROOF=SUCCESS' -ForegroundColor Green
        return
    }

    $offlineResult = [string]$s.offline_result
    if (-not $offlineResult -or -not (Test-Path -LiteralPath $offlineResult -PathType Leaf)) {
        $prepared = [DateTime]::Parse([string]$s.prepared_at).ToUniversalTime()
        $boot = Get-NexusBootTimeUtc
        if ($boot -le $prepared) {
            Write-Action 'DISCONNECT_INTERNET_AND_REBOOT' $session.Id
            return
        }
        if (Test-InternetReachable) {
            Write-Action 'DISCONNECT_INTERNET' $session.Id
            return
        }
        Invoke-ExecuteOfflineCimIndependent $session.Id
        Write-Action 'RECONNECT_INTERNET' $session.Id
        return
    }

    if (-not (Test-InternetReachable)) {
        Write-Action 'RECONNECT_INTERNET' $session.Id
        return
    }
    Invoke-Helper 'SubmitReturn' $session.Id
    $final = Get-SessionInfo -RequestedId $session.Id -AllowNone
    if ($final -and $final.Data.completed -eq $true) {
        Write-Host 'NEXUS_PHASE7_FINAL_PROOF=SUCCESS' -ForegroundColor Green
        return
    }
    Fail 'SubmitReturn finished without verified completion'
}

if ($env:OS -ne 'Windows_NT') { Fail 'this launcher must run on Windows' }
if ($Repo -ne $ExpectedRepo) { Fail "repository must remain $ExpectedRepo" }

switch ($Mode) {
    'Next' { Invoke-Next }
    'PrepareOnline' {
        $repoState = Resolve-RepoRoot
        [void](Sync-ExactMain $repoState)
        Invoke-Helper 'PrepareOnline'
    }
    'ExecuteOffline' {
        $session = Get-SessionInfo -RequestedId $SessionId
        Invoke-ExecuteOfflineCimIndependent $session.Id
    }
    'SubmitReturn' {
        $session = Get-SessionInfo -RequestedId $SessionId
        Invoke-Helper 'SubmitReturn' $session.Id
    }
    'Status' {
        $session = Get-SessionInfo -RequestedId $SessionId -AllowNone
        if (-not $session) { Write-Host 'NEXUS_PHASE7_STATUS=NO_ACTIVE_SESSION'; return }
        Write-Host "NEXUS_PHASE7_STATUS=ACTIVE"
        Write-Host "NEXUS_PHASE7_SESSION=$($session.Id)"
        Write-Host "NEXUS_PHASE7_SOURCE_SHA=$($session.Data.source_sha)"
        Write-Host "NEXUS_PHASE7_COMPLETED=$([bool]$session.Data.completed)"
    }
}
