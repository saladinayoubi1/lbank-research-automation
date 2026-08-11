import json
from pathlib import Path

import pytest

import project_memory_validator as pmv


VALID_SHA = "a" * 40
OTHER_SHA = "b" * 40
EXPECTED_CANONICAL_READS = [
    "docs/project_memory/PROJECT_MEMORY.md",
    "docs/project_memory/STATE.json",
    "docs/project_memory/DECISIONS.md",
    "docs/project_memory/RECOVERY_PLAYBOOK.md",
]


def _write_memory(root: Path, *, observed_sha: str = VALID_SHA) -> Path:
    memory = root / "docs" / "project_memory"
    memory.mkdir(parents=True)
    (memory / "PROJECT_MEMORY.md").write_text(
        "# NEXUS Project Memory\n\n## Immutable mission and safety boundary\nResearch only.\n\n## Durable-memory contract\nRepository evidence wins.\n",
        encoding="utf-8",
    )
    (memory / "DECISIONS.md").write_text(
        "# Decisions\n\nThis is an append-oriented log; later decisions supersede rather than erase history.\n",
        encoding="utf-8",
    )
    (memory / "RECOVERY_PLAYBOOK.md").write_text(
        "# Recovery\n\nverify current `main`, open PRs/issues and CI/workflow evidence before stronger action. Backup presence alone is not recovery proof.\n",
        encoding="utf-8",
    )
    state = {
        "schema_version": 2,
        "project": "NEXUS / lbank-research-automation",
        "memory_policy": {
            "repository_is_durable_source": True,
            "chat_is_source_of_truth": False,
            "secrets_allowed": False,
            "core_goals_agent_editable": False,
        },
        "data_policy": {
            "research_only": True,
            "real_trading": False,
            "fabricated_market_data": False,
        },
        "continuity": {
            "required_reads": list(EXPECTED_CANONICAL_READS),
            "drive_backup": {
                "secondary_only": True,
                "may_authorize_production_recovery": False,
            },
        },
        "current_evidence": {
            "observed_main_sha": observed_sha,
            "observed_at_utc": "2026-08-10T23:00:00Z",
        },
    }
    (memory / "STATE.json").write_text(json.dumps(state), encoding="utf-8")
    return memory


def _load_state(memory: Path) -> dict:
    return json.loads((memory / "STATE.json").read_text(encoding="utf-8"))


def _save_state(memory: Path, state: dict) -> None:
    (memory / "STATE.json").write_text(json.dumps(state), encoding="utf-8")


def test_canonical_required_reads_use_repository_slashes():
    assert pmv.CANONICAL_REQUIRED_READS == EXPECTED_CANONICAL_READS
    assert all("\\" not in path for path in pmv.CANONICAL_REQUIRED_READS)


def test_valid_canonical_memory_passes(tmp_path):
    _write_memory(tmp_path)
    result = pmv.validate_repository(tmp_path, expected_observed_main=VALID_SHA)
    assert result["observed_main_sha"] == VALID_SHA


def test_missing_canonical_file_fails_even_if_alternate_copy_exists(tmp_path):
    memory = _write_memory(tmp_path)
    canonical = memory / "STATE.json"
    alternate = tmp_path / "STATE.json"
    alternate.write_text(canonical.read_text(encoding="utf-8"), encoding="utf-8")
    canonical.unlink()
    with pytest.raises(pmv.MemoryValidationError, match="missing canonical"):
        pmv.validate_repository(tmp_path)


def test_malformed_state_fails_closed(tmp_path):
    memory = _write_memory(tmp_path)
    (memory / "STATE.json").write_text("{not-json", encoding="utf-8")
    with pytest.raises(pmv.MemoryValidationError, match="malformed state"):
        pmv.validate_repository(tmp_path)


def test_stale_sha_is_rejected_against_exact_expected_evidence(tmp_path):
    _write_memory(tmp_path, observed_sha=VALID_SHA)
    with pytest.raises(pmv.MemoryValidationError, match="stale Project Memory"):
        pmv.validate_repository(tmp_path, expected_observed_main=OTHER_SHA)


def test_main_advance_after_snapshot_is_rejected(tmp_path):
    _write_memory(tmp_path, observed_sha=VALID_SHA)
    advanced_main = OTHER_SHA
    with pytest.raises(pmv.MemoryValidationError, match="expected"):
        pmv.validate_repository(tmp_path, expected_observed_main=advanced_main)


def test_required_read_path_conflict_is_rejected(tmp_path):
    memory = _write_memory(tmp_path)
    state = _load_state(memory)
    state["continuity"]["required_reads"][1] = "STATE.json"
    _save_state(memory, state)
    with pytest.raises(pmv.MemoryValidationError, match="exactly the four canonical"):
        pmv.validate_repository(tmp_path)


def test_drive_presence_only_bypass_is_rejected(tmp_path):
    memory = _write_memory(tmp_path)
    state = _load_state(memory)
    state["continuity"]["drive_backup"]["may_authorize_production_recovery"] = True
    _save_state(memory, state)
    with pytest.raises(pmv.MemoryValidationError, match="must not authorize"):
        pmv.validate_repository(tmp_path)


def test_safety_boundary_conflict_is_rejected(tmp_path):
    memory = _write_memory(tmp_path)
    state = _load_state(memory)
    state["data_policy"]["real_trading"] = True
    _save_state(memory, state)
    with pytest.raises(pmv.MemoryValidationError, match="real trading"):
        pmv.validate_repository(tmp_path)


def test_invalid_sha_and_timestamp_are_rejected(tmp_path):
    memory = _write_memory(tmp_path)
    state = _load_state(memory)
    state["current_evidence"]["observed_main_sha"] = "not-a-sha"
    _save_state(memory, state)
    with pytest.raises(pmv.MemoryValidationError, match="40-hex"):
        pmv.validate_repository(tmp_path)

    state["current_evidence"]["observed_main_sha"] = VALID_SHA
    state["current_evidence"]["observed_at_utc"] = "not-a-time"
    _save_state(memory, state)
    with pytest.raises(pmv.MemoryValidationError, match="timestamp"):
        pmv.validate_repository(tmp_path)
