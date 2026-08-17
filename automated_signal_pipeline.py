from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from deterministic_risk import RiskDecision, evaluate_risk
from paper_event_store import PortfolioState, build_event, replay
from paper_execution import PaperExecutionResult, execute_paper_command

DATASET_KEYS = {
    "dataset_id", "dataset_revision", "source_id", "source_timestamp",
    "received_timestamp", "symbol", "timeframe", "readiness_status",
    "provenance_digest",
}
QUALIFICATION_KEYS = {
    "artifact_id", "artifact_digest", "strategy_id", "strategy_version",
    "dataset_id", "dataset_revision", "status", "qualified_at",
}
REGIME_KEYS = {
    "regime_id", "regime_version", "label", "confidence", "source_timestamp",
    "dataset_id", "dataset_revision", "symbol", "timeframe",
}
DECISION_KEYS = {
    "decision_id", "operation", "side", "quantity", "reference_price",
    "stop_price", "target_price", "confidence", "strategy_id",
    "strategy_version", "dataset_id", "dataset_revision", "regime_id",
    "regime_version", "symbol", "timeframe", "source_timestamp",
    "correlation_id", "causation_id", "risk_policy_version",
}
PAPER_ELIGIBLE_STATUSES = {"paper_eligible", "paper_active"}
SUPPORTED_TIMEFRAMES = {"minute15", "hour1", "hour4"}


class AutomatedSignalPipelineError(ValueError):
    pass


@dataclass(frozen=True)
class PipelineResult:
    signal: Mapping[str, Any]
    risk_decision: RiskDecision
    events: tuple[dict[str, Any], ...]
    state: PortfolioState
    execution: PaperExecutionResult | None


def _exact(value: Any, keys: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise AutomatedSignalPipelineError(f"{name} schema mismatch")
    return value


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise AutomatedSignalPipelineError(f"{field} must be a non-empty bounded string")
    return value


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise AutomatedSignalPipelineError(f"{field} must be a SHA-256 digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise AutomatedSignalPipelineError(f"{field} must be hexadecimal") from exc
    return value.lower()


def _utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise AutomatedSignalPipelineError(f"{field} must be UTC ISO-8601")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AutomatedSignalPipelineError(f"{field} must be UTC ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise AutomatedSignalPipelineError(f"{field} must be UTC")
    return parsed.astimezone(timezone.utc)


def _decimal(value: Any, field: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, float):
        raise AutomatedSignalPipelineError(f"{field} must not use binary floating point")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AutomatedSignalPipelineError(f"{field} is not a valid decimal") from exc
    if not result.is_finite():
        raise AutomatedSignalPipelineError(f"{field} must be finite")
    if positive and result <= 0:
        raise AutomatedSignalPipelineError(f"{field} must be positive")
    return result


def _bounded_confidence(value: Any, field: str) -> Decimal:
    confidence = _decimal(value, field)
    if confidence < 0 or confidence > 1:
        raise AutomatedSignalPipelineError(f"{field} must be between 0 and 1")
    return confidence


def _canonical_digest(value: Mapping[str, Any]) -> str:
    try:
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AutomatedSignalPipelineError("signal bindings are not canonical") from exc
    return hashlib.sha256(payload).hexdigest()


def _validate_bindings(
    *,
    dataset: Mapping[str, Any],
    qualification: Mapping[str, Any],
    regime: Mapping[str, Any],
    decision: Mapping[str, Any],
    risk_policy: Mapping[str, Any],
    occurred_at: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    dataset = dict(_exact(dataset, DATASET_KEYS, "dataset"))
    qualification = dict(_exact(qualification, QUALIFICATION_KEYS, "qualification"))
    regime = dict(_exact(regime, REGIME_KEYS, "regime"))
    decision = dict(_exact(decision, DECISION_KEYS, "decision"))

    for field in ("dataset_id", "dataset_revision", "source_id", "symbol"):
        _identifier(dataset[field], f"dataset.{field}")
    if dataset["timeframe"] not in SUPPORTED_TIMEFRAMES:
        raise AutomatedSignalPipelineError("dataset timeframe is unsupported")
    if dataset["readiness_status"] != "ready":
        raise AutomatedSignalPipelineError("dataset is not ready")
    _digest(dataset["provenance_digest"], "dataset.provenance_digest")
    source_time = _utc(dataset["source_timestamp"], "dataset.source_timestamp")
    received_time = _utc(dataset["received_timestamp"], "dataset.received_timestamp")
    occurred = _utc(occurred_at, "occurred_at")
    if not source_time <= received_time <= occurred:
        raise AutomatedSignalPipelineError("dataset timestamps are not causally ordered")

    for field in ("artifact_id", "strategy_id", "strategy_version", "dataset_id", "dataset_revision"):
        _identifier(qualification[field], f"qualification.{field}")
    _digest(qualification["artifact_digest"], "qualification.artifact_digest")
    _utc(qualification["qualified_at"], "qualification.qualified_at")
    if qualification["status"] not in PAPER_ELIGIBLE_STATUSES:
        raise AutomatedSignalPipelineError("strategy is not paper eligible")
    if qualification["dataset_id"] != dataset["dataset_id"] or qualification["dataset_revision"] != dataset["dataset_revision"]:
        raise AutomatedSignalPipelineError("qualification dataset binding mismatch")

    for field in ("regime_id", "regime_version", "label", "dataset_id", "dataset_revision", "symbol"):
        _identifier(regime[field], f"regime.{field}")
    _bounded_confidence(regime["confidence"], "regime.confidence")
    _utc(regime["source_timestamp"], "regime.source_timestamp")
    if (
        regime["dataset_id"] != dataset["dataset_id"]
        or regime["dataset_revision"] != dataset["dataset_revision"]
        or regime["symbol"] != dataset["symbol"]
        or regime["timeframe"] != dataset["timeframe"]
    ):
        raise AutomatedSignalPipelineError("regime dataset binding mismatch")

    for field in (
        "decision_id", "strategy_id", "strategy_version", "dataset_id", "dataset_revision",
        "regime_id", "regime_version", "symbol", "correlation_id", "causation_id",
        "risk_policy_version",
    ):
        _identifier(decision[field], f"decision.{field}")
    if decision["operation"] != "open":
        raise AutomatedSignalPipelineError("automated Gate 9 pipeline only authorizes paper open proposals")
    if decision["side"] not in {"long", "short"}:
        raise AutomatedSignalPipelineError("decision side is unsupported")
    for field in ("quantity", "reference_price", "stop_price", "target_price"):
        _decimal(decision[field], f"decision.{field}", positive=True)
    _bounded_confidence(decision["confidence"], "decision.confidence")
    _utc(decision["source_timestamp"], "decision.source_timestamp")
    if (
        decision["strategy_id"] != qualification["strategy_id"]
        or decision["strategy_version"] != qualification["strategy_version"]
    ):
        raise AutomatedSignalPipelineError("decision strategy binding mismatch")
    if (
        decision["dataset_id"] != dataset["dataset_id"]
        or decision["dataset_revision"] != dataset["dataset_revision"]
        or decision["symbol"] != dataset["symbol"]
        or decision["timeframe"] != dataset["timeframe"]
    ):
        raise AutomatedSignalPipelineError("decision dataset binding mismatch")
    if decision["regime_id"] != regime["regime_id"] or decision["regime_version"] != regime["regime_version"]:
        raise AutomatedSignalPipelineError("decision regime binding mismatch")
    if decision["causation_id"] != regime["regime_id"]:
        raise AutomatedSignalPipelineError("decision causation must bind the regime decision context")
    if decision["source_timestamp"] != dataset["source_timestamp"]:
        raise AutomatedSignalPipelineError("decision source timestamp must bind the ready dataset")
    if not isinstance(risk_policy, Mapping) or decision["risk_policy_version"] != risk_policy.get("policy_version"):
        raise AutomatedSignalPipelineError("decision risk policy binding mismatch")

    return dataset, qualification, regime, decision


def run_automated_signal_pipeline(
    *,
    dataset: Mapping[str, Any],
    qualification: Mapping[str, Any],
    regime: Mapping[str, Any],
    decision: Mapping[str, Any],
    risk_state: Mapping[str, Any],
    risk_policy: Mapping[str, Any],
    portfolio_state: PortfolioState,
    occurred_at: str,
    fee_rate: Any = "0.001",
    slippage_bps: Any = "0",
) -> PipelineResult:
    """Run the Gate 9 deterministic paper path without granting execution authority upstream."""

    dataset, qualification, regime, decision = _validate_bindings(
        dataset=dataset,
        qualification=qualification,
        regime=regime,
        decision=decision,
        risk_policy=risk_policy,
        occurred_at=occurred_at,
    )
    _decimal(fee_rate, "fee_rate")
    _decimal(slippage_bps, "slippage_bps")
    if not isinstance(portfolio_state, PortfolioState):
        raise AutomatedSignalPipelineError("portfolio_state must be a validated PortfolioState")

    signal_core = {
        "symbol": dataset["symbol"],
        "timeframe": dataset["timeframe"],
        "strategy_id": qualification["strategy_id"],
        "strategy_version": qualification["strategy_version"],
        "qualification_artifact_id": qualification["artifact_id"],
        "qualification_artifact_digest": qualification["artifact_digest"],
        "dataset_id": dataset["dataset_id"],
        "dataset_revision": dataset["dataset_revision"],
        "source_id": dataset["source_id"],
        "dataset_provenance_digest": dataset["provenance_digest"],
        "source_timestamp": dataset["source_timestamp"],
        "received_timestamp": dataset["received_timestamp"],
        "regime_id": regime["regime_id"],
        "regime_version": regime["regime_version"],
        "regime_label": regime["label"],
        "regime_confidence": str(_bounded_confidence(regime["confidence"], "regime.confidence")),
        "decision_id": decision["decision_id"],
        "operation": decision["operation"],
        "side": decision["side"],
        "quantity": str(_decimal(decision["quantity"], "decision.quantity", positive=True)),
        "reference_price": str(_decimal(decision["reference_price"], "decision.reference_price", positive=True)),
        "stop_price": str(_decimal(decision["stop_price"], "decision.stop_price", positive=True)),
        "target_price": str(_decimal(decision["target_price"], "decision.target_price", positive=True)),
        "confidence": str(_bounded_confidence(decision["confidence"], "decision.confidence")),
        "risk_policy_version": decision["risk_policy_version"],
        "correlation_id": decision["correlation_id"],
        "causation_id": decision["decision_id"],
        "provenance_kind": "automatic",
        "paper_trading_only": True,
    }
    signal_id = f"sig-{_canonical_digest(signal_core)[:40]}"
    signal = {"signal_id": signal_id, **signal_core}

    provenance = {
        "kind": "automatic",
        "source_id": dataset["source_id"],
        "source_timestamp": dataset["source_timestamp"],
        "received_timestamp": dataset["received_timestamp"],
        "timeframe": dataset["timeframe"],
        "confidence": signal["confidence"],
        "strategy_version": signal["strategy_version"],
        "policy_version": signal["risk_policy_version"],
    }
    signal_event = build_event(
        event_id=f"{signal_id}:signal",
        event_type="signal_recorded",
        aggregate_id=portfolio_state.aggregate_id or "paper-account",
        sequence=portfolio_state.last_sequence + 1,
        occurred_at=occurred_at,
        correlation_id=signal["correlation_id"],
        causation_id=signal["decision_id"],
        provenance=provenance,
        previous_event_digest=portfolio_state.last_event_digest,
        payload={
            "symbol": signal["symbol"],
            "timeframe": signal["timeframe"],
            "side": signal["side"],
            "quantity": signal["quantity"],
            "reference_price": signal["reference_price"],
        },
    )
    signal_state = replay([signal_event], previous_valid=portfolio_state).state

    risk_input = {
        "signal_id": signal_id,
        "symbol": signal["symbol"],
        "timeframe": signal["timeframe"],
        "strategy_id": signal["strategy_id"],
        "strategy_version": signal["strategy_version"],
        "side": signal["side"],
        "quantity": signal["quantity"],
        "reference_price": signal["reference_price"],
        "stop_price": signal["stop_price"],
        "target_price": signal["target_price"],
        "source_timestamp": signal["source_timestamp"],
        "correlation_id": signal["correlation_id"],
        "causation_id": signal["decision_id"],
        "provenance_kind": "automatic",
    }
    risk_decision = evaluate_risk(risk_input, risk_state, risk_policy, evaluated_at=occurred_at)

    if not risk_decision.allowed:
        rejection = build_event(
            event_id=f"{signal_id}:risk-rejected",
            event_type="risk_rejection_recorded",
            aggregate_id=signal_state.aggregate_id or "paper-account",
            sequence=signal_state.last_sequence + 1,
            occurred_at=occurred_at,
            correlation_id=signal["correlation_id"],
            causation_id=signal_id,
            provenance=provenance,
            previous_event_digest=signal_state.last_event_digest,
            payload={"reason_code": risk_decision.reason_code},
        )
        rejected_state = replay([rejection], previous_valid=signal_state).state
        return PipelineResult(
            signal=signal,
            risk_decision=risk_decision,
            events=(signal_event, rejection),
            state=rejected_state,
            execution=None,
        )

    execution = execute_paper_command(
        command={
            "operation": signal["operation"],
            "symbol": signal["symbol"],
            "side": signal["side"],
            "quantity": signal["quantity"],
            "reference_price": signal["reference_price"],
            "stop_price": signal["stop_price"],
            "target_price": signal["target_price"],
            "fee_rate": str(_decimal(fee_rate, "fee_rate")),
            "slippage_bps": str(_decimal(slippage_bps, "slippage_bps")),
            "currency": signal_state.currency,
        },
        state=signal_state,
        risk_decision=risk_decision,
        occurred_at=occurred_at,
        provenance=provenance,
        correlation_id=signal["correlation_id"],
        causation_id=signal_id,
    )
    return PipelineResult(
        signal=signal,
        risk_decision=risk_decision,
        events=(signal_event, *execution.events),
        state=execution.state,
        execution=execution,
    )
