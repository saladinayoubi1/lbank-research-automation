@echo off
setlocal EnableExtensions
cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\nexus_windows_autostart.ps1" -Mode Install -RepoRoot "%~dp0"
if errorlevel 1 (
  echo.
  echo [NEXUS] Autostart installation failed.
  echo Check %%LOCALAPPDATA%%\NEXUS\Autopilot\autopilot.log
  pause
  exit /b 1
)

echo.
echo [NEXUS] Zero-touch autostart is installed and running.
timeout /t 3 /nobreak >nul
exit /b 0
