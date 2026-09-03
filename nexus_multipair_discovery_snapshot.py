"""Build and verify a bounded four-symbol Bybit discovery snapshot.

The snapshot is Research-only evidence. It uses the canonical registry and public
closed-candle Bybit boundary already used by Phase 5/6. No private credentials,
Paper execution, Live authority, or exchange substitution are available here.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd

from market_data_source_validator import load_and_validate
from phase5_data_binding import validate_canonical_dataset
from phase6_research_pipeline import fetch_bind_bybit_dataset
from product_research_runtime import TIMEFRAMES, _public_mapping, _registry_path


SCHEMA = "nexus.multipair-discovery-snapshot.v1"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
TIMEFRAME_NAMES = ("minute15", "hour1", "hour4")
DEFAULT_LIMIT = 500
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


class MultiPairDiscoverySnapshotError(RuntimeError):
    pass


Fetcher = Callable[..., Mapping[str, Any]]


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MultiPairDiscoverySnapshotError("snapshot evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    target = path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(value), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


def _frame_rows(dataset: Mapping[str, Any], symbol: str, timeframe: str) -> list[dict[str, Any]]:
    rows = dataset.get("rows")
    if not isinstance(rows, list) or not rows:
        raise MultiPairDiscoverySnapshotError("canonical snapshot dataset has no rows")
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise MultiPairDiscoverySnapshotError("canonical snapshot row is invalid")
        normalized.append({
            "timestamp": pd.Timestamp(int(row["open_time_ms"]), unit="ms", tz="UTC").isoformat(),
            "open": str(row["open"]),
            "high": str(row["high"]),
            "low": str(row["low"]),
            "close": str(row["close"]),
            "volume": str(row["volume"]),
            "symbol": symbol,
            "timeframe": timeframe,
        })
    return normalized


def _stored_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [{
        "timestamp": pd.Timestamp(item.timestamp).isoformat(),
        "open": str(item.open),
        "high": str(item.high),
        "low": str(item.low),
        "close": str(item.close),
        "volume": str(item.volume),
        "symbol": str(item.symbol),
        "timeframe": str(item.timeframe),
    } for item in frame.itertuples(index=False)]


def _write_frame(path: Path, rows: list[dict[str, Any]]) -> str:
    frame = pd.DataFrame(rows)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    for field in ("open", "high", "low", "close", "volume"):
        frame[field] = pd.to_numeric(frame[field], errors="raise")
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return _digest(_stored_rows(frame))


def collect_snapshot(
    *,
    output_root: str | Path,
    source_sha: str,
    now_ms: int,
    limit: int = DEFAULT_LIMIT,
    fetcher: Fetcher = fetch_bind_bybit_dataset,
) -> dict[str, Any]:
    source_sha = str(source_sha).strip().lower()
    if not _SHA_RE.fullmatch(source_sha):
        raise MultiPairDiscoverySnapshotError("source_sha must be an exact Git SHA")
    if isinstance(now_ms, bool) or not isinstance(now_ms, int) or now_ms <= 0:
        raise MultiPairDiscoverySnapshotError("now_ms must be a positive integer")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 160 <= limit <= 500:
        raise MultiPairDiscoverySnapshotError("snapshot limit must be between 160 and 500")

    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    registry = load_and_validate(_registry_path())
    cells: list[dict[str, Any]] = []

    for symbol in SYMBOLS:
        for timeframe in TIMEFRAME_NAMES:
            mapping, source = _public_mapping(registry, symbol, timeframe)
            spec = TIMEFRAMES[timeframe]
            step_ms = int(spec["step_ms"])
            end_ms = ((now_ms - step_ms) // step_ms) * step_ms
            start_ms = end_ms - (limit - 1) * step_ms
            if start_ms < 0:
                raise MultiPairDiscoverySnapshotError("snapshot window is invalid")
            try:
                dataset = fetcher(
                    canonical_symbol=mapping["canonical_symbol"],
                    source_symbol=source["symbol"],
                    interval=spec["interval"],
                    now_ms=now_ms,
                    start_time_ms=start_ms,
                    end_time_ms=end_ms,
                    limit=limit,
                    timeout_seconds=20.0,
                )
                artifact = validate_canonical_dataset(dataset, registry_path=_registry_path())
            except Exception as exc:
                raise MultiPairDiscoverySnapshotError(
                    f"canonical public snapshot failed closed: {symbol}/{timeframe}: {exc}"
                ) from exc
            if artifact.get("row_count") != limit:
                raise MultiPairDiscoverySnapshotError("snapshot row count mismatch")
            rows = _frame_rows(artifact, symbol, timeframe)
            path = root / "bybit_market" / symbol / f"{timeframe}.parquet"
            frame_digest = _write_frame(path, rows)
            cells.append({
                "symbol": symbol,
                "timeframe": timeframe,
                "canonical_symbol": mapping["canonical_symbol"],
                "source_exchange": "Bybit",
                "source_symbol": source["symbol"],
                "mapping_id": mapping["mapping_id"],
                "row_count": limit,
                "first_open_time_ms": int(artifact["rows"][0]["open_time_ms"]),
                "last_open_time_ms": int(artifact["rows"][-1]["open_time_ms"]),
                "dataset_binding_sha256": artifact["binding_sha256"],
                "provenance_manifest_sha256": artifact["manifest_sha256"],
                "frame_digest": frame_digest,
            })

    core = {
        "schema_version": SCHEMA,
        "source_sha": source_sha,
        "as_of_ms": now_ms,
        "registry_version": registry.get("registry_version"),
        "symbols": list(SYMBOLS),
        "timeframes": list(TIMEFRAME_NAMES),
        "cell_count": 12,
        "history_limit": limit,
        "cells": sorted(cells, key=lambda row: (row["symbol"], row["timeframe"])),
        "data_origin": "canonical_public_bybit_closed_candles",
        "research_only": True,
        "paper_execution_started": False,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "silent_exchange_substitution": False,
    }
    result = {**core, "snapshot_digest": _digest(core)}
    _atomic_json(root / "snapshot-manifest.json", result)
    return result


def verify_snapshot(root: str | Path, value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {
        "schema": False,
        "digest": False,
        "shape": False,
        "authority": False,
        "frames": False,
    }
    try:
        core = dict(value)
        claimed = core.pop("snapshot_digest", None)
        checks["schema"] = bool(
            core.get("schema_version") == SCHEMA
            and _SHA_RE.fullmatch(str(core.get("source_sha", "")))
            and _HEX64_RE.fullmatch(str(claimed or ""))
        )
        checks["digest"] = claimed == _digest(core)
        cells = core.get("cells")
        expected = {(symbol, timeframe) for symbol in SYMBOLS for timeframe in TIMEFRAME_NAMES}
        checks["shape"] = bool(
            core.get("symbols") == list(SYMBOLS)
            and core.get("timeframes") == list(TIMEFRAME_NAMES)
            and core.get("cell_count") == 12
            and isinstance(cells, list)
            and len(cells) == 12
            and {(row.get("symbol"), row.get("timeframe")) for row in cells if isinstance(row, Mapping)} == expected
        )
        checks["authority"] = bool(
            core.get("research_only") is True
            and core.get("paper_execution_started") is False
            and core.get("live_trading_authority") is False
            and core.get("private_credentials_used") is False
            and core.get("automatic_strategy_promotion") is False
            and core.get("silent_exchange_substitution") is False
            and core.get("data_origin") == "canonical_public_bybit_closed_candles"
        )
        root_path = Path(root).resolve()
        frames_ok = True
        for row in cells if isinstance(cells, list) else []:
            if not isinstance(row, Mapping):
                frames_ok = False
                break
            symbol, timeframe = str(row.get("symbol")), str(row.get("timeframe"))
            path = root_path / "bybit_market" / symbol / f"{timeframe}.parquet"
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 20_000_000:
                frames_ok = False
                break
            frame = pd.read_parquet(path)
            required = ["timestamp", "open", "high", "low", "close", "volume", "symbol", "timeframe"]
            if frame.columns.tolist() != required or len(frame) != row.get("row_count"):
                frames_ok = False
                break
            if _digest(_stored_rows(frame)) != row.get("frame_digest"):
                frames_ok = False
                break
            timestamps = pd.to_datetime(frame["timestamp"], utc=True)
            step = int(TIMEFRAMES[timeframe]["step_ms"])
            open_ms = timestamps.map(lambda value: value.value // 1_000_000).astype("int64")
            if (
                set(frame["symbol"].astype(str)) != {symbol}
                or set(frame["timeframe"].astype(str)) != {timeframe}
                or open_ms.duplicated().any()
                or not open_ms.is_monotonic_increasing
                or not (open_ms.diff().dropna() == step).all()
            ):
                frames_ok = False
                break
        checks["frames"] = frames_ok
    except Exception:
        pass
    return {"decision": "pass" if all(checks.values()) else "reject", "checks": checks}
