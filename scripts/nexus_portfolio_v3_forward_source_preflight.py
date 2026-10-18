"""Fail-closed, READ-ONLY future Bybit Spot source-coverage preflight.

This does not fetch prices, place orders, run a backtest, verify Bybit TLS
history, or approve an exchange/source. It locks the previously declared
2026-10-19 .. 2027-01-17 future scoring window and makes the August 2026
archive-gap bars explicit warmup-only. A raw-file SHA is necessary but NOT
sufficient to establish the producer; external independent provenance QA
must approve any source before economic results are considered.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
FREEZE_FILE=ROOT/"research/portfolio_v3_forward_bybit_source_freeze_20261018.json"
SCHEMA="nexus.portfolio-v3-forward-bybit-spot-source-freeze.v1"
INPUT_SCHEMA="nexus.portfolio-v3-external-4h-claimed-source-receipt.v1"
RESULT_SCHEMA="nexus.portfolio-v3-forward-source-coverage-only.v1"
# The Git-reviewed original 2026-10-18 freeze file is byte-locked; only CRLF
# checkout normalization is permitted, never content, keys or benchmark edits.
EXPECTED_FREEZE_SHA256="99d70217e1ce05fe6429c075e04e7b6f99e042d61947216e51f06493732baed4"
SYMBOLS=("BTCUSDT","ETHUSDT")
SHA=re.compile(r"^[a-f0-9]{64}$")
SOURCE_START=pd.Timestamp("2026-08-01T00:00:00Z")
SCORE_START=pd.Timestamp("2026-10-19T00:00:00Z")
SCORE_END=pd.Timestamp("2027-01-17T00:00:00Z")
STEP=pd.Timedelta(hours=4)


class ForwardSourceError(ValueError):
    pass


def _read_json(path:Path)->dict:
    if path.is_symlink() or not path.is_file() or not 0<path.stat().st_size<=16384:
        raise ForwardSourceError("missing/linked/oversized research receipt")
    try:
        obj=json.loads(path.read_text(encoding="utf8"))
    except (UnicodeError,ValueError) as exc:
        raise ForwardSourceError("invalid immutable JSON research receipt") from exc
    if type(obj) is not dict:
        raise ForwardSourceError("receipt must be exact object")
    return obj


def verified_freeze(path:Path=FREEZE_FILE)->tuple[dict,str]:
    """Fail closed on changes to pre-committed 500/old candidate/risk/window."""
    o=_read_json(path)
    if (o.get("schema")!=SCHEMA or o.get("as_of_utc_date")!="2026-10-18"
        or o.get("base_main_commit_sha")!="2f7ec90a5b01753ec58e5959b0fec6aaa4c2ff01"
        or o.get("original_strategy_id")!="b4e4a2c33304aec1"
        or o.get("original_strategy_family")!="dual_rotation"
        or o.get("source_extension_start_utc")!=SOURCE_START.isoformat().replace("+00:00","Z")
        or o.get("future_scoring_start_utc")!=SCORE_START.isoformat().replace("+00:00","Z")
        or o.get("future_scoring_end_exclusive_utc")!=SCORE_END.isoformat().replace("+00:00","Z")
        or o.get("original_pinned_archive_last_4h_open_utc")!="2026-07-31T20:00:00Z"
        or o.get("required_symbols")!=list(SYMBOLS)
        or o.get("required_period_hours")!=4
        or o.get("original_wallet_start_cash_usdt")!=500
        or o.get("risk_policy")!={
            "schema":"nexus.portfolio-v3-causal-close-dd20-nextopen.v1",
            "max_closed_bar_drawdown_fraction":0.20,
            "halt_rest_of_research_period":True,
            "exit":"next_4h_open_sell_first_no_reentry",
            "live_authority":False
        }
        or o.get("original_execution_cost_profiles")!={
            "conservative":{"initial_cash":500,"fee_bps":10,"slippage_bps":5},
            "stress":{"initial_cash":500,"fee_bps":15,"slippage_bps":10},
            "severe":{"initial_cash":500,"fee_bps":25,"slippage_bps":15}
        }
        or o.get("risk_threshold_selected_after_seeing_historical_34pct_drawdown") is not True
        or o.get("full_horizon_required_for_readiness") is not True
        or o.get("independent_qa_required") is not True
        or o.get("no_parameter_search") is not True
        or o.get("no_minimum_trade_count_gate") is not True
        or o.get("research_only") is not True
        or o.get("auto_qualification") is not False
        or o.get("live_enabled") is not False
        or o.get("paper_eligible") is not False
        or o.get("automatic_demo_promotion") is not False):
        raise ForwardSourceError("future source freeze altered or missing exact risk/cash/date contract")
    fixed_digest=sha256(path.read_bytes().replace(b"\r\n",b"\n")).hexdigest()
    if fixed_digest!=EXPECTED_FREEZE_SHA256:
        raise ForwardSourceError("future source freeze altered: precommitted SHA256 identity changed")
    return o,fixed_digest


def validate_physical_4h(frame:pd.DataFrame,symbol:str)->dict:
    """No inferred/imputed bars, no 15m->4h resampling or lookahead."""
    if symbol not in SYMBOLS or type(frame) is not pd.DataFrame or list(frame.columns)!=[
        "timestamp","open","high","low","close","volume"]:
        raise ForwardSourceError("unapproved physical Bybit Spot symbol or OHLCV schema")
    if len(frame)!=len(pd.date_range(SOURCE_START,SCORE_END-STEP,freq="4h")):
        raise ForwardSourceError("missing/extra 4h source history: no implicit gap filling")
    dtype=frame["timestamp"].dtype
    # Never silently assign UTC to naive local date/time or epoch integers.
    # Explicit UTC-aware pandas datetimes or RFC3339-style explicit-UTC
    # strings are the only representations accepted by this source gateway.
    if isinstance(dtype,pd.DatetimeTZDtype):
        if str(dtype.tz)!="UTC":
            raise ForwardSourceError("source timestamps must use explicit UTC timezone")
    elif pd.api.types.is_datetime64_any_dtype(dtype):
        raise ForwardSourceError("source timestamps lack explicit UTC timezone")
    elif pd.api.types.is_object_dtype(dtype):
        if not all(isinstance(x,str) and (x.endswith("Z") or x.endswith("+00:00"))
                   for x in frame["timestamp"]):
            raise ForwardSourceError("source timestamps lack explicit UTC")
    else:
        raise ForwardSourceError("4h source timestamps must have explicit UTC")
    try:
        parsed=pd.to_datetime(frame["timestamp"],utc=True,errors="raise")
    except (ValueError,TypeError) as exc:
        raise ForwardSourceError("non-UTC or unparsable original 4h timestamps") from exc
    if parsed.isna().any():
        raise ForwardSourceError("missing 4h source timestamp")
    expected=pd.date_range(SOURCE_START,SCORE_END-STEP,freq="4h")
    if not pd.DatetimeIndex(parsed).equals(expected):
        raise ForwardSourceError("physical source timestamps not strictly contiguous or not original period")
    matrix=frame[["open","high","low","close","volume"]].to_numpy(dtype=float)
    if (not np.isfinite(matrix).all()
        or (matrix[:,:4]<=0).any() or (matrix[:,4]<0).any()):
        raise ForwardSourceError("unphysical price/volume values")
    op,hi,lo,cl=(matrix[:,i] for i in range(4))
    if (hi<np.maximum.reduce([op,lo,cl])).any() or (
        lo>np.minimum.reduce([op,hi,cl])).any():
        raise ForwardSourceError("unphysical OHLC intrabar envelope")
    score_mask=(pd.DatetimeIndex(parsed)>=SCORE_START)
    if not score_mask.any():
        raise ForwardSourceError("scored portion omitted")
    return {
        "symbol":symbol,
        "source_start_utc":SOURCE_START.isoformat(),
        "last_4h_open_utc":parsed.iloc[-1].isoformat(),
        "warmup_4h_bars":int((~score_mask).sum()),
        "future_scoring_4h_bars":int(score_mask.sum()),
        "physically_verified_full_4h_bars":len(frame),
    }


def audit_future_extension(
    input_receipt:Path,
    btc_parquet:Path,
    eth_parquet:Path,
    *,
    observed_at_utc:datetime|None=None,
    freeze_path:Path=FREEZE_FILE,
)->dict:
    freeze,freeze_raw_sha=verified_freeze(freeze_path)
    receipt=_read_json(input_receipt)
    if (receipt.get("schema")!=INPUT_SCHEMA
        or receipt.get("claimed_provider")!="BYBIT_SPOT"
        or receipt.get("claimed_4h_api_endpoint")!="https://api.bybit.com/v5/market/kline"
        or receipt.get("claimed_http_status")!=200
        or set(receipt.get("file_sha256_by_symbol",{}))!=set(SYMBOLS)
        or set(receipt)!={"schema","claimed_provider","claimed_4h_api_endpoint",
                          "claimed_http_status","file_sha256_by_symbol",
                          "collected_after_utc"}):
        raise ForwardSourceError("missing direct Bybit source receipt / untrusted substitute")
    observation=observed_at_utc or datetime.now(timezone.utc)
    if observation.tzinfo is None or observation.utcoffset().total_seconds()!=0:
        raise ForwardSourceError("observed time must be aware UTC")
    # A prospective 90-day run must never report readiness while it is still
    # ongoing, including a current synthetic/parquet file with future rows.
    if pd.Timestamp(observation)<SCORE_END:
        raise ForwardSourceError("future scoring horizon incomplete: no forward result yet")
    collected=pd.Timestamp(receipt["collected_after_utc"])
    if (collected.tzinfo is None or collected.utcoffset().total_seconds()!=0
        or collected<SCORE_END or collected>pd.Timestamp(observation)):
        raise ForwardSourceError("uncredible claimed future source collection time")
    provenance={}
    previous_dates=None
    for symbol,path in zip(SYMBOLS,(btc_parquet,eth_parquet)):
        if (path.is_symlink() or not path.is_file()
            or not 100<path.stat().st_size<10_000_000):
            raise ForwardSourceError("missing/symlink/oversized prospective source")
        actual=sha256(path.read_bytes()).hexdigest()
        claimed=receipt["file_sha256_by_symbol"].get(symbol)
        if not isinstance(claimed,str) or not SHA.fullmatch(claimed) or claimed!=actual:
            raise ForwardSourceError("raw physical parquet differs from claimed receipt hash")
        df=pd.read_parquet(path)
        item=validate_physical_4h(df,symbol)
        dates=pd.DatetimeIndex(pd.to_datetime(df["timestamp"],utc=True))
        if previous_dates is not None and not previous_dates.equals(dates):
            raise ForwardSourceError("BTC ETH peer grid mismatch")
        previous_dates=dates
        item["file_sha256"]=actual
        provenance[symbol]=item
    report={
        "schema":RESULT_SCHEMA,
        "frozen_research_manifest_sha256":freeze_raw_sha,
        "source_receipt_sha256":sha256(input_receipt.read_bytes()).hexdigest(),
        "claimed_bybit_source_file_byte_integrity_verified":True,
        "extension_start_matches_previously_verified_original_archive_tail":True,
        "original_historical_archive_six_sha_rechecked_in_this_preflight":False,
        "source_provider_claim_not_independently_authenticated":True,
        "external_provider_qa_still_required":True,
        "future_scoring_window_source_time_coverage_complete":True,
        "market_data_real_exchange_provenance_independently_verified":False,
        "ready_for_strategy_result_or_paper":False,
        "scoring_window_start_utc":freeze["future_scoring_start_utc"],
        "scoring_window_end_exclusive_utc":freeze["future_scoring_end_exclusive_utc"],
        "pre_scoring_bar_rows_warmup_only":True,
        "original_2023_2026_historical_performance_is_not_future_validation":True,
        "cash_usdt":500,
        "unmodified_candidate_id":freeze["original_strategy_id"],
        "original_risk_contract":freeze["risk_policy"],
        "sources":provenance,
        "paper_eligible":False,"live_enabled":False,"orders":0,
    }
    report["digest"]=sha256(json.dumps(
        report,sort_keys=True,separators=(",",":"),allow_nan=False
    ).encode()).hexdigest()
    return report


def main()->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-receipt",required=True,type=Path)
    p.add_argument("--btc-parquet",required=True,type=Path)
    p.add_argument("--eth-parquet",required=True,type=Path)
    p.add_argument("--output",required=True,type=Path)
    args=p.parse_args()
    result=audit_future_extension(args.source_receipt,args.btc_parquet,args.eth_parquet)
    # Write once with no overwrite; research-only, not proof of exchange auth.
    if args.output.exists() or args.output.is_symlink():
        raise ForwardSourceError("future source audit already written")
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n",encoding="utf8")
    print(json.dumps({
        "source_coverage":True,
        "provider_independently_authenticated":False,
        "status":"PROVENANCE_QA_AND_MANUAL_RESEARCH_REVIEW_STILL_REQUIRED",
        "digest":result["digest"],"paper_eligible":False,
        "live_enabled":False,
    },sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
