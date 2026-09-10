@echo off
setlocal EnableExtensions
rem Physical sidecar bootstrap: bounded, fail-closed, and content-addressed for local Python.

set "PYROOT_SUFFIX=%GITHUB_RUN_ID%"
if not defined PYROOT_SUFFIX set "PYROOT_SUFFIX=local"
set "RUN_PYROOT=%RUNNER_TEMP%\python312-%PYROOT_SUFFIX%"
set "CACHE_ROOT=%RUNNER_WORKSPACE%\_nexus_bootstrap_cache"
set "PYZIP=%CACHE_ROOT%\python-3.12.10-embed-amd64.zip"
set "PIP_WHEEL=%CACHE_ROOT%\pip-26.1.2-py3-none-any.whl"
set "PYZIP_SHA256=4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
set "PIP_WHEEL_SHA256=382ff9f685ee3bc25864f820aa50505825f10f5458ffff07e30a6d96e5715cab"
set "CURL_TIMEOUTS=--connect-timeout 10 --max-time 120 --retry 2 --retry-delay 2"
set "PIP_TIMEOUTS=--retries 2 --timeout 30 --no-input"

if not exist "%CACHE_ROOT%" mkdir "%CACHE_ROOT%"
if errorlevel 1 exit /b 1

rem Prefer an already-installed Python. Its venv is cached by Python version plus
rem both lock files. A cache hit is accepted only after pip and import checks.
set "LOCAL_PY="
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if not errorlevel 1 set "LOCAL_PY=python"
if not defined LOCAL_PY (
  py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
  if not errorlevel 1 set "LOCAL_PY=py -3"
)

if defined LOCAL_PY goto :local_python
goto :portable_fallback

:local_python
set "ENV_KEY="
if /I "%LOCAL_PY%"=="python" (
  for /f "usebackq delims=" %%K in (`python -c "import hashlib,pathlib,sys; h=hashlib.sha256(); h.update(b'nexus-env-v1\0'); h.update(pathlib.Path('requirements.lock').read_bytes()); h.update(b'\0'); h.update(pathlib.Path('requirements-dev.lock').read_bytes()); print(f'{sys.version_info.major}{sys.version_info.minor}-{h.hexdigest()[:20]}')"`) do set "ENV_KEY=%%K"
) else (
  for /f "usebackq delims=" %%K in (`py -3 -c "import hashlib,pathlib,sys; h=hashlib.sha256(); h.update(b'nexus-env-v1\0'); h.update(pathlib.Path('requirements.lock').read_bytes()); h.update(b'\0'); h.update(pathlib.Path('requirements-dev.lock').read_bytes()); print(f'{sys.version_info.major}{sys.version_info.minor}-{h.hexdigest()[:20]}')"`) do set "ENV_KEY=%%K"
)
if not defined ENV_KEY exit /b 1

set "ENV_CACHE_ROOT=%RUNNER_WORKSPACE%\_nexus_python_envs"
if not exist "%ENV_CACHE_ROOT%" mkdir "%ENV_CACHE_ROOT%"
if errorlevel 1 exit /b 1
set "PYROOT=%ENV_CACHE_ROOT%\py-%ENV_KEY%"

if exist "%PYROOT%\Scripts\python.exe" if exist "%PYROOT%\.nexus-ready" goto :try_cached_env
goto :rebuild_local_env

:try_cached_env
call :validate_local_env
if errorlevel 1 (
  echo bootstrap_cache_validation=REBUILD
  goto :rebuild_local_env
)
echo bootstrap_source=content_addressed_env_cache
if defined GITHUB_PATH echo %PYROOT%\Scripts>>"%GITHUB_PATH%"
"%PYROOT%\Scripts\python.exe" --version
exit /b 0

:rebuild_local_env
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
call :validate_local_env
if errorlevel 1 exit /b 1
>"%PYROOT%\.nexus-ready.tmp" echo env_key=%ENV_KEY%
move /y "%PYROOT%\.nexus-ready.tmp" "%PYROOT%\.nexus-ready" >nul
if errorlevel 1 exit /b 1
if defined GITHUB_PATH echo %PYROOT%\Scripts>>"%GITHUB_PATH%"
"%PYROOT%\Scripts\python.exe" --version
exit /b 0

:portable_fallback
set "PYROOT=%RUN_PYROOT%"
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

:validate_local_env
if not exist "%PYROOT%\Scripts\python.exe" exit /b 1
"%PYROOT%\Scripts\python.exe" -m pip check >nul 2>&1
if errorlevel 1 exit /b 1
"%PYROOT%\Scripts\python.exe" -c "import numpy,pandas,pyarrow,pytest,yaml" >nul 2>&1
if errorlevel 1 exit /b 1
exit /b 0
