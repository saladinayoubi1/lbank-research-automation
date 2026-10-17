"""V114 deterministic large SYNTHETIC V110/V113 event-stream stress.

Measures wall-time and tracemalloc peak for:
  fixture construction -> V110 original cash replay -> independent V114
  all-event invariant and cryptographic-prefix scan.
This isolates journal/checkpoint overhead. It DOES NOT exercise 9,000
real source-derived V99/V107 pivots or prove the entire V113 pipeline
can complete a 9,000-candidate market workload.
No HTTP, exchange credentials, orders, or return measurements.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal, ROUND_DOWN
from hashlib import sha256
from pathlib import Path
import json
import platform
import sys
import time
import tracemalloc

from research.elliott_v110_portfolio_capacity import capacity_v110 as v110
from research.elliott_v113_incremental_audit import incremental_v113 as v113

SCHEMA="nexus.elliott-v114-500usdt-synthetic-large-event-journal-stress.v1"
PARENT_COMMIT="8eeaa49a4827491d8020182919f47a7b1dc501bd"
PARENT_REL="docs/evidence/elliott-v113-streaming-audit-20261017/V113_FROZEN_INCREMENTAL_PROOF.json"
PARENT_SHA="254319942369dfb314df07c488d84724de5a5b7c095fb737c6210f821a06a6d7"
BASE=1792368000000
MIN=60000
BLOCK=30
SIZES=(600,4200,9000)
RESEARCH_ONLY=True
LIVE_ENABLED=False
PAPER_ELIGIBLE=False
ENTRY_SIGNAL=False
ORDER_ADAPTER=None
V52_UNCHANGED=True


def locked_rules()->dict:
    return {
        "schema":SCHEMA,"status":"PREDECLARED_SYNTHETIC_ONLY_NO_REAL_MARKET_EVALUATION",
        "v113_predecessor_commit":PARENT_COMMIT,
        "v113_predecessor_sha256":PARENT_SHA,
        "fixed_original_reference_balance_usdt":str(v110.CASH),
        "symbols":["BTCUSDT","ETHUSDT"],
        "price_reference_asof_closed_only":True,
        "scenario":"TWO_RESERVATIONS_PER_30_MINUTES_OTHERS_CAPACITY_DENIED",
        "all_synthetic_intents_ledgered_without_cherry_picking":True,
        "admissions_at_indices_0_and_1_each_30_min_block":True,
        "two_explicit_known_resolutions_at_each_next_30_min_boundary":True,
        "resolutions_released_before_same_minute_new_intent":True,
        "scenario_original_intents":list(SIZES),
        "all_checkpoint_prefix_hashes_computed_not_sampled":True,
        "naive_prefix_full_json_sha_crosscheck":"FIRST_MIDDLE_LAST_AND_64_SMALL_PREFIXES",
        "each_event_cash_and_stressed_risk_recomputed_independently":True,
        "negative_tamper_controls":"TIME_ORDER_CASH_RISK_CANDIDATE_CLOSE_REASON_DUPLICATION",
        "profile_measures":"PERF_COUNTER_AND_TRACEMALLOC_PEAK",
        "no_fixed_walltime_performance_guarantee":True,
        "benchmark_is_journal_only_not_full_v99_v107_source_scaling":True,
        "no_bybit_market_ohlc_read":True,
        "actual_market_data_evaluated":0,
        "verified_elliott_waves":0,
        "actual_pnl":None,"orders":0,
        "paper_eligible":False,"entry_signal":False,"live_enabled":False,
        "v52_unchanged":True,
    }


def freeze(path:Path)->dict:
    if not isinstance(path,Path):
        raise ValueError("explicit frozen protocol Path required")
    from research.elliott_v93_recursive_proof import proof_v93 as v93
    prev=v93.immutable_receipt(PARENT_REL,PARENT_SHA,PARENT_COMMIT,v113.SCHEMA)
    if (prev["orders"]!=0 or
        prev["none_sampled_or_silently_dropped"] is not True or
        prev["streaming_proof_not_equivalent_to_expensive_full_prefix_recomputation"] is not True):
        raise ValueError("prior V113 research provenance or no-sampling altered")
    raw=(json.dumps(locked_rules(),indent=2,sort_keys=True)+"\n").encode()
    if path.exists():
        if path.read_bytes()!=raw:
            raise ValueError("V114 LOCKED SCIENTIFIC RULES ALTERED")
    else:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(raw)
    return {"schema":SCHEMA,"sha256":sha256(raw).hexdigest(),
            "real_market_rows":0,"actual_orders":0}


def fixed_fixture(n:int)->tuple[list[v110.Intent],list[v110.Resolution],int]:
    if type(n) is not int or n<=0 or n%BLOCK:
        raise ValueError("stress workload requires positive complete 30-event blocks")
    intents=[]
    resolutions=[]
    for i in range(n):
        when=BASE+i*MIN
        sym="BTCUSDT" if i%2==0 else "ETHUSDT"
        intents.append(v110.Intent(
            f"fixed-{i:07d}",sym,"BUY_SPOT",when,when,
            Decimal("100"),Decimal("99")))
        if i%BLOCK in (0,1):
            # No retrospective profit or favorable forced exit: these are
            # explicitly invented closed-source scenario events.
            closure=BASE+(i//BLOCK+1)*BLOCK*MIN
            resolutions.append(v110.Resolution(
                f"fixed-{i:07d}",closure,closure,"BARRIER_CLOSED"))
    return intents,resolutions,BASE+n*MIN


def _strmoney(x:Decimal)->str:
    return format(x,"f")


def _independent_allocation(intent:v110.Intent,reserved:Decimal,
                            risk:Decimal,active:dict)->tuple[str,Decimal,Decimal]:
    """Recompute the deterministic choice without reading V110 output rows."""
    unit=(intent.hypothetical_entry_close-intent.confirmed_wave0_stop)/(
        intent.hypothetical_entry_close)+Decimal("2")*v110.COST_RATE
    why=None
    if unit<=Decimal("2")*v110.COST_RATE:
        why="INVALID_OR_NONPOSITIVE_WAVE0_RISK"
    elif len(active)>=v110.MAX_ACTIVE:
        why="MAX_CONCURRENT_RESEARCH_RESERVATIONS"
    elif any(p["symbol"]==intent.symbol for p in active.values()):
        why="SAME_SYMBOL_RESERVATION_ALREADY_ACTIVE"
    elif reserved>=v110.CASH or risk>=v110.MAX_AGGREGATE_OPEN_RISK_USDT:
        why="INSUFFICIENT_SHARED_CASH_OR_RISK_BUDGET"
    if why is not None:
        return why,Decimal(0),Decimal(0)
    notional=min(
        v110.MAX_POSITION_USDT,
        v110.CASH-reserved,
        (v110.CASH-reserved)/(Decimal(1)+v110.COST_RATE),
        v110.MAX_RISK_PER_RESERVATION_USDT/unit,
        (v110.MAX_AGGREGATE_OPEN_RISK_USDT-risk)/unit,
    ).quantize(v110.CAPITAL_PRECISION,rounding=ROUND_DOWN)
    if notional<=0:
        return "INSUFFICIENT_SHARED_CASH_OR_RISK_BUDGET",Decimal(0),Decimal(0)
    return "",notional,notional*unit


def verify_all_events(
    intents:list[v110.Intent],
    resolutions:list[v110.Resolution],
    asof:int,
    claimed:dict,
)->dict:
    """One-to-one independently recomputed source fixtures and journal rows.

    No large naive quadratic per-prefix JSON operation. SHA256 state
    copies at ALL mandatory event checkpoints (including equal-time
    ordered releases/admissions); exact canonical JSON is also checked
    by explicit naive rehash of initial/mid/final checkpoints.
    """
    if (type(claimed) is not dict or
        claimed.get("schema")!=v110.SCHEMA or
        type(intents) is not list or type(resolutions) is not list or
        type(asof) is not int):
        raise ValueError("original typed full source and cash ledger required")
    events=claimed.get("append_only_causal_event_ledger")
    if type(events) is not list or len(events)!=len(intents)+len(resolutions):
        raise ValueError("CANDIDATE_DENOMINATOR_OR_EVENT_COUNT_CHANGED")
    if (claimed.get("original_intents_count")!=len(intents) or
        claimed.get("known_resolutions_count")!=len(resolutions) or
        claimed.get("trade_count")!=0 or
        claimed.get("live_enabled") is not False or
        claimed.get("actual_net_pnl") is not None):
        raise ValueError("ORIGINAL_SOURCE_RESEARCH_ONLY_STATUS_CHANGED")
    agenda=[]
    ids={}
    by_close={}
    for i in intents:
        v110._valid_intent(i)
        if i.candidate_id in ids or i.decision_asof_ms>asof:
            raise ValueError("DUPLICATE_OR_UNSEEN_FUTURE_INTENT")
        ids[i.candidate_id]=i
        agenda.append((i.decision_asof_ms,1,i.symbol,i.candidate_id,"intent",i))
    for r in resolutions:
        v110._valid_resolution(r)
        if (r.candidate_id not in ids or r.candidate_id in by_close or
            r.known_at_ms>asof or
            r.observed_closed_ms<ids[r.candidate_id].decision_asof_ms):
            raise ValueError("DUPLICATE_OR_UNKNOWN_OR_FUTURE_RELEASE")
        by_close[r.candidate_id]=r
        agenda.append((r.known_at_ms,0,"",r.candidate_id,"release",r))
    agenda.sort(key=lambda x:x[:4])
    active={}
    historical_states={}
    reserved=Decimal(0)
    risk_reserved=Decimal(0)
    sequence=sha256()
    sequence.update(b"[")
    chain=sha256()
    first=None
    last=None
    reasons=Counter()
    naive_positions={0,len(events)//2,len(events)-1}
    naive_positions.update(range(min(64,len(events))))
    for index,(agenda_item,row) in enumerate(zip(agenda,events)):
        when,_,symbol,ident,kind,item=agenda_item
        if type(row) is not dict or row.get("known_at_ms")!=when or row.get(
            "candidate_id")!=ident:
            raise ValueError("SOURCE_TIME_OR_CANDIDATE_ORDER_CHANGED")
        if kind=="intent":
            if ident in historical_states:
                raise ValueError("REPEATED_ORIGINAL_ADMISSION")
            why,notional,risk=_independent_allocation(
                item,reserved,risk_reserved,active)
            if why:
                historical_states[ident]="DENIED_"+why
                reasons["denied_"+why]+=1
                expected={
                    "known_at_ms":when,"event":"DENIED_CAPACITY_OR_SOURCE",
                    "candidate_id":ident,"symbol":item.symbol,"reason":why,
                    "reserved_capital_after":_strmoney(reserved),
                    "stressed_risk_reserve_after":_strmoney(risk_reserved),
                }
            else:
                capital=notional*(Decimal(1)+v110.COST_RATE)
                if (notional<=0 or capital+reserved>v110.CASH
                    or risk+risk_reserved>v110.MAX_AGGREGATE_OPEN_RISK_USDT
                    or risk>v110.MAX_RISK_PER_RESERVATION_USDT
                    or len(active)>=v110.MAX_ACTIVE
                    or any(x["symbol"]==item.symbol for x in active.values())):
                    raise ValueError("RISK_OR_SHARED_CASH_OVERALLOCATED")
                active[ident]={"symbol":item.symbol,"cash":capital,"risk":risk}
                historical_states[ident]="HYPOTHETICAL_RESERVED"
                reserved+=capital
                risk_reserved+=risk
                reasons["hypothetical_reserved"]+=1
                expected={
                    "known_at_ms":when,
                    "event":"SYNTHETIC_CAPACITY_RESERVED_NOT_ORDER",
                    "candidate_id":ident,"symbol":item.symbol,
                    "hypothetical_notional_usdt":_strmoney(notional),
                    "hypothetical_buy_cash_plus_entry_stress_usdt":_strmoney(capital),
                    "assumed_gapless_stressed_loss_reserve_usdt":_strmoney(risk),
                    "reserved_capital_after":_strmoney(reserved),
                    "stressed_risk_reserve_after":_strmoney(risk_reserved),
                }
        else:
            if ident not in active:
                raise ValueError("DENIED_OR_UNKNOWN_CANDIDATE_WAS_RELEASED")
            held=active.pop(ident)
            reserved-=held["cash"]
            risk_reserved-=held["risk"]
            reasons["explicit_synthetic_closures"]+=1
            expected={
                "known_at_ms":when,"event":"RELEASE_KNOWN",
                "candidate_id":ident,"observed_closed_ms":item.observed_closed_ms,
                "reason":item.reason,
                "reserved_capital_after":_strmoney(reserved),
                "stressed_risk_reserve_after":_strmoney(risk_reserved),
                "not_realized_pnl":True,
            }
        if row!=expected:
            raise ValueError("CASH_OR_RISK_OR_EVENT_ROW_TAMPERED")
        if reserved<0 or risk_reserved<0 or reserved>v110.CASH or risk_reserved>(
            v110.MAX_AGGREGATE_OPEN_RISK_USDT):
            raise ValueError("NEGATIVE_CASH_OR_EXCESSIVE_RISK")
        if index:
            sequence.update(b", ")
        sequence.update(json.dumps(row,sort_keys=True,ensure_ascii=False).encode())
        checkpoint=sequence.copy()
        checkpoint.update(b"]")
        digest=checkpoint.digest()
        chain.update(digest)
        if first is None:
            first=digest.hex()
        last=digest.hex()
        if index in naive_positions:
            naive=sha256(json.dumps(
                events[:index+1],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            if naive!=digest.hex():
                raise ValueError("STREAMING_PREFIX_SHA256_MISMATCH")
    if (historical_states!=claimed.get("original_admission_outcomes") or
        sorted(active)!=sorted(claimed.get("open_symbol_reservations",{})) or
        reserved!=Decimal(claimed["reserved_usdt"]) or
        risk_reserved!=Decimal(claimed["stressed_gapless_risk_reserve_usdt"])
        or v110.CASH-reserved!=Decimal(claimed["unreserved_cash_usdt"]) or
        reasons["hypothetical_reserved"]!=claimed["admitted_hypothetical_intents"] or
        len(intents)-reasons["hypothetical_reserved"]!=claimed[
            "denied_hypothetical_intents"]):
        raise ValueError("FINAL_CAPACITY_DENOMINATOR_OR_BALANCE_TAMPERED")
    return {
        "schema":"nexus.elliott-v114-all-event-prefix-adversarial-proof.v1",
        "all_source_intents":len(intents),
        "all_explicit_synthetic_resolutions":len(resolutions),
        "all_event_checkpoints_checked":len(events),
        "all_event_prefix_sha256_created":len(events),
        "naive_crosscheck_prefixes":len(naive_positions),
        "checkpoint_prefix_sha256_first":first,
        "checkpoint_prefix_sha256_last":last,
        "all_prefix_digest_chain_sha256":chain.hexdigest(),
        "full_cash_event_log_sha256":sha256(json.dumps(
            events,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
        "record_counts":dict(sorted(reasons.items())),
        "current_hypothetical_reserved_cash":_strmoney(reserved),
        "current_hypothetical_gapless_risk":_strmoney(risk_reserved),
        "no_event_dropped_or_optimized_after_market_result":True,
        "not_full_market_prefix_replay":True,
        "true_market_data_candles":0,"actual_orders":0,
        "net_pnl":None,
    }


def profile_one(n:int)->dict:
    """Wall-time and tracemalloc during EXACT original offline synthetic run.

    No wall-time assertions: machine load/thermal throttling/AV may differ.
    One run per size; this measures V110 replay + V114 independent
    checkpoint proof, not V113 full-source source-driven candidate generation.
    """
    tracemalloc.start()
    try:
        t0=time.perf_counter_ns()
        intents,resolutions,asof=fixed_fixture(n)
        t1=time.perf_counter_ns()
        original=v110.replay(intents,resolutions,asof)
        t2=time.perf_counter_ns()
        proof=verify_all_events(intents,resolutions,asof,original)
        t3=time.perf_counter_ns()
        current,peak=tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    should_admit=(n//BLOCK)*2
    if (proof["all_event_checkpoints_checked"]!=n+should_admit or
        original["original_intents_count"]!=n or
        original["admitted_hypothetical_intents"]!=should_admit or
        original["denied_hypothetical_intents"]!=n-should_admit or
        original["known_resolutions_count"]!=should_admit or
        Decimal(original["reserved_usdt"])!=0 or
        proof["record_counts"]["explicit_synthetic_closures"]!=should_admit):
        raise ValueError("SYNTHETIC_BLOCK_EXPECTATION_OR_CAPACITY_MISMATCH")
    return {
        "synthetic_original_intents":n,
        "synthetic_known_closed_source_events":should_admit,
        "verified_mandatory_cash_journal_checkpoints":n+should_admit,
        "exceeds_previous_v112_4096_limit":(n+should_admit)>4096,
        "accepted_original_hypothetical_reservations":should_admit,
        "denied_original_hypothetical_reservations":n-should_admit,
        "all_prefix_hashes_checked":proof["all_event_prefix_sha256_created"],
        "all_prefix_sha256_digest_chain":proof["all_prefix_digest_chain_sha256"],
        "full_event_sha256":proof["full_cash_event_log_sha256"],
        "fixture_build_ms":round((t1-t0)/1_000_000,3),
        "v110_original_replay_ms":round((t2-t1)/1_000_000,3),
        "v114_full_independent_all_event_check_ms":round((t3-t2)/1_000_000,3),
        "total_walltime_ms":round((t3-t0)/1_000_000,3),
        "python_tracemalloc_peak_mib":round(peak/(1024*1024),3),
        "tracemalloc_current_mib":round(current/(1024*1024),3),
        "not_system_rss_or_full_application_peak":True,
        "no_source_market_rows":True,
        "orders":0,"net_pnl":None,
    }


def benchmark_snapshot()->dict:
    runs=[profile_one(n) for n in SIZES]
    if any(r["verified_mandatory_cash_journal_checkpoints"]!=
           r["all_prefix_hashes_checked"] for r in runs):
        raise ValueError("NO_SAMPLING_JOURNAL_CHECKPOINT_PROOF_FAILED")
    return {
        "schema":"nexus.elliott-v114-measured-synthetic-event-only-benchmark.v1",
        "parent_rulebook_sha256":sha256((
            json.dumps(locked_rules(),indent=2,sort_keys=True)+"\n").encode()).hexdigest(),
        "benchmark_runtime_platform":platform.platform(),
        "benchmark_runtime_python":sys.version.split()[0],
        "benchmark_single_run_per_size":True,
        "benchmark_not_repeated_statistical_sample":True,
        "benchmark_measures_V110_V114_journal_not_entire_V113_source_pipeline":True,
        "tracemalloc_only_python_traced_allocations":True,
        "results":runs,
        "bybit_data_fetched":0,
        "actually_opened_positions":0,
        "elliott_profitability_proven":False,
        "paper_eligible":False,"live_enabled":False,
    }


def write_benchmark_once(path:Path)->dict:
    if not isinstance(path,Path):
        raise ValueError("explicit immutable V114 performance evidence path required")
    result=benchmark_snapshot()
    raw=(json.dumps(result,sort_keys=True,indent=2)+"\n").encode()
    if path.exists():
        if path.read_bytes()!=raw:
            raise ValueError("V114_MEASURED_PERFORMANCE_EVIDENCE_MUST_NOT_BE_REWRITTEN")
    else:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(raw)
    return {
        "status":"V114_SYNTHETIC_EVENT_JOURNAL_CHECKED_NO_ACTUAL_MARKET",
        "evidence_sha256":sha256(raw).hexdigest(),
        "runs":len(result["results"]),
        "largest_verified_cash_checkpoints":result["results"][-1][
            "verified_mandatory_cash_journal_checkpoints"],
        "orders":0,
    }


if __name__=="__main__":
    import argparse
    cli=argparse.ArgumentParser()
    cli.add_argument("--mode",choices=("status","benchmark"),
                     default="status")
    cli.add_argument("--out",type=Path)
    arguments=cli.parse_args()
    if arguments.mode=="status":
        payload={"schema":SCHEMA,"market_rows":0,
                 "stressed_sizes":list(SIZES),"orders":0,
                 "paper_eligible":False,"live_enabled":False}
    else:
        if arguments.out is None:
            cli.error("--out file required for immutable benchmark evidence")
        payload=write_benchmark_once(arguments.out)
    print(json.dumps(payload,indent=2,sort_keys=True))
