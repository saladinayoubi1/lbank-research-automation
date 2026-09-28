"""Research-only 31-day four-pair Bybit Spot backtests, without strategy promotion.

Unlike the 240/500-bar runtime/discovery snapshots, this job retains the
ENTIRE common July 2026 monthly interval at each cadence. It consumes only
audited official public Bybit trade archives and fails closed on any gap.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

import bybit_spot_archive_audit as audit
import bybit_spot_archive_collector as collector
import bybit_spot_backfill as backfill
import nexus_multitimeframe_strategy_discovery as simulator
from nexus_multipair_trusted_surface import FAMILIES, SYMBOLS, TIMEFRAMES
from product_research_runtime import STRATEGY_PRESETS

START_DATE = "2026-07-01"
END_DATE = "2026-07-31"
MONTH = "2026-07"
EXPECTED_ROWS = {"minute15": 31 * 96, "hour1": 31 * 24, "hour4": 31 * 6}
STEPS = {"minute15": 900_000, "hour1": 3_600_000, "hour4": 14_400_000}
CONSERVATIVE = {"fee_bps": 10, "slippage_bps": 5}
STRESS = {"fee_bps": 25, "slippage_bps": 15}
FIELDS = (
    "symbol", "timeframe", "family", "first_utc", "last_utc", "bars",
    "coverage_days", "simulated_initial_usdt", "net_return_pct",
    "simulated_net_pnl_usdt", "max_drawdown_pct", "fills",
    "oos_return_pct", "oos_max_drawdown_pct", "oos_fills",
    "oos_sharpe", "stress_oos_return_pct", "stress_oos_drawdown_pct",
    "locked_holdout_bars", "monthly_coverage", "qualification",
    "demo_promoted", "live_enabled", "source_sha", "frame_sha256",
)


class MonthlyResearchError(RuntimeError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _verify_sources(state: Path, report: dict[str, Any]) -> list[dict[str, Any]]:
    summary = report["summary"]
    if (
        report["configuration"]["start_date"] != START_DATE
        or report["configuration"]["end_date"] != END_DATE
        or report["configuration"]["symbols"] != list(SYMBOLS)
        or summary["plan_units"] != 1
        or summary["plan_archives"] != len(SYMBOLS)
        or summary["completed_units"] != 1
        or summary["remaining_units"] != 0
        or summary["run_failures"] != 0
        or summary["backfill_complete"] is not True
        or summary["current_dataset_integrity_ok"] is not True
    ):
        raise MonthlyResearchError("monthly Bybit backfill source/quality did not pass")
    path = state / backfill.SOURCE_MANIFEST_NAME
    if path.is_symlink() or not path.is_file():
        raise MonthlyResearchError("official source manifest is unavailable or linked")
    sources = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(sources, list) or len(sources) != len(SYMBOLS):
        raise MonthlyResearchError("expected exactly four official July monthly sources")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in sources:
        symbol = str(row.get("symbol", ""))
        name = f"{symbol}-{MONTH}.csv.gz"
        sha = str(row.get("sha256", "")).lower()
        size = row.get("size_bytes")
        if (
            symbol not in SYMBOLS or symbol in seen
            or row.get("unit_id") != f"monthly:{MONTH}"
            or row.get("unit_kind") != "monthly"
            or row.get("filename") != name
            or row.get("url") != backfill.archive_url(symbol, name)
            or row.get("start_date") != START_DATE
            or row.get("end_date") != END_DATE
            or row.get("http_status") != 200
            or not isinstance(size, int) or isinstance(size, bool)
            or not (0 < size <= 2 * 1024 * 1024 * 1024)
            or len(sha) != 64 or any(ch not in "0123456789abcdef" for ch in sha)
            or int(row.get("source_rows", 0)) <= 0
            or int(row.get("valid_trade_rows", 0)) <= 0
        ):
            raise MonthlyResearchError("unverified official July source provenance")
        for name_field in (
            "invalid_numeric_rows", "invalid_symbol_rows", "invalid_side_rows",
            "non_positive_price_rows", "negative_size_rows", "outside_range_rows",
            "duplicate_trade_id_count", "source_rows_skipped", "malformed_csv_rows",
        ):
            if int(row.get(name_field, 0)) != 0:
                raise MonthlyResearchError("unverified raw trade archive quality")
        seen.add(symbol)
        result.append({"symbol": symbol, "filename": name, "sha256": sha, "size_bytes": size,
                       "url": row["url"], "http_status": 200})
    if seen != set(SYMBOLS):
        raise MonthlyResearchError("one or more official pairs missing")
    return sorted(result, key=lambda value: value["symbol"])


def _load_full_month(state: Path) -> dict[tuple[str, str], pd.DataFrame]:
    frames: dict[tuple[str, str], pd.DataFrame] = {}
    for tf in TIMEFRAMES:
        reference = None
        for symbol in SYMBOLS:
            path = state / "bybit_market" / collector.canonical_symbol(symbol) / f"{tf}.parquet"
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 20_000_000:
                raise MonthlyResearchError(f"unsafe or absent frame: {symbol}/{tf}")
            df = pd.read_parquet(path)
            if df.columns.tolist() != collector.CANONICAL_COLUMNS:
                raise MonthlyResearchError(f"unexpected archive columns: {symbol}/{tf}")
            df = df.copy()
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="raise")
            # The official 3-month backfill contains full May-July candles.
            # Extract exact July timestamps only; do not reuse its 500-row Discovery tail.
            july_start = pd.Timestamp(START_DATE, tz="UTC")
            august_start = pd.Timestamp("2026-08-01", tz="UTC")
            df = df.loc[(df["timestamp"] >= july_start) & (df["timestamp"] < august_start)].reset_index(drop=True)
            if len(df) != EXPECTED_ROWS[tf]:
                raise MonthlyResearchError(f"not a full 31-day series: {symbol}/{tf}")
            for column in ("open", "high", "low", "close", "volume"):
                df[column] = pd.to_numeric(df[column], errors="raise")
            if not df["timestamp"].is_monotonic_increasing or df["timestamp"].duplicated().any():
                raise MonthlyResearchError("non-monotonic or duplicate candles")
            ms = df["timestamp"].astype("int64").to_numpy() // 1_000_000
            if (
                int(ms[0]) != int(pd.Timestamp(START_DATE, tz="UTC").value // 1_000_000)
                or int(ms[-1]) != int(pd.Timestamp("2026-08-01", tz="UTC").value // 1_000_000) - STEPS[tf]
                or not (pd.Series(ms).diff().iloc[1:] == STEPS[tf]).all()
                or set(df["symbol"].astype(str)) != {symbol}
                or set(df["timeframe"].astype(str)) != {tf}
                or not df[["open", "high", "low", "close", "volume"]].map(math.isfinite).all().all()
                or (df[["open", "high", "low", "close"]] <= 0).any().any()
                or (df["volume"] < 0).any()
                or (df["high"] < df[["open", "low", "close"]].max(axis=1)).any()
                or (df["low"] > df[["open", "high", "close"]].min(axis=1)).any()
            ):
                raise MonthlyResearchError(f"full-month OHLCV integrity rejected: {symbol}/{tf}")
            dates = df["timestamp"].reset_index(drop=True)
            if reference is not None and not dates.equals(reference):
                raise MonthlyResearchError(f"four-symbol timestamp mismatch: {tf}")
            reference = dates
            frames[(symbol, tf)] = df.reset_index(drop=True)
    return frames


def calculate(frames: dict[tuple[str, str], pd.DataFrame], *, source_sha: str) -> dict[str, Any]:
    if len(source_sha) != 40 or any(ch not in "0123456789abcdef" for ch in source_sha):
        raise MonthlyResearchError("invalid pinned source SHA")
    if set(frames) != {(s, t) for s in SYMBOLS for t in TIMEFRAMES}:
        raise MonthlyResearchError("not exactly the approved four-pair/twelve-series matrix")
    rows = []
    for symbol in SYMBOLS:
        for tf in TIMEFRAMES:
            frame = frames[(symbol, tf)]
            if len(frame) != EXPECTED_ROWS[tf]:
                raise MonthlyResearchError("monthly coverage not verified")
            split = int(len(frame) * 0.7)
            frame_digest = _digest([
                [int(row.timestamp.value // 1_000_000), str(row.open), str(row.high),
                 str(row.low), str(row.close), str(row.volume)]
                for row in frame.itertuples(index=False)
            ])
            for family in FAMILIES:
                # Fixed, declared presets only: never rank on locked 30% holdout.
                target = simulator.generate_targets(frame, family, STRATEGY_PRESETS[family])
                full = simulator._simulate(
                    frame, target, 0, len(frame), CONSERVATIVE,
                    bars_per_year=simulator.TIMEFRAME_BARS_PER_YEAR[tf],
                )
                oos = simulator._simulate(
                    frame, target, split, len(frame), CONSERVATIVE,
                    bars_per_year=simulator.TIMEFRAME_BARS_PER_YEAR[tf],
                )
                stress = simulator._simulate(
                    frame, target, split, len(frame), STRESS,
                    bars_per_year=simulator.TIMEFRAME_BARS_PER_YEAR[tf],
                )
                rows.append({
                    "symbol": symbol, "timeframe": tf, "family": family,
                    "first_utc": frame["timestamp"].iloc[0].isoformat(),
                    "last_utc": frame["timestamp"].iloc[-1].isoformat(),
                    "bars": len(frame), "coverage_days": 31.0,
                    "simulated_initial_usdt": 10000,
                    "net_return_pct": round(full["total_return"] * 100, 4),
                    "simulated_net_pnl_usdt": round(full["total_return"] * 10000, 4),
                    "max_drawdown_pct": round(full["max_drawdown"] * 100, 4),
                    "fills": full["fill_count"],
                    "oos_return_pct": round(oos["total_return"] * 100, 4),
                    "oos_max_drawdown_pct": round(oos["max_drawdown"] * 100, 4),
                    "oos_fills": oos["fill_count"], "oos_sharpe": round(oos["sharpe"], 5),
                    "stress_oos_return_pct": round(stress["total_return"] * 100, 4),
                    "stress_oos_drawdown_pct": round(stress["max_drawdown"] * 100, 4),
                    "locked_holdout_bars": len(frame) - split,
                    "monthly_coverage": True,
                    "qualification": "RESEARCH_ONLY_REQUIRES_INDEPENDENT_REQUALIFICATION",
                    "demo_promoted": False, "live_enabled": False,
                    "source_sha": source_sha, "frame_sha256": frame_digest,
                })
    if len(rows) != 36 or any(row["demo_promoted"] or row["live_enabled"] for row in rows):
        raise MonthlyResearchError("monthly matrix not complete or authority widened")
    return {"contract": "nexus.bybit-monthly-pre-demo-table.v1", "source_sha": source_sha,
            "period": MONTH, "origin": "official_public_bybit_spot_trade_archive_aggregated",
            "bars_per_cadence": EXPECTED_ROWS, "locked_holdout_fraction": 0.3,
            "cost": {"conservative": CONSERVATIVE, "stress": STRESS},
            "research_only": True, "automatic_paper_promotion": False,
            "live_trading_authority": False, "rows": rows}


def run(*, source_sha: str, state: Path, cache: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise MonthlyResearchError("refuse to overwrite prior result directory")
    report = backfill.run_backfill(start_date=START_DATE, end_date=END_DATE,
                                   state_root=state, cache_root=cache, symbols=SYMBOLS,
                                   max_archives_per_run=len(SYMBOLS), clean=True)
    sources = _verify_sources(state, report)
    frames = _load_full_month(state)
    result = calculate(frames, source_sha=source_sha)
    result["archive_sources"] = sources
    result["source_manifest_sha256"] = _digest(sources)
    result["result_sha256"] = _digest(result)
    output.mkdir(parents=True, exist_ok=False)
    (output / "monthly-report.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False)+"\n", encoding="utf-8"
    )
    with (output / "monthly-table.csv").open("w", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(result["rows"])
    return result


def run_verified_three_month_backfill(*, source_sha: str, state: Path, output: Path) -> dict[str, Any]:
    """Use an already verified 12-archive May-July state before its cleanup.

    This is called by the existing policy-approved Multi-Pair archive workflow
    immediately after immutable historical snapshot verification. It never
    downloads the same official archive twice or changes the 500-row snapshot.
    """
    import nexus_multipair_archive_snapshot as archive

    if output.exists():
        raise MonthlyResearchError("refuse to overwrite prior monthly result")
    report_path = state / backfill.REPORT_NAME
    if report_path.is_symlink() or not report_path.is_file():
        raise MonthlyResearchError("existing official backfill report missing or linked")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    archive._validate_backfill_report(report)
    all_sources, all_source_digest = archive._source_evidence(state)
    july = sorted((s for s in all_sources if s["month"] == MONTH), key=lambda s: s["symbol"])
    if len(all_sources) != 12 or len(july) != len(SYMBOLS) or {s["symbol"] for s in july} != set(SYMBOLS):
        raise MonthlyResearchError("three-month official archive July provenance incomplete")
    frames = _load_full_month(state)
    result = calculate(frames, source_sha=source_sha)
    result["archive_sources"] = july
    result["verified_three_month_source_manifest_sha256"] = all_source_digest
    result["source_manifest_sha256"] = _digest(july)
    result["result_sha256"] = _digest(result)
    output.mkdir(parents=True, exist_ok=False)
    (output / "monthly-report.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    with (output / "monthly-table.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(result["rows"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--from-verified-three-month-state", action="store_true")
    args = parser.parse_args()
    if args.from_verified_three_month_state:
        outcome = run_verified_three_month_backfill(
            source_sha=args.source_sha, state=args.state_root, output=args.output_root
        )
    else:
        outcome = run(source_sha=args.source_sha, state=args.state_root,
                      cache=args.cache_root, output=args.output_root)
    print(json.dumps({"contract": outcome["contract"], "rows": len(outcome["rows"]),
                      "source_manifest_sha256": outcome["source_manifest_sha256"],
                      "result_sha256": outcome["result_sha256"], "demo_promoted": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
