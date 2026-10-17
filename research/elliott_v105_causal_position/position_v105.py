"""V105 CAUSAL WAVE-POSITION SCREEN + COUNTERFACTUAL FIRST-BAR RISK QA.

No market data is fetched and no source has been fit or traded.
V101 full five-wave classification is observable only AFTER its wave-5
confirmation: V105 categorically forbids backdated wave-2/3 entries.
Nine consecutive coarse events provide a narrow reversal-contour test;
it is NOT proof of Elliott wave position. First post-confirmation bar
OHLC tests are retrospective *synthetic* outcome diagnostics, not fills.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from research.elliott_v99_causal_scale import scale_v99 as v99
from research.elliott_v100_scale_context import context_v100 as v100
from research.elliott_v101_preregistered_grammar import grammar_v101 as v101
from research.elliott_v102_bybit_intake import intake_v102 as v102

SCHEMA="nexus.elliott-v105-causal-position-and-exit-diagnostics.v1"
UPSTREAM_V104_COMMIT="cd4421fe6a38e7ed4177e74e3f3a73e0506df279"
UPSTREAM_V104_SHA="ddac100a49f290a81e51c53f9de0e0706965d1269684881a72b3bf1ee927686f"
UPSTREAM_V104_REL="docs/evidence/elliott-v104-independent-challenger-20261017/V104_FROZEN_SECOND_AUDITOR_PROTOCOL.json"
PREDECESSOR_CONTEXT_LENGTH=3
IMPULSE_VERTICES=6
TOTAL_COARSE_VERTICES=9
COUNTERFACTUAL_TARGET_MULTIPLE=Decimal("2")
RESEARCH_ONLY=True
PAPER_ELIGIBLE=False
LIVE_ENABLED=False
ORDER_ADAPTER=None
ENTRY_SIGNAL=False
MARKET_WAVE_PROVEN=False
V52_UNCHANGED=True


def _serial(record:object)->bytes:
    return (json.dumps(record,sort_keys=True,indent=2,ensure_ascii=False)+"\n").encode()


def manifest()->dict:
    return {
        "schema":SCHEMA,
        "status":"FROZEN_SYNTHETIC_ONLY_NO_MARKET_POSITION_EVALUATED",
        "upstream_v104_sha256":UPSTREAM_V104_SHA,
        "upstream_v104_commit":UPSTREAM_V104_COMMIT,
        "preregistered_v101_sha256":v102.PREREG_V101_SHA,
        "future_bybit_spot_window_start_utc":v101.WINDOW_START_UTC,
        "future_bybit_spot_window_end_exclusive_utc":v101.WINDOW_END_EXCLUSIVE_UTC,
        "allowed_symbols":list(v101.PAIRS),
        "first_market_evaluation_after_future_window_only":True,
        "strict_9_consecutive_coarse_vertices":True,
        "prior_context_confirmed_vertices":PREDECESSOR_CONTEXT_LENGTH,
        "impulse_vertices":IMPULSE_VERTICES,
        "fixed_reversal_context":"lower_high_lower_low_for_up_mirror_for_down",
        "strict_original_v101_impulse_skeleton_required":True,
        "wave_2_or_3_retroactive_entry_forbidden":True,
        "decision_only_after_last_wave5_right_confirmation":True,
        "unconfirmed_last_extreme_rejected":True,
        "no_source_pivot_pruning":True,
        "hypothetical_first_open_not_an_executable_fill":True,
        "hypothetical_stop_from_confirmed_wave4_center":True,
        "hypothetical_risk_multiple_target":str(COUNTERFACTUAL_TARGET_MULTIPLE),
        "one_closed_next_1m_ohlc_for_counterfactual_only":True,
        "same_bar_stop_and_target_assume_stop":True,
        "gapped_open_beyond_stop_assume_stop_or_worse_not_winner":True,
        "no_fees_or_slippage_claim":True,
        "complete_elliott_degree_proven":False,
        "market_pattern_position_proven":False,
        "orders":0,"paper_eligible":False,
        "live_enabled":False,"net_pnl":None,
        "no_v52_changes":True,
        "real_market_data_read":0,
    }


def manifest_bytes()->bytes:
    return _serial(manifest())


def manifest_sha()->str:
    return hashlib.sha256(manifest_bytes()).hexdigest()


def freeze_manifest(path:Path)->dict:
    """Immutable preregistration of a *non-deployed* future hypothesis."""
    if not isinstance(path,Path):
        raise ValueError("an explicit Path is required")
    from research.elliott_v93_recursive_proof import proof_v93 as v93
    pinned=v93.immutable_receipt(
        UPSTREAM_V104_REL,UPSTREAM_V104_SHA,UPSTREAM_V104_COMMIT,
        "nexus.elliott-v104-frozen-independent-source-challenge-plan.v1")
    if (pinned["data_fetched_during_v104"]!=0 or
        pinned["real_market_patterns_evaluated"]!=0 or
        pinned["request_page_count"]!=42):
        raise ValueError("upstream source-only V104 protocol has changed")
    contents=manifest_bytes()
    if path.exists():
        if path.read_bytes()!=contents:
            raise ValueError("V105 original manifest changed; fail closed")
    else:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(contents)
    return {
        "status":"NO_MARKET_DATA_OPENED_V105_POSITION_RULES_FROZEN",
        "sha256":manifest_sha(),
        "market_examples":0,
        "orders":0,
    }


def inspect_context(
    coarse9:list[v99.ObservedSwing],
    fine:list[v99.ObservedSwing],
    decision_asof_ms:int,
)->dict:
    """A *narrow reversal* hypothesis, not an authentic Elliott origin.

    Require three prior confirmed context witnesses [H,L,H] for an upward
    impulse that starts at LOW (and mirrored [L,H,L] for bearish); prior
    impulse-direction high/lows must form strict former-trend extremes.
    Fully formed five-wave skeleton is from immutable V101 algorithm.
    """
    if (type(coarse9) is not list or len(coarse9)!=TOTAL_COARSE_VERTICES or
        type(fine) is not list or type(decision_asof_ms) is not int or
        decision_asof_ms%v99.MINUTE):
        raise ValueError("exact nine-coarse-event decision required")
    if coarse9[-1].confirmed_ms!=decision_asof_ms:
        raise ValueError("no wave-5 hindsight or delayed decision")
    # Verify each source event is chronologically consistent. This also
    # refuses any fine observation not known by the decision.
    v100.causal_relationships(fine,coarse9,decision_asof_ms)
    original=v101.inspect_window(coarse9[2:],fine,decision_asof_ms)
    left,middle,right,origin=coarse9[:4]
    direction=Decimal(1) if origin.kind=="LOW" else Decimal(-1)
    reasons=list(original["hard_rejections"])
    if ([x.kind for x in (left,middle,right,origin)]!=
        (["HIGH","LOW","HIGH","LOW"] if direction>0 else
         ["LOW","HIGH","LOW","HIGH"])):
        reasons.append("PREVIOUS_CONTEXT_ALTERNATION_MISSING")
    directed=[x.center_close*direction for x in (left,middle,right,origin)]
    if not directed[2]<directed[0]:
        reasons.append("OLDER_TREND_REVERSAL_LOWER_HIGH_UNPROVEN")
    if not directed[3]<directed[1]:
        reasons.append("OLDER_TREND_REVERSAL_LOWER_LOW_UNPROVEN")
    if any(x.confirmed_ms>origin.confirmed_ms for x in (left,middle,right)):
        reasons.append("PREDECESSOR_WAS_NOT_ALREADY_OBSERVABLE")
    if any(x.confirmed_ms>decision_asof_ms for x in coarse9):
        raise ValueError("future coarse confirmation")
    reasons=list(dict.fromkeys(reasons))
    return {
        "schema":"nexus.elliott-v105-reversal-position-synthetic-diagnostic.v1",
        "original_v101_last_observable_ms":original["first_observable_ms"],
        "decision_asof_ms":decision_asof_ms,
        "direction":original["hypothesis_direction"],
        "all_nine_coarse_events_sha256":v100.digest_events(coarse9),
        "all_fine_events_sha256":v100.digest_events(fine),
        "prior_three_context_centers_ms":[x.center_ms for x in coarse9[:3]],
        "candidate_six_wave_centers_ms":[x.center_ms for x in coarse9[3:]],
        "necessary_context_and_impulse_skeleton_pass":not reasons,
        "hard_rejections":reasons,
        "complete_market_elliott_pattern_proven":False,
        "market_pattern_position_proven":False,
        "historical_wave2_or_wave3_entry_valid":False,
        "decision_not_before_wave5_confirmed":True,
        "entry_signal":False,"paper_eligible":False,"live_enabled":False,
        "pnl":None,
    }


def hypothetical_first_postconfirmation_bar(
    coarse9:list[v99.ObservedSwing],
    fine:list[v99.ObservedSwing],
    minute:v102.Candle,
    evaluation_asof_ms:int,
)->dict:
    """NON-EXECUTABLE first-bar risk accounting on CLOSED hypothetical OHLC.

    Wave-5 confirmation occurs just *before* the bar starting minute.ms.
    Any projected next-open fill is known only retrospectively when the
    bar is closed; never record it as an actual tradable fill at its open.
    No P&L, fee, slippage, position, stop order, or chart optimization.
    """
    if type(minute) is not v102.Candle:
        raise ValueError("typed single physical future-source candle required")
    if type(evaluation_asof_ms) is not int or evaluation_asof_ms%v99.MINUTE:
        raise ValueError("completed next-bar evaluation required")
    if (type(minute.ms) is not int or minute.ms%v99.MINUTE or
        minute.ms+v99.MINUTE!=evaluation_asof_ms):
        raise ValueError("next bar not fully closed at evaluation cutoff")
    for item in (minute.open,minute.high,minute.low,minute.close,
                 minute.volume,minute.turnover):
        if type(item) is not Decimal or not item.is_finite():
            raise ValueError("nonfinite or invalid OHLC source type")
    if (not 0<minute.low<=minute.open<=minute.high or
        not minute.low<=minute.close<=minute.high or
        minute.volume<0 or minute.turnover<0):
        raise ValueError("invalid complete synthetic OHLC candle")
    context=inspect_context(coarse9,fine,minute.ms)
    blockers=list(context["hard_rejections"])
    direction=Decimal(1) if context["direction"]=="UP" else Decimal(-1)
    projected_open=minute.open
    stop_anchor=coarse9[7].center_close  # source-time confirmed Wave 4
    oriented_risk=(projected_open-stop_anchor)*direction
    if oriented_risk<=0:
        blockers.append("NEXT_OPEN_BEYOND_OR_AT_DEFENSIVE_WAVE4_STOP")
    outcome="ABSTAIN_INVALID_CONTEXT_OR_RISK"
    projected_target=None
    if not blockers:
        projected_target=projected_open+direction*COUNTERFACTUAL_TARGET_MULTIPLE*oriented_risk
        stop_hit=(minute.low<=stop_anchor if direction>0 else
                  minute.high>=stop_anchor)
        target_hit=(minute.high>=projected_target if direction>0 else
                    minute.low<=projected_target)
        if stop_hit and target_hit:
            outcome="BOTH_TOUCHED_ASSUMED_STOP_FIRST_NO_INTRABAR_SEQUENCE"
        elif stop_hit:
            outcome="HYPOTHETICAL_STOP_TOUCH"
        elif target_hit:
            outcome="HYPOTHETICAL_TARGET_TOUCH"
        else:
            outcome="NO_EXIT_IN_FIRST_CLOSED_MINUTE"
    return {
        "schema":"nexus.elliott-v105-nonexecutable-firstbar-outcome.v1",
        "causal_skeleton_asof_ms":context["decision_asof_ms"],
        "first_bar_start_ms":minute.ms,
        "first_bar_known_only_at_ms":evaluation_asof_ms,
        "projected_open_price_from_completed_bar_not_real_fill":str(projected_open),
        "projected_wave4_stop":str(stop_anchor),
        "projected_2R_target":str(projected_target) if projected_target is not None else None,
        "projected_directed_risk":str(oriented_risk),
        "rejections":blockers,
        "conservative_firstbar_diagnostic":outcome,
        "same_minute_ohlc_cannot_reveal_order_of_extrema":True,
        "retroactive_wave2_or_wave3_entry_prohibited":True,
        "not_an_executable_strategy_or_trade":True,
        "real_entry_or_exit_count":0,
        "paper_eligible":False,"entry_signal":False,
        "live_enabled":False,"net_pnl":None,
    }
