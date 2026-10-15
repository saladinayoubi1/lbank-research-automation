$ErrorActionPreference = 'Stop'
$elliottStage = 'E:\NEXUS-QA\elliott-backtest-adapter-20261015'
$elliottSource = Join-Path $elliottStage 'source'
$elliottPython = 'E:\NEXUS-QA\strategy-frontier-v5-20261010\.venv\Scripts\python.exe'
$elliottReceiptPath = Join-Path $elliottStage 'native-process-receipt.json'
$elliottEncoding = New-Object System.Text.UTF8Encoding($false)
if ((Test-Path -LiteralPath $elliottReceiptPath) -or (Test-Path -LiteralPath $elliottSource)) { throw 'Existing gate/source; do not replay' }
function ElliottHash([string]$elliottPath) { return ([string](Get-FileHash -LiteralPath $elliottPath -Algorithm SHA256).Hash).ToLowerInvariant() }
if ((ElliottHash (Join-Path $elliottStage 'stage-source.json')) -ne '796080b32a9240ef5400e804d8e7ce11ced6def048d8dd1935a5a354ba471c2a') { throw 'Payload differs' }
if ((ElliottHash (Join-Path $elliottStage 'source-gate-worker.py')) -ne 'f6c4220aa635f156817136bbe073977096a5339e0c5b0bd1f138bff3be08ec30') { throw 'Worker differs' }
if ((ElliottHash (Join-Path $elliottStage 'source-hashes.json')) -ne 'd0511e84a5fcad8de132b1a6e93f853173a14274b69cb43159c164c3503aeced') { throw 'Binding differs' }
$elliottPayload = [IO.File]::ReadAllText((Join-Path $elliottStage 'stage-source.json')) | ConvertFrom-Json
$elliottNames = @($elliottPayload.source_file_sha256.PSObject.Properties.Name)
if ($elliottNames.Count -ne 50) { throw 'Source closure differs' }
$elliottZipPath = Join-Path $elliottStage 'source.zip'
[IO.File]::WriteAllBytes($elliottZipPath, [Convert]::FromBase64String([string]$elliottPayload.zip_base64))
if ((ElliottHash $elliottZipPath) -ne [string]$elliottPayload.zip_sha256) { throw 'Source ZIP differs' }
Add-Type -AssemblyName System.IO.Compression.FileSystem
$elliottZip = [IO.Compression.ZipFile]::OpenRead($elliottZipPath)
try {
    if ($elliottZip.Entries.Count -ne 50) { throw 'Unexpected ZIP entries' }
    foreach ($elliottEntry in $elliottZip.Entries) {
        if ($elliottEntry.FullName.Contains('..') -or [IO.Path]::IsPathRooted($elliottEntry.FullName) -or $elliottEntry.FullName -notin $elliottNames) { throw 'Unexpected source path' }
    }
} finally { $elliottZip.Dispose() }
[IO.Compression.ZipFile]::ExtractToDirectory($elliottZipPath, $elliottSource)
foreach ($elliottFile in $elliottPayload.source_file_sha256.PSObject.Properties) {
    if ((ElliottHash (Join-Path $elliottSource $elliottFile.Name)) -ne [string]$elliottFile.Value) { throw 'Extracted source differs' }
}
$elliottStarted = [DateTime]::UtcNow
$elliottWatch = [Diagnostics.Stopwatch]::StartNew()
$elliottStart = New-Object Diagnostics.ProcessStartInfo
$elliottStart.FileName = $elliottPython
$elliottStart.WorkingDirectory = $elliottStage
$elliottStart.Arguments = '-I -B "' + (Join-Path $elliottStage 'source-gate-worker.py') + '" --native'
$elliottStart.UseShellExecute = $false
$elliottStart.CreateNoWindow = $true
$elliottStart.RedirectStandardOutput = $true
$elliottStart.RedirectStandardError = $true
$elliottChild = New-Object Diagnostics.Process
$elliottChild.StartInfo = $elliottStart
if (-not $elliottChild.Start()) { throw 'Owned test child did not start' }
$elliottChildPid = $elliottChild.Id
$elliottOutTask = $elliottChild.StandardOutput.ReadToEndAsync()
$elliottErrTask = $elliottChild.StandardError.ReadToEndAsync()
$elliottTimedOut = -not $elliottChild.WaitForExit(180000)
if ($elliottTimedOut) { $elliottChild.Kill(); $elliottChild.WaitForExit() }
$elliottExitCode = $elliottChild.ExitCode
$elliottStdout = [string]$elliottOutTask.Result
$elliottStderr = [string]$elliottErrTask.Result
[IO.File]::WriteAllText((Join-Path $elliottStage 'native-test-stdout.txt'), $elliottStdout, $elliottEncoding)
[IO.File]::WriteAllText((Join-Path $elliottStage 'native-test-stderr.txt'), $elliottStderr, $elliottEncoding)
$elliottSummary = $null
if ($elliottStdout.Trim()) { $elliottSummary = $elliottStdout.Trim() | ConvertFrom-Json }
$elliottWorkerReceiptHash = $null
if (Test-Path -LiteralPath (Join-Path $elliottStage 'test-worker-receipt.json')) { $elliottWorkerReceiptHash = ElliottHash (Join-Path $elliottStage 'test-worker-receipt.json') }
$elliottWatch.Stop()
$elliottReceipt = [ordered]@{
    schema = 'elliott-five-swing-adapter-native-process/v1'
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
    source_files = 50
    payload_sha256 = ElliottHash (Join-Path $elliottStage 'stage-source.json')
    invocation_sha256 = ElliottHash $PSCommandPath
    worker_sha256 = ElliottHash (Join-Path $elliottStage 'source-gate-worker.py')
    source_binding_sha256 = ElliottHash (Join-Path $elliottStage 'source-hashes.json')
    worker_receipt_sha256 = $elliottWorkerReceiptHash
    worker_result = $elliottSummary
    stdout_sha256 = ElliottHash (Join-Path $elliottStage 'native-test-stdout.txt')
    stderr_sha256 = ElliottHash (Join-Path $elliottStage 'native-test-stderr.txt')
    market_replays = 0
    live_enabled = $false
}
$elliottJson = $elliottReceipt | ConvertTo-Json -Depth 8
[IO.File]::WriteAllText($elliottReceiptPath, $elliottJson, $elliottEncoding)
Write-Output $elliottJson
if ($elliottTimedOut -or $elliottExitCode -ne 0) { exit 1 }
