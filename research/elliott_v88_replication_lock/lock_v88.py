"""V88 preregistration-only replication lock. Does NOT fetch or inspect candles.

This artifact must be committed to Draft PR #2673 BEFORE source ingestion.
All windows, source file names, eligibility gates and scorers are fixed.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

RESEARCH_ONLY = True
ENTRY_SIGNAL = False
PAPER_ELIGIBLE = False
LIVE_ENABLED = False
V52_UNCHANGED = True
SOURCE_ACQUISITION_ENABLED = False
RESULT_SCORING_ENABLED = False
SCHEMA = "nexus.elliott-v88-unopened-historical-replication-lock.v1"
BINANCE_ROOT = "https://data.binance.vision/data/spot/daily/klines"
SOURCE_START = date(2024, 7, 1)
TOTAL_DAYS = 14
SYMBOLS = ("BTCUSDT", "ETHUSDT")
ONE_MINUTE_COUNT_PER_SYMBOL = 14 * 1440
CANDIDATE_FAMILIES = (
    "FIVE_LEG_15M_PARENT_3M_CHILD_SKELETON",
    "THREE_LEG_15M_PARENT_3M_CHILD_SKELETON",
    "ORDINARY_IMPULSE_HARD_GEOMETRY_ONLY",
    "DIAGONAL_HARD_VETO_ONLY",
    "DIAGONAL_1M_STRICT_INNER_DEGREE_ONLY",
    "ZIGZAG_535_1M_STRICT_INNER_DEGREE_ONLY",
    "FLAT_335_1M_STRICT_INNER_DEGREE_ONLY",
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = (REPOSITORY_ROOT / "docs" / "evidence" /
            "elliott-v88-frozen-independent-replication-20261017" /
            "V88_PREREGISTRATION.json")


def canonical_bytes(data: dict) -> bytes:
    return (json.dumps(data, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def manifest() -> dict:
    """Deterministic, output-free declaration. No I/O except caller writes."""
    dates = [SOURCE_START + timedelta(days=i) for i in range(TOTAL_DAYS)]
    if len(dates) != 14 or dates[0].isoformat() != "2024-07-01":
        raise RuntimeError("preregistered date series changed")
    inputs = []
    for symbol in SYMBOLS:
        for day in dates:
            label = day.isoformat()
            name = f"{symbol}-1m-{label}.zip"
            uri = f"{BINANCE_ROOT}/{symbol}/1m/{name}"
            inputs.append({
                "symbol": symbol,
                "utc_day": label,
                "zip_file": name,
                "csv_member": name.removesuffix(".zip") + ".csv",
                "official_checksum_file": name + ".CHECKSUM",
                "official_source_url": uri,
                "official_checksum_url": uri + ".CHECKSUM",
                "expected_1m_rows": 1440,
                "zip_sha256": None,
                "downloaded": False,
            })
    return {
        "schema": SCHEMA,
        "protocol_state": "LOCKED_SOURCE_UNOPENED",
        "project": "NEXUS Elliot research; existing draft PR 2673",
        "prerequisite_commit": "f99c9b09d1fdca213ae7ced66b13f005c856c307",
        "period": {
            "first_open_utc": "2024-07-01T00:00:00Z",
            "exclusive_end_utc": "2024-07-15T00:00:00Z",
            "duration_days": TOTAL_DAYS,
            "split_A_days": [d.isoformat() for d in dates[:7]],
            "split_B_days": [d.isoformat() for d in dates[7:]],
            "splits_are_both_evaluation_only": True,
            "no_train_or_tune_on_either_split": True,
            "no_replacement_days_if_unavailable": True,
            "selection_basis": "two contiguous full ISO weeks of July 2024, calendar preselection; no observed 2024-07 candles or target P/L used",
        },
        "exchange_and_granularity": {
            "provider": "Binance Spot official daily public archives",
            "symbols": list(SYMBOLS),
            "base_candle_minutes": 1,
            "primary_execution_exchange": "Bybit DEMO/PAPER only; inactive",
            "per_symbol_expected_1m_rows": ONE_MINUTE_COUNT_PER_SYMBOL,
            "per_symbol_expected_3m_bars": ONE_MINUTE_COUNT_PER_SYMBOL // 3,
            "per_symbol_expected_15m_bars": ONE_MINUTE_COUNT_PER_SYMBOL // 15,
            "zip_files_expected": len(inputs),
        },
        "source_acceptance": {
            "require_http_200_for_zip_and_CHECKSUM": True,
            "require_zip_sha256_equal_official_CHECKSUM": True,
            "require_single_exact_csv_member": True,
            "require_exact_12_column_binance_ohlc_schema": True,
            "require_1440_aligned_1m_utc_rows_per_day": True,
            "require_no_duplicate_missing_or_out_of_order_minute": True,
            "require_positive_finite_decimal_ohlc_bounds": True,
            "require_close_time_equal_open_time_plus_59999_ms": True,
            "reject_incomplete_file_or_partial_day": True,
            "fail_closed_on_unavailable_day_or_source": True,
            "do_not_use_backup_exchange_to_fill_gaps": True,
        },
        "frozen_recognition": {
            "parent_15m_strict_pivot_halfwidth_bars": 3,
            "child_3m_strict_pivot_halfwidth_bars": 1,
            "physical_source_1m_pivot_halfwidth_bars": 3,
            "inner_1m_strict_pivot_halfwidth_bars": 1,
            "do_not_prune_same_kind_or_awkward_primitive_pivots": True,
            "dual_high_and_low_extrema_same_candle": "explicit_ambiguity_abstain",
            "zigzag_535_inner_1m_pivot_counts_ABC": [4, 2, 4],
            "flat_335_inner_1m_pivot_counts_ABC": [2, 2, 4],
            "ordinary_impulse_wave4_overlap_forbidden": True,
            "diagonal_wave3_shortest_forbidden": True,
            "candidate_family_names": list(CANDIDATE_FAMILIES),
            "asof_rule": "all source bars must have closed, candidate first observable only after every parent and child pivot right-confirmed; no future tail",
            "left_edge": "no invented warmup history prior to 2024-07-01; report boundary censorship, do not fill or replace",
            "scoring_basis": "first_observable_utc not retrospective pivot_center_utc",
            "allow_count_as_full_recursive_elliott": False,
            "allow_paper_entry_or_pnl": False,
        },
        "required_observations": [
            "per-symbol 1m verified source rows, parent and child pivot counts",
            "counts by 7-day split and combined 14-day period using first observable decision",
            "all parent intervals including abstentions and same-kind rejection reasons",
            "five/three-leg skeleton candidate count and nested Zigzag/Flat inner count distribution",
            "ordinary impulse hard-fail counts, diagonal necessary-veto counts and 1m witness counts",
            "all as-of confirmations and timestamp-invariance tests",
            "zero-signal reason and explicit no-profitability-claim",
            "all rejection reasons, source hashes and report sha256",
        ],
        "study_limitations": {
            "historical_not_prospective": True,
            "not_a_trade_backtest": True,
            "not_proof_of_profitability": True,
            "pristine_relative_to_known_v80_2024_03_days": True,
            "absolute_never_seen_claim": False,
            "no_retuning_using_split_A_or_B": True,
            "v52_warmup_or_future_scores_not_read": True,
            "live_trading": False,
            "paper_eligible": False,
            "entry_signal": False,
            "net_pnl": None,
            "draft_pr_only_no_merge": True,
        },
        "scheduled_inputs": inputs,
    }


def verify(sealed: dict) -> None:
    if sealed != manifest():
        raise ValueError("the preregistration document deviates from code-fixed declaration")
    expected = [(s, (SOURCE_START + timedelta(days=j)).isoformat())
                for s in SYMBOLS for j in range(TOTAL_DAYS)]
    observed = [(x["symbol"], x["utc_day"]) for x in sealed["scheduled_inputs"]]
    if observed != expected:
        raise ValueError("source schedule unordered, incomplete or duplicated")


def seal() -> dict:
    frozen = manifest()
    verify(frozen)
    encoded = canonical_bytes(frozen)
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    # Manifest already exists? Refuse silent replacement of the commitment.
    if ARTIFACT.exists() and ARTIFACT.read_bytes() != encoded:
        raise RuntimeError("frozen manifest exists with different bytes")
    ARTIFACT.write_bytes(encoded)
    print(json.dumps({
        "stage": "V88_PREREGISTRATION_NO_MARKET_DATA_FETCH",
        "manifest_file": str(ARTIFACT),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "symbols": len(SYMBOLS),
        "full_days_each": TOTAL_DAYS,
        "zip_sources_to_check_later": len(frozen["scheduled_inputs"]),
        "score_or_signal_generated": False,
    }, indent=2))
    return frozen


if __name__ == "__main__":
    seal()
