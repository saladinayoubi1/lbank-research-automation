"""V115 historical FULL Elliott pipeline profile on PREINSPECTED Binance 1m.

Offline July 2024 only. Reopen all 28 official archives and V89 SHA source
receipts; never present this as Bybit, independent, out-of-sample, or PNL.
This benchmarks source re-read, V99 independent fine/coarse observers,
V107 full six-event census, V111 candidate->shared-cash replay and
V113 no-sampling causal event audit. Two symbols and both seven-day
halves are retained. No broker or HTTP access.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime,timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import csv
import io
import json
import platform
import sys
import time
import tracemalloc
import zipfile

from research.elliott_v90_frozen_replication import replicate_v90 as v90
from research.elliott_v99_causal_scale import scale_v99 as v99
from research.elliott_v100_scale_context import context_v100 as v100
from research.elliott_v102_bybit_intake import intake_v102 as v102
from research.elliott_v107_prefix_census import census_v107 as v107
from research.elliott_v108_forward_outcomes import outcomes_v108 as v108
from research.elliott_v111_source_capacity import bridge_v111 as v111
from research.elliott_v113_incremental_audit import incremental_v113 as v113
from research.elliott_v114_load_profile import profile_v114 as v114

SCHEMA="nexus.elliott-v115-preinspected-binance-full-pipeline-performance.v1"
V114_COMMIT="d4152cdf9e970ce69c1f0be2b09886a20e25e4f9"
V114_REL="docs/evidence/elliott-v114-synthetic-load-20261017/V114_FROZEN_LOAD_STRESS_RULEBOOK.json"
V114_SHA="563ce5201a17192b7fffc70d797d5f0cacc4b31000390cd3ce867b99356f02cc"
PREINSPECTED_SOURCE="BINANCE_SPOT_HISTORICAL_JULY_2024_NO_HOLDOUT"
SYMBOLS=("BTCUSDT","ETHUSDT")
MIN=60000
HALF=10080
FULL=20160
RESEARCH_ONLY=True
ORDER_ADAPTER=None
PAPER_ELIGIBLE=False
ENTRY_SIGNAL=False
LIVE_ENABLED=False
V52_UNCHANGED=True


def rules()->dict:
    return {
        "schema":SCHEMA,
        "stage":"FROZEN_HISTORICAL_PERFORMANCE_STUDY_NO_MARKET_VALIDATION",
        "previous_v114_commit":V114_COMMIT,
        "previous_v114_sha256":V114_SHA,
        "source_exchange":"BINANCE_SPOT_NOT_BYBIT",
        "source_period":"2024-07-01_to_2024-07-15_exclusive_UTC",
        "data_status":"REPEATEDLY_INSPECTED_NOT_INDEPENDENT_HOLDOUT",
        "source_authentication":"V89_28_OFFICIAL_ZIP_PLUS_CHECKSUM_RECEIPTS",
        "pairs":list(SYMBOLS),
        "full_original_1m_per_pair":FULL,
        "first_week_original_1m_per_pair":HALF,
        "two_scales_from_v99_without_tuning":True,
        "all_v107_windows_no_skips":True,
        "full_v111_cash_and_v113_stream_proof":True,
        "first_week_replay_matured_candidate_invariance":True,
        "benchmark_sections":["load_original_28_zip","full_V99_swings",
                              "full_V107_census_and_V111_portfolio",
                              "full_V113_causal_stream"],
        "times_are_one_laptop_single_runs_not_guarantees":True,
        "memory_is_windows_process_working_set_current_and_lifetime_peak":True,
        "no_python_tracemalloc_per_allocation_in_benchmark":True,
        "no_manual_wave_labeling_or_posthoc_threshold_tuning":True,
        "zero_bybit_future_market_candles":True,
        "zero_real_market_orders":True,
        "no_trading_return_or_pnl":True,
        "not_prospective_elliott_signal_validation":True,
        "no_code_paths_modify_v52_or_demo":True,
        "orders":0,"live_enabled":False,"paper_eligible":False,
        "entry_signal":False,"v52_unchanged":True,
    }


def freeze(path:Path)->dict:
    if not isinstance(path,Path):
        raise ValueError("explicit immutable scientific rulebook path required")
    from research.elliott_v93_recursive_proof import proof_v93 as v93
    parent=v93.immutable_receipt(V114_REL,V114_SHA,V114_COMMIT,v114.SCHEMA)
    if (parent["orders"]!=0 or parent["no_bybit_market_ohlc_read"] is not True
        or parent["benchmark_is_journal_only_not_full_v99_v107_source_scaling"] is not True):
        raise ValueError("original V114 predecessor or research gate changed")
    raw=(json.dumps(rules(),sort_keys=True,indent=2)+"\n").encode()
    if path.exists():
        if path.read_bytes()!=raw:
            raise ValueError("V115 RULEBOOK IMMUTABILITY BREACH")
    else:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(raw)
    return {"status":"V115_LOCKED_PREINSPECTED_ONLY",
            "sha256":sha256(raw).hexdigest(),"orders":0}


def historical_seven_fields(symbol:str,locked:dict,receipt:dict)->list[v102.Candle]:
    """Independent seven-column crosscheck of V99/V90's verified closes.

    Here V102.Candle is just a typed OHLC container; Binance source is
    explicitly labeled and never routed through V102 future Bybit intake.
    """
    if symbol not in SYMBOLS:
        raise ValueError("only original preinspected source pairs")
    pinned=v99.load_verified_closes(symbol,locked,receipt)
    original_highlow=v90._parse_verified_source(symbol,locked,receipt)
    expected=[a for a in locked["scheduled_inputs"] if a["symbol"]==symbol]
    trusted={x["name"]:x for x in receipt["archives"]}
    if len(expected)!=14:
        raise ValueError("not all original 14 daily ZIPs")
    candles=[]
    for item in expected:
        raw=(v90.v89.BASE/item["zip_file"]).read_bytes()
        check=(v90.v89.BASE/item["official_checksum_file"]).read_bytes()
        witness=v90.v89.verify_archive(item,raw,check)
        if any(witness.get(k)!=v for k,v in trusted[item["zip_file"]].items()
               if k in witness):
            raise ValueError("original official Binance source receipt changed")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            lines=archive.read(item["csv_member"]).decode("utf-8-sig")
        for row in csv.reader(io.StringIO(lines)):
            if len(row)!=12:
                raise ValueError("original official Binance 12-field 1m row changed")
            fields=[v90.v89.strict_decimal(row[i]) for i in (1,2,3,4,5,7)]
            ms=int(row[0])
            idx=len(candles)
            if (int(row[6])!=ms+59999 or idx>=len(pinned)
                or ms!=pinned[idx].ms
                or fields[3]!=pinned[idx].close
                or fields[1]!=original_highlow[idx].high
                or fields[2]!=original_highlow[idx].low):
                raise ValueError("original Binance complete OHLC does not match two older auditors")
            candles.append(v102.Candle(ms,*fields))
    if (len(candles)!=FULL or
        v108.validate_physical_candles(candles)!=(v90.START_MS,v90.END_MS)):
        raise ValueError("full preinspected seven-field source is incomplete")
    return candles


def as_source_streams(candles_by_symbol:dict[str,list[v102.Candle]]
                      )->dict[str,tuple[list[v99.ObservedSwing],
                                        list[v99.ObservedSwing],list[v102.Candle]]]:
    if type(candles_by_symbol) is not dict or (
        set(candles_by_symbol)!=set(SYMBOLS)):
        raise ValueError("complete original two-symbol OHLC source required")
    streams={}
    for symbol in SYMBOLS:
        bars=candles_by_symbol[symbol]
        if len(bars)<64:
            raise ValueError("original full-minute warmup required")
        start,end=v108.validate_physical_candles(bars)
        closes=[v99.CloseMinute(c.ms,c.close) for c in bars]
        fine=v99.observe_scale(closes,v99.TRAILING_MEDIAN_MULTIPLIERS[0],end)
        coarse=v99.observe_scale(closes,v99.TRAILING_MEDIAN_MULTIPLIERS[1],end)
        if any(e.confirmed_ms>end for e in fine+coarse):
            raise ValueError("future swing is not yet closed")
        streams[symbol]=(coarse,fine,bars)
    return streams


def bounded_summary(out:dict)->dict:
    original=out["cash_capacity_v110"]
    statuses=Counter(x["reference_screen_status"] for x in out[
        "all_original_candidate_reference_screens"])
    prefix=original["append_only_causal_event_ledger"]
    return {
        "all_original_six_coarse_windows":out["all_v107_candidate_windows"],
        "all_reference_abstentions":out["all_source_reference_abstentions"],
        "all_hypothetical_source_proposals":out["all_source_reference_proposals"],
        "reference_screen_counts":dict(sorted(statuses.items())),
        "cash_candidate_admitted_count":original["admitted_hypothetical_intents"],
        "cash_candidate_denied_count":original["denied_hypothetical_intents"],
        "known_later_barrier_release_count":original["known_resolutions_count"],
        "cash_journal_events":len(prefix),
        "end_reserved_cash_usdt":original["reserved_usdt"],
        "end_reserved_gapless_risk_usdt":original[
            "stressed_gapless_risk_reserve_usdt"],
        "cash_journal_sha256":sha256(json.dumps(
            prefix,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
        "orders":0,"real_pnl":None,
    }


def _mature_only_compare(a:dict,b:dict,week_end:int)->dict:
    """Compare identical older decisions after original reference is mature."""
    aa={ (r["symbol"],r["original_v107_ordinal"]):r
         for r in a["all_original_candidate_reference_screens"]
         if r["original_v107_decision_asof_ms"]+2*MIN<=week_end}
    bb={ (r["symbol"],r["original_v107_ordinal"]):r
         for r in b["all_original_candidate_reference_screens"]
         if r["original_v107_decision_asof_ms"]+2*MIN<=week_end}
    if aa!=bb:
        raise ValueError("LATER_2024_BARS_REVISED_MATURE_FIRST_WEEK_DECISIONS")
    return {"original_mature_first_week_candidates":len(aa),
            "all_first_week_mature_screens_unchanged":True}



def _stage(name:str,started_ns:int)->None:
    """Transient QA progress only, not a research outcome or market result."""
    import tempfile
    temp=Path(tempfile.gettempdir())/"V115_FULL_PIPELINE_STAGE.json"
    item={"stage":name,"elapsed_walltime_s":round(
        (time.perf_counter_ns()-started_ns)/1_000_000_000,3)}
    temp.write_text(json.dumps(item,sort_keys=True)+"\n",encoding="utf-8")


def _windows_working_set()->tuple[int,int]:
    """Windows own current / process-lifetime peak working-set bytes.

    No Python allocation tracer. This counter is not a GPU/system-memory
    measurement; peak includes Python interpreter startup/import costs.
    """
    import ctypes
    class Counters(ctypes.Structure):
        _fields_=[
            ("cb",ctypes.c_ulong),
            ("PageFaultCount",ctypes.c_ulong),
            ("PeakWorkingSetSize",ctypes.c_size_t),
            ("WorkingSetSize",ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage",ctypes.c_size_t),
            ("QuotaPagedPoolUsage",ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage",ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage",ctypes.c_size_t),
            ("PagefileUsage",ctypes.c_size_t),
            ("PeakPagefileUsage",ctypes.c_size_t),
        ]
    data=Counters()
    data.cb=ctypes.sizeof(data)
    kernel=ctypes.windll.kernel32
    psapi=ctypes.windll.psapi
    kernel.GetCurrentProcess.restype=ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes=[
        ctypes.c_void_p,ctypes.c_void_p,ctypes.c_ulong]
    psapi.GetProcessMemoryInfo.restype=ctypes.c_int
    if psapi.GetProcessMemoryInfo(
            kernel.GetCurrentProcess(),ctypes.byref(data),data.cb)!=1:
        raise ValueError("Windows process working-set measurement failed")
    return int(data.WorkingSetSize),int(data.PeakWorkingSetSize)


def profile_inspected_historical()->dict:
    """One measured full-source study; not a financial backtest."""
    # Do not enable allocation tracing over millions of original
    # V107 fine/coarse source checks: it measures the tracer, not the
    # uninstrumented pipeline. Query Windows' PROCESS_MEMORY_COUNTERS.
    begin=time.perf_counter_ns()
    locked,receipt=v90.verify_locked_receipts()
    physical={s:historical_seven_fields(s,locked,receipt) for s in SYMBOLS}
    loaded=time.perf_counter_ns()
    _stage("validated_original_archives_and_7field_rows",begin)
    full=as_source_streams(physical)
    swung=time.perf_counter_ns()
    _stage("full_causal_fine_and_coarse_observed",begin)
    full_result=v111.portfolio_census_from_source_streams(full)
    cash_done=time.perf_counter_ns()
    _stage("all_original_v107_v111_candidate_screens_accounted",begin)
    full_proof=v113.audit_streaming(full,full_result)
    audited=time.perf_counter_ns()
    _stage("full_original_v113_incremental_proof_verified",begin)
    first={s:physical[s][:HALF] for s in SYMBOLS}
    first_streams=as_source_streams(first)
    first_result=v111.portfolio_census_from_source_streams(first_streams)
    first_done=time.perf_counter_ns()
    _stage("first_week_source_comparison_recomputed",begin)
    sample_maturity=_mature_only_compare(first_result,full_result,first[
        SYMBOLS[0]][-1].ms+MIN)
    current_working_set,peak_working_set=_windows_working_set()
    by_symbol={
        s:{"original_closed_1m_bars":len(full[s][2]),
           "fine_confirmed":len(full[s][1]),
           "coarse_confirmed":len(full[s][0]),
           "all_coarse_candidate_windows":max(0,len(full[s][0])-5),
           "fine_SHA256":v100.digest_events(full[s][1]),
           "coarse_SHA256":v100.digest_events(full[s][0])}
        for s in SYMBOLS
    }
    if (full_proof["all_original_candidate_windows"]!=full_result[
        "all_v107_candidate_windows"] or
        full_proof["final_v111_event_log_digest"]!=bounded_summary(full_result)[
        "cash_journal_sha256"]):
        raise ValueError("full preinspected candidate/ledger audit mismatch")
    return {
        "schema":SCHEMA,
        "data_source":PREINSPECTED_SOURCE,
        "source_period":"2024-07-01-to-2024-07-15-exclusive-UTC",
        "not_independent_holdout":True,
        "not_bybit_spot_or_market_execution":True,
        "historical_archive_count":28,
        "original_1m_candles_total":FULL*len(SYMBOLS),
        "original_official_archive_receipt_sha256":v90.SOURCE_RECEIPT_SHA,
        "python_version":sys.version.split()[0],
        "laptop2_os":platform.platform(),
        "by_symbol_source_events":by_symbol,
        "full_two_week_source_to_capacity":bounded_summary(full_result),
        "first_week_source_to_capacity":bounded_summary(first_result),
        "first_week_causal_invariance":sample_maturity,
        "full_source_stream_proof":{
            "mandatory_timing_checkpoints":full_proof[
                "all_mandatory_causal_checkpoints"],
            "no_checkpoint_silently_dropped":full_proof["no_checkpoint_omitted"],
            "original_causal_candidates":full_proof[
                "all_original_candidate_windows"],
            "cash_events":full_proof["final_portfolio_event_count"],
            "event_digest":full_proof["final_v111_event_log_digest"],
        },
        "measured_single_run_ms":{
            "original_archives_receipt_and_7field_reopen":round(
                (loaded-begin)/1_000_000,3),
            "original_full_v99_two_scales":round((swung-loaded)/1_000_000,3),
            "original_full_v107_v111_source_to_capacity":round(
                (cash_done-swung)/1_000_000,3),
            "original_full_v113_incremental_causal_audit":round(
                (audited-cash_done)/1_000_000,3),
            "first_week_source_to_portfolio_extra_study":round(
                (first_done-audited)/1_000_000,3),
            "all_study_walltime":round((first_done-begin)/1_000_000,3),
        },
        "windows_process_peak_working_set_mib":round(peak_working_set/1024**2,3),
        "windows_process_current_working_set_mib":round(current_working_set/1024**2,3),
        "measurement_does_not_use_python_tracemalloc":True,
        "market_profitability_certified":False,
        "elliott_degree_certificates":0,
        "original_market_was_already_researched":True,
        "unmodified_demo_v52":True,
        "live_enabled":False,"paper_eligible":False,
        "orders":0,"real_net_pnl":None,
    }


def write_once(path:Path)->dict:
    if not isinstance(path,Path):
        raise ValueError("explicit original measured evidence Path required")
    result=profile_inspected_historical()
    raw=(json.dumps(result,sort_keys=True,indent=2)+"\n").encode()
    if path.exists():
        if path.read_bytes()!=raw:
            raise ValueError("PREINSPECTED_MEASURED_EVIDENCE_MUST_NEVER_BE_OVERWRITTEN")
    else:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(raw)
    return {"status":"V115_INSPECTED_OLD_DATA_PERFORMANCE_PROFILE_COMPLETE",
            "sha256":sha256(raw).hexdigest(),
            "candidate_windows":result["full_two_week_source_to_capacity"][
                "all_original_six_coarse_windows"],
            "no_order":True}


if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--mode",choices=("status","bench"),default="status")
    p.add_argument("--out",type=Path)
    a=p.parse_args()
    if a.mode=="status":
        print(json.dumps({"schema":SCHEMA,"source":"PREINSPECTED_ONLY",
            "no_new_market_source":True,"no_orders":True},sort_keys=True))
    else:
        if a.out is None:
            p.error("explicit --out immutable evidence path required")
        print(json.dumps(write_once(a.out),sort_keys=True,indent=2))
