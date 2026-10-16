"""V86 isolated 1m inner-pivot census for V85 diagonal hypotheses.

Strict width=1 primitive degree is an EXPLORATORY observer, not wave grammar:
exactly two inner extrema is necessary for this narrow 3-leg skeleton only,
not a universally necessary rule for all real Elliott corrections.
Never prune same-kind pivots, pick favorable subsequences or trade.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from research.elliott_v82_causal_degree_observer.observer_v82 import (
    BASE, MINUTE_MS, Minute, digest, load_attested_symbol, validate_minutes,
)
from research.elliott_v83_impulse_geometry.geometry_v83 import audit_symbol
from research.elliott_v85_diagonal_scope.diagonal_scope_v85 import (
    evaluate_diagonal_preconditions,
)

RESEARCH_ONLY=True
ENTRY_SIGNAL=False
PAPER_ELIGIBLE=False
LIVE_ENABLED=False
FROZEN_V52_CHANGED=False
MINUTE_INNER_WIDTH=1
ROOT=Path(r"E:\NEXUS-QA\elliott-v86-diagonal-inner-witness-20261016")
V83=Path(r"E:\NEXUS-QA\elliott-v83-impulse-geometry-20261016")
V85=Path(r"E:\NEXUS-QA\elliott-v85-diagonal-scope-20261016")


def visible_prefix(minutes: list[Minute], asof: int) -> list[Minute]:
    if type(asof) is not int or asof % MINUTE_MS:
        raise ValueError("as-of must be an aligned closed minute")
    if type(minutes) is not list or not minutes or type(minutes[0]) is not Minute:
        raise ValueError("typed complete source required")
    if type(minutes[0].ms) is not int:
        raise ValueError("typed source time required")
    count,mod=divmod(asof-minutes[0].ms,MINUTE_MS)
    if mod or count<=0 or count>len(minutes):
        raise ValueError("incomplete source through decision")
    prefix=minutes[:count]
    validate_minutes(prefix)
    return prefix


def strict_1m_pivots(minutes: list[Minute], asof: int) -> tuple[list[dict],dict]:
    """Every one-minute width-1 STRICT extrema in a closed, gapless prefix.

    Dual extrema on the same candle are ambiguous as OHLC has no
    intrabar event order, and are recorded rather than silently discarded.
    """
    src=visible_prefix(minutes,asof)
    points=[]
    rejected=Counter()
    dual_centers=[]
    for i in range(MINUTE_INNER_WIDTH,len(src)-MINUTE_INNER_WIDTH):
        before,at,after=src[i-1],src[i],src[i+1]
        hi=at.high>before.high and at.high>after.high
        lo=at.low<before.low and at.low<after.low
        if hi and lo:
            rejected["DUAL_EXTREMUM_UNORDERED_OHLC"]+=1
            dual_centers.append(at.ms)
            continue
        if hi or lo:
            points.append({
                "kind":"high" if hi else "low",
                "center_ms":at.ms,
                "confirmed_ms":after.ms+MINUTE_MS,
                "price":str(at.high if hi else at.low),
                "source_minute_index":i,
            })
    return points,{**dict(rejected),"dual_center_ms":dual_centers}


def grade_one_leg(left: dict,right: dict,points: list[dict],asof: int,
                  dual_centers: list[int] | None=None) -> dict:
    """All observed pivots retained; no arbitrary subwave selection."""
    if left["center_ms"]>=right["center_ms"]:
        raise ValueError("left/right centers must increase")
    if left["kind"]==right["kind"] or left["kind"] not in ("high","low"):
        raise ValueError("parent leg must have alternating endpoints")
    if type(asof) is not int or any(type(p["center_ms"]) is not int or
                                   type(p["confirmed_ms"]) is not int
                                   for p in [left,right,*points]):
        raise ValueError("typed timing required")
    if max(left["confirmed_ms"],right["confirmed_ms"])>asof:
        raise ValueError("future parent vertex")
    if any(p["center_ms"]<right["center_ms"] and
           p["confirmed_ms"]>asof for p in points):
        raise ValueError("future center incorrectly supplied")
    middle=[p for p in points
            if left["center_ms"]<p["center_ms"]<right["center_ms"]]
    if any(p["confirmed_ms"]>asof for p in middle):
        raise ValueError("future child pivot")
    ambiguities=[t for t in (dual_centers or [])
                 if left["center_ms"]<t<right["center_ms"]]
    needed=[right["kind"],left["kind"]]
    kinds=[p["kind"] for p in middle]
    qualifies=len(middle)==2 and kinds==needed and not ambiguities
    if ambiguities:
        reason="DUAL_EXTREMUM_UNORDERED_OHLC_INSIDE_LEG"
    elif len(middle)!=2:
        reason="NOT_EXACTLY_TWO_STRICT_1M_INTERIOR_EXTREMA"
    elif kinds!=needed:
        reason="INNER_POLARITY_NOT_ALTERNATING"
    else:
        reason="THREE_LEG_SKELETON_ONLY_NO_RECURSIVE_ABC_PROOF"
    return {
        "left_center_ms":left["center_ms"],
        "right_center_ms":right["center_ms"],
        "asof_ms":asof,
        "all_interior_strict_pivots":middle,
        "interior_count":len(middle),
        "ambiguous_unordered_1m_center_ms":ambiguities,
        "reason":reason,
        "exact_two_alternating":qualifies,
        "abc_geometry_proven":False,
        "diagonal_proven":False,
        "entry_signal":False,
    }


def inspect_candidate(candidate: dict,minute_source: list[Minute]) -> dict:
    """Re-authenticate vertices directly to frozen 1m source at the decision."""
    asof=candidate["first_observable_ms"]
    src=visible_prefix(minute_source,asof)
    vertices=[]
    for i,(center,confirmation,price) in enumerate(zip(
        candidate["vertex_center_ms"],candidate["vertex_confirmed_ms"],
        candidate["price_vertices"])):
        index,mod=divmod(center-src[0].ms,MINUTE_MS)
        if mod or index<0 or index>=len(src):
            raise ValueError("V83 price center not in as-of source prefix")
        kind=("low" if i%2==0 else "high") if candidate["orientation"]=="bullish" else (
            "high" if i%2==0 else "low")
        exact=src[index].low if kind=="low" else src[index].high
        if str(exact)!=str(__import__("decimal").Decimal(price)):
            raise ValueError("V83 vertex price differs from physical 1m archive")
        if confirmation<=center or confirmation>asof:
            raise ValueError("future or noncausal V83 confirmation")
        vertices.append({
            "kind":kind, "center_ms":center,"confirmed_ms":confirmation,
            "price":price,"source_minute_index":index,
        })
    all_primitives,primitive_rejections=strict_1m_pivots(src,asof)
    parts=[grade_one_leg(a,b,all_primitives,asof,
                         primitive_rejections["dual_center_ms"])
           for a,b in zip(vertices,vertices[1:])]
    counts=[x["interior_count"] for x in parts]
    counts_summary=dict(Counter(x["reason"] for x in parts))
    enough=all(x["exact_two_alternating"] for x in parts)
    eligible=(candidate["diagonal_precondition_state"]==
              "PRELIMINARY_GEOMETRY_ONLY_DIAGONAL_NOT_PROVEN")
    return {
        "state":("HARD_VETO_PERSISTS" if not eligible else
                 "FIVE_LEG_INNER_DEGREE_SKELETON_ONLY_NOT_PATTERN"
                 if enough else "INNER_DEGREE_WITNESS_NOT_ESTABLISHED"),
        "orientation":candidate["orientation"],
        "asof_ms":asof,
        "observed_full_prefix_1m_strict_points":len(all_primitives),
        "global_dual_extremum_abstentions":primitive_rejections,
        "per_leg_inner_counts":counts,
        "per_leg_reasons":counts_summary,
        "five_legs_exact_two_alternating":enough,
        "legs":parts,
        "ending_diagonal_proven":False,
        "leading_diagonal_proven":False,
        "flat_or_zigzag_proven":False,
        "paper_eligible":False,
        "live_enabled":False,
        "entry_signal":False,
        "pnl":None,
    }


def run_historical_audit() -> dict:
    b80=(BASE/"V80_OFFICIAL_BINANCE_SOURCE_QA.json").read_bytes()
    b83=(V83/"V83_RESULT.json").read_bytes()
    b85=(V85/"V85_DIAGONAL_SOURCE_AUDIT.json").read_bytes()
    src=json.loads(b80)
    prev83=json.loads(b83)
    prev85=json.loads(b85)
    if (prev85["v80_source_receipt_sha256"]!=digest(b80) or
        prev85["v83_immutable_receipt_sha256"]!=digest(b83) or
        prev83["v80_receipt_sha256"]!=digest(b80)):
        raise ValueError("V80/V83/V85 independent source lineage mismatch")
    report={
        "schema":"nexus.elliott-v86-historical-strict-1m-inner-census.v1",
        "created_utc":datetime.now(timezone.utc).isoformat(),
        "v80_receipt_sha256":digest(b80),
        "v83_receipt_sha256":digest(b83),
        "v85_receipt_sha256":digest(b85),
        "one_minute_inner_width":MINUTE_INNER_WIDTH,
        "historically_inspected":True,
        "prospective_holdout":False,
        "frozen_v52_changed":False,
        "research_only":True,
        "paper_eligible":False,
        "live_enabled":False,
        "signals":0,
        "pnl":None,
        "symbols":{},
    }
    for symbol in ("BTCUSDT","ETHUSDT"):
        minutes=load_attested_symbol(symbol,src)
        fresh=audit_symbol(symbol,src)
        if fresh!=prev83["symbols"][symbol]:
            raise ValueError("prior verified V83 report changed for "+symbol)
        before=[x for x in fresh["results"] if "price_vertices" in x]
        old85=prev85["symbols"][symbol]["candidates"]
        if len(before)!=len(old85):
            raise ValueError("V83/V85 different candidate populations")
        cases=[]
        for rec,candidate85 in zip(before,old85):
            fresh85=evaluate_diagonal_preconditions(rec)
            if fresh85!=candidate85:
                raise ValueError("prior V85 diagnostic not reproduced")
            wrapped=dict(rec)
            wrapped["diagonal_precondition_state"]=fresh85["state"]
            cases.append(inspect_candidate(wrapped,minutes))
        report["symbols"][symbol]={
            "source_minute_bars":len(minutes),
            "candidates":cases,
            "diagonal_patterns_proven":0,
            "reason_counts":dict(Counter(x["state"] for x in cases)),
            "paper_signal_count":0,
        }
    ROOT.mkdir(parents=True,exist_ok=True)
    target=ROOT/"V86_INNER_CENSUS.json"
    target.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({
        "schema":report["schema"],
        "result_sha256":digest(target.read_bytes()),
        "results":{k:[{"state":c["state"],
                        "counts":c["per_leg_inner_counts"],
                        "reasons":c["per_leg_reasons"]}
                       for c in v["candidates"]]
                   for k,v in report["symbols"].items()}
    },indent=2))
    return report


if __name__=="__main__":
    run_historical_audit()
