@echo off
setlocal
title NEXUS Phase 7 Final Proof
cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\phase7_final_proof.ps1" -Mode Next -RepoRoot "%~dp0."
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
  echo.
  echo NEXUS Phase 7 final proof was blocked.
  echo Leave this window open and send a photo of the error.
  pause
  exit /b %RC%
)

echo.
echo If an action is shown above, complete only that physical action and run this same file again.
echo No watchdog, service, runner registration, credential mutation, or Live trading authority is added.
pause
exit /b 0
