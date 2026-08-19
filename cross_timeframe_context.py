from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

from data_intelligence import FEATURE_VERSION, SCHEMA_VERSION as REGIME_SCHEMA_VERSION, TAXONOMY_VERSION


CONTEXT_SCHEMA_VERSION = "nexus.phase7-cross-timeframe-context.v1"
CONTEXT_VERSION = "nexus.cross-timeframe-context.v1"
TIMEFRAME_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}
TIMEFRAME_ORDER = {"15m": 0, "1h": 1, "4h": 2}
MAX_STALE_MULTIPLIER = 2
ALLOWED_REGIMES = {"TREND_UP", "TREND_DOWN", "HIGH_VOLATILITY", "RANGE"}
ALLOWED_LIQUIDITY = {"THIN", "NORMAL", "ACTIVE"}
REGIME_EVIDENCE_KEYS = {
    "schema_version",
    "feature_version",
    "taxonomy_version",
    "dataset_binding_sha256",
    "instrument",
    "timeframe",
    "source",
    "finality",
    "paper_only",
    "lookahead_control",
    "records",
    "current_regime",
    "evidence_sha256",
}
REGIME_RECORD_KEYS = {
    "open_time_ms",
    "regime",
    "confidence",
    "reason_codes",
    "liquidity_state",
    "features",
}
FEATURE_KEYS = {
    "return_5",
    "return_20",
    "mean_abs_return_20",
    "mean_range_pct_20",
    "volume_ratio_20",
}


class CrossTimeframeContextError(ValueError):
    pass


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CrossTimeframeContextError("cross-timeframe evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise CrossTimeframeContextError(f"{field} must be a SHA-256 digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise CrossTimeframeContextError(f"{field} must be hexadecimal") from exc
    return value.lower()


def _bounded_text(value: Any, field: str, *, limit: int = 128) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise CrossTimeframeContextError(f"{field} must be a bounded non-empty string")
    return value


def _decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, float):
        raise CrossTimeframeContextError(f"{field} must not use binary floating point")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CrossTimeframeContextError(f"{field} is not a valid decimal") from exc
    if not parsed.is_finite():
        raise CrossTimeframeContextError(f"{field} must be finite")
    return parsed


def _validate_record(record: Any, *, previous_open_time_ms: int | None = None) -> dict[str, Any]:
    if not isinstance(record, Mapping) or set(record) != REGIME_RECORD_KEYS:
        raise CrossTimeframeContextError("regime record schema mismatch")
    open_time_ms = record["open_time_ms"]
    if isinstance(open_time_ms, bool) or not isinstance(open_time_ms, int) or open_time_ms < 0:
        raise CrossTimeframeContextError("regime record open_time_ms must be a non-negative integer")
    if previous_open_time_ms is not None and open_time_ms <= previous_open_time_ms:
        raise CrossTimeframeContextError("regime records must be strictly time ordered")
    regime = record["regime"]
    if regime not in ALLOWED_REGIMES:
        raise CrossTimeframeContextError("unsupported regime")
    confidence = _decimal(record["confidence"], "confidence")
    if confidence < 0 or confidence > 1:
        raise CrossTimeframeContextError("confidence must be between 0 and 1")
    liquidity = record["liquidity_state"]
    if liquidity not in ALLOWED_LIQUIDITY:
        raise CrossTimeframeContextError("unsupported liquidity state")
    reasons = record["reason_codes"]
    if (
        not isinstance(reasons, list)
        or not reasons
        or len(reasons) > 16
        or any(not isinstance(reason, str) or not reason or len(reason) > 128 for reason in reasons)
    ):
        raise CrossTimeframeContextError("reason_codes must be a bounded non-empty list")
    features = record["features"]
    if not isinstance(features, Mapping) or set(features) != FEATURE_KEYS:
        raise CrossTimeframeContextError("regime feature schema mismatch")
    for field in sorted(FEATURE_KEYS):
        if not isinstance(features[field], str):
            raise CrossTimeframeContextError(f"features.{field} must use canonical decimal text")
        _decimal(features[field], f"features.{field}")
    return dict(record)


def validate_regime_evidence(evidence: Any) -> dict[str, Any]:
    if not isinstance(evidence, Mapping) or set(evidence) != REGIME_EVIDENCE_KEYS:
        raise CrossTimeframeContextError("regime evidence schema mismatch")
    if evidence["schema_version"] != REGIME_SCHEMA_VERSION:
        raise CrossTimeframeContextError("unsupported regime evidence schema")
    if evidence["feature_version"] != FEATURE_VERSION or evidence["taxonomy_version"] != TAXONOMY_VERSION:
        raise CrossTimeframeContextError("unsupported feature or taxonomy version")
    timeframe = evidence["timeframe"]
    if timeframe not in TIMEFRAME_MS:
        raise CrossTimeframeContextError("unsupported canonical timeframe")
    _bounded_text(evidence["instrument"], "instrument")
    _bounded_text(evidence["source"], "source")
    if evidence["finality"] != "closed_only":
        raise CrossTimeframeContextError("cross-timeframe context requires closed-only evidence")
    if evidence["paper_only"] is not True or evidence["lookahead_control"] is not True:
        raise CrossTimeframeContextError("regime evidence is not eligible for bounded Paper context")
    _sha256(evidence["dataset_binding_sha256"], "dataset_binding_sha256")
    records = evidence["records"]
    if not isinstance(records, list) or not records:
        raise CrossTimeframeContextError("regime evidence records must be non-empty")
    previous: int | None = None
    validated_records: list[dict[str, Any]] = []
    for record in records:
        validated = _validate_record(record, previous_open_time_ms=previous)
        previous = validated["open_time_ms"]
        validated_records.append(validated)
    if evidence["current_regime"] != validated_records[-1]:
        raise CrossTimeframeContextError("current_regime is not the final regime record")
    claimed = _sha256(evidence["evidence_sha256"], "evidence_sha256")
    core = dict(evidence)
    core.pop("evidence_sha256")
    if _digest(core) != claimed:
        raise CrossTimeframeContextError("regime evidence digest mismatch")
    return dict(evidence)


def _alignment(regimes: Sequence[str]) -> tuple[str, list[str]]:
    if any(regime == "HIGH_VOLATILITY" for regime in regimes):
        return "VOLATILITY_ALERT", ["MTF_VOLATILITY_ALERT"]
    if all(regime == "TREND_UP" for regime in regimes):
        return "ALIGNED_UP", ["MTF_DIRECTION_UP_ALIGNED"]
    if all(regime == "TREND_DOWN" for regime in regimes):
        return "ALIGNED_DOWN", ["MTF_DIRECTION_DOWN_ALIGNED"]
    if all(regime == "RANGE" for regime in regimes):
        return "RANGE_DOMINANT", ["MTF_RANGE_ALIGNED"]
    return "MIXED", ["MTF_MIXED_REGIMES"]


def build_cross_timeframe_context(
    evidences: Sequence[Mapping[str, Any]], *, as_of_ms: int
) -> dict[str, Any]:
    """Build deterministic point-in-time context from 2-3 canonical regime snapshots.

    Evidence is eligible only after its current candle has closed: the record stores
    candle open time, so availability is ``open_time_ms + timeframe_ms``. An artifact
    whose current candle closes after ``as_of_ms`` is rejected instead of backselecting
    an older record from a future-bearing artifact.
    """
    if isinstance(as_of_ms, bool) or not isinstance(as_of_ms, int) or as_of_ms < 0:
        raise CrossTimeframeContextError("as_of_ms must be a non-negative integer")
    if not isinstance(evidences, Sequence) or isinstance(evidences, (str, bytes)):
        raise CrossTimeframeContextError("evidences must be a bounded sequence")
    if len(evidences) < 2 or len(evidences) > 3:
        raise CrossTimeframeContextError("cross-timeframe context requires 2 or 3 evidences")

    validated = [validate_regime_evidence(evidence) for evidence in evidences]
    timeframes = [evidence["timeframe"] for evidence in validated]
    if len(set(timeframes)) != len(timeframes):
        raise CrossTimeframeContextError("duplicate timeframe evidence is ambiguous")
    instruments = {evidence["instrument"] for evidence in validated}
    sources = {evidence["source"] for evidence in validated}
    if len(instruments) != 1 or len(sources) != 1:
        raise CrossTimeframeContextError("cross-timeframe evidence namespace mismatch")

    selected: list[dict[str, Any]] = []
    for evidence in validated:
        current = evidence["current_regime"]
        timeframe_ms = TIMEFRAME_MS[evidence["timeframe"]]
        open_time_ms = current["open_time_ms"]
        available_at_ms = open_time_ms + timeframe_ms
        if available_at_ms > as_of_ms:
            raise CrossTimeframeContextError("future-bearing regime evidence is not eligible at as_of_ms")
        age_ms = as_of_ms - available_at_ms
        max_age_ms = timeframe_ms * MAX_STALE_MULTIPLIER
        if age_ms > max_age_ms:
            raise CrossTimeframeContextError("stale regime evidence is not eligible")
        selected.append(
            {
                "timeframe": evidence["timeframe"],
                "open_time_ms": open_time_ms,
                "available_at_ms": available_at_ms,
                "regime": current["regime"],
                "confidence": current["confidence"],
                "liquidity_state": current["liquidity_state"],
                "reason_codes": list(current["reason_codes"]),
                "dataset_binding_sha256": evidence["dataset_binding_sha256"],
                "regime_evidence_sha256": evidence["evidence_sha256"],
            }
        )
    selected.sort(key=lambda item: TIMEFRAME_ORDER[item["timeframe"]])
    alignment, reasons = _alignment([item["regime"] for item in selected])
    confidence = min(_decimal(item["confidence"], "confidence") for item in selected)
    core = {
        "schema_version": CONTEXT_SCHEMA_VERSION,
        "context_version": CONTEXT_VERSION,
        "as_of_ms": as_of_ms,
        "instrument": next(iter(instruments)),
        "source": next(iter(sources)),
        "paper_only": True,
        "lookahead_control": True,
        "alignment": alignment,
        "confidence": str(confidence),
        "reason_codes": reasons,
        "timeframes": selected,
    }
    return {**core, "context_sha256": _digest(core)}
