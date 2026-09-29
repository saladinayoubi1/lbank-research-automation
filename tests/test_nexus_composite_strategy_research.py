from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import nexus_composite_strategy_research as engine


def history(n=1200):
    if n % 16:
        n += 16 - n % 16
    start = pd.Timestamp("2025-01-01T00:00:00Z")
    def mk(tf, count, step):
        t = pd.date_range(start, periods=count, freq=step, tz="UTC")
        close = 100 + np.arange(count, dtype=float) * .03
        return pd.DataFrame({
            "timestamp": t, "open": close - .05,
            "high": close + .2, "low": close - .2,
            "close": close, "volume": np.full(count, 1000.),
            "symbol": "BTCUSDT", "timeframe": tf,
        })
    return {
        "minute15": mk("minute15", n, "15min"),
        "hour1": mk("hour1", n // 4, "1h"),
        "hour4": mk("hour4", n // 16, "4h"),
    }


def test_asof_does_not_expose_unclosed_four_hour_candle():
    source = history()
    baseline = engine.build_features(source)
    mutated = {key: value.copy() for key, value in source.items()}
    four = mutated["hour4"]
    end = four.index[-1]
    four.loc[end, "close"] = 5_000.
    four.loc[end, "high"] = 5_001.
    altered = engine.build_features(mutated)
    availability = pd.Timestamp(four["timestamp"].iloc[-1]) + pd.Timedelta(hours=4)
    before = baseline["decision_at"] < availability
    pd.testing.assert_series_equal(
        baseline.loc[before, "h4_up"],
        altered.loc[before, "h4_up"],
    )
    # Exactly at the close, the 4h bar becomes legitimately observable.
    assert baseline["decision_at"].iloc[-1] == availability


def test_gap_in_any_required_frame_fails_closed():
    source = history()
    source["hour4"] = source["hour4"].drop(index=10).reset_index(drop=True)
    with pytest.raises(engine.CompositeResearchError, match="chronology"):
        engine.build_features(source)


def test_no_arbitrary_ceiling_for_more_than_100_closed_sequential_trades():
    n = 153 * 3
    stamp = pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC")
    frame = pd.DataFrame({
        "decision_at": stamp, "open": np.full(n, 100.),
        "high": np.array([100.1, 104., 100.1] * 153),
        "low": np.array([99.9, 99.7, 99.9] * 153),
        "close": np.full(n, 100.), "atr": np.ones(n),
    })
    signals = np.array([True, False, True] * 153)
    report = engine.backtest(frame, signals, fee_bps=10., slip_bps=5., risk_variant=0)
    assert report["closed_round_trips"] > 100
    assert report["trade_count_limit"] is None
    assert report["concurrent_risk_model"].startswith("one_collateral_backed")
    assert report["max_drawdown_pct"] <= 10.1


def test_same_candle_stop_and_target_chooses_stop():
    t = pd.date_range("2025-01-01", periods=3, freq="15min", tz="UTC")
    f = pd.DataFrame({
        "decision_at": t, "open": [100., 100., 100.],
        "high": [100.1, 110., 100.1],
        "low": [99.9, 97., 99.9],
        "close": [100., 100., 100.], "atr": [1., 1., 1.],
    })
    result = engine.backtest(f, np.array([True, False, False]),
                             fee_bps=10, slip_bps=5, risk_variant=0)
    assert result["closed_round_trips"] == 1
    assert result["net_pnl_usdt"] < 0
    assert result["win_rate_pct"] == 0


def test_config_novelty_progresses_without_retrying_same_failed_grammar(tmp_path: Path, monkeypatch):
    frames = history()
    monkeypatch.setattr(engine, "load_verified_archive_frame",
                        lambda _root, _symbol, tf: frames[tf])
    first = engine.run(tmp_path, tmp_path / "one", "a" * 40, None)
    assert first["status"] == "EVALUATED_RESEARCH_ONLY"
    assert first["auto_demo_promotion"] is False
    assert first["live_enabled"] is False
    assert first["historical_test_pristine"] is False
    assert len(first["rows"]) == 2 * 3 * 2
    assert all(r["trade_count_limit"] is None for r in first["rows"])
    state_path = tmp_path / "one" / "novelty-ledger.json"
    second = engine.run(tmp_path, tmp_path / "two", "a" * 40, state_path)
    assert second["selected"]["fingerprint"] != first["selected"]["fingerprint"]
    assert second["parameter_configs_tested_cumulative"] == 2
    assert second["distinct_mechanisms_tested_cumulative"] == 2
    assert second["selected"]["mechanism"] != first["selected"]["mechanism"]


def test_novelty_ledger_tamper_and_authority_widening_fail_closed(tmp_path: Path):
    p = tmp_path / "ledger.json"
    state = engine.empty_ledger()
    state["live_enabled"] = True
    p.write_text(json.dumps(state))
    with pytest.raises(engine.CompositeResearchError):
        engine.load_ledger(p)
    state = engine.empty_ledger()
    state["config_fingerprints_evaluated"] = ["unverified"]
    p.write_text(json.dumps(state))
    with pytest.raises(engine.CompositeResearchError):
        engine.load_ledger(p)


def test_all_grammar_options_exhausted_requires_new_mechanism():
    state = engine.empty_ledger()
    state["config_fingerprints_evaluated"] = [
        engine.digest({"config": cfg, "dataset": engine.ARCHIVE_SHA256,
                       "contract": engine.SCHEMA})
        for cfg in engine.CONFIGS
    ]
    assert engine.select_next(state) is None


def test_strategy_choice_is_data_and_schema_gated_not_an_arbitrary_count():
    f = engine.build_features(history())
    with pytest.raises(engine.CompositeResearchError, match="unreviewed"):
        engine.signal_for(f, {"mechanism": "unverified_private_depth_strategy",
                              "risk_variant": 0})


def test_select_next_explores_all_distinct_mechanisms_before_risk_variants():
    state = engine.empty_ledger()
    selected_mechanisms = []
    for _ in range(len(engine.MECHANISMS)):
        next_config = engine.select_next(state)
        assert next_config is not None
        selected_mechanisms.append(next_config["mechanism"])
        core = {k: v for k, v in state.items() if k != "ledger_digest"}
        core["mechanisms_evaluated"] = sorted(set([*core["mechanisms_evaluated"], next_config["mechanism"]]))
        core["config_fingerprints_evaluated"].append(next_config["fingerprint"])
        state = {**core, "ledger_digest": engine.digest(core)}
    assert len(set(selected_mechanisms)) == len(engine.MECHANISMS)
    # The same reviewed mechanism may now be retested ONLY as an explicit
    # labeled robustness variant after all distinct mechanisms had a turn.
    next_config = engine.select_next(state)
    assert next_config["mechanism"] in selected_mechanisms
    assert next_config["risk_variant"] == 1


def test_cross_pair_relative_reclaim_requires_real_aligned_closed_peer_candles():
    frames = history(n=1536)
    peer = frames["minute15"].copy()
    price = 95.0 + np.arange(len(peer)) * .015 + np.sin(np.arange(len(peer)) / 18.0) * 1.1
    peer["open"] = price - .05
    peer["close"] = price
    peer["high"] = price + .3
    peer["low"] = price - .3
    f = engine.build_features(frames, peer_15m=peer)
    assert "cross_pair_relative_z" in f
    assert np.isfinite(f["cross_pair_relative_z"].iloc[140:]).any()

    mutated = peer.copy()
    idx = len(mutated) - 1
    mutated.loc[idx, "close"] = 15_000.0
    mutated.loc[idx, "high"] = 15_001.0
    changed = engine.build_features(frames, peer_15m=mutated)
    # No future peer bar can change ANY earlier own-candle decision.
    pd.testing.assert_series_equal(
        f["cross_pair_relative_z"].iloc[:-1],
        changed["cross_pair_relative_z"].iloc[:-1],
    )
    pd.testing.assert_series_equal(
        f["cross_pair_relative_z_previous"], changed["cross_pair_relative_z_previous"],
    )

    corrupted = peer.drop(index=5).reset_index(drop=True)
    with pytest.raises(engine.CompositeResearchError, match="same closed UTC grid"):
        engine.build_features(frames, peer_15m=corrupted)
    corrupted = peer.copy()
    corrupted.loc[idx, "timestamp"] = corrupted.loc[idx - 1, "timestamp"]
    with pytest.raises(engine.CompositeResearchError, match="same closed UTC grid"):
        engine.build_features(frames, peer_15m=corrupted)
    corrupted = peer.copy()
    corrupted.loc[20, "volume"] = -1
    with pytest.raises(engine.CompositeResearchError, match="OHLCV integrity"):
        engine.build_features(frames, peer_15m=corrupted)


def test_new_cross_pair_mechanism_cannot_fake_missing_peer_as_indicators():
    f = engine.build_features(history(n=1536))
    config = {"mechanism": "cross_pair_relative_reclaim", "risk_variant": 0}
    with pytest.raises(engine.CompositeResearchError, match="verified peer history"):
        engine.signal_for(f, config)


def test_new_cross_pair_mechanism_runs_full_numeric_research_only_grid(tmp_path, monkeypatch):
    frames = history(n=1536)
    peer = frames["minute15"].copy()
    p = 103 + np.arange(len(peer), dtype=float) * .012 + np.sin(np.arange(len(peer)) / 22) * 1.4
    peer["open"] = p - .06
    peer["close"] = p
    peer["high"] = p + .3
    peer["low"] = p - .3
    def approved_loader(_root, symbol, tf):
        return peer if symbol == "ETHUSDT" and tf == "minute15" else frames[tf]
    monkeypatch.setattr(engine, "load_verified_archive_frame", approved_loader)
    previous = engine.empty_ledger()
    core = {k: v for k, v in previous.items() if k != "ledger_digest"}
    for cfg in engine.CONFIGS:
        if cfg["mechanism"] == "cross_pair_relative_reclaim" or cfg["risk_variant"] != 0:
            continue
        core["mechanisms_evaluated"].append(cfg["mechanism"])
        core["config_fingerprints_evaluated"].append(
            engine.digest({"config": cfg, "dataset": engine.ARCHIVE_SHA256,
                           "contract": engine.SCHEMA})
        )
    core["mechanisms_evaluated"] = sorted(set(core["mechanisms_evaluated"]))
    prior_path = tmp_path / "previous.json"
    prior_path.write_text(json.dumps({**core, "ledger_digest": engine.digest(core)}))
    report = engine.run(tmp_path / "approved", tmp_path / "result",
                        "a" * 40, prior_path)
    assert report["selected"]["mechanism"] == "cross_pair_relative_reclaim"
    assert len(report["rows"]) == 12
    assert set(r["symbol"] for r in report["rows"]) == set(engine.SYMBOLS)
    assert all(r["trade_count_limit"] is None for r in report["rows"])
    assert report["auto_demo_promotion"] is False
    assert report["live_enabled"] is False
    assert report["historical_test_pristine"] is False
