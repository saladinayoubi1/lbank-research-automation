@echo off
setlocal EnableExtensions
rem Physical sidecar rerun trigger after #857; bootstrap remains host-isolated and fail-closed.

set "PYROOT_SUFFIX=%GITHUB_RUN_ID%"
if not defined PYROOT_SUFFIX set "PYROOT_SUFFIX=local"
set "PYROOT=%RUNNER_TEMP%\python312-%PYROOT_SUFFIX%"
set "CACHE_ROOT=%RUNNER_WORKSPACE%\_nexus_bootstrap_cache"
set "PYZIP=%CACHE_ROOT%\python-3.12.10-embed-amd64.zip"
set "PIP_WHEEL=%CACHE_ROOT%\pip-26.1.2-py3-none-any.whl"
set "PYZIP_SHA256=4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
set "PIP_WHEEL_SHA256=382ff9f685ee3bc25864f820aa50505825f10f5458ffff07e30a6d96e5715cab"
set "CURL_TIMEOUTS=--connect-timeout 10 --max-time 120 --retry 2 --retry-delay 2"
set "PIP_TIMEOUTS=--retries 2 --timeout 30 --no-input"

if not exist "%CACHE_ROOT%" mkdir "%CACHE_ROOT%"
if errorlevel 1 exit /b 1

rem Prefer an already-installed, executable Python to avoid making the real
rem self-hosted runner depend on a fresh large Python download. Build an
rem isolated per-run venv so stale/locked runtime files from an abandoned job
rem cannot block a later scheduled run.
set "LOCAL_PY="
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if not errorlevel 1 set "LOCAL_PY=python"
if not defined LOCAL_PY (
  py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
  if not errorlevel 1 set "LOCAL_PY=py -3"
)

if defined LOCAL_PY (
  echo bootstrap_source=local_python
  if exist "%PYROOT%" rmdir /s /q "%PYROOT%"
  if exist "%PYROOT%" exit /b 1
  %LOCAL_PY% -m venv "%PYROOT%"
  if errorlevel 1 exit /b 1
  if not exist "%PYROOT%\Scripts\python.exe" exit /b 1
  "%PYROOT%\Scripts\python.exe" -m pip --version
  if errorlevel 1 exit /b 1
  "%PYROOT%\Scripts\python.exe" -m pip install --disable-pip-version-check %PIP_TIMEOUTS% -r requirements-dev.lock
  if errorlevel 1 exit /b 1
  if defined GITHUB_PATH echo %PYROOT%\Scripts>>"%GITHUB_PATH%"
  "%PYROOT%\Scripts\python.exe" --version
  exit /b 0
)

echo bootstrap_source=checksum_pinned_portable_fallback
if exist "%PYZIP%" (
  certutil -hashfile "%PYZIP%" SHA256 | findstr /i "%PYZIP_SHA256%" >nul
  if errorlevel 1 del /f /q "%PYZIP%"
)
if not exist "%PYZIP%" (
  if exist "%PYZIP%.tmp" del /f /q "%PYZIP%.tmp"
  curl.exe -L --fail %CURL_TIMEOUTS% -o "%PYZIP%.tmp" https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip
  if errorlevel 1 exit /b 1
  certutil -hashfile "%PYZIP%.tmp" SHA256 | findstr /i "%PYZIP_SHA256%" >nul
  if errorlevel 1 (
    del /f /q "%PYZIP%.tmp"
    exit /b 1
  )
  move /y "%PYZIP%.tmp" "%PYZIP%" >nul
  if errorlevel 1 exit /b 1
)
certutil -hashfile "%PYZIP%" SHA256 | findstr /i "%PYZIP_SHA256%" >nul
if errorlevel 1 exit /b 1

if exist "%PIP_WHEEL%" (
  certutil -hashfile "%PIP_WHEEL%" SHA256 | findstr /i "%PIP_WHEEL_SHA256%" >nul
  if errorlevel 1 del /f /q "%PIP_WHEEL%"
)
if not exist "%PIP_WHEEL%" (
  if exist "%PIP_WHEEL%.tmp" del /f /q "%PIP_WHEEL%.tmp"
  curl.exe -L --fail %CURL_TIMEOUTS% -o "%PIP_WHEEL%.tmp" https://files.pythonhosted.org/packages/5d/95/6b5cb3461ea5673ba0995989746db58eb18b91b54dbf331e72f569540946/pip-26.1.2-py3-none-any.whl
  if errorlevel 1 exit /b 1
  certutil -hashfile "%PIP_WHEEL%.tmp" SHA256 | findstr /i "%PIP_WHEEL_SHA256%" >nul
  if errorlevel 1 (
    del /f /q "%PIP_WHEEL%.tmp"
    exit /b 1
  )
  move /y "%PIP_WHEEL%.tmp" "%PIP_WHEEL%" >nul
  if errorlevel 1 exit /b 1
)
certutil -hashfile "%PIP_WHEEL%" SHA256 | findstr /i "%PIP_WHEEL_SHA256%" >nul
if errorlevel 1 exit /b 1

if exist "%PYROOT%" rmdir /s /q "%PYROOT%"
if exist "%PYROOT%" exit /b 1
mkdir "%PYROOT%"
if errorlevel 1 exit /b 1

tar.exe -xf "%PYZIP%" -C "%PYROOT%"
if errorlevel 1 exit /b 1
if not exist "%PYROOT%\python.exe" exit /b 1

mkdir "%PYROOT%\Lib\site-packages"
if errorlevel 1 exit /b 1
tar.exe -xf "%PIP_WHEEL%" -C "%PYROOT%\Lib\site-packages"
if errorlevel 1 exit /b 1

echo Lib\site-packages>>"%PYROOT%\python312._pth"
echo import site>>"%PYROOT%\python312._pth"
echo %GITHUB_WORKSPACE%>>"%PYROOT%\python312._pth"

"%PYROOT%\python.exe" -m pip --version
if errorlevel 1 exit /b 1
"%PYROOT%\python.exe" -m pip install --disable-pip-version-check %PIP_TIMEOUTS% -r requirements-dev.lock
if errorlevel 1 exit /b 1

if defined GITHUB_PATH echo %PYROOT%>>"%GITHUB_PATH%"
"%PYROOT%\python.exe" --version
exit /b 0
