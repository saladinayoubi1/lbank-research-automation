from __future__ import annotations

from copy import deepcopy

import pytest

from market_data_provenance_manifest import build_provenance_manifest
import phase5_data_binding as data_binding
import phase5_strategy_factory as factory

START = 1_640_995_200_000
ENDPOINT = "/v5/market/kline?category=spot&symbol=BTCUSDT&interval=15"


def dataset():
    rows = [
        {"open_time_ms": START, "open": "47000", "high": "47100", "low": "46900", "close": "47050", "volume": "12.5"},
        {"open_time_ms": START + 900_000, "open": "47050", "high": "47200", "low": "47000", "close": "47150", "volume": "10.0"},
    ]
    manifest = build_provenance_manifest(
        source="Bybit", market_type="spot", source_symbol="BTCUSDT", canonical_symbol="BTC/USDT",
        timeframe="15m", endpoint_contract=ENDPOINT, mapping_policy_version="1.0.0",
        retrieval_start_ms=START, retrieval_end_ms=START + 900_000, candles=rows,
    )
    return data_binding.bind_canonical_dataset(manifest, rows)


def kills():
    return {
        "min_robustness_score": 0.60,
        "max_cost_stress_loss_pct": 12.0,
        "min_walk_forward_score": 0.55,
        "min_oos_score": 0.55,
        "max_drawdown_pct": 25.0,
        "min_regime_pass_ratio": 0.60,
        "max_failure_mode_severity": 0.40,
    }


def experiment(ds=None):
    return factory.build_experiment(
        ds or dataset(), hypothesis="momentum persists after bounded costs", family="momentum",
        strategy_version="momentum-v1", config={"lookback": 20, "threshold": 1.2}, code_sha="a" * 40,
        cost_model={"fee_bps": 10, "slippage_bps": 5, "funding_bps": 0}, kill_criteria=kills(),
    )


def evidence(**updates):
    value = {
        "evidence_refs": ["research:#45", "dataset:btc-usdt-15m"],
        "hypothesis_supported": True,
        "preregistered": True,
        "robustness_score": 0.75,
        "cost_stress_loss_pct": 6.0,
        "walk_forward_score": 0.70,
        "oos_score": 0.68,
        "max_drawdown_pct": 18.0,
        "regime_pass_ratio": 0.75,
        "failure_mode_severity": 0.20,
        "benchmark_score": 0.62,
        "uncertainty_width": 0.12,
        "survivorship_control": True,
        "lookahead_control": True,
        "data_snooping_control": True,
    }
    value.update(updates)
    return value


def test_full_frozen_path_can_produce_paper_candidate_without_live_authority():
    ds = dataset()
    result = factory.qualify(ds, experiment(ds), evidence())
    assert result["status"] == "paper_candidate"
    assert result["stage_path"][-1] == "Paper Candidate"
    assert result["kill_reasons"] == []
    assert result["paper_only"] is True
    assert result["live_execution_allowed"] is False
    assert result["deterministic_risk_final_authority"] is True


def test_preregistered_kill_is_deterministic_and_never_promotes():
    ds = dataset()
    exp = experiment(ds)
    bad = evidence(robustness_score=0.40)
    first = factory.qualify(ds, exp, bad)
    second = factory.qualify(ds, exp, deepcopy(bad))
    assert first == second
    assert first["status"] == "killed"
    assert first["kill_reasons"] == ["ROBUSTNESS_KILL"]
    assert first["stage_path"][-1] == "Qualification Artifact"


def test_bias_controls_and_preregistration_fail_closed():
    ds = dataset()
    exp = experiment(ds)
    result = factory.qualify(ds, exp, evidence(preregistered=False, lookahead_control=False))
    assert result["status"] == "killed"
    assert "NOT_PREREGISTERED" in result["kill_reasons"]
    assert "LOOKAHEAD_CONTROL_FAILED" in result["kill_reasons"]


def test_experiment_identity_binds_data_code_config_and_cost_model():
    ds = dataset()
    exp = experiment(ds)
    for field, value in (
        ("code_sha", "b" * 40),
        ("config", {"lookback": 99}),
        ("cost_model", {"fee_bps": 0}),
        ("dataset_binding_sha256", "f" * 64),
    ):
        mutated = deepcopy(exp)
        mutated[field] = value
        with pytest.raises(factory.StrategyFactoryError, match="identity|different data"):
            factory.qualify(ds, mutated, evidence())


def test_raw_unbound_data_and_unapproved_family_cannot_enter_factory():
    with pytest.raises((factory.StrategyFactoryError, data_binding.CanonicalDataError)):
        factory.build_experiment(
            {"rows": []}, hypothesis="x", family="momentum", strategy_version="v1", config={"x": 1},
            code_sha="a" * 40, cost_model={"fee_bps": 1}, kill_criteria=kills(),
        )
    with pytest.raises(factory.StrategyFactoryError, match="family"):
        factory.build_experiment(
            dataset(), hypothesis="x", family="magic", strategy_version="v1", config={"x": 1},
            code_sha="a" * 40, cost_model={"fee_bps": 1}, kill_criteria=kills(),
        )


def test_ad_hoc_incomplete_backtest_cannot_skip_qualification_stages():
    ds = dataset()
    with pytest.raises(factory.StrategyFactoryError, match="evidence schema"):
        factory.qualify(ds, experiment(ds), {"oos_score": 1.0})
