"""Execute the hosted receiver, including corrupted transport and unsafe archives."""
from __future__ import annotations

import base64
import hashlib
import io
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tarfile

import pytest
import yaml


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/nexus_persistent_paper_trading_loop.yml"
pytestmark = pytest.mark.skipif(os.name == "nt" or not shutil.which("bash"), reason="Linux hosted receiver")


def archive_bytes(payload: bytes, name: str = "paper/state.bin") -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:xz") as archive:
        info = tarfile.TarInfo(name)
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    return stream.getvalue()


def receipt(archive: bytes) -> dict[str, str]:
    encoded = base64.b85encode(archive).decode("ascii")
    split = (len(encoded) + 1) // 2
    env = {
        "STATE_ARCHIVE_SHA256": hashlib.sha256(archive).hexdigest(),
        "STATE_ARCHIVE_B85_LEN": str(len(encoded)),
        "STATE_ROOT": "build/nexus_persistent_paper_trading_state",
    }
    for label, part in (("A", encoded[:split]), ("B", encoded[split:])):
        chunks = [part[index:index + 50_000] for index in range(0, len(part), 50_000)]
        assert len(part) * 2 + 16_384 <= 1_048_576
        prefix = f"STATE_ARCHIVE_PART_{label}"
        env[f"{prefix}_LEN"] = str(len(part))
        env[f"{prefix}_CHUNK_COUNT"] = str(len(chunks))
        for index in range(10):
            env[f"{prefix}_CHUNK_{index}"] = chunks[index] if index < len(chunks) else ""
    return env


def receive(tmp_path: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    script = workflow["jobs"]["persist-state"]["steps"][0]["run"]
    return subprocess.run(
        ["bash", "-c", script], cwd=tmp_path, env={**os.environ, **env},
        capture_output=True, text=True, timeout=30,
    )


def test_real_receiver_roundtrips_archive_above_old_job_limit(tmp_path: Path) -> None:
    payload = random.Random(1870).randbytes(430_000)
    archive = archive_bytes(payload)
    assert len(archive) > 424_596
    assert len(base64.b85encode(archive)) * 2 + 4096 > 1_048_576
    result = receive(tmp_path, receipt(archive))
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "build/nexus_persistent_paper_trading_state/paper/state.bin").read_bytes() == payload


@pytest.mark.parametrize("fault", ["missing", "swapped", "oversized", "trailing", "digest", "length"])
def test_real_receiver_rejects_corrupted_transport_before_extraction(tmp_path: Path, fault: str) -> None:
    env = receipt(archive_bytes(b"paper journal must stay intact"))
    a, b = "STATE_ARCHIVE_PART_A_CHUNK_0", "STATE_ARCHIVE_PART_B_CHUNK_0"
    if fault == "missing":
        env[b] = ""
    elif fault == "swapped":
        env[a], env[b] = env[b], env[a]
    elif fault == "oversized":
        env[a] = "x" * 50_001
    elif fault == "trailing":
        env["STATE_ARCHIVE_PART_B_CHUNK_9"] = "unexpected"
    elif fault == "digest":
        env["STATE_ARCHIVE_SHA256"] = "0" * 64
    else:
        env["STATE_ARCHIVE_B85_LEN"] = "1"
    result = receive(tmp_path, env)
    assert result.returncode != 0
    assert not list((tmp_path / env["STATE_ROOT"]).rglob("*.bin"))


def test_digest_valid_archive_cannot_escape_receiver_root(tmp_path: Path) -> None:
    result = receive(tmp_path, receipt(archive_bytes(b"untrusted", "../../escape.bin")))
    assert result.returncode != 0
    assert "unsafe state handoff path" in result.stderr
    assert not (tmp_path / "escape.bin").exists()


@pytest.mark.parametrize("linked_root", [False, True])
def test_packer_checks_original_state_root_before_resolving(tmp_path: Path, linked_root: bool) -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    step = next(step for step in workflow["jobs"]["paper-loop"]["steps"] if step.get("id") == "package")
    code = step["run"].split("<<'PY'\n", 1)[1].split("\nPY", 1)[0]
    root = tmp_path / "state"
    root.mkdir()
    (root / "journal.jsonl").write_bytes(b'{"paper_only":true}\n')
    source = root
    if linked_root:
        source = tmp_path / "linked-state"
        source.symlink_to(root, target_is_directory=True)
    output = tmp_path / "handoff.tar.xz"
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path,
        env={**os.environ, "STATE_ROOT": str(source), "HANDOFF_ARCHIVE": str(output)},
        capture_output=True, text=True, timeout=30,
    )
    if linked_root:
        assert result.returncode != 0, "symlinked state root was silently followed"
        assert not output.exists()
    else:
        assert result.returncode == 0, result.stderr
        with tarfile.open(output, "r:xz") as archive:
            assert archive.extractfile("journal.jsonl").read() == (root / "journal.jsonl").read_bytes()
