from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import prospective_paper_schedule_watchdog as watchdog


NOW = datetime(2026, 9, 2, 5, 0, tzinfo=timezone.utc)


def run(
    *,
    minutes_ago: int,
    status: str = "completed",
    conclusion: str | None = "success",
    run_id: int = 42,
):
    return {
        "id": run_id,
        "status": status,
        "conclusion": conclusion,
        "created_at": (NOW - timedelta(minutes=minutes_ago))
        .isoformat()
        .replace("+00:00", "Z"),
        "head_sha": "abc123",
        "event": "schedule",
        "html_url": f"https://example.invalid/run/{run_id}",
    }


def test_recent_success_is_healthy():
    result = watchdog.evaluate_runs([run(minutes_ago=149)], now=NOW, stale_minutes=150)
    assert result["decision"] == "HEALTHY_RECENT_SUCCESS"
    assert result["age_minutes"] == 149.0


def test_stale_success_requires_dispatch():
    result = watchdog.evaluate_runs([run(minutes_ago=151)], now=NOW, stale_minutes=150)
    assert result["decision"] == "DISPATCH_REQUIRED_STALE_SUCCESS"
    assert result["age_minutes"] == 151.0


def test_active_run_suppresses_dispatch_even_when_old():
    result = watchdog.evaluate_runs(
        [run(minutes_ago=400, status="in_progress", conclusion=None)],
        now=NOW,
        stale_minutes=150,
    )
    assert result["decision"] == "HEALTHY_ACTIVE_RUN"


def test_unsuccessful_run_fails_closed():
    result = watchdog.evaluate_runs(
        [run(minutes_ago=400, conclusion="failure")],
        now=NOW,
        stale_minutes=150,
    )
    assert result["decision"] == "FAIL_CLOSED_LAST_RUN_UNSUCCESSFUL"


def test_authoritative_recheck_prevents_duplicate_dispatch(monkeypatch):
    histories = iter(
        [
            [run(minutes_ago=400)],
            [run(minutes_ago=1, status="queued", conclusion=None, run_id=43)],
        ]
    )
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.setattr(watchdog, "utcnow", lambda: NOW)
    monkeypatch.setattr(watchdog, "get_workflow_runs", lambda: next(histories))
    dispatches: list[bool] = []
    monkeypatch.setattr(
        watchdog,
        "dispatch_workflow",
        lambda: (dispatches.append(True) or True, "unexpected"),
    )

    evidence = watchdog.watch_once(stale_minutes=150)

    assert evidence["decision"] == "DISPATCH_SUPPRESSED_AFTER_RECHECK"
    assert evidence["dispatch_attempted"] is False
    assert dispatches == []


def test_stale_success_dispatches_once_after_two_stale_reads(monkeypatch):
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.setattr(watchdog, "utcnow", lambda: NOW)
    monkeypatch.setattr(
        watchdog,
        "get_workflow_runs",
        lambda: [run(minutes_ago=400)],
    )
    dispatches: list[bool] = []
    monkeypatch.setattr(
        watchdog,
        "dispatch_workflow",
        lambda: (dispatches.append(True) or True, "ok"),
    )

    evidence = watchdog.watch_once(stale_minutes=150)

    assert evidence["decision"] == "DISPATCHED"
    assert evidence["dispatch_attempted"] is True
    assert evidence["dispatch_ok"] is True
    assert dispatches == [True]
    assert evidence["paper_only"] is True
    assert evidence["live_trading_authority"] is False


def test_non_default_ref_fails_closed_before_dispatch(monkeypatch):
    monkeypatch.setenv("GITHUB_REF_NAME", "pull/1286/merge")
    monkeypatch.setattr(watchdog, "utcnow", lambda: NOW)
    monkeypatch.setattr(
        watchdog,
        "get_workflow_runs",
        lambda: [run(minutes_ago=400)],
    )
    dispatches: list[bool] = []
    monkeypatch.setattr(
        watchdog,
        "dispatch_workflow",
        lambda: (dispatches.append(True) or True, "unexpected"),
    )

    evidence = watchdog.watch_once(stale_minutes=150)

    assert evidence["decision"] == "FAIL_CLOSED_NON_DEFAULT_REF"
    assert evidence["dispatch_attempted"] is False
    assert dispatches == []


def test_coordinator_invokes_watchdog_without_permission_expansion():
    text = Path(".github/workflows/fast-agent-coordinator.yml").read_text(
        encoding="utf-8"
    )
    permission_block = text.split("permissions:", 1)[1].split("concurrency:", 1)[0]
    assert "contents: read" in permission_block
    assert "actions: write" in permission_block
    assert "prospective_paper_schedule_watchdog.py" in text
    assert "--stale-minutes 150" in text
