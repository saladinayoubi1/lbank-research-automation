"""V95 independent physical 1m terminal witness re-attestation.

Only source data already frozen in V88 / officially verified in V89 and
candidate centers from V90 are used. Never infer intraminute high/low order.
Never certify a recursive Elliott pattern or create a trade.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from research.elliott_v82_causal_degree_observer.observer_v82 import MINUTE_MS, Minute
from research.elliott_v90_frozen_replication import replicate_v90 as v90
from research.elliott_v91_impulse_nested_gate import nested_gate_v91 as v91
from research.elliott_v93_recursive_proof import proof_v93 as v93

ROOT = Path(r"E:\NEXUS-QA\elliott-v95-physical-witness-20261017")
V93_SHA = "fa55b3dd524fba9de7546fba8ea110db30a1e7b9bb8507ff7c79325ad8a35f58"
V93_COMMIT = "dc08af84620bae51c5c7e1bf8946c9b21bc0d529"
V93_REL = "docs/evidence/elliott-v93-recursive-proof-20261017/V93_PROOF_OBLIGATIONS.json"
RESEARCH_ONLY = True
ENTRY_SIGNAL = False
PAPER_ELIGIBLE = False
LIVE_ENABLED = False
V52_UNCHANGED = True
PHYSICAL_TERMINAL_IS_NOT_FULL_RECURSION = True


def canonical(obj: object) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False)+"\n").encode("utf-8")


def independent_1m_extrema(minutes: list[Minute], asof: int) -> tuple[list[dict],list[int]]:
    """All strict width=1 high/low from the *closed* prefix, no pruning.

    Deliberately does not use V86 strict_1m_pivots or its hidden state.
    A candle marking both local high and low is undecidable from OHLC.
    """
    if type(asof) is not int or asof % MINUTE_MS:
        raise ValueError("aligned decision time required")
    if type(minutes) is not list or not minutes or type(minutes[0]) is not Minute:
        raise ValueError("complete typed minute series required")
    first = minutes[0].ms
    if type(first) is not int:
        raise ValueError("typed first source timestamp required")
    count, remainder = divmod(asof-first,MINUTE_MS)
    if remainder or not 3<=count<=len(minutes):
        raise ValueError("as-of not within complete closed source")
    found=[]
    unordered=[]
    for i in range(count):
        m=minutes[i]
        if (type(m) is not Minute or type(m.ms) is not int or
            m.ms!=first+i*MINUTE_MS or
            type(m.high) is not Decimal or type(m.low) is not Decimal or
            not m.high.is_finite() or not m.low.is_finite() or
            m.low<=0 or m.high<m.low):
            raise ValueError("invalid source minute or temporal gap")
        if not 0<i<count-1:
            continue
        a=minutes[i-1]
        c=minutes[i+1]
        top=m.high>a.high and m.high>c.high
        bottom=m.low<a.low and m.low<c.low
        if top and bottom:
            unordered.append(m.ms)
        elif top or bottom:
            found.append({
                "kind":"high" if top else "low",
                "center_ms":m.ms,
                "confirmed_ms":c.ms+MINUTE_MS,
                "price":str(m.high if top else m.low),
                "source_minute_index":i,
            })
    return found,unordered


def attest_candidate(motive:dict,source:list[Minute]) -> dict:
    """Replay original V86 observations independently from V89 raw OHLC."""
    hard=motive["v83"]
    inner=motive["v86"]
    asof=motive["first_observable_ms"]
    if (type(asof) is not int or hard["first_observable_ms"]!=asof
        or inner["asof_ms"]!=asof
        or hard["entry_signal"] is not False
        or inner["entry_signal"] is not False):
        raise ValueError("noncausal decision or forged entry flag")
    points,unordered=independent_1m_extrema(source,asof)
    if (inner["observed_full_prefix_1m_strict_points"]!=len(points)
        or inner["global_dual_extremum_abstentions"]["dual_center_ms"]!=unordered):
        raise ValueError("global physical strict pivot observations changed")
    centers=hard["vertex_center_ms"]
    confs=hard["vertex_confirmed_ms"]
    prices=hard["price_vertices"]
    if not len(centers)==len(confs)==len(prices)==6 or len(inner["legs"])!=5:
        raise ValueError("six source vertices and five full nested legs required")
    if any(type(c) is not int or c%MINUTE_MS for c in centers):
        raise ValueError("invalid source center timestamp")
    if any(left>=right for left,right in zip(centers,centers[1:])):
        raise ValueError("retroactively reordered source endpoints")
    if hard["orientation"] not in ("bullish","bearish"):
        raise ValueError("invalid original impulse direction")
    first=source[0].ms
    for i,(center,confirmed,price) in enumerate(zip(centers,confs,prices)):
        ix,rem=divmod(center-first,MINUTE_MS)
        if rem or ix<0 or ix>=len(source) or (
            type(confirmed) is not int or not center<confirmed<=asof):
            raise ValueError("future or absent source endpoint")
        expected=(source[ix].low if
                  (hard["orientation"]=="bullish")== (i%2==0)
                  else source[ix].high)
        if Decimal(str(price))!=expected:
            raise ValueError("original endpoint price not in official minute")
    legs=[]
    for i,(left,right) in enumerate(zip(centers,centers[1:])):
        original=inner["legs"][i]
        subset=[p for p in points if left<p["center_ms"]<right]
        duals=[x for x in unordered if left<x<right]
        if (original["left_center_ms"]!=left or
            original["right_center_ms"]!=right or
            original["asof_ms"]!=asof or
            original["all_interior_strict_pivots"]!=subset or
            original["ambiguous_unordered_1m_center_ms"]!=duals or
            original["interior_count"]!=len(subset) or
            inner["per_leg_inner_counts"][i]!=len(subset)):
            raise ValueError("1m terminal witness differs from attested source")
        legs.append({
            "leg":i+1,
            "source_1m_terminal_pivot_count":len(subset),
            "all_primitive_pivot_sha256":hashlib.sha256(canonical(subset)).hexdigest(),
            "ambiguous_unordered_ohlc_centers_ms":duals,
            "source_terminal_verified":True,
            "higher_degree_wave_proven":False,
        })
    return {
        "first_observable_ms":asof,
        "week":motive["week"],
        "full_source_prefix_1m_bars":(asof-first)//MINUTE_MS,
        "all_visible_strict_1m_pivots":len(points),
        "all_visible_dual_extremum_bars":len(unordered),
        "original_nested_counts":inner["per_leg_inner_counts"],
        "leg_observations":legs,
        "physical_1m_primitives_verified":True,
        "independent_recursive_wave_certificate":False,
        "verified_pattern_position":False,
        "new_entry_signal":False,
        "paper_eligible":False,
        "live_enabled":False,
        "pnl":None,
    }


def historical_replay() -> dict:
    """Source 28 files + 8 historical witnesses rechecked; zero new classifications."""
    frozen,receipt=v90.verify_locked_receipts()
    original=v91.sealed_v90()
    missing=v93.immutable_receipt(
        V93_REL,V93_SHA,V93_COMMIT,"nexus.elliott-v93-source-proof-obligations.v1")
    if (original["v89_source_receipt_sha256"]!=v90.SOURCE_RECEIPT_SHA
        or missing["v91_receipt_sha256"]!=v93.V91_SHA):
        raise ValueError("original source/model lineage changed")
    report={
        "schema":"nexus.elliott-v95-physical-source-terminal-replay.v1",
        "observed_utc":datetime.now(timezone.utc).isoformat(),
        "v88_preregistration_sha256":v90.v89.PREREG_HASH,
        "v89_official_source_receipt_sha256":v90.SOURCE_RECEIPT_SHA,
        "v90_motive_receipt_sha256":v91.PRIOR_SHA,
        "v93_proof_debt_receipt_sha256":V93_SHA,
        "source_provider":"28 official SHA-verified Binance Spot 1m daily archives July 2024",
        "research_only":True,"historical_not_prospective":True,
        "thresholds_modified":False,"all_primitives_retained":True,
        "new_recursive_pattern_certificates":0,"new_entry_signals":0,
        "orders":0,"pnl":None,"v52_unchanged":True,
        "paper_eligible":False,"live_enabled":False,
        "symbols":{},
    }
    for symbol in ("BTCUSDT","ETHUSDT"):
        mins=v90._parse_verified_source(symbol,frozen,receipt)
        cases=original["symbols"][symbol]["five_leg_candidate_details"]
        expected=6 if symbol=="BTCUSDT" else 2
        if len(cases)!=expected:
            raise ValueError("original V90 motive population changed")
        attested=[]
        week=Counter()
        for candidate in cases:
            result=attest_candidate(candidate,mins)
            week[result["week"]]+=1
            attested.append(result)
        if (len(attested)!=expected or
            any(x["new_entry_signal"] or x["independent_recursive_wave_certificate"]
                for x in attested)):
            raise ValueError("unexpected pattern promotion or incomplete population")
        report["symbols"][symbol]={
            "source_1m_minutes":len(mins),
            "source_start_ms":mins[0].ms,
            "source_exclusive_end_ms":mins[-1].ms+MINUTE_MS,
            "original_five_leg_candidates":len(cases),
            "physically_replayed_candidates":len(attested),
            "cases_by_week":dict(week),
            "all_source_terminal_matches":True,
            "full_recursive_elliott_certificates":0,
            "trade_ready_cases":0,
            "cases":attested,
        }
    ROOT.mkdir(parents=True,exist_ok=True)
    outfile=ROOT/"V95_PHYSICAL_SOURCE_WITNESS_AUDIT.json"
    encoded=(json.dumps(report,sort_keys=True,indent=2)+"\n").encode()
    if outfile.exists():
        previous=json.loads(outfile.read_bytes())
        proposed=json.loads(encoded)
        previous.pop("observed_utc",None)
        proposed.pop("observed_utc",None)
        if previous!=proposed:
            raise ValueError("existing historical V95 evidence differs; no overwrite")
        encoded=outfile.read_bytes()
    else:
        outfile.write_bytes(encoded)
    print(json.dumps({
        "status":"V95_INDEPENDENT_SOURCE_PIVOTS_REPLAYED_NOT_RECURSIVE_ELLIOTT_PROOF",
        "evidence_sha256":hashlib.sha256(encoded).hexdigest(),
        "cases_by_symbol":{s:{
            "replayed":x["physically_replayed_candidates"],
            "week_A":x["cases_by_week"].get("A",0),
            "week_B":x["cases_by_week"].get("B",0),
            "recursive_certificates":0,
        } for s,x in report["symbols"].items()},
        "source_1m_bars":sum(v["source_1m_minutes"] for v in report["symbols"].values()),
        "new_trades":0,
    },indent=2))
    return report


if __name__=="__main__":
    historical_replay()
