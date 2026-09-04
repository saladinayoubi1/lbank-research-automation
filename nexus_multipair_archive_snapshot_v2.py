"""Discovery archive snapshot v2 on a fixed April-June 2026 Bybit Spot window.

V2 leaves the original v1 evidence contract immutable. The source window is chosen
only from months where all four trusted symbols have official monthly Spot archives,
while still providing at least 500 closed 4h candles. This remains historical
Research evidence and makes no runtime-freshness claim.
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
from nexus_multipair_trusted_surface import SYMBOLS, TIMEFRAMES

SCHEMA = "nexus.multipair-discovery-archive-snapshot.v2"
SOURCE_START_DATE = "2026-04-01"
SOURCE_END_DATE = "2026-06-30"
SOURCE_MONTHS = ("2026-04", "2026-05", "2026-06")
HISTORY_LIMIT = 500
EXPECTED_SOURCE_ARCHIVES = 12
EXPECTED_CELLS = 12
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
MAX_FRAME_BYTES = 20 * 1024 * 1024
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
COLUMNS = ["timestamp", "open", "high", "low", "close", "volume", "symbol", "timeframe"]
QUALITY_ZERO_FIELDS = (
    "invalid_numeric_rows", "invalid_symbol_rows", "invalid_side_rows",
    "non_positive_price_rows", "negative_size_rows", "outside_range_rows",
    "duplicate_trade_id_count", "source_rows_skipped", "malformed_csv_rows",
)


class MultiPairArchiveSnapshotV2Error(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MultiPairArchiveSnapshotV2Error("snapshot evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stored_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [{
        "timestamp": pd.Timestamp(row.timestamp).isoformat(),
        "open": str(row.open), "high": str(row.high), "low": str(row.low),
        "close": str(row.close), "volume": str(row.volume),
        "symbol": str(row.symbol), "timeframe": str(row.timeframe),
    } for row in frame.itertuples(index=False)]


def _month_bounds(month: str) -> tuple[str, str]:
    period = pd.Period(month, freq="M")
    return period.start_time.strftime("%Y-%m-%d"), period.end_time.strftime("%Y-%m-%d")


def _window_supports_history_limit() -> bool:
    start = pd.Timestamp(SOURCE_START_DATE, tz="UTC")
    end = pd.Timestamp(SOURCE_END_DATE, tz="UTC") + pd.Timedelta(days=1)
    four_hour_rows = len(pd.date_range(start, end, freq="4h", inclusive="left"))
    return four_hour_rows >= HISTORY_LIMIT


def _validate_backfill_report(report: Mapping[str, Any]) -> None:
    configuration = report.get("configuration")
    summary = report.get("summary")
    if not isinstance(configuration, Mapping) or not isinstance(summary, Mapping):
        raise MultiPairArchiveSnapshotV2Error("backfill report structure is invalid")
    if (
        configuration.get("start_date") != SOURCE_START_DATE
        or configuration.get("end_date") != SOURCE_END_DATE
        or configuration.get("symbols") != list(SYMBOLS)
        or summary.get("plan_units") != 3
        or summary.get("plan_archives") != EXPECTED_SOURCE_ARCHIVES
        or summary.get("completed_units") != 3
        or summary.get("remaining_units") != 0
        or summary.get("run_failures") != 0
        or summary.get("backfill_complete") is not True
        or summary.get("current_dataset_integrity_ok") is not True
        or report.get("run_failures") != []
    ):
        raise MultiPairArchiveSnapshotV2Error("official Spot backfill did not complete the v2 source window")


def _source_evidence(state_root: Path) -> tuple[list[dict[str, Any]], str]:
    path = state_root / backfill.SOURCE_MANIFEST_NAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MultiPairArchiveSnapshotV2Error("source manifest is unavailable") from exc
    if not isinstance(raw, list) or len(raw) != EXPECTED_SOURCE_ARCHIVES:
        raise MultiPairArchiveSnapshotV2Error("v2 requires exactly 12 official monthly archives")
    expected = {(symbol, month) for symbol in SYMBOLS for month in SOURCE_MONTHS}
    seen: set[tuple[str, str]] = set()
    evidence: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, Mapping):
            raise MultiPairArchiveSnapshotV2Error("source record is invalid")
        symbol = str(row.get("symbol", "")).upper()
        unit_id = str(row.get("unit_id", ""))
        if not unit_id.startswith("monthly:"):
            raise MultiPairArchiveSnapshotV2Error("v2 accepts monthly Spot archives only")
        month = unit_id.split(":", 1)[1]
        key = (symbol, month)
        filename = f"{symbol}-{month}.csv.gz"
        start_date, end_date = _month_bounds(month)
        expected_url = backfill.archive_url(symbol, filename)
        size = row.get("size_bytes")
        sha = str(row.get("sha256", "")).lower()
        if (
            key not in expected or key in seen
            or row.get("unit_kind") != "monthly"
            or row.get("filename") != filename
            or row.get("url") != expected_url
            or not expected_url.startswith(archive_audit.ARCHIVE_BASE_URL + "/")
            or row.get("start_date") != start_date or row.get("end_date") != end_date
            or row.get("http_status") != 200
            or isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_ARCHIVE_BYTES
            or not _HEX64_RE.fullmatch(sha)
            or int(row.get("source_rows", 0)) <= 0 or int(row.get("valid_trade_rows", 0)) <= 0
            or any(int(row.get(field, 0)) != 0 for field in QUALITY_ZERO_FIELDS)
        ):
            raise MultiPairArchiveSnapshotV2Error(f"official Spot provenance failed closed: {symbol}/{month}")
        seen.add(key)
        evidence.append({
            "symbol": symbol, "month": month, "filename": filename, "url": expected_url,
            "sha256": sha, "size_bytes": size, "http_status": 200,
            "source_rows": int(row["source_rows"]), "valid_trade_rows": int(row["valid_trade_rows"]),
            "parser_engine": str(row.get("parser_engine", "")),
            "timestamp_unit": str(row.get("timestamp_unit", "")),
        })
    if seen != expected:
        raise MultiPairArchiveSnapshotV2Error("official Spot source surface is incomplete")
    evidence.sort(key=lambda row: (row["symbol"], row["month"]))
    return evidence, _digest(evidence)


def _load_tail(state_root: Path, symbol: str, timeframe: str) -> pd.DataFrame:
    source = state_root / "bybit_market" / collector.canonical_symbol(symbol) / f"{timeframe}.parquet"
    if source.is_symlink() or not source.is_file() or source.stat().st_size > MAX_FRAME_BYTES:
        raise MultiPairArchiveSnapshotV2Error(f"backfill frame missing or unsafe: {symbol}/{timeframe}")
    frame = pd.read_parquet(source)
    if frame.columns.tolist() != collector.CANONICAL_COLUMNS or len(frame) < HISTORY_LIMIT:
        raise MultiPairArchiveSnapshotV2Error(f"backfill cannot supply 500 rows: {symbol}/{timeframe}")
    frame = frame.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    frame = frame.sort_values("timestamp").tail(HISTORY_LIMIT).reset_index(drop=True)
    for field in ("open", "high", "low", "close", "volume"):
        frame[field] = pd.to_numeric(frame[field], errors="raise")
    frame["symbol"] = symbol
    frame["timeframe"] = timeframe
    frame = frame.loc[:, COLUMNS]
    timestamps = pd.DatetimeIndex(frame["timestamp"])
    step = archive_audit.TIMEFRAME_DELTAS[timeframe]
    if (
        timestamps.duplicated().any() or not timestamps.is_monotonic_increasing
        or not bool((timestamps[1:] - timestamps[:-1] == step).all())
        or set(frame["symbol"].astype(str)) != {symbol}
        or set(frame["timeframe"].astype(str)) != {timeframe}
        or bool((frame["volume"] < 0).any())
        or bool((frame[["open", "high", "low", "close"]] <= 0).any().any())
        or bool((frame["high"] < frame[["open", "close", "low"]].max(axis=1)).any())
        or bool((frame["low"] > frame[["open", "close", "high"]].min(axis=1)).any())
    ):
        raise MultiPairArchiveSnapshotV2Error(f"backfill tail integrity failed: {symbol}/{timeframe}")
    return frame


def build_snapshot_from_backfill(*, state_root: str | Path, output_root: str | Path, report: Mapping[str, Any], source_sha: str) -> dict[str, Any]:
    if not _SHA40_RE.fullmatch(str(source_sha)):
        raise MultiPairArchiveSnapshotV2Error("source_sha must be an exact Git SHA")
    if len(SYMBOLS) != 4 or len(TIMEFRAMES) != 3 or not _window_supports_history_limit():
        raise MultiPairArchiveSnapshotV2Error("trusted surface or v2 source-window capacity is invalid")
    _validate_backfill_report(report)
    state = Path(state_root).resolve()
    output = Path(output_root).resolve()
    if output.exists(): shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    sources, source_manifest_digest = _source_evidence(state)
    cells: list[dict[str, Any]] = []
    refs: dict[str, pd.Series] = {}
    for timeframe in TIMEFRAMES:
        for symbol in SYMBOLS:
            frame = _load_tail(state, symbol, timeframe)
            timestamps = frame["timestamp"].reset_index(drop=True)
            reference = refs.setdefault(timeframe, timestamps)
            if not reference.equals(timestamps):
                raise MultiPairArchiveSnapshotV2Error(f"four-symbol snapshot is not aligned: {timeframe}")
            target = output / "bybit_market" / symbol / f"{timeframe}.parquet"
            target.parent.mkdir(parents=True, exist_ok=True)
            frame.to_parquet(target, index=False)
            cells.append({
                "symbol": symbol, "timeframe": timeframe, "row_count": HISTORY_LIMIT,
                "first_open_time_ms": int(frame["timestamp"].iloc[0].value // 1_000_000),
                "last_open_time_ms": int(frame["timestamp"].iloc[-1].value // 1_000_000),
                "frame_digest": _digest(_stored_rows(frame)),
            })
    cells.sort(key=lambda row: (row["symbol"], row["timeframe"]))
    core = {
        "schema_version": SCHEMA, "source_sha": source_sha,
        "source_window_start": SOURCE_START_DATE, "source_window_end": SOURCE_END_DATE,
        "source_months": list(SOURCE_MONTHS), "archive_base_url": archive_audit.ARCHIVE_BASE_URL,
        "archive_sources": sources, "archive_source_count": len(sources),
        "archive_source_manifest_digest": source_manifest_digest,
        "symbols": list(SYMBOLS), "timeframes": list(TIMEFRAMES),
        "cell_count": EXPECTED_CELLS, "history_limit": HISTORY_LIMIT, "cells": cells,
        "data_origin": "official_public_bybit_spot_trade_archive_aggregated",
        "runtime_freshness_claimed": False, "research_only": True,
        "paper_execution_started": False, "live_trading_authority": False,
        "private_credentials_used": False, "real_exchange_orders": False,
        "automatic_strategy_promotion": False, "silent_exchange_substitution": False,
        "third_party_proxy_used": False, "issue_984_state_touched": False,
        "persistent_runtime_database_on_github": False,
    }
    result = {**core, "snapshot_digest": _digest(core)}
    (output / "snapshot-manifest.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def verify_snapshot(root: str | Path, value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {"schema": False, "digest": False, "source": False, "shape": False, "frames": False, "authority": False}
    try:
        core = dict(value); claimed = core.pop("snapshot_digest", None)
        checks["schema"] = bool(core.get("schema_version") == SCHEMA and _HEX64_RE.fullmatch(str(claimed or "")))
        checks["digest"] = claimed == _digest(core)
        sources = core.get("archive_sources")
        expected_sources = {(symbol, month) for symbol in SYMBOLS for month in SOURCE_MONTHS}
        checks["source"] = bool(
            core.get("source_window_start") == SOURCE_START_DATE and core.get("source_window_end") == SOURCE_END_DATE
            and core.get("source_months") == list(SOURCE_MONTHS) and core.get("archive_base_url") == archive_audit.ARCHIVE_BASE_URL
            and isinstance(sources, list) and len(sources) == EXPECTED_SOURCE_ARCHIVES
            and core.get("archive_source_count") == EXPECTED_SOURCE_ARCHIVES
            and {(row.get("symbol"), row.get("month")) for row in sources if isinstance(row, Mapping)} == expected_sources
            and core.get("archive_source_manifest_digest") == _digest(sources)
            and all(isinstance(row, Mapping) and row.get("url") == backfill.archive_url(str(row.get("symbol")), str(row.get("filename")))
                    and row.get("http_status") == 200 and _HEX64_RE.fullmatch(str(row.get("sha256", ""))) for row in sources)
        )
        cells = core.get("cells")
        expected_cells = {(symbol, timeframe) for symbol in SYMBOLS for timeframe in TIMEFRAMES}
        checks["shape"] = bool(core.get("symbols") == list(SYMBOLS) and core.get("timeframes") == list(TIMEFRAMES)
            and core.get("cell_count") == EXPECTED_CELLS and core.get("history_limit") == HISTORY_LIMIT
            and isinstance(cells, list) and len(cells) == EXPECTED_CELLS
            and {(row.get("symbol"), row.get("timeframe")) for row in cells if isinstance(row, Mapping)} == expected_cells)
        base = Path(root).resolve(); refs: dict[str, pd.Series] = {}; frames_ok = True
        for cell in cells if isinstance(cells, list) else []:
            symbol, timeframe = str(cell.get("symbol")), str(cell.get("timeframe"))
            path = base / "bybit_market" / symbol / f"{timeframe}.parquet"
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FRAME_BYTES:
                frames_ok = False; break
            frame = pd.read_parquet(path)
            if frame.columns.tolist() != COLUMNS or len(frame) != HISTORY_LIMIT:
                frames_ok = False; break
            frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
            ts = frame["timestamp"].reset_index(drop=True); ref = refs.setdefault(timeframe, ts)
            if (not ref.equals(ts) or set(frame["symbol"].astype(str)) != {symbol} or set(frame["timeframe"].astype(str)) != {timeframe}
                or int(ts.iloc[0].value // 1_000_000) != cell.get("first_open_time_ms")
                or int(ts.iloc[-1].value // 1_000_000) != cell.get("last_open_time_ms")
                or _digest(_stored_rows(frame)) != cell.get("frame_digest")):
                frames_ok = False; break
        checks["frames"] = frames_ok
        checks["authority"] = bool(core.get("data_origin") == "official_public_bybit_spot_trade_archive_aggregated"
            and core.get("runtime_freshness_claimed") is False and core.get("research_only") is True
            and core.get("paper_execution_started") is False and core.get("live_trading_authority") is False
            and core.get("private_credentials_used") is False and core.get("real_exchange_orders") is False
            and core.get("automatic_strategy_promotion") is False and core.get("silent_exchange_substitution") is False
            and core.get("third_party_proxy_used") is False and core.get("issue_984_state_touched") is False
            and core.get("persistent_runtime_database_on_github") is False)
    except Exception:
        pass
    return {"decision": "pass" if all(checks.values()) else "reject", "checks": checks, "snapshot_digest": value.get("snapshot_digest")}


def deterministic_pack(root: str | Path, output: str | Path) -> str:
    source = Path(root).resolve(); target = Path(output).resolve()
    manifest = source / "snapshot-manifest.json"
    value = json.loads(manifest.read_text(encoding="utf-8"))
    if verify_snapshot(source, value)["decision"] != "pass":
        raise MultiPairArchiveSnapshotV2Error("snapshot verifier rejected before pack")
    files = [manifest] + [source / "bybit_market" / symbol / f"{timeframe}.parquet" for symbol in SYMBOLS for timeframe in TIMEFRAMES]
    if any(path.is_symlink() or not path.is_file() for path in files):
        raise MultiPairArchiveSnapshotV2Error("snapshot pack surface is incomplete")
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED) as archive:
        for path in sorted(files, key=lambda item: item.relative_to(source).as_posix()):
            name = path.relative_to(source).as_posix(); info = zipfile.ZipInfo(name, date_time=(1980,1,1,0,0,0))
            info.compress_type = zipfile.ZIP_STORED; info.create_system = 3; info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    return _sha256_file(target)


def acquire_snapshot(*, state_root: Path, cache_root: Path, output_root: Path, source_sha: str) -> dict[str, Any]:
    report = backfill.run_backfill(start_date=SOURCE_START_DATE, end_date=SOURCE_END_DATE,
        state_root=state_root, cache_root=cache_root, max_archives_per_run=EXPECTED_SOURCE_ARCHIVES,
        symbols=tuple(SYMBOLS), clean=True)
    return build_snapshot_from_backfill(state_root=state_root, output_root=output_root, report=report, source_sha=source_sha)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", type=Path, required=True); parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True); parser.add_argument("--archive-output", type=Path, required=True)
    parser.add_argument("--digest-output", type=Path, required=True); parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    result = acquire_snapshot(state_root=args.state_root, cache_root=args.cache_root, output_root=args.output_root, source_sha=args.source_sha)
    if verify_snapshot(args.output_root, result)["decision"] != "pass":
        raise MultiPairArchiveSnapshotV2Error("archive snapshot v2 verification failed")
    archive_sha = deterministic_pack(args.output_root, args.archive_output)
    args.digest_output.parent.mkdir(parents=True, exist_ok=True); args.digest_output.write_text(archive_sha + "\n", encoding="ascii")
    print(json.dumps({"decision":"pass","schema":SCHEMA,"snapshot_digest":result["snapshot_digest"],"archive_sha256":archive_sha,"source_archives":12,"cells":12}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
