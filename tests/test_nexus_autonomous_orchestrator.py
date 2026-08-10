from __future__ import annotations

import json

import nexus_autonomous_orchestrator as orchestrator


def test_external_provider_task_is_not_allowlisted() -> None:
    ok, reason = orchestrator.validate_task(
        {"task": "deepseek-smoke", "reason": "scheduled planner check"}
    )
    assert ok is False
    assert reason == "task_not_allowlisted"


def test_protected_authority_reason_is_blocked() -> None:
    for reason_text in (
        "deploy to production",
        "use credential",
        "delete records",
        "change billing",
        "live trading",
    ):
        ok, reason = orchestrator.validate_task(
            {"task": "health", "reason": reason_text}
        )
        assert ok is False
        assert reason == "protected_boundary"


def test_safe_repository_tasks_remain_available() -> None:
    for task in ("health", "tests", "readiness", "zotero-status"):
        ok, reason = orchestrator.validate_task(
            {"task": task, "reason": "repository-local deterministic maintenance"}
        )
        assert ok is True
        assert reason == "ok"


def test_choose_next_blocks_unsafe_then_selects_safe() -> None:
    queue = [
        {"task": "deepseek-smoke", "reason": "scheduled", "status": "pending"},
        {"task": "tests", "reason": "deterministic suite", "status": "pending"},
    ]
    chosen = orchestrator.choose_next(queue)
    assert chosen is queue[1]
    assert queue[0]["status"] == "blocked"
    assert queue[0]["block_reason"] == "task_not_allowlisted"


def test_scheduled_orchestrator_has_no_external_provider_dependency() -> None:
    assert not hasattr(orchestrator, "chat")
    assert not hasattr(orchestrator, "ask_deepseek_for_next")


def test_main_uses_repository_queue_only(tmp_path, monkeypatch, capsys) -> None:
    queue = tmp_path / "queue.json"
    state = tmp_path / "state.json"
    queue.write_text(
        json.dumps([{"task": "tests", "reason": "deterministic suite", "status": "pending"}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(orchestrator, "QUEUE", queue)
    monkeypatch.setattr(orchestrator, "STATE", state)

    orchestrator.main()

    saved = json.loads(state.read_text(encoding="utf-8"))
    assert saved["next_task"] == "tests"
    assert saved["next_source"] == "queue"
    assert "NEXUS_NEXT_TASK=tests" in capsys.readouterr().out
