"""Frozen MR40 L2 stop-reference *mark* sensitivity, NOT execution PnL.

Inputs: SHA-pinned original 4h baseline fill ledger, third-party public L2
snapshot/delta reconstruction, and pre-registered study policy. No network,
API credentials, orders, backtest reruns, or parameter optimization.
"""
from __future__ import annotations
import argparse,gzip,hashlib,json
from decimal import Decimal as D,ROUND_HALF_UP
from pathlib import Path

L2_DIGEST="5cb72adacf98f0789b3095557234b07fdc21317858b64b685cda9dde3a2738e8"
LEDGER_SHA="2c7115bac4ae81cc5c21b9bfc96319d5bee79baa746074c92c998125a834331e"
HEAD="4332f84854dd5e0b6b8c1435322ac706401d8f24"
CASES=("before_1s","first_cross","after_100ms","after_1s","after_5s","after_15s","first_recovery_print")

def canon(x):
    return json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()

def fixed(d,n=6):
    return format(d.quantize(D(10)**-n,rounding=ROUND_HALF_UP),"f")

def evaluate(policy_path,l2_path,ledger_path,out_path):
    if out_path.exists():raise ValueError("refuse_overwrite")
    pol=json.loads(policy_path.read_bytes())
    if pol["schema"]!="mr40.spot-l2-event-marked-risk-envelope.v1" or pol["parent_head"]!=HEAD:
        raise ValueError("policy_drift")
    if tuple(pol["fixed_samples"])!=CASES or pol["sources"]["l2_digest"]!=L2_DIGEST or pol["sources"]["ledger_sha256"]!=LEDGER_SHA:
        raise ValueError("frozen_sources_or_samples_changed")
    if hashlib.sha256(ledger_path.read_bytes()).hexdigest()!=LEDGER_SHA:raise ValueError("ledger_not_pinned")
    raw=json.loads(l2_path.read_bytes());digest=raw.pop("digest")
    if digest!=L2_DIGEST or hashlib.sha256(canon(raw)).hexdigest()!=L2_DIGEST:raise ValueError("l2_not_pinned")
    if (raw["cross_state_usable"] is not True or raw["full_day_strict_time_scope_pass"] is not False
        or not raw["prior_4h_1m_full_ohlc_parity"].startswith("FAILED")
        or raw["real_fill_verified"] is not False):
        raise ValueError("missing_required_l2_warnings")
    matched=None
    with gzip.open(ledger_path,"rt",encoding="utf-8") as fh:
        for line in fh:
            obj=json.loads(line)
            k=obj["key"]
            if (k["venue"],k["window"],k["capital"],k["profile"],k["case"])!=(
                pol["entry_match"]["venue"],pol["entry_match"]["window"],pol["entry_match"]["capital"],
                pol["entry_match"]["profile"],pol["entry_match"]["case"]):
                continue
            subset=[p for p in obj["positions"] if p["entry"]["fill_ms"]==pol["entry_match"]["entry_ms"]]
            if len(subset)!=1:raise ValueError("entry_not_unique")
            matched=subset[0]
            break
    if matched is None:raise ValueError("original_fill_missing")
    ent=matched["entry"]
    quantity=D(str(ent["quantity"]))
    fill=D(str(ent["price"]))
    cash=D(str(ent["cash_before"]))
    if quantity!=D(pol["entry_match"]["expected_entry_quantity_btc"]) or fill!=D(pol["entry_match"]["expected_filled_entry_price"]):
        raise ValueError("entry_drift")
    if quantity<=0 or cash<=0 or D(str(ent["cash_after"]))<0:raise ValueError("invalid_position")
    stop=fill*(D(1)-D(str(pol["entry_match"]["stop_fraction"])))
    book_states={s["label"]:s for s in raw["snapshots"]}
    if any(name not in book_states for name in CASES):raise ValueError("missing_registered_case")
    table=[]
    for name in CASES:
        s=book_states[name];depth=s.get("depth_mark",{})
        if not(s["book_valid"] and 0<=s["age_ms"]<=2000 and
               depth.get("zero_latency_static_displayed_book_walk_completely_covered") is True and
               depth["bid"]<depth["ask"] and
               abs(D(str(depth["recorded_position_qty_btc"]))-quantity)<D("0.000000001")):
            raise ValueError("invalid_L2_at_"+name)
        mark=D(str(depth["static_book_walk_vwap_mark"]))
        offset=mark-stop
        sensitivity=offset*quantity
        percent_cash=(sensitivity/cash)*D(100)
        entry_mark_drop=fill-mark
        table.append({
            "label":name,"target_utc":s["target_utc"],"book_timestamp_utc":s["source_timestamp_utc"],
            "age_ms":s["age_ms"],"bid":str(depth["bid"]),"ask":str(depth["ask"]),
            "top20_displayed_bid_btc":fixed(D(str(depth["top_20_bid_btc"])),6),
            "static_mark_usdt_per_btc":fixed(mark,6),
            "mark_minus_stop_usdt_per_btc":fixed(offset,6),
            "mark_vs_stop_for_original_qty_usdt":fixed(sensitivity,6),
            "mark_vs_stop_pct_pre_entry_cash":fixed(percent_cash,6),
            "entry_minus_mark_usdt_per_btc":fixed(entry_mark_drop,6),
            "levels_for_original_qty":depth["book_walk_levels"]
        })
    last=next(x for x in table if x["label"]=="after_15s")
    distance=fill-D(last["static_mark_usdt_per_btc"])
    if distance<=0:raise ValueError("unexpected_nonadverse_reference_mark")
    diag_caps=[]
    for risk in (D("0.01"),D("0.02")):
        amount=(risk*cash)/distance
        diag_caps.append({
            "budget_pct_cash":fixed(risk*100,2),
            "budget_usdt":fixed(cash*risk,6),
            "algebraic_qty_btc":fixed(amount,8),
            "fraction_of_observed_position":fixed(amount/quantity,6),
            "NOT_DEPLOYMENT_RECOMMENDATION":True
        })
    out={
        "schema":"mr40.spot-l2-event-marked-risk-envelope.results.v1",
        "research_only":True,"future_blind":False,"paper_changed":False,"live":False,
        "actual_stop_execution_known":False,"no_realized_pnl_in_report":True,
        "protocol_sha256":hashlib.sha256(policy_path.read_bytes()).hexdigest(),
        "source_evidence":{"l2_digest":L2_DIGEST,"ledger_sha256":LEDGER_SHA,
            "third_party_recorder":True,"l2_daily_scope_pass":False,"parent_4h_1m_ohlc_pass":False},
        "original_recorded_entry":{"fill_ms":ent["fill_ms"],"cash_before_entry":str(cash),
          "btc_qty":str(quantity),"entry_fill_price":str(fill),"static_stop_reference":str(stop),
          "baseline_exit_reason":matched["exit"]["reason"]},
        "fixed_sample_table":table,
        "fifteen_second_mark_distance_from_entry":fixed(distance,6),
        "fifteen_second_entry_to_mark_notional_move_original_qty":fixed(quantity*distance,6),
        "fifteen_second_entry_to_mark_pct_pre_entry_cash":fixed(quantity*distance/cash*100,6),
        "algebra_only_risk_budget_diagnostics":diag_caps,
        "caveat":"Displayed third-party book snapshots are non-executable marks at preselected time labels, not order fills, future forecasts, slippage, executable PNL, or strategy approval. Book recording cadence, cancellations, queueing, transmission latency, fees and partial fills are not modeled."
    }
    out["digest"]=hashlib.sha256(canon(out)).hexdigest()
    out_path.write_bytes(canon(out)+b"\n")
    print(json.dumps({"digest":out["digest"],"entry":out["original_recorded_entry"],
       "cases":table,"caps":diag_caps},ensure_ascii=False),flush=True)
    return out

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    for key in ("policy_path","l2_path","ledger_path","out_path"):
        parser.add_argument("--"+key.replace("_","-"),required=True,type=Path)
    evaluate(**vars(parser.parse_args()))
