"""Read-only, explicitly pinned historical-month evidence for the owner Research UI.

This is not the live Research producer, independent prospective proof or an
integration_report_provenance envelope. It never writes files or authorizes
Paper/Demo admission, and it deliberately reports archival provenance.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import stat
from datetime import date, timedelta
from pathlib import Path
from typing import Any

CONTRACT = "nexus.historical-monthly-research.v1"
SOURCE_CONTRACT = "nexus.bybit-calendar-month-pre-demo-research.v1"
PAIRS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
FRAMES = {"15m": (900_000, 96), "1h": (3_600_000, 24), "4h": (14_400_000, 6)}
FAMILIES = ("momentum", "trend_breakout", "mean_reversion")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SHA1 = re.compile(r"^[0-9a-f]{40}$")
MAX_JSON = 8_000_000
MAX_ROWS = 36


class HistoricalArchiveUnavailable(ValueError):
    """The historical report is missing, changed or not explicitly trusted."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for k, v in pairs:
        if k in result:
            raise HistoricalArchiveUnavailable("duplicate archive JSON key")
        result[k] = v
    return result


def _read(path: Path, maximum: int) -> bytes:
    """Bound regular files; never follow symlinks or silently accept replacements."""
    try:
        before = path.lstat()
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or not 1 <= before.st_size <= maximum):
            raise HistoricalArchiveUnavailable("unsafe historical archive entry")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(path, flags), "rb") as handle:
            raw = handle.read(maximum + 1)
            after = os.fstat(handle.fileno())
        if (len(raw) != before.st_size or len(raw) > maximum
                or (before.st_dev, before.st_ino, before.st_size)
                != (after.st_dev, after.st_ino, after.st_size)):
            raise HistoricalArchiveUnavailable("historical archive file changed")
        return raw
    except (FileNotFoundError, PermissionError, OSError) as exc:
        raise HistoricalArchiveUnavailable("historical archive file unavailable") from exc


def _json(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys,
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              HistoricalArchiveUnavailable("non-finite archive number")))
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise HistoricalArchiveUnavailable("historical archive JSON invalid") from exc


def _month_bounds(start: Any, end: Any) -> tuple[int, int, int]:
    try:
        a, b = date.fromisoformat(start), date.fromisoformat(end)
        if a.day != 1 or b != (date(a.year + 1, 1, 1) if a.month == 12
                               else date(a.year, a.month + 1, 1)):
            raise ValueError("not one calendar month")
        if b > date.today().replace(day=1):
            raise ValueError("future or incomplete month")
        epoch = date(1970, 1, 1)
        return (a - epoch).days * 86_400_000, (b - epoch).days * 86_400_000, (b - a).days
    except (TypeError, ValueError) as exc:
        raise HistoricalArchiveUnavailable("invalid completed UTC month") from exc


def _finite(value: Any, field: str) -> float:
    try:
        result = float(value)
        if not (-1e9 <= result <= 1e9):
            raise ValueError("outside bound")
        return result
    except (TypeError, ValueError, OverflowError) as exc:
        raise HistoricalArchiveUnavailable("invalid historical metric " + field) from exc


def load_historical_month(
    root: Path | None = None,
    *, expected_report_sha256: str | None = None,
    expected_source_sha: str | None = None,
) -> dict[str, Any]:
    """Fail closed unless the owner deployment pins BOTH archival SHA anchors."""
    configured = root if root is not None else os.environ.get("NEXUS_HISTORICAL_MONTHLY_ARCHIVE_DIR")
    report_pin = expected_report_sha256 or os.environ.get("NEXUS_HISTORICAL_MONTHLY_REPORT_SHA256")
    source_pin = expected_source_sha or os.environ.get("NEXUS_HISTORICAL_MONTHLY_CODE_SHA")
    if (not configured or not isinstance(report_pin, str) or not SHA256.fullmatch(report_pin)
            or not isinstance(source_pin, str) or not SHA1.fullmatch(source_pin)):
        raise HistoricalArchiveUnavailable("historical archive not explicitly source-pinned")
    base = Path(configured)
    if not base.is_absolute() or base.is_symlink() or not base.is_dir():
        raise HistoricalArchiveUnavailable("historical archive directory unavailable")

    summary = _json(_read(base / "summary.json", 262_144))
    if not isinstance(summary, dict) or (
        summary.get("contract_version") != SOURCE_CONTRACT
        or summary.get("decision") != "FULL_MONTH_HISTORICAL_BACKTEST_COMPLETE"
        or summary.get("code_sha") != source_pin
        or summary.get("report_sha256") != report_pin
        or summary.get("bybit_only") is not True
        or summary.get("no_demo_or_live_execution") is not True
        or summary.get("owner_review_required_before_any_new_demo") is not True
        or summary.get("no_profitability_claim") is not True
        or summary.get("exact_canonical_months") != 12
        or summary.get("strategy_cells") != MAX_ROWS
    ):
        raise HistoricalArchiveUnavailable("historical summary contract mismatch")
    a, b, days = _month_bounds(summary.get("start_utc"), summary.get("end_exclusive_utc"))
    raw_csv = _read(base / "review-table.csv", 1_000_000)
    if hashlib.sha256(raw_csv).hexdigest() != report_pin:
        raise HistoricalArchiveUnavailable("pinned historical report digest mismatch")

    acquisition = summary.get("acquisitions")
    if not isinstance(acquisition, list) or len(acquisition) != 12:
        raise HistoricalArchiveUnavailable("historical acquisition grid incomplete")
    bindings: dict[tuple[str, str], str] = {}
    for item in acquisition:
        if not isinstance(item, dict):
            raise HistoricalArchiveUnavailable("malformed dataset acquisition")
        pair, tf = item.get("symbol"), item.get("timeframe")
        key = (pair, tf)
        if pair not in PAIRS or tf not in FRAMES or key in bindings:
            raise HistoricalArchiveUnavailable("duplicate or unsupported dataset")
        if not isinstance(item.get("dataset_sha256"), str) or not SHA256.fullmatch(item["dataset_sha256"]):
            raise HistoricalArchiveUnavailable("unbound historical dataset digest")
        if not isinstance(item.get("binding_sha256"), str) or not SHA256.fullmatch(item["binding_sha256"]):
            raise HistoricalArchiveUnavailable("unbound historical dataset identity")
        grid, bars_per_day = FRAMES[tf]
        count = days * bars_per_day
        if type(item.get("rows")) is not int or item["rows"] != count:
            raise HistoricalArchiveUnavailable("incomplete monthly dataset row count")
        # Only fixed canonical names, never untrusted paths from the summary.
        raw_ds = _read(base / "datasets" / (pair + "-" + tf + ".json"), MAX_JSON)
        if hashlib.sha256(raw_ds).hexdigest() != item["dataset_sha256"]:
            raise HistoricalArchiveUnavailable("historical dataset digest mismatch")
        ds = _json(raw_ds)
        if (not isinstance(ds, dict) or ds.get("source") != "Bybit"
                or ds.get("source_symbol") != pair or ds.get("source_role") != "primary"
                or ds.get("finality") != "closed_only"
                or ds.get("binding_sha256") != item["binding_sha256"]
                or ds.get("row_count") != count or ds.get("timestamp_grid_ms") != grid
                or ds.get("interval") != {"15m": "15", "1h": "60", "4h": "240"}[tf]):
            raise HistoricalArchiveUnavailable("historical dataset source or grid mismatch")
        rows = ds.get("rows")
        if not isinstance(rows, list) or len(rows) != count:
            raise HistoricalArchiveUnavailable("historical dataset missing closed bars")
        # Require every source-labelled closed bar to cover exactly one UTC month
        # on a gap-free, strictly ordered timeframe grid.
        for i, candle in enumerate(rows):
            if (not isinstance(candle, dict) or type(candle.get("open_time_ms")) is not int
                    or candle["open_time_ms"] != a + i * grid):
                raise HistoricalArchiveUnavailable("historical dataset has timestamp gaps")
        if rows[-1]["open_time_ms"] + grid != b:
            raise HistoricalArchiveUnavailable("historical dataset month end missing")
        bindings[key] = item["binding_sha256"]
    if len(bindings) != 12:
        raise HistoricalArchiveUnavailable("historical archive pair/timeframe grid incomplete")
    if len(list((base / "datasets").glob("*.json"))) != 12:
        raise HistoricalArchiveUnavailable("unexpected historical dataset inventory")

    try:
        reader = csv.DictReader(io.StringIO(raw_csv.decode("utf-8"), newline=""))
        names = reader.fieldnames or []
        needed = {"symbol","timeframe","strategy","source_sha",
                  "dataset_binding_sha256","qualification","net_return_pct",
                  "stress_net_return_pct","closed_trades","profit_factor",
                  "max_drawdown_pct","win_rate_pct","kill_reasons"}
        if not needed <= set(names) or len(names) != len(set(names)):
            raise HistoricalArchiveUnavailable("invalid historical CSV schema")
        csv_rows = list(reader)
    except (UnicodeError, csv.Error, ValueError) as exc:
        raise HistoricalArchiveUnavailable("historical review CSV invalid") from exc
    if len(csv_rows) != MAX_ROWS:
        raise HistoricalArchiveUnavailable("historical review grid incomplete")

    raw_journal = _read(base / "cells.jsonl", 1_500_000)
    try:
        journal = [_json(line) for line in raw_journal.splitlines() if line.strip()]
    except (UnicodeError, ValueError) as exc:
        raise HistoricalArchiveUnavailable("historical cell journal invalid") from exc
    if len(journal) != MAX_ROWS:
        raise HistoricalArchiveUnavailable("historical cell journal incomplete")
    seen = set()
    public: list[dict[str, Any]] = []
    for row, item in zip(csv_rows, journal):
        pair, tf, strategy = (row.get("symbol"), row.get("timeframe"), row.get("strategy"))
        key = (pair, tf, strategy)
        if ((pair, tf) not in bindings or strategy not in FAMILIES or key in seen
                or not isinstance(item, dict)):
            raise HistoricalArchiveUnavailable("duplicate or unbound historical cell")
        if row["source_sha"] != source_pin or row["dataset_binding_sha256"] != bindings[(pair, tf)]:
            raise HistoricalArchiveUnavailable("historical cell source mismatch")
        for field in ("symbol", "timeframe", "strategy", "source_sha",
                      "dataset_binding_sha256", "qualification"):
            if row.get(field) != item.get(field):
                raise HistoricalArchiveUnavailable("historical cell journal mismatch")
        if row["qualification"] != "killed" or not row["kill_reasons"]:
            raise HistoricalArchiveUnavailable("unsupported historical admission claim")
        closed_raw = row.get("closed_trades")
        if (not isinstance(closed_raw, str) or not closed_raw.isascii()
                or not closed_raw.isdigit() or len(closed_raw) > 7):
            raise HistoricalArchiveUnavailable("invalid historical closed-trade count")
        closed = int(closed_raw)
        if closed > 1_000_000 or closed != item.get("closed_trades"):
            raise HistoricalArchiveUnavailable("historical closed-trade count mismatch")
        metrics = {}
        for field in ("net_return_pct", "stress_net_return_pct", "max_drawdown_pct", "win_rate_pct"):
            val = _finite(row[field], field)
            if val != item.get(field):
                raise HistoricalArchiveUnavailable("historical numerical cell mismatch")
            metrics[field] = val
        pf = None if not row["profit_factor"] else _finite(row["profit_factor"], "profit_factor")
        if pf != item.get("profit_factor"):
            raise HistoricalArchiveUnavailable("historical profit factor mismatch")
        public.append({
            "symbol": pair, "timeframe": tf, "strategy": strategy,
            "net_return_pct": metrics["net_return_pct"],
            "stress_net_return_pct": metrics["stress_net_return_pct"],
            "closed_trades": closed, "max_drawdown_pct": metrics["max_drawdown_pct"],
            "win_rate_pct": metrics["win_rate_pct"], "profit_factor": pf,
            "qualification": "killed",
        })
        seen.add(key)
    if seen != {(p, t, s) for p in PAIRS for t in FRAMES for s in FAMILIES}:
        raise HistoricalArchiveUnavailable("historical result matrix incomplete")
    return {
        "contract_version": CONTRACT,
        "status": "verified_historical_only",
        "month_start_utc": summary["start_utc"],
        "month_end_exclusive_utc": summary["end_exclusive_utc"],
        "code_sha": source_pin,
        "report_sha256": report_pin,
        "dataset_count": len(bindings),
        "cell_count": len(public),
        "rejected_count": len(public),
        "qualified_count": 0,
        "source_claim": "Bybit-labelled pinned archive; not an external signature",
        "scope": "prior historical baseline, not new autonomous mechanisms or fresh data",
        "paper_only": True,
        "auto_demo_admission": False,
        "live_trading_authority": False,
        "cells": public,
    }


def archive_view() -> dict[str, Any]:
    try:
        return load_historical_month()
    except (ValueError, OSError, TypeError, KeyError) as exc:
        return {
            "contract_version": CONTRACT, "status": "unavailable",
            "reason": str(exc)[:120], "paper_only": True,
            "auto_demo_admission": False, "live_trading_authority": False,
            "cells": [],
        }
