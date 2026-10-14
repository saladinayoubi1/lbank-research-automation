
$ErrorActionPreference = 'Stop'
$auditRoot = 'E:\NEXUS-QA\economic-oracle-v6-20261013'
$workerTemp = 'C:\Users\afaq\AppData\Local\Temp\nexus_v6_decimal_audit_20261013.py'
$configTemp = 'C:\Users\afaq\AppData\Local\Temp\nexus_v6_decimal_audit_20261013.input.json'
$oracleSource = 'E:\NEXUS-QA\economic-oracle-v5-reconnect-20261013-0208\nexus_composite_fill_oracle.py'
$pythonPath = 'E:\NEXUS-QA\native-v5-independent-20261012-1604\.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $auditRoot) { throw 'v6 accounting root already exists; inspect without replay' }
if ((Get-FileHash -LiteralPath $workerTemp -Algorithm SHA256).Hash.ToLowerInvariant() -ne '62b37e8ca201d9bc7afd4ef3b94f42d6aaf3f2f38467990eec8bd84c07ea9a7f') { throw 'v6 accounting worker byte hash mismatch' }
if ((Get-FileHash -LiteralPath $configTemp -Algorithm SHA256).Hash.ToLowerInvariant() -ne '7df564fc4787f04b2670b92ac2f96d58a28d578bdbf7d6818f4e2caf4aaf2c68') { throw 'v6 accounting input byte hash mismatch' }
if (!(Test-Path -LiteralPath 'E:\NEXUS-QA\jump-v6-day-cache-qa-final-20261013\qa-evidence.json')) { throw 'Completed v6 numeric QA proof missing' }
$null = New-Item -ItemType Directory -Path $auditRoot
Copy-Item -LiteralPath $workerTemp -Destination ($auditRoot + '\run-audit.py')
Copy-Item -LiteralPath $configTemp -Destination ($auditRoot + '\audit-input.json')
Copy-Item -LiteralPath $oracleSource -Destination ($auditRoot + '\nexus_composite_fill_oracle.py')
[pscustomobject]@{prepared=$true;root=$auditRoot;worker_sha256='62b37e8ca201d9bc7afd4ef3b94f42d6aaf3f2f38467990eec8bd84c07ea9a7f';original_study_source='8899ec6bec4927fc39795f2867be91e2431178c6';accounting_cells=12;prior_v5_jobs_rerun=$false;source_simulator_called=$false;bounded_seconds=600;checked_at_utc=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json -Compress
& $pythonPath -u ($auditRoot + '\run-audit.py') 2>&1 | Tee-Object -FilePath ($auditRoot + '\stdout-native.log')
$auditExitCode = $LASTEXITCODE
[System.IO.File]::WriteAllText(($auditRoot + '\process-exit.txt'), ('NATIVE_EXIT=' + $auditExitCode + [Environment]::NewLine), (New-Object System.Text.UTF8Encoding($false)))
[pscustomobject]@{native_exit_code=$auditExitCode;root=$auditRoot;finished_at_utc=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json -Compress
exit $auditExitCode
