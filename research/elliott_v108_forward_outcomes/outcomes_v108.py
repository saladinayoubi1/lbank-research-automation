"""V108 PREREGISTERED forward-only barrier observation, NO TRADES or PNL.

V107 candidate choice, acceptance and timestamp are sealed before V108
reads any post-decision OHLC. For both accepted AND rejected candidate
windows, V108 observes first subsequent touch of physical Wave-1 endpoint
versus Wave-0 origin across a fixed 240 CLOSED one-minute-bar horizon.
This is NOT a market Elliott "truth label", prediction precision, or fill.
Ambiguous same 1m bar -> conservative origin invalidation; censored if
period ends before horizon with no touch; otherwise unresolved horizon.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path

from research.elliott_v99_causal_scale import scale_v99 as v99
from research.elliott_v100_scale_context import context_v100 as v100
from research.elliott_v101_preregistered_grammar import grammar_v101 as v101
from research.elliott_v102_bybit_intake import intake_v102 as v102
from research.elliott_v104_independent_challenger import challenger_v104 as v104
from research.elliott_v107_prefix_census import census_v107 as v107

SCHEMA="nexus.elliott-v108-frozen-forward-barrier-census.v1"
PARENT_V107_COMMIT="1933478836139953576db9d7ffbe0d7e0dad5b5e"
PARENT_V107_REL="docs/evidence/elliott-v107-prefix-census-20261017/V107_FROZEN_PREFIX_LEDGER_RULEBOOK.json"
PARENT_V107_SHA="be319ea2cd165553e331259153b305df534a8058663af6758d6d34f0199674b6"
HORIZON_CLOSED_1M=240
CLOSED_MINUTE_MS=60000
RESEARCH_ONLY=True
TRADING_ENABLED=False
PAPER_ELIGIBLE=False
ENTRY_SIGNAL=False
LIVE_ENABLED=False
ORDER_ADAPTER=None
V52_UNCHANGED=True
VALID_STATUSES=(
    "WAVE1_BARRIER_FIRST",
    "WAVE0_ORIGIN_FIRST",
    "SAME_MINUTE_BOTH_ASSUME_ORIGIN_FIRST",
    "NO_BARRIER_BY_240_CLOSED_MINUTES",
    "RIGHT_CENSORED_AFTER_SOURCE_END",
    "NONCOMPARABLE_GEOMETRY",
)

def plan()->dict:
    return {
        "schema":SCHEMA,
        "status":"FROZEN_BEFORE_FUTURE_OHLC_NO_MARKET_OUTCOMES",
        "upstream_v107_commit":PARENT_V107_COMMIT,
        "upstream_v107_sha256":PARENT_V107_SHA,
        "v101_future_window_start_utc":v101.WINDOW_START_UTC,
        "v101_future_window_end_exclusive_utc":v101.WINDOW_END_EXCLUSIVE_UTC,
        "source_market":"Bybit public Spot one minute only",
        "fixed_symbols":list(v101.PAIRS),
        "all_sequential_six_coarse_windows_scored":True,
        "both_necessary_pass_and_rejected_windows_in_denominator":True,
        "original_v107_decisions_immutable":True,
        "outcome_data_start_at_original_wave2_right_confirmation":True,
        "outcome_data_never_input_to_past_decision":True,
        "fixed_followup_closed_one_minute_bars":HORIZON_CLOSED_1M,
        "wave1_endpoint_observation_not_trade_target":True,
        "wave0_origin_observation_not_executable_stop":True,
        "simultaneous_high_low_same_bar_assume_origin_first":True,
        "unresolved_full_horizon_distinct_from_end_censored":True,
        "unusable_wave0_wave1_barrier_mark_noncomparable":True,
        "both_accepted_and_rejected_may_be_noncomparable":True,
        "no_ohlc_intrabar_order_inferred":True,
        "no_slippage_spread_fees_latency_or_fill_claim":True,
        "no_real_elliott_ground_truth_labels":True,
        "no_false_positive_rate_or_win_rate_computed":True,
        "source_requires_two_pass_same_raw_archive_audit":True,
        "not_independent_market_source_authenticity":True,
        "first_real_source_evaluation_after_2026_11_30_only":True,
        "future_data_read_during_v108":0,
        "market_outcomes_evaluated_during_v108":0,
        "orders":0,"entry_signal":False,"paper_eligible":False,
        "live_enabled":False,"v52_unchanged":True,
    }


def frozen_bytes()->bytes:
    return (json.dumps(plan(),sort_keys=True,indent=2)+"\n").encode()


def freeze_rulebook(destination:Path)->dict:
    if not isinstance(destination,Path):
        raise ValueError("explicit frozen research path required")
    from research.elliott_v93_recursive_proof import proof_v93 as v93
    witness=v93.immutable_receipt(
        PARENT_V107_REL,PARENT_V107_SHA,PARENT_V107_COMMIT,v107.SCHEMA)
    if (witness.get("future_source_not_read_or_fetched_during_v107") is not True
        or witness.get("orders")!=0
        or witness.get("all_consecutive_coarse_window_size")!=6):
        raise ValueError("upstream V107 source-only enumeration altered")
    raw=frozen_bytes()
    if destination.exists():
        if destination.read_bytes()!=raw:
            raise ValueError("V108 locked prospective rulebook modified")
    else:
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes(raw)
    return {"state":"PROSPECTIVE_OUTCOME_RULEBOOK_FROZEN_NO_SOURCE",
            "sha256":hashlib.sha256(raw).hexdigest(),
            "real_market_rows_observed":0,
            "trades":0}


def validate_physical_candles(bars:list[v102.Candle])->tuple[int,int]:
    if type(bars) is not list or not bars:
        raise ValueError("complete typed original 1m OHLC source needed")
    start=bars[0].ms
    if type(start) is not int or start%CLOSED_MINUTE_MS:
        raise ValueError("source not aligned to complete UTC 1m")
    for i,c in enumerate(bars):
        if type(c) is not v102.Candle or c.ms!=start+i*CLOSED_MINUTE_MS:
            raise ValueError("physical source gap/duplicate/nonclosed minute")
        for n in (c.open,c.high,c.low,c.close,c.volume,c.turnover):
            if type(n) is not Decimal or not n.is_finite():
                raise ValueError("invalid nonfinite/untyped physical OHLC source")
        if (not 0<c.low<=c.open<=c.high or not c.low<=c.close<=c.high
            or c.volume<0 or c.turnover<0):
            raise ValueError("unphysical OHLC / negative volume")
    return start,start+len(bars)*CLOSED_MINUTE_MS


def first_barrier_outcome(
    six:list[v99.ObservedSwing],
    decision_asof:int,
    after:list[v102.Candle],
    source_end_exclusive:int,
)->dict:
    """Retrospective price-path observation ONLY; not an entry or exit.

    after starts precisely at the time of Wave-2 right-confirmation.
    No outcomes may be assigned before 1m OHLC is fully closed. Censor
    on source end if fewer than 240 bars remain AND neither barrier hit.
    """
    if type(six) is not list or len(six)!=6 or any(
        type(x) is not v99.ObservedSwing for x in six):
        raise ValueError("six original coarse events mandatory")
    if (type(decision_asof) is not int or
        decision_asof%CLOSED_MINUTE_MS or
        six[-1].confirmed_ms!=decision_asof):
        raise ValueError("decision not wave2 causal confirmation")
    if type(source_end_exclusive) is not int or (
        source_end_exclusive%CLOSED_MINUTE_MS):
        raise ValueError("complete source end required")
    if type(after) is not list or len(after)>HORIZON_CLOSED_1M:
        raise ValueError("bounded postdecision OHLC window required")
    if source_end_exclusive<decision_asof+len(after)*CLOSED_MINUTE_MS:
        raise ValueError("source end contradicts visible followup")
    if len(after)<min(HORIZON_CLOSED_1M,
                      (source_end_exclusive-decision_asof)//CLOSED_MINUTE_MS):
        raise ValueError("missing original postdecision bars")
    if after:
        observed_start,observed_end=validate_physical_candles(after)
        if observed_start!=decision_asof or (
            observed_end!=decision_asof+len(after)*CLOSED_MINUTE_MS):
            raise ValueError("future or offset source bar substituted")
    direction=Decimal(1) if six[3].kind=="LOW" else Decimal(-1)
    wave0=six[3].center_close
    wave1=six[4].center_close
    if (type(wave0) is not Decimal or type(wave1) is not Decimal
        or not wave0.is_finite() or not wave1.is_finite() or
        wave0<=0 or wave1<=0):
        raise ValueError("untrusted physical wave barriers")
    category="NONCOMPARABLE_GEOMETRY"
    minute_label=None
    # This screens only whether barriers are distinguishable and properly
    # directionally oriented; it does not consult V106's pass verdict.
    if (wave1-wave0)*direction>0:
        category="NO_BARRIER_BY_240_CLOSED_MINUTES"
        for i,bar in enumerate(after):
            invalid=(bar.low<=wave0 if direction>0 else bar.high>=wave0)
            extend=(bar.high>=wave1 if direction>0 else bar.low<=wave1)
            if invalid and extend:
                category="SAME_MINUTE_BOTH_ASSUME_ORIGIN_FIRST"
            elif invalid:
                category="WAVE0_ORIGIN_FIRST"
            elif extend:
                category="WAVE1_BARRIER_FIRST"
            else:
                continue
            minute_label=i+1
            break
        if (minute_label is None and len(after)<HORIZON_CLOSED_1M):
            category="RIGHT_CENSORED_AFTER_SOURCE_END"
    if category not in VALID_STATUSES:
        raise ValueError("not a preregistered diagnostic classification")
    return {
        "schema":"nexus.elliott-v108-one-original-decision-observation.v1",
        "decision_asof_ms":decision_asof,
        "barrier_wave0_origin":str(wave0),
        "barrier_wave1_extreme":str(wave1),
        "hypothesis_direction":"UP" if direction>0 else "DOWN",
        "up_to_closed_followup_minutes_observed":len(after),
        "first_touch_lag_completed_minutes":minute_label,
        "outcome":category,
        "outcome_is_not_market_elliott_truth":True,
        "simultaneous_touch_not_counted_as_breakout":True,
        "actual_entry_filled":False,
        "trade_opened":False,
        "paper_eligible":False,
        "live_enabled":False,
        "net_pnl":None,
    }


def assess_every_v107_window(
    v107_census:dict,
    coarse:list[v99.ObservedSwing],
    source_bars:list[v102.Candle],
)->dict:
    """Outcome-only ledger; NEVER recompute or choose original candidates.

    Both V107 passed and rejected candidates stay in denominator, and the
    *separate* postdecision outcome is never attached to original decisions.
    Caller-provided streams are not guaranteed market-authentic; the full
    future adapter below must independently rederive and verify their origin.
    """
    start,end=validate_physical_candles(source_bars)
    if (type(v107_census) is not dict or
        v107_census.get("schema")!=v107.SCHEMA or
        type(coarse) is not list):
        raise ValueError("original V107 candidate accounting required")
    originals=v107_census.get("candidate_ledger")
    if (type(originals) is not list or
        len(originals)!=max(0,len(coarse)-5) or
        v107_census.get("all_consecutive_six_coarse_windows")!=len(originals)):
        raise ValueError("all unpruned original V107 candidates required")
    outcomes=[]
    matrix={"necessary_pass":Counter(),"necessary_reject":Counter()}
    for i,source_decision in enumerate(originals):
        if type(source_decision) is not dict:
            raise ValueError("missing source-bound candidate")
        six=coarse[i:i+6]
        expected_cutoff=six[-1].confirmed_ms
        if (source_decision.get("window_ordinal")!=i or
            source_decision.get("coarse_event_indices_in_original_stream")!=[i,i+5]
            or source_decision.get("decision_asof_ms")!=expected_cutoff or
            source_decision.get("coarse_window_sha256")!=v100.digest_events(six)
            or type(source_decision.get("necessary_partial_skeleton_pass")) is not bool
            or type(source_decision.get("rejections")) is not list or
            source_decision["necessary_partial_skeleton_pass"]==
               bool(source_decision["rejections"])):
            raise ValueError("original candidate was changed or omitted")
        if (expected_cutoff<start or expected_cutoff>end or
            (expected_cutoff-start)%CLOSED_MINUTE_MS):
            raise ValueError("source has no eligible original candidate cutoff")
        begin=(expected_cutoff-start)//CLOSED_MINUTE_MS
        tail=source_bars[begin:begin+HORIZON_CLOSED_1M]
        outcome=first_barrier_outcome(six,expected_cutoff,tail,end)
        accepted=source_decision["necessary_partial_skeleton_pass"]
        group="necessary_pass" if accepted else "necessary_reject"
        matrix[group][outcome["outcome"]]+=1
        outcomes.append({
            "original_window_ordinal":i,
            "original_decision_asof_ms":expected_cutoff,
            "original_gate_pass":accepted,
            "original_hard_rejections":source_decision["rejections"],
            "original_six_coarse_sha256":source_decision["coarse_window_sha256"],
            "original_predecision_fine_sha256":source_decision["visible_fine_stream_sha256"],
            "forward_observation":outcome,
        })
    if len(outcomes)!=len(originals) or sum(
        sum(group.values()) for group in matrix.values())!=len(originals):
        raise ValueError("outcome accounting lost a candidate")
    if (sum(matrix["necessary_pass"].values())!=v107_census.get(
        "necessary_partial_skeleton_passes") or
        sum(matrix["necessary_reject"].values())!=v107_census.get(
        "necessary_partial_skeleton_rejections")):
        raise ValueError("V108 reweighted the frozen prior decision groups")
    return {
        "schema":"nexus.elliott-v108-all-candidates-price-barrier-observations.v1",
        "original_v107_candidate_count":len(originals),
        "original_v107_gate_passes":v107_census["necessary_partial_skeleton_passes"],
        "original_v107_gate_rejections":v107_census["necessary_partial_skeleton_rejections"],
        "all_original_decisions_preserved":True,
        "fixed_followup_closed_minutes":HORIZON_CLOSED_1M,
        "outcome_group_tallies":{
            group:dict(sorted(counts.items()))
            for group,counts in matrix.items()},
        "separate_forward_only_outcome_ledger":outcomes,
        "this_pure_helper_is_not_market_source_authenticated":True,
        "real_elliott_truth_unavailable":True,
        "false_positive_rate":None,
        "trade_win_rate":None,
        "bybit_net_pnl":None,
        "paper_eligible":False,"entry_signal":False,
        "live_enabled":False,"orders":0,
    }


def evaluate_future_archive_only(folder:Path)->dict:
    """After date gate and BOTH source parsers, recompute original V107 first.

    Uses V107's fully verified 42-page archived-source reconstruction and
    rebuilds physical OHLC bars by independently revalidating each raw page.
    SHA matches on every page and canonical 7-field ledger prevent mixing
    outcomes from another dataset. NO requests or broker side effects.
    """
    if not isinstance(folder,Path):
        raise ValueError("explicit physical archive Path required")
    end=v102.locked_range()[1]
    now=int(datetime.now(timezone.utc).timestamp()*1000)
    if now<end:
        raise ValueError("FUTURE_PERIOD_INCOMPLETE_NO_ARCHIVE_READ")
    from research.elliott_v93_recursive_proof import proof_v93 as v93
    v93.immutable_receipt(PARENT_V107_REL,PARENT_V107_SHA,
                          PARENT_V107_COMMIT,v107.SCHEMA)
    prior=v107.evaluate_future_sealed_archive(folder)
    result={
        "schema":"nexus.elliott-v108-source-gated-future-outcomes.v1",
        "source_claim":prior["source"],
        "v107_original_rulebook_sha256":PARENT_V107_SHA,
        "source_origin_independently_signed":False,
        "source_provenance_limit_not_dropped":True,
        "all_symbols":{},
        "no_orders_created":True,
        "paper_eligible":False,"entry_signal":False,
        "live_enabled":False,"net_pnl":None,
    }
    for symbol in v101.PAIRS:
        rows=[]
        for desc in v104.descriptors():
            if desc["symbol"]!=symbol:
                continue
            body=(folder/(desc["stem"]+".raw.json")).read_bytes()
            meta=(folder/(desc["stem"]+".receipt.json")).read_bytes()
            audit=v104.validate_independent_page(desc,body,meta)
            rows.extend(audit["candles"])
        normalized=json.dumps(rows,ensure_ascii=False,separators=(",",":")).encode()
        recorded=prior["symbol_ledger"][symbol]
        if (len(rows)!=v101.COMPLETE_SOURCE_ROWS_PER_PAIR or
            hashlib.sha256(normalized).hexdigest()!=recorded["complete_source_sha256"]):
            raise ValueError("future source data changed between V107 and V108 audits")
        bars=[v102.Candle(int(r[0]),*(Decimal(x) for x in r[1:]))
              for r in rows]
        start,actual_end=validate_physical_candles(bars)
        if start!=v102.locked_range()[0] or actual_end!=end:
            raise ValueError("different future market period substituted")
        minute_closes=[v99.CloseMinute(c.ms,c.close) for c in bars]
        fine=v99.observe_scale(minute_closes,v101.FINE_SCALE,end)
        coarse=v99.observe_scale(minute_closes,v101.COARSE_SCALE,end)
        independent=v107.enumerate_event_prefixes(fine,coarse,end)
        if (independent["candidate_ledger"]!=recorded["candidate_ledger"] or
            v100.digest_events(coarse)!=recorded["all_coarse_events_sha256"] or
            v100.digest_events(fine)!=recorded["all_fine_events_sha256"]):
            raise ValueError("original wave2 candidate or decision was revised")
        scored=assess_every_v107_window(independent,coarse,bars)
        scored["authenticity_caveat"]="two_offline_parsers_same_archive_not_Bybit_payload_signature"
        scored["source_candles"]=len(bars)
        scored["physical_source_sha256"]=recorded["complete_source_sha256"]
        result["all_symbols"][symbol]=scored
    return result


def status()->dict:
    return {
        "status":"V108_OUTCOME_GRAMMAR_PREREGISTERED_NOT_MARKET_EVALUATED",
        "actual_source_candles_accessed":0,"real_outcomes_assigned":0,
        "trading_eligible":False,"live_enabled":False,"orders":0,
    }


if __name__=="__main__":
    import argparse
    a=argparse.ArgumentParser()
    a.add_argument("--mode",choices=("status","future-offline-outcomes"),default="status")
    a.add_argument("--archive",type=Path)
    args=a.parse_args()
    if args.mode=="status":
        print(json.dumps(status(),indent=2,sort_keys=True))
    else:
        if args.archive is None:
            a.error("--archive required for future source scoring")
        print(json.dumps(evaluate_future_archive_only(args.archive),
                         indent=2,sort_keys=True))
