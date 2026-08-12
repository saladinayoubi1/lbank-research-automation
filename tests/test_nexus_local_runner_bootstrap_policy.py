from pathlib import Path


WORKFLOW = Path('.github/workflows/nexus-local-runner.yml')
EXPECTED_PYTHON_SHA256 = '4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3'


def _text() -> str:
    return WORKFLOW.read_text(encoding='utf-8')


def test_portable_python_archive_is_sha256_pinned_and_verified_before_extract():
    text = _text()
    assert f'PYZIP_SHA256={EXPECTED_PYTHON_SHA256}' in text
    assert 'certutil -hashfile "%PYZIP%" SHA256' in text
    assert 'certutil -hashfile "%PYZIP%.tmp" SHA256' in text
    assert text.index('certutil -hashfile "%PYZIP%" SHA256') < text.index('tar.exe -xf "%PYZIP%"')


def test_extracted_interpreter_is_rebuilt_from_verified_archive_each_run():
    text = _text()
    assert 'if not exist "%PYROOT%\\python.exe" (' not in text
    assert 'if exist "%PYROOT%" rmdir /s /q "%PYROOT%"' in text
    assert text.index('if exist "%PYROOT%" rmdir /s /q "%PYROOT%"') < text.index('tar.exe -xf "%PYZIP%"')


def test_bootstrap_network_operations_remain_bounded_and_fail_closed():
    text = _text()
    assert text.count('--retry 3 --retry-all-errors --retry-delay 2') >= 2
    assert '--retries 5 --timeout 60' in text
    assert 'if errorlevel 1 exit /b 1' in text
