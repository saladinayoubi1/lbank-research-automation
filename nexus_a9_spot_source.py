"""Acquire the exact official Bybit Spot source surface for A9 research.

The A9 analysis window is 2026-07-03 through 2026-08-01 inclusive on 15-minute
Spot bars. To keep memory bounded on the dedicated Windows Research runner this
module deliberately consumes official *daily* Bybit Spot archives rather than
loading the very large July monthly archives into one pandas frame.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

import bybit_spot_archive_audit as audit
import bybit_spot_archive_collector as collector
import bybit_spot_backfill as backfill

SCHEMA = "nexus.a9-spot-source.v2"
PROOF_NAME = "_a9_spot_source_proof.json"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
SOURCE_START_DATE = "2026-07-03"
SOURCE_END_DATE = "2026-08-01"
ANALYSIS_START = pd.Timestamp("2026-07-03T00:00:00Z")
ANALYSIS_END_EXCLUSIVE = pd.Timestamp("2026-08-02T00:00:00Z")
TIMEFRAME = "minute15"
STEP = pd.Timedelta(minutes=15)
EXPECTED_DAYS = tuple(
    ts.strftime("%Y-%m-%d")
    for ts in pd.date_range(SOURCE_START_DATE, SOURCE_END_DATE, freq="1D")
)
EXPECTED_SOURCE_ROWS = len(EXPECTED_DAYS) * 96
EXPECTED_ARCHIVES = len(SYMBOLS) * len(EXPECTED_DAYS)
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_FRAME_BYTES = 500 * 1024 * 1024
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_QUALITY_ZERO_FIELDS = (
    "invalid_numeric_rows",
    "invalid_symbol_rows",
    "invalid_side_rows",
    "non_positive_price_rows",
    "negative_size_rows",
    "outside_range_rows",
    "duplicate_trade_id_count",
    "source_rows_skipped",
    "malformed_csv_rows",
)


class A9SpotSourceError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _read_json(path: Path) -> Any:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8_000_000:
        raise A9SpotSourceError(f"missing or unsafe JSON source: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise A9SpotSourceError(f"unreadable JSON source: {path}") from exc


def _validate_report(report: Mapping[str, Any]) -> None:
    config = report.get("configuration")
    summary = report.get("summary")
    if not isinstance(config, Mapping) or not isinstance(summary, Mapping):
        raise A9SpotSourceError("backfill report structure is invalid")
    if (
        config.get("start_date") != SOURCE_START_DATE
        or config.get("end_date") != SOURCE_END_DATE
        or config.get("symbols") != list(SYMBOLS)
        or config.get("max_archives_per_run") != EXPECTED_ARCHIVES
        or summary.get("plan_units") != len(EXPECTED_DAYS)
        or summary.get("plan_archives") != EXPECTED_ARCHIVES
        or summary.get("completed_units") != len(EXPECTED_DAYS)
        or summary.get("remaining_units") != 0
        or summary.get("run_failures") != 0
        or summary.get("backfill_complete") is not True
        or summary.get("current_dataset_integrity_ok") is not True
        or report.get("run_failures") != []
    ):
        raise A9SpotSourceError("official BTC/ETH daily Spot backfill did not complete exact A9 coverage")


def _source_evidence(state_root: Path) -> tuple[list[dict[str, Any]], str]:
    raw = _read_json(state_root / backfill.SOURCE_MANIFEST_NAME)
    if not isinstance(raw, list) or len(raw) != EXPECTED_ARCHIVES:
        raise A9SpotSourceError(
            f"A9 Spot source manifest must contain exactly {EXPECTED_ARCHIVES} daily archives"
        )

    expected = {
        (symbol, f"daily:{day}")
        for symbol in SYMBOLS
        for day in EXPECTED_DAYS
    }
    seen: set[tuple[str, str]] = set()
    evidence: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, Mapping):
            raise A9SpotSourceError("invalid A9 Spot source row")
        symbol = str(row.get("symbol", "")).upper()
        unit_id = str(row.get("unit_id", ""))
        key = (symbol, unit_id)
        if key not in expected or key in seen:
            raise A9SpotSourceError("unexpected, missing, or duplicated A9 Spot source identity")
        seen.add(key)
        day = unit_id.split(":", 1)[1]
        filename = f"{symbol}_{day}.csv.gz"
        expected_url = backfill.archive_url(symbol, filename)
        size = row.get("size_bytes")
        sha = str(row.get("sha256", "")).lower()
        if (
            row.get("filename") != filename
            or row.get("unit_kind") != "daily"
            or row.get("start_date") != day
            or row.get("end_date") != day
            or row.get("url") != expected_url
            or not expected_url.startswith(audit.ARCHIVE_BASE_URL + "/")
            or row.get("http_status") != 200
            or isinstance(size, bool)
            or not isinstance(size, int)
            or not 0 < size <= MAX_ARCHIVE_BYTES
            or not _HEX64.fullmatch(sha)
            or int(row.get("source_rows", 0)) <= 0
            or int(row.get("valid_trade_rows", 0)) <= 0
            or any(int(row.get(field, 0)) != 0 for field in _QUALITY_ZERO_FIELDS)
        ):
            raise A9SpotSourceError(f"official A9 Spot archive provenance failed closed: {symbol}/{day}")
        evidence.append(
            {
                "symbol": symbol,
                "date": day,
                "unit_id": unit_id,
                "unit_kind": "daily",
                "filename": filename,
                "url": expected_url,
                "sha256": sha,
                "size_bytes": size,
                "http_status": 200,
                "source_rows": int(row["source_rows"]),
                "valid_trade_rows": int(row["valid_trade_rows"]),
                "parser_engine": str(row.get("parser_engine", "")),
                "timestamp_unit": str(row.get("timestamp_unit", "")),
            }
        )
    if seen != expected:
        raise A9SpotSourceError("A9 Spot source surface is incomplete")
    evidence.sort(key=lambda item: (item["symbol"], item["date"]))
    return evidence, _digest(evidence)


def _analysis_frame(state_root: Path, symbol: str) -> tuple[pd.DataFrame, str]:
    canonical = collector.canonical_symbol(symbol)
    path = state_root / "bybit_market" / canonical / f"{TIMEFRAME}.parquet"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FRAME_BYTES:
        raise A9SpotSourceError(f"A9 Spot frame missing or unsafe: {symbol}")
    frame = pd.read_parquet(path).copy()
    if frame.columns.tolist() != collector.CANONICAL_COLUMNS:
        raise A9SpotSourceError(f"unexpected A9 Spot frame schema: {symbol}")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    expected = pd.date_range(
        ANALYSIS_START,
        ANALYSIS_END_EXCLUSIVE,
        freq=STEP,
        inclusive="left",
    )
    if (
        len(frame) != EXPECTED_SOURCE_ROWS
        or not pd.DatetimeIndex(frame["timestamp"]).equals(expected)
        or set(frame["symbol"].astype(str)) != {canonical}
        or set(frame["timeframe"].astype(str)) != {TIMEFRAME}
    ):
        raise A9SpotSourceError(f"A9 Spot 15m grid is incomplete: {symbol}")

    for field in ("open", "high", "low", "close", "volume"):
        frame[field] = pd.to_numeric(frame[field], errors="raise")
    values = frame[["open", "high", "low", "close", "volume"]].astype(float).to_numpy()
    if (
        not np.isfinite(values).all()
        or (frame[["open", "high", "low", "close"]] <= 0).any().any()
        or (frame["volume"] < 0).any()
        or (frame["high"] < frame[["open", "close", "low"]].max(axis=1)).any()
        or (frame["low"] > frame[["open", "close", "high"]].min(axis=1)).any()
    ):
        raise A9SpotSourceError(f"invalid A9 Spot OHLCV values: {symbol}")

    payload = [
        {
            "timestamp": pd.Timestamp(row.timestamp).isoformat(),
            "open": round(float(row.open), 12),
            "high": round(float(row.high), 12),
            "low": round(float(row.low), 12),
            "close": round(float(row.close), 12),
            "volume": round(float(row.volume), 12),
        }
        for row in frame.itertuples(index=False)
    ]
    return frame, _digest(payload)


def build_proof(state_root: Path, report: Mapping[str, Any]) -> dict[str, Any]:
    _validate_report(report)
    state = state_root.resolve()
    sources, source_digest = _source_evidence(state)
    cells: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        frame, frame_digest = _analysis_frame(state, symbol)
        cells.append(
            {
                "symbol": symbol,
                "canonical_symbol": collector.canonical_symbol(symbol),
                "timeframe": TIMEFRAME,
                "analysis_rows": len(frame),
                "first_open_utc": pd.Timestamp(frame["timestamp"].iloc[0]).isoformat(),
                "last_open_utc": pd.Timestamp(frame["timestamp"].iloc[-1]).isoformat(),
                "analysis_frame_sha256": frame_digest,
            }
        )
    core = {
        "schema": SCHEMA,
        "venue": "bybit",
        "market": "spot",
        "archive_base_url": audit.ARCHIVE_BASE_URL,
        "symbols": list(SYMBOLS),
        "source_window_start": SOURCE_START_DATE,
        "source_window_end_inclusive": SOURCE_END_DATE,
        "analysis_start_utc": ANALYSIS_START.isoformat(),
        "analysis_end_exclusive_utc": ANALYSIS_END_EXCLUSIVE.isoformat(),
        "timeframe": TIMEFRAME,
        "archive_granularity": "daily",
        "archive_sources": sources,
        "archive_source_count": len(sources),
        "archive_source_manifest_sha256": source_digest,
        "cells": cells,
        "data_origin": "official_public_bybit_spot_trade_archive_aggregated",
        "research_only": True,
        "paper_only": True,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "real_exchange_orders": False,
    }
    return {**core, "proof_sha256": _digest(core)}


def verify_proof(state_root: Path, value: Mapping[str, Any]) -> None:
    state = state_root.resolve()
    report = _read_json(state / backfill.REPORT_NAME)
    if not isinstance(report, Mapping):
        raise A9SpotSourceError("A9 Spot backfill report is invalid")
    expected = build_proof(state, report)
    if dict(value) != expected:
        raise A9SpotSourceError("A9 Spot proof or source bytes do not match accepted contract")


def acquire(state_root: Path, cache_root: Path) -> dict[str, Any]:
    report = backfill.run_backfill(
        start_date=SOURCE_START_DATE,
        end_date=SOURCE_END_DATE,
        state_root=state_root,
        cache_root=cache_root,
        max_archives_per_run=EXPECTED_ARCHIVES,
        symbols=SYMBOLS,
        clean=True,
    )
    proof = build_proof(state_root, report)
    target = state_root / PROOF_NAME
    target.write_text(
        json.dumps(proof, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    verify_proof(state_root, proof)
    return proof


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    args = parser.parse_args()
    proof = acquire(args.state_root, args.cache_root)
    print(
        json.dumps(
            {
                "decision": "pass",
                "archive_source_count": proof["archive_source_count"],
                "analysis_rows": {
                    cell["symbol"]: cell["analysis_rows"] for cell in proof["cells"]
                },
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
