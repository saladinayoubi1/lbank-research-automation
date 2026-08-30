from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import paper_schedule_watchdog as watchdog


NOW = datetime(2026, 8, 29, 8, 45, tzinfo=timezone.utc)


def run(
    *,
    minutes_ago: int,
    status: str = "completed",
    conclusion: str | None = "success",
    head_sha: str = "abc123",
    run_id: int = 123,
):
    return {
        "id": run_id,
        "status": status,
        "conclusion": conclusion,
        "created_at": (NOW - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z"),
        "head_sha": head_sha,
        "event": "schedule",
        "html_url": f"https://example.invalid/run/{run_id}",
    }


def test_recent_success_is_healthy_and_does_not_require_dispatch():
    result = watchdog.evaluate_runs([run(minutes_ago=20)], now=NOW, stale_minutes=45)
    assert result["decision"] == "HEALTHY_RECENT_SUCCESS"
    assert result["age_minutes"] == 20.0


def test_in_progress_run_suppresses_dispatch_even_when_old_and_noncurrent():
    result = watchdog.evaluate_runs(
        [run(minutes_ago=90, status="in_progress", conclusion=None, head_sha="old")],
        now=NOW,
        stale_minutes=45,
        current_sha="new",
    )
    assert result["decision"] == "HEALTHY_ACTIVE_RUN"


def test_stale_queued_run_on_current_sha_remains_healthy_active():
    result = watchdog.evaluate_runs(
        [run(minutes_ago=90, status="queued", conclusion=None, head_sha="same")],
        now=NOW,
        stale_minutes=45,
        current_sha="same",
    )
    assert result["decision"] == "HEALTHY_ACTIVE_RUN"


def test_stale_queued_noncurrent_run_requests_bounded_recovery():
    result = watchdog.evaluate_runs(
        [run(minutes_ago=90, status="queued", conclusion=None, head_sha="old")],
        now=NOW,
        stale_minutes=45,
        current_sha="new",
    )
    assert result["decision"] == "RECOVER_STALE_NONCURRENT_ACTIVE"
    assert result["age_minutes"] == 90.0


def test_stale_success_requires_bounded_dispatch():
    result = watchdog.evaluate_runs([run(minutes_ago=90)], now=NOW, stale_minutes=45)
    assert result["decision"] == "DISPATCH_REQUIRED_STALE_SUCCESS"
    assert result["age_minutes"] == 90.0


def test_unsuccessful_latest_run_fails_closed_instead_of_looping():
    result = watchdog.evaluate_runs(
        [run(minutes_ago=90, conclusion="failure")], now=NOW, stale_minutes=45
    )
    assert result["decision"] == "FAIL_CLOSED_LAST_RUN_UNSUCCESSFUL"


def test_newest_unstarted_run_exposes_only_stale_unstarted_predecessors():
    runs = [
        run(minutes_ago=2, status="pending", conclusion=None, head_sha="new", run_id=200),
        run(minutes_ago=90, status="queued", conclusion=None, head_sha="old", run_id=100),
        run(minutes_ago=90, status="in_progress", conclusion=None, head_sha="old2", run_id=99),
        run(minutes_ago=10, status="queued", conclusion=None, head_sha="old3", run_id=98),
        run(minutes_ago=90, status="queued", conclusion=None, head_sha="new", run_id=97),
    ]

    candidates = watchdog.stale_predecessor_candidates(
        runs,
        now=NOW,
        stale_minutes=30,
        current_sha="new",
    )

    assert [candidate["id"] for candidate in candidates] == [100, 97]


def test_predecessor_cleanup_survives_main_advancing_after_newest_dispatch():
    candidates = watchdog.stale_predecessor_candidates(
        [
            run(minutes_ago=2, status="pending", conclusion=None, head_sha="previous-main", run_id=200),
            run(minutes_ago=90, status="queued", conclusion=None, head_sha="older", run_id=100),
        ],
        now=NOW,
        stale_minutes=30,
        current_sha="new-current-main",
    )
    assert [candidate["id"] for candidate in candidates] == [100]
    assert candidates[0]["newest_run_id"] == 200
    assert candidates[0]["coordinator_current_sha"] == "new-current-main"


def test_no_predecessor_cleanup_when_newest_run_has_started():
    candidates = watchdog.stale_predecessor_candidates(
        [
            run(minutes_ago=2, status="in_progress", conclusion=None, head_sha="previous-main", run_id=200),
            run(minutes_ago=90, status="queued", conclusion=None, head_sha="older", run_id=100),
        ],
        now=NOW,
        stale_minutes=30,
        current_sha="new-current-main",
    )
    assert candidates == []


def test_pending_run_without_jobs_is_safe_to_cancel(monkeypatch):
    monkeypatch.setattr(watchdog, "api_json", lambda path: {"jobs": []})
    assert watchdog.paper_run_safe_to_cancel(123) == (
        True,
        "workflow_pending_before_job_creation",
    )


def test_started_paper_job_is_never_safe_to_cancel(monkeypatch):
    monkeypatch.setattr(
        watchdog,
        "api_json",
        lambda path: {
            "jobs": [
                {
                    "name": "paper-loop",
                    "status": "in_progress",
                    "steps": [{"name": "Checkout", "status": "in_progress"}],
                }
            ]
        },
    )
    safe, detail = watchdog.paper_run_safe_to_cancel(123)
    assert safe is False
    assert detail == "paper_loop_status=in_progress"


def test_current_exact_main_pending_releases_safe_stale_predecessor_without_dispatch(monkeypatch):
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.setenv("GITHUB_SHA", "new")
    current = run(
        minutes_ago=2,
        status="pending",
        conclusion=None,
        head_sha="new",
        run_id=200,
    )
    old = run(
        minutes_ago=90,
        status="queued",
        conclusion=None,
        head_sha="old",
        run_id=100,
    )
    histories = iter([[current, old], [current]])
    monkeypatch.setattr(watchdog, "utcnow", lambda: NOW)
    monkeypatch.setattr(watchdog, "get_workflow_runs", lambda: next(histories))
    monkeypatch.setattr(
        watchdog,
        "paper_run_safe_to_cancel",
        lambda run_id: (True, "paper_loop_unstarted_status=queued"),
    )
    cancellations: list[int] = []
    monkeypatch.setattr(
        watchdog,
        "cancel_workflow_run",
        lambda run_id: (cancellations.append(run_id) or True, "cancelled"),
    )
    dispatches: list[bool] = []
    monkeypatch.setattr(
        watchdog,
        "dispatch_workflow",
        lambda: (dispatches.append(True) or True, "unexpected"),
    )

    evidence = watchdog.watch_once(stale_minutes=30)

    assert evidence["decision"] == "STALE_PREDECESSORS_CANCELLED_NEWEST_ACTIVE"
    assert cancellations == [100]
    assert evidence["cancel_attempted"] is True
    assert evidence["cancel_ok"] is True
    assert evidence["dispatch_attempted"] is False
    assert dispatches == []


def test_previous_main_pending_releases_safe_stale_predecessor_without_dispatch(monkeypatch):
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.setenv("GITHUB_SHA", "new-current-main")
    newest = run(
        minutes_ago=2,
        status="pending",
        conclusion=None,
        head_sha="previous-main",
        run_id=200,
    )
    old = run(
        minutes_ago=90,
        status="queued",
        conclusion=None,
        head_sha="old",
        run_id=100,
    )
    histories = iter([[newest, old], [newest]])
    monkeypatch.setattr(watchdog, "utcnow", lambda: NOW)
    monkeypatch.setattr(watchdog, "get_workflow_runs", lambda: next(histories))
    monkeypatch.setattr(
        watchdog,
        "paper_run_safe_to_cancel",
        lambda run_id: (True, "paper_loop_unstarted_status=queued"),
    )
    cancellations: list[int] = []
    monkeypatch.setattr(
        watchdog,
        "cancel_workflow_run",
        lambda run_id: (cancellations.append(run_id) or True, "cancelled"),
    )
    dispatches: list[bool] = []
    monkeypatch.setattr(
        watchdog,
        "dispatch_workflow",
        lambda: (dispatches.append(True) or True, "unexpected"),
    )

    evidence = watchdog.watch_once(stale_minutes=30)

    assert evidence["decision"] == "STALE_PREDECESSORS_CANCELLED_NEWEST_ACTIVE"
    assert cancellations == [100]
    assert evidence["dispatch_attempted"] is False
    assert dispatches == []


def test_unsafe_stale_predecessor_fails_closed_before_any_cancellation(monkeypatch):
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.setenv("GITHUB_SHA", "new")
    current = run(
        minutes_ago=2,
        status="pending",
        conclusion=None,
        head_sha="new",
        run_id=200,
    )
    old = run(
        minutes_ago=90,
        status="queued",
        conclusion=None,
        head_sha="old",
        run_id=100,
    )
    monkeypatch.setattr(watchdog, "utcnow", lambda: NOW)
    monkeypatch.setattr(watchdog, "get_workflow_runs", lambda: [current, old])
    monkeypatch.setattr(
        watchdog,
        "paper_run_safe_to_cancel",
        lambda run_id: (False, "paper_loop_has_steps"),
    )
    cancellations: list[int] = []
    monkeypatch.setattr(
        watchdog,
        "cancel_workflow_run",
        lambda run_id: (cancellations.append(run_id) or True, "unexpected"),
    )

    evidence = watchdog.watch_once(stale_minutes=30)

    assert evidence["decision"] == "FAIL_CLOSED_STALE_PREDECESSOR_NOT_SAFE_TO_CANCEL"
    assert evidence["cancel_attempted"] is False
    assert cancellations == []


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

    assert evidence["decision"] == "WRITE_SUPPRESSED_AFTER_RECHECK"
    assert evidence["dispatch_attempted"] is False
    assert dispatches == []


def test_stale_success_dispatches_only_after_second_stale_read(monkeypatch):
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.setattr(watchdog, "utcnow", lambda: NOW)
    monkeypatch.setattr(
        watchdog, "get_workflow_runs", lambda: [run(minutes_ago=90)]
    )
    monkeypatch.setattr(watchdog, "dispatch_workflow", lambda: (True, "ok"))

    evidence = watchdog.watch_once(stale_minutes=45)

    assert evidence["decision"] == "DISPATCHED"
    assert evidence["dispatch_attempted"] is True
    assert evidence["dispatch_ok"] is True
    assert evidence["cancel_attempted"] is False


def test_stale_noncurrent_pending_run_is_cancelled_then_exact_main_dispatched(monkeypatch):
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.setenv("GITHUB_SHA", "new")
    monkeypatch.setattr(watchdog, "utcnow", lambda: NOW)
    monkeypatch.setattr(
        watchdog,
        "get_workflow_runs",
        lambda: [run(minutes_ago=90, status="pending", conclusion=None, head_sha="old")],
    )
    monkeypatch.setattr(
        watchdog,
        "paper_run_safe_to_cancel",
        lambda run_id: (True, "workflow_pending_before_job_creation"),
    )
    cancellations: list[int] = []
    monkeypatch.setattr(
        watchdog,
        "cancel_workflow_run",
        lambda run_id: (cancellations.append(run_id) or True, "cancelled"),
    )
    monkeypatch.setattr(watchdog, "dispatch_workflow", lambda: (True, "dispatched"))

    evidence = watchdog.watch_once(stale_minutes=45)

    assert evidence["decision"] == "STALE_ACTIVE_CANCELLED_AND_DISPATCHED"
    assert cancellations == [123]
    assert evidence["cancel_attempted"] is True
    assert evidence["cancel_ok"] is True
    assert evidence["dispatch_attempted"] is True
    assert evidence["dispatch_ok"] is True


def test_stale_noncurrent_pending_run_fails_closed_if_cancellation_not_safe(monkeypatch):
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.setenv("GITHUB_SHA", "new")
    monkeypatch.setattr(watchdog, "utcnow", lambda: NOW)
    monkeypatch.setattr(
        watchdog,
        "get_workflow_runs",
        lambda: [run(minutes_ago=90, status="queued", conclusion=None, head_sha="old")],
    )
    monkeypatch.setattr(
        watchdog,
        "paper_run_safe_to_cancel",
        lambda run_id: (False, "paper_loop_status=in_progress"),
    )
    dispatches: list[bool] = []
    monkeypatch.setattr(
        watchdog,
        "dispatch_workflow",
        lambda: (dispatches.append(True) or True, "unexpected"),
    )

    evidence = watchdog.watch_once(stale_minutes=45)

    assert evidence["decision"] == "FAIL_CLOSED_STALE_ACTIVE_NOT_SAFE_TO_CANCEL"
    assert evidence["cancel_attempted"] is False
    assert evidence["dispatch_attempted"] is False
    assert dispatches == []


def test_non_default_ref_fails_closed_before_dispatch(monkeypatch):
    monkeypatch.setenv("GITHUB_REF_NAME", "pull/1074/merge")
    monkeypatch.setattr(watchdog, "utcnow", lambda: NOW)
    monkeypatch.setattr(
        watchdog, "get_workflow_runs", lambda: [run(minutes_ago=90)]
    )
    dispatches: list[bool] = []
    monkeypatch.setattr(
        watchdog,
        "dispatch_workflow",
        lambda: (dispatches.append(True) or True, "unexpected"),
    )

    evidence = watchdog.watch_once(stale_minutes=45)

    assert evidence["decision"] == "FAIL_CLOSED_NON_DEFAULT_REF"
    assert evidence["dispatch_attempted"] is False
    assert dispatches == []


def test_coordinator_workflow_invokes_watchdog_without_permission_expansion():
    text = Path(".github/workflows/fast-agent-coordinator.yml").read_text(encoding="utf-8")
    permission_block = text.split("permissions:", 1)[1].split("concurrency:", 1)[0]
    assert "contents: read" in permission_block
    assert "actions: write" in permission_block
    assert "paper_schedule_watchdog.py" in text
