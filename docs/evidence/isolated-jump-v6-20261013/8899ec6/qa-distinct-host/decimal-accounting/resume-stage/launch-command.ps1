
$ErrorActionPreference = 'Stop'
$auditRoot = 'E:\NEXUS-QA\economic-oracle-v6-day-cache-20261013'
$previousRoot = 'E:\NEXUS-QA\economic-oracle-v6-20261013'
$pythonPath = 'E:\NEXUS-QA\native-v5-independent-20261012-1604\.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $auditRoot) { throw 'Resumed accounting root exists; inspect without relaunch' }
if ((Get-Content -LiteralPath ($previousRoot + '\process-exit.txt') -Raw).Trim() -ne 'NATIVE_EXIT=124') { throw 'Original accounting process is not fenced at its verified terminal exit' }
$payloads = @(
 @('C:\Users\afaq\AppData\Local\Temp\nexus_v6_decimal_resume_20261013.py','run-audit.py','241bb1d641d318792da6379dff7a62b917ef20cd4c6b7f547fed41747a468654'),
 @('C:\Users\afaq\AppData\Local\Temp\nexus_v6_decimal_resume_20261013.input.json','audit-input.json','094ad00eb0440fd736422585ae77052e6235d392fa2d2070a32121a9d354da2a'),
 @('C:\Users\afaq\AppData\Local\Temp\nexus_v6_decimal_cached_oracle_20261013.py','nexus_composite_fill_oracle.py','5c51c9e28bb8732784194735f4fe6f01abdf5a26477e2e2291efde039e8420f7'),
 @('C:\Users\afaq\AppData\Local\Temp\nexus_v6_decimal_goldens_20261013.json','scalar-decimal-goldens.json','991ea68568b21a94386fceec2eb1dd2af22f0c5971aab0ffc64c25eab85c6cc8'),
 @('C:\Users\afaq\AppData\Local\Temp\nexus_v6_decimal_cache_regression_20261013.py','check_day_cache.py','2fe43e01693ab40bf96bb325e92541aa8654f9a9dde016a5f8eee31f5c747be7')
)
foreach ($payload in $payloads) {
 if ((Get-FileHash -LiteralPath $payload[0] -Algorithm SHA256).Hash.ToLowerInvariant() -ne $payload[2]) { throw ('Prepared audit bytes changed: ' + $payload[1]) }
}
$null = New-Item -ItemType Directory -Path $auditRoot
foreach ($payload in $payloads) { Copy-Item -LiteralPath $payload[0] -Destination ($auditRoot + '\' + $payload[1]) }
[pscustomobject]@{prepared=$true;root=$auditRoot;reused_accounting_cells=3;new_accounting_cells=9;native_regression_required=$true;worker_sha256='241bb1d641d318792da6379dff7a62b917ef20cd4c6b7f547fed41747a468654';oracle_source_ref='b6c6efb3cdf7ceb6e23a117df43c6803604b6187';bounded_seconds=600;checked_at_utc=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json -Compress
& $pythonPath -u ($auditRoot + '\run-audit.py') 2>&1 | Tee-Object -FilePath ($auditRoot + '\stdout-native.log')
$auditExitCode = $LASTEXITCODE
[System.IO.File]::WriteAllText(($auditRoot + '\process-exit.txt'), ('NATIVE_EXIT=' + $auditExitCode + [Environment]::NewLine), (New-Object System.Text.UTF8Encoding($false)))
[pscustomobject]@{native_exit_code=$auditExitCode;root=$auditRoot;finished_at_utc=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json -Compress
exit $auditExitCode
