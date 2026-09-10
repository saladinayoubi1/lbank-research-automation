from pathlib import Path


WORKFLOW = Path('.github/workflows/nexus-local-runner.yml')
AUTONOMY_WORKFLOW = Path('.github/workflows/nexus_local_autonomy.yml')
BOOTSTRAP = Path('scripts/bootstrap_portable_python.cmd')
EXPECTED_PYTHON_SHA256 = '4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3'
EXPECTED_PIP_SHA256 = '382ff9f685ee3bc25864f820aa50505825f10f5458ffff07e30a6d96e5715cab'
EXPECTED_PIP_WHEEL = 'pip-26.1.2-py3-none-any.whl'


def _text() -> str:
    workflow = WORKFLOW.read_text(encoding='utf-8')
    assert 'call scripts\\bootstrap_portable_python.cmd' in workflow
    return BOOTSTRAP.read_text(encoding='utf-8')


def test_portable_python_archive_is_sha256_pinned_and_verified_before_extract():
    text = _text()
    assert f'PYZIP_SHA256={EXPECTED_PYTHON_SHA256}' in text
    assert 'certutil -hashfile "%PYZIP%" SHA256' in text
    assert 'certutil -hashfile "%PYZIP%.tmp" SHA256' in text
    assert text.index('certutil -hashfile "%PYZIP%" SHA256') < text.index('tar.exe -xf "%PYZIP%"')


def test_pip_bootstrap_uses_content_pinned_wheel_instead_of_unverified_script():
    text = _text()
    assert f'PIP_WHEEL_SHA256={EXPECTED_PIP_SHA256}' in text
    assert EXPECTED_PIP_WHEEL in text
    assert 'https://files.pythonhosted.org/' in text
    assert 'bootstrap.pypa.io/get-pip.py' not in text
    assert 'GETPIP=' not in text
    assert 'certutil -hashfile "%PIP_WHEEL%" SHA256' in text
    assert 'certutil -hashfile "%PIP_WHEEL%.tmp" SHA256' in text
    verify_index = text.index('certutil -hashfile "%PIP_WHEEL%" SHA256')
    extract_index = text.index('tar.exe -xf "%PIP_WHEEL%"')
    assert verify_index < extract_index
    assert '"%PYROOT%\\python.exe" -m pip --version' in text


def test_portable_fallback_is_rebuilt_from_verified_archive_each_run():
    text = _text()
    fallback = text.index(':portable_fallback')
    extract = text.index('tar.exe -xf "%PYZIP%"')
    assert 'set "PYROOT=%RUN_PYROOT%"' in text[fallback:extract]
    assert 'if exist "%PYROOT%" rmdir /s /q "%PYROOT%"' in text[fallback:extract]
    assert 'if exist "%PYROOT%" exit /b 1' in text[fallback:extract]


def test_bootstrap_network_operations_remain_bounded_fail_closed_and_portable():
    text = _text()
    assert 'CURL_TIMEOUTS=--connect-timeout 10 --max-time 120 --retry 2 --retry-delay 2' in text
    assert text.count('curl.exe -L --fail %CURL_TIMEOUTS%') == 2
    assert '--retry-all-errors' not in text
    assert 'PIP_TIMEOUTS=--retries 2 --timeout 30 --no-input' in text
    assert text.count('-m pip install --disable-pip-version-check %PIP_TIMEOUTS% -r requirements-dev.lock') == 2
    assert 'if errorlevel 1 exit /b 1' in text


def test_portable_runtime_is_per_run_and_stale_temp_downloads_are_removed():
    text = _text()
    assert 'PYROOT_SUFFIX=%GITHUB_RUN_ID%' in text
    assert 'if not defined PYROOT_SUFFIX set "PYROOT_SUFFIX=local"' in text
    assert 'RUN_PYROOT=%RUNNER_TEMP%\\python312-%PYROOT_SUFFIX%' in text
    assert 'set "PYROOT=%RUN_PYROOT%"' in text
    assert 'if exist "%PYZIP%.tmp" del /f /q "%PYZIP%.tmp"' in text
    assert 'if exist "%PIP_WHEEL%.tmp" del /f /q "%PIP_WHEEL%.tmp"' in text


def test_local_python_env_cache_is_content_addressed_by_both_locks_and_python_version():
    text = _text()
    assert 'ENV_CACHE_ROOT=%RUNNER_WORKSPACE%\\_nexus_python_envs' in text
    assert 'PYROOT=%ENV_CACHE_ROOT%\\py-%ENV_KEY%' in text
    assert text.count("pathlib.Path('requirements.lock').read_bytes()") == 2
    assert text.count("pathlib.Path('requirements-dev.lock').read_bytes()") == 2
    assert "h.update(b'nexus-env-v1\\0')" in text
    assert "sys.version_info.major" in text
    assert "sys.version_info.minor" in text


def test_local_python_cache_hit_is_validated_before_reuse_and_invalid_cache_rebuilds():
    text = _text()
    assert 'if exist "%PYROOT%\\Scripts\\python.exe" if exist "%PYROOT%\\.nexus-ready" goto :try_cached_env' in text
    assert 'call :validate_local_env' in text
    assert 'bootstrap_cache_validation=REBUILD' in text
    assert 'bootstrap_source=content_addressed_env_cache' in text
    assert '"%PYROOT%\\Scripts\\python.exe" -m pip check >nul 2>&1' in text
    assert '"%PYROOT%\\Scripts\\python.exe" -c "import numpy,pandas,pyarrow,pytest,yaml" >nul 2>&1' in text
    validate_index = text.index('call :validate_local_env')
    hit_index = text.index('bootstrap_source=content_addressed_env_cache')
    assert validate_index < hit_index


def test_local_python_cache_is_marked_ready_only_after_install_and_validation():
    text = _text()
    install = text.index('"%PYROOT%\\Scripts\\python.exe" -m pip install')
    ready = text.index('>"%PYROOT%\\.nexus-ready.tmp" echo env_key=%ENV_KEY%')
    assert install < ready
    assert text.index('call :validate_local_env', install) < ready
    assert 'move /y "%PYROOT%\\.nexus-ready.tmp" "%PYROOT%\\.nexus-ready" >nul' in text


def test_portable_artifact_cache_survives_runner_temp_cleanup_and_remains_checksum_verified():
    text = _text()
    assert 'CACHE_ROOT=%RUNNER_WORKSPACE%\\_nexus_bootstrap_cache' in text
    assert 'PYZIP=%CACHE_ROOT%\\python-3.12.10-embed-amd64.zip' in text
    assert f'PIP_WHEEL=%CACHE_ROOT%\\{EXPECTED_PIP_WHEEL}' in text
    assert 'if not exist "%CACHE_ROOT%" mkdir "%CACHE_ROOT%"' in text
    assert 'PYZIP=%RUNNER_TEMP%' not in text
    assert 'PIP_WHEEL=%RUNNER_TEMP%' not in text


def test_local_runner_checkout_is_bound_to_trigger_sha_and_verified():
    workflow = WORKFLOW.read_text(encoding='utf-8')
    assert 'ref: ${{ github.sha }}' in workflow
    assert 'ref: main' not in workflow
    assert 'git rev-parse HEAD' in workflow
    assert 'GITHUB_SHA' in workflow
    assert 'Checkout SHA mismatch' in workflow


def test_bootstrap_prefers_verified_local_python_before_portable_network_fallback():
    text = _text()
    assert 'bootstrap_source=local_python' in text
    assert 'bootstrap_source=content_addressed_env_cache' in text
    assert 'sys.version_info >= (3,11)' in text
    assert '-m venv "%PYROOT%"' in text
    assert '"%PYROOT%\\Scripts\\python.exe" -m pip --version' in text
    assert 'bootstrap_source=checksum_pinned_portable_fallback' in text
    local_index = text.index(':local_python')
    python_download_index = text.index('https://www.python.org/ftp/python/')
    assert local_index < python_download_index


def test_autonomy_schedule_exceeds_bounded_worker_window_and_keeps_push_immediate():
    workflow = AUTONOMY_WORKFLOW.read_text(encoding='utf-8')
    assert "cron: '*/15 * * * *'" in workflow
    assert "cron: '*/5 * * * *'" not in workflow
    assert "NEXUS_WORKER_MAX_SECONDS: '240'" in workflow
    assert 'push:' in workflow
    assert 'branches: [main]' in workflow
    assert 'group: nexus-local-autonomy' in workflow
    assert 'cancel-in-progress: false' in workflow


def test_owner_autostart_proof_fast_path_skips_heavy_python_and_node_bootstrap():
    workflow = WORKFLOW.read_text(encoding='utf-8')
    skip_expr = "github.event_name != 'push' || !contains(github.event.head_commit.message, '[verify-owner-autostart]')"
    assert workflow.count(skip_expr) == 3
    verifier = workflow.index('- name: Verify owner-user autostart read-only')
    setup_node = workflow.index('- uses: actions/setup-node@820762786026740c76f36085b0efc47a31fe5020')
    bootstrap = workflow.index('- name: Bootstrap portable Python')
    assert verifier < setup_node < bootstrap
    assert '- name: Owner-proof privacy guard' in workflow
    assert 'owner_proof_privacy_guard=ok' in workflow
    assert 'GITHUB_WORKSPACE' in workflow
    assert 'GITHUB_REPOSITORY' in workflow
    assert "$workLeaf -ine '_work'" in workflow
    assert 'Owner-proof workspace is not an isolated GitHub Actions _work/repo/repo checkout' in workflow
    assert 'USERPROFILE' not in workflow


def test_non_owner_proof_paths_preserve_python_bootstrap_and_privacy_guard():
    workflow = WORKFLOW.read_text(encoding='utf-8')
    assert '- name: Bootstrap portable Python' in workflow
    assert 'call scripts\\bootstrap_portable_python.cmd' in workflow
    assert '- name: Privacy guard' in workflow
    assert "python -c \"import os,pathlib; root=pathlib.Path.cwd().resolve(); repo=os.environ['GITHUB_REPOSITORY'].split('/')[-1];" in workflow
    assert "root.parent.parent.name.casefold()=='_work'" in workflow
    assert '- name: Install zero-touch NEXUS autostart' in workflow
    assert '- name: Persistent autonomous worker' in workflow
