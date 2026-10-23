"""Post-day read-only MR40 pre-profit-arm risk telemetry for LOCKED 2026-10-23 Spot day.

Not a stop backtest, not a fill, not a Paper trade. No retuning on the
47 already-seen trades. Conditional on an authentic completed public archive.
"""
from __future__ import annotations
import argparse,gzip,hashlib,json,time
from datetime import datetime,timezone
from decimal import Decimal as D
from pathlib import Path
from research.nexus_mr40_bybit_archive_bridge_v1 import rollup,epoch,STEP4,BASE_URL
from research.nexus_mr40_independent_closed_signal_v1 import canon,ROWS_SHA
from research.nexus_mr40_bybit_forward_shadow_v1 import EXPECTED_BRIDGE,NOT_BEFORE

LOCK_SCHEMA="nexus.mr40.prearm_forward_risk_telemetry.protocol.v1"
FEE=D("0.001")
ARM=D("1.02")
Q0=D("500")
FIXED_SHADOW_DAY="2026-10-23"
OCT22_SHA="9591b0ccf534810939771e59ec95d6dbab4f978a72c57f86b2b332ef4cb84587"
OCT22_PARITY="59c037de00de8af3b403ea1ca069fe2362d658a71bc428ecae6895b0fe7bc380"
OCT22_CLOSE="a3f46cf792cb47d1a3ebd01a7d5debe6abda0f0f7122a9fa9c437dff63daf351"
LIMITS=(D("5"),D("10"))

def utc(ms):
    return datetime.fromtimestamp(ms/1000,timezone.utc).isoformat()

def check_lock(p):
    try:
        x=p["sources"]; f=p["fixed_measurement"];s=p["safety"]
        good=(p["schema"]==LOCK_SCHEMA and x["locked_future_day"]==FIXED_SHADOW_DAY and
             x["earliest_eligible_utc"]=="2026-10-24T00:00:00Z" and
             x["original_8514_market_sha256"]==ROWS_SHA and
             x["preverified_oct22_archive_sha256"]==OCT22_SHA and
             x["preverified_oct22_independent_tick_vs_WS_logical_digest"]==OCT22_PARITY and
             x["previous_oct20_oct21_bridge_logical_digest"]==EXPECTED_BRIDGE and
             x["oct22_historical_close_state_logical_digest"]==OCT22_CLOSE and
             x["oct22_last_closed_target_long"] is False and
             x["oct22_first_entry_and_natural_exit_markers"]==[0,0] and
             x["oct23_full_4h_candles"]==6 and x["spot_not_perpetual"] is True and
             f["initial_quote_reference_USDT"]=="500" and
             f["public_spot_VIP0_reference_fee_per_side"]=="0.001" and
             f["prior_profit_arm_at_completed_4h_close_pct"]=="2" and
             f["pre_arm_price_adverse_thresholds_descriptive_not_stops_pct"]==[5,10] and
             s["orders"]==0 and s["private_api"] is False and
             s["Live"] is False and s["Paper_500USDT_unchanged"] is True and
             s["promote"] is False and s["merge"] is False and
             s["automations"] is False)
    except (KeyError,TypeError):
        good=False
    if not good:raise ValueError("precommitted_prearm_protocol_drift")

def verified_json(file):
    p=json.loads(file.read_bytes())
    digest=p.pop("digest",None)
    if not isinstance(digest,str) or hashlib.sha256(canon(p)).hexdigest()!=digest:
        raise ValueError("canonical_verified_evidence_drift")
    return p,digest

def validate_inputs(lock,shadow,oct22,archive,clock_ms):
    if type(clock_ms) is not int or clock_ms<NOT_BEFORE:
        raise ValueError("full_future_utc_day_not_finished_fail_closed")
    locked_bytes=lock.read_bytes()
    check_lock(json.loads(locked_bytes))
    observed,obs_digest=verified_json(oct22)
    if (obs_digest!=OCT22_CLOSE or observed["oct22_last_closed_target_long"] is not False
        or observed["oct22_first_entry_markers"]!=0 or observed["oct22_natural_exit_markers"]!=0
        or observed["original_entry_markers"]!=47 or observed["original_exit_markers"]!=47
        or observed["trusted_oct22_archive_gzip_sha256"]!=OCT22_SHA):
        raise ValueError("oct22_last_closed_flat_state_not_independently_pinned")
    doc,digest=verified_json(shadow)
    if (doc.get("schema")!="nexus.mr40.spot_archive_forward_shadow.results.v1" or
        doc.get("source_frozen_4h_sha256")!=ROWS_SHA or
        doc.get("bridge_digest")!=EXPECTED_BRIDGE or
        doc.get("oct22_independently_verified_archive_reused") is not True or
        doc.get("oct22_proof_is_required_not_optional") is not True or
        doc.get("oct22_archive_was_never_overwritten") is not True or
        doc.get("observation_fixed_full_utc_day")!=FIXED_SHADOW_DAY or
        doc.get("forward_day_observations_are_not_live_execution_signals") is not True or
        doc.get("market_close_vs_source_observed_at_distinct") is not True or
        doc.get("real_orders")!=0 or doc.get("paper_modified") is not False or
        doc.get("private_api") is not False or doc.get("promote") is not False or
        doc.get("live") is not False):
        raise ValueError("future_official_shadow_not_authentic_and_safe")
    receipts=doc["source_public_spot_archives"]
    if len(receipts)!=2 or receipts[0].get("gzip_sha256")!=OCT22_SHA:
        raise ValueError("invalid_prior_official_archive_sha_chain")
    ref=receipts[1]
    receipt_ms=ref["received_ms"]
    if (type(receipt_ms) is not int or receipt_ms<NOT_BEFORE or
        receipt_ms>clock_ms or receipt_ms!=doc["archive_source_first_observed_ms"] or
        ref["url"]!=BASE_URL+FIXED_SHADOW_DAY+".csv.gz"):
        raise ValueError("impossible_archive_receipt_or_source_day")
    raw=archive.read_bytes()
    if (len(raw)<100000 or len(raw)>12_000_000 or
        len(raw)!=ref["bytes"] or
        hashlib.sha256(raw).hexdigest()!=ref["gzip_sha256"]):
        raise ValueError("oct23_official_spot_raw_archive_SHA_or_length_drift")
    csv=gzip.decompress(raw)
    if hashlib.sha256(csv).hexdigest()!=ref["csv_sha256"]:
        raise ValueError("oct23_decoded_trade_CSV_SHA_drift")
    rows,detail=rollup(csv,FIXED_SHADOW_DAY)
    if (len(rows)!=6 or detail["minutes_verified"]!=1440 or
        detail["four_hour_candles_verified"]!=6 or
        rows!=doc["forward_closed_market_4h_rows"]):
        raise ValueError("oct23_official_public_trades_do_not_match_shadow_day_4h")
    markers=doc["locked_forward_4h_signals"]
    if len(markers)!=6:
        raise ValueError("not_six_fixed_future_signal_markers")
    for j,(bar,m) in enumerate(zip(rows,markers)):
        first=epoch(FIXED_SHADOW_DAY)+j*STEP4
        if (bar[0]!=first or
            m.get("four_hour_open_utc")!=utc(first) or
            m.get("four_hour_end_utc")!=utc(first+STEP4) or
            m.get("market_bar_close_ms")!=first+STEP4 or
            m.get("source_first_available_to_this_replay_ms")!=receipt_ms or
            m.get("signal_not_authorized_for_live_or_paper") is not True or
            m.get("realtime_decision_available_at_original_bar_close") is not False or
            m.get("entry_or_exit_fill_observed") is not False or
            type(m.get("first_entry_close_marker")) is not bool or
            type(m.get("natural_exit_close_marker")) is not bool or
            m["first_entry_close_marker"] and m["natural_exit_close_marker"]):
            raise ValueError("future_bar_clock_or_marker_integrity_failed")
    return locked_bytes,rows,markers,ref,digest,obs_digest

def drawdown_pct(previous_peak,low_equity):
    if previous_peak<=0 or low_equity<0:
        raise ValueError("unsafe_quote_reference_equity")
    return max(D(0),(D(1)-low_equity/previous_peak)*D(100))

def compute_day(rows,markers):
    """No transaction: next-OPEN natural long reference, with user Paper untouched.

    The price LOW during any held candle is adverse observation only, not a
    stop fill. Entry/exit markers arise from the preceding completed 4h close.
    """
    if len(rows)!=6 or len(markers)!=6:
        raise ValueError("six_day_bars_required")
    quote=Q0;btc=D(0);entry_px=None;entry_before=None
    pending=None;armed=False;held_bars=0;closed=0
    hist_peak=Q0;high_first_peak=Q0
    max_low_dd=D(0);max_adversarial_samebar_dd=D(0);max_adverse=D(0)
    pending_breaches={str(t):None for t in LIMITS}
    day=[]
    for j,(bar,mark) in enumerate(zip(rows,markers)):
        ts,op,high,low,cl,volume=bar
        when=epoch(FIXED_SHADOW_DAY)+j*STEP4
        if ts!=when:raise ValueError("unverified_4h_bar_calendar")
        op,high,low,cl,volume=map(lambda x:D(str(x)),(op,high,low,cl,volume))
        if (not all(x.is_finite() for x in (op,high,low,cl,volume)) or
            min(op,high,low,cl)<=0 or volume<0 or
            low>min(op,cl) or high<max(op,cl)):
            raise ValueError("invalid_ohlcv_for_risk_meter")
        action=None
        if pending=="exit":
            if btc<=0 or entry_px is None:raise ValueError("exit_without_position")
            quote=btc*op*(D(1)-FEE);btc=D(0)
            action="NATURAL_EXIT_NEXT_OPEN_REFERENCE_ONLY"
            closed+=1;entry_px=None;entry_before=None;armed=False
            hist_peak=max(hist_peak,quote)
            high_first_peak=max(high_first_peak,quote)
            max_low_dd=max(max_low_dd,drawdown_pct(hist_peak,quote))
            max_adversarial_samebar_dd=max(
                max_adversarial_samebar_dd,drawdown_pct(high_first_peak,quote))
        elif pending=="entry":
            if btc!=0 or entry_px is not None:raise ValueError("duplicate_entry")
            entry_before=quote;btc=quote*(D(1)-FEE)/op
            quote=D(0);entry_px=op;armed=False;held_bars=0
            action="ENTRY_NEXT_OPEN_REFERENCE_ONLY"
        pending=None
        start_armed=armed
        adverse=None;low_quote_equity=None;close_liquidation_equity=None
        if btc>0:
            held_bars+=1
            adverse=max(D(0),(D(1)-low/entry_px)*D(100))
            max_adverse=max(max_adverse,adverse)
            low_quote_equity=btc*low*(D(1)-FEE)
            close_liquidation_equity=btc*cl*(D(1)-FEE)
            high_quote_equity=btc*high*(D(1)-FEE)
            # Prior completed-candle HIGH is known to precede the current
            # candle's LOW; same-bar HIGH/LOW order remains unknowable.
            max_low_dd=max(max_low_dd,drawdown_pct(hist_peak,low_quote_equity))
            high_first_peak=max(high_first_peak,high_quote_equity)
            max_adversarial_samebar_dd=max(
                max_adversarial_samebar_dd,
                drawdown_pct(high_first_peak,low_quote_equity))
            hist_peak=max(hist_peak,high_quote_equity)
            # An adverse LOW during a candle that arms only at its CLOSE is
            # still strictly PRE-arm: the low is before the close.
            if not start_armed:
                for level in LIMITS:
                    if adverse>=level and pending_breaches[str(level)] is None:
                        pending_breaches[str(level)]={
                            "first_candle_open_utc":utc(ts),
                            "age_hours_from_entry_bar_start":4*(held_bars-1),
                            "no_execution_or_exact_intrabar_touch_time":True
                        }
                # At close it MAY become armed for future candles, never
                # retroactively move a stop inside the same 4h candle.
                if cl>=entry_px*ARM:
                    armed=True
        ent=mark["first_entry_close_marker"]
        ex=mark["natural_exit_close_marker"]
        # Exact mutually exclusive closed MR40 transitions; arm never makes
        # a new order or changes the natural, precommitted exit.
        if ent:
            if btc>0 or pending is not None:
                raise ValueError("duplicate_entry_close_or_invalid_state")
            pending="entry"
        if ex:
            if btc<=0 or pending is not None:
                raise ValueError("exit_close_without_position")
            pending="exit"
        day.append({
            "bar_start_utc":utc(ts),
            "bar_close_utc":utc(ts+STEP4),
            "reference_action_at_open":action,
            "entry_signal_seen_only_after_this_close":ent,
            "natural_exit_signal_seen_only_after_this_close":ex,
            "reference_open_long_during_bar":btc>0,
            "entry_open_reference_price":str(entry_px) if entry_px is not None else None,
            "arm_two_pct_completed_CLOSE_already_on_at_bar_OPEN":start_armed,
            "arm_two_pct_at_this_bar_CLOSE_for_future_bars":armed,
            "unrealized_adverse_low_pct":str(adverse) if adverse is not None else None,
            "hypothetical_500_quote_liquidation_at_low_after_fees":str(low_quote_equity) if low_quote_equity is not None else None,
            "hypothetical_500_quote_liquidation_at_close_after_fees":str(close_liquidation_equity) if close_liquidation_equity is not None else None,
            "no_intrabar_stop_fill_implied":True
        })
    return {
        "fixed_day_4h_rows":6,
        "reference_initial_capital_usdt":"500",
        "public_VIP0_fee_per_side":"0.001",
        "natural_exit_completed_positions_with_both_next_open_proxies":closed,
        "closed_positions_reference_quote_equity_if_flat_usdt":str(quote) if btc==0 else None,
        "realized_net_PnL_only_for_completed_positions_usdt":str(quote-Q0) if btc==0 and closed else None,
        "realized_net_PnL_not_available_for_unclosed_position":btc!=0,
        "an_open_position_at_day_end":btc>0,
        "entry_or_exit_next_open_outside_day_unresolved":pending,
        "fixed_day_max_held_bar_adverse_price_MAE_pct":str(max_adverse) if any(x["reference_open_long_during_bar"] for x in day) else None,
        "fixed_day_OHLC_prior_high_to_current_low_minimum_drawdown_pct":str(max_low_dd) if any(x["reference_open_long_during_bar"] for x in day) else None,
        "fixed_day_adversarial_same_bar_high_before_low_drawdown_upper_pct":str(max_adversarial_samebar_dd) if any(x["reference_open_long_during_bar"] for x in day) else None,
        "first_prearm_adverse_LOW_5_and_10_pct":pending_breaches,
        "reference_prices_are_not_executable_fills":True,
        "no_profit_protection_order_created":True,
        "per_closed_fourhour_bar":day
    }

def run(protocol,shadow,oct22,archive,output,now_ms=None):
    if output.exists():raise ValueError("never_overwrite_prospective_risk_telemetry")
    now=int(time.time()*1000) if now_ms is None else now_ms
    protocol_raw,rows,markers,meta,source_digest,history_digest=validate_inputs(
        protocol,shadow,oct22,archive,now)
    x=compute_day(rows,markers)
    doc={
      "schema":"nexus.mr40.fixed_2026oct23_postday_prearm_risk_telemetry.results.v1",
      "protocol_sha256":hashlib.sha256(protocol_raw).hexdigest(),
      "shadow_report_logical_digest":source_digest,
      "oct22_historical_close_state_digest":history_digest,
      "archive_oct23_gzip_sha256":meta["gzip_sha256"],
      "source_first_observed_utc":utc(meta["received_ms"]),
      "classification":"ONE_FUTURE_DAY_POST_ARCHIVE_RESEARCH_NOT_LIVE_ASOF_CLOSE_OR_FILL",
      "no_counterfactual_stop_RR_or_sizing_policy_tested":True,
      "risk_budget_approved":False,
      "no_economic_improvement_claim":True,
      **x,
      "orders":0,"private_API":False,"paper_500_untouched":True,
      "live":False,"promote":False,"merge":False
    }
    doc["digest"]=hashlib.sha256(canon(doc)).hexdigest()
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open("x",encoding="utf8") as f:
        f.write(json.dumps(doc,ensure_ascii=False,sort_keys=True,indent=2)+"\n")
    print(json.dumps({"digest":doc["digest"],
        "closed_positions":x["natural_exit_completed_positions_with_both_next_open_proxies"],
        "reference_realized_net_PnL":x["realized_net_PnL_only_for_completed_positions_usdt"],
        "historical_low_drawdown_lower_bound_pct":x["fixed_day_OHLC_prior_high_to_current_low_minimum_drawdown_pct"],
        "incomplete":x["an_open_position_at_day_end"],
        "signals_not_fills":True},ensure_ascii=False))

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    for key in ("protocol","shadow","oct22","archive","output"):
        parser.add_argument("--"+key,type=Path,required=True)
    run(**vars(parser.parse_args()))
