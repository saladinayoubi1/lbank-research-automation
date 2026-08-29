from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import paper_schedule_watchdog as watchdog


NOW = datetime(2026, 8, 29, 8, 45, tzinfo=timezone.utc)


def run(*, minutes_ago: int, status: str = "completed", conclusion: str | None = "success"):
    return {
        "id": 123,
        "status": status,
        "conclusion": conclusion,
        "created_at": (NOW - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z"),
        "head_sha": "abc123",
        "event": "schedule",
        "html_url": "https://example.invalid/run/123",
    }


def test_recent_success_is_healthy_and_does_not_require_dispatch():
    result = watchdog.evaluate_runs([run(minutes_ago=20)], now=NOW, stale_minutes=45)
    assert result["decision"] == "HEALTHY_RECENT_SUCCESS"
    assert result["age_minutes"] == 20.0


def test_active_run_suppresses_dispatch_even_when_old():
    result = watchdog.evaluate_runs(
        [run(minutes_ago=90, status="in_progress", conclusion=None)],
        now=NOW,
        stale_minutes=45,
    )
    assert result["decision"] == "HEALTHY_ACTIVE_RUN"


def test_stale_success_requires_bounded_dispatch():
    result = watchdog.evaluate_runs([run(minutes_ago=90)], now=NOW, stale_minutes=45)
    assert result["decision"] == "DISPATCH_REQUIRED_STALE_SUCCESS"
    assert result["age_minutes"] == 90.0


def test_unsuccessful_latest_run_fails_closed_instead_of_looping():
    result = watchdog.evaluate_runs(
        [run(minutes_ago=90, conclusion="failure")], now=NOW, stale_minutes=45
    )
    assert result["decision"] == "FAIL_CLOSED_LAST_RUN_UNSUCCESSFUL"


def test_authoritative_recheck_prevents_duplicate_dispatch(monkeypatch):
    histories = iter(
        [
            [run(minutes_ago=90)],
            [run(minutes_ago=1, status="queued", conclusion=None)],
        ]
    )
    monkeypatch.setattr(watchdog, "utcnow", lambda: NOW)
    monkeypatch.setattr(watchdog, "get_workflow_runs", lambda: next(histories))
    dispatches: list[bool] = []
    monkeypatch.setattr(
        watchdog,
        "dispatch_workflow",
        lambda: (dispatches.append(True) or True, "unexpected"),
    )

    evidence = watchdog.watch_once(stale_minutes=45)

    assert evidence["decision"] == "DISPATCH_SUPPRESSED_AFTER_RECHECK"
    assert evidence["dispatch_attempted"] is False
    assert dispatches == []


def test_stale_success_dispatches_only_after_second_stale_read(monkeypatch):
    monkeypatch.setattr(watchdog, "utcnow", lambda: NOW)
    monkeypatch.setattr(
        watchdog, "get_workflow_runs", lambda: [run(minutes_ago=90)]
    )
    monkeypatch.setattr(watchdog, "dispatch_workflow", lambda: (True, "ok"))

    evidence = watchdog.watch_once(stale_minutes=45)

    assert evidence["decision"] == "DISPATCHED"
    assert evidence["dispatch_attempted"] is True
    assert evidence["dispatch_ok"] is True


def test_coordinator_workflow_invokes_watchdog_without_permission_expansion():
    text = Path(".github/workflows/fast-agent-coordinator.yml").read_text(encoding="utf-8")
    permission_block = text.split("permissions:", 1)[1].split("concurrency:", 1)[0]
    assert "contents: read" in permission_block
    assert "actions: write" in permission_block
    assert "paper_schedule_watchdog.py" in text
