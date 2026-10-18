"""Synthetic source/review fixtures only; no market replay or real approval."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

import nexus_complete_strategy_system as contract
from research.strategy_finder_shared_cash_physical import execution_contract, replay_shared_cash
from scripts import nexus_strategy_finder_executable_intake as intake
from test_nexus_strategy_finder_executable_intake import materialized, approval_base, permit


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw=(json.dumps(value, sort_keys=True, indent=2)+"\n").encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def full_system(tmp_path):
    root, rel, _, _=materialized(tmp_path)
    for name in contract.EXECUTOR_FILES:
        target=root/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((intake.ROOT/name).read_bytes())
    note={
        "schema":contract.SOURCE_SCHEMA,
        "source_url":"https://research.example.test/synthetic-source",
        "content_kind":"research_paraphrase_not_provider_raw_bytes",
        "provider_authentication_verified":False,
        "coverage":{"context":"Synthetic contextual claim for protocol tests only."},
    }
    note_path="research/source_notes/synthetic.json"
    note_sha=write(root/note_path,note)
    preliminary=intake.inspect_candidate(root,rel,approval_base())
    value={
        "schema":contract.SCHEMA,
        "candidate":{key:preliminary[key] for key in (
            "candidate_id","candidate_path","candidate_sha256","original_factory_contract_digest")},
        "source_notes":[{"id":"synthetic","path":note_path,"sha256":note_sha,"url":note["source_url"]}],
        "rule_bindings":{
            name:{"implementation":implementation,
                  "origin":"source" if name=="context" else "research_extension",
                  "source_ids":["synthetic"] if name=="context" else [],
                  "summary":"Synthetic explicit operational rule; used only to test full-system review binding."}
            for name,implementation in contract.BINDINGS.items()
        },
        "execution_contract":execution_contract(),
        "execution_source_sha256":contract.implementation_hashes(root),
        "study_window":{"warmup_utc":"2024-12-01T00:00:00Z", "start_utc":"2025-01-01T00:00:00Z",
                        "end_exclusive_utc":"2025-04-01T00:00:00Z"},
        "selection_basis":"one_frozen_hypothesis_no_posthoc_tournament",
        "research_only":True,"paper_eligible":False,"live_enabled":False,
        "automatic_strategy_promotion":False,
    }
    system_path="research/complete_systems/synthetic.json"
    system_sha=write(root/system_path,value)
    record={**permit(root,rel),"system_specification_path":system_path,
            "system_specification_sha256":system_sha,
            "execution_contract_digest":contract.digest(execution_contract())}
    allow=approval_base();allow["approved_executable_contracts"]=[record]
    write(root/intake.DEFAULT_ALLOWLIST,allow)
    return root,rel,value,allow


def reseal(root,value,allow):
    row=allow["approved_executable_contracts"][0]
    row["system_specification_sha256"]=write(root/row["system_specification_path"],value)
    write(root/intake.DEFAULT_ALLOWLIST,allow)


def test_complete_review_connects_source_rules_actual_executor_and_frozen_window(tmp_path):
    root,rel,value,allow=full_system(tmp_path)
    row=intake.inspect_candidate(root,rel,allow)
    assert row["status"]=="APPROVED_FOR_RESEARCH_SIMULATION_ONLY"
    bound=row["complete_system"]
    assert bound["system_digest"]==contract.digest(value)
    assert bound["execution_source_sha256"]==contract.implementation_hashes(root)
    assert bound["study_window"]==value["study_window"]
    assert bound["provider_authentication_verified"] is False
    assert bound["source_interpretation_independently_attested_here"] is False
    assert row["paper_eligible"] is False and row["orders"]==0


@pytest.mark.parametrize("field",["context","entry","exit","sizing","no_trade"])
def test_each_missing_system_component_blocks_before_market_io(tmp_path,monkeypatch,field):
    root,rel,value,allow=full_system(tmp_path)
    del value["rule_bindings"][field]
    reseal(root,value,allow)
    def forbidden(*args,**kwargs):
        raise AssertionError("market input was accessed for an incomplete system")
    monkeypatch.setattr(intake,"verify_pinned_market_files",forbidden)
    with pytest.raises(intake.IntakeError,match="must specify"):
        intake.evaluate_approved(root,rel,root/"absent",**value["study_window"])


@pytest.mark.parametrize("field,value",[("stop_range_multiple",3.),("target_r",5.),
                                      ("timeout_bars",32),("initial_shared_cash_usdt",10000.),
                                      ("portfolio_drawdown_kill","pretend_structural_stop")])
def test_unsupported_source_exit_or_risk_is_not_silently_replaced_by_defaults(tmp_path,field,value):
    root,rel,system,allow=full_system(tmp_path)
    system["execution_contract"][field]=value
    reseal(root,system,allow)
    with pytest.raises(intake.IntakeError,match="requires implementation review"):
        intake.inspect_candidate(root,rel,allow)


def test_changed_source_note_or_review_digest_cannot_run(tmp_path):
    root,rel,value,allow=full_system(tmp_path)
    (root/value["source_notes"][0]["path"]).write_text("{}")
    with pytest.raises(intake.IntakeError,match="source note digest"):
        intake.inspect_candidate(root,rel,allow)


def test_changed_executor_cannot_reuse_complete_system_review(tmp_path):
    root,rel,value,allow=full_system(tmp_path)
    path=root/contract.EXECUTOR_FILES[0]
    path.write_bytes(path.read_bytes()+b"\n# changed implementation\n")
    with pytest.raises(intake.IntakeError,match="executor code changed"):
        intake.inspect_candidate(root,rel,allow)


def test_source_article_with_no_entry_rule_cannot_be_attributed_an_entry_rule(tmp_path):
    root,rel,value,allow=full_system(tmp_path)
    value["rule_bindings"]["entry"].update(origin="source",source_ids=["synthetic"])
    reseal(root,value,allow)
    with pytest.raises(intake.IntakeError,match="does not substantiate"):
        intake.inspect_candidate(root,rel,allow)


def test_changed_study_window_is_denied_before_market_io(tmp_path,monkeypatch):
    root,rel,value,_=full_system(tmp_path)
    def forbidden(*args,**kwargs):
        raise AssertionError("market input accessed before freeze verification")
    monkeypatch.setattr(intake,"verify_pinned_market_files",forbidden)
    with pytest.raises(intake.IntakeError,match="window differs"):
        intake.evaluate_approved(root,rel,root/"absent",value["study_window"]["warmup_utc"],
                                 "2025-02-01T00:00:00Z",value["study_window"]["end_exclusive_utc"])


def test_signal_only_approval_cannot_start_a_market_run(tmp_path,monkeypatch):
    root,rel,_,_=materialized(tmp_path)
    allow=approval_base();allow["approved_executable_contracts"]=[permit(root,rel)]
    write(root/intake.DEFAULT_ALLOWLIST,allow)
    with pytest.raises(intake.IntakeError,match="REVIEW_REQUIRED_COMPLETE_SYSTEM"):
        intake.evaluate_approved(root,rel,root/"absent","2024-12-01T00:00:00Z",
                                 "2025-01-01T00:00:00Z","2025-04-01T00:00:00Z")


def test_execution_contract_matches_actual_synthetic_account_and_exit_geometry():
    times=pd.date_range("2025-01-01T00:15:00Z",periods=8,freq="15min")
    frame=pd.DataFrame({"decision_at":times,"open":100.,"high":110.,"low":99.,"close":100.,"atr":2.})
    frames={symbol:frame.copy() for symbol in ("BTCUSDT","ETHUSDT")}
    signals={"BTCUSDT":np.array([True]+[False]*7),"ETHUSDT":np.zeros(8,dtype=bool)}
    result=replay_shared_cash(frames,signals,0,8,"conservative")
    profile=execution_contract();trade=result["ledger"][0]
    assert result["initial_shared_cash_usdt"]==profile["initial_shared_cash_usdt"]==500.
    assert trade["entry_fill"]-trade["stop"]==pytest.approx(profile["stop_range_multiple"]*2.)
    assert trade["target"]-trade["entry_fill"]==pytest.approx(
        profile["target_r"]*(trade["entry_fill"]-trade["stop"]))
    assert trade["qty"]*trade["entry_fill"]<=profile["max_gross_usdt"]
    assert profile["minimum_trade_count"] is None and profile["orders"]==0
    assert profile["range_proxy"].endswith("not_wilder_atr")


def test_committed_elliott_note_is_pattern_evidence_with_explicit_system_gaps():
    path=intake.ROOT/"research/source_notes/ewi_impulse_scope_20261018.json"
    value=json.loads(path.read_text())
    assert value["source_url"]=="https://www.elliottwave.com/waveopedia/impulse/"
    assert value["coverage"]["context"]
    assert all(value["coverage"][field] is None for field in ("entry","exit","sizing","no_trade"))
    assert value["automatic_implementation"] is False


def test_duplicate_json_keys_and_unreviewed_system_path_fail_closed(tmp_path):
    root,rel,value,allow=full_system(tmp_path)
    row=allow["approved_executable_contracts"][0]
    path=root/row["system_specification_path"]
    raw=b'{"schema":"first","schema":"second"}'
    path.write_bytes(raw);row["system_specification_sha256"]=hashlib.sha256(raw).hexdigest()
    with pytest.raises(intake.IntakeError,match="unreadable"):
        intake.inspect_candidate(root,rel,allow)
    row["system_specification_path"]="../arbitrary.json"
    with pytest.raises(intake.IntakeError,match="committed bounded"):
        intake.inspect_candidate(root,rel,allow)


def test_real_cli_entrypoint_resolves_repository_from_an_unrelated_directory(tmp_path):
    env=dict(os.environ);env.pop("PYTHONPATH",None)
    result=subprocess.run([sys.executable,str(Path(intake.__file__).resolve()),"--help"],
                          cwd=tmp_path,env=env,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    assert "--candidate-relative" in result.stdout
