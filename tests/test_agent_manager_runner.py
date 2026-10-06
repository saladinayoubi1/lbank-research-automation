from __future__ import annotations

from agent_manager_runner import (
    DETERMINISTIC_SPECIALIZED_RECOVERY_WORKLOADS,
    SPECIALIZED_REASONING_BLOCK_REASON,
    block_unroutable_specialized_reasoning,
    materialize_strategy_qa_store,
    materialize_composite_runtime_qa_store,
    merge_definition,
    recover_completed_root_cause_analysis,
    recover_bounded_specialized_reasoning,
    recover_research_source_epoch_with_fresh_producer,
)


def test_runtime_state_survives_non_security_definition_refresh():
    template = {
        "schema_version": 1,
        "phase": 4,
        "policy": {},
        "workers": [],
        "tasks": [{
            "id": "A", "title": "new title", "phase": 4, "gate": 2,
            "priority": 10, "dependencies": [], "required_capabilities": [],
            "preferred_resources": [], "authority": 1, "acceptance": ["same"],
            "status": "PENDING"
        }],
    }
    runtime = {
        "schema_version": 1,
        "phase": 4,
        "tasks": [{
            "id": "A", "title": "old title", "phase": 4, "gate": 2,
            "priority": 9, "dependencies": [], "required_capabilities": [],
            "preferred_resources": ["old"], "authority": 1, "acceptance": ["same"],
            "status": "VERIFYING", "producer": "dev", "verifier": "qa", "attempt": 2
        }],
    }
    merged = merge_definition(template, runtime)
    task = merged["tasks"][0]
    assert task["status"] == "VERIFYING"
    assert task["producer"] == "dev"
    assert task["attempt"] == 2
    assert task["title"] == "new title"
    assert task["authority"] == 1


def test_authority_escalation_invalidates_persisted_done_state():
    template = {
        "schema_version": 1, "phase": 4, "policy": {}, "workers": [],
        "tasks": [{
            "id": "L4", "phase": 4, "gate": 18, "dependencies": [],
            "required_capabilities": [], "authority": 4,
            "acceptance": ["owner only"], "status": "PENDING"
        }],
    }
    runtime = {
        "schema_version": 1, "phase": 4,
        "tasks": [{
            "id": "L4", "phase": 4, "gate": 18, "dependencies": [],
            "required_capabilities": [], "authority": 1,
            "acceptance": ["owner only"], "status": "DONE",
            "producer": "dev", "verification_evidence": {"old": True}
        }],
    }
    task = merge_definition(template, runtime)["tasks"][0]
    assert task["status"] == "PENDING"
    assert "producer" not in task
    assert "verification_evidence" not in task


def test_acceptance_change_requires_fresh_execution_and_verification():
    template = {
        "schema_version": 1, "phase": 4, "policy": {}, "workers": [],
        "tasks": [{
            "id": "A", "phase": 4, "gate": 2, "dependencies": [],
            "required_capabilities": [], "authority": 1,
            "acceptance": ["new invariant"], "status": "PENDING"
        }],
    }
    runtime = {
        "schema_version": 1, "phase": 4,
        "tasks": [{
            "id": "A", "phase": 4, "gate": 2, "dependencies": [],
            "required_capabilities": [], "authority": 1,
            "acceptance": ["old invariant"], "status": "DONE",
            "verification_evidence": {"old": True}
        }],
    }
    task = merge_definition(template, runtime)["tasks"][0]
    assert task["status"] == "PENDING"
    assert "verification_evidence" not in task


def test_removed_runtime_task_is_quarantined_not_silently_dropped():
    template = {"schema_version": 1, "phase": 4, "policy": {}, "workers": [], "tasks": []}
    runtime = {"schema_version": 1, "phase": 3, "tasks": [{"id": "OLD", "status": "RUNNING"}]}
    merged = merge_definition(template, runtime)
    assert merged["tasks"][0]["id"] == "OLD"
    assert merged["tasks"][0]["status"] == "QUARANTINED"


def test_specialized_reasoning_failure_is_blocked_instead_of_blind_redispatch():
    config = {
        "tasks": [{
            "id": "P4-DEEPSEEK-001",
            "status": "READY",
            "failure_class": "specialized_reasoning_provider_required",
            "failure_evidence": {"reason": "specialized provider required"},
            "assigned_worker": None,
            "dispatch_id": "stale-dispatch",
            "dispatch_transport": "github-cloud",
            "external_wait_state": "WAITING_EXTERNAL",
        }]
    }

    blocked = block_unroutable_specialized_reasoning(config)
    task = config["tasks"][0]

    assert blocked == 1
    assert task["status"] == "BLOCKED"
    assert task["blocked_reason"] == SPECIALIZED_REASONING_BLOCK_REASON
    assert task["assigned_worker"] is None
    assert task["dispatch_id"] is None
    assert task["dispatch_transport"] is None
    assert task["failure_evidence"] == {"reason": "specialized provider required"}
    assert task["external_wait_state"] is None
    assert task["triage_mode"] == "fail_closed_specialized_reasoning_provider"


def test_completed_rca_does_not_requeue_specialized_failure_to_deterministic_worker():
    config = {
        "tasks": [{
            "id": "P4-DEEPSEEK-001",
            "status": "VERIFYING",
            "failure_class": "specialized_reasoning_provider_required",
            "triage_mode": "root_cause_first",
            "assigned_worker": "qa-verifier-agent",
            "producer": "architect-agent",
            "result_evidence": {"root_cause": "reasoning provider required"},
            "result_received_at": "2026-09-01T04:00:00+00:00",
            "dispatch_id": "rca-dispatch",
            "dispatch_transport": "github-cloud",
        }]
    }

    assert recover_completed_root_cause_analysis(config) == 1
    assert config["tasks"][0]["status"] == "READY"
    assert block_unroutable_specialized_reasoning(config) == 1
    assert config["tasks"][0]["status"] == "BLOCKED"
    assert config["tasks"][0]["dispatch_id"] is None
    assert config["tasks"][0]["dispatch_transport"] is None
    assert config["tasks"][0]["triage_evidence"]["evidence"]["root_cause"] == "reasoning provider required"


def test_p4_event_matching_deterministic_contract_is_not_blocked():
    config = {
        "tasks": [{
            "id": "P4-EVENT-001",
            "status": "READY",
            "failure_class": "specialized_reasoning_provider_required",
            "assigned_worker": None,
        }]
    }

    assert DETERMINISTIC_SPECIALIZED_RECOVERY_WORKLOADS == {"P4-EVENT-001", "P4-UI-001"}
    assert block_unroutable_specialized_reasoning(config) == 0
    assert config["tasks"][0]["status"] == "READY"


def test_exact_prior_p4_event_block_is_released_for_bounded_proof(monkeypatch):
    monkeypatch.setattr("agent_manager_runner.am.iso", lambda: "2026-09-02T06:00:00+00:00")
    config = {
        "tasks": [{
            "id": "P4-EVENT-001",
            "status": "BLOCKED",
            "failure_class": "specialized_reasoning_provider_required",
            "blocked_reason": SPECIALIZED_REASONING_BLOCK_REASON,
            "triage_mode": "fail_closed_specialized_reasoning_provider",
            "failure_evidence": {"reason": "prior route unavailable"},
        }]
    }

    assert recover_bounded_specialized_reasoning(config) == 1
    task = config["tasks"][0]
    assert task["status"] == "READY"
    assert task["ready_at"] == "2026-09-02T06:00:00+00:00"
    assert task["blocked_reason"] is None
    assert task["triage_mode"] is None
    assert task["failure_evidence"] == {"reason": "prior route unavailable"}
    assert recover_bounded_specialized_reasoning(config) == 0


def test_exact_prior_p4_ui_block_is_released_for_bounded_proof(monkeypatch):
    monkeypatch.setattr("agent_manager_runner.am.iso", lambda: "2026-09-02T06:15:00+00:00")
    config = {
        "tasks": [{
            "id": "P4-UI-001",
            "status": "BLOCKED",
            "failure_class": "specialized_reasoning_provider_required",
            "blocked_reason": SPECIALIZED_REASONING_BLOCK_REASON,
        }]
    }

    assert recover_bounded_specialized_reasoning(config) == 1
    assert config["tasks"][0]["status"] == "READY"
    assert config["tasks"][0]["ready_at"] == "2026-09-02T06:15:00+00:00"
    assert config["tasks"][0]["blocked_reason"] is None


def test_p4_deepseek_cannot_use_deterministic_recovery_allowlist():
    config = {
        "tasks": [{
            "id": "P4-DEEPSEEK-001",
            "status": "BLOCKED",
            "failure_class": "specialized_reasoning_provider_required",
            "blocked_reason": SPECIALIZED_REASONING_BLOCK_REASON,
        }]
    }

    assert recover_bounded_specialized_reasoning(config) == 0
    assert config["tasks"][0]["status"] == "BLOCKED"


def test_specialized_reasoning_block_is_idempotent():
    config = {
        "tasks": [{
            "id": "P4-UI-001",
            "status": "BLOCKED",
            "failure_class": "specialized_reasoning_provider_required",
            "blocked_reason": SPECIALIZED_REASONING_BLOCK_REASON,
        }]
    }

    assert block_unroutable_specialized_reasoning(config) == 0
    assert config["tasks"][0]["status"] == "BLOCKED"


def test_specialized_reasoning_guard_does_not_change_transient_triage():
    config = {
        "tasks": [{
            "id": "A",
            "status": "TRIAGE",
            "failure_class": "timed_out",
            "assigned_worker": None,
        }]
    }

    assert block_unroutable_specialized_reasoning(config) == 0
    assert config["tasks"][0]["status"] == "TRIAGE"


def test_strategy_qa_security_binding_change_invalidates_stale_done_state():
    template = {
        "schema_version": 1, "phase": 4, "policy": {}, "workers": [],
        "tasks": [{
            "id": "STRATEGY-QA-" + "a" * 64,
            "phase": 7, "gate": 17, "dependencies": [],
            "required_capabilities": ["data_validation"],
            "required_resources": ["github-cloud"],
            "authority": 2,
            "acceptance": ["exact independent replay"],
            "status": "BLOCKED",
            "qa_verifier_only": True,
            "qa_dispatch_enabled": False,
            "required_verifier": "qa-verifier-agent",
            "qa_handoff_task": {"task_digest": "1" * 64, "strategy_config_digest": "2" * 64},
        }],
    }
    runtime = {
        "schema_version": 1, "phase": 4,
        "tasks": [{
            "id": "STRATEGY-QA-" + "a" * 64,
            "phase": 7, "gate": 17, "dependencies": [],
            "required_capabilities": ["data_validation"],
            "required_resources": ["github-cloud"],
            "authority": 2,
            "acceptance": ["exact independent replay"],
            "status": "DONE",
            "qa_verifier_only": True,
            "qa_dispatch_enabled": True,
            "required_verifier": "qa-verifier-agent",
            "qa_handoff_task": {"task_digest": "9" * 64, "strategy_config_digest": "8" * 64},
            "verifier": "qa-verifier-agent",
            "verification_evidence": {"old": True},
        }],
    }
    task = merge_definition(template, runtime)["tasks"][0]
    assert task["status"] == "BLOCKED"
    assert task["qa_dispatch_enabled"] is False
    assert task["qa_handoff_task"]["task_digest"] == "1" * 64
    assert "verification_evidence" not in task
    assert "verifier" not in task


def _strategy_qa_handoff_for_store():
    import hashlib
    import json
    from nexus_strategy_review_qa_handoff import qa_task_id

    def digest(value):
        return hashlib.sha256(
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()

    task_core = {
        "schema_version": "nexus.strategy-review-qa-task.v1",
        "id": qa_task_id("a" * 64, "b" * 40, "d" * 64),
        "task_kind": "strategy_review_independent_qa",
        "system_map_node": "QA-41",
        "status": "READY_FOR_QA_DISPATCH",
        "source_sha": "b" * 40,
        "proposal_digest": "a" * 64,
        "proposal_result_digest": "c" * 64,
        "requalification_digest": "d" * 64,
        "requalification_verification_digest": "e" * 64,
        "family": "momentum",
        "timeframe": "hour4",
        "variant_id": "v1",
        "strategy_config": {"lookback": 16},
        "strategy_config_digest": "",
        "runtime_evidence": [
            {
                "symbol": "BTCUSDT",
                "dataset_binding_sha256": "f" * 64,
                "pipeline_digest": "1" * 64,
                "qualification_digest": "2" * 64,
                "last_open_time_ms": 1_800_000_000_000,
            },
            {
                "symbol": "ETHUSDT",
                "dataset_binding_sha256": "3" * 64,
                "pipeline_digest": "4" * 64,
                "qualification_digest": "5" * 64,
                "last_open_time_ms": 1_800_000_000_000,
            },
        ],
        "producer_role": "strategy-runtime-requalification",
        "required_verifier": "qa-verifier-agent",
        "research_only": True,
        "paper_only": True,
        "candidate_creation_authority": False,
        "qualification_authority": False,
        "promotion_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    task_core["strategy_config_digest"] = digest(task_core["strategy_config"])
    task = {**task_core, "task_digest": digest(task_core)}
    core = {
        "schema_version": "nexus.strategy-review-qa-handoff.v1",
        "source_sha": "b" * 40,
        "requalification_digest": "d" * 64,
        "requalification_verification_digest": "e" * 64,
        "status": "READY_FOR_QA",
        "task_count": 1,
        "tasks": [task],
        "required_verifier": "qa-verifier-agent",
        "research_only": True,
        "paper_only": True,
        "candidate_creation_authority": False,
        "qualification_authority": False,
        "promotion_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    return {**core, "handoff_digest": digest(core)}


def test_verified_strategy_qa_store_materializes_into_repository_definition(tmp_path):
    import json
    from nexus_strategy_review_qa_handoff import verify_handoff

    handoff = _strategy_qa_handoff_for_store()
    proof = verify_handoff(handoff)
    root = tmp_path / "strategy_qa_handoffs" / handoff["handoff_digest"]
    root.mkdir(parents=True)
    (root / "qa-handoff.json").write_text(json.dumps(handoff), encoding="utf-8")
    (root / "qa-handoff-verification.json").write_text(json.dumps(proof), encoding="utf-8")

    template = {
        "schema_version": 1,
        "phase": 4,
        "policy": {},
        "workers": [],
        "tasks": [],
    }
    materialized = materialize_strategy_qa_store(template, tmp_path / "strategy_qa_handoffs")
    task = materialized["tasks"][0]
    assert task["id"] == handoff["tasks"][0]["id"]
    assert task["status"] == "READY"
    assert task["qa_dispatch_enabled"] is True
    assert task["qa_verifier_only"] is True
    assert task["required_verifier"] == "qa-verifier-agent"


def test_strategy_qa_store_tamper_fails_before_runtime_merge(tmp_path):
    import json
    import pytest
    from nexus_strategy_review_qa_handoff import verify_handoff

    handoff = _strategy_qa_handoff_for_store()
    proof = verify_handoff(handoff)
    root = tmp_path / "strategy_qa_handoffs" / handoff["handoff_digest"]
    root.mkdir(parents=True)
    (root / "qa-handoff.json").write_text(json.dumps(handoff), encoding="utf-8")
    proof["decision"] = "reject"
    (root / "qa-handoff-verification.json").write_text(json.dumps(proof), encoding="utf-8")

    with pytest.raises(ValueError, match="verification failed"):
        materialize_strategy_qa_store(
            {"schema_version": 1, "phase": 4, "policy": {}, "workers": [], "tasks": []},
            tmp_path / "strategy_qa_handoffs",
        )


def _qa_done_predecessor(task_id="P7-RESEARCH-COMPOSITE-014"):
    return {
        "id": task_id,
        "status": "DONE",
        "producer": "research-agent",
        "verifier": "qa-verifier-agent",
        "research_producer_lease_id": "producer-prior",
        "result_evidence": {
            "executor": "nexus-real-composite-backtest",
            "source_sha": "1" * 40,
            "receipt_digest": "2" * 64,
            "ledger_digest": "3" * 64,
            "prior_ledger_digest": "4" * 64,
            "config_fingerprint": "5" * 64,
            "mechanism": "factory_prior_mechanism",
            "independent_qa_complete": False,
            "auto_demo_promotion": False,
            "live_enabled": False,
        },
        "verification_evidence": {
            "executor": "nexus-independent-composite-numeric-qa",
            "producer_lease_id": "producer-prior",
            "producer_receipt_digest": "2" * 64,
            "source_sha": "1" * 40,
            "qa_digest": "6" * 64,
            "independent_qa_complete": True,
            "auto_demo_promotion": False,
            "live_enabled": False,
        },
    }


def _epoch_drift_successor(predecessor):
    from nexus_research_missions import attested_predecessor
    ancestry = attested_predecessor(predecessor)
    return {
        "id": "P7-RESEARCH-COMPOSITE-015",
        "status": "BLOCKED",
        "blocked_reason": "research_qa_source_epoch_drift_requires_fresh_producer",
        "producer": "research-agent",
        "verifier": "qa-verifier-agent",
        "assigned_worker": "qa-verifier-agent",
        "lease_id": "old-qa-lease",
        "research_producer_lease_id": "old-producer-lease",
        "result_evidence": {
            "executor": "nexus-real-composite-backtest",
            "source_sha": "7" * 40,
            "receipt_digest": "8" * 64,
            "ledger_digest": "9" * 64,
            "prior_ledger_digest": ancestry["research_predecessor_ledger_digest"],
            "config_fingerprint": "a" * 64,
            "mechanism": "factory_new_mechanism",
            "independent_qa_complete": False,
            "auto_demo_promotion": False,
            "live_enabled": False,
        },
        "research_qa_epoch_drift": {
            "producer_source_sha": "7" * 40,
            "producer_receipt_digest": "8" * 64,
            "producer_lease_id": "old-producer-lease",
            "undispatched_qa_lease_id": "old-qa-lease",
            "controller_source_sha": "b" * 40,
            "old_producer_not_qualified": True,
        },
        **ancestry,
    }


def test_source_epoch_drift_requeues_only_fresh_producer(monkeypatch):
    predecessor = _qa_done_predecessor()
    successor = _epoch_drift_successor(predecessor)
    config = {"tasks": [predecessor, successor]}
    monkeypatch.setenv("GITHUB_REPOSITORY", "saladinayoubi1/lbank-research-automation")
    monkeypatch.setenv("GITHUB_SHA", "c" * 40)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GH_TOKEN", "test-token")
    monkeypatch.setattr("agent_manager_runner.am.iso", lambda: "2026-10-06T00:00:00+00:00")
    monkeypatch.setattr("agent_manager_runner.am.emit", lambda *args, **kwargs: None)

    assert recover_research_source_epoch_with_fresh_producer(config) == 1
    task = config["tasks"][1]
    assert task["status"] == "READY"
    assert task["producer"] is None
    assert task["verifier"] is None
    assert task["lease_id"] is None
    assert task["research_producer_lease_id"] is None
    assert task["result_evidence"] is None
    assert task["verification_evidence"] is None
    assert task["blocked_reason"] is None
    assert task["attempt"] if "attempt" in task else True
    recovery = task["research_fresh_producer_recovery"]
    assert recovery["superseded_producer_source_sha"] == "7" * 40
    assert recovery["superseded_producer_receipt_digest"] == "8" * 64
    assert recovery["fresh_controller_source_sha"] == "c" * 40
    assert recovery["old_producer_not_qualified"] is True
    assert recovery["independent_qa_complete"] is False
    assert recovery["automatic_demo_promotion"] is False
    assert recovery["live_enabled"] is False
    assert task["research_predecessor_ledger_digest"] == "3" * 64


def test_source_epoch_drift_never_requeues_if_predecessor_attestation_changed(monkeypatch):
    predecessor = _qa_done_predecessor()
    successor = _epoch_drift_successor(predecessor)
    successor["research_predecessor_ledger_digest"] = "f" * 64
    config = {"tasks": [predecessor, successor]}
    monkeypatch.setenv("GITHUB_REPOSITORY", "saladinayoubi1/lbank-research-automation")
    monkeypatch.setenv("GITHUB_SHA", "c" * 40)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GH_TOKEN", "test-token")

    assert recover_research_source_epoch_with_fresh_producer(config) == 0
    assert successor["status"] == "BLOCKED"
    assert successor["result_evidence"]["receipt_digest"] == "8" * 64
    assert "research_fresh_producer_recovery" not in successor


def test_source_epoch_drift_never_reuses_already_qa_complete_old_producer(monkeypatch):
    predecessor = _qa_done_predecessor()
    successor = _epoch_drift_successor(predecessor)
    successor["result_evidence"]["independent_qa_complete"] = True
    config = {"tasks": [predecessor, successor]}
    monkeypatch.setenv("GITHUB_REPOSITORY", "saladinayoubi1/lbank-research-automation")
    monkeypatch.setenv("GITHUB_SHA", "c" * 40)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GH_TOKEN", "test-token")

    assert recover_research_source_epoch_with_fresh_producer(config) == 0
    assert successor["status"] == "BLOCKED"


def test_composite_runtime_qa_store_materializes_dispatch_enabled_verifier_task(tmp_path, monkeypatch):
    import json

    task = {
        "schema_version": "nexus.composite-runtime-qa-task.v1",
        "id": "COMPOSITE-QA-" + "a" * 64,
        "task_kind": "composite_runtime_independent_qa",
        "system_map_node": "QA-41",
        "status": "READY_FOR_QA_DISPATCH",
        "required_verifier": "qa-verifier-agent",
        "producer_role": "physical-composite-val40-requalification",
        "source_sha": "b" * 40,
        "candidate_digest": "c" * 64,
        "requalification_digest": "a" * 64,
        "requalification_verification_digest": "d" * 64,
        "evaluations_digest": "e" * 64,
        "runtime_as_of_ms": 1_800_000_000_000,
        "producer_workflow_run_id": 123,
        "producer": {},
        "producer_verification": {},
        "research_only": True,
        "paper_only": True,
        "qualification_authority": False,
        "registry_mutation_authority": False,
        "runtime_activation_authority": False,
        "promotion_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
        "task_digest": "f" * 64,
    }
    transport = {
        "schema_version": "nexus.composite-runtime-qa-transport.v1",
        "producer_workflow_run_id": 123,
        "artifact_id": 456,
        "task_digest": task["task_digest"],
        "source_sha": task["source_sha"],
        "candidate_digest": task["candidate_digest"],
        "requalification_digest": task["requalification_digest"],
        "required_verifier": "qa-verifier-agent",
        "paper_only": True,
        "qualification_authority": False,
        "registry_mutation_authority": False,
        "runtime_activation_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    root = tmp_path / "composite_runtime_qa_tasks" / task["task_digest"]
    root.mkdir(parents=True)
    (root / "qa-task.json").write_text(json.dumps(task), encoding="utf-8")
    (root / "transport.json").write_text(json.dumps(transport), encoding="utf-8")
    monkeypatch.setattr(
        "nexus_composite_runtime_qa_task_materializer.validate_task",
        lambda value, source: dict(value),
    )

    template = {"schema_version": 1, "phase": 4, "policy": {}, "workers": [], "tasks": []}
    materialized = materialize_composite_runtime_qa_store(
        template, tmp_path / "composite_runtime_qa_tasks"
    )
    row = materialized["tasks"][0]
    assert row["id"] == task["id"]
    assert row["status"] == "READY"
    assert row["qa_verifier_only"] is True
    assert row["qa_dispatch_enabled"] is True
    assert row["required_verifier"] == "qa-verifier-agent"
    assert row.get("blocked_reason") is None


def test_composite_runtime_qa_store_path_tamper_fails_closed(tmp_path):
    import json
    import pytest

    root = tmp_path / "composite_runtime_qa_tasks" / ("f" * 64)
    root.mkdir(parents=True)
    (root / "qa-task.json").write_text(
        json.dumps({"task_digest": "e" * 64}), encoding="utf-8"
    )
    (root / "transport.json").write_text(json.dumps({}), encoding="utf-8")
    with pytest.raises(ValueError, match="path does not match task digest"):
        materialize_composite_runtime_qa_store(
            {"schema_version": 1, "phase": 4, "policy": {}, "workers": [], "tasks": []},
            tmp_path / "composite_runtime_qa_tasks",
        )
