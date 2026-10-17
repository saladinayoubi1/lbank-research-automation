"""V106 strictly prospective *partial* Elliott reversal hypothesis grammar.

Six physical coarse events = three earlier context extrema, wave-zero,
wave-one, and CONFIRMED wave-two. Wave-three/four/five are NEVER inputs.
A grammar pass is NOT Elliott certification, an executable entry or PnL.
Uses frozen V99/V100 coarse/fine observations and freezes tests WITHOUT
reading future V101 Bybit Spot period. Explicitly zero broker adapters.
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

from research.elliott_v99_causal_scale import scale_v99 as v99
from research.elliott_v100_scale_context import context_v100 as v100
from research.elliott_v101_preregistered_grammar import grammar_v101 as v101
from research.elliott_v102_bybit_intake import intake_v102 as v102

SCHEMA="nexus.elliott-v106-causal-two-wave-partial-reversal-grammar.v1"
V105_REL="docs/evidence/elliott-v105-causal-position-20261017/V105_FROZEN_CAUSAL_POSITION.json"
V105_SHA="40d2b2d582a782205e115ddceacc07342f69c41111b6f6f4681785798f343e24"
V105_COMMIT="6d860b9aaffb7297f1f31dade5381650ac603fa0"
EXPECTED_COARSE_EVENTS=6
PRECONTEXT_EVENTS=3
OBSERVABLE_PARTIAL_WAVE_VERTICES=3
EARLY_LEG_FINE_COUNTS=(4,2)
COUNTERFACTUAL_R_MULTIPLE=Decimal("2")
RESEARCH_ONLY=True
ENTRY_SIGNAL=False
PAPER_ELIGIBLE=False
LIVE_ENABLED=False
ORDER_ADAPTER=None
MARKET_WAVE_POSITION_CERTIFIED=False
V52_UNCHANGED=True


def rules()->dict:
    return {
        "schema":SCHEMA,
        "status":"PREREGISTERED_SYNTHETIC_ONLY_NO_MARKET_EVALUATION",
        "source":"BYBIT_PUBLIC_SPOT_CLOSED_1M_ONLY_FOR_FUTURE_REPLAY",
        "future_uninspected_window_start":v101.WINDOW_START_UTC,
        "future_uninspected_window_end_exclusive":v101.WINDOW_END_EXCLUSIVE_UTC,
        "prior_v105_commit":V105_COMMIT,"prior_v105_manifest_sha256":V105_SHA,
        "all_consecutive_coarse_events":EXPECTED_COARSE_EVENTS,
        "prior_context_events":PRECONTEXT_EVENTS,
        "partial_impulse_vertices":OBSERVABLE_PARTIAL_WAVE_VERTICES,
        "required_unpruned_fine_pivots_wave1_wave2":list(EARLY_LEG_FINE_COUNTS),
        "fixed_coarse_to_fine_boundary_price_kind_and_time_match":True,
        "decision_exactly_at_wave2_confirmed_closed_minute":True,
        "wave3_wave4_wave5_not_available_or_consulted":True,
        "predecessor_lower_high_lower_low_for_bull_mirrored_for_bear":True,
        "wave1_positive_and_wave2_strict_retracement_with_no_origin_breach":True,
        "no_degree_certification":True,
        "all_results_are_hypotheses_not_order_admission":True,
        "first_postconfirmation_closed_1m_hypothetical_open_not_fill":True,
        "defensive_stop_origin_wave0":True,
        "counterfactual_r_multiple":str(COUNTERFACTUAL_R_MULTIPLE),
        "both_stop_and_target_one_minute_assume_stop_first":True,
        "market_data_fetched_during_v106":0,
        "evaluated_actual_future_patterns":0,
        "no_earnings_or_pnl_claim":True,
        "entry_signal":False,"paper_eligible":False,
        "live_enabled":False,"orders":0,"v52_unchanged":True,
    }


def freeze(path:Path)->dict:
    if not isinstance(path,Path):
        raise ValueError("explicit future prereg path required")
    from research.elliott_v93_recursive_proof import proof_v93 as v93
    receipt=v93.immutable_receipt(
        V105_REL,V105_SHA,V105_COMMIT,
        "nexus.elliott-v105-causal-position-and-exit-diagnostics.v1")
    if (receipt["real_market_data_read"]!=0 or
        receipt["orders"]!=0 or
        receipt["decision_only_after_last_wave5_right_confirmation"] is not True):
        raise ValueError("frozen V105 source-only chain changed")
    raw=(json.dumps(rules(),sort_keys=True,indent=2,ensure_ascii=False)+"\n").encode()
    if path.exists():
        if path.read_bytes()!=raw:
            raise ValueError("V106 frozen research protocol modified")
    else:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(raw)
    return {"status":"V106_EARLY_TWO_WAVE_RULES_FROZEN_NO_REAL_SOURCE",
            "sha256":hashlib.sha256(raw).hexdigest(),"source_rows_accessed":0,
            "positions":0}


def inspect_partial(
    coarse6:list[v99.ObservedSwing],
    fine:list[v99.ObservedSwing],
    asof:int,
)->dict:
    """One full causal prefix. NEVER load/require any wave-3 to 5.

    All six coarse events *must* be consecutive upstream events, which a
    future caller must attest from the complete pre-decision observer;
    this standalone pure function cannot prove no events were omitted.
    """
    if (type(coarse6) is not list or len(coarse6)!=EXPECTED_COARSE_EVENTS
        or type(fine) is not list or type(asof) is not int
        or asof%v99.MINUTE):
        raise ValueError("exactly six coarse context+partial events required")
    if coarse6[-1].confirmed_ms!=asof:
        raise ValueError("decision must equal wave2 right-confirmation")
    # Full V100 source index/timestamp, unique assignment, no future
    # fine pivot use, two independently obtained scale streams.
    cross=v100.causal_relationships(fine,coarse6,asof)
    old0,old1,old2,w0,w1,w2=coarse6
    direction=Decimal(1) if w0.kind=="LOW" else Decimal(-1)
    prices=[x.center_close*direction for x in coarse6]
    failures=[]
    if [x.kind for x in coarse6]!=(
        ["HIGH","LOW","HIGH","LOW","HIGH","LOW"] if direction>0 else
        ["LOW","HIGH","LOW","HIGH","LOW","HIGH"]):
        failures.append("MISSING_ALTERNATING_CONTEXT")
    if prices[2]>=prices[0]:
        failures.append("PRIOR_TREND_LOWER_HIGH_NOT_ATTESTED")
    if prices[3]>=prices[1]:
        failures.append("PRIOR_TREND_LOWER_LOW_NOT_ATTESTED")
    if prices[4]<=prices[3]:
        failures.append("WAVE1_NO_POSITIVE_DIRECTIONAL_MOVE")
    if prices[5]<=prices[3]:
        failures.append("WAVE2_BREACHES_OR_TOUCHES_WAVE0_ORIGIN")
    if prices[5]>=prices[4]:
        failures.append("WAVE2_NOT_A_STRICT_RETRACE_OF_WAVE1")
    intervals=cross["intervals"][3:]
    if len(intervals)!=2:
        raise ValueError("wave1/wave2 interval extraction error")
    for i,(leg,expected) in enumerate(zip(intervals,EARLY_LEG_FINE_COUNTS)):
        if leg["all_fine_center_interior_count"]!=expected:
            failures.append(f"WAVE{i+1}_UNPRUNED_FINE_COUNT_NOT_PREDECLARED")
        if leg["fine_confirmed_too_late_count"]>0:
            failures.append(f"WAVE{i+1}_FINE_CONFIRMATION_UNAVAILABLE_AT_LEG_END")
        for name,bound in (("LEFT",coarse6[3+i]),("RIGHT",coarse6[4+i])):
            matches=[x for x in fine if
                x.kind==bound.kind and x.center_ms==bound.center_ms
                and x.center_close==bound.center_close
                and x.confirmed_ms<=bound.confirmed_ms]
            if len(matches)!=1:
                failures.append(f"WAVE{i+1}_{name}_CAUSAL_FINE_BOUNDARY_MISMATCH")
    failures=list(dict.fromkeys(failures))
    return {
        "schema":"nexus.elliott-v106-one-causal-partial-window.v1",
        "earliest_first_observable_ms":asof,
        "original_wave0_center_ms":w0.center_ms,
        "wave1_center_ms":w1.center_ms,
        "wave2_center_ms":w2.center_ms,
        "wave2_confirmation_ms":w2.confirmed_ms,
        "direction":"UP" if direction>0 else "DOWN",
        "all_prefix_coarse_digest":cross["all_original_coarse_events_sha256"],
        "all_observable_fine_digest":cross["all_original_fine_events_sha256"],
        "prior_context_centers_ms":[x.center_ms for x in coarse6[:3]],
        "expected_unpruned_counts":list(EARLY_LEG_FINE_COUNTS),
        "observed_unpruned_counts":[x["all_fine_center_interior_count"] for x in intervals],
        "rejections":failures,
        "partial_skeleton_and_context_necessary_pass":not failures,
        "full_five_wave_observed":False,
        "elliott_degree_certified":False,
        "market_wave_position_proven":False,
        "new_trade_entry_signal":False,"paper_eligible":False,
        "live_enabled":False,"net_pnl":None,
    }


def counterfactual_first_complete_minute(
    coarse6:list[v99.ObservedSwing],
    fine:list[v99.ObservedSwing],
    candle:v102.Candle,
    evaluation_asof:int,
)->dict:
    """No actual order. Uses the first *completed* minute only AFTER w2.

    The hypothetical bar OPEN and its OHLC are only known RETROSPECTIVELY
    at the end of that minute, so this output cannot be backfilled as an
    actual market fill or used to estimate profit.
    """
    if type(candle) is not v102.Candle or (
        type(evaluation_asof) is not int or
        evaluation_asof%v99.MINUTE):
        raise ValueError("physical source minute and closed asof required")
    if (type(candle.ms) is not int or
        candle.ms+v99.MINUTE!=evaluation_asof):
        raise ValueError("first hypothetical source bar must be fully closed")
    for number in (candle.open,candle.high,candle.low,candle.close,
                   candle.volume,candle.turnover):
        if type(number) is not Decimal or not number.is_finite():
            raise ValueError("untrusted/nonfinite OHLC physical source")
    if (not 0<candle.low<=candle.open<=candle.high or
        not candle.low<=candle.close<=candle.high or
        candle.volume<0 or candle.turnover<0):
        raise ValueError("inconsistent source OHLC or negative volume")
    prior=inspect_partial(coarse6,fine,candle.ms)
    direction=Decimal(1) if prior["direction"]=="UP" else Decimal(-1)
    stop=coarse6[3].center_close
    nominal_open=candle.open
    risk=(nominal_open-stop)*direction
    failures=list(prior["rejections"])
    if risk<=0:
        failures.append("FIRST_OPEN_BEYOND_OR_AT_WAVE0_DEFENSIVE_STOP")
    target=None
    label="ABSTAIN_CONTEXT_OR_RISK_NOT_VERIFIED"
    if not failures:
        target=nominal_open+direction*COUNTERFACTUAL_R_MULTIPLE*risk
        hit_stop=(candle.low<=stop if direction>0 else candle.high>=stop)
        hit_target=(candle.high>=target if direction>0 else candle.low<=target)
        if hit_stop and hit_target:
            label="BOTH_LEVELS_TOUCHED_ASSUME_STOP_FIRST"
        elif hit_stop:
            label="HYPOTHETICAL_STOP_TOUCHED"
        elif hit_target:
            label="HYPOTHETICAL_TARGET_TOUCHED"
        else:
            label="NO_EXIT_SEEN_IN_FIRST_CLOSED_MINUTE"
    return {
        "schema":"nexus.elliott-v106-no-fill-first-closed-minute-diagnostic.v1",
        "original_partial_skeleton_confirmed_at_ms":prior["wave2_confirmation_ms"],
        "minute_open_timestamp_ms":candle.ms,
        "minute_ohlc_not_known_until_ms":evaluation_asof,
        "hypothetical_open_from_just_closed_minute_not_real_fill":str(nominal_open),
        "hypothetical_stop_at_wave0_center":str(stop),
        "hypothetical_target_2r":str(target) if target is not None else None,
        "nominal_stop_distance":str(risk),
        "original_necessary_partial_skeleton_pass":prior[
            "partial_skeleton_and_context_necessary_pass"],
        "rejections":failures,
        "conservative_one_bar_outcome":label,
        "intraminute_order_unknown_assume_stop_first":True,
        "no_historical_wave3_or_wave5_leakage":True,
        "not_a_filled_order":True,
        "entry_signal":False,"paper_eligible":False,
        "live_enabled":False,"net_pnl":None,
    }
