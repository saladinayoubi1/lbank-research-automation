from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
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
MAX_PRICE_RELATIVE_DEVIATION = Decimal("0.01")
OUTPUT_ROOT = Path("data/market/reconciliation")


@dataclass(frozen=True)
class Candidate:
    symbol: str
    timeframe: str
    timestamp_utc: str
    status: str
    selected_source: str | None
    bybit_close: str | None
    binance_close: str | None
    relative_close_deviation: str | None
    reason: str


def _sha256_json(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def missing_timestamps(frame: pd.DataFrame, timeframe: str) -> list[pd.Timestamp]:
    timestamps = pd.DatetimeIndex(pd.to_datetime(frame["timestamp"], utc=True).drop_duplicates().sort_values())
    if len(timestamps) < 2:
        return []
    step = pd.Timedelta(TIMEFRAME_SECONDS[timeframe], unit="s")
    expected = pd.date_range(start=timestamps[0], end=timestamps[-1], freq=step)
    return list(expected.difference(timestamps))


def _rel_deviation(left: str, right: str) -> Decimal:
    a, b = Decimal(left), Decimal(right)
    denominator = max(abs(a), abs(b))
    if denominator == 0:
        return Decimal("0") if a == b else Decimal("Infinity")
    return abs(a - b) / denominator


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
    end_ms = start_ms
    try:
        bybit = fetch_bybit(
            exchange_symbol,
            TIMEFRAME_MAP[timeframe]["bybit"],
            now_ms=now_ms,
            start_time_ms=start_ms,
            end_time_ms=end_ms,
            limit=1,
        )
        binance = fetch_binance(
            exchange_symbol,
            TIMEFRAME_MAP[timeframe]["binance"],
            now_ms=now_ms,
            start_time_ms=start_ms,
            end_time_ms=end_ms,
            limit=1,
        )
    except Exception as exc:  # adapters already fail closed with typed errors
        return Candidate(symbol, timeframe, timestamp.isoformat(), "blocked", None, None, None, None, f"source_fetch_failed:{type(exc).__name__}")

    if len(bybit) != 1 or len(binance) != 1:
        return Candidate(symbol, timeframe, timestamp.isoformat(), "blocked", None, None, None, None, "source_window_incomplete")

    bybit_row, binance_row = bybit[0], binance[0]
    if bybit_row["open_time_ms"] != binance_row["open_time_ms"]:
        return Candidate(symbol, timeframe, timestamp.isoformat(), "blocked", None, bybit_row["close"], binance_row["close"], None, "timestamp_disagreement")

    deviation = _rel_deviation(bybit_row["close"], binance_row["close"])
    if deviation > MAX_PRICE_RELATIVE_DEVIATION:
        return Candidate(
            symbol,
            timeframe,
            timestamp.isoformat(),
            "blocked",
            None,
            bybit_row["close"],
            binance_row["close"],
            str(deviation),
            "cross_source_price_disagreement",
        )

    return Candidate(
        symbol,
        timeframe,
        timestamp.isoformat(),
        "eligible_candidate",
        "Bybit",
        bybit_row["close"],
        binance_row["close"],
        str(deviation),
        "bybit_primary_binance_correlated",
    )


def reconcile_dataset(path: Path, symbol: str, timeframe: str, *, max_candidates: int = 50) -> dict[str, Any]:
    frame = pd.read_parquet(path)
    missing = missing_timestamps(frame, timeframe)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    candidates = [
        reconcile_one_timestamp(symbol, timeframe, ts, now_ms=now_ms)
        for ts in missing[:max_candidates]
    ]
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
        "source_policy": {
            "primary": "Bybit",
            "secondary": "Binance",
            "tertiary": "LBank",
            "max_close_relative_deviation": str(MAX_PRICE_RELATIVE_DEVIATION),
            "synthetic_candles": False,
            "silent_substitution": False,
        },
        "input": {
            "path": str(path),
            "rows": int(len(frame)),
            "missing_total": len(missing),
        },
        "candidates": [asdict(candidate) for candidate in candidates],
    }
    payload["digest_sha256"] = _sha256_json(payload)
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
    print(json.dumps({"symbol": args.symbol, "timeframe": args.timeframe, "eligible": eligible, "blocked": blocked, "missing_total": payload["input"]["missing_total"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
