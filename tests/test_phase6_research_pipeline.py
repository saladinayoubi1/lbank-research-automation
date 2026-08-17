from __future__ import annotations

from copy import deepcopy

import pytest

import phase6_research_pipeline as phase6

START = 1_700_000_100_000  # aligned to 15m grid
STEP = 900_000


def candles(count: int = 90):
    rows = []
    for index in range(count):
        if index < count // 2:
            price = 100.0 - index * 0.8
        else:
            price = 64.0 + (index - count // 2) * 1.4
        rows.append(
            {
                "source": "Bybit",
                "market_type": "spot",
                "symbol": "BTCUSDT",
                "interval": "15",
                "open_time_ms": START + index * STEP,
                "close_time_ms": START + (index + 1) * STEP - 1,
                "open": f"{price:.8f}",
                "high": f"{price * 1.01:.8f}",
                "low": f"{price * 0.99:.8f}",
                "close": f"{price:.8f}",
                "volume": "10",
                "turnover": f"{price * 10:.8f}",
                "closed": True,
            }
        )
    return rows


def dataset(rows=None):
    return phase6.bind_bybit_closed_dataset(
        rows or candles(),
        canonical_symbol="BTC/USDT",
        source_symbol="BTCUSDT",
        interval="15",
    )


def permissive_kills():
    return {
        "min_robustness_score": -1.0,
        "max_cost_stress_loss_pct": 100.0,
        "min_walk_forward_score": -1.0,
        "min_oos_score": -1.0,
        "max_drawdown_pct": 100.0,
        "min_regime_pass_ratio": 0.0,
        "max_failure_mode_severity": 10.0,
    }


def run(ds=None, kills=None):
    return phase6.run_research_job(
        ds or dataset(),
        hypothesis="long-flat momentum avoids the falling regime and participates in the rising regime",
        family="momentum",
        strategy_version="phase6-momentum-v1",
        strategy_config={"lookback": 3, "entry_threshold": 0.0},
        code_sha="a" * 40,
        cost_model={
            "fee_bps": 10.0,
            "slippage_bps": 5.0,
            "stress_fee_bps": 20.0,
            "stress_slippage_bps": 10.0,
        },
        kill_criteria=kills or permissive_kills(),
    )


def test_closed_bybit_rows_bind_to_canonical_primary_dataset():
    ds = dataset()
    assert ds["source"] == "Bybit"
    assert ds["source_role"] == "primary"
    assert ds["instrument"] == "BTC/USDT"
    assert ds["manifest_timeframe"] == "15m"
    assert ds["finality"] == "closed_only"
    assert ds["paper_only"] is True


def test_open_or_substituted_rows_fail_closed_before_backtest():
    opened = candles()
    opened[-1]["closed"] = False
    with pytest.raises(phase6.Phase6PipelineError, match="open/incomplete"):
        dataset(opened)

    substituted = candles()
    substituted[0]["source"] = "Binance"
    with pytest.raises(phase6.Phase6PipelineError, match="Bybit spot"):
        dataset(substituted)


def test_real_pipeline_can_only_produce_bounded_paper_handoff():
    result = run()
    assert result["schema_version"] == phase6.PIPELINE_SCHEMA
    assert result["paper_only"] is True
    assert result["live_execution_allowed"] is False
    assert result["qualification"]["status"] == "paper_candidate"
    handoff = result["paper_candidate_handoff"]
    assert handoff is not None
    assert handoff["paper_only"] is True
    assert handoff["live_execution_allowed"] is False
    assert handoff["private_exchange_credentials_allowed"] is False
    assert handoff["withdrawals_allowed"] is False
    assert handoff["production_promotion_allowed"] is False
    assert handoff["billing_changes_allowed"] is False
    assert handoff["signing_authority_allowed"] is False
    assert handoff["deterministic_risk_final_authority"] is True
    assert handoff["next_authority"] == "deterministic_risk_paper_review"


def test_strict_qualification_kills_without_handoff():
    kills = permissive_kills()
    kills["min_robustness_score"] = 10.0
    result = run(kills=kills)
    assert result["qualification"]["status"] == "killed"
    assert "ROBUSTNESS_KILL" in result["qualification"]["kill_reasons"]
    assert result["paper_candidate_handoff"] is None


def test_pipeline_replay_is_byte_deterministic_and_tamper_detectable():
    ds = dataset()
    first = run(ds)
    second = run(deepcopy(ds))
    assert phase6.replay_identical(first, second) is True
    assert first == second

    tampered = deepcopy(second)
    tampered["evidence"]["benchmark_score"] += 0.001
    assert phase6.replay_identical(first, tampered) is False


def test_future_candle_cannot_change_earlier_momentum_targets():
    original = candles()
    changed = deepcopy(original)
    changed[-1]["open"] = "500"
    changed[-1]["high"] = "505"
    changed[-1]["low"] = "495"
    changed[-1]["close"] = "500"
    changed[-1]["turnover"] = "5000"
    first = phase6.generate_targets(dataset(original), "momentum", {"lookback": 3, "entry_threshold": 0.0})
    second = phase6.generate_targets(dataset(changed), "momentum", {"lookback": 3, "entry_threshold": 0.0})
    assert first.iloc[:-1].tolist() == second.iloc[:-1].tolist()


def test_all_supported_families_generate_bounded_long_flat_targets():
    ds = dataset()
    configs = {
        "momentum": {"lookback": 3, "entry_threshold": 0.0},
        "trend_breakout": {"entry_lookback": 5, "exit_lookback": 3},
        "mean_reversion": {"lookback": 8, "entry_z": -1.0, "exit_z": 0.0},
    }
    for family, config in configs.items():
        targets = phase6.generate_targets(ds, family, config)
        assert len(targets) == ds["row_count"]
        assert set(targets.unique()).issubset({0.0, 1.0})
