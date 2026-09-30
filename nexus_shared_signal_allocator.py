"""Central shared-equity target allocator for Paper execution.

Strategies contribute exposure intents, never permanent cash slices. Intents are
netted at portfolio level and only then capped. Exchange lot/minimum checks stay
in the execution simulator so the allocator never rounds a signal up to force a
trade.
"""
from __future__ import annotations

import math
from typing import Mapping, Sequence


class SharedAllocatorError(ValueError):
    pass


def aggregate_targets(
    signals: Mapping[str, Sequence[float]],
    *,
    gross_cap: float = 0.95,
    asset_cap: float = 0.60,
) -> dict:
    if not (0.0 < gross_cap <= 1.0 and 0.0 < asset_cap <= 1.0):
        raise SharedAllocatorError("invalid shared portfolio caps")
    contributions = {}
    raw = [0.0, 0.0]
    for strategy, values in sorted(signals.items()):
        if not strategy or len(values) != 2:
            raise SharedAllocatorError("each signal must identify a two-asset target")
        row = [float(values[0]), float(values[1])]
        if not all(math.isfinite(x) and abs(x) <= 1.0 + 1e-12 for x in row):
            raise SharedAllocatorError("signal target is non-finite or outside [-1,1]")
        contributions[strategy] = row
        raw[0] += row[0]
        raw[1] += row[1]

    capped = [max(-asset_cap, min(asset_cap, x)) for x in raw]
    gross = sum(abs(x) for x in capped)
    scale = min(1.0, gross_cap / gross) if gross else 1.0
    target = [x * scale for x in capped]
    return {
        "schema": "nexus.shared-equity-target-allocation.v1",
        "mode": "shared_equity",
        "per_strategy_fixed_cash": False,
        "contributions": contributions,
        "raw_net_target": raw,
        "target_weights": target,
        "gross_cap": gross_cap,
        "asset_cap": asset_cap,
        "gross_after_caps": sum(abs(x) for x in target),
        "minimum_order_policy": "execution_layer_never_round_up",
    }
