from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from math import isfinite, sqrt
from pathlib import Path
from typing import Any

import pandas as pd

from backtest_engine import BacktestConfig, run_target_exposure_backtest
from data_readiness import evaluate_readiness
from research_data import load_research_series

DEFAULT_MANIFEST = Path("experiments/lbank_benchmark_v1.json")
DEFAULT_OUTPUT_ROOT = Path("build/lbank_benchmark_v1")
BARS_PER_YEAR = {
    "minute15": 365.25 * 24 * 4,
    "hour1": 365.25 * 24,
    "hour4": 365.25 * 6,
}


class BenchmarkError(RuntimeError):
    pass


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "schema_version",
        "experiment_id",
        "venue",
        "dataset_root",
        "minimum_rows",
        "series",
        "strategies",
        "execution_profiles",
        "suitability_policy",
    }
    missing = sorted(required.difference(manifest))
    if missing:
        raise BenchmarkError(f"Manifest is missing keys: {missing}")
    if manifest["schema_version"] != 1:
        raise BenchmarkError("Unsupported manifest schema_version")
    if not manifest["series"]:
        raise BenchmarkError("Manifest must select at least one series")
    if not manifest["strategies"]:
        raise BenchmarkError("Manifest must define at least one strategy")
    if not manifest["execution_profiles"]:
        raise BenchmarkError("Manifest must define at least one execution profile")

    for group, key in [
        (manifest["strategies"], "strategy_id"),
        (manifest["execution_profiles"], "profile_id"),
    ]:
        values = [item[key] for item in group]
        if len(values) != len(set(values)):
            raise BenchmarkError(f"Manifest contains duplicate {key} values")
    return manifest


def manifest_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_target_exposures(
    frame: pd.DataFrame,
    strategy: dict[str, Any],
) -> pd.Series:
    strategy_id = strategy["strategy_id"]
    if strategy_id == "buy_and_hold":
        return pd.Series(1.0, index=frame.index, dtype="float64")

    if strategy_id == "sma_long_flat":
        parameters = strategy.get("parameters", {})
        fast_window = int(parameters.get("fast_window", 50))
        slow_window = int(parameters.get("slow_window", 200))
        if fast_window < 1 or slow_window < 2 or fast_window >= slow_window:
            raise BenchmarkError("SMA windows must satisfy 1 <= fast < slow")

        close = pd.to_numeric(frame["close"], errors="raise")
        fast = close.rolling(fast_window, min_periods=fast_window).mean()
        slow = close.rolling(slow_window, min_periods=slow_window).mean()
        return (fast > slow).astype("float64")

    raise BenchmarkError(f"Unsupported strategy_id: {strategy_id}")


def calculate_risk_metrics(
    equity_curve: pd.DataFrame,
    timeframe: str,
    initial_cash: float,
) -> dict[str, float | None]:
    equity = pd.to_numeric(equity_curve["equity"], errors="raise")
    returns = equity.pct_change().replace([float("inf"), float("-inf")], pd.NA).dropna()
    bars_per_year = BARS_PER_YEAR.get(timeframe)
    if bars_per_year is None:
        raise BenchmarkError(f"Unsupported timeframe for annualization: {timeframe}")

    annualized_volatility: float | None = None
    sharpe_like: float | None = None
    if not returns.empty:
        standard_deviation = float(returns.std(ddof=0))
        annualized_volatility = standard_deviation * sqrt(bars_per_year)
        if standard_deviation > 0:
            sharpe_like = float(returns.mean()) / standard_deviation * sqrt(bars_per_year)

    start = pd.Timestamp(equity_curve.iloc[0]["timestamp"])
    end = pd.Timestamp(equity_curve.iloc[-1]["timestamp"])
    elapsed_years = max((end - start).total_seconds() / (365.25 * 24 * 3600), 0.0)
    final_equity = float(equity.iloc[-1])
    annualized_return: float | None = None
    if elapsed_years > 0 and initial_cash > 0 and final_equity > 0:
        annualized_return = (final_equity / initial_cash) ** (1.0 / elapsed_years) - 1.0

    values = {
        "annualized_return": annualized_return,
        "annualized_volatility": annualized_volatility,
        "sharpe_like_zero_rate": sharpe_like,
    }
    for name, value in values.items():
        if value is not None and not isfinite(value):
            values[name] = None
    return values


def summarize_dataset(
    status: pd.DataFrame,
    selected_series: list[dict[str, str]],
    minimum_rows: int,
) -> tuple[dict[str, Any], pd.DataFrame]:
    readiness = evaluate_readiness(status, minimum_rows=minimum_rows)
    selected_keys = {
        (series["symbol"], series["timeframe"])
        for series in selected_series
    }
    readiness_keys = list(zip(readiness["symbol"], readiness["timeframe"]))
    selected_mask = pd.Series(
        [key in selected_keys for key in readiness_keys],
        index=readiness.index,
    )

    total_series = int(len(readiness))
    ready_series = int(readiness["ready_for_research"].sum())
    selected_rows = readiness.loc[selected_mask]
    selected_ready = int(selected_rows["ready_for_research"].sum())

    return {
        "total_series": total_series,
        "ready_series": ready_series,
        "blocked_series": total_series - ready_series,
        "overall_ready_ratio": ready_series / total_series if total_series else 0.0,
        "selected_series": len(selected_series),
        "selected_series_found": int(len(selected_rows)),
        "selected_series_ready": selected_ready,
        "total_missing_candles": int(pd.to_numeric(status["missing_candles"]).sum()),
        "total_gap_count": int(pd.to_numeric(status["gap_count"]).sum()),
        "total_duplicate_timestamps": int(pd.to_numeric(status["duplicate_count"]).sum()),
        "total_off_grid_timestamps": int(pd.to_numeric(status["off_grid_count"]).sum()),
    }, readiness


def evaluate_suitability(
    dataset_summary: dict[str, Any],
    successful_runs: int,
    expected_runs: int,
    policy: dict[str, Any],
) -> dict[str, Any]:
    checks = {
        "overall_ready_ratio": dataset_summary["overall_ready_ratio"]
        >= float(policy["minimum_overall_ready_ratio"]),
        "all_selected_series_ready": (
            dataset_summary["selected_series_found"] == dataset_summary["selected_series"]
            and dataset_summary["selected_series_ready"] == dataset_summary["selected_series"]
        ),
        "all_benchmark_runs_successful": successful_runs == expected_runs,
        "duplicate_timestamp_limit": dataset_summary["total_duplicate_timestamps"]
        <= int(policy["maximum_total_duplicate_timestamps"]),
        "off_grid_timestamp_limit": dataset_summary["total_off_grid_timestamps"]
        <= int(policy["maximum_total_off_grid_timestamps"]),
    }

    if not policy.get("require_all_selected_series_ready", True):
        checks["all_selected_series_ready"] = True
    if not policy.get("require_all_benchmark_runs_successful", True):
        checks["all_benchmark_runs_successful"] = True

    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    suitable = not failed_checks
    return {
        "suitable_as_primary_research_venue": suitable,
        "decision": "retain_lbank" if suitable else "evaluate_secondary_venue",
        "next_venue": None if suitable else policy.get("next_venue_on_failure"),
        "checks": checks,
        "failed_checks": failed_checks,
        "profitability_used_as_venue_criterion": False,
    }


def run_benchmark(manifest_path: Path) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    data_root = Path(manifest["dataset_root"])
    status_path = data_root / "_backfill_status.csv"
    if not status_path.exists():
        raise BenchmarkError(f"Backfill status not found: {status_path}")

    status = pd.read_csv(status_path)
    minimum_rows = int(manifest["minimum_rows"])
    dataset_summary, readiness = summarize_dataset(
        status,
        manifest["series"],
        minimum_rows,
    )

    runs: list[dict[str, Any]] = []
    for series in manifest["series"]:
        symbol = series["symbol"]
        timeframe = series["timeframe"]
        try:
            frame = load_research_series(
                symbol,
                timeframe,
                data_root=data_root,
                minimum_rows=minimum_rows,
            )
        except Exception as exc:
            for strategy in manifest["strategies"]:
                for profile in manifest["execution_profiles"]:
                    runs.append({
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "strategy_id": strategy["strategy_id"],
                        "profile_id": profile["profile_id"],
                        "success": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    })
            continue

        for strategy in manifest["strategies"]:
            try:
                targets = build_target_exposures(frame, strategy)
            except Exception as exc:
                for profile in manifest["execution_profiles"]:
                    runs.append({
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "strategy_id": strategy["strategy_id"],
                        "profile_id": profile["profile_id"],
                        "success": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    })
                continue

            for profile in manifest["execution_profiles"]:
                config = BacktestConfig(
                    initial_cash=float(profile["initial_cash"]),
                    fee_bps=float(profile["fee_bps"]),
                    slippage_bps=float(profile["slippage_bps"]),
                    max_abs_exposure=float(profile["max_abs_exposure"]),
                    liquidate_at_end=bool(profile["liquidate_at_end"]),
                )
                try:
                    result = run_target_exposure_backtest(frame, targets, config)
                    risk = calculate_risk_metrics(
                        result.equity_curve,
                        timeframe,
                        initial_cash=config.initial_cash,
                    )
                    runs.append({
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "strategy_id": strategy["strategy_id"],
                        "profile_id": profile["profile_id"],
                        "success": True,
                        "error": None,
                        "first_candle_utc": frame.iloc[0]["timestamp"].isoformat(),
                        "last_candle_utc": frame.iloc[-1]["timestamp"].isoformat(),
                        **result.metrics,
                        **risk,
                    })
                except Exception as exc:
                    runs.append({
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "strategy_id": strategy["strategy_id"],
                        "profile_id": profile["profile_id"],
                        "success": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    })

    expected_runs = (
        len(manifest["series"])
        * len(manifest["strategies"])
        * len(manifest["execution_profiles"])
    )
    successful_runs = sum(bool(run["success"]) for run in runs)
    suitability = evaluate_suitability(
        dataset_summary,
        successful_runs,
        expected_runs,
        manifest["suitability_policy"],
    )

    selected_readiness = readiness.loc[
        readiness.apply(
            lambda row: (row["symbol"], row["timeframe"])
            in {(item["symbol"], item["timeframe"]) for item in manifest["series"]},
            axis=1,
        )
    ]

    return {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "experiment_id": manifest["experiment_id"],
        "venue": manifest["venue"],
        "manifest_path": manifest_path.as_posix(),
        "manifest_sha256": manifest_sha256(manifest_path),
        "dataset_summary": dataset_summary,
        "selected_readiness": selected_readiness.to_dict(orient="records"),
        "benchmark_summary": {
            "expected_runs": expected_runs,
            "successful_runs": successful_runs,
            "failed_runs": expected_runs - successful_runs,
        },
        "suitability": suitability,
        "runs": runs,
    }


def render_markdown(report: dict[str, Any]) -> str:
    dataset = report["dataset_summary"]
    benchmark = report["benchmark_summary"]
    suitability = report["suitability"]
    lines = [
        f"# {report['experiment_id']}",
        "",
        f"Generated at: {report['generated_at_utc']}",
        f"Manifest SHA-256: `{report['manifest_sha256']}`",
        "",
        "## Venue decision",
        "",
        f"- Suitable as primary research venue: **{suitability['suitable_as_primary_research_venue']}**",
        f"- Decision: `{suitability['decision']}`",
        f"- Next venue: `{suitability['next_venue']}`",
        f"- Failed checks: {', '.join(suitability['failed_checks']) or 'none'}",
        "- Strategy profitability is not used as an exchange-selection criterion.",
        "",
        "## Dataset coverage",
        "",
        f"- Total series: {dataset['total_series']}",
        f"- Research-ready series: {dataset['ready_series']}",
        f"- Overall ready ratio: {dataset['overall_ready_ratio']:.2%}",
        f"- Selected series ready: {dataset['selected_series_ready']} / {dataset['selected_series']}",
        f"- Missing candles: {dataset['total_missing_candles']}",
        f"- Duplicate timestamps: {dataset['total_duplicate_timestamps']}",
        f"- Off-grid timestamps: {dataset['total_off_grid_timestamps']}",
        "",
        "## Benchmark execution",
        "",
        f"- Expected runs: {benchmark['expected_runs']}",
        f"- Successful runs: {benchmark['successful_runs']}",
        f"- Failed runs: {benchmark['failed_runs']}",
        "",
        "| Symbol | Timeframe | Strategy | Profile | Success | Return | Max DD | Fills | Error |",
        "|---|---|---|---|---:|---:|---:|---:|---|",
    ]
    for run in report["runs"]:
        total_return = run.get("total_return")
        max_drawdown = run.get("max_drawdown")
        lines.append(
            "| {symbol} | {timeframe} | {strategy_id} | {profile_id} | {success} | {return_value} | {drawdown_value} | {fills} | {error} |".format(
                **run,
                return_value="" if total_return is None else f"{total_return:.2%}",
                drawdown_value="" if max_drawdown is None else f"{max_drawdown:.2%}",
                fills=run.get("fill_count", ""),
                error=run.get("error") or "",
            )
        )
    lines.append("")
    return "\n".join(lines)


def write_report(
    report: dict[str, Any],
    manifest_path: Path,
    output_root: Path,
    clean: bool,
) -> None:
    if clean and output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    (output_root / "_benchmark.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    (output_root / "_benchmark.md").write_text(
        render_markdown(report),
        encoding="utf-8",
    )
    pd.DataFrame(report["runs"]).to_csv(
        output_root / "_benchmark_runs.csv",
        index=False,
    )
    shutil.copy2(manifest_path, output_root / "_experiment_manifest.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the versioned LBank research benchmark and suitability gate."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--clean", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = run_benchmark(args.manifest)
    write_report(report, args.manifest, args.output_root, args.clean)
    print(json.dumps({
        "dataset_summary": report["dataset_summary"],
        "benchmark_summary": report["benchmark_summary"],
        "suitability": report["suitability"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
