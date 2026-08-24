from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from phase5_paper_trading import evaluate_paper_candidate
from phase5_strategy_factory import qualify


def run_paper_validation_pipeline(
    dataset: Mapping[str, Any],
    experiment: Mapping[str, Any],
    qualification_evidence: Mapping[str, Any],
    fills: Sequence[Mapping[str, Any]],
    *,
    initial_equity: float,
    minimum_days: int = 30,
    minimum_trades: int = 30,
    maximum_drawdown_pct: float = 20.0,
) -> dict[str, Any]:
    """Connect frozen qualification to live-like, paper-only validation."""
    qualification = qualify(dataset, experiment, qualification_evidence)
    if qualification["status"] != "paper_candidate":
        return {
            "pipeline_status": "qualification_rejected",
            "qualification": qualification,
            "paper_report": None,
            "paper_only": True,
            "live_execution_allowed": False,
        }
    report = evaluate_paper_candidate(
        qualification,
        fills,
        initial_equity=initial_equity,
        minimum_days=minimum_days,
        minimum_trades=minimum_trades,
        maximum_drawdown_pct=maximum_drawdown_pct,
    )
    return {
        "pipeline_status": report["status"],
        "qualification": qualification,
        "paper_report": report,
        "paper_only": True,
        "live_execution_allowed": False,
    }
