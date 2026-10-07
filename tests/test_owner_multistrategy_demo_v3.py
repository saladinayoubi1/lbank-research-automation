from copy import deepcopy
import json

import numpy as np
import pandas as pd
import pytest

import nexus_owner_multistrategy_demo_v3 as multi
import nexus_owner_consensus_demo_v2 as prior
from test_bybit_prospective_paper_forward_v1 import observation


@pytest.fixture
def initialized(tmp_path, monkeypatch):
    old = tmp_path/"old"
    old_a = prior.initialize(old, "a"*40, pd.Timestamp("2026-09-26T17:00:00Z"))
    old_s = json.loads((old/"state.json").read_text())
    report = {"results": [{"strategy": n, "symbol": s, "timeframe": "hour4",
                          "profile": "stress", "net_pnl": 1} for n, s in multi.SELECTED.items()]}
    monkeypatch.setattr(multi, "REPORT_DIGEST", multi.matrix.digest(report))
    activation, state = multi.make_initial(old_s, old_a, report, "b"*40)
    return activation, state, old_s, old_a, report


def test_total_capital_is_500_not_four_times_500(initialized):
    a, s, *_ = initialized
    for profile in ("conservative", "stress"):
        assert sum(l["profiles"][profile]["wallet"] for l in s["lanes"].values()) == 500
        assert all(c["execution_profiles"][profile]["initial_cash"] == 125 for c in a["configs"].values())
    multi.verify_state(s, a)
    assert a["live_trading_authority"] is False


def test_rejects_used_account_instead_of_resetting_it(initialized):
    _, _, old_s, old_a, report = initialized
    old_s["profiles"]["conservative"]["wallet"] = 499
    core = deepcopy(old_s)
    core.pop("state_digest")
    old_s["state_digest"] = multi.forward._digest(core)
    with pytest.raises(ValueError, match="refusing balance reset"):
        multi.make_initial(old_s, old_a, report, "b"*40)


def test_rejects_other_research_artifact(initialized):
    _, _, old_s, old_a, report = initialized
    report["results"][0]["net_pnl"] = 999
    with pytest.raises(ValueError, match="report mismatch"):
        multi.make_initial(old_s, old_a, report, "b"*40)


def test_caps_count_overlapping_and_opposing_positions_gross(initialized):
    _, s, *_ = initialized
    obs = observation("2026-09-26T20:00:00Z")
    raw = {"consensus": [-1., 0.], "bollinger20_2": [0., 1.],
           "momentum20_ema100": [1., 0.], "macd12_26_9": [1., 0.]}
    result = multi.capped_targets(s, raw, obs)
    assert sum(abs(result[n][0])*125 for n in multi.LANES) <= 500*.60+1e-8
    assert sum(sum(abs(x) for x in result[n])*125 for n in multi.LANES) <= 500*.95+1e-8
    assert result["consensus"][0] < 0


def test_caps_use_no_future_price_information(initialized):
    _, s, *_ = initialized
    obs = observation("2026-09-26T20:00:00Z")
    raw = {n: [.5, .5] for n in multi.LANES}
    first = multi.capped_targets(s, raw, obs)
    for row in obs["mark"]:
        row.update(high=1e9, low=.01, close=1e8)
    assert multi.capped_targets(s, raw, obs) == first


def test_caps_hold_for_divergent_cost_scenarios(initialized):
    _, s, *_ = initialized
    obs = observation("2026-09-26T20:00:00Z")
    rng = np.random.default_rng(91)
    for _ in range(30):
        for n in multi.LANES:
            for p in ("conservative", "stress"):
                s["lanes"][n]["profiles"][p]["wallet"] = float(rng.uniform(40, 200))
        raw = {n: [float(rng.uniform(-1, 1)), 0.] for n in multi.LANES}
        weights = multi.capped_targets(s, raw, obs)
        for p in ("conservative", "stress"):
            budgets = {n: s["lanes"][n]["profiles"][p]["wallet"] for n in multi.LANES}
            assert sum(abs(weights[n][0])*budgets[n] for n in multi.LANES) <= sum(budgets.values())*.60+1e-8


def test_atomic_four_lane_step_and_duplicate_rejection(initialized):
    a, s, *_ = initialized
    obs = observation("2026-09-26T20:00:00Z")
    signals = {n: [.95 if symbol == "BTCUSDT" else 0, .95 if symbol == "ETHUSDT" else 0]
               for n, symbol in multi.SELECTED.items()}
    updated = multi.step(s, a, obs, signals, None)
    multi.verify_state(updated, a)
    assert all(l["completed_bar_count"] == 1 for l in updated["lanes"].values())
    assert s["last_execution_utc"] is None
    assert sum(l["profiles"]["conservative"]["fill_count"] for l in updated["lanes"].values()) > 0
    with pytest.raises(ValueError, match="duplicate"):
        multi.step(updated, a, obs, signals, None)


def test_minimum_lot_cannot_be_rounded_up_to_force_activity(initialized):
    a, s, *_ = initialized
    obs = observation("2026-09-26T20:00:00Z")
    for spec in obs["instrument_specs"]:
        spec["minimum_notional"] = 1000
    signals = {n: [.95, 0] for n in multi.SELECTED}
    updated = multi.step(s, a, obs, signals, None)
    assert all(l["profiles"]["conservative"]["fill_count"] == 0 for l in updated["lanes"].values())


def test_halted_lane_cannot_open_new_positions(initialized):
    a, s, *_ = initialized
    s["halted"] = True
    s = multi.seal(s)
    obs = observation("2026-09-26T20:00:00Z")
    updated = multi.step(s, a, obs, {n: [.95, 0] for n in multi.SELECTED}, None)
    assert all(l["profiles"]["conservative"]["fill_count"] == 0 for l in updated["lanes"].values())


def test_portfolio_tampering_is_rejected(initialized):
    a, s, *_ = initialized
    s["lanes"]["consensus"]["profiles"]["conservative"]["wallet"] += 1
    with pytest.raises(ValueError, match="digest mismatch"):
        multi.verify_state(s, a)


def test_one_strategy_exit_keeps_other_strategy_positions(initialized):
    a, s, *_ = initialized
    obs = observation("2026-09-26T20:00:00Z")
    signals = {n: [.95 if symbol == "BTCUSDT" else 0, .95 if symbol == "ETHUSDT" else 0]
               for n, symbol in multi.SELECTED.items()}
    opened = multi.step(s, a, obs, signals, None)
    signals["bollinger20_2"] = [0., 0.]
    closed = multi.step(opened, a, observation("2026-09-27T00:00:00Z"), signals, None)
    multi.verify_state(closed, a)
    assert closed["lanes"]["bollinger20_2"]["profiles"]["conservative"]["positions"][1]["quantity"] == 0
    assert closed["lanes"]["momentum20_ema100"]["profiles"]["conservative"]["positions"][0]["quantity"] > 0
    assert closed["lanes"]["macd12_26_9"]["profiles"]["conservative"]["positions"][0]["quantity"] > 0


def test_migration_requires_stopped_writer_and_preserves_prior(tmp_path, initialized):
    _, _, old_s, old_a, report = initialized
    root, old = tmp_path/"new", tmp_path/"prior-copy"
    root.mkdir()
    old.mkdir()
    multi.forward.save_state(old/"state.json", old_s)
    multi.forward.save_state(old/"activation.json", old_a)
    report_path = tmp_path/"report.json"
    multi.forward.save_state(report_path, report)
    before = (old/"state.json").read_bytes()
    with pytest.raises(ValueError, match="must be stopped"):
        multi.initialize(root, old, report_path, "b"*40)
    (old/"STOP").touch()
    first = multi.initialize(root, old, report_path, "b"*40)
    assert multi.initialize(root, old, report_path, "b"*40) == first
    assert (old/"state.json").read_bytes() == before
    assert (root/"prior-state-preserved.json").read_bytes() == before
