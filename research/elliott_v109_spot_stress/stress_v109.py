"""V109 frozen hypothetical spot-long cost/latency/exit diagnostic.

NEVER an actual Bybit fill/backtest. V107/V108 original candidate and
outcome ledgers are separately frozen; future price outcomes cannot
revise original decisions. Synthetic fixed fee/spread/slippage stress
assumptions are NOT verified Bybit account charges. Public Spot data
cannot authorize short/margin fills. No network/broker/credential code.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path

from research.elliott_v99_causal_scale import scale_v99 as v99
from research.elliott_v101_preregistered_grammar import grammar_v101 as v101
from research.elliott_v102_bybit_intake import intake_v102 as v102
from research.elliott_v104_independent_challenger import challenger_v104 as v104
from research.elliott_v107_prefix_census import census_v107 as v107
from research.elliott_v108_forward_outcomes import outcomes_v108 as v108

SCHEMA="nexus.elliott-v109-spot-long-latency-stress-screen.v1"
PARENT_V108_COMMIT="0432359ad4724cc886c5e6414aafc8e5ba749747"
PARENT_V108_REL="docs/evidence/elliott-v108-forward-outcomes-20261017/V108_FROZEN_BARRIER_OUTCOMES_RULEBOOK.json"
PARENT_V108_SHA="0777098b0801f8753df6a1743a9bbe8a4dcf9df5048a5e7e1aa78d3f65ee81a8"
LATENCY_COMPLETE_1M=1
FOLLOWUP_1M=v108.HORIZON_CLOSED_1M
FEE_BPS_EACH_SIDE=Decimal("10")
HALF_SPREAD_BPS_EACH_SIDE=Decimal("2")
SLIPPAGE_BPS_EACH_SIDE=Decimal("5")
PER_SIDE_STRESS_BPS=FEE_BPS_EACH_SIDE+HALF_SPREAD_BPS_EACH_SIDE+SLIPPAGE_BPS_EACH_SIDE
PER_SIDE_COST=PER_SIDE_STRESS_BPS/Decimal("10000")
RESEARCH_ONLY=True
ORDER_ADAPTER=None
ENTRY_SIGNAL=False
PAPER_ELIGIBLE=False
LIVE_ENABLED=False
V52_UNCHANGED=True

CATEGORIES=(
    "REJECTED_ORIGINAL_V107_GATE",
    "SPOT_SHORT_UNSUPPORTED_NO_BORROW_ASSUMED",
    "NONCOMPARABLE_ORIGINAL_BARRIERS",
    "CENSORED_BEFORE_LATENCY_ENTRY",
    "LATENCY_BARRIER_TOUCHED_ABSTAIN",
    "SECOND_BAR_OPEN_OUTSIDE_STOP_TARGET_ABSTAIN",
    "STRESS_COST_REMOVES_POSITIVE_REWARD",
    "STRESS_ORIGIN_STOP_FIRST",
    "STRESS_SAME_BAR_BOTH_ASSUME_STOP_FIRST",
    "STRESS_WAVE1_TARGET_TOUCH",
    "STRESS_NO_EXIT_WITHIN_FIXED_HORIZON",
    "STRESS_RIGHT_CENSORED_UNCLOSED_POSITION",
)

def manifest()->dict:
    return {
        "schema":SCHEMA,
        "status":"PREDECLARED_SYNTHETIC_ONLY_NOT_A_TRADABLE_STRATEGY",
        "parent_v108_commit":PARENT_V108_COMMIT,
        "parent_v108_rulebook_sha256":PARENT_V108_SHA,
        "preregistered_future_start_utc":v101.WINDOW_START_UTC,
        "preregistered_future_end_exclusive_utc":v101.WINDOW_END_EXCLUSIVE_UTC,
        "Bybit_public_source_category":"spot",
        "symbols":list(v101.PAIRS),
        "both_accepted_and_rejected_v107_windows_counted":True,
        "v108_observation_ledger_fingerprint_must_match":True,
        "hypothetical_direction":"LONG_ONLY_SPOT_NO_MARGIN_OR_SHORT",
        "short_market_context_kept_but_execution_abstains":True,
        "first_full_minute_after_decision_is_latency_observation_only":True,
        "abstain_if_either_reference_barrier_touched_during_latency":True,
        "hypothetical_entry_open_of_second_closed_minute_not_actual_fill":True,
        "latency_complete_one_minute_bars":LATENCY_COMPLETE_1M,
        "fee_each_side_bps_assumed_not_verified_Bybit":str(FEE_BPS_EACH_SIDE),
        "half_spread_each_side_bps_assumed":str(HALF_SPREAD_BPS_EACH_SIDE),
        "slippage_each_side_bps_assumed":str(SLIPPAGE_BPS_EACH_SIDE),
        "per_side_additive_total_bps":str(PER_SIDE_STRESS_BPS),
        "stress_only_not_actual_Bybit_exchange_rate":True,
        "target_barrier_wave1_not_optimized":True,
        "stop_barrier_wave0_not_order_placed":True,
        "first_touch_after_delayed_entry_and_within_v108_240min_horizon":True,
        "simultaneous_stop_target_one_bar_assume_stop":True,
        "gap_below_stop_worse_open_overrides_stop":True,
        "unresolved_position_not_counted_as_closed_or_profitable":True,
        "right_censoring_not_counted_as_zero_return":True,
        "fee_stress_net_R_is_illustrative_not_verified_pnl":True,
        "no_intraminute_path_or_actual_fill_assumed":True,
        "not_measured":["Bybit_spread","Bybit_fees","Bybit_slippage","actual_fill",
                        "real_net_pnl","portfolio_return","win_rate","Elliott_truth"],
        "zero_real_market_rows_accessed_during_v109":True,
        "orders":0,"paper_eligible":False,"entry_signal":False,
        "live_enabled":False,"v52_unchanged":True,
    }


def manifest_bytes()->bytes:
    return (json.dumps(manifest(),sort_keys=True,indent=2)+"\n").encode()


def freeze_manifest(path:Path)->dict:
    if not isinstance(path,Path):
        raise ValueError("explicit frozen V109 path required")
    from research.elliott_v93_recursive_proof import proof_v93 as v93
    prev=v93.immutable_receipt(PARENT_V108_REL,PARENT_V108_SHA,
                              PARENT_V108_COMMIT,v108.SCHEMA)
    if (prev["market_outcomes_evaluated_during_v108"]!=0 or
        prev["orders"]!=0 or
        prev["fixed_followup_closed_one_minute_bars"]!=240):
        raise ValueError("original future-only V108 protocol changed")
    raw=manifest_bytes()
    if path.exists():
        if path.read_bytes()!=raw:
            raise ValueError("V109 original frozen cost protocol modified")
    else:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(raw)
    return {"status":"V109_FROZEN_SYNTHETIC_STRESS_ONLY",
            "sha256":hashlib.sha256(raw).hexdigest(),
            "market_rows_fetched":0,"actual_orders":0}


def _validate_original_six(six:list[v99.ObservedSwing],cutoff:int)->tuple[Decimal,Decimal]:
    if (type(six) is not list or len(six)!=6 or
        any(type(x) is not v99.ObservedSwing for x in six) or
        type(cutoff) is not int or six[-1].confirmed_ms!=cutoff):
        raise ValueError("original six causal source pivots required")
    if any(x.confirmed_ms>cutoff for x in six):
        raise ValueError("unconfirmed coarse source is future information")
    wave0,wave1=six[3].center_close,six[4].center_close
    if (type(wave0) is not Decimal or type(wave1) is not Decimal
        or not wave0.is_finite() or not wave1.is_finite()
        or wave0<=0 or wave1<=0):
        raise ValueError("untrusted wave reference prices")
    return wave0,wave1


def stress_one_synthetic_window(
    six:list[v99.ObservedSwing],
    original_gate_pass:bool,
    after:list[v102.Candle],
    original_cutoff_ms:int,
    source_end_exclusive:int,
)->dict:
    """All bars are ORIGINAL closed OHLC and postdate original decision.

    This function never submits orders and never estimates a real fill.
    Only synthetic fixtures are used in V109. Adverse cost on entry+exit
    is fixed, with a one-full-minute synthetic latency barrier guard.
    """
    wave0,wave1=_validate_original_six(six,original_cutoff_ms)
    if type(original_gate_pass) is not bool:
        raise ValueError("original frozen acceptance flag required")
    observation=v108.first_barrier_outcome(
        six,original_cutoff_ms,after,source_end_exclusive)
    if original_gate_pass is False:
        category="REJECTED_ORIGINAL_V107_GATE"
    elif six[3].kind!="LOW":
        category="SPOT_SHORT_UNSUPPORTED_NO_BORROW_ASSUMED"
    elif wave1<=wave0:
        category="NONCOMPARABLE_ORIGINAL_BARRIERS"
    elif not after or len(after)<LATENCY_COMPLETE_1M+1:
        category="CENSORED_BEFORE_LATENCY_ENTRY"
    else:
        latency=after[0]
        if latency.low<=wave0 or latency.high>=wave1:
            category="LATENCY_BARRIER_TOUCHED_ABSTAIN"
        else:
            candidate_open=after[1].open
            if not wave0<candidate_open<wave1:
                category="SECOND_BAR_OPEN_OUTSIDE_STOP_TARGET_ABSTAIN"
            elif candidate_open*(Decimal(1)+PER_SIDE_COST)>=wave1*(Decimal(1)-PER_SIDE_COST):
                category="STRESS_COST_REMOVES_POSITIVE_REWARD"
            else:
                category=None
    exit_reference=None
    projected_entry=None
    net_r=None
    exit_minute=None
    if category is None:
        projected_entry=after[1].open*(Decimal(1)+PER_SIDE_COST)
        risk=projected_entry-wave0
        if risk<=0:
            raise ValueError("physically inconsistent stressed long entry risk")
        # The second minute's OPEN is a *retrospective* reference price.
        # The OHLC only exists after that candle closes. Do not infer a
        # real entry fill at this opening price.
        for i in range(1,len(after)):
            bar=after[i]
            bad=bar.low<=wave0
            good=bar.high>=wave1
            if bad:
                category=("STRESS_SAME_BAR_BOTH_ASSUME_STOP_FIRST" if good else
                          "STRESS_ORIGIN_STOP_FIRST")
                exit_reference=min(wave0,bar.open)
            elif good:
                category="STRESS_WAVE1_TARGET_TOUCH"
                exit_reference=wave1
            if category is not None:
                exit_minute=i+1
                stressed_exit=exit_reference*(Decimal(1)-PER_SIDE_COST)
                net_r=(stressed_exit-projected_entry)/risk
                break
        if category is None:
            category=("STRESS_RIGHT_CENSORED_UNCLOSED_POSITION"
                      if len(after)<FOLLOWUP_1M else
                      "STRESS_NO_EXIT_WITHIN_FIXED_HORIZON")
    if category not in CATEGORIES:
        raise ValueError("not a predeclared execution-stress abstention/outcome")
    return {
        "schema":"nexus.elliott-v109-one-no-trade-long-stress-diagnostic.v1",
        "original_decision_ms":original_cutoff_ms,
        "original_gate_pass":original_gate_pass,
        "original_v108_outcome":observation["outcome"],
        "original_v108_observation_digest":hashlib.sha256(
            json.dumps(observation,sort_keys=True).encode()).hexdigest(),
        "hypothetical_latency_minutes":LATENCY_COMPLETE_1M,
        "followup_observed_complete_minutes":len(after),
        "category":category,
        "hypothetical_long_entry_after_stress":(
            str(projected_entry) if projected_entry is not None else None),
        "hypothetical_barrier_exit_reference":(
            str(exit_reference) if exit_reference is not None else None),
        "first_exit_touch_lag_completed_minutes":exit_minute,
        "illustrative_net_R_after_fixed_cost_stress":(
            str(net_r) if net_r is not None else None),
        "illustrative_R_is_not_realized_profit":True,
        "real_fill_or_fee_verified":False,
        "real_order":False,"entry_signal":False,
        "paper_eligible":False,"live_enabled":False,
        "actual_net_pnl":None,
    }


def stress_every_original_window(
    original_v107:dict,
    original_v108:dict,
    coarse:list[v99.ObservedSwing],
    physical_bars:list[v102.Candle],
)->dict:
    """Read-only research output for exactly all frozen source windows."""
    start,end=v108.validate_physical_candles(physical_bars)
    rederived=v108.assess_every_v107_window(original_v107,coarse,physical_bars)
    # The authenticated-by-two-parsers future V108 adapter appends exactly
    # three source-provenance fields to this base diagnostic. Compare every
    # original decision/outcome field, and independently verify the appended
    # source witness instead of dropping it or tolerating arbitrary extras.
    verified_fields={
        "physical_source_sha256","source_candles","authenticity_caveat",
    }
    extra=set(original_v108)-set(rederived)
    core={k:v for k,v in original_v108.items() if k in rederived}
    if core!=rederived or extra not in (set(),verified_fields):
        raise ValueError("V108 ORIGINAL OUTCOME LEDGER REWRITTEN OR MISMATCHED")
    if extra:
        physical_rows=[[c.ms,str(c.open),str(c.high),str(c.low),
                        str(c.close),str(c.volume),str(c.turnover)]
                       for c in physical_bars]
        original_bytes=json.dumps(
            physical_rows,ensure_ascii=False,separators=(",",":")).encode()
        source_digest=hashlib.sha256(original_bytes).hexdigest()
        if (original_v108["source_candles"]!=len(physical_bars)
            or original_v108["physical_source_sha256"]!=source_digest
            or original_v108["authenticity_caveat"]!=
              "two_offline_parsers_same_archive_not_Bybit_payload_signature"):
            raise ValueError("V108 audited provenance conflicts with source bytes")
    originals=original_v107["candidate_ledger"]
    if len(originals)!=max(0,len(coarse)-5):
        raise ValueError("source census count changed")
    ledger=[]
    stats={"necessary_pass":Counter(),"necessary_reject":Counter()}
    for index,parent in enumerate(original_v108["separate_forward_only_outcome_ledger"]):
        six=coarse[index:index+6]
        moment=six[-1].confirmed_ms
        begin=(moment-start)//v99.MINUTE
        after=physical_bars[begin:begin+FOLLOWUP_1M]
        original=originals[index]
        if (parent["original_window_ordinal"]!=index or
            parent["original_six_coarse_sha256"]!=original["coarse_window_sha256"]
            or parent["original_predecision_fine_sha256"]!=original[
                "visible_fine_stream_sha256"] or
            parent["original_gate_pass"]!=original[
                "necessary_partial_skeleton_pass"]):
            raise ValueError("original V107 gate or V108 outcome altered")
        record=stress_one_synthetic_window(
            six,parent["original_gate_pass"],after,moment,end)
        observation_digest=hashlib.sha256(json.dumps(
            parent["forward_observation"],sort_keys=True).encode()).hexdigest()
        if record["original_v108_observation_digest"]!=observation_digest:
            raise ValueError("V108 future-only observation was switched")
        group="necessary_pass" if parent["original_gate_pass"] else "necessary_reject"
        stats[group][record["category"]]+=1
        ledger.append({
            "original_window_ordinal":index,
            "original_predecision_sha":original["coarse_window_sha256"],
            "original_wave2_decision_ms":moment,
            "original_gate_pass":parent["original_gate_pass"],
            "cost_stress_no_order":record,
        })
    if (len(ledger)!=original_v108["original_v107_candidate_count"]
        or sum(sum(c.values()) for c in stats.values())!=len(ledger)):
        raise ValueError("silent suppression of rejected or unresolved candidates")
    if (sum(stats["necessary_pass"].values())!=original_v107[
            "necessary_partial_skeleton_passes"] or
        sum(stats["necessary_reject"].values())!=original_v107[
            "necessary_partial_skeleton_rejections"]):
        raise ValueError("original denominator rewritten by future data")
    return {
        "schema":"nexus.elliott-v109-all-originals-cost-stress-only.v1",
        "all_original_v107_candidates":len(ledger),
        "all_source_evaluations_one_for_each_original":True,
        "original_necessary_pass_count":original_v107[
            "necessary_partial_skeleton_passes"],
        "original_necessary_reject_count":original_v107[
            "necessary_partial_skeleton_rejections"],
        "status_by_original_gate":{
            group:dict(sorted(count.items()))
            for group,count in stats.items()},
        "candidate_ledger":ledger,
        "requires_another_independent_Bybit_market_source_audit":True,
        "no_real_spot_execution_or_margin_short_model":True,
        "no_actual_net_pnl_or_win_rate":True,
        "market_profitability_proven":False,
        "paper_eligible":False,"entry_signal":False,
        "live_enabled":False,"orders":0,"actual_net_pnl":None,
    }


def evaluate_future_archive_only(folder:Path)->dict:
    """After Nov 30 only; run original V108 source gates first; no HTTP."""
    if not isinstance(folder,Path):
        raise ValueError("explicit original future archive Path required")
    end=v102.locked_range()[1]
    if int(datetime.now(timezone.utc).timestamp()*1000)<end:
        raise ValueError("FUTURE_WINDOW_INCOMPLETE_NO_ARCHIVE_READ")
    from research.elliott_v93_recursive_proof import proof_v93 as v93
    v93.immutable_receipt(PARENT_V108_REL,PARENT_V108_SHA,
                          PARENT_V108_COMMIT,v108.SCHEMA)
    predecessor=v108.evaluate_future_archive_only(folder)
    output={
        "schema":"nexus.elliott-v109-postwindow-source-gated-stress-only.v1",
        "frozen_V108_SHA256":PARENT_V108_SHA,
        "not_market_profitability_evidence":True,
        "not_crypto_signed_by_Bybit":True,
        "symbols":{},
        "orders":0,"paper_eligible":False,"entry_signal":False,
        "live_enabled":False,"net_pnl":None,
    }
    for symbol in v101.PAIRS:
        original=predecessor["all_symbols"][symbol]
        all7=[]
        for page in v104.descriptors():
            if page["symbol"]!=symbol:
                continue
            raw=(folder/(page["stem"]+".raw.json")).read_bytes()
            receipt=(folder/(page["stem"]+".receipt.json")).read_bytes()
            all7.extend(v104.validate_independent_page(page,raw,receipt)["candles"])
        canonical=json.dumps(all7,ensure_ascii=False,separators=(",",":")).encode()
        if (len(all7)!=v101.COMPLETE_SOURCE_ROWS_PER_PAIR or
            hashlib.sha256(canonical).hexdigest()!=original["physical_source_sha256"]):
            raise ValueError("source changed between original V108 and V109 audit")
        bars=[v102.Candle(int(x[0]),*(Decimal(y) for y in x[1:]))
              for x in all7]
        start,last=v108.validate_physical_candles(bars)
        if (start!=v102.locked_range()[0] or last!=end):
            raise ValueError("postwindow source range replaced")
        closed=[v99.CloseMinute(x.ms,x.close) for x in bars]
        fine=v99.observe_scale(closed,v101.FINE_SCALE,end)
        coarse=v99.observe_scale(closed,v101.COARSE_SCALE,end)
        original_v107=v107.enumerate_event_prefixes(fine,coarse,end)
        cost=stress_every_original_window(original_v107,original,coarse,bars)
        cost["physical_source_rows"]=len(bars)
        cost["physical_source_sha256"]=original["physical_source_sha256"]
        output["symbols"][symbol]=cost
    return output


def status()->dict:
    return {"status":"V109_RULES_ONLY_NO_FUTURE_MARKET_SOURCE",
            "original_market_rows_evaluated":0,
            "real_positions":0,"paper_eligible":False,
            "live_enabled":False}


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--mode",choices=("status","future-offline-stress"),
                        default="status")
    parser.add_argument("--archive",type=Path)
    args=parser.parse_args()
    if args.mode=="status":
        print(json.dumps(status(),sort_keys=True,indent=2))
    else:
        if args.archive is None:
            parser.error("--archive is required after future window closes")
        print(json.dumps(evaluate_future_archive_only(args.archive),
                         sort_keys=True,indent=2))
