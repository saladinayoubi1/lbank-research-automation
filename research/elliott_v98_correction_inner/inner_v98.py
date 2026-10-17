"""V98 source-backed A-B-C necessary-geometry tests, no Elliott certification.

Zigzag 5-3-5, Flat 3-3-5, *all* independent physical 1m width-1
pivots retained. This is post-hoc old-July diagnostic only, not a trade.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from research.elliott_v82_causal_degree_observer.observer_v82 import Minute, Witness, observe
from research.elliott_v90_frozen_replication import replicate_v90 as v90
from research.elliott_v91_impulse_nested_gate import nested_gate_v91 as v91
from research.elliott_v93_recursive_proof import proof_v93 as v93
from research.elliott_v95_physical_witness import witness_v95 as v95
from research.elliott_v97_family_geometry import family_v97 as v97

ROOT=Path(tempfile.gettempdir())/"nexus-elliott-v98-research"
V97_REL="docs/evidence/elliott-v97-restricted-family-geometry-20261017/V97_FAMILY_GEOMETRY_DIAGNOSTIC.json"
V97_SHA="672af410f645ca9e9430558dace50a1c3476a2ed62c97235b6c76f1de3320fcb"
V97_COMMIT="faa7ba39ecc83a65ad78c1e3ed297c80a37316b3"
ZIGZAG_535=(4,2,4)
FLAT_335=(2,2,4)
RESEARCH_ONLY=True
ENTRY_SIGNAL=False
PAPER_ELIGIBLE=False
LIVE_ENABLED=False
ORDER_ADAPTER=None
V52_UNCHANGED=True


def physical_1m_lower_leg(
    left: Witness, right: Witness, strict:list[dict], ambiguous:list[int],
    minutes:list[Minute], asof:int, role:str, required:int) -> dict:
    """One original source-bounded A/B/C leg, no primitive pruning."""
    if role not in ("MOTIVE","CORRECTION") or required not in (2,4):
        raise ValueError("fixed lower-degree family and count required")
    if not isinstance(left,Witness) or not isinstance(right,Witness):
        raise ValueError("typed source-backed parent/child witnesses required")
    if (left.kind==right.kind or left.center_ms>=right.center_ms
        or not left.center_ms<left.confirmed_ms<=asof
        or not right.center_ms<right.confirmed_ms<=asof):
        raise ValueError("invalid source-confirmed ABC constituent boundaries")
    interior=[p for p in strict if left.center_ms<p["center_ms"]<right.center_ms]
    dual=[t for t in ambiguous if left.center_ms<t<right.center_ms]
    blockers=[]
    if len(interior)!=required:
        blockers.append("UNPRUNED_STRICT_1M_COUNT_NOT_EXPECTED")
    if dual:
        blockers.append("INTRA_1M_HIGH_LOW_ORDER_UNKNOWN")
    vertices=[v97.witness_vertex(left)]
    vertices.extend(v97.PhysicalVertex(
        x["kind"],x["center_ms"],x["confirmed_ms"],Decimal(x["price"]))
        for x in interior)
    vertices.append(v97.witness_vertex(right))
    if any(v.confirmed_ms>asof or v.center_ms>=v.confirmed_ms
           for v in vertices):
        blockers.append("FUTURE_OR_UNCONFIRMED_1M_TERMINAL")
    if any(a.center_ms>=b.center_ms or a.kind==b.kind
           for a,b in zip(vertices,vertices[1:])):
        blockers.append("NONALTERNATING_OR_OUT_OF_ORDER_1M_TERMINALS")
    geometry={}
    if not blockers:
        families=("IMPULSE",) if role=="MOTIVE" else ("ZIGZAG","FLAT")
        for family in families:
            verdict=v97.evaluate(family,tuple(vertices),minutes,asof)
            geometry[family]={
                "restricted_necessary_geometry_pass":verdict["restricted_geometry_pass"],
                "reject_reasons":verdict["rejections"],
            }
        if not any(x["restricted_necessary_geometry_pass"] for x in geometry.values()):
            blockers.append("NO_ALLOWED_LOWER_DEGREE_GEOMETRY")
    return {
        "expected_1m_interior_count":required,
        "observed_unpruned_1m_interior_count":len(interior),
        "all_interior_source_pivots_sha256":hashlib.sha256(v95.canonical(interior)).hexdigest(),
        "first_center_ms":left.center_ms,
        "final_center_ms":right.center_ms,
        "ambiguous_dual_centers_ms":dual,
        "role":role,"strict_physical_1m_observed":True,
        "degree_geometry_reject_reasons":blockers,
        "family_geometry":geometry,
        "necessary_shape_and_geometry_pass":not blockers,
        "certified_elliott_subwave":False,
        "new_entry_signal":False,
    }


def check_correction_candidate(
    endpoints:list[Witness], source:list[Minute],asof:int,
    original_v87:dict, locked_v97:dict) -> dict:
    """Source-backed replay of 1m subwave geometry, no lookahead."""
    if (type(endpoints) is not list or len(endpoints)!=4
        or not all(isinstance(x,Witness) for x in endpoints)):
        raise ValueError("exactly four physical A-B-C vertices required")
    if (original_v87["asof_ms"]!=asof or
        original_v87["entry_signal"] is not False or
        original_v87["paper_eligible"] is not False or
        locked_v97["first_observable_ms"]!=asof or
        locked_v97["original_V82_candidate_type"]!="CORRECTION"):
        raise ValueError("frozen upstream ABC admission/decision changed")
    if ([w.center_ms for w in endpoints]!=original_v87["outer_vertex_centers_ms"]
        or [w.confirmed_ms for w in endpoints]!=
            original_v87["outer_vertex_confirmations_ms"]):
        raise ValueError("source backed ABC original vertex timing changed")
    strict, dual=v95.independent_1m_extrema(source,asof)
    legs=original_v87["observed_inner_pivots_all_legs"]
    counts=[]
    for i,(left,right,prior) in enumerate(zip(endpoints,endpoints[1:],legs)):
        subset=[x for x in strict if left.center_ms<x["center_ms"]<right.center_ms]
        ambiguous=[t for t in dual if left.center_ms<t<right.center_ms]
        if (prior["left_center_ms"]!=left.center_ms
            or prior["right_center_ms"]!=right.center_ms
            or prior["right_confirmed_asof_ms"]!=asof
            or prior["observed_interior_count"]!=len(subset)
            or prior["all_interior_pivots"]!=subset
            or prior["ambiguous_dual_center_ms"]!=ambiguous):
            raise ValueError("V87 primitive material differs from independently sourced V95")
        counts.append(len(subset))
    if (counts!=original_v87["inner_counts_ABC"] or
        original_v87["ambiguous_dual_extrema_centers_ms"]!=
            [t for i in range(3) for t in dual
             if endpoints[i].center_ms<t<endpoints[i+1].center_ms]):
        raise ValueError("V87 counts or ambiguity ledger tampered")
    results={}
    for family,expect in (("ZIGZAG",ZIGZAG_535),("FLAT",FLAT_335)):
        diagnostic=locked_v97["families_diagnosed"][family]
        if diagnostic["family"]!=family or not diagnostic["source_1m_wicks_verified"]:
            raise ValueError("V97 outer family geometry record changed")
        # Consistently perform all three lower-leg audits; do not short-circuit
        # after a failed outer geometry or an unexpected source pivot.
        inner=[]
        for i,(left,right) in enumerate(zip(endpoints,endpoints[1:])):
            role="MOTIVE" if expect[i]==4 else "CORRECTION"
            inner.append(physical_1m_lower_leg(
                left,right,strict,dual,source,asof,role,expect[i]))
        blockers=[]
        if not diagnostic["restricted_geometry_pass"]:
            blockers.append("PARENT_RESTRICTED_OUTER_GEOMETRY_FAIL")
        for i,leg in enumerate(inner):
            blockers.extend("ABC"[i]+"_"+b for b in leg["degree_geometry_reject_reasons"])
        blockers=list(dict.fromkeys(blockers))
        results[family]={
            "outer_restricted_geometry_only":diagnostic["restricted_geometry_pass"],
            "frozen_counts_expected":list(expect),"observed_unpruned_counts":counts,
            "lower_constituent_diagnostics":inner,
            "blockers":blockers,
            "necessary_fixed_degree_family_diagnostics_pass":not blockers,
            "actual_recursive_wave_certificate":False,
            "pattern_position_certificate":False,
            "paper_eligible":False,"entry_signal":False,
        }
    return {
        "asof_ms":asof,
        "all_source_strict_1m_pivots_replayed":True,
        "all_ABC_inner_1m_pivots_exactly_match_V87":True,
        "v87_state":original_v87["state"],
        "v87_original_inner_counts":counts,
        "independent_ABC_motive_and_correction_geometry":results,
        "full_recursive_elliott_certified":False,
        "pattern_position_proven":False,
        "new_entry_signal":False,"paper_eligible":False,"live_enabled":False,
        "net_pnl":None,
    }


def audit_preinspected_corrections() -> dict:
    locked=v93.immutable_receipt(V97_REL,V97_SHA,V97_COMMIT,
        "nexus.elliott-v97-restricted-family-geometry-posthoc-diagnostics.v1")
    manifest,source_receipt=v90.verify_locked_receipts()
    original=v91.sealed_v90()
    if (locked["source_v90_sha256"]!=v91.PRIOR_SHA or
        locked["official_v89_sha256"]!=v90.SOURCE_RECEIPT_SHA or
        original["v89_source_receipt_sha256"]!=v90.SOURCE_RECEIPT_SHA):
        raise ValueError("V90/V97 immutable source chain unexpectedly changed")
    report={
        "schema":"nexus.elliott-v98-physical-abc-inner-geometry-diagnostics.v1",
        "recorded_utc":datetime.now(timezone.utc).isoformat(),
        "v97_immutable_receipt_sha256":V97_SHA,
        "v97_immutable_commit":V97_COMMIT,
        "v90_source_immutable_sha256":v91.PRIOR_SHA,
        "v89_official_source_receipt_sha256":v90.SOURCE_RECEIPT_SHA,
        "period":"ALREADY_INSPECTED_JULY_2024_NOT_PROSPECTIVE",
        "all_1m_primitives_retained":True,
        "original_thresholds_not_retuned":True,
        "research_only":True,"paper_eligible":False,"live_enabled":False,
        "new_signals":0,"new_orders":0,"net_pnl":None,
        "recursive_elliott_certificates":0,
        "v52_unchanged":True,
        "symbols":{},
    }
    for symbol,expected in (("BTCUSDT",9),("ETHUSDT",14)):
        minutes=v90._parse_verified_source(symbol,manifest,source_receipt)
        observer=observe(minutes,v90.END_MS)
        parents=[Witness(**x) for x in observer["parent_witnesses"]]
        children=[Witness(**x) for x in observer["child_witnesses"]]
        source_map={}
        for a,b in zip(parents,parents[1:]):
            source_map[(a.center_ms,b.center_ms)]=(
                a,b,v90.matching_children(a,b,children,max(a.confirmed_ms,b.confirmed_ms)))
        prior=original["symbols"][symbol]["three_leg_candidate_details"]
        earlier=[x for x in locked["symbols"][symbol]["cases"]
                 if x["original_V82_candidate_type"]=="CORRECTION"]
        if len(prior)!=expected or len(earlier)!=expected:
            raise ValueError("original 23 original correction cases no longer exhaustive")
        cases=[]
        reasons=Counter()
        for item,pin in zip(prior,earlier):
            left,right=item["source_parent_centers_ms"]
            a,b,middle=source_map[(left,right)]
            if (item["first_observable_ms"]!=pin["first_observable_ms"]
                or item["week"]!=pin["week"] or len(middle)!=2 or
                [a.center_ms,b.center_ms]!=item["source_parent_centers_ms"]
                or pin["families_diagnosed"]["ZIGZAG"]["vertex_centers_ms"]!=[
                     a.center_ms,*[x.center_ms for x in middle],b.center_ms]):
                raise ValueError("source ABC intervals or witness chronology tampered")
            asof=item["first_observable_ms"]
            verts=[a,*middle,b]
            # Independent V97 outer evaluator MUST agree with pinned V97
            # diagnostics for all old cases, not just the optimistic passes.
            for family in ("ZIGZAG","FLAT"):
                fresh=v97.evaluate(
                    family,tuple(v97.witness_vertex(x) for x in verts),minutes,asof)
                if fresh!=pin["families_diagnosed"][family]:
                    raise ValueError("V97 committed correction family verdict diverged")
            checked=check_correction_candidate(
                verts,minutes,asof,item["v87"],pin)
            checked["source_week"]=item["week"]
            for family,result in checked["independent_ABC_motive_and_correction_geometry"].items():
                if result["necessary_fixed_degree_family_diagnostics_pass"]:
                    reasons[family+"_SUBWAVE_NECESSARY_DIAGNOSTICS_PASS"]+=1
                if result["outer_restricted_geometry_only"]:
                    reasons[family+"_OUTER_GEOMETRY_PASS"]+=1
                for r in result["blockers"]:
                    reasons[family+"_"+r]+=1
            cases.append(checked)
        report["symbols"][symbol]={
            "physical_1m_source_rows":len(minutes),
            "original_ABC_skeletons":expected,
            "source_verified_ABC_diagnostics":len(cases),
            "all_V87_all_1m_strict_primitives_matched":True,
            "family_diagnostic_frequency":dict(reasons),
            "certified_market_recursive_elliott_patterns":0,
            "qualified_demo_positions":0,
            "cases":cases,
        }
    ROOT.mkdir(parents=True,exist_ok=True)
    dest=ROOT/"V98_ABC_SOURCE_INNER_GEOMETRY.json"
    payload=(json.dumps(report,sort_keys=True,indent=2,ensure_ascii=False)+"\n").encode()
    if dest.exists():
        previous=json.loads(dest.read_bytes())
        current=json.loads(payload)
        previous.pop("recorded_utc",None)
        current.pop("recorded_utc",None)
        if previous!=current:
            raise ValueError("immutable V98 output differs; no silent retune")
        payload=dest.read_bytes()
    else:
        dest.write_bytes(payload)
    print(json.dumps({
        "phase":"V98_LOCKED_ABC_PHYSICAL_LOWER_DEGREE",
        "receipt_sha256":hashlib.sha256(payload).hexdigest(),
        "symbols":{k:{
            "ABC_original_candidates":v["original_ABC_skeletons"],
            "inspected":v["source_verified_ABC_diagnostics"],
            "outcomes":v["family_diagnostic_frequency"],
        } for k,v in report["symbols"].items()},
        "certified_complete_patterns":0,"new_orders":0,
    },indent=2))
    return report


if __name__=="__main__":
    audit_preinspected_corrections()
