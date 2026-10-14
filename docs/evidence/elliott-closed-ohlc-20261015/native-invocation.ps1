$ErrorActionPreference = 'Stop'
$elliottStage = 'E:\NEXUS-QA\elliott-closed-ohlc-20261015'
$elliottPython = 'E:\NEXUS-QA\strategy-frontier-v5-20261010\.venv\Scripts\python.exe'
$elliottPayloadPath = Join-Path $elliottStage 'stage-source.json'
$elliottReceiptPath = Join-Path $elliottStage 'native-test-receipt.json'
$elliottExpectedPayload = 'b8a914fe05ca4c4eeec756fc3e48dbda0f1fba9d3e12af6d1bfc181723460d78'
$elliottEncoding = New-Object System.Text.UTF8Encoding($false)
if (Test-Path -LiteralPath $elliottReceiptPath) { throw 'Native receipt already exists; do not replay this gate' }
if (-not (Test-Path -LiteralPath $elliottPython)) { throw 'Existing research Python is unavailable' }
$elliottPayloadHash = ([string](Get-FileHash -LiteralPath $elliottPayloadPath -Algorithm SHA256).Hash).ToLowerInvariant()
if ($elliottPayloadHash -ne $elliottExpectedPayload) { throw 'Staged payload SHA256 mismatch' }
$elliottPayload = [IO.File]::ReadAllText($elliottPayloadPath) | ConvertFrom-Json
if ($elliottPayload.files.Count -ne 6) { throw 'Unexpected source closure' }
$elliottInputHashes = @()
foreach ($elliottSource in $elliottPayload.files) {
    $elliottRelative = [string]$elliottSource.path
    if ($elliottRelative.Contains('..') -or [IO.Path]::IsPathRooted($elliottRelative)) { throw 'Invalid source path' }
    $elliottTarget = Join-Path $elliottStage $elliottRelative
    if (Test-Path -LiteralPath $elliottTarget) { throw 'Frozen source already exists; inspect this stage' }
    $elliottDirectory = [IO.Path]::GetDirectoryName($elliottTarget)
    if (-not (Test-Path -LiteralPath $elliottDirectory)) { New-Item -ItemType Directory -Path $elliottDirectory | Out-Null }
    [IO.File]::WriteAllBytes($elliottTarget, [Convert]::FromBase64String([string]$elliottSource.base64))
    $elliottSourceHash = ([string](Get-FileHash -LiteralPath $elliottTarget -Algorithm SHA256).Hash).ToLowerInvariant()
    if ($elliottSourceHash -ne [string]$elliottSource.sha256) { throw 'Extracted source SHA256 mismatch' }
    $elliottInputHashes += [pscustomobject]@{ path = $elliottRelative; sha256 = $elliottSourceHash }
}
$elliottStarted = [DateTime]::UtcNow
$elliottWatch = [Diagnostics.Stopwatch]::StartNew()
$elliottStart = New-Object Diagnostics.ProcessStartInfo
$elliottStart.FileName = $elliottPython
$elliottStart.WorkingDirectory = $elliottStage
$elliottWorker = "import json,sys,platform,unittest,numpy,pandas; suite=unittest.defaultTestLoader.discover('.',pattern='test_*.py'); result=unittest.TextTestRunner(verbosity=2).run(suite); print(json.dumps(dict(python=platform.python_version(),numpy=numpy.__version__,pandas=pandas.__version__,tests_run=result.testsRun,failures=len(result.failures),errors=len(result.errors)))); sys.exit(0 if result.wasSuccessful() else 1)"
$elliottStart.Arguments = '-I -c "' + $elliottWorker + '"'
$elliottStart.UseShellExecute = $false
$elliottStart.CreateNoWindow = $true
$elliottStart.RedirectStandardOutput = $true
$elliottStart.RedirectStandardError = $true
$elliottChild = New-Object Diagnostics.Process
$elliottChild.StartInfo = $elliottStart
if (-not $elliottChild.Start()) { throw 'Owned child failed to start' }
$elliottChildPid = $elliottChild.Id
$elliottOutTask = $elliottChild.StandardOutput.ReadToEndAsync()
$elliottErrTask = $elliottChild.StandardError.ReadToEndAsync()
$elliottTimedOut = -not $elliottChild.WaitForExit(30000)
if ($elliottTimedOut) { $elliottChild.Kill(); $elliottChild.WaitForExit() }
$elliottExitCode = $elliottChild.ExitCode
$elliottStdout = [string]$elliottOutTask.Result
$elliottStderr = [string]$elliottErrTask.Result
[IO.File]::WriteAllText((Join-Path $elliottStage 'native-test-stdout.txt'), $elliottStdout, $elliottEncoding)
[IO.File]::WriteAllText((Join-Path $elliottStage 'native-test-stderr.txt'), $elliottStderr, $elliottEncoding)
$elliottAfterHashes = @()
foreach ($elliottInput in $elliottInputHashes) {
    $elliottAfterHash = ([string](Get-FileHash -LiteralPath (Join-Path $elliottStage $elliottInput.path) -Algorithm SHA256).Hash).ToLowerInvariant()
    $elliottAfterHashes += [pscustomobject]@{ path = [string]$elliottInput.path; sha256 = $elliottAfterHash; unchanged = ($elliottAfterHash -eq [string]$elliottInput.sha256) }
}
$elliottWorkerReceipt = $null
if ($elliottStdout.Trim()) { $elliottWorkerReceipt = $elliottStdout.Trim() | ConvertFrom-Json }
$elliottWatch.Stop()
$elliottReceipt = [ordered]@{
    schema = 'elliott-five-swing-native-tests/v1'
    device = 'DESKTOP-F4SA4VL'
    device_id = '61c3307f-e6d4-4edf-860a-3519cfb9df5d'
    stage = $elliottStage
    python = $elliottPython
    started_at = $elliottStarted.ToString('o')
    completed_at = [DateTime]::UtcNow.ToString('o')
    duration_seconds = $elliottWatch.Elapsed.TotalSeconds
    owned_child_pid = $elliottChildPid
    actual_exit_code = $elliottExitCode
    timed_out = $elliottTimedOut
    payload_sha256 = $elliottPayloadHash
    invocation_sha256 = ([string](Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash).ToLowerInvariant()
    worker_result = $elliottWorkerReceipt
    source_hashes = $elliottInputHashes
    postrun_source_hashes = $elliottAfterHashes
    stdout_sha256 = ([string](Get-FileHash -LiteralPath (Join-Path $elliottStage 'native-test-stdout.txt') -Algorithm SHA256).Hash).ToLowerInvariant()
    stderr_sha256 = ([string](Get-FileHash -LiteralPath (Join-Path $elliottStage 'native-test-stderr.txt') -Algorithm SHA256).Hash).ToLowerInvariant()
    market_replays = 0
    factory_registered = $false
    execution_integrated = $false
    live = $false
}
$elliottReceiptJson = $elliottReceipt | ConvertTo-Json -Depth 8
[IO.File]::WriteAllText($elliottReceiptPath, $elliottReceiptJson, $elliottEncoding)
Write-Output $elliottReceiptJson
if ($elliottTimedOut -or $elliottExitCode -ne 0) { exit 1 }
if (@($elliottAfterHashes | Where-Object { -not $_.unchanged }).Count -ne 0) { throw 'Source changed during tests' }
