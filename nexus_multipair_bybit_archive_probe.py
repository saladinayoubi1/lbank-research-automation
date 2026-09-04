"""Bounded four-symbol probe of Bybit's official public Spot trade archive.

This probe exists to qualify an acquisition transport for Multi-Pair Discovery
when the physical runner cannot reach Bybit REST. It does not substitute an
exchange or use a proxy: every byte comes from https://public.bybit.com/spot.
The probe is Research-only, records raw archive SHA-256 provenance, derives the
symbol surface from the trusted Multi-Pair matrix, and never grants Paper/Live
or strategy-promotion authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd

import bybit_spot_archive_audit as archive_audit
from nexus_multipair_trusted_surface import SYMBOLS, TIMEFRAMES
from run_bybit_spot_archive_audit import robust_download_archive


SCHEMA = "nexus.multipair-bybit-official-archive-probe.v1"
DEFAULT_AUDIT_DATE = "2026-07-01"
OFFICIAL_ARCHIVE_BASE_URL = "https://public.bybit.com/spot"
MAX_RAW_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


class MultiPairBybitArchiveProbeError(RuntimeError):
    pass


Downloader = Callable[[str, str, Path], Mapping[str, Any]]


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MultiPairBybitArchiveProbeError("probe evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _archive_quality_passed(quality: Mapping[str, Any]) -> bool:
    fields = (
        "invalid_numeric_rows",
        "invalid_symbol_rows",
        "invalid_side_rows",
        "non_positive_price_rows",
        "negative_size_rows",
        "outside_audit_day_rows",
        "duplicate_trade_id_count",
    )
    return bool(
        int(quality.get("source_rows", 0)) > 0
        and int(quality.get("valid_trade_rows", 0)) > 0
        and sum(int(quality.get(field, 0)) for field in fields) == 0
    )


def _validate_download_record(
    record: Mapping[str, Any], symbol: str, audit_date: str
) -> Path:
    expected_url = archive_audit.archive_url(symbol, audit_date)
    if record.get("symbol") != symbol or record.get("audit_date") != audit_date:
        raise MultiPairBybitArchiveProbeError("archive download identity mismatch")
    if record.get("url") != expected_url or not expected_url.startswith(
        OFFICIAL_ARCHIVE_BASE_URL + "/"
    ):
        raise MultiPairBybitArchiveProbeError("archive source is not the official Bybit Spot archive")
    if record.get("http_status") != 200:
        raise MultiPairBybitArchiveProbeError("archive download did not return HTTP 200")
    size = record.get("size_bytes")
    if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_RAW_ARCHIVE_BYTES:
        raise MultiPairBybitArchiveProbeError("archive size is outside bounded probe limits")
    sha256 = str(record.get("sha256", "")).lower()
    if not _HEX64_RE.fullmatch(sha256):
        raise MultiPairBybitArchiveProbeError("archive SHA-256 is invalid")
    path = Path(str(record.get("path", ""))).resolve()
    if path.is_symlink() or not path.is_file() or path.stat().st_size != size:
        raise MultiPairBybitArchiveProbeError("archive cache file failed regular-file/size validation")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != sha256:
        raise MultiPairBybitArchiveProbeError("archive cache SHA-256 mismatch")
    return path


def build_probe(
    *,
    audit_date: str = DEFAULT_AUDIT_DATE,
    cache_root: str | Path,
    downloader: Downloader = robust_download_archive,
) -> dict[str, Any]:
    date = pd.Timestamp(audit_date)
    if date.tzinfo is not None:
        raise MultiPairBybitArchiveProbeError("audit_date must be a UTC calendar date without timezone")
    normalized_date = date.strftime("%Y-%m-%d")
    if normalized_date != audit_date:
        raise MultiPairBybitArchiveProbeError("audit_date must use YYYY-MM-DD form")
    if tuple(TIMEFRAMES) != tuple(archive_audit.TIMEFRAME_RULES):
        raise MultiPairBybitArchiveProbeError("trusted Multi-Pair timeframes do not match archive aggregation rules")
    if len(SYMBOLS) != 4 or len(SYMBOLS) * len(TIMEFRAMES) != 12:
        raise MultiPairBybitArchiveProbeError("trusted Multi-Pair surface is not 4 symbols / 12 cells")

    root = Path(cache_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    archives: list[dict[str, Any]] = []
    series: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for symbol in SYMBOLS:
        try:
            record = dict(downloader(symbol, normalized_date, root))
            path = _validate_download_record(record, symbol, normalized_date)
            frame, schema = archive_audit.read_trade_archive(path)
            valid, quality = archive_audit.validate_trades(frame, symbol, normalized_date)
            archive_passed = _archive_quality_passed(quality)
            archive_row = {
                "symbol": symbol,
                "audit_date": normalized_date,
                "url": record["url"],
                "size_bytes": record["size_bytes"],
                "sha256": str(record["sha256"]).lower(),
                "http_status": 200,
                "download_attempts": int(record.get("download_attempts", 0)),
                "loaded_from_cache": bool(record.get("loaded_from_cache", False)),
                "used_positional_schema": bool(schema.get("used_positional_schema")),
                "timestamp_unit": schema.get("timestamp_unit"),
                "malformed_csv_rows": int(schema.get("malformed_csv_rows", 0)),
                "source_rows_parsed": int(schema.get("source_rows_parsed", 0)),
                "source_rows_skipped": int(schema.get("source_rows_skipped", 0)),
                **{key: int(value) for key, value in quality.items()},
                "archive_passed": archive_passed,
            }
            archives.append(archive_row)
            for timeframe in TIMEFRAMES:
                candles = archive_audit.trades_to_candles(
                    valid, symbol, timeframe, normalized_date
                )
                series.append(
                    archive_audit.audit_candles(
                        candles, symbol, timeframe, normalized_date
                    )
                )
        except Exception as exc:
            errors.append(
                {
                    "symbol": symbol,
                    "audit_date": normalized_date,
                    "error_type": type(exc).__name__,
                    "error_digest": _digest(
                        {"type": type(exc).__name__, "message": str(exc)}
                    ),
                }
            )

    archives.sort(key=lambda row: row["symbol"])
    series.sort(key=lambda row: (row["symbol"], row["timeframe"]))
    expected_cells = {(symbol, timeframe) for symbol in SYMBOLS for timeframe in TIMEFRAMES}
    passed_archives = sum(bool(row["archive_passed"]) for row in archives)
    passed_series = sum(bool(row["audit_passed"]) for row in series)
    source_ok = all(
        row["url"] == archive_audit.archive_url(row["symbol"], normalized_date)
        and row["url"].startswith(OFFICIAL_ARCHIVE_BASE_URL + "/")
        for row in archives
    )
    complete = bool(
        len(archives) == len(SYMBOLS)
        and passed_archives == len(SYMBOLS)
        and len(series) == len(expected_cells) == 12
        and passed_series == len(expected_cells)
        and {(row["symbol"], row["timeframe"]) for row in series} == expected_cells
        and source_ok
        and not errors
    )
    core = {
        "schema_version": SCHEMA,
        "audit_date": normalized_date,
        "venue": "Bybit",
        "market_type": "spot",
        "source": "official_public_spot_trade_archive",
        "archive_base_url": OFFICIAL_ARCHIVE_BASE_URL,
        "trusted_surface_source": "config/nexus-demo-strategy-matrix-v2.json",
        "symbols": list(SYMBOLS),
        "timeframes": list(TIMEFRAMES),
        "expected_cell_count": 12,
        "archives": archives,
        "series": series,
        "errors": errors,
        "archives_passed": passed_archives,
        "series_passed": passed_series,
        "decision": "pass" if complete else "reject",
        "research_only": True,
        "paper_execution_started": False,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "real_exchange_orders": False,
        "automatic_strategy_promotion": False,
        "silent_exchange_substitution": False,
        "third_party_proxy_used": False,
        "issue_984_state_touched": False,
    }
    return {**core, "probe_digest": _digest(core)}


def verify_probe(value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {
        "schema": False,
        "digest": False,
        "source": False,
        "shape": False,
        "quality": False,
        "authority": False,
    }
    try:
        core = dict(value)
        claimed = core.pop("probe_digest", None)
        checks["schema"] = bool(
            core.get("schema_version") == SCHEMA
            and _HEX64_RE.fullmatch(str(claimed or ""))
            and core.get("decision") == "pass"
        )
        checks["digest"] = claimed == _digest(core)
        archives = core.get("archives")
        series = core.get("series")
        audit_date = str(core.get("audit_date", ""))
        expected_cells = {(symbol, timeframe) for symbol in SYMBOLS for timeframe in TIMEFRAMES}
        checks["source"] = bool(
            core.get("venue") == "Bybit"
            and core.get("market_type") == "spot"
            and core.get("source") == "official_public_spot_trade_archive"
            and core.get("archive_base_url") == OFFICIAL_ARCHIVE_BASE_URL
            and isinstance(archives, list)
            and len(archives) == len(SYMBOLS)
            and all(
                isinstance(row, Mapping)
                and row.get("symbol") in SYMBOLS
                and row.get("url") == archive_audit.archive_url(str(row.get("symbol")), audit_date)
                and str(row.get("url", "")).startswith(OFFICIAL_ARCHIVE_BASE_URL + "/")
                and row.get("http_status") == 200
                and _HEX64_RE.fullmatch(str(row.get("sha256", "")))
                for row in archives
            )
        )
        checks["shape"] = bool(
            core.get("trusted_surface_source") == "config/nexus-demo-strategy-matrix-v2.json"
            and core.get("symbols") == list(SYMBOLS)
            and core.get("timeframes") == list(TIMEFRAMES)
            and core.get("expected_cell_count") == 12
            and isinstance(series, list)
            and len(series) == 12
            and {(row.get("symbol"), row.get("timeframe")) for row in series if isinstance(row, Mapping)} == expected_cells
        )
        checks["quality"] = bool(
            isinstance(archives, list)
            and isinstance(series, list)
            and core.get("archives_passed") == len(SYMBOLS)
            and core.get("series_passed") == 12
            and core.get("errors") == []
            and all(row.get("archive_passed") is True for row in archives if isinstance(row, Mapping))
            and all(row.get("audit_passed") is True for row in series if isinstance(row, Mapping))
        )
        checks["authority"] = bool(
            core.get("research_only") is True
            and core.get("paper_execution_started") is False
            and core.get("live_trading_authority") is False
            and core.get("private_credentials_used") is False
            and core.get("real_exchange_orders") is False
            and core.get("automatic_strategy_promotion") is False
            and core.get("silent_exchange_substitution") is False
            and core.get("third_party_proxy_used") is False
            and core.get("issue_984_state_touched") is False
        )
    except Exception:
        pass
    return {
        "decision": "pass" if all(checks.values()) else "reject",
        "checks": checks,
        "probe_digest": value.get("probe_digest"),
    }


def write_probe(value: Mapping[str, Any], output_root: str | Path, *, clean: bool = False) -> Path:
    root = Path(output_root).resolve()
    if clean and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / "evidence.json"
    target.write_text(
        json.dumps(dict(value), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-date", default=DEFAULT_AUDIT_DATE)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--max-attempts", type=int, default=5)
    args = parser.parse_args()

    def downloader(symbol: str, audit_date: str, cache_root: Path) -> Mapping[str, Any]:
        return robust_download_archive(
            symbol,
            audit_date,
            cache_root,
            max_attempts=args.max_attempts,
        )

    result = build_probe(
        audit_date=args.audit_date,
        cache_root=args.cache_root,
        downloader=downloader,
    )
    write_probe(result, args.output_root, clean=True)
    verification = verify_probe(result)
    print(json.dumps({
        "decision": result["decision"],
        "archives_passed": result["archives_passed"],
        "series_passed": result["series_passed"],
        "probe_digest": result["probe_digest"],
        "verification": verification["decision"],
    }, sort_keys=True))
    return 0 if verification["decision"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
