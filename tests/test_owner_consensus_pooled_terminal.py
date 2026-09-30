import pandas as pd

import bybit_prospective_paper_forward_v1 as forward
import nexus_owner_consensus_demo_v2 as pooled
import product_shared_paper as terminal
from test_bybit_prospective_paper_forward_v1 import observation


def activation_and_state():
    config, frozen = pooled.make_config(pd.Timestamp("2026-09-30T12:01:00Z"))
    source = "a" * 40
    engine = "b" * 64
    activation = {
        "schema": "nexus.owner-consensus-demo.v2",
        "config": config,
        "frozen": frozen,
        "source_sha": source,
        "engine_sha256": engine,
        "automatic_promotion": False,
    }
    state = forward.new_state(config, engine_sha256=engine, source_sha=source, run_id=0)
    return activation, state


def status(state, activation):
    return {
        "status": "paper_running",
        "checked_at": "2026-09-30T16:00:00Z",
        "start_not_before_utc": activation["config"]["start_not_before_utc"],
    }


def test_pooled_account_has_one_500_usdt_wallet_and_no_fixed_strategy_slice():
    activation, state = activation_and_state()
    snap = terminal.build_single_strategy_snapshot(
        state, activation, status(state, activation)
    )
    assert snap["account"]["initial_balance"] == 500.0
    assert snap["account"]["equity"] == 500.0
    assert snap["allocator"]["mode"] == "shared_equity"
    assert snap["allocator"]["per_strategy_fixed_cash"] is False
    assert len(snap["strategies"]) == 1
    assert snap["strategies"][0]["allocation"] is None
    assert snap["live_trading_authority"] is False


def test_pooled_execution_journal_projects_real_paper_position():
    activation, state = activation_and_state()
    when = activation["config"]["start_not_before_utc"]
    obs = observation(when)
    obs["capture_execution_details"] = True
    state = forward.apply_observations(
        state, [obs], activation["config"],
        source_sha=activation["source_sha"], run_id=1,
    )
    snap = terminal.build_single_strategy_snapshot(
        state, activation, status(state, activation)
    )
    assert len(snap["positions"]) == 2
    assert len(snap["orders"]) == 2
    assert snap["strategies"][0]["fills"] == 2
    assert snap["account"]["initial_balance"] == 500.0


def test_below_minimum_signal_is_logged_but_never_rounded_up():
    activation, state = activation_and_state()
    when = activation["config"]["start_not_before_utc"]
    obs = observation(when)
    obs["capture_execution_details"] = True
    for spec in obs["instrument_specs"]:
        spec["minimum_quantity"] = 1.0
        spec["minimum_notional"] = 100000.0
    state = forward.apply_observations(
        state, [obs], activation["config"],
        source_sha=activation["source_sha"], run_id=1,
    )
    snap = terminal.build_single_strategy_snapshot(
        state, activation, status(state, activation)
    )
    assert snap["positions"] == []
    assert snap["strategies"][0]["fills"] == 0
    skipped = [row for row in snap["orders"] if row["reason"] == "below_min_order"]
    assert len(skipped) == 2
    assert all(row["quantity"] == 0.0 for row in skipped)
