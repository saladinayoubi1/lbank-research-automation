import json
from pathlib import Path

import pytest

import nexus_final_proof_assembler as assembler


SHA = "a" * 40


def _write(path: Path, value) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _inputs(tmp_path: Path):
    return {
        "supervisor_ledger_path": _write(tmp_path / "supervisor.json", {"source_sha": SHA}),
        "mission_control_path": _write(tmp_path / "mission.json", {"paper_only": True}),
        "scheduler_snapshot_path": _write(tmp_path / "scheduler.json", {"source_sha": SHA}),
        "resource_utilization_path": _write(
            tmp_path / "resources.json", [{"resource": "windows_laptop", "source_sha": SHA}]
        ),
    }


def test_assembler_binds_project_memory_and_delegates_verification(tmp_path: Path, monkeypatch) -> None:
    inputs = _inputs(tmp_path)
    state = tmp_path / "docs/project_memory/STATE.json"
    state.parent.mkdir(parents=True)
    state.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        assembler.memory_validator,
        "validate_repository",
        lambda _root, expected_observed_main: {
            "observed_main_sha": expected_observed_main
        },
    )
    monkeypatch.setattr(
        assembler.final_proof,
        "build_unsigned_bundle",
        lambda **values: {
            **values,
            "unsigned_bundle_digest": "x",
            "project_memory_projection": {
                "observed_main_sha": values["source_sha"], "proof_bundle_digest": "x"
            },
        },
    )
    captured = {}
    monkeypatch.setattr(
        assembler.final_proof,
        "save_verified_bundle",
        lambda path, bundle: captured.setdefault("result", {**bundle, "output": str(path)}),
    )
    result = assembler.assemble(
        root=tmp_path, source_sha=SHA, output_path=tmp_path / "proof.json", **inputs
    )
    projection = result["project_memory_projection"]
    assert projection["canonical_state_observed_main_sha"] == SHA
    assert len(projection["canonical_state_sha256"]) == 64
    assert result["output"].endswith("proof.json")


@pytest.mark.parametrize("target", ["supervisor", "scheduler", "resources"])
def test_assembler_rejects_cross_sha_inputs(tmp_path: Path, monkeypatch, target: str) -> None:
    inputs = _inputs(tmp_path)
    state = tmp_path / "docs/project_memory/STATE.json"
    state.parent.mkdir(parents=True)
    state.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        assembler.memory_validator,
        "validate_repository",
        lambda _root, expected_observed_main: {"observed_main_sha": expected_observed_main},
    )
    path_key = {
        "supervisor": "supervisor_ledger_path",
        "scheduler": "scheduler_snapshot_path",
        "resources": "resource_utilization_path",
    }[target]
    path = inputs[path_key]
    value = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(value, list):
        value[0]["source_sha"] = "b" * 40
    else:
        value["source_sha"] = "b" * 40
    _write(path, value)
    with pytest.raises(assembler.FinalProofAssemblerError, match="source SHA"):
        assembler.assemble(
            root=tmp_path, source_sha=SHA, output_path=tmp_path / "proof.json", **inputs
        )
