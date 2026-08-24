from __future__ import annotations

import math

import pytest

from phase5_paper_trading import PaperTradingError, evaluate_paper_candidate


def qualification():
    return {
        "status": "paper_candidate",
        "paper_only": True,
        "live_execution_allowed": False,
        "strategy_version": "momentum-v1",
        "qualification_digest": "a" * 64,
    }


def fills(count=30, days=30, pnl=10.0):
    step = math.ceil(days * 86_400_000 / max(count - 1, 1))
    return [
        {
            "timestamp_ms": 1_700_000_000_000 + i * step,
            "side": "buy" if i % 2 == 0 else "sell",
            "quantity": 1.0,
            "mark_price": 100.0,
            "fill_price": 100.1,
            "fee": 0.1,
            "funding": 0.05,
            "realized_pnl": pnl,
        }
        for i in range(count)
    ]


def test_candidate_is_proved_only_after_time_trade_and_drawdown_gates():
    report = evaluate_paper_candidate(qualification(), fills(), initial_equity=10_000)
    assert report["status"] == "proved_in_paper"
    assert report["paper_only"] is True
    assert report["live_execution_allowed"] is False
    assert report["trade_count"] == 30
    assert report["observed_days"] == pytest.approx(30)


def test_short_observation_remains_observing_without_live_authority():
    report = evaluate_paper_candidate(qualification(), fills(count=5, days=2), initial_equity=10_000)
    assert report["status"] == "observing"
    assert set(report["reasons"]) == {"INSUFFICIENT_TRADES", "INSUFFICIENT_OBSERVATION_DAYS"}
    assert report["live_execution_allowed"] is False


def test_drawdown_breach_rejects_candidate():
    report = evaluate_paper_candidate(
        qualification(), fills(pnl=-100.0), initial_equity=1_000, maximum_drawdown_pct=20,
    )
    assert report["status"] == "rejected"
    assert "DRAWDOWN_LIMIT_BREACHED" in report["reasons"]


def test_non_candidate_and_malformed_or_unordered_fills_fail_closed():
    bad = qualification()
    bad["status"] = "killed"
    with pytest.raises(PaperTradingError, match="qualified"):
        evaluate_paper_candidate(bad, [], initial_equity=1000)
    unordered = fills(count=2, days=1)
    unordered[1]["timestamp_ms"] = unordered[0]["timestamp_ms"]
    with pytest.raises(PaperTradingError, match="strictly increasing"):
        evaluate_paper_candidate(qualification(), unordered, initial_equity=1000)
