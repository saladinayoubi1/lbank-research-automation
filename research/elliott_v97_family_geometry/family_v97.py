"""V97 restrictive source-bound geometric diagnostics, never Elliott certification.

Fixed non-diagonal non-truncated Impulse, deep B retracement Zigzag
(no B beyond A origin), regular/expanded subset Flat (B >= 90% of A).
No Elliott degree promotion, chart optimization, signals, or orders.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from research.elliott_v82_causal_degree_observer.observer_v82 import Minute, Witness, observe, validate_minutes
from research.elliott_v90_frozen_replication import replicate_v90 as v90
from research.elliott_v91_impulse_nested_gate import nested_gate_v91 as v91
from research.elliott_v93_recursive_proof import proof_v93 as v93
from research.elliott_v96_degree_bridge import bridge_v96 as v96

ROOT=Path(tempfile.gettempdir())/"nexus-elliott-v97-research"
RESEARCH_ONLY=True
ENTRY_SIGNAL=False
PAPER_ELIGIBLE=False
LIVE_ENABLED=False
ORDER_CONNECTOR=None
V52_UNCHANGED=True
SOURCE_MINUTE_MS=60000
FLAT_B_MIN_RETRACE=Decimal("0.90")
FAMILIES=("IMPULSE","ZIGZAG","FLAT")
V96_REL="docs/evidence/elliott-v96-degree-bridge-20261017/V96_DEGREE_BRIDGE_AUDIT.json"
V96_SHA="cfc29e8ed2cac611ffb09d0bf9847894dc4e935daacc2d6ae4c379c8dda78a01"
V96_COMMIT="c633fffd6daccfa6b56e5227bfbc16198a30b3f1"


@dataclass(frozen=True)
class PhysicalVertex:
    kind: str
    center_ms: int
    confirmed_ms: int
    price: Decimal


def witness_vertex(w:Witness) -> PhysicalVertex:
    if not isinstance(w,Witness):
        raise ValueError("typed source Witness required")
    return PhysicalVertex(w.kind,w.center_ms,w.confirmed_ms,Decimal(w.price))


def evaluate(family:str,vertices:tuple[PhysicalVertex,...],
             minutes:list[Minute],asof:int) -> dict:
    """Necessary geometry for explicitly restricted family, all OHLC still observed.

    Physical verification is independent of V83/V87 labels. No claim that
    source-bound vertices are valid higher-degree Elliott pivots.
    """
    if family not in FAMILIES:
        raise ValueError("unknown exact frozen candidate family")
    count=6 if family=="IMPULSE" else 4
    if (type(vertices) is not tuple or len(vertices)!=count or
        any(type(x) is not PhysicalVertex for x in vertices)):
        raise ValueError("typed exact vertex count required")
    if type(asof) is not int or asof%SOURCE_MINUTE_MS:
        raise ValueError("closed aligned as-of required")
    if type(minutes) is not list or not minutes or type(minutes[0]) is not Minute:
        raise ValueError("typed complete 1m source required")
    first=minutes[0].ms
    length,mod=divmod(asof-first,SOURCE_MINUTE_MS)
    if mod or not 3<=length<=len(minutes):
        raise ValueError("no physically closed as-of prefix")
    src=minutes[:length]
    validate_minutes(src)
    for i,v in enumerate(vertices):
        if (type(v.center_ms) is not int or type(v.confirmed_ms) is not int or
            v.center_ms%SOURCE_MINUTE_MS or
            type(v.price) is not Decimal or not v.price.is_finite() or
            v.price<=0 or v.kind not in ("high","low") or
            not v.center_ms<v.confirmed_ms<=asof):
            raise ValueError("unconfirmed or invalid physical vertex")
        idx,rem=divmod(v.center_ms-first,SOURCE_MINUTE_MS)
        if rem or idx<0 or idx>=length:
            raise ValueError("vertex absent from closed source")
        observed=src[idx].high if v.kind=="high" else src[idx].low
        if v.price!=observed:
            raise ValueError("vertex price not backed by physical 1m wick")
        if i and (vertices[i-1].center_ms>=v.center_ms or
                  vertices[i-1].kind==v.kind):
            raise ValueError("vertices out of order or nonalternating")
    up=vertices[0].kind=="low"
    direction=Decimal(1) if up else Decimal(-1)
    prices=[v.price*direction for v in vertices]
    blockers=[]
    if prices[1]<=prices[0]:
        blockers.append("NONPOSITIVE_INITIAL_DIRECTED_WAVE")
    if family=="IMPULSE":
        if prices[2]<=prices[0]:
            blockers.append("WAVE2_INVALID_ORIGIN_BREACH")
        if prices[3]<=prices[1]:
            blockers.append("WAVE3_NOT_BEYOND_WAVE1")
        if prices[4]<=prices[1]:
            blockers.append("WAVE4_OVERLAP_NONDIAGONAL")
        if prices[5]<=prices[3]:
            blockers.append("WAVE5_NOT_NEW_EXTREME_RESTRICTED_SUBSET")
        lengths=[prices[1]-prices[0],prices[3]-prices[2],prices[5]-prices[4]]
        if any(x<=0 for x in lengths):
            blockers.append("NONPOSITIVE_MOTIVE_SUBWAVE")
        elif lengths[1]<min(lengths[0],lengths[2]):
            blockers.append("WAVE3_IS_SHORTEST")
    elif family=="ZIGZAG":
        # Restrictive non-running A-B-C subset; not a universal rule for all
        # alternative Elliott corrective configurations.
        if prices[2]>=prices[1]:
            blockers.append("CORRECTIVE_B_WRONG_DIRECTION")
        if prices[2]<=prices[0]:
            blockers.append("ZIGZAG_B_AT_OR_PAST_A_ORIGIN")
        if prices[3]<=prices[1]:
            blockers.append("ZIGZAG_C_NOT_BEYOND_A_END_RESTRICTED_SUBSET")
    else:
        if prices[2]>=prices[1]:
            blockers.append("CORRECTIVE_B_WRONG_DIRECTION")
        if prices[1]>prices[0]:
            ratio=(prices[1]-prices[2])/(prices[1]-prices[0])
            if ratio<FLAT_B_MIN_RETRACE:
                blockers.append("FLAT_B_RETRACE_LESS_THAN_90_PERCENT")
        if prices[3]<=prices[1]:
            blockers.append("FLAT_C_NOT_BEYOND_A_END_RESTRICTED_SUBSET")
    # Strong path-envelope checks for this *restricted* endpoint-observed
    # family. Does not infer order of high and low within any candle.
    for i,(left,right) in enumerate(zip(vertices,vertices[1:])):
        a=(left.center_ms-first)//SOURCE_MINUTE_MS
        b=(right.center_ms-first)//SOURCE_MINUTE_MS
        candles=src[a:b+1]
        rising=(up if i%2==0 else not up)
        if rising:
            if max(x.high for x in candles)>right.price:
                blockers.append(f"LEG{i+1}_WICK_HIGH_BEYOND_END")
            if min(x.low for x in candles)<left.price:
                blockers.append(f"LEG{i+1}_WICK_LOW_BEFORE_START")
        else:
            if min(x.low for x in candles)<right.price:
                blockers.append(f"LEG{i+1}_WICK_LOW_BEYOND_END")
            if max(x.high for x in candles)>left.price:
                blockers.append(f"LEG{i+1}_WICK_HIGH_BEFORE_START")
    return {
        "family":family,"family_scope":"RESTRICTED_NECESSARY_GEOMETRY_ONLY",
        "asof_ms":asof,"vertex_centers_ms":[v.center_ms for v in vertices],
        "rejections":list(dict.fromkeys(blockers)),
        "restricted_geometry_pass":not blockers,
        "source_1m_wicks_verified":True,
        "wave_degree_or_recursive_elliott_proven":False,
        "pattern_position_proven":False,
        "entry_signal":False,"paper_eligible":False,"live_enabled":False,
        "net_pnl":None,
    }


def audit_preinspected_july() -> dict:
    """Post-hoc diagnostics on FROZEN OLD universe; NEVER selection/validation.

    Verify V96 immutable release and original V89 archive CHECKSUM provenance.
    Enumerate every V90 candidate in its original parent interval ordering.
    """
    pinned=v93.immutable_receipt(
        V96_REL,V96_SHA,V96_COMMIT,
        "nexus.elliott-v96-physically-anchored-degree-bridge.v1")
    lock,receipt=v90.verify_locked_receipts()
    original=v91.sealed_v90()
    if (pinned["v95_source_witness_sha256"]!=v96.V95_SHA
        or pinned["v90_original_candidates_sha256"]!=v91.PRIOR_SHA
        or original["v89_source_receipt_sha256"]!=v90.SOURCE_RECEIPT_SHA):
        raise ValueError("committed preregistration/market lineage changed")
    output={
        "schema":"nexus.elliott-v97-restricted-family-geometry-posthoc-diagnostics.v1",
        "recorded_utc":datetime.now(timezone.utc).isoformat(),
        "source_v96_commit":V96_COMMIT,"source_v96_sha256":V96_SHA,
        "source_v90_sha256":v91.PRIOR_SHA,
        "official_v89_sha256":v90.SOURCE_RECEIPT_SHA,
        "scope":"OLD_JULY_2024_POSTHOC_DIAGNOSTIC_ONLY_NOT_A_BACKTEST",
        "thresholds_optimized_or_prior_outcomes_tuned":False,
        "no_uninspected_market_data_seen":True,
        "research_only":True,"paper_eligible":False,"live_enabled":False,
        "entry_signals":0,"orders":0,"real_pnl":None,
        "frozen_v52_untouched":True,
        "symbols":{},
    }
    for symbol,motive_count,correction_count in (("BTCUSDT",6,9),("ETHUSDT",2,14)):
        minutes=v90._parse_verified_source(symbol,lock,receipt)
        observed=observe(minutes,v90.END_MS)
        parents=[Witness(**x) for x in observed["parent_witnesses"]]
        children=[Witness(**x) for x in observed["child_witnesses"]]
        old_intervals=original["symbols"][symbol]["all_intervals"]
        if len(old_intervals)!=len(parents)-1:
            raise ValueError("old July population size changed")
        candidates=[]
        counts=Counter()
        for left,right,case in zip(parents,parents[1:],old_intervals):
            asof=case["first_observable_ms"]
            if (case["parent_left_center_ms"]!=left.center_ms or
                case["parent_right_center_ms"]!=right.center_ms or
                asof!=max(left.confirmed_ms,right.confirmed_ms)):
                raise ValueError("prior physical parent interval/source time changed")
            middle=v90.matching_children(left,right,children,asof)
            if ([w.center_ms for w in middle]!=case["child_centers_ms"]
                or [w.confirmed_ms for w in middle]!=case["child_confirmed_ms"]):
                raise ValueError("prior nested witness order changed")
            if not case["motive_five_leg_skeleton"] and not case["correction_three_leg_skeleton"]:
                continue
            expected=4 if case["motive_five_leg_skeleton"] else 2
            if len(middle)!=expected:
                raise ValueError("historical candidate count changed")
            vertices=tuple(witness_vertex(x) for x in (left,*middle,right))
            families=("IMPULSE",) if expected==4 else ("ZIGZAG","FLAT")
            inspected={x:evaluate(x,vertices,minutes,asof) for x in families}
            if "IMPULSE" in inspected and (
                inspected["IMPULSE"]["restricted_geometry_pass"]!=(
                    case["v83_motive_state"]=="MOTIVE_HARD_GEOMETRY_ONLY_SUBWAVES_UNPROVEN")):
                raise ValueError("V83 outer hard geometry changed unexpectedly")
            passed=[x for x,v in inspected.items() if v["restricted_geometry_pass"]]
            resolution=("AMBIGUOUS_FAMILIES_NO_SELECTION" if len(passed)>1
                        else "RESTRICTED_GEOMETRY_ONLY_NO_RECURSION" if len(passed)==1
                        else "GEOMETRY_REJECTED")
            counts["candidate_intervals"]+=1
            counts["impulse_candidates" if expected==4 else "correction_candidates"]+=1
            counts[resolution]+=1
            for family,result in inspected.items():
                if result["restricted_geometry_pass"]:
                    counts[family+"_RESTRICTED_GEOMETRY_PASS"]+=1
                for failure in result["rejections"]:
                    counts[family+"_"+failure]+=1
            candidates.append({
                "first_observable_ms":asof,
                "week":case["week"],
                "original_V82_candidate_type":"IMPULSE" if expected==4 else "CORRECTION",
                "families_diagnosed":inspected,
                "narrow_family_diagnostic_resolution":resolution,
                "independent_recursive_market_wave_proven":False,
                "entry_signal":False,"paper_eligible":False,"pnl":None,
            })
        if (counts["impulse_candidates"]!=motive_count or
            counts["correction_candidates"]!=correction_count):
            raise ValueError("full original historical candidate census changed")
        output["symbols"][symbol]={
            "source_1m_candles":len(minutes),
            "original_impulse_candidates":motive_count,
            "original_correction_candidates":correction_count,
            "all_original_hypotheses_preserved":True,
            "necessary_geometry_only":True,
            "diagnostic_counts":dict(counts),
            "cases":candidates,
            "complete_elliott_patterns":0,
            "new_positions":0,
        }
    ROOT.mkdir(parents=True,exist_ok=True)
    dest=ROOT/"V97_FAMILY_GEOMETRY_DIAGNOSTIC.json"
    data=(json.dumps(output,indent=2,sort_keys=True,ensure_ascii=False)+"\n").encode()
    if dest.exists():
        prev=json.loads(dest.read_bytes())
        new=json.loads(data)
        prev.pop("recorded_utc",None)
        new.pop("recorded_utc",None)
        if prev!=new:
            raise ValueError("V97 prior historical observation differs: no overwrite")
        data=dest.read_bytes()
    else:
        dest.write_bytes(data)
    print(json.dumps({
        "status":"RESTRICTED_FAMILY_GEOMETRY_JULY_POSTHOC_ONLY",
        "sha256":hashlib.sha256(data).hexdigest(),
        "by_symbol":{k:v["diagnostic_counts"] for k,v in output["symbols"].items()},
        "new_signals":0,"orders":0,
    },indent=2))
    return output


if __name__=="__main__":
    audit_preinspected_july()
