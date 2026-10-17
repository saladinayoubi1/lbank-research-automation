"""V83 diagnostic: immutable V82 skeletons -> bounded hard motive geometry.

NOT a complete Elliott degree count, market signal, corrected strategy, or P/L.
Retains every child pivot; checks 1m physical bar envelopes and as-of timestamps.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from research.elliott_v82_causal_degree_observer.observer_v82 import (
    BASE, ROOT as V82_ROOT, MINUTE_MS, Minute, Witness,
    digest, load_attested_symbol, observe, validate_minutes,
)

RESEARCH_ONLY = True
ENTRY_SIGNAL = False
PAPER_ELIGIBLE = False
LIVE_ENABLED = False
FROZEN_V52_CHANGED = False
ROOT = Path(r"E:\NEXUS-QA\elliott-v83-impulse-geometry-20261016")


def _known_witness(w: Witness, minutes: list[Minute], asof: int) -> None:
    if not isinstance(w, Witness) or w.kind not in ("high", "low"):
        raise ValueError("invalid witnessed type")
    if type(w.source_minute_index) is not int or type(w.center_ms) is not int:
        raise ValueError("invalid witness location")
    idx = w.source_minute_index
    if idx < 0 or idx >= len(minutes) or minutes[idx].ms != w.center_ms:
        raise ValueError("unbacked physical 1m center")
    if type(w.confirmed_ms) is not int or not w.center_ms < w.confirmed_ms <= asof:
        raise ValueError("witness from future of decision")
    actual = minutes[idx].high if w.kind == "high" else minutes[idx].low
    if Decimal(w.price) != actual:
        raise ValueError("witness source price mismatch")


def check_candidate(
    left: Witness, right: Witness, children: list[Witness],
    minutes: list[Minute], asof: int,
) -> dict:
    """Fail-closed geometry of a five-leg skeleton; not a valid full Elliott motive."""
    if type(asof) is not int or asof % MINUTE_MS:
        raise ValueError("decision must be a completed one-minute instant")
    if not isinstance(minutes, list) or not minutes or type(minutes[0]) is not Minute:
        raise ValueError("complete typed 1m source required")
    if type(minutes[0].ms) is not int:
        raise ValueError("typed source opening timestamp required")
    count, remainder = divmod(asof - minutes[0].ms, MINUTE_MS)
    if remainder or count < 1 or len(minutes) < count:
        raise ValueError("unavailable closed 1m source through as-of")
    # Never inspect a future tail, including an invalid or unfinished bar.
    visible_minutes = minutes[:count]
    validate_minutes(visible_minutes)
    if len(children) != 4:
        return {"state": "NOT_FIVE_LEG_SKELETON", "motive_geometry_pass": False}
    vertices=[left,*children,right]
    if any(x.center_ms >= y.center_ms for x,y in zip(vertices,vertices[1:])):
        raise ValueError("source centers not increasing")
    for v in vertices:
        _known_witness(v,visible_minutes,asof)
    expected=("low","high","low","high","low","high") if left.kind=="low" else (
        "high","low","high","low","high","low")
    if tuple(v.kind for v in vertices) != expected:
        return {"state":"NONALTERNATING_OR_WRONG_DIRECTION",
                "motive_geometry_pass":False}
    direction=1 if left.kind=="low" else -1
    points=[direction*Decimal(v.price) for v in vertices]
    # Independent hard geometries for NON-DIAGONAL, NON-TRUNCATED impulse only.
    rule_failures=[]
    if not points[2]>points[0]:
        rule_failures.append("WAVE2_BREACHES_ORIGIN")
    if not points[3]>points[1]:
        rule_failures.append("WAVE3_NOT_BEYOND_WAVE1")
    if not points[4]>points[1]:
        rule_failures.append("WAVE4_OVERLAPS_WAVE1_NONDIAGONAL")
    if not points[5]>points[3]:
        rule_failures.append("WAVE5_TRUNCATED_OR_NOT_EXTREME")
    lengths=(points[1]-points[0], points[3]-points[2], points[5]-points[4])
    if any(n<=0 for n in lengths):
        rule_failures.append("NONPOSITIVE_MOTIVE_SUBLEG")
    elif lengths[1] < min(lengths[0],lengths[2]):
        rule_failures.append("WAVE3_IS_SHORTEST")

    # Each source minute can be fully known only after it has closed. Check
    # extrema envelopes, never pretend intraminute HIGH/LOW order was observed.
    physical_failures=[]
    for i,(a,b) in enumerate(zip(vertices,vertices[1:])):
        segment=visible_minutes[a.source_minute_index:b.source_minute_index+1]
        if not segment:
            raise ValueError("missing source path")
        up=(i%2==0) if direction==1 else (i%2==1)
        if up:
            if max(m.high for m in segment) > Decimal(b.price):
                physical_failures.append(f"LEG{i+1}_INTERVENING_HIGH_EXCEEDS_ENDPOINT")
            if min(m.low for m in segment) < Decimal(a.price):
                physical_failures.append(f"LEG{i+1}_LOW_BREACHES_START")
        else:
            if min(m.low for m in segment) < Decimal(b.price):
                physical_failures.append(f"LEG{i+1}_INTERVENING_LOW_BELOW_ENDPOINT")
            if max(m.high for m in segment) > Decimal(a.price):
                physical_failures.append(f"LEG{i+1}_HIGH_BREACHES_START")

    valid=not rule_failures and not physical_failures
    return {
        "state": ("MOTIVE_HARD_GEOMETRY_ONLY_SUBWAVES_UNPROVEN" if valid
                  else "REJECT_HARD_MOTIVE_GEOMETRY"),
        "motive_geometry_pass":valid,
        "orientation":("bullish" if direction==1 else "bearish"),
        "rule_failures":rule_failures,
        "physical_failures":physical_failures,
        "vertex_center_ms":[v.center_ms for v in vertices],
        "vertex_confirmed_ms":[v.confirmed_ms for v in vertices],
        "price_vertices":[v.price for v in vertices],
        "first_observable_ms":asof,
        "complete_recursive_elliott":False,
        "entry_signal":False,
        "paper_eligible":False,
        "live_enabled":False,
        "pnl":None,
    }


def audit_symbol(symbol: str, raw_receipt: dict) -> dict:
    minutes=load_attested_symbol(symbol,raw_receipt)
    decision_ms=minutes[-1].ms+MINUTE_MS
    observed=observe(minutes,decision_ms)
    expected_path=V82_ROOT / f"V82_{symbol}_CAUSAL_WITNESSES.json"
    prior_bytes=expected_path.read_bytes()
    prior=json.loads(prior_bytes)
    summary=json.loads((V82_ROOT/"V82_RESULT.json").read_text(encoding="utf-8"))
    if digest(prior_bytes)!=summary["symbols"][symbol]["detailed_witness_file_sha256"]:
        raise ValueError("historical source observer trace was modified")
    if prior["day2"]!=observed:
        raise ValueError("V82 source witness replay has changed")
    parents=[Witness(**x) for x in observed["parent_witnesses"]]
    children=[Witness(**x) for x in observed["child_witnesses"]]
    legs=observed["leg_assessments"]
    if len(legs)!=len(parents)-1:
        raise ValueError("parent leg count mismatch")
    outcomes=[]
    reasons=Counter()
    for l,r,record in zip(parents,parents[1:],legs):
        if (record["parent_left_center_ms"]!=l.center_ms or
            record["parent_right_center_ms"]!=r.center_ms):
            raise ValueError("leg source mismatch")
        if record["hypotheses"]["MOTIVE_FIVE_LEG_SKELETON"]:
            visible=[w for w in children if l.center_ms < w.center_ms < r.center_ms
                     and w.confirmed_ms<=record["hypothesis_first_seen_ms"]]
            inspected=check_candidate(l,r,visible,minutes,
                                      record["hypothesis_first_seen_ms"])
            outcomes.append(inspected)
            reasons[inspected["state"]]+=1
            for why in inspected["rule_failures"]+inspected["physical_failures"]:
                reasons[why]+=1
        elif record["hypotheses"]["CORRECTION_THREE_LEG_SKELETON"]:
            # Zigzag=5-3-5, Flat=3-3-5, Triangle=3-3-3-3-3
            # Do NOT pretend three simple vertices certify their substructures.
            outcomes.append({
                "state":"CORRECTION_SKELETON_UNCLASSIFIED_NO_INNER_WITNESS",
                "parent_left_center_ms":l.center_ms,
                "parent_right_center_ms":r.center_ms,
                "first_observable_ms":record["hypothesis_first_seen_ms"],
                "zigzag_proven":False, "flat_proven":False,
                "triangle_proven":False, "entry_signal":False,
                "paper_eligible":False, "pnl":None,
            })
            reasons["CORRECTION_SKELETON_UNCLASSIFIED_NO_INNER_WITNESS"]+=1
        else:
            reasons["UNRESOLVED_PARENT_INTERVAL"]+=1
    return {
        "source_1m_bars":len(minutes),
        "parent_intervals":len(legs),
        "motive_skeleton_candidates":sum(x["hypotheses"]["MOTIVE_FIVE_LEG_SKELETON"] for x in legs),
        "correction_skeleton_candidates":sum(x["hypotheses"]["CORRECTION_THREE_LEG_SKELETON"] for x in legs),
        "results":outcomes,
        "rejection_and_abstention_reasons":dict(reasons),
        "full_recursive_elliott_proven":0,
        "signals":0,
        "verified_profit_usdt":None,
    }


def main():
    receipt_bytes=(BASE/"V80_OFFICIAL_BINANCE_SOURCE_QA.json").read_bytes()
    source=json.loads(receipt_bytes)
    v82_summary=(V82_ROOT/"V82_RESULT.json").read_bytes()
    if digest(receipt_bytes)!=json.loads(v82_summary)["source_receipt_sha256"]:
        raise ValueError("V80/V82 archive receipt mismatch")
    result={
        "stage":"V83","schema":"nexus.elliott-v83-historical-motive-hard-geometry.v1",
        "utc_recorded":datetime.now(timezone.utc).isoformat(),
        "v80_receipt_sha256":digest(receipt_bytes),
        "v82_receipt_sha256":digest(v82_summary),
        "historical_exploratory":True, "future_holdout":False,
        "v52_unchanged":True, "research_only":True,
        "entry_signal":False,"paper_eligible":False,"live_enabled":False,
        "new_pnl":None, "symbols":{},
    }
    for pair in ("BTCUSDT","ETHUSDT"):
        result["symbols"][pair]=audit_symbol(pair,source)
    ROOT.mkdir(parents=True,exist_ok=True)
    p=ROOT/"V83_RESULT.json"
    p.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({
        "stage":"V83","source_sha256":digest(p.read_bytes()),
        "symbols":{k:{"candidates":v["motive_skeleton_candidates"],
                      "corrections":v["correction_skeleton_candidates"],
                      "outcomes":v["rejection_and_abstention_reasons"]}
                   for k,v in result["symbols"].items()},
        "result_path":str(p)
    },indent=2))


if __name__=="__main__":
    main()
