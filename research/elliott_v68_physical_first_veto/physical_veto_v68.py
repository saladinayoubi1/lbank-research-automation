"""V68 physical-source-first historical Elliott false entry/exit veto.

Read-only V66 + V67 integration. Neither a real-time feed nor trade authority.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
from pathlib import Path
import json
from witness_v66 import audit_files, hash_file, ETH_1M_SHA, V63_RECEIPT_SHA
from veto_v67 import audit_retrospective_claim, SCHEMA

RESEARCH_ONLY=True
ENTRY_SIGNAL=False
EXIT_SIGNAL=False
PAPER_ELIGIBLE=False
LIVE_ENABLED=False
EXECUTABLE_QUOTE_PROOF=False
FILL_CONFIRMED=False
P_AND_L=None

def reattest_then_veto(source,receipt,*,proposed_entry_utc=None,proposed_exit_utc=None):
    """Require physical hashes and source pivots BEFORE evaluating any time."""
    df, original, physical=audit_files(Path(source),Path(receipt))
    if (len(df)!=7200 or
        physical.get("physically_attested_historical_vertices") is not True or
        physical.get("confirmed_1m_count")!=8 or
        physical.get("confirmed_3m_interior_count")!=6 or
        physical.get("confirmed_15m_parent_count")!=2):
        raise ValueError("PHYSICAL_SOURCE_WITNESS_INCOMPLETE")
    witnessed={"schema":SCHEMA,
        "verified_source_sha256":ETH_1M_SHA,
        "verified_v63_receipt_sha256":V63_RECEIPT_SHA,
        **physical}
    timing=audit_retrospective_claim(
        witnessed,proposed_entry_utc=proposed_entry_utc,
        proposed_exit_utc=proposed_exit_utc)
    if (timing.entry_signal or timing.exit_signal or
        timing.paper_eligible or timing.live_enabled or
        timing.fill_confirmed or timing.pnl is not None):
        raise AssertionError("NONEXECUTING_VETO_CONTRACT_BROKEN")
    return {
        "schema":"nexus.elliott-v68-physical-first-entry-exit-veto.v1",
        "historically_inspected":True,
        "source_sha256":hash_file(source),
        "child_receipt_sha256":hash_file(receipt),
        "source_bound_v66_recomputed":True,
        "closed_1m_candles":len(df),
        "confirmed_1m_pivots":physical["confirmed_1m_count"],
        "confirmed_3m_children":physical["confirmed_3m_interior_count"],
        "confirmed_15m_endpoints":physical["confirmed_15m_parent_count"],
        "hierarchical_geometry":physical["geometry_state"],
        "structural_confirmation_utc":physical["first_structural_pivot_decision_not_before_utc"],
        "timing_veto":asdict(timing),
        "research_only":True,
        "entry_signal":False,"exit_signal":False,"paper_eligible":False,
        "live_enabled":False,"executable_quote_proof":False,
        "fill_confirmed":False,"pnl":None}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source",required=True)
    p.add_argument("--receipt",required=True)
    p.add_argument("--output",required=True)
    p.add_argument("--entry")
    p.add_argument("--exit")
    a=p.parse_args()
    out=Path(a.output)
    if out.exists():raise RuntimeError("REFUSE_OVERWRITE_IMMUTABLE_AUDIT")
    result=reattest_then_veto(a.source,a.receipt,
        proposed_entry_utc=a.entry,proposed_exit_utc=a.exit)
    out.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf8")
    print(json.dumps({
        "status":"PHYSICAL_SOURCE_VERIFIED_BUT_TRADE_CLAIM_VETOED",
        "veto":result["timing_veto"]["state"],
        "physical_1m":result["closed_1m_candles"],
        "sha256":hash_file(out)},sort_keys=True))
if __name__=="__main__":main()
