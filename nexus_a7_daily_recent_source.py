"""Memory-bounded 30-day official Bybit Spot source for A7 research.

The source is deliberately built from daily public Bybit trade archives only.
This avoids the large monthly archive parser path while preserving exact
4-symbol x 15m/1h/4h provenance and a recent complete 30-day evaluation window.
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

import bybit_spot_archive_collector as collector
import bybit_spot_backfill as backfill
import nexus_multipair_recent_archive_runtime_snapshot as recent
from nexus_multipair_trusted_surface import SYMBOLS, TIMEFRAMES

SCHEMA = "nexus.a7-daily-recent-source.v1"
PROOF_NAME = "_a7_daily_recent_source_proof.json"
WINDOW_DAYS = 30
EXPECTED_ARCHIVES = WINDOW_DAYS * len(SYMBOLS)
MAX_FRAME_BYTES = 500 * 1024 * 1024
_SHA40 = re.compile(r"^[0-9a-f]{40}$")


class A7DailyRecentSourceError(RuntimeError):
    pass


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def utc_day(value: str) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        return stamp.tz_localize("UTC").normalize()
    return stamp.tz_convert("UTC").normalize()


def window_start(latest_complete_date: str) -> str:
    return (utc_day(latest_complete_date) - pd.Timedelta(days=WINDOW_DAYS - 1)).strftime("%Y-%m-%d")


def expected_days(start_date: str, end_date: str) -> tuple[str, ...]:
    days = tuple(ts.strftime("%Y-%m-%d") for ts in pd.date_range(start_date, end_date, freq="1D"))
    if len(days) != WINDOW_DAYS:
        raise A7DailyRecentSourceError(f"A7 recent window must contain exactly {WINDOW_DAYS} complete days")
    return days


def daily_only_inventory(inventory: backfill.ArchiveInventory) -> backfill.ArchiveInventory:
    return backfill.ArchiveInventory(
        symbol=inventory.symbol,
        monthly={},
        daily=dict(inventory.daily),
    )


def _read_json(path: Path, max_bytes: int = 10_000_000) -> Any:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > max_bytes:
        raise A7DailyRecentSourceError(f"missing or unsafe JSON source: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise A7DailyRecentSourceError(f"unreadable JSON source: {path}") from exc


def _load_frame(
    state_root: Path,
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    canonical = collector.canonical_symbol(symbol)
    path = state_root / "bybit_market" / canonical / f"{timeframe}.parquet"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FRAME_BYTES:
        raise A7DailyRecentSourceError(f"missing or unsafe frame: {symbol}/{timeframe}")
    frame = pd.read_parquet(path).copy()
    if frame.columns.tolist() != collector.CANONICAL_COLUMNS:
        raise A7DailyRecentSourceError(f"unexpected frame schema: {symbol}/{timeframe}")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    frame = frame.sort_values("timestamp").reset_index(drop=True)

    expected = collector.expected_index(start_date, end_date, timeframe).as_unit("ns")
    actual = pd.DatetimeIndex(frame["timestamp"]).as_unit("ns")
    unique = actual.drop_duplicates().sort_values()
    missing = expected.difference(unique)
    unexpected = unique.difference(expected)
    if (
        len(frame) != len(expected)
        or len(unique) != len(expected)
        or not missing.empty
        or not unexpected.empty
        or set(frame["symbol"].astype(str)) != {canonical}
        or set(frame["timeframe"].astype(str)) != {timeframe}
    ):
        raise A7DailyRecentSourceError(
            f"recent frame grid mismatch: {symbol}/{timeframe}; "
            f"rows={len(frame)} expected={len(expected)} "
            f"missing={len(missing)} unexpected={len(unexpected)}"
        )

    numeric = frame[["open", "high", "low", "close", "volume"]].astype(float)
    if (
        not np.isfinite(numeric.to_numpy()).all()
        or (numeric[["open", "high", "low", "close"]] <= 0).any().any()
        or (numeric["volume"] < 0).any()
        or (numeric["high"] < numeric[["open", "close", "low"]].max(axis=1)).any()
        or (numeric["low"] > numeric[["open", "close", "high"]].min(axis=1)).any()
    ):
        raise A7DailyRecentSourceError(f"recent frame OHLCV integrity failed: {symbol}/{timeframe}")
    frame["symbol"] = symbol
    frame["timeframe"] = timeframe
    return frame


def _frame_digest(frame: pd.DataFrame) -> str:
    rows = [
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
    return digest(rows)


def build_proof(
    state_root: Path,
    *,
    source_sha: str,
    acquired_at_ms: int,
) -> dict[str, Any]:
    state = state_root.resolve()
    if not _SHA40.fullmatch(source_sha):
        raise A7DailyRecentSourceError("source_sha must be an exact lower-case git SHA")
    if isinstance(acquired_at_ms, bool) or not isinstance(acquired_at_ms, int) or acquired_at_ms <= 0:
        raise A7DailyRecentSourceError("acquired_at_ms must be a positive integer")

    report = _read_json(state / backfill.REPORT_NAME)
    plan = _read_json(state / backfill.PLAN_NAME)
    if not isinstance(report, Mapping) or not isinstance(plan, Mapping):
        raise A7DailyRecentSourceError("recent backfill report or plan is invalid")
    config = report.get("configuration")
    summary = report.get("summary")
    if not isinstance(config, Mapping) or not isinstance(summary, Mapping):
        raise A7DailyRecentSourceError("recent backfill report structure is invalid")
    start_date = str(config.get("start_date", ""))
    end_date = str(config.get("end_date", ""))
    days = expected_days(start_date, end_date)
    if (
        config.get("symbols") != list(SYMBOLS)
        or config.get("max_archives_per_run") != EXPECTED_ARCHIVES
        or summary.get("plan_units") != WINDOW_DAYS
        or summary.get("plan_archives") != EXPECTED_ARCHIVES
        or summary.get("completed_units") != WINDOW_DAYS
        or summary.get("remaining_units") != 0
        or summary.get("run_failures") != 0
        or summary.get("backfill_complete") is not True
        or summary.get("current_dataset_integrity_ok") is not True
        or report.get("run_failures") != []
    ):
        raise A7DailyRecentSourceError("daily recent backfill is incomplete")

    normalized_plan = recent._normalize_plan(plan, start_date=start_date, end_date=end_date)
    if (
        len(normalized_plan) != WINDOW_DAYS
        or any(unit["kind"] != "daily" for unit in normalized_plan)
        or tuple(unit["start_date"] for unit in normalized_plan) != days
        or any(unit["start_date"] != unit["end_date"] for unit in normalized_plan)
    ):
        raise A7DailyRecentSourceError("A7 source plan must be exactly 30 daily archive units")
    sources, source_manifest_digest = recent._source_evidence(state, normalized_plan)
    if len(sources) != EXPECTED_ARCHIVES:
        raise A7DailyRecentSourceError("A7 source provenance cardinality mismatch")

    data_as_of_ms = int((utc_day(end_date) + pd.Timedelta(days=1)).value // 1_000_000)
    source_lag_ms = acquired_at_ms - data_as_of_ms
    if source_lag_ms < 0 or source_lag_ms > recent.MAX_SOURCE_LAG_MS:
        raise A7DailyRecentSourceError(
            f"A7 recent source is outside recency bound: lag_ms={source_lag_ms}"
        )

    frames: dict[tuple[str, str], pd.DataFrame] = {}
    frame_digests: dict[str, str] = {}
    timestamp_refs: dict[str, pd.DatetimeIndex] = {}
    cells: list[dict[str, Any]] = []
    for timeframe in TIMEFRAMES:
        for symbol in SYMBOLS:
            frame = _load_frame(state, symbol, timeframe, start_date, end_date)
            idx = pd.DatetimeIndex(frame["timestamp"]).as_unit("ns")
            reference = timestamp_refs.setdefault(timeframe, idx)
            if (
                len(reference) != len(idx)
                or not reference.difference(idx).empty
                or not idx.difference(reference).empty
            ):
                raise A7DailyRecentSourceError(f"four-symbol timestamps are not aligned: {timeframe}")
            key = f"{symbol}/{timeframe}"
            frame_digest = _frame_digest(frame)
            frames[(symbol, timeframe)] = frame
            frame_digests[key] = frame_digest
            cells.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "row_count": len(frame),
                    "first_open_utc": pd.Timestamp(frame["timestamp"].iloc[0]).isoformat(),
                    "last_open_utc": pd.Timestamp(frame["timestamp"].iloc[-1]).isoformat(),
                    "frame_digest": frame_digest,
                }
            )

    dataset_digest = digest(
        {
            "source_manifest_digest": source_manifest_digest,
            "plan": normalized_plan,
            "frames": frame_digests,
        }
    )
    core = {
        "schema": SCHEMA,
        "source_sha": source_sha,
        "venue": "bybit",
        "market": "spot",
        "archive_base_url": recent.archive_audit.ARCHIVE_BASE_URL,
        "archive_granularity": "daily",
        "window_days": WINDOW_DAYS,
        "source_window_start": start_date,
        "source_window_end": end_date,
        "latest_common_complete_date": end_date,
        "acquired_at_ms": acquired_at_ms,
        "data_as_of_ms": data_as_of_ms,
        "source_lag_ms_at_acquisition": source_lag_ms,
        "max_source_lag_ms": recent.MAX_SOURCE_LAG_MS,
        "symbols": list(SYMBOLS),
        "timeframes": list(TIMEFRAMES),
        "archive_plan_units": normalized_plan,
        "archive_plan_digest": digest(normalized_plan),
        "archive_sources": sources,
        "archive_source_count": len(sources),
        "archive_source_manifest_digest": source_manifest_digest,
        "cells": sorted(cells, key=lambda row: (row["symbol"], row["timeframe"])),
        "dataset_digest": dataset_digest,
        "data_origin": recent.DATA_ORIGIN,
        "runtime_requalification_recency_verified": True,
        "live_freshness_claimed": False,
        "research_only": True,
        "paper_only": True,
        "paper_execution_started": False,
        "automatic_strategy_promotion": False,
        "derivative_execution_authority": False,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "real_exchange_orders": False,
        "owner_500_usdt_profile_touched": False,
    }
    return {**core, "proof_sha256": digest(core)}


def verify_proof(
    state_root: Path,
    value: Mapping[str, Any],
    *,
    source_sha: str,
    now_ms: int,
) -> None:
    if not isinstance(value, Mapping):
        raise A7DailyRecentSourceError("A7 source proof is not an object")
    acquired_at_ms = value.get("acquired_at_ms")
    if isinstance(acquired_at_ms, bool) or not isinstance(acquired_at_ms, int):
        raise A7DailyRecentSourceError("A7 source proof acquisition time is invalid")
    expected = build_proof(
        state_root,
        source_sha=source_sha,
        acquired_at_ms=acquired_at_ms,
    )
    if dict(value) != expected:
        raise A7DailyRecentSourceError("A7 source proof or raw source state does not match")
    data_as_of_ms = int(value["data_as_of_ms"])
    if (
        isinstance(now_ms, bool)
        or not isinstance(now_ms, int)
        or now_ms < acquired_at_ms
        or now_ms - data_as_of_ms > recent.MAX_SOURCE_LAG_MS
    ):
        raise A7DailyRecentSourceError("A7 source proof is outside current source-recency bound")


def load_verified_frames(
    state_root: Path,
    proof: Mapping[str, Any],
) -> dict[tuple[str, str], pd.DataFrame]:
    start_date = str(proof["source_window_start"])
    end_date = str(proof["source_window_end"])
    return {
        (symbol, timeframe): _load_frame(
            state_root.resolve(),
            symbol,
            timeframe,
            start_date,
            end_date,
        )
        for symbol in SYMBOLS
        for timeframe in TIMEFRAMES
    }


def acquire(
    state_root: Path,
    cache_root: Path,
    output_root: Path,
    *,
    source_sha: str,
    now_ms: int,
) -> dict[str, Any]:
    inventories = {symbol: backfill.fetch_archive_inventory(symbol) for symbol in SYMBOLS}
    latest = recent.select_latest_common_complete_date(inventories, now_ms=now_ms)
    start = window_start(latest)
    days = expected_days(start, latest)
    for symbol in SYMBOLS:
        missing = [day for day in days if day not in inventories[symbol].daily]
        if missing:
            raise A7DailyRecentSourceError(
                f"daily archive coverage incomplete for {symbol}: {missing[:5]}"
            )
    daily_inventories = {
        symbol: daily_only_inventory(inventories[symbol]) for symbol in SYMBOLS
    }
    report = backfill.run_backfill(
        start_date=start,
        end_date=latest,
        state_root=state_root,
        cache_root=cache_root,
        max_archives_per_run=EXPECTED_ARCHIVES,
        symbols=SYMBOLS,
        inventory_fetcher=lambda symbol: daily_inventories[symbol],
        clean=True,
    )
    if report.get("summary", {}).get("backfill_complete") is not True:
        raise A7DailyRecentSourceError("daily recent A7 backfill did not complete")
    proof = build_proof(
        state_root,
        source_sha=source_sha,
        acquired_at_ms=now_ms,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / PROOF_NAME).write_text(
        json.dumps(proof, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    verify_proof(state_root, proof, source_sha=source_sha, now_ms=now_ms)
    return proof


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--now-ms", type=int, required=True)
    args = parser.parse_args()
    proof = acquire(
        args.state_root,
        args.cache_root,
        args.output_root,
        source_sha=args.source_sha,
        now_ms=args.now_ms,
    )
    print(
        json.dumps(
            {
                "decision": "pass",
                "source_window_start": proof["source_window_start"],
                "source_window_end": proof["source_window_end"],
                "archive_source_count": proof["archive_source_count"],
                "dataset_digest": proof["dataset_digest"],
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
