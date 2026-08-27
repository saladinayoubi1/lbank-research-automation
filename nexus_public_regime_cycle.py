"""Run the verified NEXUS regime cycle on canonical public Bybit closed candles.

The underlying selector, independent verifier, Deterministic Risk and isolated
Paper execution are unchanged.  This adapter replaces immutable archive replay
input with the existing bounded public Bybit fetch/bind contract and then applies
the separately verified risk-reducing lifecycle bridge for already-open
regime-selected Paper positions.
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
from nexus_regime_selected_position_rebalance import (
    run_regime_selected_rebalance,
    verify_regime_selected_rebalance,
)
from phase6_research_pipeline import fetch_bind_bybit_dataset


PUBLIC_DATA_MODE = "public_bybit_closed_candles"


class PublicRegimeCycleError(RuntimeError):
    pass


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
    # lifecycle bridge consumes it. The actual datasets are already independently
    # validated canonical Bybit public data.
    core = dict(snapshot)
    core.pop("cycle_digest", None)
    core["archive_sha256"] = None
    core["data_mode"] = PUBLIC_DATA_MODE
    public_snapshot = {**core, "cycle_digest": _digest(core)}
    verification = verify_cycle_snapshot(public_snapshot)
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
    if verify_regime_selected_rebalance(rebalance).get("decision") != "pass":
        raise PublicRegimeCycleError("regime-selected rebalance failed independent verification")
    if (
        rebalance.get("paper_only") is not True
        or rebalance.get("live_trading_authority") is not False
        or rebalance.get("private_credentials_used") is not False
        or rebalance.get("automatic_strategy_promotion") is not False
        or rebalance.get("deterministic_risk_final_authority") is not True
        or rebalance.get("exposure_increased") is not False
    ):
        raise PublicRegimeCycleError("regime-selected rebalance widened authority")

    # Preserve the original independently replayable regime/runtime evidence and
    # bind the lifecycle result into the public-cycle digest as an additional
    # control projection.  Exposure increase is intentionally still fail-closed.
    final_core = dict(public_snapshot)
    final_core.pop("cycle_digest", None)
    final_core["regime_selected_rebalance_digest"] = rebalance["rebalance_digest"]
    final_core["risk_reducing_rebalance_operational"] = rebalance[
        "risk_reducing_rebalance_operational"
    ]
    final_core["regime_selected_exposure_increase_operational"] = rebalance[
        "exposure_increase_operational"
    ]
    final_core["regime_selected_rebalance_operational"] = rebalance[
        "regime_selected_rebalance_operational"
    ]
    final_core["regime_selected_rebalance_remaining_gap"] = rebalance[
        "remaining_core_gap"
    ]
    final_snapshot = {**final_core, "cycle_digest": _digest(final_core)}
    if verify_cycle_snapshot(final_snapshot).get("decision") != "pass":
        raise PublicRegimeCycleError("final public regime cycle failed independent verification")
    _atomic_json(root / "demo" / "regime-cycle.json", final_snapshot)
    return final_snapshot
