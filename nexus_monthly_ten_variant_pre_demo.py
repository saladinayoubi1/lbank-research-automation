"""Ten pre-registered variants across every verified full-month four-pair/timeframe cell.

An additional research catalog, not ten distinct algorithm families. This
reuses the exact separately verified 31-day Bybit monthly evidence, never
selects variants on locked holdout and cannot place/promote Paper orders.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Mapping

import nexus_monthly_four_pair_pre_demo as monthly
import nexus_multitimeframe_strategy_discovery as sim
from nexus_multipair_trusted_surface import SYMBOLS, TIMEFRAMES

VARIANTS: tuple[tuple[str, str, dict[str, Any]], ...] = (
    ("momentum_12_0020", "momentum", {"lookback": 12, "entry_threshold": 0.002}),
    ("momentum_24_0030", "momentum", {"lookback": 24, "entry_threshold": 0.003}),
    ("momentum_48_0050", "momentum", {"lookback": 48, "entry_threshold": 0.005}),
    ("breakout_20_10", "trend_breakout", {"entry_lookback": 20, "exit_lookback": 10}),
    ("breakout_40_12", "trend_breakout", {"entry_lookback": 40, "exit_lookback": 12}),
    ("breakout_55_20", "trend_breakout", {"entry_lookback": 55, "exit_lookback": 20}),
    ("mean_reversion_20_m1", "mean_reversion", {"lookback": 20, "entry_z": -1.0, "exit_z": 0.0}),
    ("mean_reversion_20_m15", "mean_reversion", {"lookback": 20, "entry_z": -1.5, "exit_z": 0.0}),
    ("mean_reversion_40_m15", "mean_reversion", {"lookback": 40, "entry_z": -1.5, "exit_z": 0.0}),
    ("mean_reversion_40_m2", "mean_reversion", {"lookback": 40, "entry_z": -2.0, "exit_z": 0.0}),
)
CSV_FIELDS = (
    "symbol", "timeframe", "strategy_id", "family", "config_sha256", "first_utc",
    "last_utc", "bars", "coverage_days", "research_initial_usdt",
    "net_return_pct", "net_pnl_usdt", "max_drawdown_pct", "fills",
    "oos_return_pct", "oos_max_drawdown_pct", "oos_fills", "oos_sharpe",
    "stress_oos_return_pct", "stress_oos_max_drawdown_pct", "stress_oos_fills",
    "full_month_proven", "holdout_not_used_for_selection", "qualification",
    "demo_promoted", "live_enabled", "frame_sha256", "source_sha",
)


def _verify_base(base: Mapping[str, Any], source_sha: str) -> None:
    if (
        base.get("contract") != "nexus.bybit-monthly-pre-demo-table.v1"
        or base.get("source_sha") != source_sha
        or base.get("period") != monthly.MONTH
        or base.get("origin") != "official_public_bybit_spot_trade_archive_aggregated"
        or base.get("research_only") is not True
        or base.get("automatic_paper_promotion") is not False
        or base.get("live_trading_authority") is not False
        or base.get("result_sha256") != monthly._digest(
            {k: v for k, v in base.items() if k != "result_sha256"}
        )
    ):
        raise monthly.MonthlyResearchError("prior physical monthly research receipt not source-verified")
    sources = base.get("archive_sources", [])
    if (
        not isinstance(sources, list) or len(sources) != 4
        or {s.get("symbol") for s in sources if isinstance(s, Mapping)} != set(SYMBOLS)
        or base.get("source_manifest_sha256") != monthly._digest(sources)
    ):
        raise monthly.MonthlyResearchError("monthly official source provenance not exact")


def calculate_variants(
    frames: Mapping[tuple[str, str], Any],
    *,
    source_sha: str,
    base: Mapping[str, Any],
) -> dict[str, Any]:
    _verify_base(base, source_sha)
    if set(frames) != {(s, tf) for s in SYMBOLS for tf in TIMEFRAMES}:
        raise monthly.MonthlyResearchError("not exactly twelve certified archive series")
    if len(VARIANTS) != 10 or len({v[0] for v in VARIANTS}) != 10:
        raise monthly.MonthlyResearchError("preregistered variant catalog changed")
    source_frames = {
        (row["symbol"], row["timeframe"]): row["frame_sha256"]
        for row in base.get("rows", [])
        if isinstance(row, dict)
    }
    if len(base.get("rows", [])) != 36 or len(source_frames) != 12:
        raise monthly.MonthlyResearchError("monthly source frame receipts incomplete")
    rows: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        for tf in TIMEFRAMES:
            frame = frames[(symbol, tf)]
            if len(frame) != monthly.EXPECTED_ROWS[tf]:
                raise monthly.MonthlyResearchError("variant month length mismatch")
            split = int(len(frame) * 0.7)
            expected_frame = next(row for row in base["rows"]
                                  if row["symbol"] == symbol and row["timeframe"] == tf)
            if (
                expected_frame["bars"] != len(frame)
                or expected_frame["monthly_coverage"] is not True
                or source_frames[(symbol, tf)] != expected_frame["frame_sha256"]
            ):
                raise monthly.MonthlyResearchError("variant frame differs from base monthly report")
            # Base report was produced by monthly.calculate on these exact immutable frames;
            # additionally rederive the full frame digest here to reject modified archive state.
            actual_digest = monthly._digest([
                [int(r.timestamp.value // 1_000_000), str(r.open), str(r.high),
                 str(r.low), str(r.close), str(r.volume)]
                for r in frame.itertuples(index=False)
            ])
            if actual_digest != expected_frame["frame_sha256"]:
                raise monthly.MonthlyResearchError("variant archive frame digest changed")
            for strategy_id, family, params in VARIANTS:
                # Variant definitions are frozen constants, not a holdout search.
                target = sim.generate_targets(frame, family, params)
                full = sim._simulate(frame, target, 0, len(frame), monthly.CONSERVATIVE,
                                     bars_per_year=sim.TIMEFRAME_BARS_PER_YEAR[tf])
                oos = sim._simulate(frame, target, split, len(frame), monthly.CONSERVATIVE,
                                    bars_per_year=sim.TIMEFRAME_BARS_PER_YEAR[tf])
                stress = sim._simulate(frame, target, split, len(frame), monthly.STRESS,
                                       bars_per_year=sim.TIMEFRAME_BARS_PER_YEAR[tf])
                rows.append({
                    "symbol": symbol, "timeframe": tf, "strategy_id": strategy_id,
                    "family": family, "config_sha256": monthly._digest(params),
                    "first_utc": frame["timestamp"].iloc[0].isoformat(),
                    "last_utc": frame["timestamp"].iloc[-1].isoformat(),
                    "bars": len(frame), "coverage_days": 31.0,
                    "research_initial_usdt": 10_000,
                    "net_return_pct": round(full["total_return"] * 100, 4),
                    "net_pnl_usdt": round(full["total_return"] * 10_000, 4),
                    "max_drawdown_pct": round(full["max_drawdown"] * 100, 4),
                    "fills": full["fill_count"],
                    "oos_return_pct": round(oos["total_return"] * 100, 4),
                    "oos_max_drawdown_pct": round(oos["max_drawdown"] * 100, 4),
                    "oos_fills": oos["fill_count"], "oos_sharpe": round(oos["sharpe"], 5),
                    "stress_oos_return_pct": round(stress["total_return"] * 100, 4),
                    "stress_oos_max_drawdown_pct": round(stress["max_drawdown"] * 100, 4),
                    "stress_oos_fills": stress["fill_count"],
                    "full_month_proven": True, "holdout_not_used_for_selection": True,
                    "qualification": "RESEARCH_ONLY_REQUIRES_INDEPENDENT_REQUALIFICATION",
                    "demo_promoted": False, "live_enabled": False,
                    "frame_sha256": actual_digest, "source_sha": source_sha,
                })
    if len(rows) != 120 or any(row["demo_promoted"] or row["live_enabled"] for row in rows):
        raise monthly.MonthlyResearchError("variant catalog incomplete or unsafe")
    return {
        "contract": "nexus.bybit-ten-variant-full-month-research-only.v1",
        "source_sha": source_sha, "month": monthly.MONTH,
        "pre_registered_variants": [{"id": v[0], "family": v[1], "params": v[2]}
                                    for v in VARIANTS],
        "archive_manifest_sha256": base["source_manifest_sha256"],
        "base_report_sha256": base["result_sha256"],
        "strategy_selection_performed": False,
        "independent_runtime_qualification": False,
        "research_only": True, "demo_promotions": 0, "live_trading_authority": False,
        "rows": rows,
    }


def run(*, source_sha: str, state: Path, base_report: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise monthly.MonthlyResearchError("never overwrite monthly variants output")
    if base_report.is_symlink() or not base_report.is_file():
        raise monthly.MonthlyResearchError("base verified monthly report absent or linked")
    base = json.loads(base_report.read_text(encoding="utf-8"))
    _verify_base(base, source_sha)
    frames = monthly._load_full_month(state)
    result = calculate_variants(frames, source_sha=source_sha, base=base)
    result["result_sha256"] = monthly._digest(result)
    output.mkdir(parents=True, exist_ok=False)
    (output / "ten-variant-report.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    with (output / "ten-variant-table.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(result["rows"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--base-report", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    output = run(source_sha=args.source_sha, state=args.state_root,
                 base_report=args.base_report, output=args.output_root)
    print(json.dumps({"contract": output["contract"], "rows": len(output["rows"]),
                      "digest": output["result_sha256"], "demo_promotions": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
