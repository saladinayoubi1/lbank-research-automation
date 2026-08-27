"""Atomic fresh-Risk exposure increase for regime-selected isolated Paper positions.

Paper execution intentionally has no implicit same-side ``add`` operation.  When a
verified corrected regime allocation requires more exposure than an already-open
position, this bridge simulates a full risk-reducing close, prepares a new canonical
open proposal against that hypothetical closed state, re-runs Deterministic Risk,
and commits close + reopen as one atomic journal replacement only when the fresh open
is allowed.  A Risk rejection leaves the original position untouched.

This is Paper-only.  It cannot route exchange orders, use private credentials,
promote a strategy, or grant Live/L4 authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from automated_signal_pipeline import run_automated_signal_pipeline
from nexus_demo_regime_cycle import _runtime_for
from nexus_regime_paper_lane import prepare_regime_paper_lane
from nexus_regime_selected_position_rebalance import (
    _position,
    verify_regime_selected_rebalance,
)
from paper_event_store import build_event, replay
from paper_execution import execute_paper_command
from phase6_research_pipeline import fetch_bind_bybit_dataset
from product_research_runtime import ProductResearchRuntime, TIMEFRAMES, _utc_ms
from product_runtime import (
    PAPER_CURRENCY,
    PAPER_DEFAULT_FEE_RATE,
    PAPER_DEFAULT_SLIPPAGE_BPS,
    _risk_reducing_exit,
    _session_signal_count,
)


SCHEMA = "nexus.regime-selected-exposure-increase.v1"
CELL_SCHEMA = "nexus.regime-selected-exposure-increase-cell.v1"
ACTION_SCHEMA = "nexus.regime-selected-exposure-increase-action.v1"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RegimeSelectedExposureIncreaseError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RegimeSelectedExposureIncreaseError("increase evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + f".{os.getpid()}.tmp")
    payload = json.dumps(
        dict(value), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
    ) + "\n"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise RegimeSelectedExposureIncreaseError("increase evidence persistence failed") from exc


def _decimal(value: Any, field: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, float):
        raise RegimeSelectedExposureIncreaseError(f"{field} must not use binary floating point")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise RegimeSelectedExposureIncreaseError(f"{field} is not a decimal") from exc
    if not result.is_finite() or (positive and result <= 0):
        raise RegimeSelectedExposureIncreaseError(f"{field} is outside the bounded range")
    return result


def _allocation_weight(cell: Mapping[str, Any], family: str) -> Decimal:
    allocations = cell.get("corrected_allocations")
    if not isinstance(allocations, list):
        raise RegimeSelectedExposureIncreaseError("corrected allocations are invalid")
    for row in allocations:
        if isinstance(row, Mapping) and row.get("family") == family:
            return _decimal(row.get("weight"), "allocation.weight", positive=True)
    raise RegimeSelectedExposureIncreaseError("pending increase family is not selected")


def _fresh_research_runtime(
    *,
    state_root: Path,
    source_sha: str,
    symbol: str,
    timeframe: str,
    family: str,
    as_of_ms: int,
    history_limit: int,
    expected_dataset_binding: str,
) -> tuple[Any, ProductResearchRuntime, dict[str, Any]]:
    runtime = _runtime_for(
        state_root=state_root,
        symbol=symbol,
        timeframe=timeframe,
        family=family,
        as_of_ms=as_of_ms,
    )
    research = ProductResearchRuntime(
        runtime,
        source_sha=source_sha,
        dataset_fetcher=fetch_bind_bybit_dataset,
        clock_ms=lambda as_of_ms=as_of_ms: as_of_ms,
    )
    result = research.run_research(
        symbol=symbol, timeframe=timeframe, family=family, limit=history_limit
    )
    dataset = result.get("dataset")
    qualification = result.get("qualification")
    request = result.get("request")
    if not all(isinstance(item, Mapping) for item in (dataset, qualification, request)):
        raise RegimeSelectedExposureIncreaseError("fresh increase research lineage is incomplete")
    if (
        result.get("source_sha") != source_sha
        or request.get("symbol") != symbol
        or request.get("timeframe") != timeframe
        or request.get("family") != family
        or dataset.get("binding_sha256") != expected_dataset_binding
        or qualification.get("dataset_binding_sha256") != expected_dataset_binding
    ):
        raise RegimeSelectedExposureIncreaseError("fresh increase source/dataset substitution detected")
    step_ms = int(TIMEFRAMES[timeframe]["step_ms"])
    last_open_ms = dataset.get("last_open_time_ms")
    if isinstance(last_open_ms, bool) or not isinstance(last_open_ms, int) or last_open_ms < 0:
        raise RegimeSelectedExposureIncreaseError("fresh increase close boundary is invalid")
    age_ms = as_of_ms - (last_open_ms + step_ms)
    if age_ms < 0 or age_ms > step_ms * 2:
        raise RegimeSelectedExposureIncreaseError("fresh increase data is stale or future-dated")
    _decimal(dataset.get("last_close"), "dataset.last_close", positive=True)
    return runtime, research, dict(result)


def _pipeline_equal(first: Any, second: Any) -> bool:
    return bool(
        first.signal == second.signal
        and first.risk_decision == second.risk_decision
        and first.events == second.events
        and first.state == second.state
        and first.execution == second.execution
    )


def _atomic_fresh_risk_increase(
    *,
    runtime: Any,
    research_runtime: ProductResearchRuntime,
    source_sha: str,
    symbol: str,
    timeframe: str,
    family: str,
    as_of_ms: int,
    cell_digest: str,
    rebalance_cell_digest: str,
    corrected_selection_digest: str,
    allocation_weight: Decimal,
    expected_pre_quantity: Decimal,
    expected_head_digest: str,
) -> dict[str, Any]:
    with runtime._lock:
        events = runtime._ensure_account()
        state = replay(events).state
        current = _position(state, symbol)
        if current is None:
            raise RegimeSelectedExposureIncreaseError("pending increase position disappeared")
        side, current_quantity, _entry = current
        if current_quantity != expected_pre_quantity or state.last_event_digest != expected_head_digest:
            raise RegimeSelectedExposureIncreaseError("pending increase journal changed after rebalance planning")

        occurred_at = _utc_ms(as_of_ms)
        reference_price = str(research_runtime._last_research["dataset"]["last_close"])
        close_binding = _digest({
            "source_sha": source_sha,
            "regime_cell_digest": cell_digest,
            "rebalance_cell_digest": rebalance_cell_digest,
            "corrected_selection_digest": corrected_selection_digest,
            "head_event_digest": state.last_event_digest,
            "symbol": symbol,
            "timeframe": timeframe,
            "family": family,
            "quantity": format(current_quantity, "f"),
            "reference_price": reference_price,
            "as_of_ms": as_of_ms,
        })
        close_signal_id = f"regime-increase-close-{close_binding[:40]}"
        close_correlation_id = f"regime-increase-close-{close_binding[:32]}"
        close_risk = _risk_reducing_exit(
            state=state,
            signal_id=close_signal_id,
            symbol=symbol,
            side=side,
            quantity=format(current_quantity, "f"),
            reference_price=reference_price,
        )
        if not close_risk.allowed:
            raise RegimeSelectedExposureIncreaseError(
                "deterministic risk-reducing gate rejected atomic replacement close"
            )
        strategy_version = str(
            research_runtime._last_research.get("qualification", {}).get(
                "strategy_version", "unknown"
            )
        )
        provenance = {
            "kind": "automatic",
            "source_id": "nexus-regime-selected-increase",
            "source_timestamp": occurred_at,
            "received_timestamp": occurred_at,
            "timeframe": timeframe,
            "confidence": "1",
            "strategy_version": strategy_version,
            "policy_version": "nexus-product-paper-risk-v1",
        }
        close_signal = build_event(
            event_id=f"{close_signal_id}:signal",
            event_type="signal_recorded",
            aggregate_id=state.aggregate_id or "paper-account",
            sequence=state.last_sequence + 1,
            occurred_at=occurred_at,
            correlation_id=close_correlation_id,
            causation_id=f"regime-increase:{close_binding[:40]}",
            provenance=provenance,
            previous_event_digest=state.last_event_digest,
            payload={
                "symbol": symbol,
                "timeframe": timeframe,
                "side": side,
                "quantity": format(current_quantity, "f"),
                "reference_price": reference_price,
            },
        )
        close_signal_state = replay([close_signal], previous_valid=state).state
        close_result = execute_paper_command(
            command={
                "operation": "close",
                "symbol": symbol,
                "side": side,
                "quantity": format(current_quantity, "f"),
                "reference_price": reference_price,
                "stop_price": reference_price,
                "target_price": reference_price,
                "fee_rate": PAPER_DEFAULT_FEE_RATE,
                "slippage_bps": PAPER_DEFAULT_SLIPPAGE_BPS,
                "currency": PAPER_CURRENCY,
            },
            state=close_signal_state,
            risk_decision=close_risk,
            occurred_at=occurred_at,
            provenance=provenance,
            correlation_id=close_correlation_id,
            causation_id=close_signal_id,
        )
        if _position(close_result.state, symbol) is not None:
            raise RegimeSelectedExposureIncreaseError("hypothetical replacement close left exposure")

        preparation = prepare_regime_paper_lane(
            research_runtime,
            portfolio_state_override=close_result.state,
            signals_today_override=_session_signal_count(events) + 1,
        )
        lane = preparation.get("lane")
        if preparation.get("status") != "ready" or not isinstance(lane, Mapping):
            raise RegimeSelectedExposureIncreaseError("post-close fresh open proposal is not ready")
        if lane.get("portfolio_state") != close_result.state:
            raise RegimeSelectedExposureIncreaseError("fresh open proposal is not bound to hypothetical close")

        decision = dict(lane["decision"])
        base_quantity = _decimal(decision.get("quantity"), "decision.quantity", positive=True)
        desired_quantity = base_quantity * allocation_weight
        if desired_quantity <= current_quantity:
            core = {
                "schema_version": ACTION_SCHEMA,
                "family": family,
                "status": "NO_INCREASE_AFTER_POST_CLOSE_SIZING",
                "reason_code": "POST_CLOSE_TARGET_NOT_ABOVE_CURRENT",
                "initial_quantity": format(current_quantity, "f"),
                "desired_quantity": format(desired_quantity, "f"),
                "final_quantity": format(current_quantity, "f"),
                "initial_head_event_digest": state.last_event_digest,
                "terminal_event_digest": state.last_event_digest,
                "close_risk_reason": close_risk.reason_code,
                "open_risk_allowed": False,
                "open_risk_reason": None,
                "open_signal_id": None,
                "risk_replay_verified": False,
                "journal_committed": False,
                "paper_only": True,
                "live_trading_authority": False,
                "fresh_deterministic_risk_required": True,
                "unauthorized_exposure_increase": False,
            }
            return {**core, "action_digest": _digest(core)}

        decision_binding = _digest({
            "source_sha": source_sha,
            "corrected_selection_digest": corrected_selection_digest,
            "rebalance_cell_digest": rebalance_cell_digest,
            "closed_head_event_digest": close_result.state.last_event_digest,
            "family": family,
            "weight": format(allocation_weight, "f"),
            "quantity": format(desired_quantity, "f"),
            "original_decision_id": decision.get("decision_id"),
        })
        decision["quantity"] = format(desired_quantity, "f")
        decision["decision_id"] = f"decision-{decision_binding[:40]}"
        decision["correlation_id"] = f"regime-increase-{decision_binding[:32]}"
        pipeline_kwargs = {
            "dataset": lane["dataset"],
            "qualification": lane["qualification"],
            "regime": lane["regime"],
            "decision": decision,
            "risk_state": lane["risk_state"],
            "risk_policy": lane["risk_policy"],
            "portfolio_state": close_result.state,
            "occurred_at": occurred_at,
            "fee_rate": lane["fee_rate"],
            "slippage_bps": lane["slippage_bps"],
        }
        opened = run_automated_signal_pipeline(**pipeline_kwargs)
        replayed = run_automated_signal_pipeline(**pipeline_kwargs)
        replay_verified = _pipeline_equal(opened, replayed)
        if not replay_verified:
            raise RegimeSelectedExposureIncreaseError("fresh Risk/Paper open is not deterministic")

        if not opened.risk_decision.allowed or opened.execution is None:
            core = {
                "schema_version": ACTION_SCHEMA,
                "family": family,
                "status": "INCREASE_BLOCKED_BY_DETERMINISTIC_RISK",
                "reason_code": "FRESH_RISK_REJECTED_REPLACEMENT_OPEN",
                "initial_quantity": format(current_quantity, "f"),
                "desired_quantity": format(desired_quantity, "f"),
                "final_quantity": format(current_quantity, "f"),
                "initial_head_event_digest": state.last_event_digest,
                "terminal_event_digest": state.last_event_digest,
                "close_risk_reason": close_risk.reason_code,
                "open_risk_allowed": False,
                "open_risk_reason": opened.risk_decision.reason_code,
                "open_signal_id": opened.signal["signal_id"],
                "risk_replay_verified": True,
                "journal_committed": False,
                "paper_only": True,
                "live_trading_authority": False,
                "fresh_deterministic_risk_required": True,
                "unauthorized_exposure_increase": False,
            }
            return {**core, "action_digest": _digest(core)}

        final = _position(opened.state, symbol)
        if final is None or final[1] != desired_quantity or final[1] <= current_quantity:
            raise RegimeSelectedExposureIncreaseError("fresh Risk-approved open missed increase target")
        combined = [
            *events,
            close_signal,
            *close_result.events,
            *opened.events,
        ]
        reconstructed = replay(combined).state
        if reconstructed != opened.state:
            raise RegimeSelectedExposureIncreaseError("atomic replacement journal replay mismatch")
        runtime._write_events(combined)

    core = {
        "schema_version": ACTION_SCHEMA,
        "family": family,
        "status": "INCREASED_WITH_FRESH_RISK",
        "reason_code": "ATOMIC_CLOSE_REOPEN_RISK_ALLOWED",
        "initial_quantity": format(current_quantity, "f"),
        "desired_quantity": format(desired_quantity, "f"),
        "final_quantity": format(final[1], "f"),
        "initial_head_event_digest": state.last_event_digest,
        "terminal_event_digest": opened.state.last_event_digest,
        "close_risk_reason": close_risk.reason_code,
        "open_risk_allowed": True,
        "open_risk_reason": opened.risk_decision.reason_code,
        "open_signal_id": opened.signal["signal_id"],
        "risk_replay_verified": True,
        "journal_committed": True,
        "paper_only": True,
        "live_trading_authority": False,
        "fresh_deterministic_risk_required": True,
        "unauthorized_exposure_increase": False,
    }
    return {**core, "action_digest": _digest(core)}


def run_regime_selected_exposure_increase(
    *,
    manifest: Mapping[str, Any],
    state_root: str | Path,
    source_sha: str,
    regime_snapshot: Mapping[str, Any],
    rebalance_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    source_sha = str(source_sha).strip().lower()
    if not _SHA_RE.fullmatch(source_sha):
        raise RegimeSelectedExposureIncreaseError("source_sha must be an exact Git SHA")
    verification = verify_regime_selected_rebalance(rebalance_snapshot)
    if verification.get("decision") != "pass":
        raise RegimeSelectedExposureIncreaseError("risk-reducing rebalance is not verified")
    if (
        rebalance_snapshot.get("source_sha") != source_sha
        or rebalance_snapshot.get("regime_cycle_digest") != regime_snapshot.get("cycle_digest")
        or regime_snapshot.get("source_sha") != source_sha
    ):
        raise RegimeSelectedExposureIncreaseError("increase inputs are not bound to one source/cycle")

    root = Path(state_root).resolve()
    regime_cells = {
        (row.get("symbol"), row.get("timeframe")): row
        for row in regime_snapshot.get("cells", []) if isinstance(row, Mapping)
    }
    rebalance_cells = {
        (row.get("symbol"), row.get("timeframe")): row
        for row in rebalance_snapshot.get("cells", []) if isinstance(row, Mapping)
    }
    expected = {
        (symbol, timeframe)
        for symbol in manifest["symbols"] for timeframe in manifest["timeframes"]
    }
    if set(regime_cells) != expected or set(rebalance_cells) != expected:
        raise RegimeSelectedExposureIncreaseError("increase cells do not match the manifest")

    cells: list[dict[str, Any]] = []
    for symbol in manifest["symbols"]:
        for timeframe in manifest["timeframes"]:
            regime_cell = regime_cells[(symbol, timeframe)]
            rebalance_cell = rebalance_cells[(symbol, timeframe)]
            as_of_ms = regime_cell.get("as_of_ms")
            binding = regime_cell.get("context_dataset_binding_sha256")
            cell_digest = regime_cell.get("cell_digest")
            rebalance_cell_digest = rebalance_cell.get("cell_rebalance_digest")
            corrected_selection_digest = rebalance_cell.get("corrected_selection_digest")
            if (
                isinstance(as_of_ms, bool) or not isinstance(as_of_ms, int) or as_of_ms <= 0
                or not isinstance(binding, str) or not _SHA256_RE.fullmatch(binding)
                or not isinstance(cell_digest, str) or not _SHA256_RE.fullmatch(cell_digest)
                or not isinstance(rebalance_cell_digest, str)
                or not _SHA256_RE.fullmatch(rebalance_cell_digest)
                or not isinstance(corrected_selection_digest, str)
                or not _SHA256_RE.fullmatch(corrected_selection_digest)
            ):
                raise RegimeSelectedExposureIncreaseError("increase cell binding evidence is invalid")
            pending = [
                action for action in rebalance_cell.get("actions", [])
                if isinstance(action, Mapping)
                and action.get("action") == "HOLD_INCREASE_PENDING_FRESH_RISK"
            ]
            actions: list[dict[str, Any]] = []
            for planned in pending:
                family = str(planned.get("family", ""))
                if family not in manifest["families"]:
                    raise RegimeSelectedExposureIncreaseError("pending increase family is not approved")
                weight = _allocation_weight(rebalance_cell, family)
                runtime, research, research_result = _fresh_research_runtime(
                    state_root=root,
                    source_sha=source_sha,
                    symbol=symbol,
                    timeframe=timeframe,
                    family=family,
                    as_of_ms=as_of_ms,
                    history_limit=int(manifest["history_limit"]),
                    expected_dataset_binding=binding,
                )
                if research_result.get("qualification", {}).get("status") != "paper_candidate":
                    raise RegimeSelectedExposureIncreaseError(
                        "pending increase lost independent Paper qualification"
                    )
                action = _atomic_fresh_risk_increase(
                    runtime=runtime,
                    research_runtime=research,
                    source_sha=source_sha,
                    symbol=symbol,
                    timeframe=timeframe,
                    family=family,
                    as_of_ms=as_of_ms,
                    cell_digest=cell_digest,
                    rebalance_cell_digest=rebalance_cell_digest,
                    corrected_selection_digest=corrected_selection_digest,
                    allocation_weight=weight,
                    expected_pre_quantity=_decimal(
                        planned.get("pre_quantity"), "planned.pre_quantity", positive=True
                    ),
                    expected_head_digest=str(planned.get("terminal_event_digest", "")),
                )
                actions.append(action)

            cell_core = {
                "schema_version": CELL_SCHEMA,
                "symbol": symbol,
                "timeframe": timeframe,
                "source_sha": source_sha,
                "regime_cell_digest": cell_digest,
                "rebalance_cell_digest": rebalance_cell_digest,
                "corrected_selection_digest": corrected_selection_digest,
                "pending_count": len(pending),
                "action_count": len(actions),
                "actions": actions,
                "paper_only": True,
                "live_trading_authority": False,
                "private_credentials_used": False,
                "automatic_strategy_promotion": False,
                "deterministic_risk_final_authority": True,
                "unauthorized_exposure_increase": False,
            }
            cells.append({**cell_core, "cell_increase_digest": _digest(cell_core)})

    all_actions = [action for cell in cells for action in cell["actions"]]
    core = {
        "schema_version": SCHEMA,
        "source_sha": source_sha,
        "regime_cycle_digest": regime_snapshot.get("cycle_digest"),
        "rebalance_digest": rebalance_snapshot.get("rebalance_digest"),
        "cell_count": len(cells),
        "cells": cells,
        "pending_count": sum(cell["pending_count"] for cell in cells),
        "increased_count": sum(
            action["status"] == "INCREASED_WITH_FRESH_RISK" for action in all_actions
        ),
        "risk_blocked_count": sum(
            action["status"] == "INCREASE_BLOCKED_BY_DETERMINISTIC_RISK"
            for action in all_actions
        ),
        "no_increase_count": sum(
            action["status"] == "NO_INCREASE_AFTER_POST_CLOSE_SIZING"
            for action in all_actions
        ),
        "exposure_increase_operational": True,
        "fresh_deterministic_risk_required": True,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
        "unauthorized_exposure_increase": False,
    }
    result = {**core, "increase_digest": _digest(core)}
    if verify_regime_selected_exposure_increase(result).get("decision") != "pass":
        raise RegimeSelectedExposureIncreaseError("increase snapshot failed verification")
    _atomic_json(root / "demo" / "regime-selected-exposure-increase.json", result)
    return result


def verify_regime_selected_exposure_increase(value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {
        "schema": False,
        "digest": False,
        "shape": False,
        "authority": False,
        "cell_digests": False,
        "action_digests": False,
        "fresh_risk": False,
        "counts": False,
    }
    try:
        core = dict(value)
        claimed = core.pop("increase_digest", None)
        cells = core.get("cells")
        checks["schema"] = core.get("schema_version") == SCHEMA
        checks["digest"] = isinstance(claimed, str) and claimed == _digest(core)
        checks["shape"] = bool(
            core.get("cell_count") == 6
            and isinstance(cells, list)
            and len(cells) == 6
            and len({(cell.get("symbol"), cell.get("timeframe")) for cell in cells}) == 6
        )
        checks["authority"] = bool(
            core.get("paper_only") is True
            and core.get("live_trading_authority") is False
            and core.get("private_credentials_used") is False
            and core.get("automatic_strategy_promotion") is False
            and core.get("deterministic_risk_final_authority") is True
            and core.get("fresh_deterministic_risk_required") is True
            and core.get("unauthorized_exposure_increase") is False
        )
        checks["cell_digests"] = bool(
            all(
                isinstance(cell, Mapping)
                and cell.get("schema_version") == CELL_SCHEMA
                and cell.get("source_sha") == core.get("source_sha")
                and cell.get("paper_only") is True
                and cell.get("live_trading_authority") is False
                and cell.get("unauthorized_exposure_increase") is False
                and cell.get("action_count") == len(cell.get("actions", []))
                and isinstance(cell.get("cell_increase_digest"), str)
                and cell["cell_increase_digest"] == _digest({
                    key: item for key, item in cell.items() if key != "cell_increase_digest"
                })
                for cell in cells
            )
        )
        allowed = {
            "INCREASED_WITH_FRESH_RISK",
            "INCREASE_BLOCKED_BY_DETERMINISTIC_RISK",
            "NO_INCREASE_AFTER_POST_CLOSE_SIZING",
        }
        actions = [action for cell in cells for action in cell.get("actions", [])]
        checks["action_digests"] = bool(
            all(
                isinstance(action, Mapping)
                and action.get("schema_version") == ACTION_SCHEMA
                and action.get("status") in allowed
                and action.get("paper_only") is True
                and action.get("live_trading_authority") is False
                and action.get("fresh_deterministic_risk_required") is True
                and action.get("unauthorized_exposure_increase") is False
                and isinstance(action.get("action_digest"), str)
                and action["action_digest"] == _digest({
                    key: item for key, item in action.items() if key != "action_digest"
                })
                for action in actions
            )
        )
        checks["fresh_risk"] = bool(
            core.get("exposure_increase_operational") is True
            and all(
                action.get("status") != "INCREASED_WITH_FRESH_RISK"
                or (
                    action.get("open_risk_allowed") is True
                    and action.get("risk_replay_verified") is True
                    and action.get("journal_committed") is True
                    and _decimal(action.get("final_quantity"), "final_quantity")
                    > _decimal(action.get("initial_quantity"), "initial_quantity")
                )
                for action in actions
            )
        )
        checks["counts"] = bool(
            core.get("pending_count") == sum(cell.get("pending_count", 0) for cell in cells)
            and core.get("increased_count")
            == sum(action.get("status") == "INCREASED_WITH_FRESH_RISK" for action in actions)
            and core.get("risk_blocked_count")
            == sum(
                action.get("status") == "INCREASE_BLOCKED_BY_DETERMINISTIC_RISK"
                for action in actions
            )
            and core.get("no_increase_count")
            == sum(
                action.get("status") == "NO_INCREASE_AFTER_POST_CLOSE_SIZING"
                for action in actions
            )
        )
    except (KeyError, TypeError, ValueError, RegimeSelectedExposureIncreaseError):
        pass
    return {"decision": "pass" if all(checks.values()) else "reject", "checks": checks}
