"""Research-only Oct22 historical MR40 closed-signal continuity from VERIFIED public Spot ticks.

Already-seen historical bridge, never a forward fill or strategy-edge test.
No REST private API, order, Paper/Live write, stop optimizer or time scheduling.
"""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
from datetime import datetime,timezone
from research.nexus_mr40_independent_closed_signal_v1 import ClosedMR40,frozen_rows,canon,ROWS_SHA,STEP
from research.nexus_mr40_bybit_archive_bridge_v1 import epoch
from research.nexus_mr40_bybit_forward_shadow_v1 import (
    validate_bridge,reuse_oct22_only_if_archive_ws_parity_proven,
    EXPECTED_BRIDGE,EXPECTED_BRIDGE_ROWS)
from research.nexus_mr40_oct22_tick_vs_ws_reconcile_v1 import WS_SHA

SCHEMA="nexus.mr40.authenticated_oct22_historical_closed_signal_state_protocol.v1"
ARCHIVE_SHA="9591b0ccf534810939771e59ec95d6dbab4f978a72c57f86b2b332ef4cb84587"
REPORT_SHA="ea5f020264cb3e307bc142f22a9736c8c5afdd5df16fa9615927f887384c099c"
AUDIT_DIGEST="59c037de00de8af3b403ea1ca069fe2362d658a71bc428ecae6895b0fe7bc380"
COUNT_ORIGINAL=8514
COUNT_BRIDGE=12
COUNT_NEW_DAY=6

def utc(ms):
    return datetime.fromtimestamp(ms/1000,timezone.utc).isoformat()

def verify_lock(p):
    x=p["sources"]
    c=p["signal_contract"]
    s=p["safety"]
    if (p.get("schema")!=SCHEMA or
        x["original_4h_count"]!=COUNT_ORIGINAL or
        x["original_4h_digest"]!=ROWS_SHA or
        x["original_closed_entry_count"]!=47 or
        x["original_closed_exit_count"]!=47 or
        x["bridge_4h_count"]!=COUNT_BRIDGE or
        x["bridge_logical_digest"]!=EXPECTED_BRIDGE or
        x["bridge_12_rows_digest"]!=EXPECTED_BRIDGE_ROWS or
        x["oct22_day"]!="2026-10-22" or
        x["oct22_4h_count"]!=COUNT_NEW_DAY or
        x["verified_oct22_independent_spot_archive_gzip_sha256"]!=ARCHIVE_SHA or
        x["verified_oct22_public_tick_WS_parity_report_sha256"]!=REPORT_SHA or
        x["verified_oct22_public_tick_WS_parity_logical_digest"]!=AUDIT_DIGEST or
        x["original_native_confirmed_49_frame_WS_sha256"]!=WS_SHA or
        c["entry_z_lte"]!="-2" or c["natural_exit_z_gte"]!="0" or
        c["episode_first_momentum30"]!="close[j]>=close[j-180]" or
        c["lookback_40_prior_closed_candles"] is not True or
        c["match_bridge_12_signal_states"] is not True or
        c["output_six_historical_oct22_closed_bar_states"] is not True or
        s["orders"]!=0 or s["promote"] is not False or
        s["live"] is not False or s["not_future_OOS"] is not True or
        s["paper_modified"] is not False or s["refuse_overwrite"] is not True):
        raise ValueError("historical_six_bar_source_and_strategy_lock_drift")

def verified_inputs(protocol,old_market_dir,bridge_file,archive_file,parity_file):
    p_bytes=protocol.read_bytes()
    verify_lock(json.loads(p_bytes))
    report_bytes=parity_file.read_bytes()
    if hashlib.sha256(report_bytes).hexdigest()!=REPORT_SHA:
        raise ValueError("oct22_crossvenue_source_proof_file_SHA_changed")
    archived=archive_file.read_bytes()
    if hashlib.sha256(archived).hexdigest()!=ARCHIVE_SHA:
        raise ValueError("oct22_immutable_trade_archive_SHA_changed")
    # This function reconstitutes the full 1440-minute trade archive
    # and checks its full SHA, native live 4h parity and receipt time.
    rows22,info=reuse_oct22_only_if_archive_ws_parity_proven(archive_file,parity_file)
    if (len(rows22)!=COUNT_NEW_DAY or
        info["oct22_prior_verified_live_WS_same_venue_parity_digest"]!=AUDIT_DIGEST or
        info["oct22_reused_without_re_download"] is not True):
        raise ValueError("oct22_public_official_trade_source_not_independently_verified")
    original=frozen_rows(old_market_dir)
    if len(original)!=COUNT_ORIGINAL:
        raise ValueError("pinned_8514_row_prefix_changed")
    prior=json.loads(bridge_file.read_bytes())
    bridge=validate_bridge(prior)
    if len(bridge)!=COUNT_BRIDGE or not prior.get("bridge_source_integrity_gate_pass"):
        raise ValueError("fixed_oct20_oct21_bridge_not_verified")
    whole=original+bridge+rows22
    if len(whole)!=COUNT_ORIGINAL+COUNT_BRIDGE+COUNT_NEW_DAY:
        raise ValueError("historical_source_length_drift")
    if whole[COUNT_BRIDGE+COUNT_ORIGINAL][0]!=epoch("2026-10-22"):
        raise ValueError("pinned_oct22_start_not_connected")
    for i in range(1,len(whole)):
        if whole[i][0]!=whole[i-1][0]+STEP:
            raise ValueError("source_4h_bar_time_gap_at_"+str(i))
    return p_bytes,original,bridge,prior,rows22,info

def compute(original,bridge,previous_bridge_report,day,observed_received_utc):
    if len(original)!=8514 or len(bridge)!=12 or len(day)!=6:
        raise ValueError("required_full_contiguous_history")
    historical=previous_bridge_report["new_asof_signal_descriptions"]
    if len(historical)!=12:
        raise ValueError("pinned_bridge_12_signals_missing")
    engine=ClosedMR40()
    entry_count=exit_count=0
    previous_signal=None
    six=[]
    for i,row in enumerate(original+bridge+day):
        signal=engine.feed(row,confirmed=True,source_verified=True)
        if i<8514:
            entry_count+=int(signal.first_entry_close)
            exit_count+=int(signal.natural_exit_close)
        elif i<8514+12:
            idx=i-8514
            prior=historical[idx]
            expected={
                "bar_start_ms":signal.start_ms,
                "z_score_as_of_this_confirmed_close":signal.z_score,
                "raw_active":signal.raw_active,
                "momentum_episode_admitted":signal.episode_admitted,
                "closed_signal_target":signal.final_target,
                "first_entry_signal_at_close":signal.first_entry_close,
                "natural_exit_signal_at_close":signal.natural_exit_close,
                "potential_next_open_ms":signal.start_ms+STEP,
            }
            for key,value in expected.items():
                if prior[key]!=value:
                    raise ValueError("oct20_oct21_frozen_bridge_signal_state_changed_"+str(idx)+"_"+key)
            previous_signal=signal
        else:
            j=i-(8514+12)
            if row[0]!=epoch("2026-10-22")+j*STEP:
                raise ValueError("oct22_six_complete_bar_starts_changed")
            six.append({
                "bar_start_utc":utc(signal.start_ms),
                "market_bar_close_utc":utc(signal.start_ms+STEP),
                "market_bar_start_ms":signal.start_ms,
                "source_verified_spot_archive":True,
                "z_score_of_closed_fourhour_bar":signal.z_score,
                "raw_MR40_active":signal.raw_active,
                "momentum30_episode_admitted":signal.episode_admitted,
                "target_long_after_closed_bar":signal.final_target,
                "first_new_long_entry_marker_at_close":signal.first_entry_close,
                "natural_long_exit_marker_at_close":signal.natural_exit_close,
                "historical_post_day_archive_first_available_utc":observed_received_utc,
                "historical_signal_not_observed_live_at_bar_close":True,
                "historical_next_open_is_not_a_verified_fill":True,
                "private_api":False,"orders":0
            })
    if (entry_count,exit_count)!=(47,47) or engine.suspended:
        raise ValueError("immutable_47_47_prefix_not_reproduced")
    if len(six)!=6 or previous_signal is None:
        raise ValueError("oct22_six_closed_state_rows_missing")
    return {
        "original_entry_markers":entry_count,"original_exit_markers":exit_count,
        "pinned_oct20_oct21_bridge_state_checks":12,
        "prior_bridge_last_state_target_long":previous_signal.final_target,
        "oct22_first_entry_markers":sum(bool(x["first_new_long_entry_marker_at_close"]) for x in six),
        "oct22_natural_exit_markers":sum(bool(x["natural_long_exit_marker_at_close"]) for x in six),
        "oct22_last_closed_target_long":six[-1]["target_long_after_closed_bar"],
        "oct22_last_closed_z":six[-1]["z_score_of_closed_fourhour_bar"],
        "oct22_six_bar_markers":six,
    }

def run(protocol,old_market_dir,bridge_file,archive_file,parity_file,out):
    if out.exists():
        raise ValueError("never_overwrite_historical_source_signal_audit")
    lock,old,bridge,report,day,meta=verified_inputs(
        protocol,old_market_dir,bridge_file,archive_file,parity_file)
    state=compute(old,bridge,report,day,meta["utc_received"])
    audit={
        "schema":"nexus.mr40.authenticated_oct22_spot_historical_close_state.results.v1",
        "classification":"RETROSPECTIVE_PUBLISHED_ARCHIVE_AFTER_BAR_CLOSE_NOT_BLIND_FORWARD_NOT_A_FILL",
        "protocol_file_sha256":hashlib.sha256(lock).hexdigest(),
        "historical_8514_4h_digest":ROWS_SHA,
        "original_12_bar_bridge_digest":EXPECTED_BRIDGE,
        "trusted_oct22_archive_gzip_sha256":ARCHIVE_SHA,
        "trusted_independent_spot_ws_parity_report_sha256":REPORT_SHA,
        "original_source_received_utc":meta["utc_received"],
        "twenty_four_hour_verified_bridge_bars":18,
        "historical_oct22_true_new_trade_data_source_verified":True,
        "separate_4h_live_decision_latency_proven_for_oct22_six":False,
        **state,
        "no_strategy_parameters_optimized":True,"no_profit_or_loss_labels":True,
        "source_receipt_is_after_six_market_close_events":True,
        "orders":0,"private_api":False,"paper_modified":False,
        "live":False,"promote":False,"merge":False,
    }
    audit["digest"]=hashlib.sha256(canon(audit)).hexdigest()
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open("x",encoding="utf8") as f:
        f.write(json.dumps(audit,ensure_ascii=False,sort_keys=True,indent=2)+"\n")
    print(json.dumps({
        "digest":audit["digest"],
        "original_markers":[state["original_entry_markers"],state["original_exit_markers"]],
        "pinned_bridge_12_states_pass":True,
        "oct22_entry_markers":state["oct22_first_entry_markers"],
        "oct22_exit_markers":state["oct22_natural_exit_markers"],
        "oct22_last_target_long":state["oct22_last_closed_target_long"],
        "oct22_last_z":state["oct22_last_closed_z"],
        "six":state["oct22_six_bar_markers"],
        "source_not_live_execution":True
    },ensure_ascii=False))

if __name__=="__main__":
    p=argparse.ArgumentParser()
    for x in ("protocol","old_market_dir","bridge_file","archive_file","parity_file","out"):
        p.add_argument("--"+x,required=True,type=Path)
    run(**vars(p.parse_args()))
