"""Full-July, four-pair, truly composite historical Bybit Research matrix.

Consumes ONLY the exact full-month official Bybit Parquet state that the
already-approved May–July acquisition verified. The separate 500-bar Discovery
snapshot MUST NOT be substituted for this 2,976-bar 15m month.

All five existing compiled entry mechanisms get independent per-symbol 15m
next-open backtests with causal closed 1h/4h contexts. The cross-pair mechanism
has an explicit reviewed exploratory peer topology (BTC<-ETH; others<-BTC):
NOT synthetic order flow, L2, multi-leg execution or portfolio PnL.

The historical month is already inspected. The 20% diagnostic final partition
is NOT pristine OOS; this artifact NEVER grants Demo/Live admission.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

import nexus_composite_strategy_research as composite
import nexus_monthly_four_pair_pre_demo as month
import nexus_multipair_archive_snapshot as archive
from nexus_multipair_trusted_surface import SYMBOLS, TIMEFRAMES

SCHEMA = "nexus.fourpair-monthly-causal-composite-research.v1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")
PEER_TOPOLOGY = {
    "BTCUSDT": "ETHUSDT", "ETHUSDT": "BTCUSDT",
    "SOLUSDT": "BTCUSDT", "XRPUSDT": "BTCUSDT",
}
MECHANISMS = composite.MECHANISMS
PARTS = ("train", "validation", "historically_inspected_test")
PROFILES = ("conservative", "stress")
# TWO risk calibrations are ROBUSTNESS variants, not new causal mechanisms.
RISK_VARIANTS = (0, 1)
CSV_FIELDS = (
    "symbol", "entry_timeframe", "higher_contexts", "mechanism", "peer",
    "risk_variant", "config_fingerprint", "part", "profile", "bars",
    "first_closed_utc", "last_closed_utc", "net_return_pct", "net_pnl_usdt",
    "max_drawdown_pct", "closed_round_trips", "win_rate_pct", "profit_factor",
    "profit_factor_status", "turnover_usdt", "exposure_bar_ratio",
    "halted_on_drawdown", "fee_bps", "slippage_bps", "trade_count_limit",
    "concurrent_risk_model", "qualification", "demo_promoted", "live_enabled",
)


class FourPairCompositeResearchError(RuntimeError):
    pass


def _safe_monthly_report(path: Path, source_sha: str, state: Path) -> tuple[dict[str, Any], dict[tuple[str, str], str]]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
        raise FourPairCompositeResearchError("signed monthly input report missing or unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError, UnicodeError) as exc:
        raise FourPairCompositeResearchError("signed full-month report unreadable") from exc
    if not isinstance(value, dict):
        raise FourPairCompositeResearchError("monthly report must be an object")
    core = {k: v for k, v in value.items() if k != "result_sha256"}
    if (
        not _SHA40.fullmatch(source_sha)
        or value.get("source_sha") != source_sha
        or value.get("contract") != "nexus.bybit-monthly-pre-demo-table.v1"
        or value.get("period") != month.MONTH
        or value.get("origin") != "official_public_bybit_spot_trade_archive_aggregated"
        or value.get("result_sha256") != month._digest(core)
        or value.get("research_only") is not True
        or value.get("automatic_paper_promotion") is not False
        or value.get("live_trading_authority") is not False
        or not _SHA64.fullmatch(str(value.get("verified_three_month_source_manifest_sha256", "")))
    ):
        raise FourPairCompositeResearchError("full-month signed report provenance or authority rejected")
    # Bind to the original 12 official May–July source archives, not just a
    # stand-alone report containing plausible-looking symbol labels.
    _, parent_digest = archive._source_evidence(state)
    if value["verified_three_month_source_manifest_sha256"] != parent_digest:
        raise FourPairCompositeResearchError("full-month original verified three-month source mismatch")
    sources = value.get("archive_sources")
    if (
        not isinstance(sources, list) or len(sources) != len(SYMBOLS)
        or value.get("source_manifest_sha256") != month._digest(sources)
        or {s.get("symbol") for s in sources if isinstance(s, dict)} != set(SYMBOLS)
        or any(
            not isinstance(s, dict)
            or s.get("url") != month.backfill.archive_url(
                str(s.get("symbol")), f"{s.get('symbol')}-{month.MONTH}.csv.gz"
            )
            or not _SHA64.fullmatch(str(s.get("sha256", "")))
            or s.get("http_status") != 200
            for s in sources
        )
    ):
        raise FourPairCompositeResearchError("full-month four official July sources rejected")
    rows = value.get("rows")
    expected = {(s, tf, family) for s in SYMBOLS for tf in TIMEFRAMES for family in month.FAMILIES}
    if (
        not isinstance(rows, list) or len(rows) != 36
        or {(x.get("symbol"), x.get("timeframe"), x.get("family"))
            for x in rows if isinstance(x, dict)} != expected
        or any(
            not isinstance(x, dict)
            or x.get("source_sha") != source_sha
            or x.get("monthly_coverage") is not True
            or x.get("bars") != month.EXPECTED_ROWS.get(x.get("timeframe"))
            or x.get("qualification") != "RESEARCH_ONLY_REQUIRES_INDEPENDENT_REQUALIFICATION"
            or x.get("demo_promoted") is not False or x.get("live_enabled") is not False
            or not _SHA64.fullmatch(str(x.get("frame_sha256", "")))
            for x in rows
        )
    ):
        raise FourPairCompositeResearchError("full-month 36 baseline rows are incomplete or unsafe")
    digests: dict[tuple[str, str], str] = {}
    for row in rows:
        key = row["symbol"], row["timeframe"]
        existing = digests.setdefault(key, row["frame_sha256"])
        if existing != row["frame_sha256"]:
            raise FourPairCompositeResearchError("the same monthly candles have conflicting frame hashes")
    return value, digests


def _frame_digest(frame: Any) -> str:
    return month._digest([
        [int(row.timestamp.value // 1_000_000),
         str(row.open), str(row.high), str(row.low), str(row.close), str(row.volume)]
        for row in frame.itertuples(index=False)
    ])


def calculate(
    frames: dict[tuple[str, str], Any], baseline: dict[str, Any],
    frame_digests: dict[tuple[str, str], str], *, source_sha: str,
) -> dict[str, Any]:
    if (
        set(frames) != {(s, t) for s in SYMBOLS for t in TIMEFRAMES}
        or set(frame_digests) != set(frames)
        or set(PEER_TOPOLOGY) != set(SYMBOLS)
        or set(MECHANISMS) != set(composite.MECHANISMS)
        or composite.MIN_BARS_15M > month.EXPECTED_ROWS["minute15"]
    ):
        raise FourPairCompositeResearchError("reviewed complete 4x3 monthly research surface changed")
    for key, frame in frames.items():
        if len(frame) != month.EXPECTED_ROWS[key[1]] or _frame_digest(frame) != frame_digests[key]:
            raise FourPairCompositeResearchError("official exact 31-day full-month frame digest mismatch")
    # Never pool isolated 10,000-USDT diagnostic cash into the owner's 500.
    rows: list[dict[str, Any]] = []
    for mechanism in MECHANISMS:
        for symbol in SYMBOLS:
            peer = PEER_TOPOLOGY[symbol] if mechanism == "cross_pair_relative_reclaim" else None
            feature_input = {tf: frames[(symbol, tf)] for tf in TIMEFRAMES}
            feature_frame = composite.build_features(
                feature_input,
                peer_15m=(frames[(peer, "minute15")] if peer else None),
            )
            if (
                len(feature_frame) != month.EXPECTED_ROWS["minute15"]
                or str(feature_frame["decision_at"].iloc[0]) != str(
                    frames[(symbol, "minute15")]["timestamp"].iloc[0] + month.pd.Timedelta(minutes=15)
                )
            ):
                raise FourPairCompositeResearchError("causal close-time or full-month feature coverage invalid")
            n = len(feature_frame)
            lo1, lo2 = int(n * composite.TRAIN_FRAC), int(n * (composite.TRAIN_FRAC + composite.VALID_FRAC))
            parts = {
                PARTS[0]: (0, lo1), PARTS[1]: (lo1, lo2), PARTS[2]: (lo2, n),
            }
            for risk_variant in RISK_VARIANTS:
                config = {
                    "mechanism": mechanism, "risk_variant": risk_variant,
                    "entry_model": "closed_4h_1h_15m_next_open",
                }
                cfg_digest = composite.digest({
                    "mechanism_config": config,
                    "source_sha": source_sha,
                    "verified_three_month_digest": baseline["verified_three_month_source_manifest_sha256"],
                    "monthly_report_digest": baseline["result_sha256"],
                    "contract": SCHEMA,
                })
                signal = composite.signal_for(feature_frame, config)
                for part, (lo, hi) in parts.items():
                    if hi - lo <= 0:
                        raise FourPairCompositeResearchError("empty chronological diagnostic partition")
                    for profile, (fee, slip) in (
                        ("conservative", (composite.ENTRY_FEE_BPS, composite.ENTRY_SLIP_BPS)),
                        ("stress", (composite.STRESS_FEE_BPS, composite.STRESS_SLIP_BPS)),
                    ):
                        metrics = composite.backtest(
                            feature_frame.iloc[lo:hi].reset_index(drop=True),
                            signal[lo:hi], fee_bps=fee, slip_bps=slip,
                            risk_variant=risk_variant,
                        )
                        rows.append({
                            "symbol": symbol, "entry_timeframe": "minute15",
                            "higher_contexts": "completed_hour1_completed_hour4",
                            "mechanism": mechanism, "peer": peer or "",
                            "risk_variant": risk_variant, "config_fingerprint": cfg_digest,
                            "part": part, "profile": profile, "bars": hi - lo,
                            "first_closed_utc": feature_frame["decision_at"].iloc[lo].isoformat(),
                            "last_closed_utc": feature_frame["decision_at"].iloc[hi-1].isoformat(),
                            **metrics,
                            "qualification": "RESEARCH_ONLY_NO_UNTOUCHED_OOS_NO_PORTFOLIO_QA",
                            "demo_promoted": False, "live_enabled": False,
                        })
    expected = len(MECHANISMS) * len(SYMBOLS) * len(RISK_VARIANTS) * len(PARTS) * len(PROFILES)
    if (
        len(rows) != expected
        or any(x["demo_promoted"] or x["live_enabled"] or x["trade_count_limit"] is not None
               for x in rows)
    ):
        raise FourPairCompositeResearchError("exact composite matrix or no-promotion authority failed")
    core = {
        "schema": SCHEMA, "source_sha": source_sha,
        "month": month.MONTH, "origin": baseline["origin"],
        "source_manifest_sha256": baseline["source_manifest_sha256"],
        "verified_three_month_source_manifest_sha256":
            baseline["verified_three_month_source_manifest_sha256"],
        "signed_monthly_baseline_sha256": baseline["result_sha256"],
        "frame_digests": {s: {tf: frame_digests[(s,tf)] for tf in TIMEFRAMES} for s in SYMBOLS},
        "symbols": list(SYMBOLS), "entry_timeframe": "minute15",
        "higher_contexts": ["closed_hour1", "closed_hour4"],
        "peer_topology": PEER_TOPOLOGY,
        "mechanisms": list(MECHANISMS),
        "distinct_causal_mechanisms": len(MECHANISMS),
        "risk_calibrations_per_mechanism": len(RISK_VARIANTS),
        "rows_per_mechanism": len(SYMBOLS)*len(RISK_VARIANTS)*len(PARTS)*len(PROFILES),
        "total_rows": len(rows),
        "capital_model": "separate_hypothetical_10000USDT_per_symbol_per_partition_not_a_portfolio",
        "simulation_model": "one_net_long_per_symbol_unbounded_sequential_trade_count",
        "historical_final_partition_pristine": False,
        "independent_numeric_QA_complete": False,
        "research_only": True, "auto_demo_promotion": False, "live_enabled": False,
        "rows": rows,
    }
    return {**core, "report_digest": composite.digest(core)}


def run(*, state: Path, monthly_report: Path, source_sha: str, output: Path) -> dict[str, Any]:
    if output.exists() or output.is_symlink():
        raise FourPairCompositeResearchError("never overwrite an existing research result")
    baseline, expected = _safe_monthly_report(monthly_report, source_sha, state)
    frames = month._load_full_month(state)
    report = calculate(frames, baseline, expected, source_sha=source_sha)
    output.mkdir(parents=True, exist_ok=False)
    composite.safe_write(output / "composite-report.json", report)
    with (output / "composite-table.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(report["rows"])
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--monthly-report", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    report = run(state=args.state_root, monthly_report=args.monthly_report,
                 source_sha=args.source_sha, output=args.output_root)
    print(json.dumps({
        "status": "COMPLETE_EXPLORATORY_HISTORICAL_NO_INDEPENDENT_QA",
        "source_sha": report["source_sha"], "report_digest": report["report_digest"],
        "distinct_causal_mechanisms": report["distinct_causal_mechanisms"],
        "rows": report["total_rows"], "auto_demo_promotion": False,
        "live_enabled": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
