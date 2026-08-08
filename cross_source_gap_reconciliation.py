from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd

from binance_public_klines import fetch_closed_klines as fetch_binance
from bybit_public_klines import fetch_closed_klines as fetch_bybit
from main import TIMEFRAME_SECONDS

TIMEFRAME_MAP = {
    "minute15": {"bybit": "15", "binance": "15m"},
    "hour1": {"bybit": "60", "binance": "1h"},
    "hour4": {"bybit": "240", "binance": "4h"},
}
SUPPORTED_SYMBOLS = {"btc_usdt": "BTCUSDT", "eth_usdt": "ETHUSDT"}
MAX_OHLC_RELATIVE_DEVIATION = Decimal("0.01")
OUTPUT_ROOT = Path("data/market/reconciliation")
OHLC_FIELDS = ("open", "high", "low", "close")


@dataclass(frozen=True)
class Candidate:
    symbol: str
    timeframe: str
    timestamp_utc: str
    status: str
    selected_source: str | None
    primary_candle_sha256: str | None
    secondary_candle_sha256: str | None
    max_ohlc_relative_deviation: str | None
    reason: str


def _sha256_json(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def missing_timestamps(frame: pd.DataFrame, timeframe: str) -> list[pd.Timestamp]:
    timestamps = pd.DatetimeIndex(pd.to_datetime(frame["timestamp"], utc=True).drop_duplicates().sort_values())
    if len(timestamps) < 2:
        return []
    step = pd.Timedelta(TIMEFRAME_SECONDS[timeframe], unit="s")
    expected = pd.date_range(start=timestamps[0], end=timestamps[-1], freq=step)
    return list(expected.difference(timestamps))


def _decimal(value: Any) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("malformed numeric candle value") from exc
    if not parsed.is_finite():
        raise ValueError("non-finite candle value")
    return parsed


def _rel_deviation(left: Any, right: Any) -> Decimal:
    a, b = _decimal(left), _decimal(right)
    denominator = max(abs(a), abs(b))
    if denominator == 0:
        return Decimal("0") if a == b else Decimal("Infinity")
    return abs(a - b) / denominator


def _canonical_candle(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": row["source"],
        "market_type": row["market_type"],
        "symbol": row["symbol"],
        "open_time_ms": row["open_time_ms"],
        "open": str(row["open"]),
        "high": str(row["high"]),
        "low": str(row["low"]),
        "close": str(row["close"]),
        "volume": str(row["volume"]),
        "closed": row["closed"],
    }


def _validate_row(row: dict[str, Any], *, expected_source: str, expected_symbol: str, expected_open_ms: int) -> None:
    required = {"source", "market_type", "symbol", "open_time_ms", "open", "high", "low", "close", "volume", "closed"}
    if not isinstance(row, dict) or not required.issubset(row):
        raise ValueError("source row schema incomplete")
    if row["source"] != expected_source or row["market_type"] != "spot" or row["symbol"] != expected_symbol:
        raise ValueError("source identity mismatch")
    if row["open_time_ms"] != expected_open_ms or row["closed"] is not True:
        raise ValueError("source timestamp/finality mismatch")
    prices = {field: _decimal(row[field]) for field in OHLC_FIELDS}
    volume = _decimal(row["volume"])
    if min(prices.values()) <= 0 or volume < 0:
        raise ValueError("invalid OHLCV values")
    if prices["high"] < max(prices["open"], prices["close"], prices["low"]):
        raise ValueError("invalid high bound")
    if prices["low"] > min(prices["open"], prices["close"], prices["high"]):
        raise ValueError("invalid low bound")


def reconcile_one_timestamp(
    symbol: str,
    timeframe: str,
    timestamp: pd.Timestamp,
    *,
    now_ms: int,
) -> Candidate:
    if symbol not in SUPPORTED_SYMBOLS or timeframe not in TIMEFRAME_MAP:
        return Candidate(symbol, timeframe, timestamp.isoformat(), "blocked", None, None, None, None, "mapping_unapproved")

    exchange_symbol = SUPPORTED_SYMBOLS[symbol]
    start_ms = int(timestamp.timestamp() * 1000)
    try:
        bybit = fetch_bybit(
            exchange_symbol,
            TIMEFRAME_MAP[timeframe]["bybit"],
            now_ms=now_ms,
            start_time_ms=start_ms,
            end_time_ms=start_ms,
            limit=1,
        )
        binance = fetch_binance(
            exchange_symbol,
            TIMEFRAME_MAP[timeframe]["binance"],
            now_ms=now_ms,
            start_time_ms=start_ms,
            end_time_ms=start_ms,
            limit=1,
        )
    except Exception as exc:
        return Candidate(symbol, timeframe, timestamp.isoformat(), "blocked", None, None, None, None, f"source_fetch_failed:{type(exc).__name__}")

    if len(bybit) != 1 or len(binance) != 1:
        return Candidate(symbol, timeframe, timestamp.isoformat(), "blocked", None, None, None, None, "source_window_incomplete")

    bybit_row, binance_row = bybit[0], binance[0]
    try:
        _validate_row(bybit_row, expected_source="Bybit", expected_symbol=exchange_symbol, expected_open_ms=start_ms)
        _validate_row(binance_row, expected_source="Binance", expected_symbol=exchange_symbol, expected_open_ms=start_ms)
    except ValueError as exc:
        return Candidate(symbol, timeframe, timestamp.isoformat(), "blocked", None, None, None, None, f"source_validation_failed:{str(exc)}")

    deviations = [_rel_deviation(bybit_row[field], binance_row[field]) for field in OHLC_FIELDS]
    max_deviation = max(deviations)
    primary_digest = _sha256_json(_canonical_candle(bybit_row))
    secondary_digest = _sha256_json(_canonical_candle(binance_row))
    if max_deviation > MAX_OHLC_RELATIVE_DEVIATION:
        return Candidate(
            symbol,
            timeframe,
            timestamp.isoformat(),
            "blocked",
            None,
            primary_digest,
            secondary_digest,
            str(max_deviation),
            "cross_source_ohlc_disagreement",
        )

    return Candidate(
        symbol,
        timeframe,
        timestamp.isoformat(),
        "eligible_candidate",
        "Bybit",
        primary_digest,
        secondary_digest,
        str(max_deviation),
        "bybit_primary_binance_correlated",
    )


def reconcile_dataset(
    path: Path,
    symbol: str,
    timeframe: str,
    *,
    max_candidates: int = 50,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    frame = pd.read_parquet(path)
    missing = missing_timestamps(frame, timeframe)
    generated_at = generated_at or datetime.now(timezone.utc)
    now_ms = int(generated_at.timestamp() * 1000)
    candidates = [
        reconcile_one_timestamp(symbol, timeframe, ts, now_ms=now_ms)
        for ts in missing[:max_candidates]
    ]
    deterministic_core = {
        "schema_version": 2,
        "symbol": symbol,
        "timeframe": timeframe,
        "source_policy": {
            "primary": "Bybit",
            "secondary": "Binance",
            "tertiary": "LBank",
            "max_ohlc_relative_deviation": str(MAX_OHLC_RELATIVE_DEVIATION),
            "synthetic_candles": False,
            "silent_substitution": False,
        },
        "input": {
            "path": str(path),
            "sha256": _sha256_file(path),
            "rows": int(len(frame)),
            "missing_total": len(missing),
        },
        "candidates": [asdict(candidate) for candidate in candidates],
    }
    payload = {
        **deterministic_core,
        "generated_at": generated_at.astimezone(timezone.utc).isoformat(),
        "reconciliation_sha256": _sha256_json(deterministic_core),
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_ROOT / f"{symbol}__{timeframe}.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate fail-closed Bybit/Binance reconciliation candidates for LBank gaps")
    parser.add_argument("symbol", choices=sorted(SUPPORTED_SYMBOLS))
    parser.add_argument("timeframe", choices=sorted(TIMEFRAME_MAP))
    parser.add_argument("--max-candidates", type=int, default=50)
    args = parser.parse_args()
    path = Path("data/market") / args.symbol / f"{args.timeframe}.parquet"
    payload = reconcile_dataset(path, args.symbol, args.timeframe, max_candidates=max(1, args.max_candidates))
    eligible = sum(candidate["status"] == "eligible_candidate" for candidate in payload["candidates"])
    blocked = len(payload["candidates"]) - eligible
    print(json.dumps({"symbol": args.symbol, "timeframe": args.timeframe, "eligible": eligible, "blocked": blocked, "missing_total": payload["input"]["missing_total"], "reconciliation_sha256": payload["reconciliation_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
