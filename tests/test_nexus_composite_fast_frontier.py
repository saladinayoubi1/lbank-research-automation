from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import nexus_agent_research_prepare as prepare
import nexus_composite_strategy_research as research
import agent_manager
from nexus_research_missions import NINTH, TENTH, PREDECESSOR, TASKS


def _legacy_complete_ledger():
    state = research.empty_ledger()
    core = {key: value for key, value in state.items() if key != "ledger_digest"}
    for mechanism in research.MECHANISMS:
        cfg = next(
            item for item in research.CONFIGS
            if item["mechanism"] == mechanism and item["risk_variant"] == 0
        )
        core["mechanisms_evaluated"].append(mechanism)
        core["config_fingerprints_evaluated"].append(
            research.digest({
                "config": cfg,
                "dataset": research.ARCHIVE_SHA256,
                "contract": research.SCHEMA,
            })
        )
    core["mechanisms_evaluated"] = sorted(set(core["mechanisms_evaluated"]))
    return {**core, "ledger_digest": research.digest(core)}


def test_frontier_tournament_preempts_legacy_risk_variant_cycle():
    state = _legacy_complete_ledger()
    legacy_next = research.select_next(state)
    assert legacy_next is not None
    assert legacy_next["risk_variant"] == 1
    assert research.research_mode(state) == "frontier_tournament"
    assert research.has_runnable_candidate(state) is True
    frontier = research._frontier_configs_to_screen(state)
    assert len(frontier) == len(research.FRONTIER_MECHANISMS)
    assert {row["mechanism"] for row in frontier} == set(research.FRONTIER_MECHANISMS)

    core = {key: value for key, value in state.items() if key != "ledger_digest"}
    core["frontier_screening_version"] = research.FRONTIER_SCREEN_VERSION
    core["frontier_screened_mechanisms"] = sorted(research.FRONTIER_MECHANISMS)
    exhausted = {**core, "ledger_digest": research.digest(core)}
    assert research.research_mode(exhausted) == "exhausted"
    assert research.has_runnable_candidate(exhausted) is False



def test_preparer_accepts_frontier_tournament_and_rejects_true_exhaustion():
    state = _legacy_complete_ledger()
    predecessor = {"research_predecessor_mechanism": "regime_conditional_composite"}

    prepare._ensure_new_reviewed_work(state, predecessor)

    core = {key: value for key, value in state.items() if key != "ledger_digest"}
    core["frontier_screening_version"] = research.FRONTIER_SCREEN_VERSION
    core["frontier_screened_mechanisms"] = sorted(research.FRONTIER_MECHANISMS)
    exhausted = {**core, "ledger_digest": research.digest(core)}
    with pytest.raises(prepare.ResearchPreparationError, match="no new reviewed"):
        prepare._ensure_new_reviewed_work(exhausted, predecessor)

def test_frontier_rank_prefers_activity_breadth_and_stress_resilience():
    zero = {
        "mechanism": "zero",
        "has_activity": False,
        "positive_cells": 4,
        "stress_median_return_pct": 9.0,
        "worst_return_pct": 9.0,
        "median_return_pct": 9.0,
        "max_drawdown_pct": 0.0,
    }
    active_weak = {
        "mechanism": "active_weak",
        "has_activity": True,
        "positive_cells": 1,
        "stress_median_return_pct": -1.0,
        "worst_return_pct": -2.0,
        "median_return_pct": -0.5,
        "max_drawdown_pct": 3.0,
    }
    active_robust = {
        "mechanism": "active_robust",
        "has_activity": True,
        "positive_cells": 3,
        "stress_median_return_pct": 0.2,
        "worst_return_pct": -0.1,
        "median_return_pct": 0.4,
        "max_drawdown_pct": 1.5,
    }
    ranked = sorted([zero, active_weak, active_robust], key=research._frontier_rank_key)
    assert [row["mechanism"] for row in ranked] == [
        "active_robust", "active_weak", "zero"
    ]


def test_all_frontier_mechanisms_emit_bounded_boolean_signals():
    n = 8
    frame = pd.DataFrame({
        "close": np.linspace(100.0, 101.4, n),
        "open": np.linspace(99.8, 101.0, n),
        "high": np.linspace(100.4, 101.8, n),
        "low": np.linspace(99.4, 100.6, n),
        "h4_up": [1] * n,
        "h4_range": [1] * n,
        "h1_compression": [1] * n,
        "h1_vol_ok": [1] * n,
        "rel_vol": [1.4] * n,
        "rel_vol_previous": [0.5] * n,
        "prior_hi": [100.2] * n,
        "prior_lo": [99.5] * n,
        "prior_range_mid": [99.85] * n,
        "atr": [1.0] * n,
        "bar_proxy_vwap": [100.0] * n,
        "close_location": [0.8] * n,
        "body_efficiency": [0.7] * n,
        "lagged_own_return_1h": [0.006] * n,
        "lagged_own_return_4h": [0.012] * n,
        "own_return_1h_abs_baseline": [0.003] * n,
        "own_realized_volatility": [0.02] * n,
        "own_realized_volatility_baseline": [0.015] * n,
        "relative_momentum_previous": [0.004] * n,
        "relative_momentum_baseline": [0.001] * n,
        "cross_pair_relative_z_previous": [-1.8] * n,
        "cross_pair_volatility_ratio": [1.6] * n,
        "cross_pair_volatility_ratio_baseline": [1.1] * n,
    })
    for mechanism in research.FRONTIER_MECHANISMS:
        signal = research.signal_for(
            frame,
            {"mechanism": mechanism, "risk_variant": 0},
        )
        assert signal.dtype == bool
        assert signal.shape == (n,)


def test_mission_010_is_sequential_qa_bound_and_manager_declared():
    assert PREDECESSOR[TENTH] == NINTH
    assert TENTH in TASKS
    config = agent_manager.load_config(Path("config/nexus-agent-manager.json"))
    task = next(row for row in config["tasks"] if row["id"] == TENTH)
    assert task["dependencies"] == [NINTH]
    assert task["authority"] == 2
    acceptance = " ".join(task["acceptance"]).lower()
    assert "training-only tournament" in acceptance
    assert "independent" in acceptance
    assert "no automatic paper/demo promotion" in acceptance
