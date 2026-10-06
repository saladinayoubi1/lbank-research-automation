from __future__ import annotations

from copy import deepcopy

import pytest

import nexus_composite_runtime_requalification as rq


def _candidate():
    return {
        "candidate_digest": "a" * 64,
        "source_sha": "b" * 40,
        "decision": "FORWARD_TO_VAL40",
        "eligible_for_fresh_runtime_requalification": True,
        "requires_fresh_runtime_data": True,
        "mechanism": "factory_gen_example",
        "timeframe": "minute15_with_completed_1h_4h",
        "strategy_config": {
            "mechanism": "factory_gen_example",
            "risk_variant": 0,
            "entry_model": "closed_4h_1h_15m_next_open",
            "factory_contract_digest": "c" * 64,
        },
        "config_fingerprint": "d" * 64,
        "paper_only": True,
        "candidate_state_created": False,
        "qualification_authority": False,
        "registry_mutation_authority": False,
        "promotion_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }


def _verification(candidate):
    return {
        "schema_version": "test-candidate-verification",
        "decision": "pass",
        "candidate_digest": candidate["candidate_digest"],
        "verification_digest": "e" * 64,
    }


def _dataset(symbol, timeframe):
    steps = {"minute15": 900_000, "hour1": 3_600_000, "hour4": 14_400_000}
    step = steps[timeframe]
    start = 1_700_000_000_000 - (1_700_000_000_000 % step)
    rows = []
    for index in range(1000):
        price = 100.0 + index * 0.01
        rows.append({
            "open_time_ms": start + index * step,
            "open": price,
            "high": price + 1.0,
            "low": price - 1.0,
            "close": price + 0.2,
            "volume": 1000.0,
        })
    return {
        "paper_only": True,
        "downstream_eligible": True,
        "source": "Bybit",
        "source_role": "primary",
        "instrument": symbol,
        "manifest_timeframe": timeframe,
        "finality": "closed_only",
        "row_count": 1000,
        "binding_sha256": rq.digest({"symbol": symbol, "timeframe": timeframe}),
        "rows": rows,
    }


def _rows(candidate, symbol, value=0.1, trades=1, halted=False):
    return [
        {
            "symbol": symbol,
            "profile": profile,
            "mechanism": candidate["mechanism"],
            "timeframe": candidate["timeframe"],
            "config_fingerprint": candidate["config_fingerprint"],
            "bars": 1000,
            "net_return_pct": value,
            "net_pnl_usdt": value * 100,
            "max_drawdown_pct": 0.2,
            "closed_round_trips": trades,
            "win_rate_pct": 50.0 if trades else None,
            "profit_factor": 1.2 if trades else None,
            "profit_factor_status": "AVAILABLE" if trades else "NOT_AVAILABLE_NO_REALIZED_LOSSES",
            "turnover_usdt": 100.0 if trades else 0.0,
            "exposure_bar_ratio": 0.01 if trades else 0.0,
            "halted_on_drawdown": halted,
            "fee_bps": 10.0 if profile == "conservative" else 25.0,
            "slippage_bps": 5.0 if profile == "conservative" else 15.0,
            "trade_count_limit": None,
            "concurrent_risk_model": "one_collateral_backed_net_long_per_symbol;10pct_position_budget",
        }
        for profile in ("conservative", "stress")
    ]


def test_fresh_runtime_positive_candidate_qualifies_for_review(monkeypatch):
    candidate = _candidate()
    verification = _verification(candidate)
    monkeypatch.setattr(rq, "verify_candidate", lambda value: verification)
    result = rq.run_requalification(
        candidate,
        verification,
        execution_source_sha="f" * 40,
        now_ms=1_800_000_000_000,
        dataset_loader=lambda symbol, timeframe, limit: _dataset(symbol, timeframe),
        evaluator=lambda cand, symbol, datasets, peer: _rows(cand, symbol),
    )
    assert result["decision"] == "QUALIFIED_FOR_REVIEW"
    assert result["qualified_for_review"] is True
    assert result["total_runtime_round_trips"] == 4
    assert result["no_minimum_trade_count_gate"] is True
    assert result["qualification_authority"] is False
    assert result["paper_execution_authority"] is False
    assert result["live_trading_authority"] is False
    monkeypatch.setattr(rq, "verify_candidate", lambda value: verification)
    assert rq.verify_requalification(result)["decision"] == "pass"


@pytest.mark.parametrize(
    ("value", "trades", "halted", "reason"),
    [
        (0.0, 0, False, "ZERO_ACTIVITY"),
        (-0.1, 1, False, "NON_POSITIVE_RUNTIME_CELL"),
        (0.1, 1, True, "DRAWDOWN_HALT"),
    ],
)
def test_fresh_runtime_rejections_are_not_qualification(value, trades, halted, reason, monkeypatch):
    candidate = _candidate()
    verification = _verification(candidate)
    monkeypatch.setattr(rq, "verify_candidate", lambda value: verification)
    result = rq.run_requalification(
        candidate,
        verification,
        execution_source_sha="f" * 40,
        now_ms=1_800_000_000_000,
        dataset_loader=lambda symbol, timeframe, limit: _dataset(symbol, timeframe),
        evaluator=lambda cand, symbol, datasets, peer: _rows(
            cand, symbol, value=value, trades=trades, halted=halted
        ),
    )
    assert result["decision"] == "REJECTED_FRESH_RUNTIME"
    assert result["reason_codes"] == [reason]
    assert result["qualified_for_review"] is False
    assert result["qualification_authority"] is False


def test_runtime_replay_must_be_deterministic(monkeypatch):
    candidate = _candidate()
    verification = _verification(candidate)
    monkeypatch.setattr(rq, "verify_candidate", lambda value: verification)
    count = {"n": 0}

    def evaluator(cand, symbol, datasets, peer):
        count["n"] += 1
        return _rows(cand, symbol, value=0.1 + count["n"] * 0.001)

    with pytest.raises(rq.CompositeRuntimeRequalificationError, match="not deterministic"):
        rq.run_requalification(
            candidate,
            verification,
            execution_source_sha="f" * 40,
            now_ms=1_800_000_000_000,
            dataset_loader=lambda symbol, timeframe, limit: _dataset(symbol, timeframe),
            evaluator=evaluator,
        )


def test_dataset_or_candidate_tamper_fails_closed(monkeypatch):
    candidate = _candidate()
    verification = _verification(candidate)
    monkeypatch.setattr(rq, "verify_candidate", lambda value: verification)

    def bad_loader(symbol, timeframe, limit):
        artifact = _dataset(symbol, timeframe)
        artifact["source"] = "Binance"
        return artifact

    with pytest.raises(rq.CompositeRuntimeRequalificationError, match="dataset contract"):
        rq.run_requalification(
            candidate,
            verification,
            execution_source_sha="f" * 40,
            now_ms=1_800_000_000_000,
            dataset_loader=bad_loader,
            evaluator=lambda cand, symbol, datasets, peer: _rows(cand, symbol),
        )

    bad_candidate = deepcopy(candidate)
    bad_candidate["live_trading_authority"] = True
    with pytest.raises(rq.CompositeRuntimeRequalificationError, match="not eligible"):
        rq.run_requalification(
            bad_candidate,
            verification,
            execution_source_sha="f" * 40,
            now_ms=1_800_000_000_000,
            dataset_loader=lambda symbol, timeframe, limit: _dataset(symbol, timeframe),
            evaluator=lambda cand, symbol, datasets, peer: _rows(cand, symbol),
        )
