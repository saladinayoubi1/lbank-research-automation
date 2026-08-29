from pathlib import Path


def test_fallback_probe_documentation_exists():
    text = Path('docs/wsl-virtualization-fallback-probes.md').read_text(encoding='utf-8')
    assert 'native Windows processor feature flags' in text
    assert 'disposable tiny WSL2 import probe' in text
    assert 'without touching the existing Windows runner service' in text
