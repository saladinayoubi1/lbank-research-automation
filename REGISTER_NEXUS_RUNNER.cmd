@echo off
setlocal
cd /d "%~dp0"
set "NEXUS_RUNNER_SCRIPT=%~dp0scripts\register_nexus_runner_interactive.ps1"
if not exist "%NEXUS_RUNNER_SCRIPT%" (
  echo NEXUS runner registration script is missing.
  pause
  exit /b 2
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%NEXUS_RUNNER_SCRIPT%"
set "RC=%ERRORLEVEL%"
exit /b %RC%
