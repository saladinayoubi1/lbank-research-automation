"""Risk-reducing lifecycle bridge for regime-selected isolated Paper positions.

The synchronized regime runtime historically treated ``position_exists`` as a
non-actionable open proposal.  That is correct for opening, but it must not make
an already-open, still-qualified family disappear from the selector on the next
boundary.  This bridge replays the current selector inputs, requalifies existing
positions on fresh public Bybit data, restores those eligible candidates to the
selection surface, and applies only deterministic risk-reducing HOLD/REDUCE/CLOSE
transitions.

Exposure increases deliberately remain fail-closed in this slice.  They require a
fresh deterministic Risk-approved automated open/replacement path and are reported
as the next explicit core gap rather than being synthesized here.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from pathlib import Path
from typing import Any, Mapping

from nexus_demo_regime_cycle import (
    _eligible_health_rows,
    _load_cell_inputs,
    _runtime_for,
)
from nexus_regime_paper_lane import prepare_regime_paper_lane
from nexus_regime_strategy_runtime import load_runtime_evidence, verify_runtime_evidence
from nexus_regime_strategy_selector import select_strategy_mix
from paper_event_store import build_event, replay
from paper_execution import execute_paper_command
from phase6_research_pipeline import fetch_bind_bybit_dataset
from product_research_runtime import ProductResearchRuntime, TIMEFRAMES, _utc_ms
from product_runtime import (
    PAPER_CURRENCY,
    PAPER_DEFAULT_FEE_RATE,
    PAPER_DEFAULT_SLIPPAGE_BPS,
    _risk_reducing_exit,
)


SCHEMA = "nexus.regime-selected-position-rebalance.v1"
CELL_SCHEMA = "nexus.regime-selected-position-rebalance-cell.v1"
ACTION_SCHEMA = "nexus.regime-selected-position-rebalance-action.v1"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_JSON_BYTES = 20_000_000
_QUANTITY_QUANTUM = Decimal("0.00000001")


class RegimeSelectedRebalanceError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RegimeSelectedRebalanceError("rebalance evidence is not canonical JSON") from exc


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
        raise RegimeSelectedRebalanceError("rebalance evidence persistence failed") from exc


def _decimal(value: Any, field: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, float):
        raise RegimeSelectedRebalanceError(f"{field} must not use binary floating point")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise RegimeSelectedRebalanceError(f"{field} is not a decimal") from exc
    if not result.is_finite() or (positive and result <= 0):
        raise RegimeSelectedRebalanceError(f"{field} is outside the bounded range")
    return result


def _position(state: Any, symbol: str) -> tuple[str, Decimal, Decimal] | None:
    for item_symbol, side, quantity, entry in state.positions:
        if item_symbol == symbol:
            return str(side), Decimal(quantity), Decimal(entry)
    return None


def _candidate_from_health(family: str, health: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "family": family,
        "strategy_id": family,
        "strategy_version": health.get("strategy_version"),
        "lifecycle_state": "PAPER",
        "health_state": health.get("health_state"),
        "record_digest": health.get("record_digest"),
        "health_digest": health.get("health_digest"),
        "paper_only": True,
        "live_trading_authority": False,
    }


def _validate_regime_snapshot(value: Mapping[str, Any], source_sha: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, Mapping):
        raise RegimeSelectedRebalanceError("regime snapshot is missing")
    cells = value.get("cells")
    if (
        value.get("source_sha") != source_sha
        or value.get("paper_only") is not True
        or value.get("live_trading_authority") is not False
        or value.get("private_credentials_used") is not False
        or value.get("automatic_strategy_promotion") is not False
        or value.get("deterministic_risk_final_authority") is not True
        or not isinstance(cells, list)
        or len(cells) != 6
    ):
        raise RegimeSelectedRebalanceError("regime snapshot authority/source verification failed")
    return cells


def _fresh_research(
    *,
    state_root: Path,
    source_sha: str,
    symbol: str,
    timeframe: str,
    family: str,
    as_of_ms: int,
    history_limit: int,
    expected_dataset_binding: str,
) -> tuple[Any, dict[str, Any], dict[str, Any]]:
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
        raise RegimeSelectedRebalanceError("fresh research lineage is incomplete")
    if (
        result.get("source_sha") != source_sha
        or request.get("symbol") != symbol
        or request.get("timeframe") != timeframe
        or request.get("family") != family
        or dataset.get("binding_sha256") != expected_dataset_binding
    ):
        raise RegimeSelectedRebalanceError("fresh research source/dataset substitution detected")
    step_ms = int(TIMEFRAMES[timeframe]["step_ms"])
    last_open_ms = dataset.get("last_open_time_ms")
    if isinstance(last_open_ms, bool) or not isinstance(last_open_ms, int) or last_open_ms < 0:
        raise RegimeSelectedRebalanceError("fresh research close boundary is invalid")
    source_ms = last_open_ms + step_ms
    age_ms = as_of_ms - source_ms
    if age_ms < 0 or age_ms > step_ms * 2:
        raise RegimeSelectedRebalanceError("fresh research is stale or future-dated")
    price = _decimal(dataset.get("last_close"), "dataset.last_close", positive=True)
    if price <= 0:
        raise RegimeSelectedRebalanceError("fresh research price is invalid")
    preparation = prepare_regime_paper_lane(research)
    return runtime, dict(result), preparation


def _selected_weight(selection: Mapping[str, Any], family: str) -> Decimal:
    allocations = selection.get("allocations")
    if not isinstance(allocations, list):
        raise RegimeSelectedRebalanceError("corrected allocation rows are invalid")
    for row in allocations:
        if isinstance(row, Mapping) and row.get("family") == family:
            return _decimal(row.get("weight"), "allocation.weight")
    return Decimal("0")


def _target_quantity(state: Any, research: Mapping[str, Any], weight: Decimal) -> Decimal:
    dataset = research.get("dataset")
    if not isinstance(dataset, Mapping):
        raise RegimeSelectedRebalanceError("target sizing dataset is unavailable")
    price = _decimal(dataset.get("last_close"), "dataset.last_close", positive=True)
    equity = _decimal(state.equity, "portfolio.equity", positive=True)
    base = ((equity * Decimal("0.05")) / price).quantize(
        _QUANTITY_QUANTUM, rounding=ROUND_DOWN
    )
    target = base * weight
    if target < 0:
        raise RegimeSelectedRebalanceError("target quantity cannot be negative")
    return target


def _risk_reducing_transition(
    *,
    runtime: Any,
    source_sha: str,
    cell_digest: str,
    selection_digest: str,
    symbol: str,
    timeframe: str,
    family: str,
    strategy_version: str,
    as_of_ms: int,
    reference_price: str,
    target_quantity: Decimal,
) -> dict[str, Any]:
    with runtime._lock:
        events = runtime._ensure_account()
        state = replay(events).state
        current = _position(state, symbol)
        if current is None:
            core = {
                "schema_version": ACTION_SCHEMA,
                "family": family,
                "action": "FLAT",
                "reason_code": "NO_EXISTING_POSITION",
                "target_quantity": format(target_quantity, "f"),
                "pre_quantity": "0",
                "post_quantity": "0",
                "event_count_added": 0,
                "risk_reason": None,
                "terminal_event_digest": state.last_event_digest,
                "paper_only": True,
                "live_trading_authority": False,
                "exposure_increased": False,
            }
            return {**core, "action_digest": _digest(core)}

        side, current_quantity, _entry = current
        if target_quantity > current_quantity:
            core = {
                "schema_version": ACTION_SCHEMA,
                "family": family,
                "action": "HOLD_INCREASE_PENDING_FRESH_RISK",
                "reason_code": "TARGET_EXCEEDS_CURRENT_EXPOSURE",
                "target_quantity": format(target_quantity, "f"),
                "pre_quantity": format(current_quantity, "f"),
                "post_quantity": format(current_quantity, "f"),
                "event_count_added": 0,
                "risk_reason": None,
                "terminal_event_digest": state.last_event_digest,
                "paper_only": True,
                "live_trading_authority": False,
                "exposure_increased": False,
            }
            return {**core, "action_digest": _digest(core)}
        if target_quantity == current_quantity:
            core = {
                "schema_version": ACTION_SCHEMA,
                "family": family,
                "action": "HELD",
                "reason_code": "TARGET_MATCHES_CURRENT_EXPOSURE",
                "target_quantity": format(target_quantity, "f"),
                "pre_quantity": format(current_quantity, "f"),
                "post_quantity": format(current_quantity, "f"),
                "event_count_added": 0,
                "risk_reason": None,
                "terminal_event_digest": state.last_event_digest,
                "paper_only": True,
                "live_trading_authority": False,
                "exposure_increased": False,
            }
            return {**core, "action_digest": _digest(core)}

        quantity = current_quantity - target_quantity
        operation = "close" if target_quantity == 0 else "reduce"
        binding = _digest({
            "source_sha": source_sha,
            "cell_digest": cell_digest,
            "selection_digest": selection_digest,
            "head_event_digest": state.last_event_digest,
            "symbol": symbol,
            "timeframe": timeframe,
            "family": family,
            "operation": operation,
            "quantity": format(quantity, "f"),
            "target_quantity": format(target_quantity, "f"),
            "reference_price": reference_price,
            "as_of_ms": as_of_ms,
        })
        signal_id = f"regime-rebalance-{binding[:40]}"
        correlation_id = f"regime-rebalance-{binding[:32]}"
        risk = _risk_reducing_exit(
            state=state,
            signal_id=signal_id,
            symbol=symbol,
            side=side,
            quantity=format(quantity, "f"),
            reference_price=reference_price,
        )
        if not risk.allowed:
            raise RegimeSelectedRebalanceError("deterministic risk-reducing gate rejected rebalance")
        occurred_at = _utc_ms(as_of_ms)
        provenance = {
            "kind": "automatic",
            "source_id": "nexus-regime-selected-rebalance",
            "source_timestamp": occurred_at,
            "received_timestamp": occurred_at,
            "timeframe": timeframe,
            "confidence": "1",
            "strategy_version": strategy_version,
            "policy_version": "nexus-product-paper-risk-v1",
        }
        signal_event = build_event(
            event_id=f"{signal_id}:signal",
            event_type="signal_recorded",
            aggregate_id=state.aggregate_id or "paper-account",
            sequence=state.last_sequence + 1,
            occurred_at=occurred_at,
            correlation_id=correlation_id,
            causation_id=f"regime-rebalance:{binding[:40]}",
            provenance=provenance,
            previous_event_digest=state.last_event_digest,
            payload={
                "symbol": symbol,
                "timeframe": timeframe,
                "side": side,
                "quantity": format(quantity, "f"),
                "reference_price": reference_price,
            },
        )
        signal_state = replay([signal_event], previous_valid=state).state
        result = execute_paper_command(
            command={
                "operation": operation,
                "symbol": symbol,
                "side": side,
                "quantity": format(quantity, "f"),
                "reference_price": reference_price,
                "stop_price": reference_price,
                "target_price": reference_price,
                "fee_rate": PAPER_DEFAULT_FEE_RATE,
                "slippage_bps": PAPER_DEFAULT_SLIPPAGE_BPS,
                "currency": PAPER_CURRENCY,
            },
            state=signal_state,
            risk_decision=risk,
            occurred_at=occurred_at,
            provenance=provenance,
            correlation_id=correlation_id,
            causation_id=signal_id,
        )
        post = _position(result.state, symbol)
        post_quantity = Decimal("0") if post is None else post[1]
        if post_quantity > current_quantity:
            raise RegimeSelectedRebalanceError("risk-reducing transition increased exposure")
        if operation == "close" and post is not None:
            raise RegimeSelectedRebalanceError("regime-selected close left residual exposure")
        if operation == "reduce" and post_quantity != target_quantity:
            raise RegimeSelectedRebalanceError("regime-selected reduce missed deterministic target")
        runtime._write_events([*events, signal_event, *result.events])

    core = {
        "schema_version": ACTION_SCHEMA,
        "family": family,
        "action": "CLOSED" if operation == "close" else "REDUCED",
        "reason_code": "REMOVED_FROM_SELECTION" if operation == "close" else "TARGET_WEIGHT_REDUCED",
        "target_quantity": format(target_quantity, "f"),
        "pre_quantity": format(current_quantity, "f"),
        "post_quantity": format(post_quantity, "f"),
        "event_count_added": 1 + len(result.events),
        "risk_reason": risk.reason_code,
        "terminal_event_digest": result.state.last_event_digest,
        "paper_only": True,
        "live_trading_authority": False,
        "exposure_increased": False,
    }
    return {**core, "action_digest": _digest(core)}


def run_regime_selected_rebalance(
    *,
    manifest: Mapping[str, Any],
    state_root: str | Path,
    source_sha: str,
    regime_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    source_sha = str(source_sha).strip().lower()
    if not _SHA_RE.fullmatch(source_sha):
        raise RegimeSelectedRebalanceError("source_sha must be an exact Git SHA")
    root = Path(state_root).resolve()
    cells = _validate_regime_snapshot(regime_snapshot, source_sha)
    by_identity = {(row.get("symbol"), row.get("timeframe")): row for row in cells}
    expected = {
        (symbol, timeframe)
        for symbol in manifest["symbols"]
        for timeframe in manifest["timeframes"]
    }
    if set(by_identity) != expected:
        raise RegimeSelectedRebalanceError("regime cells do not match the manifest")

    cell_results: list[dict[str, Any]] = []
    pending_increase = 0
    for symbol in manifest["symbols"]:
        for timeframe in manifest["timeframes"]:
            cell = by_identity[(symbol, timeframe)]
            if cell.get("source_sha") != source_sha:
                raise RegimeSelectedRebalanceError("regime cell cross-SHA substitution detected")
            as_of_ms = cell.get("as_of_ms")
            if isinstance(as_of_ms, bool) or not isinstance(as_of_ms, int) or as_of_ms <= 0:
                raise RegimeSelectedRebalanceError("regime cell as_of_ms is invalid")
            cell_digest = cell.get("cell_digest")
            expected_binding = cell.get("context_dataset_binding_sha256")
            if (
                not isinstance(cell_digest, str) or not _SHA256_RE.fullmatch(cell_digest)
                or not isinstance(expected_binding, str) or not _SHA256_RE.fullmatch(expected_binding)
            ):
                raise RegimeSelectedRebalanceError("regime cell digest/binding is invalid")

            evidence_name = cell.get("runtime_evidence_file")
            if not isinstance(evidence_name, str) or Path(evidence_name).name != evidence_name:
                raise RegimeSelectedRebalanceError("runtime evidence filename is unsafe")
            evidence_path = (
                root / "regime_runtime_evidence" / symbol.lower() / timeframe / evidence_name
            )
            runtime_evidence = load_runtime_evidence(evidence_path)
            verification = verify_runtime_evidence(runtime_evidence)
            if (
                verification.get("decision") != "pass"
                or runtime_evidence.get("source_sha") != source_sha
                or runtime_evidence.get("runtime_digest") != cell.get("runtime_digest")
                or runtime_evidence.get("selection_digest") != cell.get("selection_digest")
            ):
                raise RegimeSelectedRebalanceError("runtime evidence failed exact-cell verification")
            selector_inputs = runtime_evidence.get("selector_inputs")
            if not isinstance(selector_inputs, Mapping):
                raise RegimeSelectedRebalanceError("selector replay inputs are unavailable")
            context = selector_inputs.get("context")
            policy = selector_inputs.get("policy")
            original_candidates = selector_inputs.get("candidates")
            if (
                not isinstance(context, Mapping)
                or not isinstance(policy, Mapping)
                or not isinstance(original_candidates, list)
            ):
                raise RegimeSelectedRebalanceError("selector replay inputs are malformed")
            candidates = [dict(row) for row in original_candidates if isinstance(row, Mapping)]
            if len(candidates) != len(original_candidates):
                raise RegimeSelectedRebalanceError("selector candidate row is malformed")
            candidate_families = {str(row.get("family")) for row in candidates}

            ledger, performance = _load_cell_inputs(
                state_root=root, symbol=symbol, timeframe=timeframe, source_sha=source_sha
            )
            health_rows = _eligible_health_rows(ledger, performance)
            preparation_rows = cell.get("preparations")
            if not isinstance(preparation_rows, list):
                raise RegimeSelectedRebalanceError("regime preparation evidence is unavailable")
            preparation_status = {
                str(row.get("family")): str(row.get("status"))
                for row in preparation_rows if isinstance(row, Mapping)
            }
            research_by_family: dict[str, tuple[Any, dict[str, Any], dict[str, Any]]] = {}

            for family in manifest["families"]:
                runtime = _runtime_for(
                    state_root=root, symbol=symbol, timeframe=timeframe,
                    family=family, as_of_ms=as_of_ms,
                )
                with runtime._lock:
                    state = replay(runtime._ensure_account()).state
                    current = _position(state, symbol)
                if current is None:
                    continue
                fresh = _fresh_research(
                    state_root=root,
                    source_sha=source_sha,
                    symbol=symbol,
                    timeframe=timeframe,
                    family=family,
                    as_of_ms=as_of_ms,
                    history_limit=int(manifest["history_limit"]),
                    expected_dataset_binding=expected_binding,
                )
                research_by_family[family] = fresh
                _runtime, research_result, preparation = fresh
                health = health_rows.get(family)
                if (
                    family not in candidate_families
                    and preparation.get("status") == "position_exists"
                    and preparation_status.get(family) == "position_exists"
                    and isinstance(health, Mapping)
                    and research_result.get("qualification", {}).get("strategy_version")
                    == health.get("strategy_version")
                ):
                    candidates.append(_candidate_from_health(family, health))
                    candidate_families.add(family)

            corrected_selection = select_strategy_mix(
                context=context,
                candidates=candidates,
                policy=policy,
                source_sha=source_sha,
            )
            actions: list[dict[str, Any]] = []
            for family in sorted(research_by_family):
                runtime, research_result, _preparation = research_by_family[family]
                weight = _selected_weight(corrected_selection, family)
                with runtime._lock:
                    state = replay(runtime._ensure_account()).state
                target_quantity = (
                    Decimal("0") if weight == 0
                    else _target_quantity(state, research_result, weight)
                )
                dataset = research_result["dataset"]
                action = _risk_reducing_transition(
                    runtime=runtime,
                    source_sha=source_sha,
                    cell_digest=cell_digest,
                    selection_digest=corrected_selection["selection_digest"],
                    symbol=symbol,
                    timeframe=timeframe,
                    family=family,
                    strategy_version=str(
                        research_result.get("qualification", {}).get("strategy_version", "unknown")
                    ),
                    as_of_ms=as_of_ms,
                    reference_price=str(dataset["last_close"]),
                    target_quantity=target_quantity,
                )
                actions.append(action)
                if action["action"] == "HOLD_INCREASE_PENDING_FRESH_RISK":
                    pending_increase += 1

            cell_core = {
                "schema_version": CELL_SCHEMA,
                "symbol": symbol,
                "timeframe": timeframe,
                "source_sha": source_sha,
                "as_of_ms": as_of_ms,
                "regime_cell_digest": cell_digest,
                "runtime_digest": runtime_evidence["runtime_digest"],
                "runtime_verification_digest": verification["verification_digest"],
                "original_selection_digest": runtime_evidence["selection_digest"],
                "corrected_selection_digest": corrected_selection["selection_digest"],
                "corrected_cash_weight": corrected_selection["cash_weight"],
                "corrected_allocations": corrected_selection["allocations"],
                "action_count": len(actions),
                "actions": actions,
                "paper_only": True,
                "live_trading_authority": False,
                "private_credentials_used": False,
                "automatic_strategy_promotion": False,
                "deterministic_risk_final_authority": True,
                "exposure_increased": False,
            }
            cell_results.append({**cell_core, "cell_rebalance_digest": _digest(cell_core)})

    core = {
        "schema_version": SCHEMA,
        "source_sha": source_sha,
        "regime_cycle_digest": regime_snapshot.get("cycle_digest"),
        "cell_count": len(cell_results),
        "cells": cell_results,
        "held_count": sum(
            action["action"] == "HELD"
            for cell in cell_results for action in cell["actions"]
        ),
        "reduced_count": sum(
            action["action"] == "REDUCED"
            for cell in cell_results for action in cell["actions"]
        ),
        "closed_count": sum(
            action["action"] == "CLOSED"
            for cell in cell_results for action in cell["actions"]
        ),
        "increase_pending_count": pending_increase,
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
    result = {**core, "rebalance_digest": _digest(core)}
    if verify_regime_selected_rebalance(result)["decision"] != "pass":
        raise RegimeSelectedRebalanceError("rebalance snapshot failed independent shape verification")
    _atomic_json(root / "demo" / "regime-selected-rebalance.json", result)
    return result


def verify_regime_selected_rebalance(value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {
        "schema": False,
        "digest": False,
        "shape": False,
        "authority": False,
        "risk_reducing_only": False,
        "cell_digests": False,
        "action_digests": False,
        "mission_truth": False,
    }
    try:
        core = dict(value)
        claimed = core.pop("rebalance_digest", None)
        cells = core.get("cells")
        checks["schema"] = core.get("schema_version") == SCHEMA
        checks["digest"] = isinstance(claimed, str) and claimed == _digest(core)
        checks["shape"] = bool(
            core.get("cell_count") == 6
            and isinstance(cells, list)
            and len(cells) == 6
        )
        checks["authority"] = bool(
            core.get("paper_only") is True
            and core.get("live_trading_authority") is False
            and core.get("private_credentials_used") is False
            and core.get("automatic_strategy_promotion") is False
            and core.get("deterministic_risk_final_authority") is True
        )
        checks["risk_reducing_only"] = bool(
            core.get("exposure_increased") is False
            and all(
                isinstance(cell, Mapping) and cell.get("exposure_increased") is False
                for cell in cells
            )
        )
        checks["cell_digests"] = bool(
            all(
                isinstance(cell, Mapping)
                and cell.get("schema_version") == CELL_SCHEMA
                and isinstance(cell.get("cell_rebalance_digest"), str)
                and cell["cell_rebalance_digest"] == _digest({
                    key: item for key, item in cell.items()
                    if key != "cell_rebalance_digest"
                })
                for cell in cells
            )
        )
        allowed_actions = {
            "FLAT", "HELD", "REDUCED", "CLOSED",
            "HOLD_INCREASE_PENDING_FRESH_RISK",
        }
        checks["action_digests"] = bool(
            all(
                isinstance(action, Mapping)
                and action.get("schema_version") == ACTION_SCHEMA
                and action.get("action") in allowed_actions
                and action.get("paper_only") is True
                and action.get("live_trading_authority") is False
                and action.get("exposure_increased") is False
                and isinstance(action.get("action_digest"), str)
                and action["action_digest"] == _digest({
                    key: item for key, item in action.items() if key != "action_digest"
                })
                for cell in cells for action in cell.get("actions", [])
            )
        )
        checks["mission_truth"] = bool(
            core.get("risk_reducing_rebalance_operational") is True
            and core.get("exposure_increase_operational") is False
            and core.get("regime_selected_rebalance_operational") is False
            and core.get("remaining_core_gap")
            == "REGIME_SELECTED_EXPOSURE_INCREASE_WITH_FRESH_RISK"
        )
    except (KeyError, TypeError, ValueError):
        pass
    return {"decision": "pass" if all(checks.values()) else "reject", "checks": checks}
