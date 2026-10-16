"""V78 retrospective stop-bar OHLC path ambiguity audit.

Reads immutable, hash-pinned V77 physical first-touch source-bar audit.
Splits *certifiably earlier completed-bar* favorable moves from high values
inside the terminal stop bar, whose intrabar ordering cannot be inferred.
No hypothetical earlier take-profit fills, optimizing, trading or P/L.
"""
from __future__ import annotations
import argparse
from collections import Counter
from decimal import Decimal,InvalidOperation
from hashlib import sha256
import json
from pathlib import Path

V77_SHA256="6e842b71af41f43a78c3e70c3e148ee1896153123aad8e4e2a8cc8f7660806e3"
SOURCE_TRACE_SHA256="c734d9abd0dd8a18fe4269a15b8eceddf91643d8943ddb3bc851311772f2373c"
RESEARCH_ONLY=True
ENTRY_SIGNAL=False
EXIT_SIGNAL=False
PAPER_ELIGIBLE=False
LIVE_ENABLED=False
AUTO_DEMO=False
FILLED_ORDERS_CONFIRMED=False
NEW_PNL=None
ONE_R=Decimal("1")

def hashfile(path):
    h=sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda:f.read(1048576),b""):h.update(b)
    return h.hexdigest()

def decimal(x):
    if isinstance(x,bool):raise ValueError("BAD_BOOLEAN_METRIC")
    try:value=Decimal(str(x))
    except (TypeError,ValueError,InvalidOperation) as e:
        raise ValueError("INVALID_R_MULTIPLE") from e
    if not value.is_finite():raise ValueError("NONFINITE_R_MULTIPLE")
    return value

def classify_stop_record(record):
    """Return an observed exposure classification, not a trade recommendation."""
    if record["exit_reason"] not in ("stop","stop_open_gap"):
        raise ValueError("STOP_ONLY_INTERPRETATION")
    if record.get("invalid_earlier_exit") is not False or int(record["prior_exit_touch_count"])!=0:
        raise ValueError("UNVERIFIED_FIRST_TOUCH_PATH")
    exposure=record["exposure_bars"]
    if type(exposure) is not int or exposure<=0:
        raise ValueError("INVALID_EXPOSURE_BARS")
    earlier=record["preexit_favorable_R"]
    terminal_included=decimal(record["full_hold_favorable_R"])
    target=decimal(record["target_reward_to_stop_risk_R"])
    if target<=0:raise ValueError("INVALID_RISK_TARGET")
    if exposure==1:
        if earlier is not None:raise ValueError("ONE_BAR_MUST_HAVE_NO_PREEXIT_CANDLE")
        earlier_max=None
    else:
        if earlier is None:raise ValueError("MISSING_CERTIFIABLE_EARLIER_MFE")
        earlier_max=decimal(earlier)
        if earlier_max>terminal_included:
            raise ValueError("PRIOR_HIGH_CANNOT_EXCEED_FULL_HIGH")
    # An OHLC HIGH > 1R inside the stop bar is NOT known to occur before
    # the LOW hit the stop. This applies even if the profit target wasn't hit.
    prior_1r=bool(earlier_max is not None and earlier_max>=ONE_R)
    terminal_1r=bool(terminal_included>=ONE_R)
    return {
        "symbol":record["symbol"],"partition":record["partition"],
        "profile":record["profile"],"trade_index":int(record["trade_index"]),
        "bars_exposed":exposure,
        "verified_strict_prior_bar_favorable_at_least_1R":prior_1r,
        "full_ohlc_high_including_stop_bar_at_least_1R":terminal_1r,
        "terminal_stop_bar_intrabar_1R_timing_unresolved":
            bool(terminal_1r and not prior_1r),
        "earlier_completed_bar_mfe_R":str(earlier_max) if earlier_max is not None else None,
        "full_exposure_high_mfe_R":str(terminal_included),
        "original_target_multiple_R":str(target),
        "realized_stop_not_a_validated_1R_profit":True,
        "simulator_exit_reason":record["exit_reason"]
    }

def audit_v77_receipt(v77_path):
    if hashfile(v77_path)!=V77_SHA256:
        raise ValueError("IMMUTABLE_V77_SOURCE_BAR_RECEIPT_HASH_MISMATCH")
    source=json.loads(Path(v77_path).read_text(encoding="utf8"))
    if (source.get("schema")!="nexus.elliott-v77-first-touch-source-causal-exit-audit.v1" or
        source.get("frozen_trace_sha256")!=SOURCE_TRACE_SHA256 or
        source.get("archived_15m_physical_validation_performed") is not True or
        source.get("all_preexit_source_bars_checked_for_early_touch") is not True or
        source.get("incorrect_early_exit_holds_detected")!=0 or
        source.get("paired_cost_profile_exit_paths_checked")!=20 or
        source.get("different_historical_simulated_trades")!=10 or
        source.get("demo_promotion") is not False or
        source.get("live_enabled") is not False or
        source.get("new_pnl") is not None):
        raise ValueError("ORIGINAL_V77_FIRST_TOUCH_EVIDENCE_REQUIRED")
    rows=source.get("per_trade")
    if not isinstance(rows,list) or len(rows)!=20:
        raise ValueError("SOURCE_PATH_COUNT_WRONG")
    stops=[r for r in rows if r.get("exit_reason") in ("stop","stop_open_gap")]
    if len(stops)!=12 or len(rows)-len(stops)!=8:
        raise ValueError("ORIGINAL_STOP_TARGET_COUNTS_CHANGED")
    records=[classify_stop_record(r) for r in stops]
    paired={}
    for r in records:
        key=(r["symbol"],r["partition"],r["trade_index"])
        bucket=paired.setdefault(key,set())
        if r["profile"] in bucket:raise ValueError("DUPLICATE_PROFILE")
        bucket.add(r["profile"])
    if (len(paired)!=6 or
        any(v!={"conservative","stress"} for v in paired.values())):
        raise ValueError("SIX_PAIRING_VALIDATION_FAILED")
    counts=Counter()
    for r in records:
        if r["verified_strict_prior_bar_favorable_at_least_1R"]:
            counts["strict_prior_bar_1r"]+=1
        if r["terminal_stop_bar_intrabar_1R_timing_unresolved"]:
            counts["stop_bar_only_ambiguous_1r"]+=1
        if r["bars_exposed"]==1:counts["one_bar_stop"]+=1
    uncertain_unique=sorted({
        (x["symbol"],x["partition"],x["trade_index"])
        for x in records
        if x["terminal_stop_bar_intrabar_1R_timing_unresolved"]})
    return {
        "schema":"nexus.elliott-v78-frozen-stop-bar-ohlc-path-ambiguity.v1",
        "source_v77_sha256":hashfile(v77_path),
        "already_inspected_historical_legacy":True,
        "unique_losing_stop_trades":len(paired),
        "stop_profiles_verified":len(records),
        "strictly_prior_completed_bar_profit_1R_instances":
            counts["strict_prior_bar_1r"],
        "same_terminal_stop_bar_high_1R_without_verified_order_instances":
            counts["stop_bar_only_ambiguous_1r"],
        "distinct_ambiguous_historical_stop_trades":len(uncertain_unique),
        "ambiguous_stops":[
            dict(symbol=sym,partition=part,trade_index=index)
            for sym,part,index in uncertain_unique],
        "stopped_on_entry_bar_profile_records":counts["one_bar_stop"],
        "intrabar_order_was_independently_reconstructed":False,
        "hypothetical_pre_stop_profitable_exits_proven":0,
        "no_legacy_strategy_promotion":True,
        "prospective_v52_score":False,
        "entry_signal":False,"exit_signal":False,"paper_eligible":False,
        "live_enabled":False,"new_pnl":None,
        "profile_paths":records,
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--v77",required=True)
    p.add_argument("--output",required=True)
    a=p.parse_args()
    output=Path(a.output)
    if output.exists():raise RuntimeError("IMMUTABLE_REPORT_CANNOT_OVERWRITE")
    result=audit_v77_receipt(a.v77)
    output.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print(json.dumps({
        "stop_profiles":result["stop_profiles_verified"],
        "strict_prior_1R":result["strictly_prior_completed_bar_profit_1R_instances"],
        "terminal_ambiguous_1R":result["same_terminal_stop_bar_high_1R_without_verified_order_instances"],
        "distinct_ambiguous_stops":result["distinct_ambiguous_historical_stop_trades"],
        "output_sha256":hashfile(output)
    },ensure_ascii=False))
if __name__=="__main__":main()
