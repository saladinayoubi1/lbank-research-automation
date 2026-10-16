"""V93 finite recursive Elliott grammar and pattern-position proof obligations.

A shape-valid synthetic proof tree NEVER authenticates physical candle witnesses
or enables a Demo order. Actual V91 evidence has no terminal source graph.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO=Path(__file__).resolve().parents[2]
ROOT=Path(tempfile.gettempdir()) / "nexus-elliott-v93-report"
V91_REL="docs/evidence/elliott-v91-nested-impulse-gate-20261017/V91_NESTED_ENTRY_EXIT_GATE.json"
V91_SHA="d4401a5606dee6a0842d1ee3752375dc95de732b9189eb3e65983640ec1715c0"
V91_COMMIT="1fa94b9432be9d13782f3f76c0bb48737c3bc445"
V92_REL="docs/evidence/elliott-v92-synthetic-execution-gate-20261017/V92_EXECUTION_CONTRACT_AUDIT.json"
V92_SHA="490b283bbf0cc218eec1e417df49f854fe4e4646e142a4d98b7bb244a097324a"
V92_COMMIT="48a29982e82856ea5242ceec156204e7c05618a3"
MINUTE_MS=60000
RESEARCH_ONLY=True
LIVE_ENABLED=False
PAPER_ELIGIBLE=False
ENTRY_SIGNAL=False
V52_UNCHANGED=True
ORDER_CONNECTOR=None
PREREGISTERED_RULES_ONLY=True
TERMINAL_PHYSICAL_SOURCE_VERIFIER_AVAILABLE=False
EXPECTED_IMPULSE_INNER=(4,2,4,2,4)


@dataclass(frozen=True)
class WaveNode:
    """Pure syntactic wave graph, not an authenticated source certificate."""
    label: str
    family: str
    degree: int
    start_ms: int
    end_ms: int
    known_ms: int
    direction: str
    children: tuple["WaveNode", ...]=()


def _allowed_family(parent: str,index: int,degree: int) -> frozenset[str]:
    if degree==1:
        return frozenset(("TERMINAL",))
    if parent=="IMPULSE":
        return (frozenset(("IMPULSE",)) if index%2==0
                else frozenset(("ZIGZAG","FLAT")))
    if parent=="ZIGZAG":
        return (frozenset(("IMPULSE",)) if index!=1
                else frozenset(("ZIGZAG","FLAT")))
    if parent=="FLAT":
        return (frozenset(("IMPULSE",)) if index==2
                else frozenset(("ZIGZAG","FLAT")))
    raise ValueError("unknown internal family")


def audit_graph(root: WaveNode, max_nodes: int=10000) -> dict:
    """Validate complete finite grammar, time and degree, never authenticity."""
    if type(max_nodes) is not int or max_nodes<1:
        raise ValueError("positive node bound required")
    seen=set()
    visited=0
    depth=0
    def walk(node: WaveNode,level: int) -> None:
        nonlocal visited,depth
        if type(node) is not WaveNode:
            raise ValueError("immutable typed WaveNode required")
        if id(node) in seen:
            raise ValueError("cycle or node reused in recursive tree")
        seen.add(id(node))
        visited+=1
        depth=max(depth,level)
        if visited>max_nodes or level>20:
            raise ValueError("unsafe recursive graph expansion")
        if (type(node.label) is not str or not node.label or
            node.family not in ("IMPULSE","ZIGZAG","FLAT","TERMINAL") or
            node.direction not in ("up","down") or
            type(node.degree) is not int or not 0<=node.degree<=8 or
            any(type(t) is not int or t%MINUTE_MS for t in
                (node.start_ms,node.end_ms,node.known_ms))):
            raise ValueError("typed degree, label, family, and aligned times required")
        if not 0<=node.start_ms<node.end_ms<=node.known_ms:
            raise ValueError("future, impossible or unconfirmed wave interval")
        if type(node.children) is not tuple:
            raise ValueError("wave children must be immutable tuple")
        if node.family=="TERMINAL":
            if node.degree!=0 or node.children:
                raise ValueError("terminal cannot claim unseen lower-degree waves")
            return
        if node.degree<1:
            raise ValueError("nonterminal lacks lower-degree hierarchy")
        required=5 if node.family=="IMPULSE" else 3
        if len(node.children)!=required:
            raise ValueError("wrong recursive subwave count")
        prior=node.start_ms
        for i,child in enumerate(node.children):
            if type(child) is not WaveNode:
                raise ValueError("untyped subwave")
            if child.degree!=node.degree-1:
                raise ValueError("subwave degree not strictly lower")
            if child.family not in _allowed_family(node.family,i,node.degree):
                raise ValueError("invalid motive versus corrective grammar")
            if child.start_ms!=prior or child.end_ms>node.end_ms:
                raise ValueError("subwave overlap, gap or boundary mismatch")
            if child.known_ms>node.known_ms:
                raise ValueError("future subwave confirmation")
            expected=(node.direction if i%2==0 else
                      ("down" if node.direction=="up" else "up"))
            if child.direction!=expected:
                raise ValueError("alternating subwave direction violated")
            prior=child.end_ms
            walk(child,level+1)
        if prior!=node.end_ms:
            raise ValueError("uncovered wave endpoint or future completion")
    walk(root,0)
    return {
        "status":"SYNTACTIC_RECURSIVE_SHAPE_ONLY",
        "structural_shape_consistent":True,
        "visited_nodes":visited,
        "max_degree_seen":root.degree,
        "tree_depth":depth,
        "physical_1m_and_subminute_provenance_verified":False,
        "independently_proven_market_wave":False,
        "entry_signal":False,"paper_eligible":False,"live_enabled":False,
    }


def immutable_receipt(path: str,sha256: str,commit: str,expected_schema: str) -> dict:
    raw=(REPO/path).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=sha256:
        raise ValueError("source receipt SHA altered")
    old=subprocess.run(["git","show",commit+":"+path],cwd=REPO,
                       check=True,capture_output=True).stdout
    if raw!=old:
        raise ValueError("source receipt differs from exact Git commit bytes")
    subprocess.run(["git","merge-base","--is-ancestor",commit,"HEAD"],
                   cwd=REPO,check=True,capture_output=True)
    result=json.loads(raw)
    if result.get("schema")!=expected_schema:
        raise ValueError("source receipt schema differs")
    return result


def preregistered_research_policy() -> dict:
    """Fixed exploratory FUTURE-ONLY hypothesis; not operational or backtested."""
    return {
        "status":"HYPOTHESIS_DECLARED_NOT_VALIDATED_OR_ENABLED",
        "apply_to_prior_inspected_july_samples":False,
        "requires_source_attested_recursive_tree":True,
        "requires_pattern_position":"prior 15m context and correct leading/ending class independently witnessed",
        "trigger":"after fully confirmed wave-5, first future completed 1m CLOSE past wave-5 outer extreme in motive direction",
        "entry":"earliest subsequent 1m OPEN, subject to certified bid/ask/fill constraints",
        "stop":"strictly invalidating outer wave-4 extreme; reject if on wrong side of entry",
        "target":"2R measured from execution entry to declared stop, hypothetical research heuristic",
        "timeout":"60 completed 1m bars after actual research entry; close only at first subsequent open",
        "nominal_risk_limit_usdt":"2.50",
        "paper_reference_balance_usdt":"500",
        "one_position_per_symbol":True,
        "disallow_overlap_and_immediate_reentry":True,
        "cost_gate":"real Bybit Demo spreads, quote age, fees, slippage and stop gap-loss must be observed before any simulation or promotion",
        "missing_quote_or_tick_or_contract_spec":"ABSTAIN",
        "simultaneous_stop_target":"STOP_FIRST_CONSERVATIVE",
        "stop_gap":"WORSE_NEXT_OPEN_NOT_STALE_STOP_PRICE",
        "training_or_optimization_using_v90_or_v91":False,
        "performance_claim":None,
        "signals_issued":0,
        "orders_issued":0,
        "live_enabled":False,
        "paper_eligible":False,
    }


def obligation_for_case(case: dict,execution: dict) -> dict:
    anatomy=case["nesting"]
    counts=anatomy["observed_counts"]
    expected=anatomy["expected_counts"]
    if (case["first_observable_ms"]!=anatomy["asof_ms"] or
        execution.get("order_admission")!="DENY" or
        anatomy.get("complete_recursive_elliott_proven") is not False or
        case.get("week") not in ("A","B")):
        raise ValueError("altered V91 candidate decisions or admissions")
    if (type(counts) is not list or type(expected) is not list or
        len(counts)!=5 or expected!=list(EXPECTED_IMPULSE_INNER) or
        any(type(x) is not int or x<0 for x in counts)):
        raise ValueError("source-bound primitive width/count contract altered")
    if (execution.get("earliest_bar_open_after_confirmation_ms")!=
        case["first_observable_ms"] or
        execution.get("new_entry_signal") is not False or
        any(execution.get(k) is not None for k in
            ("entry_price","protective_stop","take_profit","quantity","net_pnl"))):
        raise ValueError("lookahead or fabricated V91 entry parameters")
    mismatch=[i+1 for i,(a,b) in enumerate(zip(counts,expected)) if a!=b]
    reasons=[]
    if anatomy.get("outer_geometry_pass") is not True:
        reasons.append("V83_NONDIAGONAL_OUTER_GEOMETRY_FAIL")
    if anatomy.get("intraminute_dual_extremum_count",0)>0:
        reasons.append("UNORDERED_1M_OHLC_SOURCE_AMBIGUITY")
    if anatomy.get("nonalternating_reasons"):
        reasons.append("INVALID_1M_INNER_ALTERNATION")
    if mismatch:
        reasons.append("FIXED_53535_INNER_COUNT_MISMATCH")
    # These are missing *positive evidence*, not necessarily violated rules.
    reasons.extend((
        "NO_INDEPENDENT_RECURSIVE_CANDLE_BACKED_TREE",
        "NO_CERTIFIED_15M_PATTERN_POSITION_OR_PRECEDING_CONTEXT",
        "NO_POST_CONFIRMATION_MARKET_BREAKOUT_WITNESS",
        "NO_EXTERNALLY_VERIFIED_BYBIT_EXECUTION_FRICTIONS",
        "NO_REAL_ORDER_OR_POSITION_LIFECYCLE_VALIDATION",
    ))
    return {
        "asof_ms":case["first_observable_ms"],
        "week":case["week"],
        "original_anatomy_state":anatomy["state"],
        "original_1m_counts":counts,
        "precommitted_expected_1m_counts":expected,
        "mismatched_subwave_leg_numbers":mismatch,
        "dual_extremum_inside_nested_leg_count":
            anatomy["intraminute_dual_extremum_count"],
        "failed_or_missing_proof_obligations":reasons,
        "recursive_proof_tree_authenticated":False,
        "pattern_position_proven":False,
        "position_context_seen":False,
        "hypothesis_is_trade_ready":False,
        "admission":"DENY",
        "entry_signal":False,"paper_eligible":False,
        "live_enabled":False,"pnl":None,
    }


def audit_prior_cases() -> dict:
    v91=immutable_receipt(V91_REL,V91_SHA,V91_COMMIT,
        "nexus.elliott-v91-causal-nested-impulse-entry-exit-gate.v1")
    v92=immutable_receipt(V92_REL,V92_SHA,V92_COMMIT,
        "nexus.elliott-v92-synthetic-execution-contract-v1")
    if (v91.get("v90_committed_sha256")!=
        "1db892fcfe75699ded97151501e538d04c2fd8ae4084765c9e1cd4aa9fd4683a"
        or v92.get("v91_immutable_source_sha256")!=V91_SHA):
        raise ValueError("prior source/proof lineage broken")
    report={
        "schema":"nexus.elliott-v93-source-proof-obligations.v1",
        "recorded_utc":datetime.now(timezone.utc).isoformat(),
        "v91_receipt_sha256":V91_SHA,
        "v92_receipt_sha256":V92_SHA,
        "prior_case_data_reused_not_retuned":True,
        "rulebook_applies_future_only":True,
        "historical_not_prospective":True,
        "research_only":True,"paper_eligible":False,"live_enabled":False,
        "signals":0,"new_positions":0,"net_pnl":None,
        "terminal_physical_source_verifier_available":False,
        "experimental_post_confirmation_policy":preregistered_research_policy(),
        "symbols":{},
    }
    for symbol,expected_size in (("BTCUSDT",6),("ETHUSDT",2)):
        cases=v91["symbols"][symbol]["cases"]
        if len(cases)!=expected_size or v92["sources"][symbol]["denied"]!=expected_size:
            raise ValueError("source case cardinality or V92 denied population differs")
        results=[]
        counts=Counter()
        for item in cases:
            result=obligation_for_case(item,item["execution_gate"])
            for reason in result["failed_or_missing_proof_obligations"]:
                counts[reason]+=1
            results.append(result)
        report["symbols"][symbol]={
            "v91_cases_seen":len(results),
            "all_admissions_denied":len(results),
            "source_bound_recursive_tree_certificates":0,
            "pattern_position_certificates":0,
            "reason_frequencies":dict(counts),
            "cases":results,
        }
    ROOT.mkdir(parents=True,exist_ok=True)
    target=ROOT/"V93_PROOF_OBLIGATIONS.json"
    bytesout=(json.dumps(report,sort_keys=True,indent=2)+"\n").encode()
    if target.exists():
        prev=json.loads(target.read_bytes())
        cur=json.loads(bytesout)
        prev.pop("recorded_utc",None)
        cur.pop("recorded_utc",None)
        if prev!=cur:
            raise ValueError("prior V93 observation differs; no rewrite")
        bytesout=target.read_bytes()
    else:
        target.write_bytes(bytesout)
    print(json.dumps({
        "status":"V93_INDEPENDENT_PROOF_DEBT_AND_FUTURE_ONLY_RULEBOOK",
        "sha256":hashlib.sha256(bytesout).hexdigest(),
        "source_counts":{k:{"cases":v["v91_cases_seen"],
             "missing_recursive_tree":v["reason_frequencies"]["NO_INDEPENDENT_RECURSIVE_CANDLE_BACKED_TREE"],
             "inner_count_mismatch":v["reason_frequencies"].get("FIXED_53535_INNER_COUNT_MISMATCH",0)}
             for k,v in report["symbols"].items()},
        "signals":0,"orders":0,
    },indent=2))
    return report


if __name__=="__main__":
    audit_prior_cases()
