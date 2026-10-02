"""Verify public Bybit perpetual funding + open-interest inputs for Research only.

This module does not trade derivatives. It authenticates fixed-window public market
data needed by the reviewed `perpetual_positioning_divergence` spot-long
hypothesis and emits a digest-bound proof plus sanitized parquet inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from bybit_derivatives_core_v1 import Client, milliseconds

SCHEMA = "nexus.verified-perpetual-positioning.v1"
CAPABILITIES = ("verified_perpetual_funding", "verified_perpetual_oi")
CATEGORY = "linear"
OI_INTERVAL = "1h"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
DEFAULT_START = "2026-07-03T00:00:00Z"
DEFAULT_END = "2026-08-02T00:00:00Z"


class PositioningCapabilityError(ValueError):
    pass


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _instrument_identity(client: Client, symbol: str) -> dict[str, Any]:
    result = client.get(
        "/v5/market/instruments-info",
        {"category": CATEGORY, "symbol": symbol, "limit": 1000},
    )["result"]
    if result.get("category") != CATEGORY:
        raise PositioningCapabilityError(f"instrument category mismatch: {symbol}")
    items = [x for x in result.get("list", []) if x.get("symbol") == symbol]
    if len(items) != 1:
        raise PositioningCapabilityError(f"ambiguous instrument identity: {symbol}")
    item = items[0]
    expected_base = symbol.removesuffix("USDT")
    funding_interval = int(item.get("fundingInterval", 0))
    if (
        item.get("contractType") != "LinearPerpetual"
        or item.get("status") != "Trading"
        or item.get("baseCoin") != expected_base
        or item.get("quoteCoin") != "USDT"
        or item.get("settleCoin") != "USDT"
        or str(item.get("deliveryTime", "0")) != "0"
        or funding_interval <= 0
    ):
        raise PositioningCapabilityError(f"unsupported perpetual identity: {symbol}")
    return {
        "symbol": symbol,
        "category": CATEGORY,
        "contract_type": "LinearPerpetual",
        "status": "Trading",
        "base_coin": expected_base,
        "quote_coin": "USDT",
        "settle_coin": "USDT",
        "funding_interval_minutes": funding_interval,
    }


def fetch_verified_open_interest(
    client: Client,
    symbol: str,
    start_ms: int,
    end_ms: int,
) -> pd.DataFrame:
    cursor = ""
    seen_cursors: set[str] = set()
    rows: dict[int, float] = {}
    while True:
        params: dict[str, Any] = {
            "category": CATEGORY,
            "symbol": symbol,
            "intervalTime": OI_INTERVAL,
            "startTime": start_ms,
            "endTime": end_ms - 1,
            "limit": 200,
        }
        if cursor:
            params["cursor"] = cursor
        result = client.get("/v5/market/open-interest", params)["result"]
        if result.get("category") != CATEGORY or result.get("symbol") != symbol:
            raise PositioningCapabilityError(f"OI product identity mismatch: {symbol}")
        batch = result.get("list", [])
        if not isinstance(batch, list):
            raise PositioningCapabilityError(f"OI response is not a list: {symbol}")
        for item in batch:
            stamp = int(item["timestamp"])
            value = float(item["openInterest"])
            if not math.isfinite(value) or value < 0:
                raise PositioningCapabilityError(f"invalid OI value: {symbol}")
            if start_ms <= stamp < end_ms:
                if stamp in rows and rows[stamp] != value:
                    raise PositioningCapabilityError(f"conflicting duplicate OI timestamp: {symbol}")
                rows[stamp] = value
        next_cursor = str(result.get("nextPageCursor") or "")
        if not next_cursor:
            break
        if next_cursor == cursor or next_cursor in seen_cursors:
            raise PositioningCapabilityError(f"OI cursor pagination stalled: {symbol}")
        seen_cursors.add(next_cursor)
        cursor = next_cursor

    if not rows:
        raise PositioningCapabilityError(f"no OI rows: {symbol}")
    ordered = sorted(rows)
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(ordered, unit="ms", utc=True),
            "open_interest": [rows[x] for x in ordered],
        }
    )
    expected = pd.date_range(
        pd.to_datetime(start_ms, unit="ms", utc=True),
        pd.to_datetime(end_ms, unit="ms", utc=True),
        freq="1h",
        inclusive="left",
    )
    actual = pd.DatetimeIndex(frame["timestamp"])
    if not actual.equals(expected):
        raise PositioningCapabilityError(
            f"incomplete or off-grid 1h OI coverage: {symbol}; "
            f"actual={len(actual)} expected={len(expected)}"
        )
    return frame


def fetch_verified_funding(
    client: Client,
    symbol: str,
    start_ms: int,
    end_ms: int,
    interval_minutes: int,
) -> pd.DataFrame:
    rows: dict[int, float] = {}
    cursor = end_ms - 1
    while cursor >= start_ms:
        result = client.get(
            "/v5/market/funding/history",
            {
                "category": CATEGORY,
                "symbol": symbol,
                "endTime": cursor,
                "limit": 200,
            },
        )["result"]
        if result.get("category") != CATEGORY:
            raise PositioningCapabilityError(f"funding category mismatch: {symbol}")
        batch = result.get("list", [])
        if not isinstance(batch, list):
            raise PositioningCapabilityError(f"funding response is not a list: {symbol}")
        if not batch:
            break
        stamps = []
        for item in batch:
            if item.get("symbol") != symbol:
                raise PositioningCapabilityError(f"funding symbol mismatch: {symbol}")
            stamp = int(item["fundingRateTimestamp"])
            stamps.append(stamp)
            value = float(item["fundingRate"])
            if not math.isfinite(value):
                raise PositioningCapabilityError(f"invalid funding rate: {symbol}")
            if start_ms <= stamp < end_ms:
                if stamp in rows and rows[stamp] != value:
                    raise PositioningCapabilityError(
                        f"conflicting duplicate funding timestamp: {symbol}"
                    )
                rows[stamp] = value
        oldest = min(stamps)
        if oldest <= start_ms:
            break
        if oldest >= cursor:
            raise PositioningCapabilityError(f"funding pagination stalled: {symbol}")
        cursor = oldest - 1

    ordered = sorted(rows)
    if len(ordered) < 2:
        raise PositioningCapabilityError(f"insufficient funding rows: {symbol}")
    interval_ms = interval_minutes * 60_000
    if any((b - a) != interval_ms for a, b in zip(ordered, ordered[1:])):
        raise PositioningCapabilityError(f"funding interval gap: {symbol}")
    if ordered[0] - start_ms >= interval_ms or end_ms - ordered[-1] > interval_ms:
        raise PositioningCapabilityError(f"incomplete funding boundary coverage: {symbol}")
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(ordered, unit="ms", utc=True),
            "funding_rate": [rows[x] for x in ordered],
        }
    )


def _semantic_frame_digest(frame: pd.DataFrame) -> str:
    canonical = frame.copy()
    canonical["timestamp"] = pd.to_datetime(canonical["timestamp"], utc=True).map(
        lambda x: x.isoformat()
    )
    return digest(canonical.to_dict(orient="records"))


def collect(
    client: Client,
    start_utc: str,
    end_utc: str,
    output: Path,
    symbols: tuple[str, ...] = SYMBOLS,
) -> dict[str, Any]:
    start_ms = milliseconds(start_utc)
    end_ms = milliseconds(end_utc)
    if end_ms <= start_ms or (end_ms - start_ms) < 30 * 24 * 60 * 60 * 1000:
        raise PositioningCapabilityError("positioning window must cover at least 30 days")
    output.mkdir(parents=True, exist_ok=True)

    symbol_proofs = []
    for symbol in symbols:
        identity = _instrument_identity(client, symbol)
        oi = fetch_verified_open_interest(client, symbol, start_ms, end_ms)
        funding = fetch_verified_funding(
            client,
            symbol,
            start_ms,
            end_ms,
            identity["funding_interval_minutes"],
        )
        oi["available_at"] = oi["timestamp"] + pd.Timedelta(hours=1)
        funding["available_at"] = funding["timestamp"]
        oi["symbol"] = symbol
        funding["symbol"] = symbol
        oi["category"] = CATEGORY
        funding["category"] = CATEGORY
        oi["research_only"] = True
        funding["research_only"] = True
        folder = output / symbol.lower()
        folder.mkdir(parents=True, exist_ok=True)
        oi.to_parquet(folder / "open_interest_1h.parquet", index=False)
        funding.to_parquet(folder / "funding_events.parquet", index=False)
        symbol_proofs.append(
            {
                "identity": identity,
                "open_interest_rows": len(oi),
                "funding_rows": len(funding),
                "open_interest_sha256": _semantic_frame_digest(oi),
                "funding_sha256": _semantic_frame_digest(funding),
                "open_interest_unit": "base_asset_for_linear_contract",
            }
        )

    core = {
        "schema": SCHEMA,
        "capabilities": list(CAPABILITIES),
        "venue": "bybit",
        "category": CATEGORY,
        "symbols": list(symbols),
        "start_utc": pd.Timestamp(start_utc).isoformat(),
        "end_exclusive_utc": pd.Timestamp(end_utc).isoformat(),
        "open_interest_interval": OI_INTERVAL,
        "sources": {
            "instrument": "/v5/market/instruments-info",
            "funding": "/v5/market/funding/history",
            "open_interest": "/v5/market/open-interest",
        },
        "symbol_proofs": symbol_proofs,
        "research_only": True,
        "paper_only": True,
        "spot_long_hypothesis_only": True,
        "derivatives_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    proof = {**core, "proof_sha256": digest(core)}
    (output / "_perpetual_positioning_proof.json").write_text(
        json.dumps(proof, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return proof


def verify_output(root: Path) -> dict[str, Any]:
    path = root / "_perpetual_positioning_proof.json"
    proof = json.loads(path.read_text(encoding="utf-8"))
    claimed = proof.pop("proof_sha256", None)
    if (
        proof.get("schema") != SCHEMA
        or proof.get("capabilities") != list(CAPABILITIES)
        or proof.get("venue") != "bybit"
        or proof.get("category") != CATEGORY
        or proof.get("research_only") is not True
        or proof.get("paper_only") is not True
        or proof.get("spot_long_hypothesis_only") is not True
        or proof.get("derivatives_execution_authority") is not False
        or proof.get("automatic_strategy_promotion") is not False
        or proof.get("live_trading_authority") is not False
        or claimed != digest(proof)
    ):
        raise PositioningCapabilityError("positioning proof integrity or authority rejected")
    return {**proof, "proof_sha256": claimed}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("experiments/bybit_derivatives_validation_v1.json"))
    parser.add_argument("--start-utc", default=DEFAULT_START)
    parser.add_argument("--end-utc", default=DEFAULT_END)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    config = json.loads(args.manifest.read_text(encoding="utf-8"))
    client = Client(
        config["api_base_urls"],
        float(config["timeout_seconds"]),
        int(config["maximum_attempts"]),
        float(config["request_pause_seconds"]),
    )
    proof = collect(client, args.start_utc, args.end_utc, args.output)
    verify_output(args.output)
    print(
        json.dumps(
            {
                "capabilities": proof["capabilities"],
                "symbols": proof["symbols"],
                "research_only": True,
                "derivatives_execution_authority": False,
                "auto_promotion": False,
                "live_authority": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
