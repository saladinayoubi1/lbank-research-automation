@echo off
setlocal EnableExtensions

set "PYROOT=%RUNNER_WORKSPACE%\_nexus_python312_env"
set "CACHE_ROOT=%RUNNER_WORKSPACE%\_nexus_bootstrap_cache"
set "PIP_CACHE_DIR=%CACHE_ROOT%\pip-cache"
set "PYZIP=%CACHE_ROOT%\python-3.12.10-embed-amd64.zip"
set "PIP_WHEEL=%CACHE_ROOT%\pip-26.1.2-py3-none-any.whl"
set "PYZIP_SHA256=4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
set "PIP_WHEEL_SHA256=382ff9f685ee3bc25864f820aa50505825f10f5458ffff07e30a6d96e5715cab"

if not exist "%CACHE_ROOT%" mkdir "%CACHE_ROOT%"
if errorlevel 1 exit /b 1
if not exist "%PIP_CACHE_DIR%" mkdir "%PIP_CACHE_DIR%"
if errorlevel 1 exit /b 1

rem Reuse a previously verified persistent environment before touching the network.
if exist "%PYROOT%\Scripts\python.exe" (
  "%PYROOT%\Scripts\python.exe" -c "import pandas, pyarrow, requests, tenacity, pytest, yaml" >nul 2>&1
  if not errorlevel 1 (
    echo bootstrap_source=persistent_venv
    if defined GITHUB_PATH echo %PYROOT%\Scripts>>"%GITHUB_PATH%"
    "%PYROOT%\Scripts\python.exe" --version
    exit /b 0
  )
)
if exist "%PYROOT%\python.exe" (
  "%PYROOT%\python.exe" -c "import pandas, pyarrow, requests, tenacity, pytest, yaml" >nul 2>&1
  if not errorlevel 1 (
    echo bootstrap_source=persistent_portable_python
    if defined GITHUB_PATH echo %PYROOT%>>"%GITHUB_PATH%"
    "%PYROOT%\python.exe" --version
    exit /b 0
  )
)

rem Prefer an already-installed, executable Python. Build the venv in persistent
rem runner workspace so a verified dependency environment survives later checkouts.
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
  %LOCAL_PY% -m venv "%PYROOT%"
  if errorlevel 1 exit /b 1
  if not exist "%PYROOT%\Scripts\python.exe" exit /b 1
  "%PYROOT%\Scripts\python.exe" -m pip --version
  if errorlevel 1 exit /b 1
  "%PYROOT%\Scripts\python.exe" -m pip install --disable-pip-version-check --retries 5 --timeout 60 --cache-dir "%PIP_CACHE_DIR%" -r requirements.txt pytest PyYAML
  if errorlevel 1 exit /b 1
  "%PYROOT%\Scripts\python.exe" -c "import pandas, pyarrow, requests, tenacity, pytest, yaml"
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
  curl.exe -L --fail --retry 3 --retry-delay 2 -o "%PYZIP%.tmp" https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip
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
  curl.exe -L --fail --retry 3 --retry-delay 2 -o "%PIP_WHEEL%.tmp" https://files.pythonhosted.org/packages/5d/95/6b5cb3461ea5673ba0995989746db58eb18b91b54dbf331e72f569540946/pip-26.1.2-py3-none-any.whl
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
"%PYROOT%\python.exe" -m pip install --disable-pip-version-check --retries 5 --timeout 60 --cache-dir "%PIP_CACHE_DIR%" -r requirements.txt pytest PyYAML
if errorlevel 1 exit /b 1
"%PYROOT%\python.exe" -c "import pandas, pyarrow, requests, tenacity, pytest, yaml"
if errorlevel 1 exit /b 1

if defined GITHUB_PATH echo %PYROOT%>>"%GITHUB_PATH%"
"%PYROOT%\python.exe" --version
exit /b 0
