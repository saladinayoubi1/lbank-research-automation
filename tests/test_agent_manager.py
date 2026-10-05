from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

import agent_manager as am


def base_config():
    return {
        "schema_version": 1,
        "phase": 4,
        "policy": {"max_parallel_tasks": 4},
        "workers": [
            {"id": "dev", "capabilities": ["implementation", "diagnostics"], "resources": ["cloud"], "authority_max": 3, "enabled": True, "verifier": False},
            {"id": "qa", "capabilities": ["implementation", "diagnostics", "root_cause_analysis"], "resources": ["cloud"], "authority_max": 3, "enabled": True, "verifier": True},
            {"id": "rca", "capabilities": ["diagnostics", "root_cause_analysis"], "resources": ["cloud"], "authority_max": 3, "enabled": True, "verifier": True},
        ],
        "tasks": [
            {"id": "A", "status": "PENDING", "priority": 10, "dependencies": [], "required_capabilities": ["implementation"], "preferred_resources": ["cloud"], "authority": 1},
            {"id": "B", "status": "PENDING", "priority": 9, "dependencies": ["A"], "required_capabilities": ["implementation"], "preferred_resources": ["cloud"], "authority": 1},
        ],
    }


def test_dependency_dag_releases_only_eligible_work():
    cfg = base_config()
    now = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)
    am.cycle(cfg, now)
    assert cfg["tasks"][0]["status"] == "LEASED"
    assert cfg["tasks"][1]["status"] == "PENDING"


def test_l4_never_auto_executes():
    cfg = base_config()
    cfg["tasks"] = [{"id": "L4", "status": "PENDING", "priority": 100, "dependencies": [], "required_capabilities": [], "preferred_resources": [], "authority": 4}]
    am.cycle(cfg, datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc))
    assert cfg["tasks"][0]["status"] == "OWNER_REQUIRED"
    assert cfg["tasks"][0].get("assigned_worker") is None


def test_restored_l4_running_or_done_state_is_forced_back_to_owner_required():
    cfg = base_config()
    cfg["tasks"] = [{
        "id": "L4", "status": "DONE", "priority": 100, "dependencies": [],
        "required_capabilities": [], "preferred_resources": [], "authority": 4,
        "assigned_worker": "dev", "producer": "dev", "lease_id": "stale",
        "heartbeat_at": "2026-08-16T11:59:00+00:00",
        "lease_expires_at": "2026-08-16T12:04:00+00:00",
    }]
    am.cycle(cfg, datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc))
    task = cfg["tasks"][0]
    assert task["status"] == "OWNER_REQUIRED"
    assert task["assigned_worker"] is None
    assert task["lease_id"] is None
    assert task["heartbeat_at"] is None
    assert task["lease_expires_at"] is None


def test_l4_result_submission_is_rejected_even_with_matching_worker_identity():
    cfg = base_config()
    cfg["tasks"] = [{
        "id": "L4", "status": "VERIFYING", "priority": 100, "dependencies": [],
        "required_capabilities": [], "preferred_resources": [], "authority": 4,
        "assigned_worker": "qa", "producer": "dev",
    }]
    with pytest.raises(ValueError, match="L4 task results require owner-controlled handling"):
        am.record_result(cfg, "L4", "qa", "success", {"forged": True})


def test_stale_lease_enters_five_minute_triage():
    cfg = base_config()
    task = cfg["tasks"][0]
    task.update({"status": "RUNNING", "assigned_worker": "dev", "producer": "dev", "heartbeat_at": "2026-08-16T11:50:00+00:00", "lease_expires_at": "2026-08-16T11:55:00+00:00"})
    cfg["tasks"][1]["status"] = "PENDING"
    now = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)
    am.expire_stale_leases(cfg, now)
    assert task["status"] == "TRIAGE"
    assert task["assigned_worker"] is None


def test_non_transient_failure_gets_independent_root_cause_analysis_not_blind_retry():
    cfg = base_config()
    task = cfg["tasks"][0]
    task.update({"status": "TRIAGE", "producer": "dev", "failure_class": "deterministic_or_unknown"})
    am.route_triage(cfg, datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc))
    assert task["status"] == "RUNNING"
    assert task["assigned_worker"] != "dev"
    assert task["triage_mode"] == "root_cause_first"
    assert "single_best_remediation" in task["required_output"]


def test_transient_failure_has_at_most_one_direct_retry():
    cfg = base_config()
    task = cfg["tasks"][0]
    task.update({"status": "TRIAGE", "failure_class": "timed_out", "transient_retries": 0})
    am.route_triage(cfg, datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc))
    assert task["status"] == "READY"
    assert task["transient_retries"] == 1
    task["status"] = "TRIAGE"
    am.route_triage(cfg, datetime(2026, 8, 16, 12, 1, tzinfo=timezone.utc))
    assert task["status"] == "RUNNING"
    assert task["triage_mode"] == "root_cause_first"


def test_numerical_research_failure_cannot_dispatch_generic_rca():
    cfg = base_config()
    task = cfg["tasks"][0]
    task.update(
        id="P7-RESEARCH-COMPOSITE-010", status="TRIAGE", phase=7,
        producer="research-agent", assigned_worker="research-agent",
        failure_class="verified_research_execution_failed",
        failure_evidence={"reason": "exact observed preparation failure"},
        lease_id="failed-numeric-lease", dispatch_id="failed-numeric-dispatch",
    )
    original_failure = deepcopy(task["failure_evidence"])
    am.route_triage(cfg, datetime(2026, 10, 4, 4, 0, tzinfo=timezone.utc))
    assert task["status"] == "BLOCKED"
    assert task["assigned_worker"] is None
    assert task["lease_id"] is None
    assert task["dispatch_id"] is None
    assert task["failure_evidence"] == original_failure
    assert task["blocked_reason"] == am.RESEARCH_RCA_BLOCK_REASON


def test_producer_cannot_be_final_verifier():
    cfg = base_config()
    task = cfg["tasks"][0]
    task.update({"status": "RUNNING", "assigned_worker": "dev", "producer": "dev"})
    am.record_result(cfg, "A", "dev", "success", {"tests": "pass"})
    assert task["status"] == "VERIFYING"
    assert task["verifier"] != "dev"


def test_verified_success_is_only_terminal_success():
    cfg = base_config()
    task = cfg["tasks"][0]
    task.update({"status": "RUNNING", "assigned_worker": "dev", "producer": "dev"})
    am.record_result(cfg, "A", "dev", "success", {"tests": "pass"})
    verifier = task["assigned_worker"]
    am.record_result(cfg, "A", verifier, "success", {"independent": True})
    assert task["status"] == "DONE"
    assert task["verification_evidence"]["independent"] is True


def test_unknown_dependency_fails_closed():
    cfg = base_config()
    cfg["tasks"][0]["dependencies"] = ["MISSING"]
    with pytest.raises(ValueError):
        am.validate_config(cfg)


def test_worker_authority_must_cover_task():
    cfg = base_config()
    cfg["workers"][0]["authority_max"] = 0
    workers = am.workers_from(cfg)
    candidates = am.eligible_workers(cfg["tasks"][0], workers)
    assert all(w.id != "dev" for w in candidates)


def test_worker_capacity_allows_safe_parallel_leases():
    cfg = base_config()
    cfg["workers"][0]["max_concurrent_tasks"] = 2
    cfg["workers"][1]["capabilities"] = ["root_cause_analysis", "diagnostics"]
    cfg["tasks"] = [
        {"id": "A", "status": "PENDING", "priority": 10, "dependencies": [], "required_capabilities": ["implementation"], "preferred_resources": ["cloud"], "authority": 1},
        {"id": "B", "status": "PENDING", "priority": 9, "dependencies": [], "required_capabilities": ["implementation"], "preferred_resources": ["cloud"], "authority": 1},
    ]
    am.cycle(cfg, datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc))
    assert [task["status"] for task in cfg["tasks"]] == ["LEASED", "LEASED"]
    assert [task["assigned_worker"] for task in cfg["tasks"]] == ["dev", "dev"]


def test_load_aware_router_prefers_worker_with_more_free_capacity():
    cfg = base_config()
    cfg["workers"] = [
        {"id": "busy", "capabilities": ["implementation"], "resources": ["cloud"], "authority_max": 3, "max_concurrent_tasks": 2},
        {"id": "free", "capabilities": ["implementation"], "resources": ["cloud"], "authority_max": 3, "max_concurrent_tasks": 2},
    ]
    cfg["tasks"] = [
        {"id": "ACTIVE", "status": "RUNNING", "assigned_worker": "busy", "producer": "busy", "priority": 20, "dependencies": [], "required_capabilities": ["implementation"], "preferred_resources": ["cloud"], "authority": 1},
        {"id": "NEXT", "status": "PENDING", "priority": 10, "dependencies": [], "required_capabilities": ["implementation"], "preferred_resources": ["cloud"], "authority": 1},
    ]
    am.cycle(cfg, datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc))
    assert cfg["tasks"][1]["assigned_worker"] == "free"


def test_summary_exposes_idle_capacity_and_unassigned_ready_work():
    cfg = base_config()
    cfg["workers"][0]["max_concurrent_tasks"] = 2
    cfg["tasks"][0]["status"] = "READY"
    summary = am.summarize(cfg)
    assert summary["worker_capacity"]["dev"] == {"active": 0, "capacity": 2, "available": 2}
    assert summary["available_worker_slots"] >= 2
    assert summary["unassigned_ready"] == ["A"]


def test_manager_accepts_tasks_from_multiple_project_phases():
    cfg = base_config()
    cfg["tasks"] = [
        {"id": "P3", "phase": 3, "status": "PENDING", "priority": 10, "dependencies": [], "required_capabilities": ["implementation"], "preferred_resources": ["cloud"], "authority": 1},
        {"id": "P4", "phase": 4, "status": "PENDING", "priority": 9, "dependencies": [], "required_capabilities": ["implementation"], "preferred_resources": ["cloud"], "authority": 1},
    ]
    cfg["workers"][0]["max_concurrent_tasks"] = 2
    summary = am.cycle(cfg, datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc))
    assert {task["phase"] for task in cfg["tasks"] if task["status"] == "LEASED"} == {3, 4}
    assert summary["task_phases"] == [3, 4]


def test_invalid_worker_capacity_fails_closed():
    cfg = base_config()
    cfg["workers"][0]["max_concurrent_tasks"] = 0
    with pytest.raises(ValueError, match="invalid worker capacity"):
        am.validate_config(cfg)


def test_verification_does_not_overbook_worker_capacity():
    cfg = base_config()
    cfg["workers"][2]["enabled"] = False
    cfg["tasks"] = [
        {"id": "ACTIVE", "status": "VERIFYING", "assigned_worker": "qa", "producer": "dev", "priority": 20, "dependencies": [], "required_capabilities": ["implementation"], "preferred_resources": ["cloud"], "authority": 1},
        {"id": "NEXT", "status": "RUNNING", "assigned_worker": "dev", "producer": "dev", "priority": 10, "dependencies": [], "required_capabilities": ["implementation"], "preferred_resources": ["cloud"], "authority": 1},
    ]
    am.record_result(cfg, "NEXT", "dev", "success", {"tests": "pass"})
    assert cfg["tasks"][1]["status"] == "BLOCKED"
    assert cfg["tasks"][1]["blocked_reason"] == "independent verifier unavailable"


def test_triage_does_not_overbook_or_exceed_worker_authority():
    cfg = base_config()
    cfg["workers"][1]["authority_max"] = 1
    cfg["workers"][2]["authority_max"] = 2
    cfg["tasks"] = [
        {"id": "ACTIVE", "status": "RUNNING", "assigned_worker": "rca", "producer": "dev", "priority": 20, "dependencies": [], "required_capabilities": [], "preferred_resources": ["cloud"], "authority": 1},
        {"id": "TRIAGE", "status": "TRIAGE", "producer": "dev", "failure_class": "deterministic_or_unknown", "priority": 10, "dependencies": [], "required_capabilities": [], "preferred_resources": ["cloud"], "authority": 2},
    ]
    am.route_triage(cfg, datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc))
    assert cfg["tasks"][1]["status"] == "BLOCKED"
    assert cfg["tasks"][1]["blocked_reason"] == "independent root-cause analyst unavailable"


def test_materialized_qa_task_leases_only_designated_qa_verifier(monkeypatch):
    monkeypatch.setattr(am, "emit", lambda *args, **kwargs: None)
    config = {
        "policy": {"max_parallel_tasks": 2},
        "workers": [
            {"id":"cloud-worker","capabilities":["data_validation"],"resources":["github-cloud"],"authority_max":3,"enabled":True,"verifier":False,"max_concurrent_tasks":2},
            {"id":"qa-verifier-agent","capabilities":["data_validation"],"resources":["github-cloud"],"authority_max":3,"enabled":True,"verifier":True,"max_concurrent_tasks":2},
        ],
        "tasks": [{
            "id":"STRATEGY-QA-"+"a"*64,"status":"READY","priority":92,"authority":2,
            "dependencies":[],"required_capabilities":["data_validation"],"required_resources":["github-cloud"],
            "preferred_resources":["github-cloud"],"qa_verifier_only":True,
            "qa_dispatch_enabled":True,"required_verifier":"qa-verifier-agent",
            "qa_handoff_task":{
                "task_kind":"strategy_review_independent_qa","system_map_node":"QA-41",
                "required_verifier":"qa-verifier-agent","producer_role":"strategy-runtime-requalification",
                "task_digest":"1"*64,"source_sha":"2"*40,"proposal_digest":"3"*64,
                "proposal_result_digest":"4"*64,"requalification_digest":"5"*64,
                "requalification_verification_digest":"6"*64,"strategy_config_digest":"7"*64,
            },
        }],
    }
    am.assign_ready_tasks(config, datetime(2026,10,6,tzinfo=timezone.utc))
    task=config["tasks"][0]
    assert task["status"]=="VERIFYING"
    assert task["assigned_worker"]=="qa-verifier-agent"
    assert task["verifier"]=="qa-verifier-agent"
    assert "producer" not in task


def test_materialized_qa_success_is_single_verifier_stage_and_exact_receipt(monkeypatch):
    from nexus_strategy_independent_qa import digest

    monkeypatch.setattr(am, "emit", lambda *args, **kwargs: None)
    qa_core = {
        "schema_version":"nexus.strategy-review-qa-task.v1",
        "id":"STRATEGY-QA-"+"a"*64,
        "task_kind":"strategy_review_independent_qa","system_map_node":"QA-41",
        "status":"READY_FOR_QA_DISPATCH","source_sha":"2"*40,
        "proposal_digest":"a"*64,"proposal_result_digest":"4"*64,
        "requalification_digest":"5"*64,"requalification_verification_digest":"6"*64,
        "family":"momentum","timeframe":"hour4","variant_id":"v1",
        "strategy_config":{"lookback":16},"strategy_config_digest":"",
        "runtime_evidence":[
            {
                "symbol":"BTCUSDT","dataset_binding_sha256":"9"*64,
                "pipeline_digest":"b"*64,"qualification_digest":"c"*64,
                "last_open_time_ms":1800000000000,
            },
            {
                "symbol":"ETHUSDT","dataset_binding_sha256":"a"*64,
                "pipeline_digest":"d"*64,"qualification_digest":"e"*64,
                "last_open_time_ms":1800000000000,
            },
        ],
        "producer_role":"strategy-runtime-requalification",
        "required_verifier":"qa-verifier-agent","research_only":True,"paper_only":True,
        "candidate_creation_authority":False,"qualification_authority":False,
        "promotion_authority":False,"paper_execution_authority":False,
        "automatic_strategy_promotion":False,"live_trading_authority":False,
    }
    qa_core["strategy_config_digest"] = digest(qa_core["strategy_config"])
    qa_task = {**qa_core, "task_digest": digest(qa_core)}
    config = {
        "policy":{"max_parallel_tasks":2},
        "workers":[
            {"id":"qa-verifier-agent","capabilities":["data_validation"],"resources":["github-cloud"],
             "authority_max":3,"enabled":True,"verifier":True,"max_concurrent_tasks":2},
        ],
        "tasks":[{
            "id":qa_task["id"],"status":"READY","priority":92,"authority":2,
            "dependencies":[],"required_capabilities":["data_validation"],"required_resources":["github-cloud"],
            "qa_verifier_only":True,"qa_dispatch_enabled":True,"required_verifier":"qa-verifier-agent",
            "qa_handoff_task":qa_task,
        }],
    }
    am.assign_ready_tasks(config, datetime(2026,10,6,tzinfo=timezone.utc))
    task=config["tasks"][0]
    receipt_core={
        "schema_version":"nexus.strategy-independent-qa-receipt.v1",
        "qa_lease_id":task["lease_id"],"task_digest":qa_task["task_digest"],
        "source_sha":qa_task["source_sha"],"proposal_digest":qa_task["proposal_digest"],
        "proposal_result_digest":qa_task["proposal_result_digest"],
        "requalification_digest":qa_task["requalification_digest"],
        "requalification_verification_digest":qa_task["requalification_verification_digest"],
        "strategy_config_digest":qa_task["strategy_config_digest"],
        "runtime_evidence":[
            {
                "symbol":"BTCUSDT","dataset_binding_sha256":"9"*64,
                "pipeline_digest":"b"*64,"qualification_digest":"c"*64,
                "last_open_time_ms":1800000000000,"qualification_status":"paper_candidate",
                "deterministic_replay_verified":True,
            },
            {
                "symbol":"ETHUSDT","dataset_binding_sha256":"a"*64,
                "pipeline_digest":"d"*64,"qualification_digest":"e"*64,
                "last_open_time_ms":1800000000000,"qualification_status":"paper_candidate",
                "deterministic_replay_verified":True,
            },
        ],
        "independent_qa_complete":True,"qualification_authority":False,
        "promotion_authority":False,"paper_execution_authority":False,
        "automatic_strategy_promotion":False,"live_trading_authority":False,
    }
    receipt={**receipt_core,"qa_receipt_digest":digest(receipt_core)}
    am.record_result(config, task["id"], "qa-verifier-agent", "success", receipt)
    assert task["status"]=="DONE"
    assert task["verification_evidence"]==receipt

def test_materialized_qa_failure_blocks_instead_of_generic_second_stage(monkeypatch):
    monkeypatch.setattr(am, "emit", lambda *args, **kwargs: None)
    config = {
        "policy":{"max_parallel_tasks":2},
        "workers":[
            {"id":"qa-verifier-agent","capabilities":["data_validation"],"resources":["github-cloud"],
             "authority_max":3,"enabled":True,"verifier":True,"max_concurrent_tasks":2},
        ],
        "tasks":[{
            "id":"STRATEGY-QA-"+"a"*64,"status":"READY","priority":92,"authority":2,
            "dependencies":[],"required_capabilities":["data_validation"],"required_resources":["github-cloud"],
            "qa_verifier_only":True,"qa_dispatch_enabled":True,"required_verifier":"qa-verifier-agent",
            "qa_handoff_task":{
                "task_kind":"strategy_review_independent_qa","system_map_node":"QA-41",
                "required_verifier":"qa-verifier-agent",
            },
        }],
    }
    am.assign_ready_tasks(config, datetime(2026,10,6,tzinfo=timezone.utc))
    task=config["tasks"][0]
    am.record_result(config, task["id"], "qa-verifier-agent", "failure", {"failure_class":"replay_mismatch"})
    assert task["status"]=="BLOCKED"
    assert task["assigned_worker"] is None
    assert task["blocked_reason"].startswith("independent Strategy QA failed")
