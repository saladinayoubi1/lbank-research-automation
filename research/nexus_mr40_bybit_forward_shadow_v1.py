"""Frozen future-only Bybit Spot MR40 SHADOW ARCHIVE, no order or paper hooks.

First observed full UTC day is FIXED at 2026-10-23. This module must
refuse any source download before 2026-10-24T00:00Z, and never self-schedule.
"""
from __future__ import annotations
import argparse,gzip,hashlib,json,time,urllib.request
from datetime import datetime,timezone
from pathlib import Path
from research.nexus_mr40_bybit_archive_bridge_v1 import (
    BASE_URL,MAX_BYTES,rollup,epoch,STEP4,canon)
from research.nexus_mr40_independent_closed_signal_v1 import ClosedMR40,frozen_rows

EXPECTED_BRIDGE="f118d0affe21995f4bfa01c1b5261eb7e963d1c1d46bfb094debf28a35c3114e"
EXPECTED_BRIDGE_ROWS="a3fe422736b0dd27342b711765e721608cb88f7ec49ef22b723d09b64acaf5a6"
EXPECTED_SOURCE="a458d9f83df633df8ee5cab5f2a19de41c4c79c61185b5abd258fdefa80d575a"
DAYS=("2026-10-22","2026-10-23")
NOT_BEFORE=epoch("2026-10-24")


def check_clock(now_ms):
    if now_ms<NOT_BEFORE:
        raise ValueError("future_full_day_not_finished_no_network")


def validate_bridge(bridge):
    if bridge.get("digest")!=EXPECTED_BRIDGE:
        raise ValueError("historical_bridge_logical_digest_modified")
    x=dict(bridge)
    claimed=x.pop("digest")
    if hashlib.sha256(canon(x)).hexdigest()!=claimed:
        raise ValueError("historical_bridge_payload_modified")
    rows=bridge["new_4h_rows_utc_day20_21"]
    if len(rows)!=12 or hashlib.sha256(canon(rows)).hexdigest()!=EXPECTED_BRIDGE_ROWS:
        raise ValueError("historical_bridge_row_hash_changed")
    if not bridge["bridge_source_integrity_gate_pass"]:
        raise ValueError("historical_bridge_failed")
    return rows


def get_archive(day):
    url=BASE_URL+day+".csv.gz"
    req=urllib.request.Request(url,headers={"User-Agent":"NEXUS-forward-shadow-research-only"})
    with urllib.request.urlopen(req,timeout=23) as response:
        if response.status!=200:raise ValueError("archive_not_http_200")
        raw=response.read(MAX_BYTES+1)
        modified=response.headers.get("Last-Modified")
    received=int(time.time()*1000)
    if len(raw)>MAX_BYTES or len(raw)<100000:
        raise ValueError("archive_missing_or_truncated")
    csv_raw=gzip.decompress(raw)
    rows,info=rollup(csv_raw,day)
    if len(rows)!=6:raise ValueError("not_six_completed_4h_bars")
    info.update({"utc_received":datetime.fromtimestamp(received/1000,timezone.utc).isoformat(),
                 "received_ms":received,"url":url,
                 "bytes":len(raw),"gzip_sha256":hashlib.sha256(raw).hexdigest(),
                 "csv_sha256":hashlib.sha256(csv_raw).hexdigest(),
                 "server_last_modified":modified})
    return rows,info,raw


def replay_no_orders(original,bridge,days):
    full=original+bridge+days
    if len(full)!=8514+12+12:raise ValueError("wrong_combined_history_length")
    first=original[0][0]
    for k,row in enumerate(full):
        if row[0]!=first+k*STEP4:raise ValueError("missing_4h_source_interval")
    engine=ClosedMR40()
    past_entry=0;past_exit=0;forward=[]
    for row in full:
        signal=engine.feed(row,confirmed=True,source_verified=True)
        if signal.bar_index<8514:
            past_entry+=signal.first_entry_close
            past_exit+=signal.natural_exit_close
        elif row[0]>=epoch("2026-10-23"):
            forward.append({
                "four_hour_open_utc":datetime.fromtimestamp(row[0]/1000,timezone.utc).isoformat(),
                "four_hour_end_utc":datetime.fromtimestamp((row[0]+STEP4)/1000,timezone.utc).isoformat(),
                "z_of_closed_bar":signal.z_score,
                "raw_active":signal.raw_active,
                "momentum_episode_admitted":signal.episode_admitted,
                "closed_target":signal.final_target,
                "first_entry_close_marker":signal.first_entry_close,
                "natural_exit_close_marker":signal.natural_exit_close,
                "marker_only_not_executable":True,
            })
    if (past_entry,past_exit)!=(47,47):
        raise ValueError("frozen_prefix_47_47_not_reproduced")
    if len(forward)!=6:raise ValueError("fixed_one_day_six_candles_not_reproduced")
    return forward,{"original_entries":past_entry,"original_exits":past_exit,
                    "locked_forward_day":"2026-10-23",
                    "new_future_first_entry_close_markers":sum(x["first_entry_close_marker"] for x in forward),
                    "new_future_natural_exit_close_markers":sum(x["natural_exit_close_marker"] for x in forward)}



def mark_archive_signals_as_delayed(markers,archive_received_ms):
    """Never mistake post-day FULL ARCHIVE computation for an online close event.

    Signals are market-clock-as-of in the indicator, but were *observed*
    only after the official daily file arrived, later than the 4h next open.
    This method never generates an executable signal or a pretend fill.
    """
    if (type(archive_received_ms) is not int or archive_received_ms<NOT_BEFORE
        or len(markers)!=6):
        raise ValueError("invalid_fixed_day_archive_receipt_or_bar_count")
    seen=[]
    for index,old in enumerate(markers):
        opening=epoch("2026-10-23")+index*STEP4
        closing=opening+STEP4
        if (old.get("four_hour_open_utc")!=datetime.fromtimestamp(opening/1000,timezone.utc).isoformat()
            or old.get("four_hour_end_utc")!=datetime.fromtimestamp(closing/1000,timezone.utc).isoformat()):
            raise ValueError("archive_signal_market_clock_modified")
        if archive_received_ms<closing:
            raise ValueError("cannot_receive_completed_4h_bar_before_close")
        item=dict(old)
        item.update({
            "market_bar_close_ms":closing,
            "source_first_available_to_this_replay_ms":archive_received_ms,
            "archive_receipt_lag_after_4h_close_ms":archive_received_ms-closing,
            "next_open_reference_ms":closing,
            "next_open_reference_already_past_at_receipt":archive_received_ms>closing,
            "source_kind":"PUBLIC_BYBIT_SPOT_DAILY_ARCHIVE_POST_DAY_END",
            "signal_calculation_is_retrospective_after_archive_release":True,
            "realtime_decision_available_at_original_bar_close":False,
            "signal_not_authorized_for_live_or_paper":True,
            "entry_or_exit_fill_observed":False,
        })
        seen.append(item)
    return seen


def run(protocol,source_dir,bridge_file,archive_dir,output):
    if output.exists():raise ValueError("refuse_overwrite_shadow_report")
    p=json.loads(protocol.read_bytes())
    if (p["schema"]!="nexus.mr40.prospective_spot_archive_shadow_protocol.v1"
        or p["fixed_observation_day"]!="2026-10-23"
        or p["prerequisites"]["historical_bridge_oct20_21_logical_digest"]!=EXPECTED_BRIDGE
        or p["constraints"]["orders"]!=0 or p["constraints"]["promote"] is not False):
        raise ValueError("frozen_forward_protocol_changed")
    # Absolutely no HTTP before date completion.
    now=int(time.time()*1000)
    check_clock(now)
    original=frozen_rows(source_dir)
    if len(original)!=8514 or original[-1][0]!=epoch("2026-10-19")+5*STEP4:
        raise ValueError("immutable_OHLC_prefix_missing")
    bridge=validate_bridge(json.loads(bridge_file.read_bytes()))
    all_days=[];receipts=[];source_blobs={}
    for day in DAYS:
        target=archive_dir/("Bybit_BTCUSDT_Spot_"+day+".csv.gz")
        if target.exists():raise ValueError("refuse_overwrite_future_archive")
        rows,metadata,raw=get_archive(day)
        source_blobs[day]=raw
        all_days+=rows
        receipts.append(metadata)
    for i,row in enumerate(bridge+all_days):
        if row[0]!=original[-1][0]+STEP4*(i+1):
            raise ValueError("historical_to_forward_calendar_gap")
    markers,counts=replay_no_orders(original,bridge,all_days)
    # Exact source-observation time is NOT the historical market-close time.
    # This is why an archival shadow marker can never be treated as a fill.
    receipt_ms=receipts[1]["received_ms"]
    markers=mark_archive_signals_as_delayed(markers,receipt_ms)
    doc={
        "schema":"nexus.mr40.spot_archive_forward_shadow.results.v1",
        "protocol_sha256":hashlib.sha256(protocol.read_bytes()).hexdigest(),
        "bridge_digest":EXPECTED_BRIDGE,
        "source_frozen_4h_sha256":EXPECTED_SOURCE,
        "source_public_spot_archives":receipts,
        "observation_fixed_full_utc_day":"2026-10-23",
        "data_source_receipt_after_day_end":now>=NOT_BEFORE,
        "forward_closed_market_4h_rows":all_days[6:],
        "locked_forward_4h_signals":markers,
        "clock_and_closed_signals":counts,
        "no_future_price_used_in_marker":True,
        "no_same_day_profit_labels":True,
        "source_is_archive_not_live_rest":True,
        "market_close_vs_source_observed_at_distinct":True,
        "archive_source_first_observed_ms":receipt_ms,
        "forward_day_observations_are_not_live_execution_signals":True,
        "real_time_close_decision_latency_tested":False,
        "not_a_verified_fill":True,
        "real_orders":0,"private_api":False,
        "paper_modified":False,"live":False,
        "promote":False,"merge":False
    }
    doc["digest"]=hashlib.sha256(canon(doc)).hexdigest()
    archive_dir.mkdir(parents=True,exist_ok=True)
    for day,raw in source_blobs.items():
        (archive_dir/("Bybit_BTCUSDT_Spot_"+day+".csv.gz")).write_bytes(raw)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(doc,sort_keys=True,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print(json.dumps({"digest":doc["digest"],"markers":counts},ensure_ascii=False))


if __name__=="__main__":
    a=argparse.ArgumentParser()
    for name in ("protocol","source_dir","bridge_file","archive_dir","output"):
        a.add_argument("--"+name,required=True,type=Path)
    run(**vars(a.parse_args()))
