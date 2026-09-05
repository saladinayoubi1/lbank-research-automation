"""Run the verified NEXUS regime cycle on canonical public Bybit closed candles.

The underlying selector, independent verifier, Deterministic Risk and isolated
Paper execution are unchanged.  This adapter replaces immutable archive replay
input with the existing bounded public Bybit fetch/bind contract, applies the
risk-reducing lifecycle bridge for already-open positions, and routes any required
exposure increase through an atomic close/reopen with fresh Deterministic Risk.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from nexus_demo_regime_cycle import (
    _atomic_json,
    _digest,
    run_demo_regime_cycle,
    verify_cycle_snapshot,
)
from nexus_regime_selected_exposure_increase import (
    run_regime_selected_exposure_increase,
    verify_regime_selected_exposure_increase,
)
from nexus_regime_selected_position_rebalance import (
    run_regime_selected_rebalance,
    verify_regime_selected_rebalance,
)
from phase6_research_pipeline import fetch_bind_bybit_dataset


PUBLIC_DATA_MODE = "public_bybit_closed_candles"


class PublicRegimeCycleError(RuntimeError):
    pass


def _expected_cell_count(manifest: Mapping[str, Any]) -> int:
    symbols = manifest.get("symbols")
    timeframes = manifest.get("timeframes")
    if not isinstance(symbols, list) or not symbols or len(set(symbols)) != len(symbols):
        raise PublicRegimeCycleError("regime manifest symbol surface is invalid")
    if not isinstance(timeframes, list) or not timeframes or len(set(timeframes)) != len(timeframes):
        raise PublicRegimeCycleError("regime manifest timeframe surface is invalid")
    expected = len(symbols) * len(timeframes)
    if expected not in {6, 12}:
        raise PublicRegimeCycleError("regime manifest cell surface is not approved")
    return expected


def run_public_regime_cycle(
    *,
    manifest: Mapping[str, Any],
    matrix_state: Mapping[str, Any],
    state_root: str | Path,
    source_sha: str,
    selector_policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Execute one synchronized public-data regime selection at the 4h boundary."""
    root = Path(state_root).resolve()
    expected_cells = _expected_cell_count(manifest)
    snapshot = run_demo_regime_cycle(
        manifest=manifest,
        matrix_state=matrix_state,
        state_root=root,
        source_sha=source_sha,
        archive_fetcher=fetch_bind_bybit_dataset,
        selector_policy=selector_policy,
    )

    # The core function predates public runtime and records the historical archive
    # identity. Replace that provenance marker and rebind the digest before the
    # lifecycle bridges consume it. The datasets are independently validated
    # canonical Bybit public data.
    core = dict(snapshot)
    core.pop("cycle_digest", None)
    core["archive_sha256"] = None
    core["data_mode"] = PUBLIC_DATA_MODE
    public_snapshot = {**core, "cycle_digest": _digest(core)}
    verification = verify_cycle_snapshot(
        public_snapshot, expected_cell_count=expected_cells
    )
    if verification.get("decision") != "pass":
        raise PublicRegimeCycleError("public regime cycle failed independent verification")
    if (
        public_snapshot.get("paper_only") is not True
        or public_snapshot.get("live_trading_authority") is not False
        or public_snapshot.get("private_credentials_used") is not False
        or public_snapshot.get("automatic_strategy_promotion") is not False
        or public_snapshot.get("deterministic_risk_final_authority") is not True
    ):
        raise PublicRegimeCycleError("public regime cycle widened authority")

    rebalance = run_regime_selected_rebalance(
        manifest=manifest,
        state_root=root,
        source_sha=source_sha,
        regime_snapshot=public_snapshot,
    )
    if verify_regime_selected_rebalance(
        rebalance, expected_cell_count=expected_cells
    ).get("decision") != "pass":
        raise PublicRegimeCycleError("regime-selected rebalance failed independent verification")
    if (
        rebalance.get("paper_only") is not True
        or rebalance.get("live_trading_authority") is not False
        or rebalance.get("private_credentials_used") is not False
        or rebalance.get("automatic_strategy_promotion") is not False
        or rebalance.get("deterministic_risk_final_authority") is not True
        or rebalance.get("exposure_increased") is not False
    ):
        raise PublicRegimeCycleError("risk-reducing rebalance widened authority")

    increase = run_regime_selected_exposure_increase(
        manifest=manifest,
        state_root=root,
        source_sha=source_sha,
        regime_snapshot=public_snapshot,
        rebalance_snapshot=rebalance,
    )
    if verify_regime_selected_exposure_increase(
        increase, expected_cell_count=expected_cells
    ).get("decision") != "pass":
        raise PublicRegimeCycleError("regime-selected exposure increase failed verification")
    if (
        increase.get("paper_only") is not True
        or increase.get("live_trading_authority") is not False
        or increase.get("private_credentials_used") is not False
        or increase.get("automatic_strategy_promotion") is not False
        or increase.get("deterministic_risk_final_authority") is not True
        or increase.get("fresh_deterministic_risk_required") is not True
        or increase.get("unauthorized_exposure_increase") is not False
    ):
        raise PublicRegimeCycleError("exposure increase widened authority")

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
    if verify_cycle_snapshot(
        final_snapshot, expected_cell_count=expected_cells
    ).get("decision") != "pass":
        raise PublicRegimeCycleError("final public regime cycle failed independent verification")
    _atomic_json(root / "demo" / "regime-cycle.json", final_snapshot)
    return final_snapshot
