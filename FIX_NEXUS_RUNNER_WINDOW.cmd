@echo off
setlocal
cd /d "%~dp0"
set "NEXUS_DEFERRED_MIGRATION=%~dp0scripts\defer_nexus_runner_hidden_migration.ps1"
if not exist "%NEXUS_DEFERRED_MIGRATION%" (
  echo NEXUS deferred hidden runner migration script is missing.
  pause
  exit /b 2
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$psi=New-Object System.Diagnostics.ProcessStartInfo; $psi.FileName=(Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'); if(-not (Test-Path -LiteralPath $psi.FileName)){ $psi.FileName='powershell.exe' }; $psi.UseShellExecute=$false; $psi.CreateNoWindow=$true; $psi.WindowStyle=[System.Diagnostics.ProcessWindowStyle]::Hidden; $psi.Arguments='-NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"%NEXUS_DEFERRED_MIGRATION%\"'; $p=New-Object System.Diagnostics.Process; $p.StartInfo=$psi; if(-not $p.Start()){ exit 3 }; Write-Host 'NEXUS hidden runner migration scheduled. Active GitHub jobs will not be interrupted.' -ForegroundColor Green; exit 0"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo NEXUS deferred runner window repair could not be started.
  pause
  exit /b %RC%
)
timeout /t 3 /nobreak >nul
exit /b 0
