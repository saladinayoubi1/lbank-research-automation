"""V91 fixed-degree 5-3-5-3-5 impulse witness and fail-closed research admission.

Read-only audit of V90 Git-attested historical output. This DOES NOT
claim a full Elliott recursion or wire any order into Bybit/Demo.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from research.elliott_v82_causal_degree_observer.observer_v82 import MINUTE_MS

RESEARCH_ONLY=True
ENTRY_SIGNAL=False
PAPER_ELIGIBLE=False
LIVE_ENABLED=False
V52_UNCHANGED=True
EXECUTION_CONNECTOR_ENABLED=False
EXPECTED_COUNTS=(4,2,4,2,4)
PRIOR_SHA="1db892fcfe75699ded97151501e538d04c2fd8ae4084765c9e1cd4aa9fd4683a"
PRIOR_HEAD="cda4423b47926ea0b0b05ab6e38b5aa8e73c37e4"
PRIOR_REL="docs/evidence/elliott-v90-independent-replication-20261017/V90_REPLICATION_AUDIT.json"
REPO=Path(__file__).resolve().parents[2]
ROOT=Path(r"E:\NEXUS-QA\elliott-v91-nested-impulse-20261017")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sealed_v90() -> dict:
    raw=(REPO/PRIOR_REL).read_bytes()
    if sha(raw)!=PRIOR_SHA:
        raise ValueError("V90 evidence SHA mismatch; fail closed")
    committed=subprocess.run(["git","show",PRIOR_HEAD+":"+PRIOR_REL],
                             cwd=REPO,check=True,capture_output=True).stdout
    if raw!=committed:
        raise ValueError("V90 local data does not match committed source evidence")
    subprocess.run(["git","merge-base","--is-ancestor",PRIOR_HEAD,"HEAD"],
                   cwd=REPO,check=True,capture_output=True)
    payload=json.loads(raw)
    if (payload["v88_preregistration_sha256"] !=
            "fae91774a57f887fc14122b4b1c74a26f6c7ad5daac28488c4e440b836523899"
        or payload["v89_source_receipt_sha256"] !=
            "e1c3988f6112ccd12883e35704b63024dc56bf52cc7a38f36ef42e743c2ed7df"
        or payload["schema"]!="nexus.elliott-v90-locked-independent-structural-replication.v1"):
        raise ValueError("V88/V89/V90 receipt lineage invalid")
    return payload


def source_nested_anatomy(motive: dict) -> dict:
    """Falsification only: original 1m width-1 primitive counts ALL retained."""
    if type(motive) is not dict or "v83" not in motive or "v86" not in motive:
        raise ValueError("V90 attested motive detail required")
    hard=motive["v83"]
    inner=motive["v86"]
    asof=motive.get("first_observable_ms")
    if (type(asof) is not int or asof % MINUTE_MS
        or hard.get("first_observable_ms")!=asof
        or inner.get("asof_ms")!=asof or motive.get("week") not in ("A","B")):
        raise ValueError("inconsistent confirmed as-of timestamps")
    centers=hard.get("vertex_center_ms")
    confirmations=hard.get("vertex_confirmed_ms")
    legs=inner.get("legs")
    counts=inner.get("per_leg_inner_counts")
    if (type(centers) is not list or len(centers)!=6 or
        type(confirmations) is not list or len(confirmations)!=6 or
        type(legs) is not list or len(legs)!=5 or
        type(counts) is not list or len(counts)!=5):
        raise ValueError("source-bound five-leg anatomy incomplete")
    if any(type(x) is not int for x in centers+confirmations+counts):
        raise ValueError("non-integer source timing/count")
    if any(a>=b for a,b in zip(centers,centers[1:])) or any(
        not center<conf<=asof for center,conf in zip(centers,confirmations)):
        raise ValueError("future or unordered parent/child vertex")
    direction=hard.get("orientation")
    if direction not in ("bullish","bearish"):
        raise ValueError("unknown impulse orientation")
    start_high=direction=="bearish"
    contradictions=[]
    ambiguity_count=0
    for i,leg in enumerate(legs):
        if (leg.get("left_center_ms")!=centers[i] or
            leg.get("right_center_ms")!=centers[i+1] or
            leg.get("asof_ms")!=asof or
            leg.get("interior_count")!=counts[i]):
            raise ValueError("nested source leg boundaries changed")
        pivots=leg.get("all_interior_strict_pivots")
        duals=leg.get("ambiguous_unordered_1m_center_ms")
        if type(pivots) is not list or type(duals) is not list:
            raise ValueError("missing unpruned primitive source evidence")
        if len(pivots)!=counts[i]:
            raise ValueError("primitive counts inconsistent with stored observations")
        if any(type(t) is not int or not centers[i]<t<centers[i+1]
               for t in duals):
            raise ValueError("ambiguous OHLC event outside inspected leg")
        ambiguity_count+=len(duals)
        left_kind=("high" if start_high==(i%2==0) else "low")
        right_kind="low" if left_kind=="high" else "high"
        expected_next=right_kind
        prev=centers[i]
        for pivot in pivots:
            time=pivot.get("center_ms")
            confirmed=pivot.get("confirmed_ms")
            if (type(time) is not int or type(confirmed) is not int or
                not prev<time<centers[i+1] or not time<confirmed<=asof):
                raise ValueError("unconfirmed or unordered 1m subpivot")
            if pivot.get("kind")!=expected_next:
                contradictions.append(f"LEG{i+1}_INNER_POLARITY")
            expected_next="high" if expected_next=="low" else "low"
            prev=time
        if expected_next!=right_kind:
            contradictions.append(f"LEG{i+1}_END_POLARITY")
    if hard.get("entry_signal") is not False or hard.get("paper_eligible") is not False:
        raise ValueError("untrusted executable V90 impulse")
    if inner.get("entry_signal") is not False or inner.get("paper_eligible") is not False:
        raise ValueError("untrusted executable V90 nested anatomy")
    if hard.get("motive_geometry_pass") is not True:
        state="ORDINARY_IMPULSE_OUTER_GEOMETRY_FAIL"
    elif ambiguity_count:
        state="UNORDERED_OHLC_WITHIN_NESTED_LEG_ABSTAIN"
    elif contradictions:
        state="NONALTERNATING_SOURCE_INNER_PIVOTS"
    elif tuple(counts)!=EXPECTED_COUNTS:
        state="NESTED_53535_FIXED_DEGREE_COUNT_MISMATCH"
    else:
        state="NESTED_53535_SKELETON_ONLY_RECURSION_UNPROVEN"
    return {
        "state":state, "week":motive["week"],"asof_ms":asof,
        "orientation":direction,"observed_counts":counts,
        "expected_counts":list(EXPECTED_COUNTS),
        "intraminute_dual_extremum_count":ambiguity_count,
        "nonalternating_reasons":contradictions,
        "outer_geometry_pass":hard["motive_geometry_pass"],
        "five_three_five_three_five_inner_skeleton_only":
            state=="NESTED_53535_SKELETON_ONLY_RECURSION_UNPROVEN",
        "complete_recursive_elliott_proven":False,
        "entry_signal":False,"paper_eligible":False,"pnl":None,
    }


def research_entry_exit_gate(anatomy: dict) -> dict:
    """No order adapter; explicit missing preconditions rather than fake SL/TP."""
    if anatomy.get("entry_signal") is not False or anatomy.get("paper_eligible") is not False:
        raise ValueError("unsafe executable structure")
    if type(anatomy.get("asof_ms")) is not int:
        raise ValueError("known decision time required")
    # First physical 1m bar that can be observed *after* the prior closed bar.
    earliest_next_bar_open_ms=anatomy["asof_ms"]
    missing=[
        "RECURSIVE_ELLiOTT_SUBDEGREE_PROOF_NOT_AVAILABLE",
        "CONTEXT_AND_PATTERN_POSITION_NOT_CERTIFIED",
        "POST_CONFIRMATION_ENTRY_TRIGGER_NOT_DEFINED",
        "PREDECLARED_STOP_INVALIDATION_NOT_DEFINED",
        "PREDECLARED_EXIT_TAKE_PROFIT_TIMEOUT_NOT_DEFINED",
        "DEMO_ORDERBOOK_SPREAD_FEES_SLIPPAGE_UNVERIFIED",
        "BYBIT_DEMO_FILL_SL_TP_SEQUENCE_NOT_TESTED",
    ]
    return {
        "order_admission":"DENY",
        "earliest_bar_open_after_confirmation_ms":earliest_next_bar_open_ms,
        "must_not_use_pivot_center_as_entry_time":True,
        "missing_requirements":missing,
        "entry_price":None,
        "protective_stop":None,
        "take_profit":None,
        "timeout_exit":None,
        "quantity":None,
        "new_entry_signal":False,
        "paper_eligible":False,
        "live_enabled":False,
        "net_pnl":None,
    }


def audit() -> dict:
    base=sealed_v90()
    output={
        "schema":"nexus.elliott-v91-causal-nested-impulse-entry-exit-gate.v1",
        "observed_utc":datetime.now(timezone.utc).isoformat(),
        "v90_committed_sha256":PRIOR_SHA,
        "v90_commit":PRIOR_HEAD,
        "historical_research_only":True,
        "not_prospective_performance":True,
        "unchanged_v52":True,
        "research_only":True,
        "signals":0,"orders":0,"pnl":None,
        "paper_eligible":False,"live_enabled":False,
        "symbols":{},
    }
    for symbol in ("BTCUSDT","ETHUSDT"):
        cases=[]
        state_counts=Counter()
        count_by_week={"A":Counter(),"B":Counter()}
        details=base["symbols"][symbol]["five_leg_candidate_details"]
        for m in details:
            result=source_nested_anatomy(m)
            order=research_entry_exit_gate(result)
            state_counts[result["state"]]+=1
            count_by_week[result["week"]][result["state"]]+=1
            cases.append({"first_observable_ms":result["asof_ms"],
                          "week":result["week"],
                          "nesting":result,"execution_gate":order})
        if len(cases)!=base["symbols"][symbol]["all_weeks_counts"].get("motive_skeletons",0):
            raise ValueError("V90 motive population changed")
        if any(x["execution_gate"]["order_admission"]!="DENY" for x in cases):
            raise ValueError("V91 unexpectedly enabled order entry")
        output["symbols"][symbol]={
            "source_bound_five_leg_cases":len(cases),
            "state_counts":dict(state_counts),
            "states_by_week":{k:dict(v) for k,v in count_by_week.items()},
            "cases":cases,"proven_full_elliott":0,"new_demo_positions":0,
        }
    ROOT.mkdir(parents=True,exist_ok=True)
    file=ROOT/"V91_NESTED_ENTRY_EXIT_GATE.json"
    content=(json.dumps(output,indent=2,ensure_ascii=False,sort_keys=True)+"\n").encode()
    if file.exists():
        existing=json.loads(file.read_bytes())
        copy=json.loads(content)
        existing.pop("observed_utc",None)
        copy.pop("observed_utc",None)
        if existing!=copy:
            raise ValueError("frozen V91 result already differs; no overwrite")
        content=file.read_bytes()
    else:
        file.write_bytes(content)
    print(json.dumps({
        "stage":"V91",
        "evidence_sha256":sha(content),
        "summary":{k:v["state_counts"] for k,v in output["symbols"].items()},
        "confirmed_entries":0,
        "paper_eligible":False,
    },indent=2))
    return output


if __name__=="__main__":
    audit()
