from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from nexus_multipair_demo_strategy_matrix import run_cycle
from nexus_multipair_restart_replay import (
    MultiPairRestartReplayError,
    capture_seed,
    verify_restart,
)


ROOT = Path(__file__).resolve().parents[1]
V2_MANIFEST = ROOT / "config" / "nexus-demo-strategy-matrix-v2.json"
LEGACY_MANIFEST = ROOT / "config" / "nexus-demo-strategy-matrix-v1.json"
SOURCE_SHA = "a" * 40
RUN_ID = "91"
NOW_MS = 1_800_000_000_000


def _hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _runner(**kwargs):
    symbol = kwargs["symbol"]
    timeframe = kwargs["timeframe"]
    tasks = []
    for family in kwargs["families"]:
        tasks.append({
            "family": family,
            "task_id": f"{symbol}:{timeframe}:{family}",
            "status": "qualification_killed",
            "evidence_digest": _hex(f"{symbol}:{timeframe}:{family}"),
        })
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "paper_only": True,
        "live_trading_authority": False,
        "tasks": tasks,
        "ledger_digest": _hex(f"ledger:{symbol}:{timeframe}"),
    }


def _verifier(ledger):
    return {
        "decision": "pass",
        "verification_digest": _hex(f"verify:{ledger['symbol']}:{ledger['timeframe']}"),
    }


def _analyzer(root, _ledger):
    return {
        "paper_only": True,
        "live_trading_authority": False,
        "status_counts": {},
        "projection_digest": _hex(f"analysis:{root}"),
    }


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _seed(tmp_path: Path):
    state_path = tmp_path / "matrix-state.json"
    snapshot_path = tmp_path / "demo" / "strategy-matrix.json"
    state, snapshot, migration = run_cycle(
        manifest_path=V2_MANIFEST,
        legacy_manifest_path=LEGACY_MANIFEST,
        state_path=state_path,
        state_root=tmp_path,
        source_sha=SOURCE_SHA,
        run_id=RUN_ID,
        now_ms=NOW_MS,
        runner=_runner,
        verifier=_verifier,
        analyzer=_analyzer,
    )
    assert migration is None
    _write(state_path, state)
    _write(snapshot_path, snapshot)
    seed_path = tmp_path / "continuity-seed.json"
    seed = capture_seed(
        manifest_path=V2_MANIFEST,
        state_path=state_path,
        snapshot_path=snapshot_path,
        source_sha=SOURCE_SHA,
        run_id=RUN_ID,
        now_ms=NOW_MS,
        output_path=seed_path,
    )
    return state_path, snapshot_path, seed_path, seed


def test_same_clock_restart_preserves_state_and_skips_all_duplicate_bars(tmp_path: Path) -> None:
    state_path, snapshot_path, seed_path, seed = _seed(tmp_path)
    calls = []

    def must_not_run(**kwargs):
        calls.append((kwargs["symbol"], kwargs["timeframe"]))
        raise AssertionError("duplicate closed candle was re-executed")

    state, snapshot, migration = run_cycle(
        manifest_path=V2_MANIFEST,
        legacy_manifest_path=LEGACY_MANIFEST,
        state_path=state_path,
        state_root=tmp_path,
        source_sha=SOURCE_SHA,
        run_id=RUN_ID,
        now_ms=NOW_MS,
        runner=must_not_run,
        verifier=_verifier,
        analyzer=_analyzer,
    )
    assert migration is None
    assert calls == []
    assert state["state_digest"] == seed["state_digest"]
    assert len(snapshot["cycle"]) == 12
    assert {row["status"] for row in snapshot["cycle"]} == {"SKIPPED_NO_NEW_BAR"}
    _write(state_path, state)
    _write(snapshot_path, snapshot)

    proof_path = tmp_path / "restart-replay-proof.json"
    proof = verify_restart(
        manifest_path=V2_MANIFEST,
        seed_path=seed_path,
        state_path=state_path,
        snapshot_path=snapshot_path,
        source_sha=SOURCE_SHA,
        run_id=RUN_ID,
        output_path=proof_path,
    )
    assert proof["state_digest_preserved"] is True
    assert proof["cell_cursors_preserved"] is True
    assert proof["lane_identity_preserved"] is True
    assert proof["duplicate_bar_execution_count"] == 0
    assert proof["skipped_no_new_bar_count"] == 12
    assert proof["verified_cell_count"] == 12
    assert proof["reported_lane_count"] == 36
    assert proof["paper_only"] is True
    assert proof["live_trading_authority"] is False


def test_restart_with_new_bar_is_rejected_as_same_clock_replay(tmp_path: Path) -> None:
    state_path, snapshot_path, seed_path, _seed_value = _seed(tmp_path)
    state, snapshot, _migration = run_cycle(
        manifest_path=V2_MANIFEST,
        legacy_manifest_path=LEGACY_MANIFEST,
        state_path=state_path,
        state_root=tmp_path,
        source_sha=SOURCE_SHA,
        run_id=RUN_ID,
        now_ms=NOW_MS + 900_000,
        runner=_runner,
        verifier=_verifier,
        analyzer=_analyzer,
    )
    _write(state_path, state)
    _write(snapshot_path, snapshot)
    with pytest.raises(MultiPairRestartReplayError, match="continuity verification failed"):
        verify_restart(
            manifest_path=V2_MANIFEST,
            seed_path=seed_path,
            state_path=state_path,
            snapshot_path=snapshot_path,
            source_sha=SOURCE_SHA,
            run_id=RUN_ID,
            output_path=tmp_path / "should-not-exist.json",
        )


def test_tampered_seed_digest_fails_closed(tmp_path: Path) -> None:
    state_path, snapshot_path, seed_path, seed = _seed(tmp_path)
    seed["now_ms"] += 1
    _write(seed_path, seed)
    with pytest.raises(MultiPairRestartReplayError, match="seed digest verification failed"):
        verify_restart(
            manifest_path=V2_MANIFEST,
            seed_path=seed_path,
            state_path=state_path,
            snapshot_path=snapshot_path,
            source_sha=SOURCE_SHA,
            run_id=RUN_ID,
            output_path=tmp_path / "should-not-exist.json",
        )
