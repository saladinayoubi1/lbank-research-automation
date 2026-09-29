"""Full July four-pair reviewed composite research from VERIFIED official Bybit archives.

Research only: 15m next-open entry with completed 1h/4h context; this is NOT
independent 1h or 4h entry trading, a multi-symbol portfolio, a pristine
future holdout, or a qualification for Paper or Live. All 5 reviewed causal
mechanisms and both risk robustness variants are exhaustively evaluated,
without ranking or a maximum number of trades.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re
from typing import Any, Mapping

import pandas as pd

import bybit_spot_backfill as backfill
import nexus_multipair_archive_snapshot as archive
import nexus_monthly_four_pair_pre_demo as monthly
import nexus_composite_strategy_research as composite
from nexus_multipair_trusted_surface import SYMBOLS, TIMEFRAMES

SCHEMA = "nexus.four-pair-july-reviewed-composite.v1"
QA_SCHEMA = "nexus.four-pair-july-composite-numeric-replay.v1"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA64 = re.compile(r"^[0-9a-f]{64}$")
EXPERIMENTS = composite.CONFIGS
PROFILES = (
    ("conservative", composite.ENTRY_FEE_BPS, composite.ENTRY_SLIP_BPS),
    ("stress", composite.STRESS_FEE_BPS, composite.STRESS_SLIP_BPS),
)
PARTITIONS = ("training", "historically_inspected_validation",
              "historically_inspected_test")
PEER = {"BTCUSDT": "ETHUSDT", "ETHUSDT": "BTCUSDT",
        "SOLUSDT": "BTCUSDT", "XRPUSDT": "BTCUSDT"}


class FourPairCompositeError(ValueError):
    pass


def _frame_digest(df: pd.DataFrame) -> str:
    """Use exactly the signed July monthly baseline's frame normalization."""
    return monthly._digest([
        [int(row.timestamp.value // 1_000_000), str(row.open), str(row.high),
         str(row.low), str(row.close), str(row.volume)]
        for row in df.itertuples(index=False)
    ])


def _baseline_frames(baseline: Mapping[str, Any],
                     frames: Mapping[tuple[str, str], pd.DataFrame],
                     source_sha: str) -> dict[str, str]:
    if (
        not SHA40.fullmatch(source_sha)
        or baseline.get("contract") != "nexus.bybit-monthly-pre-demo-table.v1"
        or baseline.get("source_sha") != source_sha
        or baseline.get("period") != "2026-07"
        or baseline.get("origin") != "official_public_bybit_spot_trade_archive_aggregated"
        or baseline.get("research_only") is not True
        or baseline.get("automatic_paper_promotion") is not False
        or baseline.get("live_trading_authority") is not False
        or baseline.get("bars_per_cadence") != monthly.EXPECTED_ROWS
        or not isinstance(baseline.get("archive_sources"), list)
        or len(baseline["archive_sources"]) != len(SYMBOLS)
        or set(x.get("symbol") for x in baseline["archive_sources"]) != set(SYMBOLS)
        or not SHA64.fullmatch(str(baseline.get("verified_three_month_source_manifest_sha256", "")))
    ):
        raise FourPairCompositeError("signed original full July official source contract mismatched")
    core = {k: v for k, v in baseline.items() if k != "result_sha256"}
    if (
        baseline.get("result_sha256") != monthly._digest(core)
        or baseline.get("source_manifest_sha256") != monthly._digest(baseline["archive_sources"])
    ):
        raise FourPairCompositeError("signed baseline research or official source digest tampered")
    expected = {(s, tf) for s in SYMBOLS for tf in TIMEFRAMES}
    if set(frames) != expected or len(PEER) != len(SYMBOLS):
        raise FourPairCompositeError("not an exact full four-pair three-timeframe input matrix")
    baseline_rows = baseline.get("rows")
    if not isinstance(baseline_rows, list) or len(baseline_rows) != len(expected) * 3:
        raise FourPairCompositeError("not exactly 36 original monthly baseline results")
    verified: dict[str, str] = {}
    for symbol, tf in sorted(expected):
        frame = frames[(symbol, tf)]
        actual = _frame_digest(frame)
        refs = [row for row in baseline_rows
                if row.get("symbol") == symbol and row.get("timeframe") == tf]
        if (
            len(refs) != 3
            or {row.get("family") for row in refs} !=
               {"momentum", "trend_breakout", "mean_reversion"}
            or any(row.get("frame_sha256") != actual
                   or row.get("bars") != monthly.EXPECTED_ROWS[tf]
                   or row.get("monthly_coverage") is not True
                   or row.get("source_sha") != source_sha
                   or row.get("demo_promoted") is not False
                   or row.get("live_enabled") is not False
                   or row.get("qualification") !=
                      "RESEARCH_ONLY_REQUIRES_INDEPENDENT_REQUALIFICATION"
                   for row in refs)
        ):
            raise FourPairCompositeError(f"July baseline frame or trading authority mismatched: {symbol}/{tf}")
        verified[f"{symbol}/{tf}"] = actual
    return verified


def _source_state_verified(state: Path, baseline: Mapping[str, Any]) -> None:
    """Revalidate all 12 actual compressed official sources, not just a CSV label."""
    report_file = state / backfill.REPORT_NAME
    if report_file.is_symlink() or not report_file.is_file():
        raise FourPairCompositeError("no verified original official three-month archive report")
    report = json.loads(report_file.read_text(encoding="utf-8"))
    archive._validate_backfill_report(report)
    sources, signed = archive._source_evidence(state)
    if signed != baseline["verified_three_month_source_manifest_sha256"] or len(sources) != 12:
        raise FourPairCompositeError("current official compressed-source state differs from signed baseline")


def calculate(frames: Mapping[tuple[str, str], pd.DataFrame],
              baseline: Mapping[str, Any], source_sha: str) -> dict[str, Any]:
    bound = _baseline_frames(baseline, frames, source_sha)
    if (
        len(EXPERIMENTS) != 10
        or {c["mechanism"] for c in EXPERIMENTS} != set(composite.MECHANISMS)
        or {c["risk_variant"] for c in EXPERIMENTS} != {0, 1}
        or any(c["entry_model"] != "closed_4h_1h_15m_next_open" for c in EXPERIMENTS)
    ):
        raise FourPairCompositeError("reviewed full causal-mechanism grammar changed")
    # Frames have been fully checked and have EXACT same-UTC timing across
    # symbols/timeframes by monthly._load_full_month before this function.
    features: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
    for symbol in SYMBOLS:
        own = {tf: frames[(symbol, tf)] for tf in TIMEFRAMES}
        frames15 = own["minute15"].reset_index(drop=True)
        peer15 = frames[(PEER[symbol], "minute15")].reset_index(drop=True)
        if not frames15["timestamp"].reset_index(drop=True).equals(
            peer15["timestamp"].reset_index(drop=True)
        ):
            raise FourPairCompositeError("asynchronous official peer data is forbidden")
        f = composite.build_features(own, peer_15m=peer15)
        features[symbol] = (f, peer15)
    rows: list[dict[str, Any]] = []
    signatures: list[dict[str, Any]] = []
    dataset_id = composite.digest({
        "source_manifest_sha256": baseline["source_manifest_sha256"],
        "full_july_12_frames": bound,
        "period": baseline["period"],
    })
    for config in EXPERIMENTS:
        mechanism = config["mechanism"]
        fingerprint = composite.digest({
            "config": config, "dataset": dataset_id, "contract": SCHEMA
        })
        signatures.append({"mechanism": mechanism,
                           "risk_variant": config["risk_variant"],
                           "config_fingerprint": fingerprint})
        for symbol in SYMBOLS:
            f, _ = features[symbol]
            signals = composite.signal_for(f, config)
            n = len(f)
            if n != monthly.EXPECTED_ROWS["minute15"]:
                raise FourPairCompositeError("full month input was silently shortened")
            first = int(n * composite.TRAIN_FRAC)
            second = int(n * (composite.TRAIN_FRAC + composite.VALID_FRAC))
            for part, (start, end) in zip(
                PARTITIONS, ((0, first), (first, second), (second, n))
            ):
                # Historical partitions have been inspected by earlier NEXUS
                # work. Strictly no pristine/OOS profitability claim.
                for profile, fee, slip in PROFILES:
                    result = composite.backtest(
                        f.iloc[start:end].reset_index(drop=True), signals[start:end],
                        fee_bps=fee, slip_bps=slip,
                        risk_variant=config["risk_variant"],
                    )
                    rows.append({
                        "symbol": symbol,
                        "entry_timeframe": "15m",
                        "context_timeframes": ["completed_1h", "completed_4h"],
                        "peer": PEER[symbol] if mechanism == "cross_pair_relative_reclaim" else None,
                        "historical_period": "2026-07",
                        "part": part, "profile": profile,
                        "mechanism": mechanism,
                        "risk_variant": config["risk_variant"],
                        "config_fingerprint": fingerprint,
                        "source_sha": source_sha,
                        "dataset_fingerprint": dataset_id,
                        "original_monthly_frame_sha256": bound[f"{symbol}/minute15"],
                        "bars": end - start,
                        "first_closed_utc": str(f["decision_at"].iloc[start]),
                        "last_closed_utc": str(f["decision_at"].iloc[end-1]),
                        "qualification": "NOT_QUALIFIED_HISTORICAL_ALREADY_INSPECTED",
                        "auto_demo_promotion": False,
                        "live_enabled": False,
                        **result,
                    })
    expected_count = len(EXPERIMENTS) * len(SYMBOLS) * len(PARTITIONS) * len(PROFILES)
    if len(rows) != expected_count or expected_count != 240:
        raise FourPairCompositeError("full four-pair composite grid incomplete")
    core = {
        "schema": SCHEMA,
        "source_sha": source_sha,
        "source_manifest_sha256": baseline["source_manifest_sha256"],
        "verified_three_month_source_manifest_sha256":
            baseline["verified_three_month_source_manifest_sha256"],
        "monthly_baseline_digest": baseline["result_sha256"],
        "dataset_fingerprint": dataset_id,
        "original_frame_digests": bound,
        "source_origin": "official_public_bybit_spot_trade_archive_aggregated",
        "period": "2026-07",
        "symbols": list(SYMBOLS),
        "entry_timeframe": "15m",
        "context_timeframes": ["completed_1h", "completed_4h"],
        "simulated_cash_per_isolated_symbol_run_usdt": composite.SIM_CASH,
        "independent_concurrent_multi_asset_portfolio_tested": False,
        "independent_hourly_or_fourhour_entries_tested": False,
        "full_month_verified": True,
        "historical_test_pristine": False,
        "strategy_selection_performed": False,
        "automatic_paper_promotion": False,
        "live_trading_authority": False,
        "maximum_trade_count": None,
        "qualification": "RESEARCH_ONLY_REQUIRE_NEW_PROSPECTIVE_EVIDENCE",
        "reviewed_distinct_mechanisms": len(composite.MECHANISMS),
        "risk_parameter_variants_per_mechanism": 2,
        "rows_count": expected_count,
        "configurations": signatures,
        "rows": rows,
    }
    return {**core, "report_digest": composite.digest(core)}


def _validate_report_surface(value: Mapping[str, Any]) -> None:
    core = {k: v for k, v in value.items() if k != "report_digest"}
    if (
        value.get("schema") != SCHEMA
        or value.get("report_digest") != composite.digest(core)
        or value.get("automatic_paper_promotion") is not False
        or value.get("live_trading_authority") is not False
        or value.get("historical_test_pristine") is not False
        or value.get("strategy_selection_performed") is not False
        or value.get("independent_concurrent_multi_asset_portfolio_tested") is not False
        or value.get("independent_hourly_or_fourhour_entries_tested") is not False
        or len(value.get("rows", [])) != 240
        or value.get("rows_count") != 240
    ):
        raise FourPairCompositeError("monthly composite report integrity or safety failed")


def run(*, state: Path, baseline_file: Path, source_sha: str,
        output: Path) -> dict[str, Any]:
    if output.exists():
        raise FourPairCompositeError("refuse to overwrite previous full-month research")
    if baseline_file.is_symlink() or not baseline_file.is_file():
        raise FourPairCompositeError("original signed monthly baseline is missing")
    baseline = json.loads(baseline_file.read_text(encoding="utf-8"))
    _source_state_verified(state, baseline)
    frames = monthly._load_full_month(state)
    result = calculate(frames, baseline, source_sha)
    output.mkdir(parents=True, exist_ok=False)
    composite.safe_write(output / "composite-report.json", result)
    with (output / "composite-table.csv").open("w", encoding="utf-8", newline="") as handle:
        flattened = [
            {**row, "context_timeframes": ",".join(row["context_timeframes"])}
            for row in result["rows"]
        ]
        writer = csv.DictWriter(handle, fieldnames=list(flattened[0]))
        writer.writeheader()
        writer.writerows(flattened)
    return result


def replay_verify(*, state: Path, baseline_file: Path,
                  report_file: Path, source_sha: str, output: Path) -> dict[str, Any]:
    """A separate process reruns all 240 numerical experiments and compares all bytes.

    Same reviewed engine != independent model QA. This is a deterministic
    numerical replay gate; future untouched prospective QA remains required.
    """
    if output.exists() or not report_file.is_file() or report_file.is_symlink():
        raise FourPairCompositeError("invalid immutable original report or QA destination")
    report = json.loads(report_file.read_text(encoding="utf-8"))
    _validate_report_surface(report)
    baseline = json.loads(baseline_file.read_text(encoding="utf-8"))
    _source_state_verified(state, baseline)
    frames = monthly._load_full_month(state)
    recomputed = calculate(frames, baseline, source_sha)
    if recomputed != report:
        raise FourPairCompositeError("independent-process numerical replay did not match report")
    core = {
        "schema": QA_SCHEMA,
        "source_sha": source_sha,
        "report_digest": report["report_digest"],
        "monthly_baseline_digest": baseline["result_sha256"],
        "full_240_cell_numerical_replay_matches": True,
        "source_material_rechecked": True,
        "independent_model_qa_claimed": False,
        "historical_test_pristine": False,
        "automatic_paper_promotion": False,
        "live_trading_authority": False,
    }
    proof = {**core, "qa_digest": composite.digest(core)}
    output.mkdir(parents=True, exist_ok=False)
    composite.safe_write(output / "replay-proof.json", proof)
    return proof


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("run", "replay-verify"))
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.mode == "run":
        report = run(state=args.state, baseline_file=args.baseline,
                     source_sha=args.source_sha, output=args.output)
        print(json.dumps({key: report[key] for key in (
            "source_sha", "rows_count", "report_digest", "qualification"
        )}, sort_keys=True))
    else:
        if args.report is None:
            raise FourPairCompositeError("--report required for separate numerical replay")
        proof = replay_verify(
            state=args.state, baseline_file=args.baseline, source_sha=args.source_sha,
            report_file=args.report, output=args.output
        )
        print(json.dumps(proof, sort_keys=True))


if __name__ == "__main__":
    main()
