[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('PrepareOnline','ExecuteOffline','SubmitReturn')]
    [string]$Mode,

    [string]$SessionId,
    [string]$Repo = 'saladinayoubi1/lbank-research-automation',
    [string]$RepoRoot = (Get-Location).Path
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$ExpectedRepo = 'saladinayoubi1/lbank-research-automation'
$Workflow = 'NEXUS Mission Queue'
$CourierSecret = 'NEXUS_OFFLINE_COURIER_KEY'
$StateBase = Join-Path $env:LOCALAPPDATA 'NEXUS\Phase7'
$PreparedFiles = @(
    'agent-manager-runtime.json',
    'manager-state.json',
    'phase7-supervisor-state.sqlite3',
    'manager-events.jsonl',
    'phase7-e2e-proof.json',
    'phase7-proof-mission-run.json',
    'courier\phase7-laptop-dispatch.json'
)

function Fail([string]$Message) {
    throw "NEXUS Phase 7: $Message"
}

function UtcNow {
    return [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
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
        throw "command failed ($File $($Arguments -join ' ')): $stderr$stdout"
    }
    return $stdout.Trim()
}

function Invoke-SecretStdin([string]$SecretValue) {
    $gh = Require-Command 'gh'
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $gh
    $psi.Arguments = "secret set $CourierSecret --repo $Repo"
    $psi.UseShellExecute = $false
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $p = New-Object System.Diagnostics.Process
    $p.StartInfo = $psi
    [void]$p.Start()
    $p.StandardInput.Write($SecretValue)
    $p.StandardInput.Close()
    $stdout = $p.StandardOutput.ReadToEnd()
    $stderr = $p.StandardError.ReadToEnd()
    $p.WaitForExit()
    if ($p.ExitCode -ne 0) { Fail "GitHub secret update failed: $stderr$stdout" }
}

function New-RandomKey {
    $bytes = New-Object byte[] 48
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return [Convert]::ToBase64String($bytes)
}

function New-SessionId {
    $bytes = New-Object byte[] 4
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $suffix = -join ($bytes | ForEach-Object { $_.ToString('x2') })
    return 'p7-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' + $suffix
}

function Protect-Key([string]$Value, [string]$Path) {
    Add-Type -AssemblyName System.Security
    $plain = [Text.Encoding]::UTF8.GetBytes($Value)
    try {
        $protected = [Security.Cryptography.ProtectedData]::Protect(
            $plain,
            $null,
            [Security.Cryptography.DataProtectionScope]::CurrentUser
        )
        [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($Path)) | Out-Null
        [IO.File]::WriteAllBytes($Path, $protected)
    }
    finally {
        [Array]::Clear($plain, 0, $plain.Length)
    }
}

function Unprotect-Key([string]$Path) {
    Add-Type -AssemblyName System.Security
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { Fail 'DPAPI Courier key is missing' }
    $protected = [IO.File]::ReadAllBytes($Path)
    $plain = [Security.Cryptography.ProtectedData]::Unprotect(
        $protected,
        $null,
        [Security.Cryptography.DataProtectionScope]::CurrentUser
    )
    try { return [Text.Encoding]::UTF8.GetString($plain) }
    finally { [Array]::Clear($plain, 0, $plain.Length) }
}

function Get-PythonCommand {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return @($python.Source) }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { return @($py.Source, '-3') }
    Fail 'Python 3 is required before Phase 7 preparation'
}

function Invoke-Python([string[]]$PythonCommand, [string[]]$Arguments, [string]$WorkingDirectory) {
    $exe = $PythonCommand[0]
    $prefix = @()
    if ($PythonCommand.Count -gt 1) { $prefix = $PythonCommand[1..($PythonCommand.Count-1)] }
    return Invoke-Capture $exe ($prefix + $Arguments) $WorkingDirectory
}

function Get-RepoState {
    $git = Require-Command 'git'
    if ($Repo -ne $ExpectedRepo) { Fail "repository must remain $ExpectedRepo" }
    $root = (Resolve-Path -LiteralPath $RepoRoot).Path
    $inside = Invoke-Capture $git @('-C',$root,'rev-parse','--show-toplevel')
    if ((Resolve-Path -LiteralPath $inside).Path -ne $root) { Fail 'RepoRoot must be the repository root' }
    $status = Invoke-Capture $git @('-C',$root,'status','--porcelain=v1')
    if ($status) { Fail 'repository working tree must be clean' }
    $branch = Invoke-Capture $git @('-C',$root,'branch','--show-current')
    if ($branch -ne 'main') { Fail 'Prepare/Execute must run from the main branch' }
    return @{ Root = $root; Git = $git }
}

function Assert-ExactMain([hashtable]$RepoState, [switch]$Fetch) {
    if ($Fetch) { [void](Invoke-Capture $RepoState.Git @('-C',$RepoState.Root,'fetch','origin','main','--quiet')) }
    $head = Invoke-Capture $RepoState.Git @('-C',$RepoState.Root,'rev-parse','HEAD')
    $origin = Invoke-Capture $RepoState.Git @('-C',$RepoState.Root,'rev-parse','origin/main')
    if ($head -ne $origin) { Fail 'local main is not the exact current origin/main' }
    if ($head -notmatch '^[0-9a-f]{40}$') { Fail 'invalid main SHA' }
    return $head
}

function Test-TcpTarget([string]$HostName, [int]$Port, [int]$TimeoutMs = 2500) {
    $client = New-Object System.Net.Sockets.TcpClient
    $reachable = $false
    $errorText = ''
    try {
        $async = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) {
            $errorText = 'timeout'
        } else {
            $client.EndConnect($async)
            $reachable = $true
        }
    }
    catch { $errorText = $_.Exception.GetType().Name + ': ' + $_.Exception.Message }
    finally { $client.Close() }
    return [ordered]@{ host=$HostName; port=$Port; reachable=$reachable; error=$errorText }
}

function Get-NetworkObservation {
    $targets = @(
        (Test-TcpTarget 'api.github.com' 443),
        (Test-TcpTarget '1.1.1.1' 443)
    )
    $reachable = @($targets | Where-Object { $_.reachable -eq $true }).Count
    return [ordered]@{
        checked_at = UtcNow
        internet_unavailable = ($reachable -eq 0)
        targets = $targets
    }
}

function Load-Session([string]$Id) {
    if (-not $Id) { Fail 'SessionId is required for this mode' }
    $sessionRoot = Join-Path $StateBase $Id
    $sessionPath = Join-Path $sessionRoot 'session.json'
    if (-not (Test-Path -LiteralPath $sessionPath -PathType Leaf)) { Fail "session '$Id' was not found" }
    $session = Get-Content -LiteralPath $sessionPath -Raw | ConvertFrom-Json
    if ($session.schema_version -ne 'nexus.phase7-local-session.v1') { Fail 'local session schema mismatch' }
    if ($session.repository -ne $ExpectedRepo) { Fail 'local session repository mismatch' }
    return @{ Root=$sessionRoot; Path=$sessionPath; Data=$session }
}

function Save-Session([hashtable]$SessionInfo) {
    $SessionInfo.Data | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $SessionInfo.Path -Encoding UTF8
}

function Read-ProofRun([string]$ArtifactDir) {
    $path = Join-Path $ArtifactDir 'phase7-proof-mission-run.json'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { Fail 'Phase 7 proof run artifact is missing' }
    return Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
}

function Prepare-Online {
    Require-Command 'gh' | Out-Null
    $repoState = Get-RepoState
    $sourceSha = Assert-ExactMain $repoState -Fetch
    [void](Invoke-Capture 'gh' @('auth','status','--hostname','github.com'))

    $python = Get-PythonCommand
    [void](Invoke-Python $python @('--version') $repoState.Root)
    $id = New-SessionId
    $sessionRoot = Join-Path $StateBase $id
    New-Item -ItemType Directory -Force -Path $sessionRoot | Out-Null
    $keyPath = Join-Path $sessionRoot 'courier-key.dpapi'
    $secret = New-RandomKey
    try {
        Protect-Key $secret $keyPath
        Invoke-SecretStdin $secret
    }
    finally { $secret = $null }

    $venv = Join-Path $sessionRoot 'venv'
    [void](Invoke-Python $python @('-m','venv',$venv) $repoState.Root)
    $venvPython = Join-Path $venv 'Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) { Fail 'offline virtual environment creation failed' }
    [void](Invoke-Capture $venvPython @('-m','pip','install','-r',(Join-Path $repoState.Root 'requirements-dev.lock')) $repoState.Root)
    [void](Invoke-Capture $venvPython @('-m','pip','check') $repoState.Root)

    $started = [DateTime]::UtcNow.AddSeconds(-5)
    [void](Invoke-Capture 'gh' @('workflow','run',$Workflow,'--ref','main','--repo',$Repo))
    $run = $null
    for ($i=0; $i -lt 30 -and -not $run; $i++) {
        Start-Sleep -Seconds 2
        $json = Invoke-Capture 'gh' @('run','list','--repo',$Repo,'--workflow',$Workflow,'--branch','main','--event','workflow_dispatch','--commit',$sourceSha,'--limit','20','--json','databaseId,headSha,status,conclusion,createdAt,workflowName')
        $rows = @($json | ConvertFrom-Json)
        $run = $rows | Where-Object {
            $_.headSha -eq $sourceSha -and [DateTime]::Parse($_.createdAt).ToUniversalTime() -ge $started
        } | Sort-Object databaseId -Descending | Select-Object -First 1
    }
    if (-not $run) { Fail 'could not identify the exact-source Mission Queue workflow_dispatch run' }
    $runId = [int64]$run.databaseId
    [void](Invoke-Capture 'gh' @('run','watch',"$runId",'--repo',$Repo,'--exit-status'))

    $artifactName = "nexus-phase7-proof-$sourceSha"
    $artifactDir = Join-Path $sessionRoot 'prepared-proof'
    if (Test-Path $artifactDir) { Remove-Item -LiteralPath $artifactDir -Recurse -Force }
    New-Item -ItemType Directory -Path $artifactDir | Out-Null
    [void](Invoke-Capture 'gh' @('run','download',"$runId",'--repo',$Repo,'--name',$artifactName,'--dir',$artifactDir))
    $proof = Read-ProofRun $artifactDir
    if ($proof.source_sha -ne $sourceSha) { Fail 'downloaded proof is not bound to exact main SHA' }
    if ($proof.paper_only -ne $true -or $proof.live_trading_authority -ne $false) { Fail 'downloaded proof widened authority' }
    if ($proof.core_cloud_chain_complete -ne $true -or $proof.hardware_proof_complete -ne $false) { Fail 'prepared proof state is invalid' }
    if ($proof.courier.status -ne 'EXPORTED') { Fail "Courier was not exported; status=$($proof.courier.status)" }
    if (-not $proof.zero_idle_evidence) { Fail 'prepared proof lacks zero-idle evidence' }
    $dispatch = Join-Path $artifactDir 'courier\phase7-laptop-dispatch.json'
    if (-not (Test-Path -LiteralPath $dispatch -PathType Leaf)) { Fail 'Courier dispatch bundle is missing' }

    $preparedAt = UtcNow
    $sessionData = [ordered]@{
        schema_version = 'nexus.phase7-local-session.v1'
        session_id = $id
        repository = $Repo
        repo_root = $repoState.Root
        source_sha = $sourceSha
        prepared_at = $preparedAt
        proof_run_id = $runId
        prepared_artifact_name = $artifactName
        artifact_dir = $artifactDir
        courier_dispatch = $dispatch
        key_path = $keyPath
        venv_python = $venvPython
        offline_result = $null
        offline_network_proof = $null
        return_pr = $null
        completed = $false
    }
    $info = @{ Root=$sessionRoot; Path=(Join-Path $sessionRoot 'session.json'); Data=[pscustomobject]$sessionData }
    Save-Session $info
    Write-Host "NEXUS Phase 7 prepared: $id"
    Write-Host 'Disconnect internet completely, reboot Windows, then run:'
    Write-Host ".\scripts\phase7_offline_laptop.ps1 -Mode ExecuteOffline -SessionId $id"
}

function Execute-Offline {
    $info = Load-Session $SessionId
    $s = $info.Data
    $repoState = Get-RepoState
    $head = Invoke-Capture $repoState.Git @('-C',$repoState.Root,'rev-parse','HEAD')
    if ($head -ne $s.source_sha) { Fail 'repository HEAD changed after preparation' }
    $boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime()
    $prepared = [DateTime]::Parse($s.prepared_at).ToUniversalTime()
    if ($boot -le $prepared) { Fail 'Windows must be rebooted after PrepareOnline before the offline proof can run' }

    $pre = Get-NetworkObservation
    if ($pre.internet_unavailable -ne $true) { Fail 'internet is still reachable; disconnect it before ExecuteOffline' }
    $started = UtcNow
    $result = Join-Path $info.Root 'phase7-laptop-result.json'
    $key = Unprotect-Key $s.key_path
    $oldKey = $env:NEXUS_OFFLINE_COURIER_KEY
    try {
        $env:NEXUS_OFFLINE_COURIER_KEY = $key
        [void](Invoke-Capture $s.venv_python @('-m','offline_agent_courier','execute','--input',$s.courier_dispatch,'--output',$result) $repoState.Root)
    }
    finally {
        $env:NEXUS_OFFLINE_COURIER_KEY = $oldKey
        $key = $null
    }
    if (-not (Test-Path -LiteralPath $result -PathType Leaf)) { Fail 'offline execution did not produce a result bundle' }
    $finished = UtcNow
    $post = Get-NetworkObservation
    if ($post.internet_unavailable -ne $true) { Fail 'internet became reachable during offline execution; proof rejected' }
    $resultSha = (Get-FileHash -LiteralPath $result -Algorithm SHA256).Hash.ToLowerInvariant()
    $networkPath = Join-Path $info.Root 'offline-network-proof.json'
    $network = [ordered]@{
        schema_version = 'nexus.phase7-offline-network-proof.v1'
        session_id = $s.session_id
        source_sha = $s.source_sha
        prepared_at = $s.prepared_at
        boot_time_utc = $boot.ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
        reboot_after_prepare = $true
        pre_execution = $pre
        execution_started_at = $started
        execution_finished_at = $finished
        post_execution = $post
        result_sha256 = $resultSha
        observation_method = 'bounded_tcp_connect_dual_target_v1'
    }
    $network | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $networkPath -Encoding UTF8
    [void](Invoke-Capture $s.venv_python @('-c',"import phase7_offline_network_proof as p; p.validate_offline_network_proof(r'$($networkPath.Replace("'","''"))', r'$($result.Replace("'","''"))', expected_source_sha='$($s.source_sha)', expected_session_id='$($s.session_id)'); print('offline_network_proof_valid=true')") $repoState.Root)
    $s.offline_result = $result
    $s.offline_network_proof = $networkPath
    Save-Session $info
    Write-Host 'Offline workload completed with internet unavailable before and after execution.'
    Write-Host 'Reconnect internet, then run:'
    Write-Host ".\scripts\phase7_offline_laptop.ps1 -Mode SubmitReturn -SessionId $SessionId"
}

function Copy-PreparedPayload([pscustomobject]$Session, [string]$PackageRoot) {
    foreach ($relative in $PreparedFiles) {
        $source = Join-Path $Session.artifact_dir $relative
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { Fail "prepared proof file missing: $relative" }
        $destination = Join-Path (Join-Path $PackageRoot 'prepared') $relative
        $parent = Split-Path -Parent $destination
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
        Copy-Item -LiteralPath $source -Destination $destination -Force
    }
}

function Submit-Return {
    Require-Command 'gh' | Out-Null
    $info = Load-Session $SessionId
    $s = $info.Data
    if (-not $s.offline_result -or -not (Test-Path -LiteralPath $s.offline_result -PathType Leaf)) { Fail 'offline result is missing' }
    if (-not $s.offline_network_proof -or -not (Test-Path -LiteralPath $s.offline_network_proof -PathType Leaf)) { Fail 'offline network proof is missing' }
    [void](Invoke-Capture 'gh' @('auth','status','--hostname','github.com'))
    $repoState = Get-RepoState
    [void](Invoke-Capture $repoState.Git @('-C',$repoState.Root,'fetch','origin','main','--quiet'))
    [void](Invoke-Capture $repoState.Git @('-C',$repoState.Root,'merge-base','--is-ancestor',$s.source_sha,'origin/main'))

    $packageRoot = Join-Path $info.Root 'return-package'
    if (Test-Path $packageRoot) { Remove-Item -LiteralPath $packageRoot -Recurse -Force }
    New-Item -ItemType Directory -Force -Path (Join-Path $packageRoot 'returned') | Out-Null
    Copy-PreparedPayload $s $packageRoot
    Copy-Item -LiteralPath $s.offline_result -Destination (Join-Path $packageRoot 'returned\phase7-laptop-result.json') -Force
    Copy-Item -LiteralPath $s.offline_network_proof -Destination (Join-Path $packageRoot 'returned\offline-network-proof.json') -Force
    [void](Invoke-Capture $s.venv_python @('-m','scripts.phase7_build_return_manifest','--package-root',$packageRoot,'--session-id',$s.session_id,'--source-sha',$s.source_sha,'--proof-run-id',"$($s.proof_run_id)",'--prepared-artifact-name',$s.prepared_artifact_name) $repoState.Root)
    [void](Invoke-Capture $s.venv_python @('-m','scripts.phase7_return_package','--package-root',$packageRoot,'--expected-source-sha',$s.source_sha) $repoState.Root)

    $branch = "phase7/return-$($s.session_id)"
    $worktree = Join-Path $info.Root 'return-worktree'
    if (Test-Path $worktree) { [void](Invoke-Capture $repoState.Git @('-C',$repoState.Root,'worktree','remove','--force',$worktree)) }
    [void](Invoke-Capture $repoState.Git @('-C',$repoState.Root,'branch','-D',$branch) 2>$null)
    [void](Invoke-Capture $repoState.Git @('-C',$repoState.Root,'worktree','add','-b',$branch,$worktree,$s.source_sha))
    try {
        $target = Join-Path $worktree ".nexus\phase7-return\$($s.session_id)"
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
        Copy-Item -LiteralPath $packageRoot -Destination $target -Recurse -Force
        [void](Invoke-Capture $repoState.Git @('-C',$worktree,'add',".nexus/phase7-return/$($s.session_id)"))
        $changed = (Invoke-Capture $repoState.Git @('-C',$worktree,'diff','--cached','--name-only')).Split([Environment]::NewLine,[StringSplitOptions]::RemoveEmptyEntries)
        if ($changed.Count -eq 0) { Fail 'return package produced no staged files' }
        foreach ($path in $changed) {
            if (-not $path.StartsWith(".nexus/phase7-return/$($s.session_id)/")) { Fail "return branch contains non-data change: $path" }
        }
        [void](Invoke-Capture $repoState.Git @('-C',$worktree,'-c','user.name=NEXUS Phase7 Courier','-c','user.email=nexus-phase7@users.noreply.github.com','commit','-m',"Phase 7 returned laptop proof $($s.session_id)"))
        $returnSha = Invoke-Capture $repoState.Git @('-C',$worktree,'rev-parse','HEAD')
        [void](Invoke-Capture $repoState.Git @('-C',$worktree,'push','-u','origin',$branch))
        $prUrl = Invoke-Capture 'gh' @('pr','create','--repo',$Repo,'--base','main','--head',$branch,'--title',"[Phase 7 Return] $($s.session_id)",'--body',"Data-only Offline Courier return. Source SHA: $($s.source_sha). Do not merge; Mission Queue independently verifies and publishes a completed proof artifact.")
        $prNumber = [int]($prUrl.TrimEnd('/') -split '/')[-1]
        $s.return_pr = $prNumber
        Save-Session $info
        [void](Invoke-Capture 'gh' @('pr','checks',"$prNumber",'--repo',$Repo,'--watch'))

        $run = $null
        for ($i=0; $i -lt 30 -and -not $run; $i++) {
            Start-Sleep -Seconds 2
            $json = Invoke-Capture 'gh' @('run','list','--repo',$Repo,'--workflow',$Workflow,'--branch',$branch,'--event','pull_request','--commit',$returnSha,'--limit','20','--json','databaseId,headSha,status,conclusion,createdAt')
            $run = @($json | ConvertFrom-Json) | Where-Object { $_.headSha -eq $returnSha } | Sort-Object databaseId -Descending | Select-Object -First 1
        }
        if (-not $run) { Fail 'verified return workflow run could not be identified' }
        $verifiedDir = Join-Path $info.Root 'verified-proof'
        if (Test-Path $verifiedDir) { Remove-Item -LiteralPath $verifiedDir -Recurse -Force }
        New-Item -ItemType Directory -Path $verifiedDir | Out-Null
        $verifiedArtifact = "nexus-phase7-return-verified-$($s.session_id)"
        [void](Invoke-Capture 'gh' @('run','download',"$($run.databaseId)",'--repo',$Repo,'--name',$verifiedArtifact,'--dir',$verifiedDir))
        $finalRunPath = Join-Path $verifiedDir 'phase7-proof-mission-run.json'
        if (-not (Test-Path -LiteralPath $finalRunPath -PathType Leaf)) { Fail 'completed hardware proof artifact is missing' }
        $final = Get-Content -LiteralPath $finalRunPath -Raw | ConvertFrom-Json
        if ($final.hardware_proof_complete -ne $true -or $final.manager_summary.verified_progress_percent -ne 100) { Fail 'hardware proof did not reach verified 100%' }
        if ($final.resource_classification.Laptop.classification -ne 'EXECUTED') { Fail 'Laptop resource was not classified EXECUTED' }
        if ($final.offline_network_proof.reboot_after_prepare -ne $true -or $final.offline_network_proof.internet_unavailable_pre -ne $true -or $final.offline_network_proof.internet_unavailable_post -ne $true) { Fail 'completed proof lacks real offline evidence' }

        [void](Invoke-Capture 'gh' @('secret','delete',$CourierSecret,'--repo',$Repo))
        Remove-Item -LiteralPath $s.key_path -Force -ErrorAction SilentlyContinue
        [void](Invoke-Capture 'gh' @('pr','close',"$prNumber",'--repo',$Repo,'--delete-branch'))
        $s.completed = $true
        $s.completed_at = UtcNow
        $s.verified_artifact_dir = $verifiedDir
        Save-Session $info
        Write-Host "Phase 7 laptop proof VERIFIED: 100% ($verifiedArtifact)"
    }
    finally {
        if (Test-Path $worktree) {
            try { [void](Invoke-Capture $repoState.Git @('-C',$repoState.Root,'worktree','remove','--force',$worktree)) } catch { }
        }
    }
}

if ($env:OS -ne 'Windows_NT') { Fail 'this helper must run on Windows' }
if ($Repo -ne $ExpectedRepo) { Fail "repository must remain $ExpectedRepo" }

switch ($Mode) {
    'PrepareOnline' { Prepare-Online }
    'ExecuteOffline' { Execute-Offline }
    'SubmitReturn' { Submit-Return }
    default { Fail 'unsupported mode' }
}
