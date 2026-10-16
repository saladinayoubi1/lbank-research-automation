"""V85 conservative DIAGONAL possibility veto; never label a complete Elliott count.

Exploratory historical Bybit-independent Binance source; original V52 unchanged.
This is a read-only post-hoc diagnostic, never an entry, fill or position.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from research.elliott_v82_causal_degree_observer.observer_v82 import (
    BASE, digest,
)
from research.elliott_v83_impulse_geometry.geometry_v83 import audit_symbol

RESEARCH_ONLY = True
ENTRY_SIGNAL = False
PAPER_ELIGIBLE = False
LIVE_ENABLED = False
COMPLETE_RECURSIVE_ELLIOTT = False
ROOT = Path(r"E:\NEXUS-QA\elliott-v85-diagonal-scope-20261016")
V83_ROOT = Path(r"E:\NEXUS-QA\elliott-v83-impulse-geometry-20261016")


def _price(x: object) -> Decimal:
    if isinstance(x, (bool, float)):
        raise ValueError("lossy source price")
    try:
        v = Decimal(str(x))
    except (TypeError, InvalidOperation, ValueError) as exc:
        raise ValueError("malformed source price") from exc
    if not v.is_finite() or v <= 0:
        raise ValueError("non-positive / nonfinite price")
    return v


def evaluate_diagonal_preconditions(motive: dict) -> dict:
    """Necessary motive-veto checks; never prove diagonal subdivided 3-3-3-3-3.

    An ending diagonal's location, trendline context and constituent three-wave
    subdivisions are NOT supplied by this six-point input. Leading diagonals
    also require separate family-specific, independently authenticated evidence.
    """
    if type(motive) is not dict or motive.get("state") not in (
        "REJECT_HARD_MOTIVE_GEOMETRY",
        "MOTIVE_HARD_GEOMETRY_ONLY_SUBWAVES_UNPROVEN",
    ):
        raise ValueError("must provide verified V83 motive-candidate record")
    raw=motive.get("price_vertices")
    times=motive.get("vertex_center_ms")
    confirmed=motive.get("vertex_confirmed_ms")
    asof=motive.get("first_observable_ms")
    orientation=motive.get("orientation")
    if not isinstance(raw,list) or len(raw)!=6 or any(type(x) is not str for x in raw):
        raise ValueError("exactly six source-bound price vertices required")
    if not isinstance(times,list) or len(times)!=6 or any(type(x) is not int for x in times):
        raise ValueError("six typed minute-center timestamps required")
    if not isinstance(confirmed,list) or len(confirmed)!=6 or any(type(x) is not int for x in confirmed):
        raise ValueError("six typed right-confirmation timestamps required")
    if type(asof) is not int or orientation not in ("bullish","bearish"):
        raise ValueError("invalid as-of instant or orientation")
    if any(b<=a for a,b in zip(times,times[1:])):
        raise ValueError("pivot centers are not in source-time order")
    if any(c<=t or c>asof for t,c in zip(times,confirmed)):
        raise ValueError("noncausal pivot-right-confirmation")
    if any(t%60000 or c%60000 for t,c in zip(times,confirmed)) or asof%60000:
        raise ValueError("UTC 1m alignment required")
    if motive.get("entry_signal") is not False or motive.get("paper_eligible") is not False:
        raise ValueError("untrusted executable motive candidate")
    direction=Decimal(1) if orientation=="bullish" else Decimal(-1)
    values=[direction*_price(p) for p in raw]
    w1,w3,w5=(values[1]-values[0],
               values[3]-values[2],
               values[5]-values[4])
    veto=[]
    if values[2]<=values[0]:
        veto.append("WAVE2_FULL_RETRACE_W1")
    if values[4]<=values[2]:
        veto.append("WAVE4_FULL_RETRACE_W3")
    if values[3]<=values[1]:
        veto.append("WAVE3_NOT_BEYOND_W1")
    if min(w1,w3,w5)<=0:
        veto.append("NONPOSITIVE_ACTIONARY_LEG")
    elif w3<min(w1,w5):
        veto.append("WAVE3_SHORTEST_FORBIDDEN_IN_DIAGONAL")
    if motive.get("physical_failures"):
        veto.append("PHYSICAL_SOURCE_PATH_INVALIDATED")
    overlap=values[4]<=values[1]
    # Overlap is common in diagonals but is NOT itself a proof or obligatory
    # universal hard rule. A wave-5 truncation remains only a caveated possibility.
    possible=not veto
    return {
        "state":("PRELIMINARY_GEOMETRY_ONLY_DIAGONAL_NOT_PROVEN"
                 if possible else "DIAGONAL_HARD_VETO"),
        "hard_veto_reasons":veto,
        "wave4_overlaps_wave1":overlap,
        "wave5_extends_wave3":values[5]>values[3],
        "three_subwaves_per_leg_verified":False,
        "correct_structural_position_verified":False,
        "contracting_or_expanding_wedge_verified":False,
        "ending_diagonal_proven":False,
        "leading_diagonal_proven":False,
        "complete_recursive_elliott":False,
        "entry_signal":False,
        "paper_eligible":False,
        "live_enabled":False,
        "pnl":None,
        "first_observable_ms":asof,
        "orientation":orientation,
        "source_price_vertices":raw,
    }


def run_audit() -> dict:
    srcbytes=(BASE/"V80_OFFICIAL_BINANCE_SOURCE_QA.json").read_bytes()
    src=json.loads(srcbytes)
    prevbytes=(V83_ROOT/"V83_RESULT.json").read_bytes()
    old=json.loads(prevbytes)
    if src.get("stage")!="V80" or old.get("stage")!="V83":
        raise ValueError("unverified data lineage stage")
    if old.get("v80_receipt_sha256")!=digest(srcbytes):
        raise ValueError("historical archive changed")
    report={
        "schema":"nexus.elliott-v85-diagonal-veto.v1",
        "created_utc":datetime.now(timezone.utc).isoformat(),
        "v80_source_receipt_sha256":digest(srcbytes),
        "v83_immutable_receipt_sha256":digest(prevbytes),
        "historical_exploratory":True,
        "prospective_holdout":False,
        "no_v52_change":True,
        "research_only":True,
        "paper_eligible":False,
        "live_enabled":False,
        "signals":0,
        "pnl":None,
        "symbols":{},
    }
    for symbol in ("BTCUSDT","ETHUSDT"):
        fresh=audit_symbol(symbol,src)
        if fresh!=old["symbols"][symbol]:
            raise ValueError("V83 source-bound replay mismatch for "+symbol)
        cases=[]
        for result in fresh["results"]:
            if "price_vertices" in result:
                cases.append(evaluate_diagonal_preconditions(result))
        reasons=Counter()
        for case in cases:
            reasons[case["state"]]+=1
            for why in case["hard_veto_reasons"]:
                reasons[why]+=1
        report["symbols"][symbol]={
            "evaluated_source_bound_five_leg_skeletons":len(cases),
            "reason_counts":dict(reasons),
            "candidates":cases,
            "proven_diagonals":0,
            "new_elliott_signals":0,
        }
    ROOT.mkdir(parents=True,exist_ok=True)
    path=ROOT/"V85_DIAGONAL_SOURCE_AUDIT.json"
    path.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({
        "schema":report["schema"],
        "results":{symbol:entry["reason_counts"]
                   for symbol,entry in report["symbols"].items()},
        "receipt_sha256":digest(path.read_bytes()),
        "receipt_path":str(path),
    },indent=2))
    return report


if __name__ == "__main__":
    run_audit()
