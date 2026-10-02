"""A7 range-failure reversal research on independently recent official Bybit Spot data.

This module evaluates the preregistered A7 hypothesis from #1985:
observed 15m range failure -> reversal, confirmed by completed 1h/4h context
and multi-horizon volatility. Execution is Spot long/cash only at the NEXT
15m open with explicit ATR stop/target/time exit. No martingale, no trade-count
cap, no Paper promotion, no derivatives execution, and no Live authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

import bybit_spot_archive_audit as archive_audit
import bybit_spot_archive_collector as collector
import bybit_spot_backfill as backfill
import nexus_composite_strategy_research as composite
import nexus_multipair_recent_archive_runtime_snapshot as recent
from nexus_multipair_trusted_surface import SYMBOLS, TIMEFRAMES

SCHEMA = "nexus.a7-range-failure-reversal-research.v1"
MECHANISM = "a7_range_failure_reversal"
ENTRY_TIMEFRAME = "minute15"
CONTEXT_TIMEFRAMES = ("hour1", "hour4")
PROFILES = (
    ("conservative", composite.ENTRY_FEE_BPS, composite.ENTRY_SLIP_BPS),
    ("stress", composite.STRESS_FEE_BPS, composite.STRESS_SLIP_BPS),
)
RISK_VARIANT = 0
SHA40 = re.compile(r"^[0-9a-f]{40}$")
MAX_FRAME_BYTES = 250 * 1024 * 1024


class A7ResearchError(ValueError):
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


def _read_json(path: Path, max_bytes: int = 8_000_000) -> Any:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > max_bytes:
        raise A7ResearchError(f"missing or unsafe JSON source: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise A7ResearchError(f"unreadable JSON source: {path}") from exc


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


def _load_full_frame(
    state_root: Path,
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    path = (
        state_root.resolve()
        / "bybit_market"
        / collector.canonical_symbol(symbol)
        / f"{timeframe}.parquet"
    )
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FRAME_BYTES:
        raise A7ResearchError(f"missing or unsafe A7 frame: {symbol}/{timeframe}")
    frame = pd.read_parquet(path).copy()
    if frame.columns.tolist() != collector.CANONICAL_COLUMNS:
        raise A7ResearchError(f"unexpected A7 frame schema: {symbol}/{timeframe}")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    expected = collector.expected_index(start_date, end_date, timeframe)
    actual = pd.DatetimeIndex(frame["timestamp"]).drop_duplicates().sort_values()
    missing = expected.difference(actual)
    unexpected = actual.difference(expected)
    canonical = collector.canonical_symbol(symbol)
    if (
        len(frame) != len(expected)
        or len(actual) != len(expected)
        or not missing.empty
        or not unexpected.empty
        or set(frame["symbol"].astype(str)) != {canonical}
        or set(frame["timeframe"].astype(str)) != {timeframe}
    ):
        raise A7ResearchError(
            f"A7 frame grid mismatch: {symbol}/{timeframe}; "
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
        raise A7ResearchError(f"A7 OHLCV integrity failed: {symbol}/{timeframe}")
    frame["symbol"] = symbol
    frame["timeframe"] = timeframe
    return frame


def load_verified_recent_surface(
    state_root: Path,
    snapshot_root: Path,
    *,
    source_sha: str,
    now_ms: int,
) -> tuple[dict[tuple[str, str], pd.DataFrame], dict[str, Any]]:
    if not SHA40.fullmatch(source_sha):
        raise A7ResearchError("source_sha must be an exact lower-case git SHA")
    manifest = _read_json(snapshot_root.resolve() / "snapshot-manifest.json")
    if not isinstance(manifest, dict):
        raise A7ResearchError("recent snapshot manifest is invalid")
    verification = recent.verify_recent_archive_runtime_snapshot(
        snapshot_root.resolve(),
        manifest,
        source_sha=source_sha,
        now_ms=now_ms,
    )
    if verification.get("decision") != "pass":
        raise A7ResearchError(f"recent official snapshot rejected: {verification}")

    state = state_root.resolve()
    report = _read_json(state / backfill.REPORT_NAME)
    plan = _read_json(state / backfill.PLAN_NAME)
    if not isinstance(report, dict) or not isinstance(plan, dict):
        raise A7ResearchError("recent raw source report or plan is invalid")
    summary = report.get("summary")
    config = report.get("configuration")
    if (
        not isinstance(summary, Mapping)
        or not isinstance(config, Mapping)
        or config.get("start_date") != manifest.get("source_window_start")
        or config.get("end_date") != manifest.get("source_window_end")
        or config.get("symbols") != list(SYMBOLS)
        or summary.get("remaining_units") != 0
        or summary.get("run_failures") != 0
        or summary.get("backfill_complete") is not True
        or summary.get("current_dataset_integrity_ok") is not True
        or report.get("run_failures") != []
    ):
        raise A7ResearchError("recent raw source state is not complete")
    normalized_plan = recent._normalize_plan(
        plan,
        start_date=str(manifest["source_window_start"]),
        end_date=str(manifest["source_window_end"]),
    )
    if normalized_plan != manifest.get("archive_plan_units"):
        raise A7ResearchError("recent raw source plan differs from signed snapshot")
    source_rows, source_digest = recent._source_evidence(state, normalized_plan)
    if (
        source_digest != manifest.get("archive_source_manifest_digest")
        or source_rows != manifest.get("archive_sources")
    ):
        raise A7ResearchError("recent raw source provenance differs from signed snapshot")

    frames: dict[tuple[str, str], pd.DataFrame] = {}
    frame_digests: dict[str, str] = {}
    timestamp_refs: dict[str, pd.DatetimeIndex] = {}
    for timeframe in TIMEFRAMES:
        for symbol in SYMBOLS:
            frame = _load_full_frame(
                state,
                symbol,
                timeframe,
                str(manifest["source_window_start"]),
                str(manifest["source_window_end"]),
            )
            idx = pd.DatetimeIndex(frame["timestamp"])
            reference = timestamp_refs.setdefault(timeframe, idx)
            if len(reference) != len(idx) or not reference.difference(idx).empty or not idx.difference(reference).empty:
                raise A7ResearchError(f"four-symbol A7 timestamps are not aligned: {timeframe}")
            frames[(symbol, timeframe)] = frame
            frame_digests[f"{symbol}/{timeframe}"] = _frame_digest(frame)

    dataset_digest = digest(
        {
            "snapshot_digest": manifest["snapshot_digest"],
            "source_manifest_digest": source_digest,
            "full_frames": frame_digests,
        }
    )
    proof = {
        "snapshot_digest": manifest["snapshot_digest"],
        "source_manifest_digest": source_digest,
        "dataset_digest": dataset_digest,
        "source_window_start": manifest["source_window_start"],
        "source_window_end": manifest["source_window_end"],
        "data_as_of_ms": manifest["data_as_of_ms"],
        "symbols": list(SYMBOLS),
        "timeframes": list(TIMEFRAMES),
        "research_only": True,
        "paper_only": True,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    return frames, proof


def build_a7_features(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    f = composite.build_features(frames)
    close = f["close"].astype(float)
    ret = close.pct_change()
    short_rv = ret.shift(1).rolling(16, min_periods=16).std()
    long_rv = ret.shift(1).rolling(192, min_periods=96).std()
    f["a7_rv15_ratio"] = short_rv / long_rv.replace(0.0, np.nan)

    q = frames["hour4"].reset_index(drop=True)
    q_range = (q["high"].astype(float) - q["low"].astype(float)) / q["close"].astype(float)
    q_baseline = q_range.shift(1).rolling(30, min_periods=20).median()
    h4 = composite._closed_asof(
        q,
        14_400_000,
        f,
        {
            "vol_ratio": q_range / q_baseline.replace(0.0, np.nan),
        },
        "a7_h4_",
    )
    f["a7_h4_vol_ratio"] = h4["a7_h4_vol_ratio"].to_numpy()
    return f


def signal_for_a7(frame: pd.DataFrame) -> np.ndarray:
    required = [
        "h4_range",
        "h1_vol_ok",
        "prior_lo",
        "rel_vol",
        "atr",
        "a7_rv15_ratio",
        "a7_h4_vol_ratio",
    ]
    valid = frame[required].notna().all(axis=1) & (frame["atr"] > 0)
    # Preregistered causal A7:
    # 1) completed 4h range regime;
    # 2) completed 1h volatility is not extreme;
    # 3) pre-decision 15m realized volatility is active but not explosive;
    # 4) completed 4h realized range is not an extreme shock;
    # 5) THIS closed 15m candle trades below the prior observed range and
    #    closes back above it with positive body and observed relative volume;
    # 6) execution may occur only at the NEXT 15m open in backtest().
    signal = (
        (frame["h4_range"] == 1)
        & (frame["h1_vol_ok"] == 1)
        & (frame["a7_rv15_ratio"] >= 0.75)
        & (frame["a7_rv15_ratio"] <= 1.80)
        & (frame["a7_h4_vol_ratio"] <= 1.75)
        & (frame["low"] < frame["prior_lo"])
        & (frame["close"] > frame["prior_lo"])
        & (frame["close"] > frame["open"])
        & (frame["rel_vol"] > 1.0)
    )
    return (valid & signal).fillna(False).to_numpy(dtype=bool)


def evaluate(
    state_root: Path,
    snapshot_root: Path,
    *,
    source_sha: str,
    now_ms: int,
) -> dict[str, Any]:
    frames, source = load_verified_recent_surface(
        state_root,
        snapshot_root,
        source_sha=source_sha,
        now_ms=now_ms,
    )
    config = {
        "mechanism": MECHANISM,
        "entry_model": "closed_4h_1h_15m_next_open",
        "signal": "15m_failed_prior_18_bar_low_reclaim",
        "regime": "completed_4h_range_and_completed_1h_vol_ok",
        "multi_horizon_volatility": {
            "15m_predecision_realized_vol_ratio": [0.75, 1.80],
            "4h_completed_range_vol_ratio_max": 1.75,
        },
        "relative_volume_min": 1.0,
        "stop_atr": 1.5,
        "target_multiple_of_stop": 2.0,
        "time_exit_bars_15m": 64,
        "position_budget_fraction": 0.10,
        "stop_risk_fraction": 0.001,
        "martingale": False,
        "trade_count_limit": None,
    }
    mechanism_fingerprint = digest(
        {
            "schema": SCHEMA,
            "config": config,
            "dataset_digest": source["dataset_digest"],
        }
    )

    rows: list[dict[str, Any]] = []
    cells: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        own = {tf: frames[(symbol, tf)] for tf in TIMEFRAMES}
        feature = build_a7_features(own)
        signals = signal_for_a7(feature)
        for profile, fee, slip in PROFILES:
            result = composite.backtest(
                feature.reset_index(drop=True),
                signals,
                fee_bps=fee,
                slip_bps=slip,
                risk_variant=RISK_VARIANT,
            )
            rows.append(
                {
                    "symbol": symbol,
                    "entry_timeframe": ENTRY_TIMEFRAME,
                    "context_timeframes": list(CONTEXT_TIMEFRAMES),
                    "mechanism": MECHANISM,
                    "mechanism_fingerprint": mechanism_fingerprint,
                    "profile": profile,
                    "bars": len(feature),
                    "signals": int(signals.sum()),
                    "first_decision_utc": pd.Timestamp(feature["decision_at"].iloc[0]).isoformat(),
                    "last_decision_utc": pd.Timestamp(feature["decision_at"].iloc[-1]).isoformat(),
                    **result,
                }
            )

        cons = next(row for row in rows if row["symbol"] == symbol and row["profile"] == "conservative")
        stress = next(row for row in rows if row["symbol"] == symbol and row["profile"] == "stress")
        if stress["closed_round_trips"] == 0:
            verdict = "REJECTED_NO_CLOSED_RECENT_TRADES"
        elif stress["net_return_pct"] <= 0 or stress["profit_factor"] is None or stress["profit_factor"] <= 1.0:
            verdict = "REJECTED_RECENT_STRESS_EDGE_NOT_POSITIVE"
        else:
            verdict = "REVIEW_REQUIRED_POSITIVE_RECENT_STRESS_EVIDENCE"
        cells.append(
            {
                "symbol": symbol,
                "timeframe": ENTRY_TIMEFRAME,
                "role": "entry",
                "verdict": verdict,
                "conservative_net_return_pct": cons["net_return_pct"],
                "stress_net_return_pct": stress["net_return_pct"],
                "stress_closed_round_trips": stress["closed_round_trips"],
                "stress_profit_factor": stress["profit_factor"],
                "stress_max_drawdown_pct": stress["max_drawdown_pct"],
            }
        )
        for timeframe in CONTEXT_TIMEFRAMES:
            cells.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "role": "context_only",
                    "verdict": "CONTEXT_ONLY_NOT_INDEPENDENT_ENTRY_CELL",
                }
            )

    entry_cells = [cell for cell in cells if cell["role"] == "entry"]
    positive = sum(cell["verdict"].startswith("REVIEW_REQUIRED") for cell in entry_cells)
    if positive == 0:
        conclusion = "REJECTED_NO_POSITIVE_RECENT_STRESS_CELL"
    else:
        conclusion = "OWNER_REVIEW_REQUIRED_NO_AUTOMATIC_PROMOTION"

    core = {
        "schema": SCHEMA,
        "source_sha": source_sha,
        "mechanism": MECHANISM,
        "mechanism_fingerprint": mechanism_fingerprint,
        "preregistration": config,
        "selection_basis": "A7_preregistered_in_issue_1985_not_selected_by_recent_returns",
        "source": source,
        "evaluation_window": "independently_recent_official_bybit_archive_surface",
        "historical_july_previously_inspected": True,
        "recent_window_used_for_selection": False,
        "independent_future_data_required_for_any_paper_promotion": True,
        "rows": rows,
        "owner_review_cells": cells,
        "positive_recent_stress_entry_cells": positive,
        "conclusion": conclusion,
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
    return {**core, "report_sha256": digest(core)}


def run(
    state_root: Path,
    snapshot_root: Path,
    output_root: Path,
    *,
    source_sha: str,
    now_ms: int,
) -> dict[str, Any]:
    report = evaluate(
        state_root,
        snapshot_root,
        source_sha=source_sha,
        now_ms=now_ms,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "a7-range-failure-reversal-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--now-ms", type=int, required=True)
    args = parser.parse_args()
    report = run(
        args.state_root,
        args.snapshot_root,
        args.output_root,
        source_sha=args.source_sha,
        now_ms=args.now_ms,
    )
    print(
        json.dumps(
            {
                "decision": "pass",
                "conclusion": report["conclusion"],
                "positive_recent_stress_entry_cells": report["positive_recent_stress_entry_cells"],
                "dataset_digest": report["source"]["dataset_digest"],
                "mechanism_fingerprint": report["mechanism_fingerprint"],
                "research_only": report["research_only"],
                "auto_promotion": report["automatic_strategy_promotion"],
                "live_authority": report["live_trading_authority"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
