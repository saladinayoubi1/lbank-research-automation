"""Verified public Bybit perpetual positioning inputs for NEXUS research.

This module creates a source-bound, research-only capability from public
USDT-linear perpetual Open Interest and Funding history. It never authenticates,
places orders, touches owner Paper state, or grants promotion/Live authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from bybit_derivatives_core_v1 import (
    Client,
    ValidationError,
    fetch_funding,
    fetch_instrument,
    milliseconds,
)

SCHEMA = "nexus.verified-perpetual-positioning.v1"
PROOF_SCHEMA = "nexus.verified-perpetual-positioning-proof.v1"
CAPABILITY_OI = "verified_perpetual_oi"
CAPABILITY_FUNDING = "verified_perpetual_funding"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
OI_INTERVAL = "1h"
OI_STEP = pd.Timedelta(hours=1)
OI_METHOD_CHANGE = pd.Timestamp("2026-06-11T00:00:00Z")
MAX_PAGES = 100


class PositioningDataError(ValueError):
    pass


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def utc_ns(values: Any) -> pd.Series:
    result = pd.Series(pd.to_datetime(values, utc=True, errors="raise"))
    if result.isna().any():
        raise PositioningDataError("missing positioning timestamp")
    return result.astype("datetime64[ns, UTC]")


def fetch_open_interest(
    client: Client,
    symbol: str,
    start_ms: int,
    end_ms: int,
) -> pd.DataFrame:
    if end_ms <= start_ms:
        raise PositioningDataError("invalid OI window")
    rows: dict[int, tuple[float, float]] = {}
    cursor: str | None = None
    seen_cursors: set[str] = set()

    for _ in range(MAX_PAGES):
        params: dict[str, Any] = {
            "category": "linear",
            "symbol": symbol,
            "intervalTime": OI_INTERVAL,
            "startTime": start_ms,
            "endTime": end_ms - 1,
            "limit": 200,
        }
        if cursor:
            params["cursor"] = cursor
        payload = client.get("/v5/market/open-interest", params)
        result = payload.get("result")
        if not isinstance(result, dict):
            raise PositioningDataError("invalid OI result object")
        items = result.get("list")
        if not isinstance(items, list):
            raise PositioningDataError("invalid OI list")
        for item in items:
            if not isinstance(item, dict):
                raise PositioningDataError("invalid OI row")
            if "singleOpenInterest" not in item:
                raise PositioningDataError(
                    "single-sided OI is required after the 2026-06-11 methodology change"
                )
            stamp = int(item["timestamp"])
            if start_ms <= stamp < end_ms:
                single = float(item["singleOpenInterest"])
                bilateral = float(item["openInterest"])
                if single < 0 or bilateral < 0:
                    raise PositioningDataError("negative OI value")
                value = (single, bilateral)
                if stamp in rows and rows[stamp] != value:
                    raise PositioningDataError("conflicting duplicate OI timestamp")
                rows[stamp] = value

        next_cursor = str(result.get("nextPageCursor") or "")
        if not next_cursor:
            break
        if next_cursor in seen_cursors:
            raise PositioningDataError("OI pagination cursor repeated")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    else:
        raise PositioningDataError("OI pagination exceeded bounded page limit")

    if not rows:
        raise PositioningDataError(f"no OI rows for {symbol}")
    ordered = sorted(rows)
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(ordered, unit="ms", utc=True),
            "single_open_interest": [rows[x][0] for x in ordered],
            "bilateral_open_interest": [rows[x][1] for x in ordered],
        }
    )
    return frame


def verify_open_interest_grid(
    frame: pd.DataFrame,
    symbol: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    if frame.empty:
        raise PositioningDataError(f"empty OI frame for {symbol}")
    out = frame.copy()
    out["timestamp"] = utc_ns(out["timestamp"])
    out = out.sort_values("timestamp").reset_index(drop=True)
    if out["timestamp"].duplicated().any():
        raise PositioningDataError(f"duplicate OI timestamp for {symbol}")
    if (out["timestamp"] < start).any() or (out["timestamp"] >= end).any():
        raise PositioningDataError(f"out-of-window OI timestamp for {symbol}")
    expected = pd.date_range(start, end, freq=OI_STEP, inclusive="left")
    actual = pd.DatetimeIndex(out["timestamp"])
    if len(actual) != len(expected) or not actual.equals(expected):
        raise PositioningDataError(f"incomplete exact 1h OI grid for {symbol}")
    oi_values = out[["single_open_interest", "bilateral_open_interest"]].astype(float).to_numpy()
    if not np.isfinite(oi_values).all() or (oi_values < 0).any():
        raise PositioningDataError(f"non-finite or negative OI for {symbol}")
    out["available_at"] = out["timestamp"] + OI_STEP
    out["symbol"] = symbol
    out["oi_methodology"] = "post_2026_06_11_single_sided"
    return out


def verify_funding(
    frame: pd.DataFrame,
    symbol: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    interval_minutes: int,
) -> pd.DataFrame:
    if frame.empty:
        raise PositioningDataError(f"empty funding frame for {symbol}")
    out = frame.copy()
    out["timestamp"] = utc_ns(out["timestamp"])
    out["funding_rate"] = pd.to_numeric(out["funding_rate"], errors="raise")
    out = out.sort_values("timestamp").reset_index(drop=True)
    if out["timestamp"].duplicated().any():
        raise PositioningDataError(f"duplicate funding timestamp for {symbol}")
    if (out["timestamp"] < start).any() or (out["timestamp"] >= end).any():
        raise PositioningDataError(f"out-of-window funding timestamp for {symbol}")
    if not np.isfinite(out["funding_rate"].astype(float).to_numpy()).all():
        raise PositioningDataError(f"non-finite funding value for {symbol}")
    expected_count = int((end - start).total_seconds() // (interval_minutes * 60))
    if len(out) != expected_count:
        raise PositioningDataError(
            f"incomplete funding settlements for {symbol}: {len(out)} != {expected_count}"
        )
    if len(out) > 1:
        gaps = out["timestamp"].diff().dropna()
        expected_gap = pd.Timedelta(minutes=interval_minutes)
        if not (gaps == expected_gap).all():
            raise PositioningDataError(f"irregular funding settlement grid for {symbol}")
    out["available_at"] = out["timestamp"]
    out["symbol"] = symbol
    return out


def semantic_digest(oi_by_symbol: dict[str, pd.DataFrame], funding_by_symbol: dict[str, pd.DataFrame]) -> str:
    payload: dict[str, Any] = {"oi": {}, "funding": {}}
    for symbol in sorted(oi_by_symbol):
        frame = oi_by_symbol[symbol].copy()
        for name in ("timestamp", "available_at"):
            frame[name] = utc_ns(frame[name]).map(lambda x: x.isoformat())
        payload["oi"][symbol] = frame[
            [
                "timestamp",
                "available_at",
                "single_open_interest",
                "bilateral_open_interest",
                "oi_methodology",
            ]
        ].to_dict(orient="records")
    for symbol in sorted(funding_by_symbol):
        frame = funding_by_symbol[symbol].copy()
        for name in ("timestamp", "available_at"):
            frame[name] = utc_ns(frame[name]).map(lambda x: x.isoformat())
        payload["funding"][symbol] = frame[
            ["timestamp", "available_at", "funding_rate"]
        ].to_dict(orient="records")
    return digest(payload)


def build(
    start: str,
    end_exclusive: str,
    output_root: Path,
    base_urls: list[str],
    timeout_seconds: float = 30.0,
    attempts: int = 20,
    pause_seconds: float = 0.03,
) -> dict[str, Any]:
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end_exclusive)
    start_ts = start_ts.tz_localize("UTC") if start_ts.tzinfo is None else start_ts.tz_convert("UTC")
    end_ts = end_ts.tz_localize("UTC") if end_ts.tzinfo is None else end_ts.tz_convert("UTC")
    if start_ts < OI_METHOD_CHANGE:
        raise PositioningDataError(
            "research window crosses the 2026-06-11 Bybit OI methodology boundary"
        )
    if end_ts <= start_ts or start_ts.minute or start_ts.second or end_ts.minute or end_ts.second:
        raise PositioningDataError("positioning window must be positive and hour-aligned")

    client = Client(base_urls, timeout_seconds, attempts, pause_seconds)
    start_ms = milliseconds(start_ts)
    end_ms = milliseconds(end_ts)
    oi_by_symbol: dict[str, pd.DataFrame] = {}
    funding_by_symbol: dict[str, pd.DataFrame] = {}
    instrument_rows: list[dict[str, Any]] = []

    output_root.mkdir(parents=True, exist_ok=True)
    for symbol in SYMBOLS:
        spec = fetch_instrument(client, symbol)
        if spec.funding_interval_minutes <= 0:
            raise PositioningDataError(f"invalid funding interval for {symbol}")
        oi = verify_open_interest_grid(
            fetch_open_interest(client, symbol, start_ms, end_ms),
            symbol,
            start_ts,
            end_ts,
        )
        funding = verify_funding(
            fetch_funding(client, symbol, start_ms, end_ms),
            symbol,
            start_ts,
            end_ts,
            spec.funding_interval_minutes,
        )
        oi_by_symbol[symbol] = oi
        funding_by_symbol[symbol] = funding
        symbol_dir = output_root / symbol.lower()
        symbol_dir.mkdir(parents=True, exist_ok=True)
        oi.to_parquet(symbol_dir / "open_interest_1h.parquet", index=False)
        funding.to_parquet(symbol_dir / "funding_settlements.parquet", index=False)
        instrument_rows.append(
            {
                "symbol": symbol,
                "funding_interval_minutes": spec.funding_interval_minutes,
            }
        )

    core = {
        "schema": PROOF_SCHEMA,
        "capabilities": [CAPABILITY_FUNDING, CAPABILITY_OI],
        "venue": "bybit",
        "category": "linear",
        "symbols": list(SYMBOLS),
        "start_utc": start_ts.isoformat(),
        "end_exclusive_utc": end_ts.isoformat(),
        "oi_endpoint": "/v5/market/open-interest",
        "oi_interval": OI_INTERVAL,
        "oi_value_field": "singleOpenInterest",
        "oi_methodology": "post_2026_06_11_single_sided",
        "funding_endpoint": "/v5/market/funding/history",
        "instrument_endpoint": "/v5/market/instruments-info",
        "instrument_contracts": instrument_rows,
        "oi_rows": {s: len(oi_by_symbol[s]) for s in SYMBOLS},
        "funding_rows": {s: len(funding_by_symbol[s]) for s in SYMBOLS},
        "dataset_semantic_sha256": semantic_digest(oi_by_symbol, funding_by_symbol),
        "research_only": True,
        "paper_only": True,
        "spot_execution_only_for_strategy_research": True,
        "derivatives_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
        "credentials_used": False,
    }
    proof = {**core, "proof_sha256": digest(core)}
    (output_root / "_perpetual_positioning_proof.json").write_text(
        json.dumps(proof, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return proof


def verify_proof(value: dict[str, Any]) -> None:
    core = dict(value)
    claimed = core.pop("proof_sha256", None)
    if (
        core.get("schema") != PROOF_SCHEMA
        or core.get("capabilities") != [CAPABILITY_FUNDING, CAPABILITY_OI]
        or core.get("venue") != "bybit"
        or core.get("category") != "linear"
        or core.get("symbols") != list(SYMBOLS)
        or core.get("oi_value_field") != "singleOpenInterest"
        or core.get("oi_methodology") != "post_2026_06_11_single_sided"
        or core.get("research_only") is not True
        or core.get("paper_only") is not True
        or core.get("spot_execution_only_for_strategy_research") is not True
        or core.get("derivatives_execution_authority") is not False
        or core.get("automatic_strategy_promotion") is not False
        or core.get("live_trading_authority") is not False
        or core.get("credentials_used") is not False
        or claimed != digest(core)
    ):
        raise PositioningDataError("perpetual positioning proof integrity or authority rejected")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2026-07-03T00:00:00Z")
    parser.add_argument("--end-exclusive", default="2026-08-02T00:00:00Z")
    parser.add_argument("--output-root", type=Path, default=Path("build/perpetual-positioning"))
    args = parser.parse_args()
    bases = [
        "https://api.bybit.nl",
        "https://api.bybit.tr",
        "https://api.bybit.kz",
        "https://api.bybitgeorgia.ge",
        "https://api.bybit.ae",
        "https://api.bybit.id",
        "https://api.byhkbit.com",
        "https://api.bybit.com",
        "https://api.bytick.com",
    ]
    proof = build(args.start, args.end_exclusive, args.output_root, bases)
    verify_proof(proof)
    print(
        json.dumps(
            {
                "capabilities": proof["capabilities"],
                "dataset_semantic_sha256": proof["dataset_semantic_sha256"],
                "research_only": proof["research_only"],
                "auto_promotion": proof["automatic_strategy_promotion"],
                "live_authority": proof["live_trading_authority"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
