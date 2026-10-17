"""V87 research-only Zigzag 5-3-5 / Flat 3-3-5 physical inner degree audit.

The 1m width-1 observer is deliberately narrow; count skeleton != Elliott proof.
No adaptive pivot deletion, retrospective relabeling, signals, Demo or Live.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from research.elliott_v82_causal_degree_observer.observer_v82 import (
    BASE, MINUTE_MS, Minute, Witness, digest, load_attested_symbol, observe,
)
from research.elliott_v86_diagonal_inner_witness.inner_witness_v86 import (
    visible_prefix, strict_1m_pivots,
)

RESEARCH_ONLY=True
ENTRY_SIGNAL=False
PAPER_ELIGIBLE=False
LIVE_ENABLED=False
COMPLETE_RECURSIVE_ELLIOTT=False
FROZEN_V52_CHANGED=False
ROOT=Path(r"E:\NEXUS-QA\elliott-v87-correction-witness-20261016")
V82=Path(r"E:\NEXUS-QA\elliott-v82-causal-degree-observer-20261016")
ZIGZAG_535=(4,2,4)
FLAT_335=(2,2,4)


def _validate_vertex(point: Witness, src: list[Minute], asof: int) -> None:
    if not isinstance(point,Witness) or point.kind not in ("high","low"):
        raise ValueError("typed parent/child source witness required")
    i=point.source_minute_index
    if type(i) is not int or i<0 or i>=len(src) or point.center_ms!=src[i].ms:
        raise ValueError("unbacked source 1m witness center")
    if type(point.confirmed_ms) is not int or not point.center_ms<point.confirmed_ms<=asof:
        raise ValueError("unconfirmed future vertex")
    try:
        p=Decimal(point.price)
    except (InvalidOperation,TypeError,ValueError) as exc:
        raise ValueError("unparseable source-bound pivot price") from exc
    actual=src[i].high if point.kind=="high" else src[i].low
    if not p.is_finite() or p<=0 or p!=actual:
        raise ValueError("incorrect physical OHLC extremum value")


def _leg_info(a: Witness,b: Witness, strict_points: list[dict],
              dual_centers: list[int], asof: int) -> dict:
    if a.center_ms>=b.center_ms or a.kind==b.kind:
        raise ValueError("non-directed or unordered correction leg")
    points=[x for x in strict_points if a.center_ms<x["center_ms"]<b.center_ms]
    unresolved=[x for x in dual_centers if a.center_ms<x<b.center_ms]
    if any(type(x["confirmed_ms"]) is not int or x["confirmed_ms"]>asof
           for x in points):
        raise ValueError("post-decision child pivot injected")
    kinds=[a.kind,*[x["kind"] for x in points],b.kind]
    alternating=all(k!=n for k,n in zip(kinds,kinds[1:]))
    return {
        "left_center_ms":a.center_ms,
        "right_center_ms":b.center_ms,
        "observed_interior_count":len(points),
        "all_interior_pivots":points,
        "ambiguous_dual_center_ms":unresolved,
        "alternating":alternating,
        "right_confirmed_asof_ms":asof,
    }


def assess_correction(vertices: list[Witness], src: list[Minute],
                      asof: int) -> dict:
    """Two competing hypotheses evaluated together. No pattern certificates."""
    if len(vertices)!=4:
        raise ValueError("exactly four causal 15m/3m/3m/15m vertices required")
    visible=visible_prefix(src,asof)
    for p in vertices:
        _validate_vertex(p,visible,asof)
    if any(a.center_ms>=b.center_ms for a,b in zip(vertices,vertices[1:])):
        raise ValueError("correction vertex time not strictly increasing")
    kinds=tuple(v.kind for v in vertices)
    if kinds not in (("high","low","high","low"),("low","high","low","high")):
        return {
            "state":"NOT_THREE_DIRECTED_CORRECTION_LEGS",
            "zigzag_535_skeleton":False,
            "flat_335_skeleton":False,
            "entry_signal":False,
            "paper_eligible":False,
        }
    primitive,rejected=strict_1m_pivots(visible,asof)
    dual=rejected["dual_center_ms"]
    legs=[_leg_info(a,b,primitive,dual,asof)
          for a,b in zip(vertices,vertices[1:])]
    counts=tuple(x["observed_interior_count"] for x in legs)
    has_dual=any(x["ambiguous_dual_center_ms"] for x in legs)
    alternating=all(x["alternating"] for x in legs)
    zigzag=(counts==ZIGZAG_535 and alternating and not has_dual)
    flat=(counts==FLAT_335 and alternating and not has_dual)
    sign=Decimal(-1) if vertices[0].kind=="high" else Decimal(1)
    prices=[Decimal(x.price)*sign for x in vertices]
    # Only describe B's actual A retracement. Do not tune a ratio threshold.
    if prices[1]==prices[0]:
        raise ValueError("correction wave A is zero length")
    retracement=(prices[1]-prices[2])/(prices[1]-prices[0])
    if has_dual:
        state="AMBIGUOUS_UNORDERED_1M_EXTREMA_ABSTAIN"
    elif not alternating:
        state="NONALTERNATING_ALL_INNER_PIVOTS_RETAINED"
    elif zigzag and flat:
        state="AMBIGUOUS_TWO_FAMILIES_ABSTAIN"
    elif zigzag:
        state="ZIGZAG_535_INNER_SKELETON_ONLY"
    elif flat:
        state="FLAT_335_INNER_SKELETON_ONLY"
    else:
        state="NO_COMPLETE_FIXED_DEGREE_CORRECTION_WITNESS"
    return {
        "state":state,
        "asof_ms":asof,
        "outer_vertex_centers_ms":[v.center_ms for v in vertices],
        "outer_vertex_confirmations_ms":[v.confirmed_ms for v in vertices],
        "inner_width_1m":1,
        "inner_counts_ABC":list(counts),
        "observed_inner_pivots_all_legs":legs,
        "ambiguous_dual_extrema_centers_ms":
            [x for leg in legs for x in leg["ambiguous_dual_center_ms"]],
        "outer_B_retracement_of_A":str(retracement),
        "zigzag_535_skeleton":zigzag,
        "flat_335_skeleton":flat,
        "zigzag_subwave_geometry_proven":False,
        "flat_subwave_geometry_proven":False,
        "complete_recursive_elliott":False,
        "entry_signal":False,
        "paper_eligible":False,
        "live_enabled":False,
        "new_pnl":None,
    }


def audited_corrections(symbol: str, receipt: dict) -> dict:
    minutes=load_attested_symbol(symbol,receipt)
    asof=minutes[-1].ms+MINUTE_MS
    replay=observe(minutes,asof)
    oldsummary=json.loads((V82/"V82_RESULT.json").read_text(encoding="utf-8"))
    detailed=(V82/f"V82_{symbol}_CAUSAL_WITNESSES.json").read_bytes()
    if digest(detailed)!=oldsummary["symbols"][symbol]["detailed_witness_file_sha256"]:
        raise ValueError("V82 attested witness receipt changed")
    if replay!=json.loads(detailed)["day2"]:
        raise ValueError("V82 source-bound pivot replay differs")
    parent=[Witness(**p) for p in replay["parent_witnesses"]]
    child=[Witness(**p) for p in replay["child_witnesses"]]
    output=[]
    states=Counter()
    n_skeletons=0
    for a,b,info in zip(parent,parent[1:],replay["leg_assessments"]):
        if not info["hypotheses"]["CORRECTION_THREE_LEG_SKELETON"]:
            continue
        n_skeletons+=1
        cutoff=info["hypothesis_first_seen_ms"]
        middle=[p for p in child if a.center_ms<p.center_ms<b.center_ms
                and p.confirmed_ms<=cutoff]
        if len(middle)!=2 or len(info["all_child_centers_ms"])!=2:
            raise ValueError("source correction witness cardinality changed")
        if ([p.center_ms for p in middle]!=info["all_child_centers_ms"] or
            [p.confirmed_ms for p in middle]!=info["all_child_confirmation_ms"]):
            raise ValueError("posthoc correction children differ from V82")
        if cutoff!=max(a.confirmed_ms,b.confirmed_ms):
            raise ValueError("hypothesis wrong first observable close")
        verdict=assess_correction([a,*middle,b],minutes,cutoff)
        states[verdict["state"]]+=1
        output.append(verdict)
    return {
        "source_minute_bars":len(minutes),
        "original_v82_three_leg_skeletons":n_skeletons,
        "exploratory_assessments":output,
        "reason_counts":dict(states),
        "zigzag_535_complete_patterns":0,
        "flat_335_complete_patterns":0,
        "new_trading_signals":0,
    }


def run_historical_audit() -> dict:
    basebytes=(BASE/"V80_OFFICIAL_BINANCE_SOURCE_QA.json").read_bytes()
    parentbytes=(V82/"V82_RESULT.json").read_bytes()
    receipt=json.loads(basebytes)
    prior=json.loads(parentbytes)
    if (receipt.get("stage")!="V80" or
        prior.get("source_receipt_sha256")!=digest(basebytes)):
        raise ValueError("V80/V82 physical source receipt mismatch")
    result={
        "schema":"nexus.elliott-v87-correction-535-335-physical-skeleton.v1",
        "observed_utc":datetime.now(timezone.utc).isoformat(),
        "v80_source_receipt_sha256":digest(basebytes),
        "v82_pivot_receipt_sha256":digest(parentbytes),
        "strict_1m_inner_width":1,
        "zigzag_fixed_interior_counts":list(ZIGZAG_535),
        "flat_fixed_interior_counts":list(FLAT_335),
        "already_inspected_historical_window":True,
        "prospective_holdout":False,
        "v52_changed":False,
        "research_only":True,
        "paper_eligible":False,
        "live_enabled":False,
        "entry_signal":False,
        "new_pnl":None,
        "symbols":{},
    }
    for symbol in ("BTCUSDT","ETHUSDT"):
        result["symbols"][symbol]=audited_corrections(symbol,receipt)
    ROOT.mkdir(parents=True,exist_ok=True)
    target=ROOT/"V87_CORRECTION_AUDIT.json"
    target.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({
        "schema":result["schema"],
        "hash":digest(target.read_bytes()),
        "results":{k:{"candidate_count":v["original_v82_three_leg_skeletons"],
                      "observations":[{"state":a["state"],
                                       "ABC_counts":a["inner_counts_ABC"],
                                       "dual_count":len(a["ambiguous_dual_extrema_centers_ms"])}
                                      for a in v["exploratory_assessments"]]}
                   for k,v in result["symbols"].items()}
    },indent=2))
    return result


if __name__=="__main__":
    run_historical_audit()
