"""Bounded monthly comparison using the existing ten-strategy engine and replay.

No mechanism selection, qualification or Paper mutation. Each month/cell starts
with an independent 500 USDT Spot long/flat account and closes at month end.
Previously inspected history is never presented as a pristine holdout.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re

import pandas as pd

from backtest_engine import BacktestConfig
from canonical_backtest import canonical_market_frame, run_canonical_target_exposure_backtest
import nexus_monthly_strategy_matrix_v1 as engine
from nexus_demo_archive_replay import ARCHIVE_SHA256, build_archive_dataset_fetcher
from scripts.build_nexus_bybit_replay_package import build_manifest

SCHEMA = "nexus.monthly-archive-comparison.v1"
QA_SCHEMA = "nexus.monthly-archive-numeric-replay.v1"
SHA40 = re.compile(r"^[a-f0-9]{40}$")


def months_between(start: str, end: str) -> list[pd.Timestamp]:
    first, last = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    if any(x.day != 1 or x != x.normalize() for x in (first, last)) or last <= first:
        raise ValueError("whole UTC months required")
    months = list(pd.date_range(first, last, freq="MS", inclusive="left"))
    if not 1 <= len(months) <= 12:
        raise ValueError("one bounded stage covers one to twelve months")
    return months


def verify_archive(root: Path) -> dict:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("regular extracted replay root required")
    supplied = json.loads((root / "REPLAY_DATASET_MANIFEST.json").read_text("utf-8"))
    actual = build_manifest(root)
    if supplied != actual or actual["semantic_dataset_sha256"] != ARCHIVE_SHA256:
        raise ValueError("recomputed immutable replay identity mismatch")
    return actual


def plan(source_sha: str, start: str, end: str) -> dict:
    if not SHA40.fullmatch(source_sha):
        raise ValueError("exact source SHA required")
    months = months_between(start, end)
    return {
        "schema": SCHEMA, "source_sha": source_sha,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "engine_sha256": hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest(),
        "archive_sha256": ARCHIVE_SHA256,
        "months": [x.strftime("%Y-%m") for x in months],
        "symbols": list(engine.CONTRACT["symbols"]),
        "timeframes": list(engine.CONTRACT["timeframes"]),
        "strategies": list(engine.STRATEGIES), "costs_bps_per_leg": engine.PROFILES,
        "initial_cash_usdt": 500, "warmup_bars": engine.WARMUP,
        "execution": "closed_bar_signal_next_open", "terminal_exit": "last_month_close_with_costs",
        "monthly_account_policy": "independent_reset_not_continuous_portfolio",
        "research_only": True, "independent_holdout": False,
        "exchange_lot_size_validated": False, "minimum_trade_count_gate": None,
        "automatic_paper_admission": False, "live_trading_authority": False,
    }


def month_dataset(fetcher, month: pd.Timestamp, symbol: str, timeframe: str):
    spec = engine.TIMEFRAMES[timeframe]
    step = spec["step_ms"]
    first = int(month.timestamp() * 1000)
    end = int((month + pd.offsets.MonthBegin(1)).timestamp() * 1000)
    lo, hi = first - engine.WARMUP * step, end - step
    dataset = fetcher(canonical_symbol=symbol[:-4]+"/USDT", source_symbol=symbol,
                      interval=spec["interval"], now_ms=end,
                      start_time_ms=lo, end_time_ms=hi, limit=(hi-lo)//step+1)
    artifact, frame = canonical_market_frame(dataset, registry_path=engine._registry_path())
    if [x["open_time_ms"] for x in artifact["rows"]] != list(range(lo, end, step)):
        raise ValueError("full month and warmup coverage mismatch")
    frame["volume"] = [float(x["volume"]) for x in artifact["rows"]]
    return dataset, frame


def cell_result(dataset, frame, month: str, symbol: str, timeframe: str,
                strategy: str, profile: str) -> dict:
    fee, slip = engine.PROFILES[profile]
    result = run_canonical_target_exposure_backtest(
        dataset, engine.targets(frame, strategy),
        BacktestConfig(initial_cash=500, fee_bps=fee, slippage_bps=slip),
        registry_path=engine._registry_path(), start=engine.WARMUP-1)
    metrics = engine.summarize(result)
    trades = metrics["completed_trades"]
    return {"month": month, "symbol": symbol, "timeframe": timeframe,
            "strategy": strategy, "profile": profile,
            "dataset_binding_sha256": dataset["binding_sha256"],
            "trade_count": trades, "sum_net_pnl_usdt": metrics["net_pnl"],
            "mean_net_pnl_per_trade_usdt": metrics["net_pnl"]/trades if trades else None,
            "max_drawdown": metrics["max_drawdown"],
            "forced_terminal_exits": metrics["forced_terminal_exits"],
            "bars_in_month": len(frame)-engine.WARMUP,
            "research_only": True, "automatic_paper_admission": False,
            "live_trading_authority": False}


def sealed(value: dict) -> dict:
    return {**value, "digest": engine.digest(value)}


def read_sealed(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError("regular numerical evidence required")
    obj = json.loads(path.read_text("utf-8"))
    core = {k: v for k, v in obj.items() if k != "digest"}
    if obj.get("digest") != engine.digest(core):
        raise ValueError("numerical evidence digest mismatch")
    return obj


@contextmanager
def stage_lock(root: Path):
    if root.is_symlink():
        raise ValueError("linked output root refused")
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".stage-lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError("monthly stage already active or requires stale-lock review") from exc
    try:
        os.close(fd)
        yield
    finally:
        lock.unlink()


def run_stage(archive_root: Path, output: Path, source_sha: str, start: str, end: str,
              producer_report: Path | None = None) -> dict:
    contract = plan(source_sha, start, end)
    # Normalize tuples before comparing a resumed JSON plan.
    contract = json.loads(json.dumps(contract))
    with stage_lock(output):
        verify_archive(archive_root)
        freeze = output / "plan.json"
        if freeze.exists() and read_sealed(freeze) != sealed(contract):
            raise ValueError("checkpoint belongs to a different source or experiment")
        engine.write_json(freeze, sealed(contract))
        fetcher = build_archive_dataset_fetcher(archive_root)
        cells = []
        for month in months_between(start, end):
            for symbol in contract["symbols"]:
                for timeframe in contract["timeframes"]:
                    dataset, frame = month_dataset(fetcher, month, symbol, timeframe)
                    for strategy in contract["strategies"]:
                        for profile in contract["costs_bps_per_leg"]:
                            name = f"{month:%Y-%m}-{symbol}-{timeframe}-{strategy}-{profile}"
                            checkpoint = output / (name+".json")
                            # QA recomputes every cell; it never consumes producer checkpoints.
                            if checkpoint.exists() and producer_report is None:
                                item = read_sealed(checkpoint)
                                if item["plan_digest"] != engine.digest(contract):
                                    raise ValueError("cell checkpoint plan mismatch")
                                cell = item["cell"]
                                expected = (month.strftime("%Y-%m"), symbol, timeframe, strategy, profile,
                                            dataset["binding_sha256"])
                                if tuple(cell[k] for k in ("month", "symbol", "timeframe", "strategy",
                                                           "profile", "dataset_binding_sha256")) != expected:
                                    raise ValueError("cell checkpoint identity mismatch")
                            else:
                                cell = cell_result(dataset, frame, month.strftime("%Y-%m"), symbol,
                                                   timeframe, strategy, profile)
                                engine.write_json(checkpoint, sealed({"plan_digest": engine.digest(contract),
                                                                     "cell": cell}))
                            cells.append(cell)
                            engine.write_json(output / "progress.json", {"completed": len(cells),
                                               "expected": len(contract["months"])*len(contract["symbols"])*
                                                   len(contract["timeframes"])*len(contract["strategies"])*
                                                   len(contract["costs_bps_per_leg"]),
                                               "research_only": True, "live_trading_authority": False})
        report = sealed({"schema": SCHEMA, "contract": contract, "cells": cells,
                         "status": "HISTORICAL_COMPARISON_COMPLETE",
                         "automatic_paper_admission": False, "live_trading_authority": False})
        if producer_report is not None:
            original = read_sealed(producer_report)
            if original != report:
                raise ValueError("independent process numeric replay differs from producer")
            evidence = sealed({"schema": QA_SCHEMA, "producer_report_digest": original["digest"],
                               "source_sha": source_sha, "archive_sha256": ARCHIVE_SHA256,
                               "verified_cells": len(cells), "status": "NUMERIC_REPLAY_MATCH",
                               "strategy_qualification": False, "automatic_paper_admission": False,
                               "live_trading_authority": False})
            engine.write_json(output / "qa-evidence.json", evidence)
        engine.write_json(output / "report.json", report)
        pd.DataFrame(cells).to_csv(output / "monthly-table.csv", index=False)
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end-exclusive", required=True)
    parser.add_argument("--verify-producer-report", type=Path)
    args = parser.parse_args()
    report = run_stage(args.archive_root, args.output, args.source_sha, args.start,
                       args.end_exclusive, args.verify_producer_report)
    print(json.dumps({"status": report["status"], "cells": len(report["cells"]),
                      "report_digest": report["digest"], "live_trading_authority": False}), flush=True)


if __name__ == "__main__":
    main()
