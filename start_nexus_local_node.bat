@echo off
setlocal
cd /d %~dp0

if not exist .venv\Scripts\python.exe (
  echo [NEXUS] Virtual environment not found: .venv\Scripts\python.exe
  pause
  exit /b 1
)

echo [NEXUS] Starting local coordinator and dashboard supervisor...
.venv\Scripts\python.exe local_node_supervisor.py --poll-seconds 20 --with-dashboard

endlocal
