from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import agent_manager
import nexus_composite_strategy_research as research
import nexus_mechanism_factory as factory
from nexus_research_missions import (
    EIGHTEENTH,
    NINETEENTH,
    PREDECESSOR,
    SEVENTEENTH,
    TASKS,
)


G4_FIELDS = {
    "lagged_directional_entropy_64",
    "lagged_range_compression_ratio_32",
    "lagged_volume_return_corr_64",
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


def test_generator_v4_is_distinct_and_preserves_v2_v3_contracts():
    fixed = factory.load_factory_contract()
    v2 = factory.generate_factory_contracts(fixed, limit=24)
    v3 = factory.generate_factory_contracts_v3({**fixed, **v2}, limit=36)
    v4 = factory.generate_factory_contracts_v4({**fixed, **v2, **v3}, limit=15)

    assert len(v2) == 24
    assert len(v3) == 36
    assert len(v4) == 15
    assert not (set(v4) & (set(v2) | set(v3)))
    assert tuple(research.GENERATED_FACTORY_SPECS)[:60] == tuple({**v2, **v3})
    assert set(v4) <= set(research.GENERATED_FACTORY_SPECS)
    for name, conditions in factory.GENERATOR_CONTEXTS_V4:
        fields = {row["field"] for row in conditions}
        fields |= {row["other"] for row in conditions if "other" in row}
        assert fields & G4_FIELDS, name


def test_generator_v4_features_are_current_bar_invariant():
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

    changed = research.build_features(mutated, peer_15m=peer)
    for field in sorted(G4_FIELDS):
        left = baseline.iloc[-1][field]
        right = changed.iloc[-1][field]
        assert (pd.isna(left) and pd.isna(right)) or np.isclose(
            float(left), float(right), rtol=0.0, atol=1e-12
        ), (field, left, right)


def test_generator_v4_missions_are_sequential_qa_successors():
    assert PREDECESSOR[EIGHTEENTH] == SEVENTEENTH
    assert PREDECESSOR[NINETEENTH] == EIGHTEENTH
    assert {EIGHTEENTH, NINETEENTH} <= TASKS

    cfg = agent_manager.load_config(Path("config/nexus-agent-manager.json"))
    by_id = {row["id"]: row for row in cfg["tasks"]}
    for task_id, predecessor in (
        (EIGHTEENTH, SEVENTEENTH),
        (NINETEENTH, EIGHTEENTH),
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
