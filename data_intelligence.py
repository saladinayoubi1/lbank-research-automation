from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from typing import Any, Mapping

from phase5_data_binding import CanonicalDataError, validate_canonical_dataset


SCHEMA_VERSION = "nexus.phase7-data-intelligence.v1"
FEATURE_VERSION = "nexus.features.market-core.v1"
TAXONOMY_VERSION = "nexus.regime-taxonomy.v1"
MIN_ROWS = 21
TREND_RETURN_20 = Decimal("0.03")
HIGH_VOL_20 = Decimal("0.015")
HIGH_RANGE_20 = Decimal("0.025")
THIN_LIQUIDITY_RATIO = Decimal("0.50")
ACTIVE_LIQUIDITY_RATIO = Decimal("1.50")
Q8 = Decimal("0.00000001")
Q6 = Decimal("0.000001")


class DataIntelligenceError(ValueError):
    pass


def _decimal(value: Any, field: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, float):
        value = repr(value)
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise DataIntelligenceError(f"{field} is not a valid decimal") from exc
    if not result.is_finite():
        raise DataIntelligenceError(f"{field} must be finite")
    if positive and result <= 0:
        raise DataIntelligenceError(f"{field} must be positive")
    return result


def _q8(value: Decimal) -> Decimal:
    return value.quantize(Q8, rounding=ROUND_HALF_EVEN)


def _q6(value: Decimal) -> Decimal:
    return value.quantize(Q6, rounding=ROUND_HALF_EVEN)


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
        raise DataIntelligenceError("intelligence evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _ratio(numerator: Decimal, denominator: Decimal, field: str) -> Decimal:
    if denominator <= 0:
        raise DataIntelligenceError(f"{field} denominator must be positive")
    return _q8(numerator / denominator)


def _confidence(regime: str, slow_return: Decimal, volatility: Decimal, range_pct: Decimal) -> Decimal:
    if regime in {"TREND_UP", "TREND_DOWN"}:
        strength = min(Decimal("1"), abs(slow_return) / Decimal("0.10"))
        return _q6(max(Decimal("0.50"), strength))
    if regime == "HIGH_VOLATILITY":
        vol_strength = max(volatility / Decimal("0.05"), range_pct / Decimal("0.08"))
        return _q6(max(Decimal("0.50"), min(Decimal("1"), vol_strength)))
    return Decimal("0.600000")


def _liquidity_state(volume_ratio: Decimal) -> str:
    if volume_ratio < THIN_LIQUIDITY_RATIO:
        return "THIN"
    if volume_ratio > ACTIVE_LIQUIDITY_RATIO:
        return "ACTIVE"
    return "NORMAL"


def _classify(
    *,
    fast_return: Decimal,
    slow_return: Decimal,
    volatility: Decimal,
    range_pct: Decimal,
    liquidity: str,
) -> tuple[str, tuple[str, ...]]:
    reasons: list[str] = []
    if volatility >= HIGH_VOL_20 or range_pct >= HIGH_RANGE_20:
        regime = "HIGH_VOLATILITY"
        reasons.append("VOLATILITY_THRESHOLD")
    elif slow_return >= TREND_RETURN_20 and fast_return > 0:
        regime = "TREND_UP"
        reasons.append("POSITIVE_20_BAR_STRUCTURE")
    elif slow_return <= -TREND_RETURN_20 and fast_return < 0:
        regime = "TREND_DOWN"
        reasons.append("NEGATIVE_20_BAR_STRUCTURE")
    else:
        regime = "RANGE"
        reasons.append("NO_DIRECTIONAL_OR_VOLATILITY_THRESHOLD")
    if liquidity == "THIN":
        reasons.append("THIN_LIQUIDITY")
    elif liquidity == "ACTIVE":
        reasons.append("ACTIVE_LIQUIDITY")
    else:
        reasons.append("NORMAL_LIQUIDITY")
    return regime, tuple(reasons)


def classify_canonical_regimes(dataset: Mapping[str, Any]) -> dict[str, Any]:
    """Build deterministic, no-look-ahead regime evidence from canonical closed candles.

    Every record at index *i* uses only rows ``<= i``. The output binds directly to the
    canonical dataset SHA and is Paper/Research only. No caller-supplied regime labels,
    confidence values or provenance fields are accepted.
    """
    try:
        dataset = validate_canonical_dataset(dataset)
    except CanonicalDataError as exc:
        raise DataIntelligenceError(f"canonical dataset rejected: {exc}") from exc
    rows = dataset["rows"]
    if len(rows) < MIN_ROWS:
        raise DataIntelligenceError(f"at least {MIN_ROWS} canonical rows are required")

    closes = [_decimal(row["close"], f"rows[{i}].close", positive=True) for i, row in enumerate(rows)]
    highs = [_decimal(row["high"], f"rows[{i}].high", positive=True) for i, row in enumerate(rows)]
    lows = [_decimal(row["low"], f"rows[{i}].low", positive=True) for i, row in enumerate(rows)]
    volumes = [_decimal(row["volume"], f"rows[{i}].volume") for i, row in enumerate(rows)]
    if any(volume < 0 for volume in volumes):
        raise DataIntelligenceError("volume must be non-negative")

    records: list[dict[str, Any]] = []
    for i in range(20, len(rows)):
        fast_return = _q8(closes[i] / closes[i - 5] - Decimal("1"))
        slow_return = _q8(closes[i] / closes[i - 20] - Decimal("1"))
        abs_returns = [abs(closes[j] / closes[j - 1] - Decimal("1")) for j in range(i - 19, i + 1)]
        volatility = _q8(sum(abs_returns, Decimal("0")) / Decimal("20"))
        ranges = [(highs[j] - lows[j]) / closes[j] for j in range(i - 19, i + 1)]
        range_pct = _q8(sum(ranges, Decimal("0")) / Decimal("20"))
        trailing_volume = sum(volumes[i - 19 : i + 1], Decimal("0")) / Decimal("20")
        volume_ratio = _ratio(volumes[i], trailing_volume, "volume_ratio") if trailing_volume > 0 else Decimal("0")
        liquidity = _liquidity_state(volume_ratio)
        regime, reasons = _classify(
            fast_return=fast_return,
            slow_return=slow_return,
            volatility=volatility,
            range_pct=range_pct,
            liquidity=liquidity,
        )
        confidence = _confidence(regime, slow_return, volatility, range_pct)
        records.append(
            {
                "open_time_ms": int(rows[i]["open_time_ms"]),
                "regime": regime,
                "confidence": str(confidence),
                "reason_codes": list(reasons),
                "liquidity_state": liquidity,
                "features": {
                    "return_5": str(fast_return),
                    "return_20": str(slow_return),
                    "mean_abs_return_20": str(volatility),
                    "mean_range_pct_20": str(range_pct),
                    "volume_ratio_20": str(volume_ratio),
                },
            }
        )

    core = {
        "schema_version": SCHEMA_VERSION,
        "feature_version": FEATURE_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "dataset_binding_sha256": dataset["binding_sha256"],
        "instrument": dataset["instrument"],
        "timeframe": dataset["manifest_timeframe"],
        "source": dataset["source"],
        "finality": dataset["finality"],
        "paper_only": True,
        "lookahead_control": True,
        "records": records,
        "current_regime": records[-1],
    }
    return {**core, "evidence_sha256": _digest(core)}


def replay_identical(first: Mapping[str, Any], second: Mapping[str, Any]) -> bool:
    return _canonical_json(first) == _canonical_json(second)
