"""Fail-closed archival of terminal Paper states with exact ORIGINAL engine identity."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

import bybit_prospective_paper_forward_v1 as forward
import nexus_paper_terminal_archive as archive
import nexus_paper_terminal_rebind as terminal

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "experiments" / "bybit_prospective_paper_forward_v1.json"
SOURCE_A = "a" * 40
SOURCE_B = "b" * 40


def _fixture(tmp_path: Path, *, status: str = "QUARANTINED") -> dict:
    producer = tmp_path / "original-git-pinned-engine.py"
    producer.write_bytes(b"# Old archived engine, not executed or loaded\n")
    config, _ = forward.load_contract(MANIFEST)
    state = forward.new_state(
        config, engine_sha256=forward._file_sha(producer),
        source_sha=SOURCE_A, run_id=17,
    )
    state["status"] = status
    state["decision"] = terminal.TERMINAL_DECISIONS[status]
    _redigest(state)
    state_file = tmp_path / "original-state.json"
    state_file.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return {"producer": producer, "config": config, "state": state, "state_file": state_file,
            "output": tmp_path / "archive"}


def _redigest(state: dict) -> None:
    core = dict(state)
    core.pop("state_digest", None)
    state["state_digest"] = forward._digest(core)


def _run(item: dict, **overrides) -> dict:
    args = dict(
        state_path=item["state_file"],
        historical_engine_path=item["producer"],
        manifest_path=MANIFEST,
        historical_engine_source_sha=SOURCE_A,
        observer_source_sha=SOURCE_B,
        observer_run_id=18,
        destination=item["output"],
    )
    return archive.archive_terminal(**(args | overrides))


@pytest.mark.parametrize("status", ("COMPLETE_REVIEW_REQUIRED", "QUARANTINED"))
def test_terminal_archive_preserves_exact_original_engine_and_state(tmp_path: Path, status: str) -> None:
    item = _fixture(tmp_path, status=status)
    before = item["state_file"].read_bytes()
    receipt = _run(item)
    assert (item["output"] / "original-state.json").read_bytes() == before
    assert receipt["original_state_bytes_sha256"] == archive._hash_bytes(before)
    assert receipt["original_engine_sha256"] == forward._file_sha(item["producer"])
    assert receipt["original_last_run_id"] == 17
    assert receipt["observer_run_id"] == 18
    assert receipt["original_latest_source_sha"] == SOURCE_A
    assert receipt["original_completed_bar_count"] == 0
    assert receipt["current_engine_different_from_original"] is True
    assert receipt["historical_terminal_event_chain_verified"] is True
    assert receipt["original_signed_evidence_preserved_byte_for_byte"] is True
    assert receipt["archive_only"] is True
    assert receipt["current_or_future_paper_execution_authorized"] is False
    assert receipt["automatic_paper_promotion"] is False
    assert receipt["live_trading_enabled"] is False
    assert receipt["current_runtime_equivalence_claimed"] is False
    assert receipt["independent_numerical_historical_replay_claimed"] is False
    core = {k: v for k, v in receipt.items() if k != "receipt_digest"}
    assert receipt["receipt_digest"] == archive._digest(core)
    assert json.loads((item["output"] / "archive-receipt.json").read_text()) == receipt
    assert item["state_file"].read_bytes() == before
    with pytest.raises(archive.TerminalArchiveError, match="overwrite"):
        _run(item)


def test_changed_current_engine_does_not_rewrite_terminal_original_engine(tmp_path: Path) -> None:
    item = _fixture(tmp_path)
    # The previous implementation would reject this because current code
    # changed; archival verification requires the exact old producer file.
    current = forward._file_sha(Path(forward.__file__).resolve())
    assert item["state"]["engine_sha256"] != current
    receipt = _run(item)
    assert receipt["original_engine_sha256"] == item["state"]["engine_sha256"]
    assert receipt["current_engine_different_from_original"] is True
    assert receipt["original_signed_state_digest"] == item["state"]["state_digest"]


@pytest.mark.parametrize("mutation", (
    lambda s: s.update(engine_sha256="0" * 64),
    lambda s: s.update(latest_source_sha=SOURCE_B),
    lambda s: s.update(status="WAITING_FOR_FIRST_PROSPECTIVE_BAR"),
    lambda s: s.update(decision="paper_forward_passed_requires_separate_owner_review"),
    lambda s: s.update(paper_only=False),
    lambda s: s.update(live_trading_enabled=True),
    lambda s: s.update(private_credentials_used=True),
    lambda s: s.update(automatic_live_promotion=True),
    lambda s: s.update(strategy_manifest_sha256="0" * 64),
))
def test_resigned_wrong_engine_wrong_source_changed_authority_or_manifest_rejected(
    tmp_path: Path, mutation,
) -> None:
    item = _fixture(tmp_path)
    original = deepcopy(item["state"])
    mutation(original)
    _redigest(original)
    item["state_file"].write_text(json.dumps(original) + "\n")
    with pytest.raises((archive.TerminalArchiveError, forward.ProspectivePaperError)):
        _run(item)
    assert not item["output"].exists()


def test_signed_terminal_chain_tamper_is_not_repaired(tmp_path: Path) -> None:
    item = _fixture(tmp_path)
    state = item["state"]
    core = {
        "schema_version": forward.EVENT_SCHEMA,
        "sequence": 1, "previous_event_digest": "0" * 64,
        "execution_utc": "2026-09-25T00:00:00Z",
        "target_weights": [0.0, 0.0],
        "paper_only": True, "live_trading_enabled": False,
    }
    event = {**core, "event_digest": forward._digest(core)}
    state["events"] = [event]
    state["completed_bar_count"] = 1
    state["last_execution_utc"] = event["execution_utc"]
    _redigest(state)
    item["state_file"].write_text(json.dumps(state))
    receipt = _run(item)
    assert receipt["original_completed_bar_count"] == 1

    # Re-signing the outer JSON still cannot launder a broken original event
    # digest, because original producer event-chain validation runs again.
    item["output"] = tmp_path / "malicious-archive"
    bad = deepcopy(state)
    bad["events"][0]["event_digest"] = "0" * 64
    _redigest(bad)
    item["state_file"].write_text(json.dumps(bad))
    with pytest.raises(forward.ProspectivePaperError, match="event chain"):
        _run(item)
    assert not item["output"].exists()


def test_refuses_missing_source_mismatched_ids_and_symlinks(tmp_path: Path) -> None:
    item = _fixture(tmp_path)
    for changes in (
        {"historical_engine_source_sha": SOURCE_B},
        {"historical_engine_source_sha": "no-such-commit"},
        {"observer_source_sha": "bad"},
        {"observer_run_id": 17},
        {"observer_run_id": True},
        {"historical_engine_path": tmp_path / "no-engine.py"},
    ):
        with pytest.raises((archive.TerminalArchiveError, forward.ProspectivePaperError)):
            _run(item, **changes)
    assert not item["output"].exists()


def test_workflow_never_rebinds_terminal_state_to_new_engine() -> None:
    workflow = (ROOT / ".github/workflows/bybit_prospective_paper_forward_v1.yml").read_text()
    assert "nexus_paper_terminal_archive.py" in workflow
    assert "original-state.json" in workflow or "build/terminal-archive" in workflow
    assert "nexus_paper_terminal_rebind.py \\" not in workflow
    assert "steps.terminal.outputs.terminal != 'true'" in workflow
    assert "github.event_name != 'schedule'" in workflow
    assert "Historical frozen state" in workflow
    assert "Automatic paper promotion is not granted" in workflow
