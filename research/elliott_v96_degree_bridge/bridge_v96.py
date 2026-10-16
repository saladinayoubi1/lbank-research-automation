"""V96 physically anchored *necessary* degree bridge, no trading.

Reopens the V89 official July sources and compares V95 locked terminal
witnesses. Only a complete unpruned 5-3-5-3-5 *syntactic* candidate
can cross the structural gate; a pass never certifies Elliott grammar,
source-defined pattern location, profitability or an order.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from research.elliott_v90_frozen_replication import replicate_v90 as v90
from research.elliott_v91_impulse_nested_gate import nested_gate_v91 as v91
from research.elliott_v93_recursive_proof import proof_v93 as v93
from research.elliott_v95_physical_witness import witness_v95 as v95

ROOT=Path(r"E:\NEXUS-QA\elliott-v96-degree-bridge-20261017")
V95_REL="docs/evidence/elliott-v95-physical-witness-20261017/V95_PHYSICAL_SOURCE_WITNESS_AUDIT.json"
V95_SHA="3935d6d79f9f50ca873ff1a60afca6467b02d80650b4bfce92f78053be755d4e"
V95_COMMIT="b1193198d7b2861efe14bf621f9caeefe7cfdf4d"
RESEARCH_ONLY=True
LIVE_ENABLED=False
PAPER_ELIGIBLE=False
ENTRY_SIGNAL=False
V52_UNCHANGED=True
ORDER_ADAPTER=None
EXPECTED_1M_COUNTS=(4,2,4,2,4)
MINUTE=v90.MINUTE_MS


def _verified_last_degree_leg(candidate:dict,index:int) -> dict:
    """Source-attested input from V95 required at outer call."""
    hard=candidate["v83"]
    nested=candidate["v86"]
    times=hard["vertex_center_ms"]
    a,b=times[index:index+2]
    segment=nested["legs"][index]
    original=segment["all_interior_strict_pivots"]
    dual=segment["ambiguous_unordered_1m_center_ms"]
    exp=EXPECTED_1M_COUNTS[index]
    needed_high=((hard["orientation"]=="bullish")== (index%2==0))
    direction="up" if needed_high else "down"
    left_kind="low" if needed_high else "high"
    right_kind="high" if needed_high else "low"
    reasons=[]
    if len(original)!=exp or nested["per_leg_inner_counts"][index]!=exp:
        reasons.append("STRICT_UNPRUNED_1M_PRIMITIVE_COUNT_NOT_FROZEN_DEGREE")
    if dual:
        reasons.append("INTRA_MINUTE_HIGH_LOW_ORDER_UNKNOWN")
    endpoints=[{"center_ms":a,"kind":left_kind,"confirmed_ms":hard["vertex_confirmed_ms"][index]}]
    endpoints.extend(original)
    endpoints.append({"center_ms":b,"kind":right_kind,
                      "confirmed_ms":hard["vertex_confirmed_ms"][index+1]})
    asof=candidate["first_observable_ms"]
    for i,x in enumerate(endpoints):
        if (type(x.get("center_ms")) is not int or
            type(x.get("confirmed_ms")) is not int or
            x["center_ms"]%MINUTE or
            not x["center_ms"]<x["confirmed_ms"]<=asof):
            reasons.append("FUTURE_OR_INVALID_TERMINAL_CONFIRMATION")
            break
        if x.get("kind")!=("low" if needed_high == (i%2==0) else "high"):
            reasons.append("NONALTERNATING_TERMINAL_POLARITY")
        if i and not endpoints[i-1]["center_ms"]<x["center_ms"]:
            reasons.append("TERMINAL_NONMONOTONIC_OR_OVERLAPPING")
            break
    reasons=list(dict.fromkeys(reasons))
    return {"leg_index":index+1,"expected_interior_pivots":exp,
            "observed_interior_pivots":len(original),
            "terminal_extrema_unordered":len(dual),
            "direction":direction,
            "boundaries_ms":[a,b],
            "source_endpoint_centers_ms":[x["center_ms"] for x in endpoints],
            "rejection_reasons":reasons,
            "necessary_degree_shape_pass":not reasons,
            "full_recursive_degree_proven":False,
            "bybit_demo_eligible":False}


def bridge_attested_candidate(candidate:dict,mins:list) -> dict:
    """Always revalidate original physical observations before grammar bridge."""
    checked=v95.attest_candidate(candidate,mins)
    if checked["physical_1m_primitives_verified"] is not True or (
        checked["new_entry_signal"] is not False):
        raise ValueError("physical input not source-attested")
    if len(candidate["v86"]["legs"])!=5:
        raise ValueError("incomplete source-bound five-leg hypothesis")
    hard=candidate["v83"]
    legs=[_verified_last_degree_leg(candidate,i) for i in range(5)]
    blockers=[]
    if hard.get("motive_geometry_pass") is not True:
        blockers.append("V83_CONVENTIONAL_OUTER_IMPULSE_HARD_GEOMETRY_FAIL")
    for leg in legs:
        blockers.extend("LEG"+str(leg["leg_index"])+"_"+r
                        for r in leg["rejection_reasons"])
    blockers=list(dict.fromkeys(blockers))
    syntax=None
    if not blockers:
        # Only when all original 1m primitive endpoints agree: instantiate
        # a degree=2 root with five degree=1 (hypothesized) constituents.
        children=[]
        for i,leg in enumerate(legs):
            centers=leg["source_endpoint_centers_ms"]
            direction=leg["direction"]
            family="IMPULSE" if i%2==0 else "ZIGZAG"
            leaves=[]
            for j,(left,right) in enumerate(zip(centers,centers[1:])):
                subdir=(direction if j%2==0 else
                        ("down" if direction=="up" else "up"))
                leaves.append(v93.WaveNode(
                    "leg"+str(i+1)+".terminal"+str(j+1),"TERMINAL",0,
                    left,right,candidate["first_observable_ms"],subdir))
            children.append(v93.WaveNode(
                "leg"+str(i+1),family,1,centers[0],centers[-1],
                candidate["first_observable_ms"],direction,tuple(leaves)))
        orientation=("up" if hard["orientation"]=="bullish" else "down")
        root=v93.WaveNode("hypothesized_outer_impulse","IMPULSE",2,
                          children[0].start_ms,children[-1].end_ms,
                          candidate["first_observable_ms"],orientation,
                          tuple(children))
        syntax=v93.audit_graph(root)
        if syntax["independently_proven_market_wave"] is not False:
            raise ValueError("syntax parser cannot authenticate market Elliott")
    return {
        "first_observable_ms":candidate["first_observable_ms"],
        "week":candidate["week"],
        "orientation":hard["orientation"],
        "all_1m_terminals_verified_against_official_source":True,
        "all_original_primitives_retained":True,
        "outer_conventional_impulse_necessary_geometry":hard["motive_geometry_pass"],
        "per_leg":legs,"hard_blockers":blockers,
        "necessary_fixed_degree_53535_shape_pass":not blockers,
        "v93_syntactic_graph_result":syntax,
        "pattern_position_proven":False,
        "higher_degree_recursive_market_proof":False,
        "entry_signal":False,"paper_eligible":False,
        "live_enabled":False,"net_pnl":None,
    }


def verify_upstream_locked() -> tuple[dict,dict,dict,dict]:
    locked,receipt=v90.verify_locked_receipts()
    old=v91.sealed_v90()
    pinned=v93.immutable_receipt(
        V95_REL,V95_SHA,V95_COMMIT,
        "nexus.elliott-v95-physical-source-terminal-replay.v1")
    if (pinned["v90_motive_receipt_sha256"]!=v91.PRIOR_SHA
        or pinned["v89_official_source_receipt_sha256"]!=v90.SOURCE_RECEIPT_SHA
        or old["v89_source_receipt_sha256"]!=v90.SOURCE_RECEIPT_SHA):
        raise ValueError("independent source/terminal lineage diverged")
    return locked,receipt,old,pinned


def audit() -> dict:
    locked,receipt,old,pinned=verify_upstream_locked()
    report={
        "schema":"nexus.elliott-v96-physically-anchored-degree-bridge.v1",
        "recorded_utc":datetime.now(timezone.utc).isoformat(),
        "v95_source_witness_sha256":V95_SHA,
        "v95_source_witness_commit":V95_COMMIT,
        "v90_original_candidates_sha256":v91.PRIOR_SHA,
        "v88_source_lock_sha256":v90.v89.PREREG_HASH,
        "v89_source_archive_receipt_sha256":v90.SOURCE_RECEIPT_SHA,
        "evaluation_sample":"same pre-inspected historical 2024-07-01 through 14 UTC",
        "no_historical_rule_tuning":True,
        "data_is_not_prospective":True,
        "entry_signal":False,"paper_eligible":False,"live_enabled":False,
        "new_trades":0,"net_pnl":None,
        "complete_recursive_market_waves":0,
        "pattern_position_verified":False,"v52_unchanged":True,
        "symbols":{},
    }
    for symbol,size in (("BTCUSDT",6),("ETHUSDT",2)):
        mins=v90._parse_verified_source(symbol,locked,receipt)
        motives=old["symbols"][symbol]["five_leg_candidate_details"]
        previous=pinned["symbols"][symbol]["cases"]
        if len(motives)!=size or len(previous)!=size:
            raise ValueError("upstream population size changed")
        results=[]
        reasons=Counter()
        for motive,prior in zip(motives,previous):
            fresh=bridge_attested_candidate(motive,mins)
            if (fresh["first_observable_ms"]!=prior["first_observable_ms"]
                or fresh["week"]!=prior["week"]
                or not prior["physical_1m_primitives_verified"]
                or fresh["entry_signal"] is not False):
                raise ValueError("V95 attested candidate order/policy differs")
            for new,old_leg in zip(fresh["per_leg"],prior["leg_observations"]):
                if (new["observed_interior_pivots"]!=old_leg["source_1m_terminal_pivot_count"]
                    or new["terminal_extrema_unordered"]!=len(
                        old_leg["ambiguous_unordered_ohlc_centers_ms"])):
                    raise ValueError("independent source terminal count differed")
            for cause in fresh["hard_blockers"]:
                reasons[cause]+=1
            results.append(fresh)
        if any(x["higher_degree_recursive_market_proof"] or x["paper_eligible"]
               for x in results):
            raise ValueError("spurious market pattern or trading promotion")
        report["symbols"][symbol]={
            "complete_source_1m_rows":len(mins),
            "source_backed_motive_hypotheses":len(motives),
            "hypotheses_physically_replayed":len(results),
            "necessary_degree_skeleton_pass_count":sum(
                x["necessary_fixed_degree_53535_shape_pass"] for x in results),
            "full_recursive_wave_proven":0,
            "source_blocker_frequencies":dict(reasons),
            "cases":results,
        }
    ROOT.mkdir(parents=True,exist_ok=True)
    file=ROOT/"V96_DEGREE_BRIDGE_AUDIT.json"
    encoded=(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+"\n").encode("utf-8")
    if file.exists():
        stored=json.loads(file.read_bytes())
        current=json.loads(encoded)
        stored.pop("recorded_utc",None)
        current.pop("recorded_utc",None)
        if stored!=current:
            raise ValueError("V96 evidence differs from prior execution; fail closed")
        encoded=file.read_bytes()
    else:
        file.write_bytes(encoded)
    print(json.dumps({
        "status":"PHYSICAL_1M_TERMINALS_VERIFIED_HIERARCHY_STILL_UNPROVEN",
        "receipt_sha256":hashlib.sha256(encoded).hexdigest(),
        "symbols":{k:{"replayed":v["hypotheses_physically_replayed"],
            "necessary_degree_shape_pass":v["necessary_degree_skeleton_pass_count"],
            "reasons":v["source_blocker_frequencies"]}
            for k,v in report["symbols"].items()},
        "orders":0,"economic_pnl":None,
    },indent=2))
    return report


if __name__=="__main__":
    audit()
