"""Digest-bound regime selection to isolated Paper pipelines.

This runtime is orchestration only. It cannot promote strategies, bypass
Deterministic Risk, share Paper portfolios, or grant Live authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping, Sequence

from automated_signal_pipeline import PipelineResult, run_automated_signal_pipeline
from deterministic_risk import SIGNAL_KEYS, RiskInputError, evaluate_risk
from nexus_regime_strategy_selector import select_strategy_mix
from paper_event_store import PaperEventError, PortfolioState, validate_event


RUNTIME_SCHEMA = "nexus.regime-strategy-runtime.v1"
VERIFICATION_SCHEMA = "nexus.regime-strategy-runtime-verification.v1"
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_LANE_KEYS = {
    "family", "dataset", "qualification", "regime", "decision", "risk_state",
    "risk_policy", "portfolio_state", "fee_rate", "slippage_bps",
}
_RUNTIME_KEYS = {
    "schema_version", "source_sha", "selector_inputs", "selection_digest", "selection",
    "occurred_at", "lanes", "cash_weight", "paper_only", "live_trading_authority",
    "automatic_strategy_promotion", "deterministic_risk_final_authority",
    "runtime_digest",
}
_EVIDENCE_LANE_KEYS = {
    "family", "weight", "portfolio_id", "signal_id", "pipeline_input", "risk_input",
    "risk_state", "risk_policy", "risk_decision", "risk_allowed", "risk_reason",
    "execution_status", "events", "event_digests", "terminal_portfolio",
    "paper_only", "live_trading_authority",
}
_SELECTOR_INPUT_KEYS = {"context", "candidates", "policy"}
_PIPELINE_INPUT_KEYS = {
    "dataset", "qualification", "regime", "base_decision", "decision", "risk_state",
    "risk_policy", "portfolio_state", "fee_rate", "slippage_bps",
}
_PORTFOLIO_KEYS = {
    "aggregate_id", "currency", "cash", "equity", "realized_pnl", "unrealized_pnl",
    "positions", "stops", "targets", "kill_switch_enabled", "session_open",
    "last_sequence", "last_event_digest",
}
_RISK_DECISION_KEYS = {
    "allowed", "reason_code", "policy_id", "policy_version", "signal_id",
    "proposed_notional", "resulting_exposure",
}
_VERIFICATION_CHECKS = (
    "schema", "shape", "source_binding", "paper_only", "live_disabled",
    "promotion_disabled", "risk_final", "runtime_digest", "selection_digest",
    "selection_replay", "selection_authority", "lane_shape", "lane_selection_binding",
    "portfolio_isolation", "lane_authority", "proposal_binding", "risk_replay",
    "risk_execution_binding", "pipeline_replay", "event_chain", "event_semantics",
    "allocation_total",
)


class RegimeStrategyRuntimeError(ValueError):
    pass


@dataclass(frozen=True)
class RegimeStrategyRuntimeResult:
    evidence: Mapping[str, Any]
    pipelines: tuple[PipelineResult, ...]


def _risk_decision_evidence(decision: Any) -> dict[str, Any]:
    return {
        "allowed": decision.allowed,
        "reason_code": decision.reason_code,
        "policy_id": decision.policy_id,
        "policy_version": decision.policy_version,
        "signal_id": decision.signal_id,
        "proposed_notional": format(decision.proposed_notional, "f"),
        "resulting_exposure": format(decision.resulting_exposure, "f"),
    }


def _json_copy(value: Any) -> Any:
    return json.loads(_canonical(value))


def _portfolio_evidence(state: PortfolioState) -> dict[str, Any]:
    return {
        "aggregate_id": state.aggregate_id,
        "currency": state.currency,
        "cash": format(state.cash, "f"),
        "equity": format(state.equity, "f"),
        "realized_pnl": format(state.realized_pnl, "f"),
        "unrealized_pnl": format(state.unrealized_pnl, "f"),
        "positions": [
            [symbol, side, format(quantity, "f"), format(entry, "f")]
            for symbol, side, quantity, entry in state.positions
        ],
        "stops": [[symbol, format(price, "f")] for symbol, price in state.stops],
        "targets": [[symbol, format(price, "f")] for symbol, price in state.targets],
        "kill_switch_enabled": state.kill_switch_enabled,
        "session_open": state.session_open,
        "last_sequence": state.last_sequence,
        "last_event_digest": state.last_event_digest,
    }


def _portfolio_from_evidence(value: Any) -> PortfolioState:
    if not isinstance(value, Mapping) or set(value) != _PORTFOLIO_KEYS:
        raise RegimeStrategyRuntimeError("portfolio evidence schema mismatch")
    if value["aggregate_id"] is not None and not isinstance(value["aggregate_id"], str):
        raise RegimeStrategyRuntimeError("portfolio aggregate_id is invalid")
    if value["currency"] is not None and not isinstance(value["currency"], str):
        raise RegimeStrategyRuntimeError("portfolio currency is invalid")
    if (
        not isinstance(value["kill_switch_enabled"], bool)
        or not isinstance(value["session_open"], bool)
        or isinstance(value["last_sequence"], bool)
        or not isinstance(value["last_sequence"], int)
        or value["last_sequence"] < 0
        or not isinstance(value["last_event_digest"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", value["last_event_digest"])
    ):
        raise RegimeStrategyRuntimeError("portfolio control evidence is invalid")
    positions = value["positions"]
    stops = value["stops"]
    targets = value["targets"]
    if (
        not isinstance(positions, list) or len(positions) > 10_000
        or not isinstance(stops, list) or len(stops) > 10_000
        or not isinstance(targets, list) or len(targets) > 10_000
        or any(not isinstance(row, list) or len(row) != 4 for row in positions)
        or any(not isinstance(row, list) or len(row) != 2 for row in stops)
        or any(not isinstance(row, list) or len(row) != 2 for row in targets)
    ):
        raise RegimeStrategyRuntimeError("portfolio position evidence is invalid")
    return PortfolioState(
        aggregate_id=value["aggregate_id"],
        currency=value["currency"],
        cash=_decimal(value["cash"], "portfolio.cash"),
        equity=_decimal(value["equity"], "portfolio.equity"),
        realized_pnl=_decimal(value["realized_pnl"], "portfolio.realized_pnl"),
        unrealized_pnl=_decimal(value["unrealized_pnl"], "portfolio.unrealized_pnl"),
        positions=tuple(
            (str(row[0]), str(row[1]), _decimal(row[2], "position.quantity"),
             _decimal(row[3], "position.entry"))
            for row in positions
        ),
        stops=tuple((str(row[0]), _decimal(row[1], "stop.price")) for row in stops),
        targets=tuple((str(row[0]), _decimal(row[1], "target.price")) for row in targets),
        kill_switch_enabled=value["kill_switch_enabled"],
        session_open=value["session_open"],
        last_sequence=value["last_sequence"],
        last_event_digest=value["last_event_digest"],
    )


def _event_checks(row: Mapping[str, Any]) -> tuple[bool, bool]:
    events = row.get("events")
    digests = row.get("event_digests")
    if not isinstance(events, list) or not events or not isinstance(digests, list):
        return False, False
    try:
        validated = [validate_event(dict(event)) for event in events]
    except (PaperEventError, TypeError, ValueError):
        return False, False
    chain_valid = digests == [event["event_digest"] for event in validated]
    chain_valid = chain_valid and all(
        current["previous_event_digest"] == previous["event_digest"]
        for previous, current in zip(validated, validated[1:])
    )
    chain_valid = chain_valid and all(
        event["aggregate_id"] == row.get("portfolio_id") for event in validated
    )
    first = validated[0]
    risk = row.get("risk_decision", {})
    risk_input = row.get("risk_input", {})
    if not isinstance(risk, Mapping) or not isinstance(risk_input, Mapping):
        return chain_valid, False
    semantic_valid = bool(
        first["event_type"] == "signal_recorded"
        and first["event_id"] == f"{row.get('signal_id')}:signal"
        and first["payload"].get("symbol") == risk_input.get("symbol")
        and first["payload"].get("timeframe") == risk_input.get("timeframe")
        and first["payload"].get("quantity") == risk_input.get("quantity")
        and first["payload"].get("reference_price") == risk_input.get("reference_price")
    )
    event_types = [event["event_type"] for event in validated]
    if risk.get("allowed") is True:
        risk_events = [event for event in validated if event["event_type"] == "risk_decision_recorded"]
        semantic_valid = bool(
            semantic_valid
            and row.get("execution_status") in {"FILLED", "PARTIALLY_FILLED"}
            and len(risk_events) == 1
            and risk_events[0]["payload"] == {
                "decision": "allow", "reason_code": risk.get("reason_code")
            }
            and "order_intent_recorded" in event_types
            and "simulated_fill_recorded" in event_types
            and "equity_snapshot_recorded" in event_types
            and "risk_rejection_recorded" not in event_types
        )
    else:
        semantic_valid = bool(
            semantic_valid
            and row.get("execution_status") == "BLOCKED"
            and event_types == ["signal_recorded", "risk_rejection_recorded"]
            and validated[1]["payload"] == {"reason_code": risk.get("reason_code")}
        )
    return chain_valid, semantic_valid


def verify_runtime_evidence(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Independently replay Risk and verify Paper event and digest bindings."""
    checks = {name: False for name in _VERIFICATION_CHECKS}
    claimed_runtime: Any = None
    try:
        if not isinstance(evidence, Mapping):
            raise RegimeStrategyRuntimeError("runtime evidence must be a mapping")
        checks["schema"] = evidence.get("schema_version") == RUNTIME_SCHEMA
        checks["shape"] = set(evidence) == _RUNTIME_KEYS
        checks["paper_only"] = evidence.get("paper_only") is True
        checks["live_disabled"] = evidence.get("live_trading_authority") is False
        checks["promotion_disabled"] = evidence.get("automatic_strategy_promotion") is False
        checks["risk_final"] = evidence.get("deterministic_risk_final_authority") is True
        claimed_runtime = evidence.get("runtime_digest")
        unsigned = dict(evidence)
        unsigned.pop("runtime_digest", None)
        checks["runtime_digest"] = (
            isinstance(claimed_runtime, str)
            and bool(re.fullmatch(r"[0-9a-f]{64}", claimed_runtime))
            and claimed_runtime == _digest(unsigned)
        )
        selection = evidence.get("selection")
        if not isinstance(selection, Mapping):
            raise RegimeStrategyRuntimeError("selection evidence must be a mapping")
        selection_core = dict(selection)
        claimed_selection = selection_core.pop("selection_digest", None)
        checks["selection_digest"] = (
            isinstance(claimed_selection, str)
            and claimed_selection == evidence.get("selection_digest")
            and claimed_selection == _digest(selection_core)
        )
        selector_inputs = evidence.get("selector_inputs")
        if not isinstance(selector_inputs, Mapping) or set(selector_inputs) != _SELECTOR_INPUT_KEYS:
            raise RegimeStrategyRuntimeError("selector replay inputs are invalid")
        replayed_selection = select_strategy_mix(
            context=selector_inputs["context"],
            candidates=selector_inputs["candidates"],
            policy=selector_inputs["policy"],
            source_sha=str(evidence.get("source_sha", "")),
        )
        checks["selection_replay"] = replayed_selection == selection
        checks["source_binding"] = bool(
            _GIT_SHA_RE.fullmatch(str(evidence.get("source_sha", "")))
            and selection.get("source_sha") == evidence.get("source_sha")
        )
        checks["selection_authority"] = bool(
            selection.get("paper_only") is True
            and selection.get("live_trading_authority") is False
            and selection.get("automatic_strategy_promotion") is False
            and selection.get("deterministic_risk_final_authority") is True
            and selection.get("cash_weight") == evidence.get("cash_weight")
        )
        allocations = selection.get("allocations")
        lanes = evidence.get("lanes")
        checks["lane_shape"] = bool(
            isinstance(lanes, list)
            and len(lanes) <= 32
            and isinstance(allocations, list)
            and len(allocations) <= 32
            and all(isinstance(row, Mapping) and set(row) == _EVIDENCE_LANE_KEYS for row in lanes)
        )
        if not checks["lane_shape"]:
            raise RegimeStrategyRuntimeError("runtime lane evidence schema mismatch")
        selected_rows = {
            row.get("family"): row for row in allocations if isinstance(row, Mapping)
        }
        selected = {family: row.get("weight") for family, row in selected_rows.items()}
        observed = {row.get("family"): row.get("weight") for row in lanes}
        checks["lane_selection_binding"] = bool(
            len(selected) == len(allocations)
            and len(observed) == len(lanes)
            and observed == selected
        )
        portfolios = [row.get("portfolio_id") for row in lanes]
        checks["portfolio_isolation"] = bool(
            all(isinstance(item, str) and item for item in portfolios)
            and len(set(portfolios)) == len(portfolios)
        )
        checks["lane_authority"] = all(
            row.get("paper_only") is True and row.get("live_trading_authority") is False
            for row in lanes
        )
        risk_replay = True
        risk_execution = True
        proposal_binding = True
        pipeline_replay = True
        event_chain = True
        event_semantics = True
        for row in lanes:
            risk_input = row.get("risk_input")
            risk_state = row.get("risk_state")
            risk_policy = row.get("risk_policy")
            recorded = row.get("risk_decision")
            if (
                not isinstance(risk_input, Mapping)
                or set(risk_input) != SIGNAL_KEYS
                or not isinstance(risk_state, Mapping)
                or not isinstance(risk_policy, Mapping)
                or not isinstance(recorded, Mapping)
                or set(recorded) != _RISK_DECISION_KEYS
            ):
                risk_replay = False
                risk_execution = False
            else:
                replayed = evaluate_risk(
                    risk_input, risk_state, risk_policy,
                    evaluated_at=str(evidence.get("occurred_at", "")),
                )
                replayed_evidence = _risk_decision_evidence(replayed)
                risk_replay = risk_replay and replayed_evidence == recorded
                risk_execution = risk_execution and bool(
                    recorded.get("signal_id") == row.get("signal_id")
                    and recorded.get("allowed") == row.get("risk_allowed")
                    and recorded.get("reason_code") == row.get("risk_reason")
                    and (
                        (recorded.get("allowed") is True and row.get("execution_status") != "BLOCKED")
                        or (recorded.get("allowed") is False and row.get("execution_status") == "BLOCKED")
                    )
                )
            pipeline_input = row.get("pipeline_input")
            if not isinstance(pipeline_input, Mapping) or set(pipeline_input) != _PIPELINE_INPUT_KEYS:
                proposal_binding = False
                pipeline_replay = False
            else:
                allocation = selected_rows.get(row.get("family"), {})
                qualification = pipeline_input.get("qualification", {})
                base_decision = pipeline_input.get("base_decision", {})
                expected_decision = dict(base_decision) if isinstance(base_decision, Mapping) else {}
                try:
                    base_quantity = _decimal(
                        expected_decision.get("quantity"), "base_decision.quantity", positive=True
                    )
                    weight = _decimal(row.get("weight"), "lane.weight", positive=True)
                    expected_decision["quantity"] = format(base_quantity * weight, "f")
                    binding = _digest({
                        "selection_digest": evidence.get("selection_digest"),
                        "family": row.get("family"),
                        "weight": row.get("weight"),
                        "original_decision_id": expected_decision.get("decision_id"),
                    })
                    expected_decision["decision_id"] = f"decision-{binding[:40]}"
                    expected_decision["correlation_id"] = f"regime-runtime-{binding[:32]}"
                    proposal_binding = proposal_binding and bool(
                        isinstance(allocation, Mapping)
                        and isinstance(qualification, Mapping)
                        and qualification.get("strategy_id") == allocation.get("strategy_id")
                        and qualification.get("strategy_version") == allocation.get("strategy_version")
                        and expected_decision == pipeline_input.get("decision")
                        and row.get("risk_state") == pipeline_input.get("risk_state")
                        and row.get("risk_policy") == pipeline_input.get("risk_policy")
                    )
                except (RegimeStrategyRuntimeError, TypeError, ValueError):
                    proposal_binding = False
                replayed_pipeline = run_automated_signal_pipeline(
                    dataset=pipeline_input["dataset"],
                    qualification=pipeline_input["qualification"],
                    regime=pipeline_input["regime"],
                    decision=pipeline_input["decision"],
                    risk_state=pipeline_input["risk_state"],
                    risk_policy=pipeline_input["risk_policy"],
                    portfolio_state=_portfolio_from_evidence(pipeline_input["portfolio_state"]),
                    occurred_at=str(evidence.get("occurred_at", "")),
                    fee_rate=pipeline_input["fee_rate"],
                    slippage_bps=pipeline_input["slippage_bps"],
                )
                replayed_status = (
                    replayed_pipeline.execution.execution_status
                    if replayed_pipeline.execution else "BLOCKED"
                )
                pipeline_replay = pipeline_replay and bool(
                    replayed_pipeline.signal["signal_id"] == row.get("signal_id")
                    and {key: replayed_pipeline.signal[key] for key in SIGNAL_KEYS}
                    == row.get("risk_input")
                    and _risk_decision_evidence(replayed_pipeline.risk_decision) == recorded
                    and [dict(event) for event in replayed_pipeline.events] == row.get("events")
                    and replayed_status == row.get("execution_status")
                    and _portfolio_evidence(replayed_pipeline.state)
                    == row.get("terminal_portfolio")
                )
            lane_chain, lane_semantics = _event_checks(row)
            event_chain = event_chain and lane_chain
            event_semantics = event_semantics and lane_semantics
        checks["risk_replay"] = risk_replay
        checks["risk_execution_binding"] = risk_execution
        checks["proposal_binding"] = proposal_binding
        checks["pipeline_replay"] = pipeline_replay
        checks["event_chain"] = event_chain
        checks["event_semantics"] = event_semantics
        total = _decimal(evidence.get("cash_weight"), "cash_weight") + sum(
            (_decimal(row["weight"], "lane.weight") for row in lanes), Decimal(0)
        )
        checks["allocation_total"] = total == Decimal("1")
    except (RegimeStrategyRuntimeError, RiskInputError, PaperEventError, KeyError, TypeError, ValueError):
        pass
    passed = all(checks.values())
    core = {
        "schema_version": VERIFICATION_SCHEMA,
        "decision": "pass" if passed else "reject",
        "verifier": "regime-strategy-runtime-independent-verifier",
        "runtime_digest": claimed_runtime,
        "checks": checks,
    }
    return {**core, "verification_digest": _digest(core)}


def persist_runtime_evidence(evidence: Mapping[str, Any], state_root: Path) -> Path:
    """Persist one verified result using create-once append-only semantics."""
    verification = verify_runtime_evidence(evidence)
    if verification["decision"] != "pass":
        raise RegimeStrategyRuntimeError("independent verifier rejected runtime evidence")
    root = Path(state_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{evidence['runtime_digest']}.json"
    temporary = root / f".{evidence['runtime_digest']}.{os.getpid()}.tmp"
    payload = json.dumps(
        {**dict(evidence), "verification": verification},
        indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False,
    ).encode("utf-8") + b"\n"
    if path.exists():
        _verify_existing_evidence_file(path, payload)
        return path
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            _verify_existing_evidence_file(path, payload)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def _verify_existing_evidence_file(path: Path, payload: bytes) -> None:
    if path.is_symlink() or not path.is_file():
        raise RegimeStrategyRuntimeError("append-only runtime evidence path is unsafe")
    try:
        existing = path.read_bytes()
    except OSError as exc:
        raise RegimeStrategyRuntimeError("append-only runtime evidence is unreadable") from exc
    if existing != payload:
        raise RegimeStrategyRuntimeError("append-only runtime evidence collision")


def load_runtime_evidence(path: Path) -> dict[str, Any]:
    """Reload persisted evidence after restart and re-run independent verification."""
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 5_000_000:
        raise RegimeStrategyRuntimeError("runtime evidence path is unsafe or unbounded")
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RegimeStrategyRuntimeError("runtime evidence is unreadable") from exc
    if not isinstance(stored, Mapping) or "verification" not in stored:
        raise RegimeStrategyRuntimeError("persisted runtime verification is missing")
    evidence = dict(stored)
    recorded = evidence.pop("verification")
    verification = verify_runtime_evidence(evidence)
    if verification["decision"] != "pass" or recorded != verification:
        raise RegimeStrategyRuntimeError("persisted runtime evidence failed restart verification")
    expected_name = f"{evidence['runtime_digest']}.json"
    if path.name != expected_name:
        raise RegimeStrategyRuntimeError("runtime evidence filename binding mismatch")
    return evidence


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RegimeStrategyRuntimeError("runtime evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _decimal(value: Any, field: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, float):
        raise RegimeStrategyRuntimeError(f"{field} must not use binary floating point")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise RegimeStrategyRuntimeError(f"{field} is not a decimal") from exc
    if not result.is_finite() or (positive and result <= 0):
        raise RegimeStrategyRuntimeError(f"{field} is outside the bounded range")
    return result


def _lanes(value: Any) -> dict[str, Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) > 32:
        raise RegimeStrategyRuntimeError("lanes must be a bounded sequence")
    result: dict[str, Mapping[str, Any]] = {}
    aggregate_ids: set[str] = set()
    for lane in value:
        if not isinstance(lane, Mapping) or set(lane) != _LANE_KEYS:
            raise RegimeStrategyRuntimeError("Paper lane schema mismatch")
        family = lane["family"]
        if not isinstance(family, str) or not family or family in result:
            raise RegimeStrategyRuntimeError("Paper lane family is invalid or duplicated")
        portfolio = lane["portfolio_state"]
        if not isinstance(portfolio, PortfolioState) or not portfolio.aggregate_id:
            raise RegimeStrategyRuntimeError("Paper lane requires an initialized portfolio")
        if portfolio.aggregate_id in aggregate_ids:
            raise RegimeStrategyRuntimeError("Paper lanes must use isolated portfolios")
        aggregate_ids.add(portfolio.aggregate_id)
        result[family] = lane
    return result


def run_regime_strategy_runtime(
    *,
    context: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    selector_policy: Mapping[str, Any],
    lanes: Sequence[Mapping[str, Any]],
    source_sha: str,
    occurred_at: str,
) -> RegimeStrategyRuntimeResult:
    """Select a mix and route each selected family through its isolated Paper lane."""
    source_sha = str(source_sha).strip().lower()
    if not _GIT_SHA_RE.fullmatch(source_sha):
        raise RegimeStrategyRuntimeError("source_sha must be a 40-character Git SHA")
    selection = select_strategy_mix(
        context=context, candidates=candidates, policy=selector_policy, source_sha=source_sha,
    )
    lane_map = _lanes(lanes)
    selected = {row["family"]: row for row in selection["allocations"]}
    if set(lane_map) != set(selected):
        raise RegimeStrategyRuntimeError("Paper lanes must exactly match selected families")

    pipeline_results: list[PipelineResult] = []
    rows: list[dict[str, Any]] = []
    for family in selector_policy["approved_families"]:
        allocation = selected.get(family)
        if allocation is None:
            continue
        lane = lane_map[family]
        qualification = dict(lane["qualification"])
        base_decision = dict(lane["decision"])
        decision = dict(base_decision)
        if (
            qualification.get("strategy_id") != allocation["strategy_id"]
            or qualification.get("strategy_version") != allocation["strategy_version"]
        ):
            raise RegimeStrategyRuntimeError("lane qualification contradicts selected strategy")
        base_quantity = _decimal(decision.get("quantity"), "decision.quantity", positive=True)
        weight = _decimal(allocation["weight"], "allocation.weight", positive=True)
        decision["quantity"] = format(base_quantity * weight, "f")
        binding = _digest({
            "selection_digest": selection["selection_digest"],
            "family": family,
            "weight": allocation["weight"],
            "original_decision_id": decision.get("decision_id"),
        })
        decision["decision_id"] = f"decision-{binding[:40]}"
        decision["correlation_id"] = f"regime-runtime-{binding[:32]}"
        pipeline_input = {
            "dataset": _json_copy(lane["dataset"]),
            "qualification": _json_copy(qualification),
            "regime": _json_copy(lane["regime"]),
            "base_decision": _json_copy(base_decision),
            "decision": _json_copy(decision),
            "risk_state": _json_copy(lane["risk_state"]),
            "risk_policy": _json_copy(lane["risk_policy"]),
            "portfolio_state": _portfolio_evidence(lane["portfolio_state"]),
            "fee_rate": _json_copy(lane["fee_rate"]),
            "slippage_bps": _json_copy(lane["slippage_bps"]),
        }
        result = run_automated_signal_pipeline(
            dataset=lane["dataset"], qualification=qualification, regime=lane["regime"],
            decision=decision, risk_state=lane["risk_state"], risk_policy=lane["risk_policy"],
            portfolio_state=lane["portfolio_state"], occurred_at=occurred_at,
            fee_rate=lane["fee_rate"], slippage_bps=lane["slippage_bps"],
        )
        pipeline_results.append(result)
        risk_input = {key: result.signal[key] for key in SIGNAL_KEYS}
        rows.append({
            "family": family,
            "weight": allocation["weight"],
            "portfolio_id": result.state.aggregate_id,
            "signal_id": result.signal["signal_id"],
            "pipeline_input": pipeline_input,
            "risk_input": risk_input,
            "risk_state": dict(lane["risk_state"]),
            "risk_policy": dict(lane["risk_policy"]),
            "risk_decision": _risk_decision_evidence(result.risk_decision),
            "risk_allowed": result.risk_decision.allowed,
            "risk_reason": result.risk_decision.reason_code,
            "execution_status": result.execution.execution_status if result.execution else "BLOCKED",
            "events": [dict(event) for event in result.events],
            "event_digests": [event["event_digest"] for event in result.events],
            "terminal_portfolio": _portfolio_evidence(result.state),
            "paper_only": True,
            "live_trading_authority": False,
        })

    core = {
        "schema_version": RUNTIME_SCHEMA,
        "source_sha": source_sha,
        "selector_inputs": {
            "context": _json_copy(context),
            "candidates": _json_copy(candidates),
            "policy": _json_copy(selector_policy),
        },
        "selection_digest": selection["selection_digest"],
        "selection": selection,
        "occurred_at": occurred_at,
        "lanes": rows,
        "cash_weight": selection["cash_weight"],
        "paper_only": True,
        "live_trading_authority": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
    }
    evidence = {**core, "runtime_digest": _digest(core)}
    return RegimeStrategyRuntimeResult(evidence=evidence, pipelines=tuple(pipeline_results))
