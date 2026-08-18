@echo off
setlocal EnableExtensions
cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\nexus_windows_autostart.ps1" -Mode Install -RepoRoot "%~dp0"
if errorlevel 1 (
  echo.
  echo [NEXUS] Core autostart installation failed.
  echo Check %%LOCALAPPDATA%%\NEXUS\Autopilot\autopilot.log
  pause
  exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\nexus_github_runner_autostart.ps1" -Mode Install -RepoRoot "%~dp0"
if errorlevel 1 (
  echo.
  echo [NEXUS] GitHub runner autostart installation failed.
  echo Core NEXUS autostart remains installed.
  echo Check %%LOCALAPPDATA%%\NEXUS\RunnerAutostart\runner-autostart.log
  pause
  exit /b 1
)

echo.
echo [NEXUS] Zero-touch core + GitHub runner autostart installed.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\nexus_github_runner_autostart.ps1" -Mode Status -RepoRoot "%~dp0"
echo.
echo After future Windows logons, no CMD or PowerShell window is required.
timeout /t 5 /nobreak >nul
exit /b 0
