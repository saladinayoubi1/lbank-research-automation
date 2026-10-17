"""Original 2025 Q1 Strategy Finder 114-executable semantic evidence integrity.

Historical, descriptive SIGNAL-ONLY evidence; no market P/L is inferred.
"""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/"docs"/"evidence"/"strategy-finder-priorday-semantic-20261018"
ORIGINAL_SHA="ad20bb4b3d18da4b601793c6bdccdf42623187803df7389ffb2b6da3e75be92d"
NEIGHBOR_DIGEST="72e4cbe1c03f4582d16385a189f6f18b6cd8ed154576043e68dd2c7641fc8eaf"
FULL_DIGEST="212b5e6e73b83639a017ad412c4889791f684d5965dec259b63944acc57fd1c4"


def load(filename):
    data=json.loads((EVIDENCE/filename).read_text("utf8"))
    core={key:value for key,value in data.items()
          if key not in ("report_digest","result_digest")}
    digest=sha256(json.dumps(core,sort_keys=True,separators=(",",":"),
                            allow_nan=False).encode()).hexdigest()
    return data,digest


def test_original_preregistered_executable_proposal_bytes_unchanged():
    p=ROOT/"research"/"intake_candidates"/"factory_prior_day_sweep_peer_resilience_v1.json"
    # GitHub Windows checkout may CRLF-normalize the working-tree JSON while
    # the reviewed Git blob and raw source SHA retain LF. Normalize ONLY EOL,
    # never strip whitespace, reorder JSON or weaken the original SHA lock.
    raw=p.read_bytes()
    assert sha256(raw.replace(b"\r\n",b"\n")).hexdigest()==ORIGINAL_SHA


def test_neighbor_audit_digest_source_and_non_economic_scope():
    data,digest=load("2025q1-original-source-signal-overlap.json")
    assert digest==data["report_digest"]==NEIGHBOR_DIGEST
    assert data["original_candidate_raw_sha256"]==ORIGINAL_SHA
    assert data["market_profitability_tested"] is False
    assert data["economically_novel_proven"] is False
    assert data["independent_semantic_review_completed"] is False
    assert data["research_allowlist_still_empty"] is True
    assert data["live_enabled"] is False and data["orders"]==0


def test_full_audit_digest_and_all_114_record_tables():
    data,digest=load("2025q1-all-114-original-signal-overlap.json")
    assert digest==data["result_digest"]==FULL_DIGEST
    assert data["original_mechanisms_compared"]==114
    assert data["candidate_raw_sha256"]==ORIGINAL_SHA
    for symbol in ("BTCUSDT","ETHUSDT"):
        row=data["symbols"][symbol]
        names=[x["mechanism"] for x in row["all_original_overlap_records"]]
        assert len(names)==len(set(names))==114
        assert row["original_mechanisms_compared"]==114
        assert row["source_decision_bars"]==8640


def test_causal_event_union_counts_reconcile_without_double_counting():
    data,_=load("2025q1-all-114-original-signal-overlap.json")
    for symbol,expected in (("BTCUSDT",(7,3,4)),("ETHUSDT",(8,7,1))):
        r=data["symbols"][symbol]
        count,covered,unmatched=expected
        assert r["candidate_events"]==count
        assert r["candidate_events_matching_at_least_one_old"]==covered
        assert r["candidate_events_not_matching_any_old"]==unmatched
        assert covered+unmatched==count
        assert r["old_any_event_decision_bars"]>=covered
        for old in r["all_original_overlap_records"]:
            intersection=old["candidate_exact_bar_overlap"]
            assert 0<=intersection<=min(count,old["original_signal_count"])
            assert old["candidate_only_vs_mechanism"]==count-intersection


def test_six_neighbor_audit_reconciles_with_full_frontier_counts():
    nearby,_=load("2025q1-original-source-signal-overlap.json")
    full,_=load("2025q1-all-114-original-signal-overlap.json")
    for symbol in ("BTCUSDT","ETHUSDT"):
        one=nearby["symbols"][symbol]
        all_rows=full["symbols"][symbol]
        assert one["candidate_signals"]==all_rows["candidate_events"]
        assert one["evaluated_closed_15m_bars"]==all_rows["source_decision_bars"]
        records={r["mechanism"]:r for r in all_rows["all_original_overlap_records"]}
        for name,old in one["old_family_overlap"].items():
            assert old["old_signals"]==records[name]["original_signal_count"]
            assert old["same_bar_intersection"]==records[name]["candidate_exact_bar_overlap"]
            assert old["candidate_only_vs_family"]==records[name]["candidate_only_vs_mechanism"]


def test_original_source_and_proposal_permit_remain_research_only():
    a,_=load("2025q1-all-114-original-signal-overlap.json")
    b,_=load("2025q1-original-source-signal-overlap.json")
    assert a["source_six_sha256"]==b["six_original_bybit_source_sha256"]
    assert len(a["source_six_sha256"])==6
    assert a["source_already_inspected"] is True
    assert a["market_profitability_tested"] is False
    assert a["not_global_semantic_novelty_proof"] is True
    assert a["qualified"] is False
    assert a["paper_eligible"] is False
    assert a["live_enabled"] is False
    assert a["orders"]==0
    approved=json.loads((ROOT/"research"/"strategy_finder_executable_intake_allowlist_v1.json").read_text("utf8"))
    assert approved["approved_executable_contracts"]==[]
