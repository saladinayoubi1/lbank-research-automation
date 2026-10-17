"""V113 no-sampling streaming proof of V111 causal 500-USDT capacity events.

Unlike V112, this proof computes V111 full source state ONCE, independently
verifies each matured two-minute reference from physical OHLC, and scans the
original V110 cash event journal ONCE in timestamp order. Every mandatory
checkpoint gets its own hash-equivalent exact event prefix and risk/cash
balance without re-running V111 on the entire growing original sample.
Small fixtures MUST also match V112's expensive true prefix replays.
For large inputs this is a DIFFERENT proof technique; never claim full
prefix recomputation at every checkpoint.
No source HTTP, broker orders, or real performance is involved.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

from research.elliott_v99_causal_scale import scale_v99 as v99
from research.elliott_v101_preregistered_grammar import grammar_v101 as v101
from research.elliott_v102_bybit_intake import intake_v102 as v102
from research.elliott_v104_independent_challenger import challenger_v104 as v104
from research.elliott_v108_forward_outcomes import outcomes_v108 as v108
from research.elliott_v110_portfolio_capacity import capacity_v110 as v110
from research.elliott_v111_source_capacity import bridge_v111 as v111
from research.elliott_v112_prefix_audit import audit_v112 as v112

SCHEMA="nexus.elliott-v113-streaming-all-checkpoint-portfolio-proof.v1"
PARENT_COMMIT="272618d12932bcde1df1ce0a214425b2e3e386f0"
PARENT_SHA="c15cb6a11b5077e22f8759a3cc75ad0429434103f2f42a00bb9a72ea5356c34e"
PARENT_REL="docs/evidence/elliott-v112-prefix-audit-20261017/V112_FROZEN_PREFIX_REPLAY_AUDIT.json"
RESEARCH_ONLY=True
ENTRY_SIGNAL=False
PAPER_ELIGIBLE=False
LIVE_ENABLED=False
ORDER_ADAPTER=None
V52_UNCHANGED=True


def rules()->dict:
    return {
        "schema":SCHEMA,
        "stage":"FROZEN_RESEARCH_PROOF_NO_MARKET_CANDLES",
        "prior_v112_commit":PARENT_COMMIT,
        "prior_v112_sha256":PARENT_SHA,
        "future_source_start":v101.WINDOW_START_UTC,
        "future_source_end_exclusive":v101.WINDOW_END_EXCLUSIVE_UTC,
        "symbols":list(v101.PAIRS),
        "source":"BYBIT_PUBLIC_SPOT_1M_POSTWINDOW_OFFLINE_ONLY",
        "one_full_v111_original_reconstruction":True,
        "all_confirmed_six_coarse_windows_counted":True,
        "all_coarse_candidate_right_confirmation_checkpoints":True,
        "all_two_closed_minute_reference_checkpoints":True,
        "all_original_cash_event_known_at_checkpoints":True,
        "initial_and_final_closed_source_minute_checkpoints":True,
        "none_sampled_or_silently_dropped":True,
        "v112_fixed_4096_checkpoint_cap_not_reused":True,
        "event_log_verified_incrementally_from_closed_observations":True,
        "original_six_wave_candidate_geometry_source_is_immutable":True,
        "matured_reference_screen_rederived_from_original_ohlc":True,
        "same_source_sealed_provenance_checked_by_v111_v112_overlay":True,
        "exact_replay_sha256_compatible_with_v112_at_every_checkpoint":True,
        "crosscheck_with_v112_full_differential_on_small_fixtures":True,
        "streaming_proof_not_equivalent_to_expensive_full_prefix_recomputation":True,
        "each_checkpoint_source_temporal_constraints_enforced":True,
        "cash_and_risk_reserve_reconciled_per_original_event":True,
        "no_unknown_source_exit_frees_reserved_capital":True,
        "late_closure_cannot_edit_past":True,
        "not_proof_of_authentic_exchange_signature":True,
        "no_real_elliott_truth_or_profitability_claim":True,
        "future_market_rows_read_during_v113":0,
        "orders":0,"paper_eligible":False,"entry_signal":False,
        "live_enabled":False,"v52_unchanged":True,
    }


def freeze(path:Path)->dict:
    if not isinstance(path,Path):
        raise ValueError("explicit future rulebook file required")
    from research.elliott_v93_recursive_proof import proof_v93 as v93
    upstream=v93.immutable_receipt(PARENT_REL,PARENT_SHA,
                                    PARENT_COMMIT,v112.SCHEMA)
    if (upstream["orders"]!=0
        or upstream["no_cutoff_sampling_or_random_skipping"] is not True
        or upstream["live_enabled"] is not False):
        raise ValueError("upstream V112 immutable causality policy changed")
    raw=(json.dumps(rules(),sort_keys=True,indent=2)+"\n").encode()
    if path.exists():
        if path.read_bytes()!=raw:
            raise ValueError("V113 FROZEN RULEBOOK CHANGED")
    else:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(raw)
    return {"state":"V113_CAUSAL_STREAMING_RULES_FROZEN",
            "sha256":sha256(raw).hexdigest(),
            "actual_market_candles":0,"orders":0}


def all_checkpoint_timestamps(start:int,end:int,
                               candidate_confirmations:list[int],
                               known_cash_events:list[int])->list[int]:
    """No count limit, no random sampling; strict complete-minute times."""
    if (type(start) is not int or type(end) is not int or
        not start<end or start%v99.MINUTE or end%v99.MINUTE):
        raise ValueError("untrusted complete-minute source period")
    points={start+v99.MINUTE,end}
    for ts in candidate_confirmations+known_cash_events:
        if type(ts) is not int or ts%v99.MINUTE or not start<ts<=end:
            raise ValueError("future/misaligned original mandatory checkpoint")
        points.add(ts)
    return sorted(points)


def _physical_mature_screen(screen:dict,coarse:list,
                             bars:list,source_start:int,
                             source_end:int)->None:
    """Check the final mature V111 Wave1/2 reference from original 2 bars.

    Only invoked once the source reference becomes observable, not used
    to create any earlier candidate. Both rejected and bearish original
    candidate statuses are preserved without consulting later bars.
    """
    i=screen["original_v107_ordinal"]
    six=coarse[i:i+6]
    if len(six)!=6 or screen["original_v107_decision_asof_ms"]!=six[-1].confirmed_ms:
        raise ValueError("mature candidate index or original cutoff altered")
    t=six[-1].confirmed_ms
    w0,w1=six[3].center_close,six[4].center_close
    original_pass=screen["original_v107_necessary_screen_pass"]
    if original_pass is False:
        expected="ORIGINAL_V107_NECESSARY_SCREEN_REJECTED"
        evidence={}
    elif six[3].kind!="LOW":
        expected="BEAR_CANNOT_OPEN_SPOT_SHORT"
        evidence={}
    elif not 0<w0<w1:
        expected="NONCOMPARABLE_WAVE0_WAVE1_PRICE_LEVELS"
        evidence={}
    elif t<source_start or (t-source_start)%v99.MINUTE:
        raise ValueError("source candidate Wave2 cutoff forged")
    elif t+2*v99.MINUTE>source_end:
        expected="RIGHT_CENSORED_BEFORE_CLOSED_REFERENCE"
        evidence={}
    else:
        idx=(t-source_start)//v99.MINUTE
        first,second=bars[idx:idx+2]
        if first.ms!=t or second.ms!=t+v99.MINUTE:
            raise ValueError("missing first two physical 1m source bars")
        evidence={
            "original_wave2_right_confirmation_ms":t,
            "first_closed_latency_minute_known_ms":first.ms+v99.MINUTE,
            "second_close_reference_known_ms":second.ms+v99.MINUTE,
            "reference_source_price":str(second.close),
        }
        if (first.low<=w0 or first.high>=w1 or
            second.low<=w0 or second.high>=w1):
            expected="BARRIER_TOUCHED_BEFORE_CLOSED_REFERENCE"
        elif not w0<second.close<w1:
            expected="SECOND_CLOSED_REFERENCE_OUTSIDE_WAVE_BARRIERS"
        else:
            expected="SOURCE_CAUSAL_SPOT_LONG_REFERENCE_ONLY"
    if (screen["reference_screen_status"]!=expected or
        screen["closed_reference_evidence"]!=evidence):
        raise ValueError("FUTURE_PRICE_REWROTE_MATURED_REFERENCE_SCREEN")


def audit_streaming(series:dict,provided_final:dict|None=None)->dict:
    """Incremental event proof; V112 is reference oracle on smaller cases.

    Efficient in number of mandatory checkpoints, original source pivots,
    original V111 original events, and at most 240 close bars per admitted
    release. Does NOT call V111 separately at each checkpoint.
    """
    start,end=v112._original_series(series)
    final=v111.portfolio_census_from_source_streams(series)
    if provided_final is not None and provided_final!=final:
        raise ValueError("V111_FINAL_CANDIDATE_OR_CAPACITY_LEDGER_TAMPERED")
    cash=final["cash_capacity_v110"]
    events=cash["append_only_causal_event_ledger"]
    by_symbol={}
    screen_by_id={}
    confirmations=[]
    intended_times=[]
    for sym,(coarse,fine,bars) in sorted(series.items()):
        times=[x.confirmed_ms for x in coarse]
        if times!=sorted(times) or any(type(t) is not int for t in times):
            raise ValueError("original coarse order not confirmed")
        by_symbol[sym]=times
        source=final["all_original_candidate_reference_screens"]
        screens=[x for x in source if x["symbol"]==sym]
        if len(screens)!=max(0,len(coarse)-5):
            raise ValueError("original source candidate window silently missing")
        for i,screen in enumerate(screens):
            if screen["original_v107_ordinal"]!=i:
                raise ValueError("original event ordinal tampered")
            _physical_mature_screen(screen,coarse,bars,start,end)
            t=screen["original_v107_decision_asof_ms"]
            if not start<=t<=end or t%v99.MINUTE:
                raise ValueError("original decision timestamp not in physical source")
            if t>start:
                confirmations.append(t)
            if t+2*v99.MINUTE<=end:
                confirmations.append(t+2*v99.MINUTE)
            if screen["reference_screen_status"]==(
                "SOURCE_CAUSAL_SPOT_LONG_REFERENCE_ONLY"):
                k=f"{sym}-W{i:06d}"
                if k in screen_by_id:
                    raise ValueError("duplicate original proposed identifier")
                screen_by_id[k]=(screen,coarse[i+4].center_close,bars)
                intended_times.append(t+2*v99.MINUTE)
    if len(final["all_original_candidate_reference_screens"])!=final[
            "all_v107_candidate_windows"]:
        raise ValueError("all original source candidates not accounted")
    all_times=all_checkpoint_timestamps(
        start,end,confirmations,[e["known_at_ms"] for e in events])
    entry_reference_times=sorted(intended_times)
    num_candidates=final["all_v107_candidate_windows"]
    if len(entry_reference_times)!=final["all_source_reference_proposals"]:
        raise ValueError("proposals omitted despite mature reference")
    if len(cash["original_admission_outcomes"])!=len(entry_reference_times):
        raise ValueError("capacity ledger omitted or doubled original proposal")
    if any(e["known_at_ms"]>end or e["known_at_ms"]<start
           for e in events):
        raise ValueError("invalid event-time source range")
    if any(events[i]["known_at_ms"]>events[i+1]["known_at_ms"]
           for i in range(len(events)-1)):
        raise ValueError("cash journal not ordered by known-at timestamp")
    # The journal's exact prefix sha256 equals json.dumps(list_of_events,
    # sort_keys=True,ensure_ascii=False) without materializing each prefix.
    hashed=sha256()
    hashed.update(b"[")
    event_ptr=0
    reserved=Decimal(0)
    risk_reserved=Decimal(0)
    active={}
    original_admitted={}
    proof=[]
    for when in all_times:
        while event_ptr<len(events) and events[event_ptr]["known_at_ms"]<=when:
            e=events[event_ptr]
            when_e=e["known_at_ms"]
            candidate=e["candidate_id"]
            if type(when_e) is not int or when_e%v99.MINUTE:
                raise ValueError("nonclosing original event timestamp")
            if candidate not in screen_by_id:
                raise ValueError("unknown or noncausal original source candidate")
            screen,wave1,bars=screen_by_id[candidate]
            ref_time=screen["original_v107_decision_asof_ms"]+2*v99.MINUTE
            if when_e<ref_time:
                raise ValueError("FUTURE_REFERENCE_GRANTED_BEFORE_BAR_CLOSED")
            kind=e["event"]
            if kind=="SYNTHETIC_CAPACITY_RESERVED_NOT_ORDER":
                if candidate in original_admitted:
                    raise ValueError("duplicate research proposal admission")
                notional=Decimal(e["hypothetical_notional_usdt"])
                required=Decimal(e["hypothetical_buy_cash_plus_entry_stress_usdt"])
                risk=Decimal(e["assumed_gapless_stressed_loss_reserve_usdt"])
                stop=screen["closed_reference_evidence"]["reference_source_price"]
                hypothetical=v110.Intent(candidate,screen["symbol"],"BUY_SPOT",
                     ref_time,ref_time,Decimal(stop),
                     # This is the immutable already-confirmed Wave0 pivot.
                     series[screen["symbol"]][0][screen["original_v107_ordinal"]+3].center_close)
                if (when_e!=ref_time or not 0<notional<=v110.MAX_POSITION_USDT
                    or required!=notional*(Decimal(1)+v110.COST_RATE)
                    or risk!=notional*v110._risk_rate(hypothetical)
                    or len(active)>=v110.MAX_ACTIVE
                    or any(v["symbol"]==screen["symbol"] for v in active.values())
                    or required+reserved>v110.CASH
                    or risk+risk_reserved>v110.MAX_AGGREGATE_OPEN_RISK_USDT
                    or risk>v110.MAX_RISK_PER_RESERVATION_USDT):
                    raise ValueError("cash admission contradicts original causal capacity")
                active[candidate]={"symbol":screen["symbol"],
                                   "cash":required,"risk":risk}
                original_admitted[candidate]="HYPOTHETICAL_RESERVED"
                reserved+=required
                risk_reserved+=risk
            elif kind=="DENIED_CAPACITY_OR_SOURCE":
                if candidate in original_admitted or when_e!=ref_time:
                    raise ValueError("forged or mistimed original denied proposal")
                original_admitted[candidate]="DENIED_"+e["reason"]
            elif kind=="RELEASE_KNOWN":
                if candidate not in active or when_e<ref_time:
                    raise ValueError("release before actual known entry reservation")
                screen,w1,physical=screen_by_id[candidate]
                original=v110.Intent(
                    candidate,screen["symbol"],"BUY_SPOT",ref_time,ref_time,
                    Decimal(screen["closed_reference_evidence"]["reference_source_price"]),
                    series[screen["symbol"]][0][screen["original_v107_ordinal"]+3].center_close)
                from_source,label=v111._find_known_barrier_release(
                    original,screen["original_v107_decision_asof_ms"],w1,physical)
                if (from_source is None or from_source.known_at_ms!=when_e
                    or from_source.observed_closed_ms!=e["observed_closed_ms"]
                    or e["reason"]!="BARRIER_CLOSED"):
                    raise ValueError("source bar did not justify known closed release")
                holding=active.pop(candidate)
                reserved-=holding["cash"]
                risk_reserved-=holding["risk"]
            else:
                raise ValueError("unknown original journal event category")
            if (e["reserved_capital_after"]!=format(reserved,"f")
                or e["stressed_risk_reserve_after"]!=format(risk_reserved,"f")
                or reserved<0 or reserved>v110.CASH or
                risk_reserved<0 or
                risk_reserved>v110.MAX_AGGREGATE_OPEN_RISK_USDT):
                raise ValueError("original cash/risk balance not conserved")
            if event_ptr:
                hashed.update(b", ")
            hashed.update(json.dumps(e,sort_keys=True,ensure_ascii=False).encode())
            event_ptr+=1
        history_digest=hashed.copy()
        history_digest.update(b"]")
        observed_candidates=sum(
            max(0,bisect_right(times,when)-5)
            for times in by_symbol.values())
        observed_intents=bisect_right(entry_reference_times,when)
        if (observed_candidates>num_candidates
            or observed_intents<len(original_admitted)
            or observed_intents>len(entry_reference_times)):
            raise ValueError("future original candidates used in prior cutoff")
        proof.append({
            "source_cutoff_ms":when,
            "source_closed_minutes_per_symbol":(when-start)//v99.MINUTE,
            "observable_cash_events":event_ptr,
            "original_v107_candidates_seen":observed_candidates,
            "hypothetical_reference_intents_seen":observed_intents,
            "open_reservations_at_cutoff":len(active),
            "replay_events_sha256":history_digest.hexdigest(),
            "prior_decisions_unchanged":True,
            "real_trade_count":0,
        })
    if (event_ptr!=len(events)
        or original_admitted!=cash["original_admission_outcomes"]
        or sorted(active)!=sorted(cash["open_symbol_reservations"])
        or format(reserved,"f")!=cash["reserved_usdt"]
        or format(risk_reserved,"f")!=cash["stressed_gapless_risk_reserve_usdt"]):
        raise ValueError("final original V110 portfolio does not reconcile")
    if (len(proof)!=len(all_times) or
        proof[-1]["observable_cash_events"]!=len(events)):
        raise ValueError("mandatory event checkpoint silently omitted")
    return {
        "schema":SCHEMA,
        "source_status":"CALLER_SUPPLIED_STREAMS_NOT_BYBIT_AUTHENTICATED",
        "source_1m_minutes_per_symbol":(end-start)//v99.MINUTE,
        "all_mandatory_causal_checkpoints":len(all_times),
        "no_checkpoint_omitted":True,
        "all_original_candidate_windows":num_candidates,
        "all_final_hypothetical_reference_proposals":len(entry_reference_times),
        "final_portfolio_event_count":len(events),
        "differential_asof_ledger_checks":proof,
        "final_v111_event_log_digest":sha256(json.dumps(
            events,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
        "source_authenticity_not_proven":True,
        "uses_event_based_proof_not_expensive_full_prefix_recomputation":True,
        "market_prediction_or_profitability_not_established":True,
        "trade_count":0,"entry_signal":False,
        "paper_eligible":False,"live_enabled":False,"net_pnl":None,
    }


def evaluate_future_sealed_archive(folder:Path)->dict:
    """Post-2026-11-30 only. Full audited Bybit-shaped 42-page source.

    Independent V103/V104 archived-source validation is delegated to
    original V111 adapter; V113 then checks the exact original sealed
    source overlay and recomputes all necessary causal pivots. Two
    parsers inspecting one archive are not exchange-source signatures.
    """
    if not isinstance(folder,Path):
        raise ValueError("original physical future archive Path required")
    end=v102.locked_range()[1]
    if int(datetime.now(timezone.utc).timestamp()*1000)<end:
        raise ValueError("FUTURE_WINDOW_NOT_FINISHED_NO_ARCHIVE_READ")
    from research.elliott_v93_recursive_proof import proof_v93 as v93
    v93.immutable_receipt(PARENT_REL,PARENT_SHA,PARENT_COMMIT,v112.SCHEMA)
    parent=v111.evaluate_future_sealed_archive(folder)
    streams={}
    for symbol in v101.PAIRS:
        rows=[]
        for desc in v104.descriptors():
            if desc["symbol"]!=symbol:
                continue
            raw=(folder/(desc["stem"]+".raw.json")).read_bytes()
            side=(folder/(desc["stem"]+".receipt.json")).read_bytes()
            rows.extend(v104.validate_independent_page(desc,raw,side)["candles"])
        bars=[v102.Candle(int(r[0]),*(Decimal(field) for field in r[1:]))
              for r in rows]
        start,last=v108.validate_physical_candles(bars)
        if (start,last)!=v102.locked_range() or len(bars)!=(
            v101.COMPLETE_SOURCE_ROWS_PER_PAIR):
            raise ValueError("physical full future source altered")
        original_closes=[v99.CloseMinute(c.ms,c.close) for c in bars]
        coarse=v99.observe_scale(original_closes,v101.COARSE_SCALE,last)
        fine=v99.observe_scale(original_closes,v101.FINE_SCALE,last)
        streams[symbol]=(coarse,fine,bars)
    plain=v111.portfolio_census_from_source_streams(streams)
    v112.verify_sealed_v111_source_overlay(parent,plain)
    audited=audit_streaming(streams,plain)
    audited["source_status"]="POSTWINDOW_V103_V104_SAME_SEALED_ARCHIVE"
    audited["source_provider_payload_signature_confirmed"]=False
    audited["source_rows_two_symbols"]=40320
    audited["complete_external_source_replay"]=True
    return audited


if __name__=="__main__":
    import argparse
    cli=argparse.ArgumentParser()
    cli.add_argument("--mode",choices=("status","future-offline-audit"),
                     default="status")
    cli.add_argument("--archive",type=Path)
    args=cli.parse_args()
    if args.mode=="status":
        result={"schema":SCHEMA,
                "status":"V113_PROSPECTIVE_RESEARCH_ONLY_ZERO_SOURCE",
                "actual_market_rows_evaluated":0,"orders":0,
                "entry_signal":False,"paper_eligible":False,
                "live_enabled":False}
    else:
        if args.archive is None:
            cli.error("original complete future Bybit archive required")
        result=evaluate_future_sealed_archive(args.archive)
    print(json.dumps(result,sort_keys=True,indent=2))
