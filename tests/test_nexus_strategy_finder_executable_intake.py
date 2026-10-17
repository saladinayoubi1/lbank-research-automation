"""Review-only executable Strategy Finder intake adversarial policy tests."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from nexus_mechanism_factory import load_factory_contract
from scripts import nexus_strategy_finder_executable_intake as module


def approval_base():
    return {
        "schema":module.APPROVAL_SCHEMA,
        "status":"NO_INDEPENDENTLY_REVIEWED_NEW_EXECUTABLE_CONTRACTS",
        "research_only":True,"paper_only":True,
        "live_trading_authority":False,
        "automatic_strategy_promotion":False,
        "qualification_authority":False,
        "approved_executable_contracts":[],
    }


def materialized(tmp_path, *, ident="factory_new_original_event", unique=True,
                 metadata_only=False, threshold=None):
    root=tmp_path
    dest=root/"research"/"intake_candidates"
    dest.mkdir(parents=True,exist_ok=True)
    first=next(iter(module.FACTORY_SPECS.values()))
    item={k:deepcopy(first[k]) for k in (
        "id","family","hypothesis","peer_required","context","entry")}
    item["id"]=ident
    if metadata_only:
        item["family"]="completely_different_claim_but_same_actual_signal"
        item["hypothesis"]="Entirely different marketing description cannot change actual causal entry logic."
    if unique:
        item["context"].append({
            "field":"lagged_peer_lead_corr_96","op":"gt","value":0.12345})
        item["peer_required"]=True
    if threshold is not None:
        cond=next(x for x in item["context"] if "value" in x
                  and x["field"] not in (
                      "h4_up","h4_range","h1_compression","h1_vol_ok"))
        cond["value"]=threshold
    schema={
        "schema":"nexus.mechanism-factory.v1",
        "authority":"research-only-no-auto-promotion",
        "selection_basis":"training_partition_only",
        "no_minimum_trade_count_gate":True,
        "auto_demo_promotion":False,
        "live_trading_authority":False,
        "candidates":[item],
    }
    path=dest/"candidate.json"
    path.write_text(json.dumps(schema,sort_keys=True,indent=2)+"\n",encoding="utf8")
    return root,"research/intake_candidates/candidate.json",path,schema


def permit(root,rel):
    row=module.inspect_candidate(root,rel,approval_base())
    return {
        "candidate_path":rel,
        "candidate_id":row["candidate_id"],
        "candidate_sha256":row["candidate_sha256"],
        "qualitative_signature":row["qualitative_signature"],
        "review_pr_url":"https://github.com/saladinayoubi1/lbank-research-automation/pull/2715",
        "independent_legacy_semantic_review":True,
        "source_provenance_review":True,
        "rationale":"This is a synthetic test approval record used exclusively inside isolated pytest, not a real new trading strategy approval.",
    }


def test_original_repo_allowlist_intentionally_empty_and_no_authority():
    path=module.ROOT/module.DEFAULT_ALLOWLIST
    value=json.loads(path.read_text("utf8"))
    assert value==approval_base()
    assert value["approved_executable_contracts"]==[]


def test_new_executable_grammar_is_not_executable_until_separate_review(tmp_path):
    root,rel,_,_=materialized(tmp_path)
    value=module.inspect_candidate(root,rel,approval_base())
    assert value["status"]=="REVIEW_REQUIRED_NO_SEPARATE_APPROVAL"
    assert value["matching_existing_executable_ids"]==[]
    assert value["paper_eligible"] is False
    assert value["orders"]==0 and value["live_enabled"] is False


def test_separately_signed_exact_contract_can_pass_only_research_gate(tmp_path):
    root,rel,_,_=materialized(tmp_path)
    allow=approval_base()
    allow["approved_executable_contracts"]=[permit(root,rel)]
    row=module.inspect_candidate(root,rel,allow)
    assert row["status"]=="APPROVED_FOR_RESEARCH_SIMULATION_ONLY"
    assert row["global_economic_semantic_novelty_proven"] is False
    assert row["strategy_proven_profitable"] is False


def test_changed_threshold_alone_is_not_semantically_novel():
    first=next(iter(module.FACTORY_SPECS.values()))
    a=deepcopy(first)
    b=deepcopy(first)
    item=next(x for x in b["context"] if "value" in x and x["field"] not in (
        "h4_up","h4_range","h1_compression","h1_vol_ok"))
    item["value"]=float(item["value"])*1.05
    assert module.structural_signature(a)==module.structural_signature(b)


def test_changed_name_family_hypothesis_only_does_not_pass(tmp_path):
    root,rel,_,_=materialized(tmp_path,ident="factory_fake_novel",unique=False,metadata_only=True)
    row=module.inspect_candidate(root,rel,approval_base())
    assert row["status"]=="REJECT_DUPLICATE_EXECUTABLE_TOPOLOGY"
    assert row["matching_existing_executable_ids"]


def test_exact_existing_id_never_accepted_even_with_new_context(tmp_path):
    existing=next(iter(module.FACTORY_SPECS))
    root,rel,_,_=materialized(tmp_path,ident=existing,unique=True)
    allow=approval_base()
    allow["approved_executable_contracts"]=[permit(root,rel)]
    result=module.inspect_candidate(root,rel,allow)
    assert result["status"]=="REJECT_DUPLICATE_EXECUTABLE_ID"


def test_condition_order_does_not_count_as_new_mechanism():
    first=next(iter(module.FACTORY_SPECS.values()))
    a=deepcopy(first)
    b=deepcopy(first)
    b["context"]=list(reversed(b["context"]))
    b["entry"]=list(reversed(b["entry"]))
    assert module.structural_signature(a)==module.structural_signature(b)


def test_duplicate_conjunctive_condition_refused(tmp_path):
    root,rel,path,schema=materialized(tmp_path)
    schema["candidates"][0]["context"].append(
        deepcopy(schema["candidates"][0]["context"][0]))
    path.write_text(json.dumps(schema))
    with pytest.raises(module.IntakeError,match="repeated"):
        module.inspect_candidate(root,rel,approval_base())


def test_stale_review_sha_rejected_on_causal_rule_changed(tmp_path):
    root,rel,path,schema=materialized(tmp_path)
    allow=approval_base()
    allow["approved_executable_contracts"]=[permit(root,rel)]
    schema["candidates"][0]["hypothesis"]+=" Updated after initial independent review."
    path.write_text(json.dumps(schema))
    row=module.inspect_candidate(root,rel,allow)
    assert row["status"]=="REJECT_STALE_OR_MISMATCHED_APPROVAL"


def test_fake_external_candidate_path_denied(tmp_path):
    for bad in (
        "../evil.json","research/intake_candidates/../../bad.json",
        "docs/research/candidate.json","research/intake_candidates/foo.py",
    ):
        with pytest.raises(module.IntakeError,match="repo-local"):
            module.inspect_candidate(tmp_path,bad,approval_base())


def test_invalid_factory_field_rejected_before_any_data_access(tmp_path):
    root,rel,path,schema=materialized(tmp_path)
    schema["candidates"][0]["context"][0]["field"]="import os; os.system"
    path.write_text(json.dumps(schema))
    with pytest.raises(module.IntakeError,match="strict original reviewed"):
        module.inspect_candidate(root,rel,approval_base())


def test_untrusted_allowlist_does_not_widen_authority(tmp_path):
    root,rel,_,_=materialized(tmp_path)
    x=approval_base()
    x["live_trading_authority"]=True
    with pytest.raises(module.IntakeError,match="allowlist"):
        module.inspect_candidate(root,rel,x)
    x=approval_base()
    x["approved_executable_contracts"]=[{**permit(root,rel),"independent_legacy_semantic_review":False}]
    with pytest.raises(module.IntakeError,match="permit"):
        module.inspect_candidate(root,rel,x)


def test_unapproved_candidate_abort_before_any_archive_lookup(tmp_path,monkeypatch):
    root,rel,_,_=materialized(tmp_path)
    path=root/module.DEFAULT_ALLOWLIST
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(approval_base()))
    def forbidden(*args,**kwargs):
        raise AssertionError("unexpected archive/network/computation before research approval")
    monkeypatch.setattr(module,"verify_pinned_market_files",forbidden)
    with pytest.raises(module.IntakeError,match="cannot run"):
        module.evaluate_approved(
            root,rel,root/"fake_archive",
            "2025-01-01T00:00:00Z","2025-02-01T00:00:00Z",
            "2025-03-01T00:00:00Z"
        )


def test_first_committed_proposal_is_dsl_executable_but_blocked_from_all_replay():
    row=module.inspect_candidate(
        module.ROOT,
        "research/intake_candidates/factory_prior_day_sweep_peer_resilience_v1.json",
        approval_base(),
    )
    assert row["candidate_id"]=="factory_prior_day_sweep_peer_resilience"
    assert row["status"]=="REVIEW_REQUIRED_NO_SEPARATE_APPROVAL"
    assert not row["matching_existing_executable_ids"]
    assert row["global_economic_semantic_novelty_proven"] is False
    assert row["paper_eligible"] is False
    assert row["orders"]==0


def test_no_order_key_or_paper_authority_in_source():
    source=Path(module.__file__).read_text("utf8")
    assert "place_order(" not in source
    assert "create_order(" not in source
    assert module.SCHEMA
    assert module.DEFAULT_ALLOWLIST.as_posix().startswith("research/")
