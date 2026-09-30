from __future__ import annotations

from pathlib import Path

import pandas as pd

import bybit_prospective_paper_forward_v1 as forward
import nexus_owner_consensus_demo_v3 as demo
from test_bybit_prospective_paper_forward_v1 import observation


def test_consensus_only_terminal_uses_full_500_allocation(tmp_path: Path) -> None:
    config, frozen = demo.make_config(pd.Timestamp("2026-09-30T00:00:00Z"))
    source_sha = "b" * 40
    activation = {
        "schema": demo.SCHEMA,
        "config": config,
        "frozen": frozen,
        "source_sha": source_sha,
        "engine_sha256": demo.engine_digest(),
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_allowed": False,
        "automatic_promotion": False,
    }
    state = forward.new_state(
        config,
        engine_sha256=activation["engine_sha256"],
        source_sha=source_sha,
        run_id=0,
    )
    obs = observation("2026-09-30T08:00:00Z")
    obs["target_weights"] = [0.2, 0.0]
    obs["capture_execution_details"] = True
    state = forward.apply_observations(
        state,
        [obs],
        config,
        source_sha=source_sha,
        run_id=1,
    )
    summary = {
        "status": "paper_running",
        "checked_at": "2026-09-30T12:00:00Z",
        "risk_reasons": [],
        "start_not_before_utc": config["start_not_before_utc"],
    }

    terminal = demo._terminal_wrapper(state, activation, summary)

    assert terminal["available"] is True
    assert terminal["live_trading_authority"] is False
    assert terminal["account"]["initial_balance"] == 500.0
    assert [row["strategy"] for row in terminal["strategies"]] == ["consensus"]
    assert terminal["strategies"][0]["allocation"] == 500.0
    assert terminal["strategies"][0]["fills"] == 1
    assert terminal["positions"][0]["strategy"] == "consensus"
    assert terminal["positions"][0]["symbol"] == "BTCUSDT"


def test_consensus_runtime_records_full_execution_journal() -> None:
    config, _ = demo.make_config(pd.Timestamp("2026-09-30T00:00:00Z"))
    source_sha = "c" * 40
    engine_sha = demo.engine_digest()
    state = forward.new_state(
        config,
        engine_sha256=engine_sha,
        source_sha=source_sha,
        run_id=0,
    )
    obs = observation("2026-09-30T08:00:00Z")
    obs["target_weights"] = [0.2, 0.0]
    obs["capture_execution_details"] = True
    updated = forward.apply_observations(
        state,
        [obs],
        config,
        source_sha=source_sha,
        run_id=1,
    )
    conservative = updated["profiles"]["conservative"]

    assert conservative["fill_count"] == 1
    assert len(conservative["execution_journal"]) == 1
    assert conservative["execution_journal"][0]["kind"] == "fill"
    assert conservative["execution_journal"][0]["reason"] == "strategy_signal"
