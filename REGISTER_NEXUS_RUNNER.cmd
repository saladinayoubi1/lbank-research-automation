@echo off
setlocal
cd /d "%~dp0"
set "NEXUS_RUNNER_SCRIPT=%~dp0scripts\register_nexus_runner_interactive.ps1"
set "NEXUS_HIDDEN_RUNNER_SCRIPT=%~dp0scripts\install_nexus_runner_hidden_autostart.ps1"
set "NEXUS_SELF_HEAL_SCRIPT=%~dp0scripts\enable_nexus_runner_self_heal.ps1"
if not exist "%NEXUS_RUNNER_SCRIPT%" (
  echo NEXUS runner registration script is missing.
  pause
  exit /b 2
)
if not exist "%NEXUS_HIDDEN_RUNNER_SCRIPT%" (
  echo NEXUS hidden runner autostart script is missing.
  pause
  exit /b 2
)
if not exist "%NEXUS_SELF_HEAL_SCRIPT%" (
  echo NEXUS runner self-heal script is missing.
  pause
  exit /b 2
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%NEXUS_RUNNER_SCRIPT%"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" exit /b %RC%
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%NEXUS_HIDDEN_RUNNER_SCRIPT%" -Mode Install
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" exit /b %RC%
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%NEXUS_SELF_HEAL_SCRIPT%"
set "RC=%ERRORLEVEL%"
exit /b %RC%
