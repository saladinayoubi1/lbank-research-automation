from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import agent_manager
import nexus_composite_strategy_research as research
import nexus_mechanism_factory as factory
from nexus_research_missions import (
    FOURTEENTH,
    FIFTEENTH,
    SIXTEENTH,
    SEVENTEENTH,
    PREDECESSOR,
    TASKS,
)


G3_FIELDS = {
    "lagged_return_skew_64",
    "lagged_downside_variance_share_64",
    "lagged_drawdown_depth_32",
    "lagged_recovery_from_low_32",
    "lagged_wick_asymmetry_32",
    "lagged_abs_return_autocorr_48",
    "lagged_close_location_persistence_16",
    "lagged_peer_lead_corr_96",
}


def _ohlcv(freq: str, periods: int, *, phase: float) -> pd.DataFrame:
    ts = pd.date_range("2026-01-01", periods=periods, freq=freq, tz="UTC")
    x = np.arange(periods, dtype=float)
    close = 100.0 + 0.02 * x + 0.55 * np.sin(x / 13.0 + phase)
    open_ = close * (1.0 + 0.0007 * np.sin(x / 7.0 + phase))
    high = np.maximum(open_, close) * (1.002 + 0.0002 * np.sin(x / 5.0))
    low = np.minimum(open_, close) * (0.998 - 0.0002 * np.cos(x / 6.0))
    volume = 1000.0 + 80.0 * np.cos(x / 11.0 + phase)
    return pd.DataFrame({
        "timestamp": ts,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


def _frames() -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    return (
        {
            "minute15": _ohlcv("15min", 1200, phase=0.0),
            "hour1": _ohlcv("1h", 300, phase=0.2),
            "hour4": _ohlcv("4h", 75, phase=0.4),
        },
        _ohlcv("15min", 1200, phase=0.8),
    )


def test_generator_v3_contexts_use_new_causal_primitives():
    # Generator v2's first five contexts are historical and immutable.
    g3_contexts = factory.GENERATOR_CONTEXTS[5:]
    assert len(g3_contexts) == 8
    for name, conditions in g3_contexts:
        fields = {row["field"] for row in conditions}
        fields |= {row["other"] for row in conditions if "other" in row}
        assert fields & G3_FIELDS, name


def test_generator_v3_features_are_current_bar_invariant():
    frames, peer = _frames()
    baseline = research.build_features(frames, peer_15m=peer)

    mutated = {key: value.copy() for key, value in frames.items()}
    i = len(mutated["minute15"]) - 1
    mutated["minute15"].loc[i, "close"] *= 1.09
    mutated["minute15"].loc[i, "open"] *= 0.94
    mutated["minute15"].loc[i, "high"] = max(
        mutated["minute15"].loc[i, "open"],
        mutated["minute15"].loc[i, "close"],
    ) * 1.01
    mutated["minute15"].loc[i, "low"] = min(
        mutated["minute15"].loc[i, "open"],
        mutated["minute15"].loc[i, "close"],
    ) * 0.99
    mutated["minute15"].loc[i, "volume"] *= 4.0

    peer_mutated = peer.copy()
    j = len(peer_mutated) - 1
    peer_mutated.loc[j, "close"] *= 1.12
    peer_mutated.loc[j, "high"] = max(
        peer_mutated.loc[j, "open"], peer_mutated.loc[j, "close"]
    ) * 1.01
    peer_mutated.loc[j, "low"] = min(
        peer_mutated.loc[j, "open"], peer_mutated.loc[j, "close"]
    ) * 0.99

    changed = research.build_features(mutated, peer_15m=peer_mutated)
    for field in sorted(G3_FIELDS):
        left = baseline.iloc[-1][field]
        right = changed.iloc[-1][field]
        assert (pd.isna(left) and pd.isna(right)) or np.isclose(
            float(left), float(right), rtol=0.0, atol=1e-12
        ), (field, left, right)


def test_generator_v3_adds_exactly_three_unseen_batches_after_v2():
    fixed = factory.load_factory_contract()
    v2 = factory.generate_factory_contracts(fixed, limit=24)
    v3 = factory.generate_factory_contracts_v3({**fixed, **v2}, limit=36)
    combined = {**v2, **v3}
    assert len(v2) == 24
    assert len(v3) == 36
    assert len(combined) == 60
    assert tuple(combined)[:24] == tuple(v2)
    for ident, row in v2.items():
        assert combined[ident] == row
    new = list(v3)
    assert len(new) == 36
    assert len(set(new)) == 36
    assert all(any(token in ident for token in (
        "downside_tail_exhaustion",
        "positive_tail_trend",
        "deep_drawdown_recovery",
        "shallow_drawdown_acceptance",
        "wick_pressure_range",
        "wick_pressure_trend",
        "volatility_cluster_release",
        "peer_lead_followthrough",
    )) for ident in new)


def test_generator_v3_missions_are_strict_sequential_qa_successors():
    assert PREDECESSOR[FIFTEENTH] == FOURTEENTH
    assert PREDECESSOR[SIXTEENTH] == FIFTEENTH
    assert PREDECESSOR[SEVENTEENTH] == SIXTEENTH
    assert {FIFTEENTH, SIXTEENTH, SEVENTEENTH} <= TASKS

    cfg = agent_manager.load_config(Path("config/nexus-agent-manager.json"))
    by_id = {row["id"]: row for row in cfg["tasks"]}
    for task_id, predecessor in (
        (FIFTEENTH, FOURTEENTH),
        (SIXTEENTH, FIFTEENTH),
        (SEVENTEENTH, SIXTEENTH),
    ):
        task = by_id[task_id]
        assert task["dependencies"] == [predecessor]
        assert task["status"] == "PENDING"
        assert task["authority"] == 2
        acceptance = " ".join(task["acceptance"]).lower()
        assert "training-only" in acceptance
        assert "no minimum trade-count gate" in acceptance
        assert "independent" in acceptance
        assert "no automatic paper/demo promotion" in acceptance
        assert "no owner-wallet mutation" in acceptance
        assert "live authority" in acceptance
