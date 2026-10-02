"""Build privacy-safe, source-bound signed taker-flow aggregates from official Bybit Spot trades.

The public Bybit trade archive's Buy/Sell field is treated only as taker side.
Raw trades are inputs, never published by this module. Output is completed 15m
aggregate research data with no Paper/Demo/Live authority.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SCHEMA = "nexus.verified-signed-trade-flow.v1"
PROOF_SCHEMA = "nexus.verified-signed-trade-flow-proof.v1"
TIMEFRAME = "minute15"
STEP = pd.Timedelta(minutes=15)
HEX64 = re.compile(r"^[a-f0-9]{64}$")
REQUIRED = {"timestamp", "side", "size", "price"}
CAPABILITY = "verified_signed_trade_flow"


class SignedTradeFlowError(ValueError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()
def canonical_symbol(symbol: str) -> str:
    value = symbol.strip().upper()
    if not value.endswith("USDT") or len(value) <= 4:
        raise SignedTradeFlowError("unsupported canonical Spot symbol")
    return value[:-4].lower() + "_usdt"


def aggregate_day(
    trades: pd.DataFrame,
    symbol: str,
    audit_date: str,
    source_sha256: str,
) -> pd.DataFrame:
    if not HEX64.fullmatch(str(source_sha256)):
        raise SignedTradeFlowError("source archive SHA256 is invalid")
    if not REQUIRED.issubset(trades.columns) or trades.empty:
        raise SignedTradeFlowError("validated raw trade inputs are unavailable")

    frame = trades.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    frame["size"] = pd.to_numeric(frame["size"], errors="raise")
    frame["price"] = pd.to_numeric(frame["price"], errors="raise")
    frame["side"] = frame["side"].astype("string").str.strip().str.title()
    if (~frame["side"].isin(["Buy", "Sell"])).any():
        raise SignedTradeFlowError("trade side is not verified Buy/Sell taker side")
    if (frame["size"] < 0).any() or (frame["price"] <= 0).any():
        raise SignedTradeFlowError("invalid trade size or price")
    if "trade_id" in frame.columns:
        ids = frame["trade_id"].dropna().astype("string")
        if len(ids) != ids.nunique():
            raise SignedTradeFlowError("duplicate trade IDs reject signed flow")
    day_start = pd.Timestamp(audit_date, tz="UTC")
    day_end = day_start + pd.Timedelta(days=1)
    if ((frame["timestamp"] < day_start) | (frame["timestamp"] >= day_end)).any():
        raise SignedTradeFlowError("trade timestamp is outside source archive day")

    frame = frame.sort_values("timestamp").reset_index(drop=True)
    frame["bucket"] = frame["timestamp"].dt.floor("15min")
    frame["notional"] = frame["size"] * frame["price"]
    frame["buy_base"] = np.where(frame["side"].eq("Buy"), frame["size"], 0.0)
    frame["sell_base"] = np.where(frame["side"].eq("Sell"), frame["size"], 0.0)
    frame["buy_notional"] = np.where(frame["side"].eq("Buy"), frame["notional"], 0.0)
    frame["sell_notional"] = np.where(frame["side"].eq("Sell"), frame["notional"], 0.0)

    grouped = frame.groupby("bucket", sort=True).agg(
        buy_base_volume=("buy_base", "sum"),
        sell_base_volume=("sell_base", "sum"),
        buy_notional=("buy_notional", "sum"),
        sell_notional=("sell_notional", "sum"),
        total_base_volume=("size", "sum"),
        total_notional=("notional", "sum"),
        trade_count=("timestamp", "size"),
    )
    expected = pd.date_range(day_start, day_end, freq=STEP, inclusive="left")
    grouped = grouped.reindex(expected)
    if grouped.isna().any().any():
        raise SignedTradeFlowError("incomplete 15m signed-flow UTC grid")
    if (grouped["total_notional"] <= 0).any() or (grouped["trade_count"] <= 0).any():
        raise SignedTradeFlowError("empty signed-flow bucket")
    out = grouped.reset_index(names="timestamp")
    out["available_at"] = out["timestamp"] + STEP
    out["signed_notional"] = out["buy_notional"] - out["sell_notional"]
    out["signed_notional_imbalance"] = out["signed_notional"] / out["total_notional"]
    out["vwap"] = out["total_notional"] / out["total_base_volume"].replace(0.0, np.nan)
    numeric = out[["signed_notional_imbalance", "vwap"]].astype(float).to_numpy()
    if not np.isfinite(numeric).all():
        raise SignedTradeFlowError("non-finite signed-flow aggregate")
    if (out["signed_notional_imbalance"].abs() > 1.000000000001).any():
        raise SignedTradeFlowError("signed-flow imbalance outside [-1, 1]")

    out["symbol"] = canonical_symbol(symbol)
    out["timeframe"] = TIMEFRAME
    out["source_archive_sha256"] = source_sha256
    out["source_side_semantics"] = "bybit_public_trade_taker_side_buy_sell"
    out["research_only"] = True
    out["automatic_strategy_promotion"] = False
    out["live_trading_authority"] = False
    return out


def semantic_digest(frame: pd.DataFrame) -> str:
    if frame.empty:
        raise SignedTradeFlowError("cannot digest empty signed-flow dataset")
    canonical = frame.copy().sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    for name in ("timestamp", "available_at"):
        canonical[name] = pd.to_datetime(canonical[name], utc=True).map(
            lambda value: value.isoformat()
        )
    payload = canonical.to_dict(orient="records")
    return _digest(payload)
def build_proof(
    frame: pd.DataFrame,
    archive_records: list[dict[str, Any]],
    start_date: str,
    end_date: str,
    symbols: tuple[str, ...],
) -> dict[str, Any]:
    if not archive_records:
        raise SignedTradeFlowError("archive provenance is unavailable")
    sources = []
    source_pairs = set()
    for row in archive_records:
        sha = str(row.get("sha256", ""))
        url = str(row.get("url", ""))
        pair = (str(row.get("symbol", "")), str(row.get("audit_date", "")))
        if (
            not HEX64.fullmatch(sha)
            or row.get("archive_ok") is not True
            or not url.startswith("https://public.bybit.com/spot/")
            or pair in source_pairs
        ):
            raise SignedTradeFlowError("source archive provenance is not verified")
        source_pairs.add(pair)
        sources.append({
            "symbol": row["symbol"],
            "audit_date": row["audit_date"],
            "sha256": sha,
            "url": url,
            "valid_trade_rows": int(row["valid_trade_rows"]),
            "invalid_side_rows": int(row["invalid_side_rows"]),
            "duplicate_trade_id_count": int(row["duplicate_trade_id_count"]),
        })
    expected_dates = [
        value.strftime("%Y-%m-%d")
        for value in pd.date_range(start_date, end_date, freq="1D")
    ]
    expected_pairs = {(symbol, day) for symbol in symbols for day in expected_dates}
    expected_rows = len(expected_dates) * len(symbols) * 96
    if source_pairs != expected_pairs or len(frame) != expected_rows:
        raise SignedTradeFlowError("signed-flow aggregate coverage is incomplete")

    core = {
        "schema": PROOF_SCHEMA,
        "capability": CAPABILITY,
        "venue": "bybit",
        "market": "spot",
        "source": "official_public_spot_trade_archive",
        "side_semantics": "taker_side_buy_sell",
        "timeframe": TIMEFRAME,
        "start_date": start_date,
        "end_date": end_date,
        "symbols": [canonical_symbol(s) for s in symbols],
        "rows": int(len(frame)),
        "dataset_semantic_sha256": semantic_digest(frame),
        "sources": sorted(sources, key=lambda x: (x["symbol"], x["audit_date"])),
        "raw_trade_rows_published": False,
        "research_only": True,
        "paper_only": True,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    return {**core, "proof_sha256": _digest(core)}
def verify_proof(frame: pd.DataFrame, proof: dict[str, Any]) -> None:
    core = dict(proof)
    claimed = core.pop("proof_sha256", None)
    if (
        core.get("schema") != PROOF_SCHEMA
        or core.get("capability") != CAPABILITY
        or core.get("venue") != "bybit"
        or core.get("market") != "spot"
        or core.get("source") != "official_public_spot_trade_archive"
        or core.get("side_semantics") != "taker_side_buy_sell"
        or core.get("raw_trade_rows_published") is not False
        or core.get("research_only") is not True
        or core.get("paper_only") is not True
        or core.get("automatic_strategy_promotion") is not False
        or core.get("live_trading_authority") is not False
        or core.get("rows") != len(frame)
        or core.get("dataset_semantic_sha256") != semantic_digest(frame)
        or claimed != _digest(core)
    ):
        raise SignedTradeFlowError("signed-flow proof integrity or authority rejected")
    for row in core.get("sources", []):
        if (
            not HEX64.fullmatch(str(row.get("sha256", "")))
            or int(row.get("invalid_side_rows", -1)) != 0
            or int(row.get("duplicate_trade_id_count", -1)) != 0
            or int(row.get("valid_trade_rows", 0)) <= 0
        ):
            raise SignedTradeFlowError("signed-flow source provenance rejected")


def write_proof(path: Path, proof: dict[str, Any]) -> None:
    path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
