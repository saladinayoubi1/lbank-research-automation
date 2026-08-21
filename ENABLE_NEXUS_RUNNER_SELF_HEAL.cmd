@echo off
setlocal
cd /d "%~dp0"
set "NEXUS_SELF_HEAL_SCRIPT=%~dp0scripts\enable_nexus_runner_self_heal.ps1"
if not exist "%NEXUS_SELF_HEAL_SCRIPT%" (
  echo NEXUS runner self-heal script is missing.
  pause
  exit /b 2
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%NEXUS_SELF_HEAL_SCRIPT%"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo NEXUS runner self-heal setup was blocked.
  pause
  exit /b %RC%
)
timeout /t 2 /nobreak >nul
exit /b 0
