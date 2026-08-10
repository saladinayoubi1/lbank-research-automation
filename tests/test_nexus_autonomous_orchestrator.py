from __future__ import annotations

import nexus_autonomous_orchestrator as orchestrator


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
