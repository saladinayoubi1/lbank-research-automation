"""Execute the exact Linux sender/receiver snippets, including UTF-8 env limits."""
from __future__ import annotations
import base64
import io
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tarfile
import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/nexus_persistent_paper_trading_loop.yml'
pytestmark = pytest.mark.skipif(sys.platform != 'linux' or not shutil.which('bash'), reason='Linux hosted transport')

def steps():
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding='utf-8'))['jobs']
    package = next(s['run'] for s in jobs['paper-loop']['steps'] if s.get('id') == 'package')
    receiver = jobs['persist-state']['steps'][0]['run']
    return package, receiver

def python_blocks(script):
    return [block.split('\nPY', 1)[0] for block in script.split("<<'PY'\n")[1:]]

def archive_bytes(payload, name='paper/state.bin'):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:xz') as archive:
        info = tarfile.TarInfo(name)
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    return stream.getvalue()

def receipt(tmp_path, raw):
    source = tmp_path / 'sender'
    (source / 'build').mkdir(parents=True, exist_ok=True)
    (source / 'build/persistent-state-handoff.tar.xz').write_bytes(raw)
    output = source / 'outputs'
    result = subprocess.run([sys.executable, '-c', python_blocks(steps()[0])[1]], cwd=source,
        env={**os.environ, 'GITHUB_OUTPUT': str(output)}, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    encoded = output.read_text(encoding='utf-8')
    assert len(encoded.encode('utf-16-le')) + 16_384 <= 1_048_576
    values = dict(line.split('=', 1) for line in encoded.splitlines())
    assert all(len(value.encode('utf-8')) < 100_000 for value in values.values())
    values['STATE_ROOT'] = 'build/nexus_persistent_paper_trading_state'
    return json.loads(json.dumps({k.upper():v for k,v in values.items()}))

def receive(tmp_path, env):
    return subprocess.run(['bash', '-c', steps()[1]], cwd=tmp_path,
        env={**os.environ, **env}, capture_output=True, text=True, timeout=30)

def test_large_state_roundtrip_through_real_utf8_job_outputs_and_environment(tmp_path):
    payload = random.Random(1870).randbytes(430_000)
    raw = archive_bytes(payload)
    assert len(raw) > 424_596
    assert len(base64.b85encode(raw)) * 2 + 4096 > 1_048_576
    result = receive(tmp_path, receipt(tmp_path, raw))
    assert result.returncode == 0, result.stderr
    assert (tmp_path / 'build/nexus_persistent_paper_trading_state/paper/state.bin').read_bytes() == payload

@pytest.mark.parametrize('size', [1, 2, 3, 4, 5, 800_000])
def test_codec_boundaries_and_maximum_linux_environment(tmp_path, size):
    raw = random.Random(size).randbytes(size)
    env = receipt(tmp_path, raw)
    (tmp_path / 'build').mkdir()
    result = subprocess.run([sys.executable, '-c', python_blocks(steps()[1])[0]], cwd=tmp_path,
        env={**os.environ, **env}, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / 'build/persistent-state-handoff.tar.xz').read_bytes() == raw

@pytest.mark.parametrize('fault', ['missing','swapped','oversized','trailing','digest','length','codec','character','padding'])
def test_corrupted_transport_fails_before_extraction(tmp_path, fault):
    raw = archive_bytes(random.Random(9).randbytes(60_000))
    env = receipt(tmp_path, raw)
    a, b = 'STATE_ARCHIVE_CHUNK_0', 'STATE_ARCHIVE_CHUNK_1'
    if fault == 'missing': env[a] = ''
    elif fault == 'swapped': env[a],env[b] = env[b],env[a]
    elif fault == 'oversized': env[a] = '\u4000' * 30_001
    elif fault == 'trailing': env['STATE_ARCHIVE_CHUNK_17'] = '\u4000'
    elif fault == 'digest': env['STATE_ARCHIVE_SHA256'] = '0' * 64
    elif fault == 'length': env['STATE_ARCHIVE_B85_LEN'] = '1'
    elif fault == 'codec': env['STATE_ARCHIVE_CODEC'] = 'unknown'
    elif fault == 'character': env[a] = 'A' + env[a][1:]
    else:
        env = receipt(tmp_path, b'1234')  # Five Base85 digits: one canonical pad.
        env[a] = env[a][:-1] + chr(ord(env[a][-1]) + 1)
    result = receive(tmp_path, env)
    assert result.returncode != 0
    assert not (tmp_path / 'build/persistent-state-handoff.tar.xz').exists()
    assert not list((tmp_path / env['STATE_ROOT']).rglob('*.bin'))

def test_digest_valid_traversal_archive_is_rejected(tmp_path):
    result = receive(tmp_path, receipt(tmp_path, archive_bytes(b'untrusted', '../../escape.bin')))
    assert result.returncode != 0
    assert 'unsafe state handoff path' in result.stderr
    assert not (tmp_path / 'escape.bin').exists()

@pytest.mark.parametrize('linked', [False, True])
def test_packer_rejects_root_symlink_before_resolution(tmp_path, linked):
    root = tmp_path / 'state'
    root.mkdir()
    (root / 'journal.jsonl').write_bytes(b'{"paper_only":true}\n')
    source = root
    if linked:
        source = tmp_path / 'linked'
        source.symlink_to(root, target_is_directory=True)
    result = subprocess.run([sys.executable, '-c', python_blocks(steps()[0])[0]], cwd=tmp_path,
        env={**os.environ, 'STATE_ROOT': str(source)}, capture_output=True, text=True, timeout=30)
    assert (result.returncode != 0) == linked, result.stderr
    assert (tmp_path / 'build/persistent-state-handoff.tar.xz').exists() != linked

def test_sender_rejects_oversized_archive_before_emitting_any_outputs(tmp_path):
    (tmp_path / 'build').mkdir()
    (tmp_path / 'build/persistent-state-handoff.tar.xz').write_bytes(b'x' * 800_001)
    output = tmp_path / 'outputs'
    result = subprocess.run([sys.executable, '-c', python_blocks(steps()[0])[1]], cwd=tmp_path,
        env={**os.environ, 'GITHUB_OUTPUT': str(output)}, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert not output.exists()
