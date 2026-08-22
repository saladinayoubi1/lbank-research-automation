import json
from pathlib import Path

import pytest

from scripts.build_reproducible_control_bundle import build
from scripts.nonproduction_rollback_drill import drill


ROOT = Path(__file__).resolve().parents[1]


def test_independent_bundle_builds_are_byte_identical(tmp_path: Path):
    outputs = []
    for name in ("a", "b"):
        output = tmp_path / f"{name}.zip"
        build(ROOT, output, tmp_path / f"{name}.json", "a" * 40)
        outputs.append(output.read_bytes())
    assert outputs[0] == outputs[1]


def test_bundle_binds_exact_source_and_is_nonproduction(tmp_path: Path):
    output, manifest = tmp_path / "bundle.zip", tmp_path / "manifest.json"
    build(ROOT, output, manifest, "b" * 40)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["source_commit"] == "b" * 40
    assert data["production"] is False
    assert len(data["inputs"]) == 5


def test_rollback_drill_rejects_corruption_quarantines_and_restores(tmp_path: Path):
    bundle, manifest = tmp_path / "bundle.zip", tmp_path / "manifest.json"
    build(ROOT, bundle, manifest, "c" * 40)
    evidence = tmp_path / "drill.json"
    drill(bundle, tmp_path / "drill", evidence)
    data = json.loads(evidence.read_text(encoding="utf-8"))
    assert data["production_authorized"] is False
    assert data["corruption_rejected"] is True
    assert data["quarantine_preserved"] is True
    assert data["restore_verified"] is True


def test_invalid_source_commit_fails(tmp_path: Path):
    with pytest.raises(ValueError, match="source_commit"):
        build(ROOT, tmp_path / "bundle.zip", tmp_path / "manifest.json", "main")
