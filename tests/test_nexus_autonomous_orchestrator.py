from __future__ import annotations

import json

import pytest

import nexus_autonomous_orchestrator as orchestrator
from nexus_execution_contract import load_contract


def complete_task(name: str, reason: str = "repository-local deterministic maintenance") -> dict:
    return {
        "task": name,
        "reason": reason,
        "task_id": f"task-{name}",
        "lane": "Lane P",
        "deliverable_or_gate": "maintenance",
        "acceptance_criterion": "bounded task passes its deterministic verifier",
        "assigned_resource": "agents",
        "dependencies": [],
        "execution_action": f"run {name}",
        "verification_method": "deterministic test",
        "durable_evidence_location": f"build/evidence/{name}.json",
        "status": "QUEUED",
        "pre_execution": {
            key: True for key in load_contract()["requiredBeforeExecution"]
        },
    }


def test_external_provider_task_is_not_allowlisted() -> None:
    ok, reason = orchestrator.validate_task(
        {"task": "deepseek-smoke", "reason": "scheduled planner check"}
    )
    assert ok is False
    assert reason == "task_not_allowlisted"


def test_credential_or_external_ai_reason_is_blocked() -> None:
    for reason_text in (
        "use credential-backed helper",
        "ask external AI to choose",
        "use DeepSeek reviewer",
    ):
        ok, reason = orchestrator.validate_task(
            {"task": "health", "reason": reason_text}
        )
        assert ok is False
        assert reason == "protected_boundary"


def test_safe_repository_tasks_remain_available() -> None:
    for task in ("health", "tests", "readiness", "zotero-status"):
        ok, reason = orchestrator.validate_task(complete_task(task))
        assert ok is True
        assert reason == "ok"


def test_allowlisted_task_without_execution_record_is_blocked() -> None:
    ok, reason = orchestrator.validate_task({"task": "tests", "reason": "deterministic suite"})
    assert ok is False
    assert reason == "execution_record_incomplete"


def test_choose_next_blocks_unsafe_then_selects_safe() -> None:
    queue = [
        {"task": "deepseek-smoke", "reason": "scheduled", "status": "pending"},
        {**complete_task("tests", "deterministic suite"), "status": "QUEUED"},
    ]
    chosen = orchestrator.choose_next(queue)
    assert chosen is queue[1]
    assert queue[0]["status"] == "blocked"
    assert queue[0]["block_reason"] == "task_not_allowlisted"


def test_durable_queue_wins_over_reset_repository_seed(tmp_path, monkeypatch) -> None:
    seed = tmp_path / "checkout" / ".nexus" / "autonomous-queue.json"
    durable = tmp_path / "runner-state" / "autonomous-queue.json"
    seed.parent.mkdir(parents=True)
    durable.parent.mkdir(parents=True)
    seed.write_text(json.dumps([{"task": "health", "status": "pending"}]), encoding="utf-8")
    durable.write_text(json.dumps([{"task": "health", "status": "completed"}]), encoding="utf-8")
    monkeypatch.setattr(orchestrator, "SEED_QUEUE", seed)
    monkeypatch.setattr(orchestrator, "QUEUE", durable)

    # A clean checkout can rewind the tracked seed, but cannot rewind runner-local state.
    seed.write_text(json.dumps([{"task": "health", "status": "pending"}]), encoding="utf-8")
    assert orchestrator.load_queue()[0]["status"] == "completed"


def test_first_run_seeds_external_state_once(tmp_path, monkeypatch) -> None:
    seed = tmp_path / "checkout" / ".nexus" / "autonomous-queue.json"
    durable = tmp_path / "runner-state" / "autonomous-queue.json"
    seed.parent.mkdir(parents=True)
    seed.write_text(json.dumps([{"task": "tests", "status": "pending"}]), encoding="utf-8")
    monkeypatch.setattr(orchestrator, "SEED_QUEUE", seed)
    monkeypatch.setattr(orchestrator, "QUEUE", durable)

    queue = orchestrator.load_queue()
    assert queue == [{"task": "tests", "status": "pending"}]
    assert json.loads(durable.read_text(encoding="utf-8")) == queue


def test_corrupt_durable_queue_never_falls_back_to_clean_seed(tmp_path, monkeypatch) -> None:
    seed = tmp_path / "checkout" / ".nexus" / "autonomous-queue.json"
    durable = tmp_path / "runner-state" / "autonomous-queue.json"
    seed.parent.mkdir(parents=True)
    durable.parent.mkdir(parents=True)
    seed.write_text(json.dumps([{"task": "health", "status": "pending"}]), encoding="utf-8")
    durable.write_text("{not-json", encoding="utf-8")
    monkeypatch.setattr(orchestrator, "SEED_QUEUE", seed)
    monkeypatch.setattr(orchestrator, "QUEUE", durable)

    with pytest.raises(json.JSONDecodeError):
        orchestrator.load_queue()
