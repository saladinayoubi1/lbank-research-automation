from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAX_SOURCE_ARCHIVE_BYTES = 8 * 1024 * 1024
REQUIRED_RUNTIME_FILES = {
    "requirements.lock",
    "nexus_multipair_strategy_discovery.py",
    "nexus_multipair_training_refinement.py",
    "nexus_multipair_runtime_requalification_snapshot.py",
    "scripts/nexus_snapshot_artifact.py",
    "scripts/nexus_runtime_snapshot_artifact.py",
}


def test_exact_source_archive_excludes_duplicate_market_data_and_keeps_runtime(tmp_path: Path) -> None:
    archive = tmp_path / "nexus-multipair-exact-source.zip"
    subprocess.run(
        ["git", "archive", "--format=zip", "--output", str(archive), "HEAD"],
        cwd=ROOT,
        check=True,
    )
    assert archive.stat().st_size <= MAX_SOURCE_ARCHIVE_BYTES

    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        names = {member.filename for member in members}

    assert not any(
        member.filename.startswith("data/market/") and not member.is_dir()
        for member in members
    )
    assert REQUIRED_RUNTIME_FILES <= names
