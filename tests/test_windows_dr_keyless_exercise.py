import json
import zipfile
from pathlib import Path

import pytest

from scripts.windows_dr_keyless_exercise import run


def test_windows_dr_exercise_builds_valid_nonproduction_bundle(tmp_path: Path) -> None:
    bundle = run(tmp_path / "out", "a" * 40, 123456, "test-windows-runner")
    assert bundle.is_file()
    with zipfile.ZipFile(bundle) as source:
        names = set(source.namelist())
        assert "dr-evidence.json" in names
        assert "verified-backup.zip" in names
        evidence = json.loads(source.read("dr-evidence.json"))
    assert evidence["production_authorized"] is False
    assert evidence["source_commit"] == "a" * 40
    assert len(evidence["scenarios"]) == 4


@pytest.mark.parametrize("sha", ["main", "A" * 40, "a" * 39])
def test_windows_dr_exercise_rejects_invalid_source_sha(tmp_path: Path, sha: str) -> None:
    with pytest.raises(ValueError, match="source SHA"):
        run(tmp_path / "out", sha, 123456, "runner")
