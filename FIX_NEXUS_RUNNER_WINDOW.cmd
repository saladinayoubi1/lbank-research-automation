@echo off
setlocal
cd /d "%~dp0"
set "NEXUS_HIDDEN_RUNNER_SCRIPT=%~dp0scripts\install_nexus_runner_hidden_autostart.ps1"
if not exist "%NEXUS_HIDDEN_RUNNER_SCRIPT%" (
  echo NEXUS hidden runner autostart repair script is missing.
  pause
  exit /b 2
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%NEXUS_HIDDEN_RUNNER_SCRIPT%" -Mode Install
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" pause
exit /b %RC%
