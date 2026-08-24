from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import time

import pytest

from nexus_paper_performance_drift import PaperPerformanceDriftError, evaluate_paper_drift
from nexus_strategy_paper_supervisor import run_once
from phase5_strategy_factory import build_experiment, qualify
from phase6_research_pipeline import bind_bybit_closed_dataset
from strategy_lifecycle import build_research_lifecycle
from strategy_registry import build_strategy_record

STEP = 900_000
NOW = int(time.time() * 1000)
SOURCE = "a" * 40


def _dataset(count: int = 240):
    end_open = ((NOW - STEP) // STEP) * STEP
    start = end_open - (count - 1) * STEP
    rows = []
    for index in range(count):
        price = 80 + index * 0.5
        rows.append({
            "source": "Bybit", "market_type": "spot", "symbol": "BTCUSDT",
            "interval": "15", "open_time_ms": start + index * STEP,
            "close_time_ms": start + (index + 1) * STEP - 1,
            "open": f"{price:.8f}", "high": f"{price * 1.01:.8f}",
            "low": f"{price * 0.99:.8f}", "close": f"{price:.8f}",
            "volume": "10", "turnover": f"{price * 10:.8f}", "closed": True,
        })
    return bind_bybit_closed_dataset(
        rows, canonical_symbol="BTC/USDT", source_symbol="BTCUSDT", interval="15"
    )


def _fetcher(**_):
    return deepcopy(_dataset())


def _kills():
    return {
        "min_robustness_score": -1.0, "max_cost_stress_loss_pct": 100.0,
        "min_walk_forward_score": -1.0, "min_oos_score": -1.0,
        "max_drawdown_pct": 100.0, "min_regime_pass_ratio": 0.0,
        "max_failure_mode_severity": 10.0,
    }


def _trades(pnls):
    return [{
        "trade_id": f"trade-{index}", "opened_at_ms": 1_700_000_000_000 + index * 20_000,
        "closed_at_ms": 1_700_000_010_000 + index * 20_000,
        "gross_pnl": str(pnl), "fees": "1", "entry_notional": "500",
        "exit_notional": "500", "regime": "TREND_UP",
    } for index, pnl in enumerate(pnls)]


class _AcceptedResearch:
    def __init__(self, dataset):
        experiment = build_experiment(
            dataset, hypothesis="bounded Paper monitor hypothesis", family="momentum",
            strategy_version="momentum-monitor-v1", config={"lookback": 3},
            code_sha=SOURCE, cost_model={"fee_bps": 10.0, "slippage_bps": 5.0},
            kill_criteria=_kills(),
        )
        evidence = {
            "evidence_refs": ["dataset-sha256:" + dataset["binding_sha256"]],
            "hypothesis_supported": True, "preregistered": True,
            "robustness_score": 0.1, "cost_stress_loss_pct": 1.0,
            "walk_forward_score": 0.1, "oos_score": 0.1,
            "max_drawdown_pct": 5.0, "regime_pass_ratio": 0.67,
            "failure_mode_severity": 0.0, "benchmark_score": 0.05,
            "uncertainty_width": 0.01, "survivorship_control": True,
            "lookahead_control": True, "data_snooping_control": True,
        }
        qualification = qualify(dataset, experiment, evidence)
        record = build_strategy_record(dataset, experiment, qualification, evidence)
        self.result = {
            "qualification": qualification, "strategy_record": record,
            "research_lifecycle": list(build_research_lifecycle(record)),
        }

    def run_research(self, **_):
        return deepcopy(self.result)

    def auto_paper(self):
        return {
            "paper_only": True, "live_trading_authority": False, "accepted": True,
            "status": "paper_executed", "risk": {"allowed": True},
            "execution": {"fill_price": "100", "fee": "1", "slippage_cost": "0.1"},
        }


def _task(tmp_path: Path):
    ledger = run_once(
        source_sha=SOURCE, state_root=tmp_path, families=("momentum",),
        now_ms=NOW, dataset_fetcher=_fetcher,
        research_factory=lambda _runtime, _source, dataset, _now: _AcceptedResearch(dataset),
    )
    return ledger, ledger["tasks"][0]


def test_insufficient_closed_trades_preserves_paper_state(tmp_path: Path) -> None:
    ledger, task = _task(tmp_path)
    result = evaluate_paper_drift(
        supervisor_ledger=ledger, task_id=task["task_id"],
        closed_trades=_trades([2, 2]), baseline_expectancy="2", baseline_fee_per_trade="1",
    )
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["lifecycle_state"] == "PAPER"


def test_healthy_paper_evidence_is_measured_without_promotion(tmp_path: Path) -> None:
    ledger, task = _task(tmp_path)
    result = evaluate_paper_drift(
        supervisor_ledger=ledger, task_id=task["task_id"],
        closed_trades=_trades([3, 4, 2, 3, 4]), baseline_expectancy="2", baseline_fee_per_trade="1",
    )
    assert result["status"] == "HEALTHY"
    assert result["lifecycle_state"] == "PAPER"
    assert result["promotion_authority"] is False


def test_severe_performance_drift_quarantines_strategy(tmp_path: Path) -> None:
    ledger, task = _task(tmp_path)
    result = evaluate_paper_drift(
        supervisor_ledger=ledger, task_id=task["task_id"],
        closed_trades=_trades([-5, -4, -6, -5, -7]), baseline_expectancy="2",
        baseline_fee_per_trade="1",
    )
    assert result["status"] == "QUARANTINED"
    assert result["lifecycle_state"] == "QUARANTINED"
    assert result["lifecycle"][-1]["reason_code"] == "HEALTH_QUARANTINE"


def test_unverified_supervisor_or_live_authority_fails_closed(tmp_path: Path) -> None:
    ledger, task = _task(tmp_path)
    tampered = deepcopy(ledger)
    tampered["tasks"][0]["family"] = "tampered"
    with pytest.raises(PaperPerformanceDriftError, match="not independently verified"):
        evaluate_paper_drift(
            supervisor_ledger=tampered, task_id=task["task_id"],
            closed_trades=_trades([1] * 5), baseline_expectancy="1", baseline_fee_per_trade="1",
        )
    with pytest.raises(PaperPerformanceDriftError, match="uniquely bound"):
        evaluate_paper_drift(
            supervisor_ledger=ledger, task_id="missing-task",
            closed_trades=_trades([1] * 5), baseline_expectancy="1", baseline_fee_per_trade="1",
        )
