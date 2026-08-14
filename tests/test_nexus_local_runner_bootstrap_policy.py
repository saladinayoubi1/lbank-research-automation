from pathlib import Path


WORKFLOW = Path('.github/workflows/nexus-local-runner.yml')
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


def test_extracted_interpreter_is_rebuilt_from_verified_archive_each_run():
    text = _text()
    assert 'if not exist "%PYROOT%\\python.exe" (' not in text
    assert 'if exist "%PYROOT%" rmdir /s /q "%PYROOT%"' in text
    assert text.index('if exist "%PYROOT%" rmdir /s /q "%PYROOT%"') < text.index('tar.exe -xf "%PYZIP%"')


def test_bootstrap_network_operations_remain_bounded_fail_closed_and_portable():
    text = _text()
    assert text.count('--retry 3 --retry-delay 2') >= 2
    assert '--retry-all-errors' not in text
    assert '--retries 5 --timeout 60' in text
    assert 'if errorlevel 1 exit /b 1' in text


def test_local_runner_checkout_is_bound_to_trigger_sha_and_verified():
    workflow = WORKFLOW.read_text(encoding='utf-8')
    assert 'ref: ${{ github.sha }}' in workflow
    assert 'ref: main' not in workflow
    assert 'git rev-parse HEAD' in workflow
    assert 'GITHUB_SHA' in workflow
    assert 'Checkout SHA mismatch' in workflow


def test_bootstrap_prefers_verified_local_python_with_isolated_venv_before_network_fallback():
    text = _text()
    assert 'bootstrap_source=local_python' in text
    assert 'sys.version_info >= (3,11)' in text
    assert '-m venv "%PYROOT%"' in text
    assert '"%PYROOT%\\Scripts\\python.exe" -m pip --version' in text
    assert 'bootstrap_source=checksum_pinned_portable_fallback' in text
    local_index = text.index('bootstrap_source=local_python')
    python_download_index = text.index('https://www.python.org/ftp/python/')
    assert local_index < python_download_index
