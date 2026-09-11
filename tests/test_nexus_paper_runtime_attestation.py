from __future__ import annotations

import json
from pathlib import Path

import pytest

import bybit_prospective_paper_forward_v1 as forward
import nexus_paper_runtime_attestation as attestation

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "experiments" / "bybit_prospective_paper_forward_v1.json"
LOCK = ROOT / "requirements.lock"
ENGINE_SHA = forward._file_sha(ROOT / "bybit_prospective_paper_forward_v1.py")  # noqa: SLF001
SOURCE_A = "a" * 40
SOURCE_B = "b" * 40


def _fresh_state(run_id: int = 10, source_sha: str = SOURCE_A) -> tuple[dict, dict]:
    config, _ = forward.load_contract(MANIFEST)
    state = forward.new_state(
        config,
        engine_sha256=ENGINE_SHA,
        source_sha=source_sha,
        run_id=run_id,
    )
    return config, state


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _redigest(state: dict) -> None:
    unsigned = dict(state)
    unsigned.pop("state_digest", None)
    state["state_digest"] = forward._digest(unsigned)  # noqa: SLF001


def test_runtime_lock_matches_installed_contract_environment() -> None:
    runtime = attestation.load_locked_runtime(LOCK, verify_installed=True)
    assert runtime["locked_versions"]["numpy"] == "2.3.5"
    assert runtime["locked_versions"]["pandas"] == "2.3.3"
    assert len(runtime["requirements_lock_sha256"]) == 64


def test_fresh_state_requalification_requires_no_network(tmp_path: Path) -> None:
    _, state = _fresh_state()
    state_path = tmp_path / "state.json"
    output = tmp_path / "attestation.json"
    _write(state_path, state)

    result = attestation.requalify(
        manifest_path=MANIFEST,
        state_path=state_path,
        lock_path=LOCK,
        output_path=output,
    )

    assert result["legacy_completed_bar_count"] == 0
    assert result["historical_target_replay_verified"] is True
    assert result["historical_zero_execution_exposure_verified"] is True
    assert result["lock_enforced_from_sequence"] == 1
    assert result["lock_enforced_event_count"] == 0
    assert result["live_trading_enabled"] is False
    assert output.is_file()


def test_rebind_preserves_requalified_history_and_binds_new_state(tmp_path: Path) -> None:
    config, previous = _fresh_state()
    previous_path = tmp_path / "previous.json"
    state_path = tmp_path / "state.json"
    initial_path = tmp_path / "initial-attestation.json"
    output = tmp_path / "updated-attestation.json"
    _write(previous_path, previous)
    initial = attestation.requalify(
        manifest_path=MANIFEST,
        state_path=previous_path,
        lock_path=LOCK,
        output_path=initial_path,
    )

    current = dict(previous)
    current["last_run_id"] = 11
    current["latest_source_sha"] = SOURCE_B
    _redigest(current)
    forward.verify_state(current, config, ENGINE_SHA)
    _write(state_path, current)

    updated = attestation.rebind(
        manifest_path=MANIFEST,
        previous_state_path=previous_path,
        state_path=state_path,
        attestation_path=initial_path,
        lock_path=LOCK,
        output_path=output,
    )

    assert updated["legacy_completed_bar_count"] == initial["legacy_completed_bar_count"]
    assert updated["historical_replay_target_digest"] == initial["historical_replay_target_digest"]
    assert updated["bound_state_digest"] == current["state_digest"]
    assert updated["bound_last_run_id"] == 11
    assert updated["bound_source_sha"] == SOURCE_B
    assert updated["live_trading_enabled"] is False


def test_legacy_execution_exposure_cannot_be_requalified() -> None:
    config, state = _fresh_state()
    state["profiles"]["conservative"]["orders"] = 1
    with pytest.raises(attestation.PaperRuntimeAttestationError, match="execution exposure"):
        attestation._assert_zero_execution_legacy(state, config)  # noqa: SLF001


def test_changed_legacy_target_cannot_be_requalified() -> None:
    config, state = _fresh_state()
    state["events"] = [{"target_weights": [0.1, 0.0], "target_changed": True}]
    with pytest.raises(attestation.PaperRuntimeAttestationError, match="non-zero or changed targets"):
        attestation._assert_zero_execution_legacy(state, config)  # noqa: SLF001


def test_attestation_digest_or_state_binding_tamper_fails(tmp_path: Path) -> None:
    config, state = _fresh_state()
    state_path = tmp_path / "state.json"
    output = tmp_path / "attestation.json"
    _write(state_path, state)
    result = attestation.requalify(
        manifest_path=MANIFEST,
        state_path=state_path,
        lock_path=LOCK,
        output_path=output,
    )
    runtime = attestation.load_locked_runtime(LOCK, verify_installed=True)

    bad_digest = dict(result)
    bad_digest["bound_last_run_id"] = 999
    with pytest.raises(attestation.PaperRuntimeAttestationError, match="digest mismatch"):
        attestation.verify_attestation(bad_digest, state, config, runtime)

    rebound = dict(result)
    rebound_core = dict(rebound)
    rebound_core["bound_state_digest"] = "0" * 64
    rebound_core.pop("attestation_digest", None)
    rebound = {**rebound_core, "attestation_digest": attestation._digest(rebound_core)}  # noqa: SLF001
    with pytest.raises(attestation.PaperRuntimeAttestationError, match="state digest binding"):
        attestation.verify_attestation(rebound, state, config, runtime)
