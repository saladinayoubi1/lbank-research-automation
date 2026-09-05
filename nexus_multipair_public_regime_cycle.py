"""Run the accepted four-symbol NEXUS regime lifecycle on public Bybit candles.

This adapter keeps the legacy two-symbol public regime path unchanged.  It runs the
existing synchronized regime engine over the exact v2 manifest, verifies the
12-cell result through the bounded multi-pair partition contract, and composes the
unchanged risk-reducing and fresh-Deterministic-Risk Paper lifecycle primitives.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from nexus_demo_regime_cycle import _atomic_json, _digest, run_demo_regime_cycle
from nexus_multipair_regime_lifecycle import (
    run_v2_exposure_increase,
    run_v2_rebalance,
    verify_v2_exposure_increase,
    verify_v2_rebalance,
    verify_v2_regime_snapshot,
)
from nexus_public_regime_cycle import PUBLIC_DATA_MODE
from phase6_research_pipeline import fetch_bind_bybit_dataset


class MultiPairPublicRegimeCycleError(RuntimeError):
    pass


def run_multipair_public_regime_cycle(
    *,
    manifest: Mapping[str, Any],
    matrix_state: Mapping[str, Any],
    state_root: str | Path,
    source_sha: str,
    selector_policy: Mapping[str, Any],
) -> dict[str, Any]:
    root = Path(state_root).resolve()
    snapshot = run_demo_regime_cycle(
        manifest=manifest,
        matrix_state=matrix_state,
        state_root=root,
        source_sha=source_sha,
        archive_fetcher=fetch_bind_bybit_dataset,
        selector_policy=selector_policy,
    )

    core = dict(snapshot)
    core.pop("cycle_digest", None)
    core["archive_sha256"] = None
    core["data_mode"] = PUBLIC_DATA_MODE
    public_snapshot = {**core, "cycle_digest": _digest(core)}
    if verify_v2_regime_snapshot(public_snapshot).get("decision") != "pass":
        raise MultiPairPublicRegimeCycleError("four-symbol public regime verification failed")
    if (
        public_snapshot.get("paper_only") is not True
        or public_snapshot.get("live_trading_authority") is not False
        or public_snapshot.get("private_credentials_used") is not False
        or public_snapshot.get("automatic_strategy_promotion") is not False
        or public_snapshot.get("deterministic_risk_final_authority") is not True
    ):
        raise MultiPairPublicRegimeCycleError("four-symbol public regime widened authority")

    rebalance = run_v2_rebalance(
        manifest=manifest,
        state_root=root,
        source_sha=source_sha,
        regime_snapshot=public_snapshot,
    )
    if verify_v2_rebalance(rebalance).get("decision") != "pass":
        raise MultiPairPublicRegimeCycleError("four-symbol rebalance verification failed")
    if (
        rebalance.get("paper_only") is not True
        or rebalance.get("live_trading_authority") is not False
        or rebalance.get("private_credentials_used") is not False
        or rebalance.get("automatic_strategy_promotion") is not False
        or rebalance.get("deterministic_risk_final_authority") is not True
        or rebalance.get("exposure_increased") is not False
    ):
        raise MultiPairPublicRegimeCycleError("four-symbol rebalance widened authority")

    increase = run_v2_exposure_increase(
        manifest=manifest,
        state_root=root,
        source_sha=source_sha,
        regime_snapshot=public_snapshot,
        rebalance_snapshot=rebalance,
    )
    if verify_v2_exposure_increase(increase).get("decision") != "pass":
        raise MultiPairPublicRegimeCycleError("four-symbol exposure increase verification failed")
    if (
        increase.get("paper_only") is not True
        or increase.get("live_trading_authority") is not False
        or increase.get("private_credentials_used") is not False
        or increase.get("automatic_strategy_promotion") is not False
        or increase.get("deterministic_risk_final_authority") is not True
        or increase.get("fresh_deterministic_risk_required") is not True
        or increase.get("unauthorized_exposure_increase") is not False
    ):
        raise MultiPairPublicRegimeCycleError("four-symbol exposure increase widened authority")

    lifecycle_operational = bool(
        rebalance.get("risk_reducing_rebalance_operational") is True
        and increase.get("exposure_increase_operational") is True
    )
    final_core = dict(public_snapshot)
    final_core.pop("cycle_digest", None)
    final_core["regime_selected_rebalance_digest"] = rebalance["rebalance_digest"]
    final_core["regime_selected_exposure_increase_digest"] = increase["increase_digest"]
    final_core["risk_reducing_rebalance_operational"] = rebalance[
        "risk_reducing_rebalance_operational"
    ]
    final_core["regime_selected_exposure_increase_operational"] = increase[
        "exposure_increase_operational"
    ]
    final_core["regime_selected_rebalance_operational"] = lifecycle_operational
    final_core["regime_selected_rebalance_remaining_gap"] = (
        None if lifecycle_operational else "REGIME_SELECTED_POSITION_CLOSE_AND_RESIZE"
    )
    final_core["next_core_gap"] = "HEALTH_DRIVEN_STRATEGY_FACTORY_CLOSED_LOOP"
    final_snapshot = {**final_core, "cycle_digest": _digest(final_core)}
    if verify_v2_regime_snapshot(final_snapshot).get("decision") != "pass":
        raise MultiPairPublicRegimeCycleError("final four-symbol public regime verification failed")
    _atomic_json(root / "demo" / "regime-cycle.json", final_snapshot)
    return final_snapshot
