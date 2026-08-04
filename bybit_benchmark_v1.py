from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from math import isfinite, sqrt
from pathlib import Path
from statistics import median
from typing import Any

import pandas as pd

from backtest_engine import BacktestConfig, run_target_exposure_backtest
from research_data import validate_research_frame

DEFAULT_MANIFEST = Path("experiments/bybit_benchmark_v1.json")
DEFAULT_OUTPUT_ROOT = Path("build/bybit_benchmark_v1")
BARS_PER_YEAR = {
    "minute15": 365.25 * 24 * 4,
    "hour1": 365.25 * 24,
    "hour4": 365.25 * 6,
}
STATUS_ZERO_FIELDS = [
    "missing_candles",
    "gap_count",
    "duplicate_count",
    "off_grid_count",
    "invalid_ohlc_count",
]


class BybitBenchmarkError(RuntimeError):
    pass


def normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return False
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no", ""}:
        return False
    raise BybitBenchmarkError(f"Unsupported boolean value: {value!r}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "schema_version",
        "experiment_id",
        "venue",
        "dataset",
        "holdout_start_utc",
        "minimum_rows",
        "series",
        "strategies",
        "execution_profiles",
        "qualification_policy",
    }
    missing = sorted(required.difference(manifest))
    if missing:
        raise BybitBenchmarkError(f"Manifest is missing keys: {missing}")
    if manifest["schema_version"] != 1:
        raise BybitBenchmarkError("Unsupported manifest schema_version")
    if manifest["venue"] != "bybit_spot_official_archives":
        raise BybitBenchmarkError("Unexpected venue identifier")
    if not manifest["series"] or not manifest["strategies"]:
        raise BybitBenchmarkError("Manifest must select series and strategies")
    if not manifest["execution_profiles"]:
        raise BybitBenchmarkError("Manifest must define execution profiles")

    for group, key in [
        (manifest["strategies"], "strategy_id"),
        (manifest["execution_profiles"], "profile_id"),
    ]:
        values = [str(item[key]) for item in group]
        if len(values) != len(set(values)):
            raise BybitBenchmarkError(f"Manifest contains duplicate {key} values")

    selected = [(item["symbol"], item["timeframe"]) for item in manifest["series"]]
    if len(selected) != len(set(selected)):
        raise BybitBenchmarkError("Manifest contains duplicate symbol/timeframe series")
    return manifest


def load_snapshot_hashes(snapshot_manifest_path: Path) -> dict[str, str]:
    if not snapshot_manifest_path.exists():
        raise BybitBenchmarkError(
            f"Snapshot manifest not found: {snapshot_manifest_path}"
        )
    payload = json.loads(snapshot_manifest_path.read_text(encoding="utf-8"))
    hashes: dict[str, str] = {}
    for item in payload:
        path = item.get("path")
        digest = item.get("sha256")
        if path and digest:
            hashes[str(path)] = str(digest)
    return hashes


def validate_status_row(
    status: pd.DataFrame,
    symbol: str,
    timeframe: str,
    minimum_rows: int,
) -> dict[str, Any]:
    required = {
        "symbol",
        "timeframe",
        "rows",
        "expected_rows",
        "integrity_ok",
        "status",
        *STATUS_ZERO_FIELDS,
    }
    missing = sorted(required.difference(status.columns))
    if missing:
        raise BybitBenchmarkError(f"Status report is missing columns: {missing}")

    match = status.loc[
        (status["symbol"].astype(str) == symbol)
        & (status["timeframe"].astype(str) == timeframe)
    ]
    if len(match) != 1:
        raise BybitBenchmarkError(
            f"Expected one status row for {symbol}/{timeframe}, found {len(match)}"
        )
    row = match.iloc[0].to_dict()
    rows = int(row["rows"])
    expected_rows = int(row["expected_rows"])
    if rows < minimum_rows:
        raise BybitBenchmarkError(
            f"Insufficient rows for {symbol}/{timeframe}: {rows} < {minimum_rows}"
        )
    if rows != expected_rows:
        raise BybitBenchmarkError(
            f"Row-count mismatch for {symbol}/{timeframe}: {rows} != {expected_rows}"
        )
    if not normalize_bool(row["integrity_ok"]):
        raise BybitBenchmarkError(f"Integrity failed for {symbol}/{timeframe}")
    if str(row["status"]).strip().lower() != "ready":
        raise BybitBenchmarkError(
            f"Unexpected status for {symbol}/{timeframe}: {row['status']}"
        )
    nonzero = {
        field: int(row[field])
        for field in STATUS_ZERO_FIELDS
        if int(row[field]) != 0
    }
    if nonzero:
        raise BybitBenchmarkError(
            f"Nonzero integrity counters for {symbol}/{timeframe}: {nonzero}"
        )
    return row


def load_series(
    dataset_root: Path,
    status: pd.DataFrame,
    snapshot_hashes: dict[str, str],
    symbol: str,
    timeframe: str,
    minimum_rows: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    status_row = validate_status_row(status, symbol, timeframe, minimum_rows)
    relative_path = f"bybit_market/{symbol}/{timeframe}.parquet"
    parquet_path = dataset_root / relative_path
    if not parquet_path.exists():
        raise BybitBenchmarkError(f"Parquet file not found: {parquet_path}")
    expected_digest = snapshot_hashes.get(relative_path)
    if not expected_digest:
        raise BybitBenchmarkError(
            f"Snapshot manifest has no hash for {relative_path}"
        )
    actual_digest = sha256_file(parquet_path)
    if actual_digest != expected_digest:
        raise BybitBenchmarkError(
            f"Parquet SHA-256 mismatch for {relative_path}: "
            f"{actual_digest} != {expected_digest}"
        )

    frame = pd.read_parquet(parquet_path)
    validated = validate_research_frame(frame, symbol, timeframe)
    if len(validated) != int(status_row["rows"]):
        raise BybitBenchmarkError(
            f"Loaded row count differs from status for {symbol}/{timeframe}"
        )
    return validated, status_row


def build_target_exposures(
    frame: pd.DataFrame,
    strategy: dict[str, Any],
) -> pd.Series:
    strategy_id = str(strategy["strategy_id"])
    close = pd.to_numeric(frame["close"], errors="raise")

    if strategy_id == "buy_and_hold":
        return pd.Series(1.0, index=frame.index, dtype="float64")

    if strategy_id == "sma_long_flat":
        parameters = strategy.get("parameters", {})
        fast_window = int(parameters.get("fast_window", 50))
        slow_window = int(parameters.get("slow_window", 200))
        if fast_window < 1 or slow_window < 2 or fast_window >= slow_window:
            raise BybitBenchmarkError("SMA windows must satisfy 1 <= fast < slow")
        fast = close.rolling(fast_window, min_periods=fast_window).mean()
        slow = close.rolling(slow_window, min_periods=slow_window).mean()
        return (fast > slow).astype("float64")

    if strategy_id == "donchian_long_flat":
        parameters = strategy.get("parameters", {})
        entry_window = int(parameters.get("entry_window", 55))
        exit_window = int(parameters.get("exit_window", 20))
        if exit_window < 2 or entry_window <= exit_window:
            raise BybitBenchmarkError(
                "Donchian windows must satisfy 2 <= exit < entry"
            )
        prior_entry_high = close.shift(1).rolling(
            entry_window, min_periods=entry_window
        ).max()
        prior_exit_low = close.shift(1).rolling(
            exit_window, min_periods=exit_window
        ).min()
        exposure = 0.0
        targets: list[float] = []
        for index, price in enumerate(close):
            entry_level = prior_entry_high.iloc[index]
            exit_level = prior_exit_low.iloc[index]
            if exposure == 0.0 and pd.notna(entry_level) and price > entry_level:
                exposure = 1.0
            elif exposure == 1.0 and pd.notna(exit_level) and price < exit_level:
                exposure = 0.0
            targets.append(exposure)
        return pd.Series(targets, index=frame.index, dtype="float64")

    raise BybitBenchmarkError(f"Unsupported strategy_id: {strategy_id}")


def calculate_risk_metrics(
    equity_curve: pd.DataFrame,
    timeframe: str,
    initial_cash: float,
) -> dict[str, float | None]:
    bars_per_year = BARS_PER_YEAR.get(timeframe)
    if bars_per_year is None:
        raise BybitBenchmarkError(f"Unsupported timeframe: {timeframe}")
    equity = pd.to_numeric(equity_curve["equity"], errors="raise")
    returns = (
        equity.pct_change()
        .replace([float("inf"), float("-inf")], float("nan"))
        .dropna()
    )
    annualized_volatility: float | None = None
    sharpe_like: float | None = None
    if not returns.empty:
        standard_deviation = float(returns.std(ddof=0))
        annualized_volatility = standard_deviation * sqrt(bars_per_year)
        if standard_deviation > 0:
            sharpe_like = float(returns.mean()) / standard_deviation * sqrt(
                bars_per_year
            )

    start = pd.Timestamp(equity_curve.iloc[0]["timestamp"])
    end = pd.Timestamp(equity_curve.iloc[-1]["timestamp"])
    elapsed_years = max(
        (end - start).total_seconds() / (365.25 * 24 * 3600), 0.0
    )
    final_equity = float(equity.iloc[-1])
    annualized_return: float | None = None
    if elapsed_years > 0 and final_equity > 0:
        annualized_return = (final_equity / initial_cash) ** (
            1.0 / elapsed_years
        ) - 1.0

    values = {
        "annualized_return": annualized_return,
        "annualized_volatility": annualized_volatility,
        "sharpe_like_zero_rate": sharpe_like,
    }
    for name, value in list(values.items()):
        if value is not None and not isfinite(value):
            values[name] = None
    return values


def run_period(
    frame: pd.DataFrame,
    targets: pd.Series,
    timeframe: str,
    profile: dict[str, Any],
    period: str,
    holdout_start: pd.Timestamp,
) -> dict[str, Any]:
    if period == "full":
        selected_frame = frame.reset_index(drop=True)
        selected_targets = targets.reset_index(drop=True)
    elif period == "holdout":
        mask = frame["timestamp"] >= holdout_start
        selected_frame = frame.loc[mask].reset_index(drop=True)
        selected_targets = targets.loc[mask].reset_index(drop=True)
    else:
        raise BybitBenchmarkError(f"Unsupported period: {period}")
    if len(selected_frame) < 2:
        raise BybitBenchmarkError(f"Period {period} has fewer than two bars")

    config = BacktestConfig(
        initial_cash=float(profile["initial_cash"]),
        fee_bps=float(profile["fee_bps"]),
        slippage_bps=float(profile["slippage_bps"]),
        max_abs_exposure=float(profile["max_abs_exposure"]),
        liquidate_at_end=bool(profile["liquidate_at_end"]),
    )
    result = run_target_exposure_backtest(
        selected_frame,
        selected_targets,
        config,
    )
    risk = calculate_risk_metrics(
        result.equity_curve,
        timeframe,
        initial_cash=config.initial_cash,
    )
    return {
        "period": period,
        "first_candle_utc": selected_frame.iloc[0]["timestamp"].isoformat(),
        "last_candle_utc": selected_frame.iloc[-1]["timestamp"].isoformat(),
        **result.metrics,
        **risk,
    }


def evaluate_qualification(
    runs: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    policy = manifest["qualification_policy"]
    profile_id = str(policy["profile_id"])
    period = str(policy.get("period", "holdout"))
    benchmark_strategy = str(policy.get("benchmark_strategy_id", "buy_and_hold"))
    candidates: list[dict[str, Any]] = []

    timeframes = sorted({item["timeframe"] for item in manifest["series"]})
    symbols_by_timeframe = {
        timeframe: sorted(
            item["symbol"]
            for item in manifest["series"]
            if item["timeframe"] == timeframe
        )
        for timeframe in timeframes
    }
    strategies = [
        str(item["strategy_id"])
        for item in manifest["strategies"]
        if str(item["strategy_id"]) != benchmark_strategy
    ]

    for strategy_id in strategies:
        for timeframe in timeframes:
            expected_symbols = symbols_by_timeframe[timeframe]
            selected = [
                run
                for run in runs
                if run["strategy_id"] == strategy_id
                and run["timeframe"] == timeframe
                and run["profile_id"] == profile_id
                and run["period"] == period
            ]
            by_symbol = {run["symbol"]: run for run in selected}
            missing_symbols = sorted(set(expected_symbols).difference(by_symbol))
            successful = [
                by_symbol[symbol]
                for symbol in expected_symbols
                if symbol in by_symbol and by_symbol[symbol]["success"]
            ]
            returns = [float(run["total_return"]) for run in successful]
            drawdowns = [float(run["max_drawdown"]) for run in successful]
            sharpes = [run.get("sharpe_like_zero_rate") for run in successful]
            fills = [int(run["fill_count"]) for run in successful]

            checks = {
                "all_symbols_present": not missing_symbols,
                "all_runs_successful": len(successful) == len(expected_symbols),
                "all_returns_positive": bool(returns)
                and all(value > float(policy["minimum_total_return"]) for value in returns),
                "median_return": bool(returns)
                and median(returns) >= float(policy["minimum_median_total_return"]),
                "maximum_drawdown": bool(drawdowns)
                and max(drawdowns) <= float(policy["maximum_drawdown"]),
                "all_sharpe_positive": bool(sharpes)
                and all(value is not None and float(value) > float(policy["minimum_sharpe_like"]) for value in sharpes),
                "minimum_fills": bool(fills)
                and min(fills) >= int(policy["minimum_fill_count"]),
            }
            failed_checks = sorted(name for name, passed in checks.items() if not passed)
            candidates.append(
                {
                    "strategy_id": strategy_id,
                    "timeframe": timeframe,
                    "profile_id": profile_id,
                    "period": period,
                    "expected_symbols": expected_symbols,
                    "missing_symbols": missing_symbols,
                    "successful_runs": len(successful),
                    "median_total_return": median(returns) if returns else None,
                    "worst_max_drawdown": max(drawdowns) if drawdowns else None,
                    "minimum_sharpe_like": min(float(value) for value in sharpes if value is not None) if any(value is not None for value in sharpes) else None,
                    "minimum_fill_count": min(fills) if fills else None,
                    "checks": checks,
                    "failed_checks": failed_checks,
                    "qualifies_for_paper_forward_review": not failed_checks,
                }
            )
    return candidates


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        f"# {report['experiment_id']}",
        "",
        f"Generated at: {report['generated_at_utc']}",
        f"Manifest SHA-256: `{report['manifest_sha256']}`",
        f"Dataset archive SHA-256: `{report['dataset']['archive_sha256']}`",
        "",
        "## Dataset gate",
        "",
        f"- Selected series ready: {summary['ready_series']} / {summary['selected_series']}",
        f"- Expected runs: {summary['expected_runs']}",
        f"- Successful runs: {summary['successful_runs']}",
        f"- Failed runs: {summary['failed_runs']}",
        f"- Paper-forward review candidates: {summary['paper_forward_review_candidates']}",
        "",
        "## Paper-forward review gate",
        "",
        "Passing this gate does not start live trading or paper forward automatically. It only authorizes a separate review and implementation step.",
        "",
        "| Strategy | Timeframe | Qualified | Median holdout return | Worst max DD | Minimum Sharpe-like | Minimum fills | Failed checks |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for item in report["qualifications"]:
        median_return = item["median_total_return"]
        worst_dd = item["worst_max_drawdown"]
        min_sharpe = item["minimum_sharpe_like"]
        lines.append(
            "| {strategy_id} | {timeframe} | {qualified} | {median_return} | {worst_dd} | {min_sharpe} | {fills} | {failed} |".format(
                strategy_id=item["strategy_id"],
                timeframe=item["timeframe"],
                qualified=item["qualifies_for_paper_forward_review"],
                median_return="" if median_return is None else f"{median_return:.2%}",
                worst_dd="" if worst_dd is None else f"{worst_dd:.2%}",
                min_sharpe="" if min_sharpe is None else f"{min_sharpe:.3f}",
                fills="" if item["minimum_fill_count"] is None else item["minimum_fill_count"],
                failed=", ".join(item["failed_checks"]) or "none",
            )
        )

    lines.extend(
        [
            "",
            "## Conservative holdout runs",
            "",
            "| Symbol | Timeframe | Strategy | Return | Max DD | Sharpe-like | Fills | Success | Error |",
            "|---|---|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for run in report["runs"]:
        if run["period"] != "holdout" or run["profile_id"] != "conservative":
            continue
        total_return = run.get("total_return")
        max_drawdown = run.get("max_drawdown")
        sharpe = run.get("sharpe_like_zero_rate")
        lines.append(
            "| {symbol} | {timeframe} | {strategy_id} | {ret} | {dd} | {sharpe} | {fills} | {success} | {error} |".format(
                symbol=run["symbol"],
                timeframe=run["timeframe"],
                strategy_id=run["strategy_id"],
                ret="" if total_return is None else f"{total_return:.2%}",
                dd="" if max_drawdown is None else f"{max_drawdown:.2%}",
                sharpe="" if sharpe is None else f"{sharpe:.3f}",
                fills=run.get("fill_count", ""),
                success=run["success"],
                error=run.get("error") or "",
            )
        )
    return "\n".join(lines) + "\n"


def write_reports(
    report: dict[str, Any],
    manifest_path: Path,
    output_root: Path,
) -> None:
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True)

    (output_root / "bybit_benchmark_v1.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_root / "bybit_benchmark_v1.md").write_text(
        render_markdown(report), encoding="utf-8"
    )
    pd.DataFrame(report["runs"]).to_csv(
        output_root / "bybit_benchmark_v1_runs.csv", index=False
    )
    pd.DataFrame(report["qualifications"]).drop(columns=["checks"], errors="ignore").to_csv(
        output_root / "paper_forward_review_candidates.csv", index=False
    )
    shutil.copy2(manifest_path, output_root / manifest_path.name)


def run_benchmark(manifest_path: Path) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    dataset = manifest["dataset"]
    dataset_root = Path(dataset["dataset_root"])
    status_path = Path(dataset["status_path"])
    snapshot_manifest_path = Path(dataset["snapshot_manifest_path"])
    if not status_path.exists():
        raise BybitBenchmarkError(f"Status report not found: {status_path}")

    status = pd.read_csv(status_path)
    snapshot_hashes = load_snapshot_hashes(snapshot_manifest_path)
    minimum_rows = int(manifest["minimum_rows"])
    holdout_start = pd.Timestamp(manifest["holdout_start_utc"])
    if holdout_start.tzinfo is None:
        holdout_start = holdout_start.tz_localize("UTC")
    else:
        holdout_start = holdout_start.tz_convert("UTC")

    runs: list[dict[str, Any]] = []
    ready_series: list[dict[str, Any]] = []
    for series in manifest["series"]:
        symbol = str(series["symbol"])
        timeframe = str(series["timeframe"])
        try:
            frame, status_row = load_series(
                dataset_root,
                status,
                snapshot_hashes,
                symbol,
                timeframe,
                minimum_rows,
            )
            ready_series.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "rows": int(status_row["rows"]),
                    "first_candle_utc": status_row.get("first_candle_utc"),
                    "last_candle_utc": status_row.get("last_candle_utc"),
                }
            )
        except Exception as exc:
            for strategy in manifest["strategies"]:
                for profile in manifest["execution_profiles"]:
                    for period in ["full", "holdout"]:
                        runs.append(
                            {
                                "symbol": symbol,
                                "timeframe": timeframe,
                                "strategy_id": strategy["strategy_id"],
                                "profile_id": profile["profile_id"],
                                "period": period,
                                "success": False,
                                "error": f"{type(exc).__name__}: {exc}",
                            }
                        )
            continue

        for strategy in manifest["strategies"]:
            strategy_id = str(strategy["strategy_id"])
            try:
                targets = build_target_exposures(frame, strategy)
            except Exception as exc:
                for profile in manifest["execution_profiles"]:
                    for period in ["full", "holdout"]:
                        runs.append(
                            {
                                "symbol": symbol,
                                "timeframe": timeframe,
                                "strategy_id": strategy_id,
                                "profile_id": profile["profile_id"],
                                "period": period,
                                "success": False,
                                "error": f"{type(exc).__name__}: {exc}",
                            }
                        )
                continue

            for profile in manifest["execution_profiles"]:
                for period in ["full", "holdout"]:
                    base = {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "strategy_id": strategy_id,
                        "profile_id": str(profile["profile_id"]),
                        "period": period,
                    }
                    try:
                        values = run_period(
                            frame,
                            targets,
                            timeframe,
                            profile,
                            period,
                            holdout_start,
                        )
                        runs.append({**base, "success": True, "error": None, **values})
                    except Exception as exc:
                        runs.append(
                            {
                                **base,
                                "success": False,
                                "error": f"{type(exc).__name__}: {exc}",
                            }
                        )

    expected_runs = (
        len(manifest["series"])
        * len(manifest["strategies"])
        * len(manifest["execution_profiles"])
        * 2
    )
    successful_runs = sum(bool(run["success"]) for run in runs)
    qualifications = evaluate_qualification(runs, manifest)
    qualified = sum(
        bool(item["qualifies_for_paper_forward_review"])
        for item in qualifications
    )
    return {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "experiment_id": manifest["experiment_id"],
        "venue": manifest["venue"],
        "manifest_path": manifest_path.as_posix(),
        "manifest_sha256": sha256_file(manifest_path),
        "dataset": dataset,
        "holdout_start_utc": holdout_start.isoformat(),
        "ready_series": ready_series,
        "summary": {
            "selected_series": len(manifest["series"]),
            "ready_series": len(ready_series),
            "expected_runs": expected_runs,
            "successful_runs": successful_runs,
            "failed_runs": expected_runs - successful_runs,
            "paper_forward_review_candidates": qualified,
            "automatic_paper_forward_started": False,
            "live_trading_enabled": False,
        },
        "qualifications": qualifications,
        "runs": runs,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the versioned Bybit baseline and holdout research benchmark."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--require-all-runs", action="store_true")
    parser.add_argument("--require-all-series-ready", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_benchmark(args.manifest)
    write_reports(report, args.manifest, args.output_root)
    print(json.dumps(report["summary"], sort_keys=True))
    if args.require_all_series_ready and (
        report["summary"]["ready_series"] != report["summary"]["selected_series"]
    ):
        return 1
    if args.require_all_runs and report["summary"]["failed_runs"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
