"""Deterministic, Paper-only regime-aware strategy selection.

The selector never promotes a strategy, never places an order, and never grants
Live authority.  It converts an independently built cross-timeframe context and
immutable strategy health/lifecycle records into a bounded allocation proposal.
Deterministic Risk remains the final authority for every Paper action.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence


SELECTION_SCHEMA = "nexus.regime-strategy-selection.v1"
POLICY_SCHEMA = "nexus.regime-strategy-policy.v1"
CONTEXT_SCHEMA = "nexus.phase7-cross-timeframe-context.v1"
ALLOWED_ALIGNMENTS = {"TREND_UP", "TREND_DOWN", "RANGE", "HIGH_VOLATILITY", "MIXED"}
ALLOWED_TIMEFRAMES = {"15m", "1h", "4h"}
TIMEFRAME_ORDER = {"15m": 0, "1h": 1, "4h": 2}
ALLOWED_REGIMES = {"TREND_UP", "TREND_DOWN", "HIGH_VOLATILITY", "RANGE"}
ALLOWED_LIQUIDITY = {"THIN", "NORMAL", "ACTIVE"}
ALLOWED_LIFECYCLE = {"CANDIDATE", "PAPER", "REJECTED", "QUARANTINED"}
ALLOWED_HEALTH = {"HEALTHY", "WATCH", "DEGRADED", "QUARANTINED"}
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_Q = Decimal("0.000001")

_CONTEXT_KEYS = {
    "schema_version", "context_version", "as_of_ms", "instrument", "source",
    "paper_only", "lookahead_control", "alignment", "confidence", "reason_codes",
    "timeframes", "context_sha256",
}
_TIMEFRAME_KEYS = {
    "timeframe", "open_time_ms", "available_at_ms", "regime", "confidence",
    "liquidity_state", "reason_codes", "dataset_binding_sha256",
    "regime_evidence_sha256",
}
_CANDIDATE_KEYS = {
    "family", "strategy_id", "strategy_version", "lifecycle_state", "health_state",
    "record_digest", "health_digest", "paper_only", "live_trading_authority",
}
_POLICY_KEYS = {
    "schema_version", "paper_only", "live_trading_authority",
    "automatic_strategy_promotion", "deterministic_risk_final_authority",
    "minimum_context_confidence", "watch_weight_multiplier",
    "preserve_cash_alignments", "preserve_cash_liquidity_states",
    "approved_families", "alignment_weights",
}


class RegimeStrategySelectorError(ValueError):
    """Raised when strategy selection cannot be proven safe and deterministic."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RegimeStrategySelectorError("selection evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SHA_RE.fullmatch(value):
        raise RegimeStrategySelectorError(f"{field} must be a SHA-256 digest")
    return value


def _text(value: Any, field: str, *, limit: int = 128) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise RegimeStrategySelectorError(f"{field} must be bounded non-empty text")
    return value


def _decimal(value: Any, field: str) -> Decimal:
    if not isinstance(value, str):
        raise RegimeStrategySelectorError(f"{field} must use canonical decimal text")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise RegimeStrategySelectorError(f"{field} is not a decimal") from exc
    if not number.is_finite():
        raise RegimeStrategySelectorError(f"{field} must be finite")
    return number


def _unit(value: Any, field: str) -> Decimal:
    number = _decimal(value, field)
    if number < 0 or number > 1:
        raise RegimeStrategySelectorError(f"{field} must be between 0 and 1")
    return number


def _weight_text(value: Decimal) -> str:
    return format(value.quantize(_Q), "f")


def validate_context(context: Any) -> dict[str, Any]:
    if not isinstance(context, Mapping) or set(context) != _CONTEXT_KEYS:
        raise RegimeStrategySelectorError("cross-timeframe context schema mismatch")
    if context["schema_version"] != CONTEXT_SCHEMA:
        raise RegimeStrategySelectorError("unsupported cross-timeframe context schema")
    if context["paper_only"] is not True or context["lookahead_control"] is not True:
        raise RegimeStrategySelectorError("context exceeds Paper or lookahead authority")
    if context["alignment"] not in ALLOWED_ALIGNMENTS:
        raise RegimeStrategySelectorError("unsupported cross-timeframe alignment")
    _unit(context["confidence"], "context.confidence")
    if isinstance(context["as_of_ms"], bool) or not isinstance(context["as_of_ms"], int):
        raise RegimeStrategySelectorError("context.as_of_ms must be an integer")
    _text(context["instrument"], "context.instrument")
    _text(context["source"], "context.source")
    if not isinstance(context["reason_codes"], list):
        raise RegimeStrategySelectorError("context.reason_codes must be a list")
    rows = context["timeframes"]
    if not isinstance(rows, list) or not 2 <= len(rows) <= 3:
        raise RegimeStrategySelectorError("context requires two or three timeframes")
    seen: set[str] = set()
    last_order = -1
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or set(row) != _TIMEFRAME_KEYS:
            raise RegimeStrategySelectorError("context timeframe schema mismatch")
        timeframe = row["timeframe"]
        if timeframe not in ALLOWED_TIMEFRAMES or timeframe in seen:
            raise RegimeStrategySelectorError("unsupported or duplicate context timeframe")
        order = TIMEFRAME_ORDER[timeframe]
        if order <= last_order:
            raise RegimeStrategySelectorError("context timeframes are not canonical ordered")
        seen.add(timeframe)
        last_order = order
        if row["regime"] not in ALLOWED_REGIMES:
            raise RegimeStrategySelectorError("unsupported timeframe regime")
        if row["liquidity_state"] not in ALLOWED_LIQUIDITY:
            raise RegimeStrategySelectorError("unsupported liquidity state")
        _unit(row["confidence"], f"context.timeframes[{index}].confidence")
        _sha(row["dataset_binding_sha256"], "dataset_binding_sha256")
        _sha(row["regime_evidence_sha256"], "regime_evidence_sha256")
        if not isinstance(row["reason_codes"], list):
            raise RegimeStrategySelectorError("timeframe reason_codes must be a list")
        for field in ("open_time_ms", "available_at_ms"):
            if isinstance(row[field], bool) or not isinstance(row[field], int) or row[field] < 0:
                raise RegimeStrategySelectorError(f"timeframe {field} must be non-negative")
        if row["available_at_ms"] > context["as_of_ms"]:
            raise RegimeStrategySelectorError("context contains future-bearing evidence")
    unsigned = dict(context)
    claimed = _sha(unsigned.pop("context_sha256"), "context.context_sha256")
    if _digest(unsigned) != claimed:
        raise RegimeStrategySelectorError("cross-timeframe context digest mismatch")
    return dict(context)


def validate_policy(policy: Any) -> dict[str, Any]:
    if not isinstance(policy, Mapping) or set(policy) != _POLICY_KEYS:
        raise RegimeStrategySelectorError("strategy selection policy schema mismatch")
    if policy["schema_version"] != POLICY_SCHEMA:
        raise RegimeStrategySelectorError("unsupported strategy selection policy")
    if (
        policy["paper_only"] is not True
        or policy["live_trading_authority"] is not False
        or policy["automatic_strategy_promotion"] is not False
        or policy["deterministic_risk_final_authority"] is not True
    ):
        raise RegimeStrategySelectorError("strategy selection policy widens authority")
    _unit(policy["minimum_context_confidence"], "minimum_context_confidence")
    _unit(policy["watch_weight_multiplier"], "watch_weight_multiplier")
    families = policy["approved_families"]
    if not isinstance(families, list) or not families or len(set(families)) != len(families):
        raise RegimeStrategySelectorError("approved_families must be unique and non-empty")
    for family in families:
        _text(family, "approved family", limit=80)
    preserve_alignments = policy["preserve_cash_alignments"]
    if not isinstance(preserve_alignments, list) or any(
        value not in ALLOWED_ALIGNMENTS for value in preserve_alignments
    ):
        raise RegimeStrategySelectorError("invalid preserve-cash alignment")
    preserve_liquidity = policy["preserve_cash_liquidity_states"]
    if not isinstance(preserve_liquidity, list) or any(
        value not in ALLOWED_LIQUIDITY for value in preserve_liquidity
    ):
        raise RegimeStrategySelectorError("invalid preserve-cash liquidity state")
    weights = policy["alignment_weights"]
    if not isinstance(weights, Mapping) or set(weights) != ALLOWED_ALIGNMENTS:
        raise RegimeStrategySelectorError("alignment_weights must cover every alignment")
    approved = set(families)
    for alignment, row in weights.items():
        if not isinstance(row, Mapping) or any(family not in approved for family in row):
            raise RegimeStrategySelectorError(f"{alignment} contains an unapproved family")
        total = sum((_unit(value, f"{alignment}.{family}") for family, value in row.items()), Decimal(0))
        if total > 1:
            raise RegimeStrategySelectorError(f"{alignment} weights exceed one")
        if alignment in preserve_alignments and total != 0:
            raise RegimeStrategySelectorError("preserve-cash alignments must allocate zero")
    return dict(policy)


def _validate_candidates(
    candidates: Sequence[Mapping[str, Any]], approved_families: set[str]
) -> dict[str, dict[str, Any]]:
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
        raise RegimeStrategySelectorError("candidates must be a sequence")
    result: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        if not isinstance(candidate, Mapping) or set(candidate) != _CANDIDATE_KEYS:
            raise RegimeStrategySelectorError("candidate schema mismatch")
        family = _text(candidate["family"], "candidate.family", limit=80)
        if family not in approved_families:
            raise RegimeStrategySelectorError("candidate family is not policy approved")
        if family in result:
            raise RegimeStrategySelectorError("duplicate candidate family is ambiguous")
        _text(candidate["strategy_id"], "candidate.strategy_id")
        _text(candidate["strategy_version"], "candidate.strategy_version")
        if candidate["lifecycle_state"] not in ALLOWED_LIFECYCLE:
            raise RegimeStrategySelectorError("unsupported candidate lifecycle state")
        if candidate["health_state"] not in ALLOWED_HEALTH:
            raise RegimeStrategySelectorError("unsupported candidate health state")
        _sha(candidate["record_digest"], "candidate.record_digest")
        _sha(candidate["health_digest"], "candidate.health_digest")
        if candidate["paper_only"] is not True or candidate["live_trading_authority"] is not False:
            raise RegimeStrategySelectorError("candidate exceeds Paper authority")
        result[family] = dict(candidate)
    return result


def select_strategy_mix(
    *,
    context: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    policy: Mapping[str, Any],
    source_sha: str,
) -> dict[str, Any]:
    """Return a digest-bound allocation proposal; never execute or promote it."""
    context = validate_context(context)
    policy = validate_policy(policy)
    source_sha = str(source_sha).strip().lower()
    if not _GIT_SHA_RE.fullmatch(source_sha):
        raise RegimeStrategySelectorError("source_sha must be a 40-character Git SHA")
    approved = set(policy["approved_families"])
    rows = _validate_candidates(candidates, approved)
    alignment = context["alignment"]
    reasons = [f"REGIME_{alignment}"]
    preserve = alignment in set(policy["preserve_cash_alignments"])
    confidence = _unit(context["confidence"], "context.confidence")
    if confidence < _unit(policy["minimum_context_confidence"], "minimum_context_confidence"):
        preserve = True
        reasons.append("CONTEXT_CONFIDENCE_BELOW_POLICY")
    if any(
        row["liquidity_state"] in set(policy["preserve_cash_liquidity_states"])
        for row in context["timeframes"]
    ):
        preserve = True
        reasons.append("LIQUIDITY_PRESERVE_CASH")

    allocations: list[dict[str, Any]] = []
    allocated = Decimal(0)
    target_weights = {} if preserve else policy["alignment_weights"][alignment]
    watch_multiplier = _unit(policy["watch_weight_multiplier"], "watch_weight_multiplier")
    for family in policy["approved_families"]:
        target = _unit(target_weights.get(family, "0"), f"{alignment}.{family}")
        candidate = rows.get(family)
        if target == 0:
            continue
        if candidate is None:
            reasons.append(f"FAMILY_UNAVAILABLE_{family.upper()}")
            continue
        if candidate["lifecycle_state"] != "PAPER":
            reasons.append(f"FAMILY_NOT_PAPER_{family.upper()}")
            continue
        if candidate["health_state"] not in {"HEALTHY", "WATCH"}:
            reasons.append(f"FAMILY_UNHEALTHY_{family.upper()}")
            continue
        weight = target
        if candidate["health_state"] == "WATCH":
            weight *= watch_multiplier
            reasons.append(f"WATCH_HAIRCUT_{family.upper()}")
        if weight <= 0:
            continue
        allocated += weight
        allocations.append({
            "family": family,
            "strategy_id": candidate["strategy_id"],
            "strategy_version": candidate["strategy_version"],
            "weight": _weight_text(weight),
            "lifecycle_state": candidate["lifecycle_state"],
            "health_state": candidate["health_state"],
            "record_digest": candidate["record_digest"],
            "health_digest": candidate["health_digest"],
        })
    if allocated > 1:
        raise RegimeStrategySelectorError("selected strategy allocation exceeds one")
    cash = Decimal(1) - allocated
    if not allocations:
        reasons.append("NO_ELIGIBLE_ACTIVE_STRATEGY")
    core = {
        "schema_version": SELECTION_SCHEMA,
        "source_sha": source_sha,
        "policy_sha256": _digest(policy),
        "context_sha256": context["context_sha256"],
        "as_of_ms": context["as_of_ms"],
        "instrument": context["instrument"],
        "alignment": alignment,
        "mode": "ACTIVE" if allocations else "PRESERVE_CASH",
        "allocations": allocations,
        "cash_weight": _weight_text(cash),
        "reason_codes": list(dict.fromkeys(reasons)),
        "paper_only": True,
        "live_trading_authority": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
    }
    return {**core, "selection_digest": _digest(core)}

