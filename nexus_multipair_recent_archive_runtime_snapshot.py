"""Recent official Bybit archive transport for Multi-Pair requalification.

Bybit's public REST API can reject both the physical EEA runner and US-hosted CI by
region. This module does not bypass that restriction. It independently acquires the
latest common *complete UTC day* available from Bybit's official Spot trade archive,
aggregates it with enough preceding official archive history for 240 rows at 4h, and
emits a digest-pinned 12-cell Research snapshot.

Archive recency and Live freshness are intentionally different claims. The snapshot
must be within a bounded archive-source lag, but ``live_freshness_claimed`` is always
False. It is independent requalification evidence, not a current-tick feed, and grants
no Candidate/Paper execution/promotion/Live authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

import bybit_spot_archive_audit as archive_audit
import bybit_spot_archive_collector as collector
import bybit_spot_backfill as backfill
import nexus_multipair_archive_snapshot as historical_archive
import nexus_multipair_runtime_requalification_snapshot as rest_runtime
import nexus_multipair_strategy_proposal_requalification as multipair_requal
import nexus_strategy_proposal_runtime_requalification as legacy_requal
from nexus_multipair_trusted_surface import SYMBOLS, TIMEFRAMES
from phase6_research_pipeline import run_research_job
from product_research_runtime import COST_MODEL, KILL_CRITERIA


SCHEMA = "nexus.multipair-runtime-requalification-recent-archive-snapshot.v1"
HISTORY_LIMIT = 240
MAX_SOURCE_LAG_MS = 36 * 60 * 60 * 1000
MAX_TRANSPORT_AGE_MS = 20 * 60 * 1000
TRANSPORT_ORIGIN = "digest_pinned_recent_official_bybit_spot_archive_snapshot"
DATA_ORIGIN = "official_public_bybit_spot_trade_archive_aggregated_recent"
INNER_ARCHIVE_NAME = rest_runtime.INNER_ARCHIVE_NAME
EXPECTED_CELLS = len(SYMBOLS) * len(TIMEFRAMES)
MAX_ARCHIVE_BYTES = historical_archive.MAX_ARCHIVE_BYTES
MAX_FRAME_BYTES = historical_archive.MAX_FRAME_BYTES
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_COLUMNS = historical_archive._REQUIRED_COLUMNS
_QUALITY_ZERO_FIELDS = historical_archive._QUALITY_ZERO_FIELDS


class MultiPairRecentArchiveRuntimeError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MultiPairRecentArchiveRuntimeError("recent archive evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(value), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _stored_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return historical_archive._stored_rows(frame)


def _utc_day(value: str) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    else:
        stamp = stamp.tz_convert("UTC")
    return stamp.normalize()


def select_latest_common_complete_date(
    inventories: Mapping[str, backfill.ArchiveInventory],
    *,
    now_ms: int,
    max_source_lag_ms: int = MAX_SOURCE_LAG_MS,
) -> str:
    if isinstance(now_ms, bool) or not isinstance(now_ms, int) or now_ms <= 0:
        raise MultiPairRecentArchiveRuntimeError("now_ms must be a positive integer")
    if isinstance(max_source_lag_ms, bool) or not isinstance(max_source_lag_ms, int) or max_source_lag_ms <= 0:
        raise MultiPairRecentArchiveRuntimeError("max_source_lag_ms must be positive")
    if set(inventories) != set(SYMBOLS):
        raise MultiPairRecentArchiveRuntimeError("recent archive inventory surface is incomplete")
    common: set[str] | None = None
    for symbol in SYMBOLS:
        inventory = inventories[symbol]
        if inventory.symbol != symbol:
            raise MultiPairRecentArchiveRuntimeError("recent archive inventory identity mismatch")
        dates = set(inventory.daily)
        common = dates if common is None else common.intersection(dates)
    assert common is not None
    now = pd.Timestamp(now_ms, unit="ms", tz="UTC")
    latest_complete = now.normalize() - pd.Timedelta(days=1)
    eligible = sorted(date for date in common if _utc_day(date) <= latest_complete)
    if not eligible:
        raise MultiPairRecentArchiveRuntimeError("no common complete official Bybit archive day is available")
    latest = eligible[-1]
    data_as_of_ms = int((_utc_day(latest) + pd.Timedelta(days=1)).value // 1_000_000)
    lag = now_ms - data_as_of_ms
    if lag < 0 or lag > max_source_lag_ms:
        raise MultiPairRecentArchiveRuntimeError(
            f"latest common official Bybit archive day is stale: {latest} lag_ms={lag}"
        )
    return latest


def source_window_start(latest_complete_date: str) -> str:
    latest = _utc_day(latest_complete_date)
    period = latest.to_period("M") - 2
    return period.start_time.strftime("%Y-%m-%d")


def _normalize_plan(plan: Mapping[str, Any], *, start_date: str, end_date: str) -> list[dict[str, Any]]:
    units = plan.get("units")
    if (
        plan.get("start_date") != start_date
        or plan.get("end_date") != end_date
        or plan.get("symbols") != list(SYMBOLS)
        or plan.get("unavailable_dates") != []
        or not isinstance(units, list)
        or not units
    ):
        raise MultiPairRecentArchiveRuntimeError("recent archive plan is incomplete")
    normalized: list[dict[str, Any]] = []
    previous_end: pd.Timestamp | None = None
    for row in units:
        if not isinstance(row, Mapping):
            raise MultiPairRecentArchiveRuntimeError("recent archive plan unit is invalid")
        kind = str(row.get("kind", ""))
        unit_id = str(row.get("unit_id", ""))
        unit_start = str(row.get("start_date", ""))
        unit_end = str(row.get("end_date", ""))
        filenames = row.get("filenames")
        if kind not in {"monthly", "daily"} or not isinstance(filenames, Mapping):
            raise MultiPairRecentArchiveRuntimeError("recent archive plan unit type is invalid")
        if set(filenames) != set(SYMBOLS):
            raise MultiPairRecentArchiveRuntimeError("recent archive plan filenames are incomplete")
        start = _utc_day(unit_start)
        end = _utc_day(unit_end)
        if end < start or (previous_end is not None and start != previous_end + pd.Timedelta(days=1)):
            raise MultiPairRecentArchiveRuntimeError("recent archive plan is not contiguous")
        previous_end = end
        checked: dict[str, str] = {}
        for symbol in SYMBOLS:
            filename = str(filenames[symbol])
            if kind == "daily":
                if unit_start != unit_end or unit_id != f"daily:{unit_start}" or filename != f"{symbol}_{unit_start}.csv.gz":
                    raise MultiPairRecentArchiveRuntimeError("recent daily archive filename contract mismatch")
            else:
                month = unit_start[:7]
                month_period = pd.Period(month, freq="M")
                if (
                    unit_id != f"monthly:{month}"
                    or unit_start != month_period.start_time.strftime("%Y-%m-%d")
                    or unit_end != month_period.end_time.strftime("%Y-%m-%d")
                    or filename != f"{symbol}-{month}.csv.gz"
                ):
                    raise MultiPairRecentArchiveRuntimeError("recent monthly archive filename contract mismatch")
            checked[symbol] = filename
        normalized.append(
            {
                "unit_id": unit_id,
                "kind": kind,
                "start_date": unit_start,
                "end_date": unit_end,
                "filenames": checked,
            }
        )
    if normalized[0]["start_date"] != start_date or normalized[-1]["end_date"] != end_date:
        raise MultiPairRecentArchiveRuntimeError("recent archive plan does not cover the requested window")
    return normalized


def _source_evidence(
    state_root: Path,
    plan_units: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    path = state_root / backfill.SOURCE_MANIFEST_NAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MultiPairRecentArchiveRuntimeError("recent archive source manifest is unavailable") from exc
    expected = {
        (unit["unit_id"], symbol): (unit, unit["filenames"][symbol])
        for unit in plan_units
        for symbol in SYMBOLS
    }
    if not isinstance(raw, list) or len(raw) != len(expected):
        raise MultiPairRecentArchiveRuntimeError("recent archive source manifest cardinality mismatch")
    seen: set[tuple[str, str]] = set()
    evidence: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, Mapping):
            raise MultiPairRecentArchiveRuntimeError("recent archive source record is invalid")
        unit_id = str(row.get("unit_id", ""))
        symbol = str(row.get("symbol", "")).upper()
        key = (unit_id, symbol)
        if key not in expected or key in seen:
            raise MultiPairRecentArchiveRuntimeError("recent archive source identity is unexpected or duplicated")
        seen.add(key)
        unit, filename = expected[key]
        url = backfill.archive_url(symbol, filename)
        sha = str(row.get("sha256", "")).lower()
        size = row.get("size_bytes")
        if (
            row.get("unit_kind") != unit["kind"]
            or row.get("filename") != filename
            or row.get("url") != url
            or not url.startswith(archive_audit.ARCHIVE_BASE_URL + "/")
            or row.get("start_date") != unit["start_date"]
            or row.get("end_date") != unit["end_date"]
            or row.get("http_status") != 200
            or isinstance(size, bool)
            or not isinstance(size, int)
            or not 0 < size <= MAX_ARCHIVE_BYTES
            or not _HEX64.fullmatch(sha)
            or int(row.get("source_rows", 0)) <= 0
            or int(row.get("valid_trade_rows", 0)) <= 0
            or any(int(row.get(field, 0)) != 0 for field in _QUALITY_ZERO_FIELDS)
        ):
            raise MultiPairRecentArchiveRuntimeError(f"recent official archive provenance failed: {unit_id}/{symbol}")
        evidence.append(
            {
                "unit_id": unit_id,
                "unit_kind": unit["kind"],
                "start_date": unit["start_date"],
                "end_date": unit["end_date"],
                "symbol": symbol,
                "filename": filename,
                "url": url,
                "sha256": sha,
                "size_bytes": size,
                "http_status": 200,
                "source_rows": int(row["source_rows"]),
                "valid_trade_rows": int(row["valid_trade_rows"]),
            }
        )
    if seen != set(expected):
        raise MultiPairRecentArchiveRuntimeError("recent archive source surface is incomplete")
    evidence.sort(key=lambda row: (row["unit_id"], row["symbol"]))
    return evidence, _digest(evidence)


def _load_tail(state_root: Path, symbol: str, timeframe: str, *, data_as_of_ms: int) -> pd.DataFrame:
    source = state_root / "bybit_market" / collector.canonical_symbol(symbol) / f"{timeframe}.parquet"
    if source.is_symlink() or not source.is_file() or source.stat().st_size > MAX_FRAME_BYTES:
        raise MultiPairRecentArchiveRuntimeError(f"recent archive frame is missing or unsafe: {symbol}/{timeframe}")
    frame = pd.read_parquet(source)
    if frame.columns.tolist() != collector.CANONICAL_COLUMNS or len(frame) < HISTORY_LIMIT:
        raise MultiPairRecentArchiveRuntimeError(f"recent archive frame cannot supply 240 rows: {symbol}/{timeframe}")
    frame = frame.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    frame = frame.sort_values("timestamp").tail(HISTORY_LIMIT).reset_index(drop=True)
    for field in ("open", "high", "low", "close", "volume"):
        frame[field] = pd.to_numeric(frame[field], errors="raise")
    frame["symbol"] = symbol
    frame["timeframe"] = timeframe
    frame = frame.loc[:, _REQUIRED_COLUMNS]
    timestamps = pd.DatetimeIndex(frame["timestamp"])
    step = archive_audit.TIMEFRAME_DELTAS[timeframe]
    expected_last = pd.Timestamp(data_as_of_ms, unit="ms", tz="UTC") - step
    if (
        len(frame) != HISTORY_LIMIT
        or timestamps.duplicated().any()
        or not timestamps.is_monotonic_increasing
        or not bool((timestamps[1:] - timestamps[:-1] == step).all())
        or timestamps[-1] != expected_last
        or set(frame["symbol"].astype(str)) != {symbol}
        or set(frame["timeframe"].astype(str)) != {timeframe}
        or bool((frame["volume"] < 0).any())
        or bool((frame[["open", "high", "low", "close"]] <= 0).any().any())
        or bool((frame["high"] < frame[["open", "close", "low"]].max(axis=1)).any())
        or bool((frame["low"] > frame[["open", "close", "high"]].min(axis=1)).any())
    ):
        raise MultiPairRecentArchiveRuntimeError(f"recent archive tail integrity failed: {symbol}/{timeframe}")
    return frame


def build_snapshot_from_backfill(
    *,
    state_root: str | Path,
    output_root: str | Path,
    report: Mapping[str, Any],
    source_sha: str,
    acquired_at_ms: int,
    latest_common_complete_date: str,
    max_source_lag_ms: int = MAX_SOURCE_LAG_MS,
) -> dict[str, Any]:
    source_sha = str(source_sha).strip().lower()
    if not _HEX40.fullmatch(source_sha):
        raise MultiPairRecentArchiveRuntimeError("source_sha must be an exact Git SHA")
    if isinstance(acquired_at_ms, bool) or not isinstance(acquired_at_ms, int) or acquired_at_ms <= 0:
        raise MultiPairRecentArchiveRuntimeError("acquired_at_ms must be positive")
    if len(SYMBOLS) != 4 or EXPECTED_CELLS != 12:
        raise MultiPairRecentArchiveRuntimeError("trusted Multi-Pair surface is not 12 cells")

    start_date = source_window_start(latest_common_complete_date)
    end_date = latest_common_complete_date
    summary = report.get("summary")
    configuration = report.get("configuration")
    if (
        not isinstance(summary, Mapping)
        or not isinstance(configuration, Mapping)
        or configuration.get("start_date") != start_date
        or configuration.get("end_date") != end_date
        or configuration.get("symbols") != list(SYMBOLS)
        or summary.get("remaining_units") != 0
        or summary.get("run_failures") != 0
        or summary.get("backfill_complete") is not True
        or summary.get("current_dataset_integrity_ok") is not True
        or report.get("run_failures") != []
    ):
        raise MultiPairRecentArchiveRuntimeError("recent official archive backfill did not complete")

    state = Path(state_root).resolve()
    try:
        raw_plan = json.loads((state / backfill.PLAN_NAME).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MultiPairRecentArchiveRuntimeError("recent archive plan is unavailable") from exc
    plan_units = _normalize_plan(raw_plan, start_date=start_date, end_date=end_date)
    sources, source_manifest_digest = _source_evidence(state, plan_units)
    data_as_of_ms = int((_utc_day(end_date) + pd.Timedelta(days=1)).value // 1_000_000)
    source_lag_ms = acquired_at_ms - data_as_of_ms
    if source_lag_ms < 0 or source_lag_ms > max_source_lag_ms:
        raise MultiPairRecentArchiveRuntimeError("recent archive source lag exceeds the accepted bound")

    output = Path(output_root).resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    cells: list[dict[str, Any]] = []
    timestamps_by_timeframe: dict[str, pd.Series] = {}
    for timeframe in TIMEFRAMES:
        for symbol in SYMBOLS:
            frame = _load_tail(state, symbol, timeframe, data_as_of_ms=data_as_of_ms)
            timestamps = frame["timestamp"].reset_index(drop=True)
            reference = timestamps_by_timeframe.setdefault(timeframe, timestamps)
            if not reference.equals(timestamps):
                raise MultiPairRecentArchiveRuntimeError(f"recent archive four-symbol timestamps are not aligned: {timeframe}")
            target = output / "bybit_market" / symbol / f"{timeframe}.parquet"
            target.parent.mkdir(parents=True, exist_ok=True)
            frame.to_parquet(target, index=False)
            cells.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "row_count": HISTORY_LIMIT,
                    "first_open_time_ms": int(frame["timestamp"].iloc[0].value // 1_000_000),
                    "last_open_time_ms": int(frame["timestamp"].iloc[-1].value // 1_000_000),
                    "frame_digest": _digest(_stored_rows(frame)),
                }
            )
    cells.sort(key=lambda row: (row["symbol"], row["timeframe"]))
    core = {
        "schema_version": SCHEMA,
        "source_sha": source_sha,
        "as_of_ms": acquired_at_ms,
        "acquired_at_ms": acquired_at_ms,
        "data_as_of_ms": data_as_of_ms,
        "latest_common_complete_date": end_date,
        "source_window_start": start_date,
        "source_window_end": end_date,
        "source_lag_ms_at_acquisition": source_lag_ms,
        "max_source_lag_ms": max_source_lag_ms,
        "archive_base_url": archive_audit.ARCHIVE_BASE_URL,
        "archive_plan_units": plan_units,
        "archive_plan_digest": _digest(plan_units),
        "archive_sources": sources,
        "archive_source_count": len(sources),
        "archive_source_manifest_digest": source_manifest_digest,
        "symbols": list(SYMBOLS),
        "timeframes": list(TIMEFRAMES),
        "cell_count": EXPECTED_CELLS,
        "history_limit": HISTORY_LIMIT,
        "cells": cells,
        "data_origin": DATA_ORIGIN,
        "runtime_requalification_recency_verified": True,
        "live_freshness_claimed": False,
        "research_only": True,
        "paper_execution_started": False,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "real_exchange_orders": False,
        "automatic_strategy_promotion": False,
        "silent_exchange_substitution": False,
        "third_party_proxy_used": False,
        "issue_984_state_touched": False,
        "persistent_runtime_database_on_github": False,
    }
    result = {**core, "snapshot_digest": _digest(core)}
    _atomic_json(output / "snapshot-manifest.json", result)
    return result


def verify_recent_archive_runtime_snapshot(
    root: str | Path,
    value: Mapping[str, Any],
    *,
    source_sha: str,
    now_ms: int,
    max_transport_age_ms: int = MAX_TRANSPORT_AGE_MS,
) -> dict[str, Any]:
    checks = {
        "schema": False,
        "digest": False,
        "source": False,
        "shape": False,
        "frames": False,
        "transport_age": False,
        "source_recency": False,
        "authority": False,
    }
    try:
        source_sha = str(source_sha).strip().lower()
        core = dict(value)
        claimed = core.pop("snapshot_digest", None)
        checks["schema"] = bool(core.get("schema_version") == SCHEMA and _HEX64.fullmatch(str(claimed or "")))
        checks["digest"] = claimed == _digest(core)
        acquired = core.get("acquired_at_ms")
        data_as_of = core.get("data_as_of_ms")
        max_source_lag = core.get("max_source_lag_ms")
        checks["transport_age"] = bool(
            isinstance(acquired, int) and not isinstance(acquired, bool)
            and core.get("as_of_ms") == acquired
            and 0 <= now_ms - acquired <= max_transport_age_ms
        )
        checks["source_recency"] = bool(
            isinstance(data_as_of, int) and not isinstance(data_as_of, bool)
            and isinstance(max_source_lag, int) and not isinstance(max_source_lag, bool)
            and 0 < max_source_lag <= MAX_SOURCE_LAG_MS
            and core.get("source_lag_ms_at_acquisition") == acquired - data_as_of
            and 0 <= now_ms - data_as_of <= max_source_lag
            and core.get("runtime_requalification_recency_verified") is True
            and core.get("live_freshness_claimed") is False
        )
        plan_units = core.get("archive_plan_units")
        sources = core.get("archive_sources")
        normalized_plan = _normalize_plan(
            {
                "start_date": core.get("source_window_start"),
                "end_date": core.get("source_window_end"),
                "symbols": list(SYMBOLS),
                "unavailable_dates": [],
                "units": plan_units,
            },
            start_date=str(core.get("source_window_start", "")),
            end_date=str(core.get("source_window_end", "")),
        )
        expected_source_pairs = {(unit["unit_id"], symbol) for unit in normalized_plan for symbol in SYMBOLS}
        checks["source"] = bool(
            _HEX40.fullmatch(source_sha)
            and core.get("source_sha") == source_sha
            and core.get("latest_common_complete_date") == core.get("source_window_end")
            and core.get("archive_base_url") == archive_audit.ARCHIVE_BASE_URL
            and core.get("archive_plan_digest") == _digest(normalized_plan)
            and isinstance(sources, list)
            and core.get("archive_source_count") == len(sources) == len(expected_source_pairs)
            and core.get("archive_source_manifest_digest") == _digest(sources)
            and {(row.get("unit_id"), row.get("symbol")) for row in sources if isinstance(row, Mapping)} == expected_source_pairs
            and all(
                isinstance(row, Mapping)
                and row.get("url") == backfill.archive_url(str(row.get("symbol")), str(row.get("filename")))
                and str(row.get("url", "")).startswith(archive_audit.ARCHIVE_BASE_URL + "/")
                and row.get("http_status") == 200
                and _HEX64.fullmatch(str(row.get("sha256", "")))
                and isinstance(row.get("size_bytes"), int)
                and 0 < int(row.get("size_bytes")) <= MAX_ARCHIVE_BYTES
                and int(row.get("source_rows", 0)) > 0
                and int(row.get("valid_trade_rows", 0)) > 0
                for row in sources
            )
        )
        cells = core.get("cells")
        expected_cells = {(symbol, timeframe) for symbol in SYMBOLS for timeframe in TIMEFRAMES}
        checks["shape"] = bool(
            core.get("symbols") == list(SYMBOLS)
            and core.get("timeframes") == list(TIMEFRAMES)
            and core.get("cell_count") == EXPECTED_CELLS == 12
            and core.get("history_limit") == HISTORY_LIMIT
            and isinstance(cells, list)
            and len(cells) == EXPECTED_CELLS
            and {(row.get("symbol"), row.get("timeframe")) for row in cells if isinstance(row, Mapping)} == expected_cells
        )
        frames_ok = checks["shape"]
        if frames_ok:
            base = Path(root).resolve()
            for cell in cells:
                symbol = str(cell["symbol"])
                timeframe = str(cell["timeframe"])
                path = base / "bybit_market" / symbol / f"{timeframe}.parquet"
                if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FRAME_BYTES:
                    frames_ok = False
                    break
                frame = pd.read_parquet(path)
                if frame.columns.tolist() != _REQUIRED_COLUMNS or len(frame) != HISTORY_LIMIT:
                    frames_ok = False
                    break
                frame = frame.copy()
                frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
                timestamps = pd.DatetimeIndex(frame["timestamp"])
                step = archive_audit.TIMEFRAME_DELTAS[timeframe]
                expected_last = pd.Timestamp(int(data_as_of), unit="ms", tz="UTC") - step
                if (
                    timestamps.duplicated().any()
                    or not timestamps.is_monotonic_increasing
                    or not bool((timestamps[1:] - timestamps[:-1] == step).all())
                    or timestamps[-1] != expected_last
                    or cell.get("row_count") != HISTORY_LIMIT
                    or cell.get("first_open_time_ms") != int(timestamps[0].value // 1_000_000)
                    or cell.get("last_open_time_ms") != int(timestamps[-1].value // 1_000_000)
                    or cell.get("frame_digest") != _digest(_stored_rows(frame))
                    or set(frame["symbol"].astype(str)) != {symbol}
                    or set(frame["timeframe"].astype(str)) != {timeframe}
                ):
                    frames_ok = False
                    break
        checks["frames"] = bool(frames_ok)
        checks["authority"] = bool(
            core.get("data_origin") == DATA_ORIGIN
            and core.get("runtime_requalification_recency_verified") is True
            and core.get("live_freshness_claimed") is False
            and core.get("research_only") is True
            and core.get("paper_execution_started") is False
            and core.get("live_trading_authority") is False
            and core.get("private_credentials_used") is False
            and core.get("real_exchange_orders") is False
            and core.get("automatic_strategy_promotion") is False
            and core.get("silent_exchange_substitution") is False
            and core.get("third_party_proxy_used") is False
            and core.get("issue_984_state_touched") is False
            and core.get("persistent_runtime_database_on_github") is False
        )
    except Exception:
        pass
    return {
        "decision": "pass" if all(checks.values()) else "reject",
        "checks": checks,
        "snapshot_digest": value.get("snapshot_digest"),
    }


def collect_recent_archive_runtime_snapshot(
    *,
    state_root: str | Path,
    cache_root: str | Path,
    output_root: str | Path,
    source_sha: str,
    now_ms: int,
) -> dict[str, Any]:
    inventories = {symbol: backfill.fetch_archive_inventory(symbol) for symbol in SYMBOLS}
    latest = select_latest_common_complete_date(inventories, now_ms=now_ms)
    start = source_window_start(latest)
    plan = backfill.build_archive_plan(inventories, start, latest, symbols=SYMBOLS)
    max_archives = max(len(SYMBOLS), int(plan["total_archives"]))
    report = backfill.run_backfill(
        start_date=start,
        end_date=latest,
        state_root=Path(state_root),
        cache_root=Path(cache_root),
        max_archives_per_run=max_archives,
        symbols=SYMBOLS,
        inventory_fetcher=lambda symbol: inventories[symbol],
        clean=True,
    )
    result = build_snapshot_from_backfill(
        state_root=state_root,
        output_root=output_root,
        report=report,
        source_sha=source_sha,
        acquired_at_ms=now_ms,
        latest_common_complete_date=latest,
    )
    verification = verify_recent_archive_runtime_snapshot(
        output_root, result, source_sha=source_sha, now_ms=now_ms
    )
    if verification["decision"] != "pass":
        raise MultiPairRecentArchiveRuntimeError("recent archive runtime snapshot rejected after acquisition")
    return result


def deterministic_pack(root: str | Path, output: str | Path) -> str:
    source = Path(root).resolve()
    manifest_path = source / "snapshot-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MultiPairRecentArchiveRuntimeError("recent archive manifest unavailable before pack") from exc
    if manifest.get("schema_version") != SCHEMA or manifest.get("history_limit") != HISTORY_LIMIT:
        raise MultiPairRecentArchiveRuntimeError("recent archive pack identity mismatch")
    files = [manifest_path] + [
        source / "bybit_market" / symbol / f"{timeframe}.parquet"
        for symbol in SYMBOLS
        for timeframe in TIMEFRAMES
    ]
    if any(path.is_symlink() or not path.is_file() for path in files):
        raise MultiPairRecentArchiveRuntimeError("recent archive pack surface is incomplete")
    target = Path(output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED) as archive:
        for path in sorted(files, key=lambda item: item.relative_to(source).as_posix()):
            name = path.relative_to(source).as_posix()
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    return _sha256_file(target)


class RecentArchiveRuntimeEvaluator:
    def __init__(self, root: str | Path, snapshot: Mapping[str, Any], *, source_sha: str, now_ms: int) -> None:
        self.root = Path(root).resolve()
        self.snapshot = dict(snapshot)
        self.source_sha = str(source_sha).strip().lower()
        self.now_ms = int(now_ms)
        verification = verify_recent_archive_runtime_snapshot(
            self.root, self.snapshot, source_sha=self.source_sha, now_ms=self.now_ms
        )
        if verification["decision"] != "pass":
            raise MultiPairRecentArchiveRuntimeError("transported recent archive snapshot is not verified")

    def __call__(
        self,
        proposal: Mapping[str, Any],
        symbol: str,
        source_sha: str,
        now_ms: int,
        state_root: Path,
    ) -> dict[str, Any]:
        del state_root
        if str(source_sha).strip().lower() != self.source_sha or int(now_ms) != self.now_ms:
            raise MultiPairRecentArchiveRuntimeError("recent archive evaluator identity mismatch")
        timeframe = str(proposal.get("timeframe", ""))
        dataset = rest_runtime.bind_transported_runtime_dataset(
            self.root, self.snapshot, symbol=symbol, timeframe=timeframe
        )
        family = str(proposal["family"])
        variant_id = str(proposal["variant_id"])
        job_kwargs = {
            "hypothesis": (
                "Independent requalification from a recent bounded-lag official Bybit Spot archive "
                f"snapshot for proposal {proposal['proposal_digest']}; no profitability or promotion claim."
            ),
            "family": family,
            "strategy_version": f"{family}-recent-archive-requalification-{variant_id}",
            "strategy_config": dict(proposal["strategy_config"]),
            "code_sha": self.source_sha,
            "cost_model": COST_MODEL,
            "kill_criteria": KILL_CRITERIA,
        }
        job = run_research_job(dataset, **job_kwargs)
        replay = run_research_job(dataset, **job_kwargs)
        binding = str(dataset.get("binding_sha256", ""))
        legacy_requal._validate_runtime_job(job, dataset_sha=binding, source_sha=self.source_sha, proposal=proposal)
        legacy_requal._validate_runtime_job(replay, dataset_sha=binding, source_sha=self.source_sha, proposal=proposal)
        if legacy_requal._canonical(job) != legacy_requal._canonical(replay):
            raise MultiPairRecentArchiveRuntimeError("recent archive qualification replay is not deterministic")
        qualification = job.get("qualification")
        if not isinstance(qualification, Mapping) or qualification.get("status") not in {"paper_candidate", "killed"}:
            raise MultiPairRecentArchiveRuntimeError("recent archive qualification status is invalid")
        return {
            "symbol": symbol,
            "family": family,
            "timeframe": timeframe,
            "variant_id": variant_id,
            "runtime_dataset_binding_sha256": binding,
            "runtime_last_open_time_ms": dataset["rows"][-1]["open_time_ms"],
            "qualification_status": qualification["status"],
            "pipeline_digest": job.get("pipeline_digest"),
            "qualification_digest": qualification.get("qualification_digest"),
            "kill_reasons": list(qualification.get("kill_reasons", [])),
            "deterministic_replay_verified": True,
            "data_origin": "canonical_public_bybit_runtime",
            "runtime_data_transport": TRANSPORT_ORIGIN,
            "runtime_snapshot_digest": self.snapshot["snapshot_digest"],
            "runtime_snapshot_as_of_ms": self.snapshot["as_of_ms"],
            "runtime_data_as_of_ms": self.snapshot["data_as_of_ms"],
            "runtime_source_lag_ms": self.now_ms - self.snapshot["data_as_of_ms"],
            "runtime_live_freshness_claimed": False,
            "runtime_requalification_recency_verified": True,
            "closed_candle_finality_verified": True,
            "paper_only": True,
            "live_trading_authority": False,
            "paper_execution_started": False,
            "automatic_strategy_promotion": False,
            "deterministic_risk_final_authority": True,
        }


def run_requalification_from_snapshot(
    discovery_path: str | Path,
    queue_path: str | Path,
    *,
    snapshot_root: str | Path,
    source_sha: str,
    state_root: str | Path,
    output: str | Path,
    now_ms: int,
) -> dict[str, Any]:
    discovery = rest_runtime._load_json(discovery_path)
    queue = rest_runtime._load_json(queue_path)
    snapshot = rest_runtime._load_json(Path(snapshot_root) / "snapshot-manifest.json")
    evaluator = RecentArchiveRuntimeEvaluator(
        snapshot_root, snapshot, source_sha=source_sha, now_ms=now_ms
    )
    result = multipair_requal.build_requalification(
        discovery,
        queue,
        source_sha=source_sha,
        discovery_source_sha=source_sha,
        state_root=state_root,
        now_ms=now_ms,
        evaluator=evaluator,
    )
    core = dict(result)
    core.pop("requalification_digest", None)
    historical_digest = str(discovery.get("dataset_snapshot_sha256", ""))
    runtime_digest = str(snapshot.get("snapshot_digest", ""))
    core.update(
        {
            "runtime_data_transport": TRANSPORT_ORIGIN,
            "runtime_snapshot_digest": runtime_digest,
            "runtime_snapshot_as_of_ms": snapshot["as_of_ms"],
            "runtime_data_as_of_ms": snapshot["data_as_of_ms"],
            "runtime_snapshot_history_limit": snapshot["history_limit"],
            "runtime_source_lag_ms": now_ms - snapshot["data_as_of_ms"],
            "runtime_live_freshness_claimed": False,
            "runtime_requalification_recency_verified": True,
            "legacy_runtime_freshness_field_semantics": "independent_recent_requalification_dataset_not_historical_discovery_reuse",
            "runtime_snapshot_distinct_from_discovery": bool(
                _HEX64.fullmatch(runtime_digest)
                and _HEX64.fullmatch(historical_digest)
                and runtime_digest != historical_digest
            ),
            "historical_discovery_snapshot_reused": False,
        }
    )
    result = {**core, "requalification_digest": multipair_requal._digest(core)}
    verification = multipair_requal.verify_requalification(result)
    if verification["decision"] != "pass":
        raise MultiPairRecentArchiveRuntimeError("recent archive requalification verifier rejected evidence")
    if core["runtime_snapshot_distinct_from_discovery"] is not True:
        raise MultiPairRecentArchiveRuntimeError("recent archive snapshot must differ from historical Discovery")
    for row in result.get("proposal_results", []):
        for evaluation in row.get("runtime_evaluations", []):
            if (
                evaluation.get("runtime_data_transport") != TRANSPORT_ORIGIN
                or evaluation.get("runtime_snapshot_digest") != runtime_digest
                or evaluation.get("runtime_data_as_of_ms") != snapshot["data_as_of_ms"]
                or evaluation.get("runtime_live_freshness_claimed") is not False
                or evaluation.get("runtime_requalification_recency_verified") is not True
            ):
                raise MultiPairRecentArchiveRuntimeError("evaluation is not bound to recent archive evidence")
    target = Path(output).resolve()
    _atomic_json(target, result)
    _atomic_json(target.with_name("verification.json"), verification)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    acquire = subparsers.add_parser("acquire")
    acquire.add_argument("--state-root", type=Path, required=True)
    acquire.add_argument("--cache-root", type=Path, required=True)
    acquire.add_argument("--output-root", type=Path, required=True)
    acquire.add_argument("--archive-output", type=Path, required=True)
    acquire.add_argument("--digest-output", type=Path, required=True)
    acquire.add_argument("--source-sha", required=True)
    acquire.add_argument("--now-ms", type=int, required=True)

    requalify = subparsers.add_parser("requalify")
    requalify.add_argument("--snapshot-root", type=Path, required=True)
    requalify.add_argument("--discovery", type=Path, required=True)
    requalify.add_argument("--queue", type=Path, required=True)
    requalify.add_argument("--source-sha", required=True)
    requalify.add_argument("--state-root", type=Path, required=True)
    requalify.add_argument("--output", type=Path, required=True)
    requalify.add_argument("--now-ms", type=int, required=True)

    args = parser.parse_args()
    if args.command == "acquire":
        snapshot = collect_recent_archive_runtime_snapshot(
            state_root=args.state_root,
            cache_root=args.cache_root,
            output_root=args.output_root,
            source_sha=args.source_sha,
            now_ms=args.now_ms,
        )
        archive_sha = deterministic_pack(args.output_root, args.archive_output)
        args.digest_output.parent.mkdir(parents=True, exist_ok=True)
        args.digest_output.write_text(archive_sha + "\n", encoding="ascii")
        print(
            json.dumps(
                {
                    "decision": "pass",
                    "snapshot_digest": snapshot["snapshot_digest"],
                    "snapshot_as_of_ms": snapshot["as_of_ms"],
                    "data_as_of_ms": snapshot["data_as_of_ms"],
                    "source_lag_ms": snapshot["source_lag_ms_at_acquisition"],
                    "latest_common_complete_date": snapshot["latest_common_complete_date"],
                    "archive_sha256": archive_sha,
                    "cells": snapshot["cell_count"],
                    "history_limit": snapshot["history_limit"],
                    "live_freshness_claimed": False,
                },
                sort_keys=True,
            )
        )
        return 0

    result = run_requalification_from_snapshot(
        args.discovery,
        args.queue,
        snapshot_root=args.snapshot_root,
        source_sha=args.source_sha,
        state_root=args.state_root,
        output=args.output,
        now_ms=args.now_ms,
    )
    print(
        json.dumps(
            {
                "decision": "pass",
                "status": result["status"],
                "proposal_count": result["proposal_count"],
                "qualified": result["qualified_for_review_count"],
                "rejected": result["rejected_count"],
                "runtime_snapshot_digest": result["runtime_snapshot_digest"],
                "runtime_data_as_of_ms": result["runtime_data_as_of_ms"],
                "runtime_live_freshness_claimed": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
