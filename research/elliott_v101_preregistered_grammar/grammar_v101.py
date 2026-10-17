"""V101 preregistered, fail-closed structural impulse screen, no orders.

Pure grammar on *source-derived* V99 independently confirmed coarse/fine
swings, plus fixed untouched post-V52 Bybit Spot future-research window.
No data for that window is opened or scored in V101. Neither a passing
structural screen nor market-pivot coincidence proves an Elliott pattern.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from research.elliott_v99_causal_scale import scale_v99 as v99
from research.elliott_v100_scale_context import context_v100 as v100

SCHEMA="nexus.elliott-v101-preregistered-causal-impulse-grammar.v1"
RESEARCH_ONLY=True
LIVE_ENABLED=False
PAPER_ELIGIBLE=False
ENTRY_SIGNAL=False
ORDER_ADAPTER=None
V52_UNCHANGED=True
CERTIFIED_ELLIOTT_PATTERNS=0
COARSE_SCALE=Decimal("8")
FINE_SCALE=Decimal("3")
FIXED_INTERIOR_SWINGS=(4,2,4,2,4)
WINDOW_START_UTC="2026-11-16T00:00:00Z"
WINDOW_END_EXCLUSIVE_UTC="2026-11-30T00:00:00Z"
MARKET_SOURCE="BYBIT_SPOT_PUBLIC_CLOSED_1M"
PAIRS=("BTCUSDT","ETHUSDT")
COMPLETE_SOURCE_ROWS_PER_PAIR=20_160
EXPECTED_CONTEXT_EVENTS=7


def manifest() ->dict:
    return {
        "schema":SCHEMA,
        "status":"RULES_FROZEN_BEFORE_DATA_AVAILABLE_NOT_EVALUATED",
        "first_evaluation_not_before_utc":WINDOW_END_EXCLUSIVE_UTC,
        "window_start_utc":WINDOW_START_UTC,
        "window_end_exclusive_utc":WINDOW_END_EXCLUSIVE_UTC,
        "market_source":MARKET_SOURCE,
        "public_source_only_no_live_trading":True,
        "official_exchange": "Bybit",
        "symbol_universe":list(PAIRS),
        "market_type":"spot",
        "interval":"1m",
        "source_rows_per_pair":COMPLETE_SOURCE_ROWS_PER_PAIR,
        "data_not_fetched_in_v101":True,
        "holdout_separate_from_2026_v52":True,
        "warmup_closes":v99.LOOKBACK_CLOSED_RETURNS,
        "fine_mult":str(FINE_SCALE),
        "coarse_mult":str(COARSE_SCALE),
        "threshold_price_floor":str(v99.ABSOLUTE_PAST_PRICE_FLOOR),
        "source_1m_close_required":True,
        "causal_confirmation_only":True,
        "required_consecutive_coarse_events":EXPECTED_CONTEXT_EVENTS,
        "fixed_interior_fine_pivot_counts":list(FIXED_INTERIOR_SWINGS),
        "missing_degree_context_rejected":True,
        "coarse_and_fine_same_source_required":True,
        "coarse_boundary_must_match_fine_swing":True,
        "no_fine_point_pruning":True,
        "late_confirmation_abstains":True,
        "future_neighbor_not_required_or_consulted":True,
        "wave_family":"NONDIAGONAL_NONTRUNCATED_IMPULSE_NECESSARY_ONLY",
        "alternative_elliott_count_allowed":False,
        "candidate_enumeration":"ALL_SLIDING_SEVEN_CONSECUTIVE_COARSE_PIVOTS",
        "five_leg_geometry":["wave_2_no_origin_violation",
          "wave_3_beyond_wave_1","wave_4_no_wave_1_overlap",
          "wave_5_beyond_wave_3","wave_3_not_shortest"],
        "market_degree_authenticated":False,
        "pattern_position_authenticated":False,
        "profitability_demonstrated":False,
        "orders":0,
        "entry_signal":False,
        "paper_eligible":False,
        "live_enabled":False,
        "v52_unchanged":True,
    }


def manifest_bytes()->bytes:
    return (json.dumps(manifest(),sort_keys=True,indent=2,ensure_ascii=False)+"\n").encode()


def prereg_sha()->str:
    return hashlib.sha256(manifest_bytes()).hexdigest()


def _price_geometry(vertices:list[v99.ObservedSwing])->list[str]:
    """Narrow necessary conventional impulse constraints, no prices fabricated."""
    direction=Decimal(1) if vertices[0].kind=="LOW" else Decimal(-1)
    prices=[x.center_close*direction for x in vertices]
    blockers=[]
    if prices[1]<=prices[0]:
        blockers.append("WAVE1_NONPOSITIVE")
    if prices[2]<=prices[0]:
        blockers.append("WAVE2_ORIGIN_BREACH")
    if prices[3]<=prices[1]:
        blockers.append("WAVE3_NO_NEW_EXTREME")
    if prices[4]<=prices[1]:
        blockers.append("WAVE4_OVERLAPS_WAVE1_NONDIAGONAL")
    if prices[5]<=prices[3]:
        blockers.append("WAVE5_NO_NEW_EXTREME_RESTRICTED")
    lengths=(prices[1]-prices[0],prices[3]-prices[2],prices[5]-prices[4])
    if any(x<=0 for x in lengths):
        blockers.append("MOTIVE_LEG_NONPOSITIVE")
    elif lengths[1]<min(lengths[0],lengths[2]):
        blockers.append("WAVE3_SHORTEST")
    return blockers


def inspect_window(
    coarse7:list[v99.ObservedSwing],
    fine:list[v99.ObservedSwing],
    asof:int,
)->dict:
    """One seven-consecutive-coarse-event impulse hypothesis.

    First coarse event is the *past* context witness. Subsequent six events
    are all five endpoints. Entire source-observed fine stream is immutable
    input. A structural pass never certifies Elliott/position/orders.
    """
    if type(coarse7) is not list or len(coarse7)!=EXPECTED_CONTEXT_EVENTS:
        raise ValueError("exactly seven consecutive context+impulse vertices needed")
    if type(fine) is not list or type(asof) is not int or asof%v99.MINUTE:
        raise ValueError("source complete minute decision cutoff required")
    if asof!=coarse7[-1].confirmed_ms:
        raise ValueError("evaluate at last physical coarse confirmation, never later")
    # V100 independently enforces monotonic confirmation and source-epoch
    # consistency. It accounts for all fine events, no selection/pruning.
    ledger=v100.causal_relationships(fine,coarse7,asof)
    vertices=coarse7[1:]
    last_confirm=vertices[-1].confirmed_ms
    if last_confirm>asof:
        raise ValueError("unclosed higher-scale decision")
    reasons=[]
    if coarse7[0].confirmed_ms>vertices[0].confirmed_ms:
        reasons.append("PRECONTEXT_NOT_YET_CONFIRMED")
    if vertices[0].kind!="LOW":
        # Both directions are tested by mirrored price geometry, but only
        # the prior context signal must alternate with first wave center.
        if vertices[0].kind!="HIGH":
            reasons.append("UNKNOWN_DIRECTION")
    reasons.extend(_price_geometry(vertices))
    intervals=ledger["intervals"][1:]
    if len(intervals)!=5:
        raise ValueError("expected exactly five coarse candidate legs")
    for i,(leg,expected) in enumerate(zip(intervals,FIXED_INTERIOR_SWINGS)):
        if leg["all_fine_center_interior_count"]!=expected:
            reasons.append(f"LEG{i+1}_UNPRUNED_FINE_COUNT_NOT_FROZEN_DEGREE")
        if leg["fine_confirmed_too_late_count"]!=0:
            reasons.append(f"LEG{i+1}_LATE_FINE_CONFIRMATION")
        if leg["right_confirmed_ms"]>last_confirm:
            reasons.append(f"LEG{i+1}_FUTURE_COARSE_CONFIRMATION")
        # Physical fine-scale boundary attestation at *both* endpoints.
        coarse_left=vertices[i]
        coarse_right=vertices[i+1]
        if not any(x.center_ms==coarse_left.center_ms and
                   x.kind==coarse_left.kind and
                   x.center_close==coarse_left.center_close and
                   x.confirmed_ms<=coarse_left.confirmed_ms
                   for x in fine):
            reasons.append(f"LEG{i+1}_MISSING_CAUSAL_FINE_LEFT_BOUNDARY")
        if not any(x.center_ms==coarse_right.center_ms and
                   x.kind==coarse_right.kind and
                   x.center_close==coarse_right.center_close and
                   x.confirmed_ms<=coarse_right.confirmed_ms
                   for x in fine):
            reasons.append(f"LEG{i+1}_MISSING_CAUSAL_FINE_RIGHT_BOUNDARY")
    return {
        "schema":"nexus.elliott-v101-single-window-synthetic-screen.v1",
        "first_observable_ms":last_confirm,
        "hypothesis_direction":"UP" if vertices[0].kind=="LOW" else "DOWN",
        "historical_predecessor_center_ms":coarse7[0].center_ms,
        "impulse_center_timestamps_ms":[x.center_ms for x in vertices],
        "required_interior_counts":list(FIXED_INTERIOR_SWINGS),
        "observed_interior_counts":[x["all_fine_center_interior_count"]
                                     for x in intervals],
        "entire_fine_source_digest":ledger["all_original_fine_events_sha256"],
        "entire_context_coarse_digest":ledger["all_original_coarse_events_sha256"],
        "hard_rejections":list(dict.fromkeys(reasons)),
        "necessary_geometry_and_degree_skeleton_pass":not reasons,
        "full_elliott_market_wave_proven":False,
        "pattern_position_proven":False,
        "paper_eligible":False,
        "entry_signal":False,
        "live_enabled":False,
        "net_pnl":None,
    }


def enumerate_all_source_candidates(
    closed_1m:list[v99.CloseMinute],asof:int,
)->dict:
    """Future evaluation API: every consecutive coarse window, no scoring.

    Caller must supply verified Bybit closed 1m source in the locked window.
    This API is NOT invoked for any market data by V101.
    """
    src=v99.validate_closed_prefix(closed_1m,asof)
    start=int(datetime.fromisoformat(WINDOW_START_UTC.replace("Z","+00:00")).timestamp()*1000)
    end=int(datetime.fromisoformat(WINDOW_END_EXCLUSIVE_UTC.replace("Z","+00:00")).timestamp()*1000)
    if (src[0].ms!=start or src[-1].ms+v99.MINUTE!=end or
        len(src)!=COMPLETE_SOURCE_ROWS_PER_PAIR or asof!=end):
        raise ValueError("complete locked future-window source required")
    fine=v99.observe_scale(src,FINE_SCALE,asof)
    coarse=v99.observe_scale(src,COARSE_SCALE,asof)
    results=[]
    for offset in range(max(0,len(coarse)-EXPECTED_CONTEXT_EVENTS+1)):
        seven=coarse[offset:offset+EXPECTED_CONTEXT_EVENTS]
        cutoff=seven[-1].confirmed_ms
        # Strictly replay only observations available at candidate decision.
        eligible_fine=[x for x in fine if x.confirmed_ms<=cutoff]
        verdict=inspect_window(seven,eligible_fine,cutoff)
        results.append(verdict)
    return {
        "schema":"nexus.elliott-v101-exhaustive-structural-diagnostic.v1",
        "preregistered_rulebook_sha256":prereg_sha(),
        "source_minutes_examined":len(src),
        "all_fine_scale_confirmations":len(fine),
        "all_coarse_scale_confirmations":len(coarse),
        "all_consecutive_context_windows":len(results),
        "necessary_technical_skeleton_passes":sum(
            x["necessary_geometry_and_degree_skeleton_pass"] for x in results),
        "all_windows_accounted":True,
        "results":results,
        "certified_elliott_patterns":0,
        "paper_eligible":False,"entry_signal":False,
        "live_enabled":False,"net_pnl":None,
    }


def freeze_unopened_rulebook(destination:Path)->dict:
    """Write-only sealed future protocol; reject any changes on later runs."""
    if not isinstance(destination,Path):
        raise ValueError("explicit local research rulebook file required")
    raw=manifest_bytes()
    if destination.exists():
        if destination.read_bytes()!=raw:
            raise ValueError("frozen V101 rulebook differs; no silent rewrite")
    else:
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes(raw)
    return {
        "status":"PRE_REGISTERED_RULEBOOK_NO_FUTURE_SOURCE_OPENED",
        "sha256":prereg_sha(),
        "path":str(destination),
        "source_rows_fetched":0,"market_patterns_evaluated":0,
        "trades":0,
    }


if __name__=="__main__":
    import argparse
    args=argparse.ArgumentParser()
    args.add_argument("--prereg-output",type=Path,required=True)
    opts=args.parse_args()
    print(json.dumps(freeze_unopened_rulebook(opts.prereg_output),
                     sort_keys=True,indent=2))
