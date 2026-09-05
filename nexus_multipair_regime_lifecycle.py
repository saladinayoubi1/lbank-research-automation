"""Four-symbol adapter for the existing verified NEXUS regime lifecycle.

The legacy regime/rebalance/exposure implementations intentionally retain their
six-cell BTC/ETH verifier defaults.  This module composes the accepted v2 surface
as two disjoint six-cell partitions, runs the unchanged legacy execution
primitives on each partition, then recombines and independently verifies the
exact 12-cell BTC/ETH/SOL/XRP evidence surface.

No authority is widened: Research/Paper only, Live disabled, no private exchange
credentials, no real exchange orders, no automatic strategy promotion, and
Deterministic Risk remains final authority.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import nexus_demo_regime_cycle as regime
import nexus_regime_selected_exposure_increase as increase
import nexus_regime_selected_position_rebalance as rebalance
from nexus_multipair_demo_strategy_matrix import (
    APPROVED_SYMBOLS,
    AUTHORITY,
    FAMILIES,
    TIMEFRAMES,
)


SYMBOL_GROUPS = (
    ("BTCUSDT", "ETHUSDT"),
    ("SOLUSDT", "XRPUSDT"),
)
EXPECTED_CELLS = len(APPROVED_SYMBOLS) * len(TIMEFRAMES)
LEGACY_GROUP_CELLS = len(SYMBOL_GROUPS[0]) * len(TIMEFRAMES)


class MultiPairRegimeLifecycleError(RuntimeError):
    pass


def _validate_manifest(manifest: Mapping[str, Any]) -> None:
    if not isinstance(manifest, Mapping):
        raise MultiPairRegimeLifecycleError("multi-pair manifest is missing")
    if manifest.get("symbols") != list(APPROVED_SYMBOLS):
        raise MultiPairRegimeLifecycleError("multi-pair symbol surface mismatch")
    if manifest.get("timeframes") != list(TIMEFRAMES):
        raise MultiPairRegimeLifecycleError("multi-pair timeframe surface mismatch")
    if manifest.get("families") != list(FAMILIES):
        raise MultiPairRegimeLifecycleError("multi-pair family surface mismatch")
    if manifest.get("authority") != AUTHORITY:
        raise MultiPairRegimeLifecycleError("multi-pair authority boundary mismatch")


def _identity_set(cells: Any) -> set[tuple[str, str]]:
    if not isinstance(cells, list) or any(not isinstance(row, Mapping) for row in cells):
        return set()
    return {(str(row.get("symbol")), str(row.get("timeframe"))) for row in cells}


def _expected_identities(symbols: Sequence[str]) -> set[tuple[str, str]]:
    return {(symbol, timeframe) for symbol in symbols for timeframe in TIMEFRAMES}


def _group_manifest(manifest: Mapping[str, Any], symbols: Sequence[str]) -> dict[str, Any]:
    value = dict(manifest)
    value["symbols"] = list(symbols)
    return value


def _regime_group(value: Mapping[str, Any], symbols: Sequence[str]) -> dict[str, Any]:
    core = dict(value)
    core.pop("cycle_digest", None)
    cells = [
        dict(row)
        for row in core.get("cells", [])
        if isinstance(row, Mapping) and row.get("symbol") in symbols
    ]
    if _identity_set(cells) != _expected_identities(symbols):
        raise MultiPairRegimeLifecycleError("regime subgroup surface mismatch")
    contexts = core.get("context_digests")
    if not isinstance(contexts, Mapping):
        raise MultiPairRegimeLifecycleError("regime context surface is missing")
    core["cells"] = sorted(cells, key=lambda row: (row["symbol"], row["timeframe"]))
    core["context_digests"] = {symbol: contexts[symbol] for symbol in symbols}
    core["expected_cell_count"] = LEGACY_GROUP_CELLS
    core["verified_cell_count"] = LEGACY_GROUP_CELLS
    return {**core, "cycle_digest": regime._digest(core)}


def verify_v2_regime_snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {
        "digest": False,
        "shape": False,
        "identity": False,
        "contexts": False,
        "legacy_partitions": False,
    }
    try:
        core = dict(value)
        claimed = core.pop("cycle_digest", None)
        cells = core.get("cells")
        checks["digest"] = isinstance(claimed, str) and claimed == regime._digest(core)
        checks["shape"] = bool(
            core.get("expected_cell_count") == EXPECTED_CELLS
            and core.get("verified_cell_count") == EXPECTED_CELLS
            and isinstance(cells, list)
            and len(cells) == EXPECTED_CELLS
        )
        checks["identity"] = _identity_set(cells) == _expected_identities(APPROVED_SYMBOLS)
        contexts = core.get("context_digests")
        checks["contexts"] = bool(
            isinstance(contexts, Mapping) and set(contexts) == set(APPROVED_SYMBOLS)
        )
        checks["legacy_partitions"] = all(
            regime.verify_cycle_snapshot(_regime_group(value, symbols)).get("decision") == "pass"
            for symbols in SYMBOL_GROUPS
        )
    except (KeyError, TypeError, ValueError, MultiPairRegimeLifecycleError):
        pass
    return {"decision": "pass" if all(checks.values()) else "reject", "checks": checks}


def _rebalance_counts(cells: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    actions = [
        action
        for cell in cells
        for action in cell.get("actions", [])
        if isinstance(action, Mapping)
    ]
    return {
        "held_count": sum(action.get("action") == "HELD" for action in actions),
        "reduced_count": sum(action.get("action") == "REDUCED" for action in actions),
        "closed_count": sum(action.get("action") == "CLOSED" for action in actions),
        "increase_pending_count": sum(
            action.get("action") == "HOLD_INCREASE_PENDING_FRESH_RISK" for action in actions
        ),
    }


def _rebalance_group(
    value: Mapping[str, Any],
    symbols: Sequence[str],
    *,
    regime_cycle_digest: str | None = None,
) -> dict[str, Any]:
    core = dict(value)
    core.pop("rebalance_digest", None)
    cells = [
        dict(row)
        for row in core.get("cells", [])
        if isinstance(row, Mapping) and row.get("symbol") in symbols
    ]
    if _identity_set(cells) != _expected_identities(symbols):
        raise MultiPairRegimeLifecycleError("rebalance subgroup surface mismatch")
    core["cells"] = sorted(cells, key=lambda row: (row["symbol"], row["timeframe"]))
    core["cell_count"] = LEGACY_GROUP_CELLS
    core.update(_rebalance_counts(core["cells"]))
    if regime_cycle_digest is not None:
        core["regime_cycle_digest"] = regime_cycle_digest
    return {**core, "rebalance_digest": rebalance._digest(core)}


def _combine_rebalances(
    results: Sequence[Mapping[str, Any]], *, parent_cycle_digest: str
) -> dict[str, Any]:
    cells = sorted(
        [dict(cell) for result in results for cell in result.get("cells", [])],
        key=lambda row: (row["symbol"], row["timeframe"]),
    )
    if _identity_set(cells) != _expected_identities(APPROVED_SYMBOLS):
        raise MultiPairRegimeLifecycleError("combined rebalance surface mismatch")
    first = results[0]
    core = {
        "schema_version": rebalance.SCHEMA,
        "source_sha": first["source_sha"],
        "regime_cycle_digest": parent_cycle_digest,
        "cell_count": EXPECTED_CELLS,
        "cells": cells,
        **_rebalance_counts(cells),
        "risk_reducing_rebalance_operational": True,
        "exposure_increase_operational": False,
        "regime_selected_rebalance_operational": False,
        "remaining_core_gap": "REGIME_SELECTED_EXPOSURE_INCREASE_WITH_FRESH_RISK",
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
        "exposure_increased": False,
    }
    return {**core, "rebalance_digest": rebalance._digest(core)}


def verify_v2_rebalance(value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {
        "digest": False,
        "shape": False,
        "identity": False,
        "legacy_partitions": False,
    }
    try:
        core = dict(value)
        claimed = core.pop("rebalance_digest", None)
        cells = core.get("cells")
        checks["digest"] = isinstance(claimed, str) and claimed == rebalance._digest(core)
        checks["shape"] = bool(
            core.get("cell_count") == EXPECTED_CELLS
            and isinstance(cells, list)
            and len(cells) == EXPECTED_CELLS
        )
        checks["identity"] = _identity_set(cells) == _expected_identities(APPROVED_SYMBOLS)
        checks["legacy_partitions"] = all(
            rebalance.verify_regime_selected_rebalance(
                _rebalance_group(value, symbols)
            ).get("decision") == "pass"
            for symbols in SYMBOL_GROUPS
        )
    except (KeyError, TypeError, ValueError, MultiPairRegimeLifecycleError):
        pass
    return {"decision": "pass" if all(checks.values()) else "reject", "checks": checks}


def run_v2_rebalance(
    *,
    manifest: Mapping[str, Any],
    state_root: str | Path,
    source_sha: str,
    regime_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    _validate_manifest(manifest)
    if verify_v2_regime_snapshot(regime_snapshot).get("decision") != "pass":
        raise MultiPairRegimeLifecycleError("v2 regime snapshot failed verification")
    results: list[dict[str, Any]] = []
    for symbols in SYMBOL_GROUPS:
        group_regime = _regime_group(regime_snapshot, symbols)
        if regime.verify_cycle_snapshot(group_regime).get("decision") != "pass":
            raise MultiPairRegimeLifecycleError("legacy regime partition failed verification")
        result = rebalance.run_regime_selected_rebalance(
            manifest=_group_manifest(manifest, symbols),
            state_root=state_root,
            source_sha=source_sha,
            regime_snapshot=group_regime,
        )
        if rebalance.verify_regime_selected_rebalance(result).get("decision") != "pass":
            raise MultiPairRegimeLifecycleError("legacy rebalance partition failed verification")
        results.append(result)
    combined = _combine_rebalances(
        results, parent_cycle_digest=str(regime_snapshot["cycle_digest"])
    )
    if verify_v2_rebalance(combined).get("decision") != "pass":
        raise MultiPairRegimeLifecycleError("combined v2 rebalance failed verification")
    rebalance._atomic_json(
        Path(state_root).resolve() / "demo" / "regime-selected-rebalance.json", combined
    )
    return combined


def _increase_counts(cells: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    actions = [
        action
        for cell in cells
        for action in cell.get("actions", [])
        if isinstance(action, Mapping)
    ]
    return {
        "pending_count": sum(int(cell.get("pending_count", 0)) for cell in cells),
        "increased_count": sum(
            action.get("status") == "INCREASED_WITH_FRESH_RISK" for action in actions
        ),
        "risk_blocked_count": sum(
            action.get("status") == "INCREASE_BLOCKED_BY_DETERMINISTIC_RISK"
            for action in actions
        ),
        "no_increase_count": sum(
            action.get("status") == "NO_INCREASE_AFTER_POST_CLOSE_SIZING"
            for action in actions
        ),
    }


def _increase_group(
    value: Mapping[str, Any],
    symbols: Sequence[str],
    *,
    regime_cycle_digest: str | None = None,
    rebalance_digest: str | None = None,
) -> dict[str, Any]:
    core = dict(value)
    core.pop("increase_digest", None)
    cells = [
        dict(row)
        for row in core.get("cells", [])
        if isinstance(row, Mapping) and row.get("symbol") in symbols
    ]
    if _identity_set(cells) != _expected_identities(symbols):
        raise MultiPairRegimeLifecycleError("increase subgroup surface mismatch")
    core["cells"] = sorted(cells, key=lambda row: (row["symbol"], row["timeframe"]))
    core["cell_count"] = LEGACY_GROUP_CELLS
    core.update(_increase_counts(core["cells"]))
    if regime_cycle_digest is not None:
        core["regime_cycle_digest"] = regime_cycle_digest
    if rebalance_digest is not None:
        core["rebalance_digest"] = rebalance_digest
    return {**core, "increase_digest": increase._digest(core)}


def _combine_increases(
    results: Sequence[Mapping[str, Any]],
    *,
    parent_cycle_digest: str,
    parent_rebalance_digest: str,
) -> dict[str, Any]:
    cells = sorted(
        [dict(cell) for result in results for cell in result.get("cells", [])],
        key=lambda row: (row["symbol"], row["timeframe"]),
    )
    if _identity_set(cells) != _expected_identities(APPROVED_SYMBOLS):
        raise MultiPairRegimeLifecycleError("combined increase surface mismatch")
    first = results[0]
    core = {
        "schema_version": increase.SCHEMA,
        "source_sha": first["source_sha"],
        "regime_cycle_digest": parent_cycle_digest,
        "rebalance_digest": parent_rebalance_digest,
        "cell_count": EXPECTED_CELLS,
        "cells": cells,
        **_increase_counts(cells),
        "exposure_increase_operational": True,
        "fresh_deterministic_risk_required": True,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
        "unauthorized_exposure_increase": False,
    }
    return {**core, "increase_digest": increase._digest(core)}


def verify_v2_exposure_increase(value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {
        "digest": False,
        "shape": False,
        "identity": False,
        "legacy_partitions": False,
    }
    try:
        core = dict(value)
        claimed = core.pop("increase_digest", None)
        cells = core.get("cells")
        checks["digest"] = isinstance(claimed, str) and claimed == increase._digest(core)
        checks["shape"] = bool(
            core.get("cell_count") == EXPECTED_CELLS
            and isinstance(cells, list)
            and len(cells) == EXPECTED_CELLS
        )
        checks["identity"] = _identity_set(cells) == _expected_identities(APPROVED_SYMBOLS)
        checks["legacy_partitions"] = all(
            increase.verify_regime_selected_exposure_increase(
                _increase_group(value, symbols)
            ).get("decision") == "pass"
            for symbols in SYMBOL_GROUPS
        )
    except (KeyError, TypeError, ValueError, MultiPairRegimeLifecycleError):
        pass
    return {"decision": "pass" if all(checks.values()) else "reject", "checks": checks}


def run_v2_exposure_increase(
    *,
    manifest: Mapping[str, Any],
    state_root: str | Path,
    source_sha: str,
    regime_snapshot: Mapping[str, Any],
    rebalance_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    _validate_manifest(manifest)
    if verify_v2_regime_snapshot(regime_snapshot).get("decision") != "pass":
        raise MultiPairRegimeLifecycleError("v2 regime snapshot failed verification before increase")
    if verify_v2_rebalance(rebalance_snapshot).get("decision") != "pass":
        raise MultiPairRegimeLifecycleError("v2 rebalance failed verification before increase")

    results: list[dict[str, Any]] = []
    for symbols in SYMBOL_GROUPS:
        group_regime = _regime_group(regime_snapshot, symbols)
        group_rebalance = _rebalance_group(
            rebalance_snapshot,
            symbols,
            regime_cycle_digest=str(group_regime["cycle_digest"]),
        )
        result = increase.run_regime_selected_exposure_increase(
            manifest=_group_manifest(manifest, symbols),
            state_root=state_root,
            source_sha=source_sha,
            regime_snapshot=group_regime,
            rebalance_snapshot=group_rebalance,
        )
        if increase.verify_regime_selected_exposure_increase(result).get("decision") != "pass":
            raise MultiPairRegimeLifecycleError("legacy increase partition failed verification")
        results.append(result)

    combined = _combine_increases(
        results,
        parent_cycle_digest=str(regime_snapshot["cycle_digest"]),
        parent_rebalance_digest=str(rebalance_snapshot["rebalance_digest"]),
    )
    if verify_v2_exposure_increase(combined).get("decision") != "pass":
        raise MultiPairRegimeLifecycleError("combined v2 increase failed verification")
    increase._atomic_json(
        Path(state_root).resolve() / "demo" / "regime-selected-exposure-increase.json",
        combined,
    )
    return combined
