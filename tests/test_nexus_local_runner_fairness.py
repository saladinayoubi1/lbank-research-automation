from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "nexus-local-runner.yml"
WORKER = ROOT / "scripts" / "nexus_local_worker.py"


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _load_worker():
    spec = importlib.util.spec_from_file_location("nexus_local_worker_fairness", WORKER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_local_runner_uses_task_aware_concurrency_lanes_and_latest_owner_proof_wins():
    text = _workflow()
    assert "group: >-" in text
    assert "nexus-local-runner-${{" in text
    assert "'[verify-owner-autostart]'" in text
    assert "&& 'owner-proof'" in text
    assert "'[install-autostart]'" in text
    assert "&& 'install'" in text
    assert "'[autonomous]'" in text
    assert "&& 'autonomous'" in text
    assert "'general'" in text
    cancel_line = next(line.strip() for line in text.splitlines() if line.strip().startswith("cancel-in-progress:"))
    assert cancel_line == "cancel-in-progress: ${{ github.event_name == 'push' && contains(github.event.head_commit.message, '[verify-owner-autostart]') }}"
    assert "[install-autostart]" not in cancel_line
    assert "[sidecar-compat]" not in cancel_line
    assert "[autonomous]" not in cancel_line
    assert "group: nexus-local-runner\n" not in text


def test_autonomous_worker_state_is_durable_and_lease_is_short_and_fair():
    text = _workflow()
    assert "NEXUS_STATE_DIR: ${{ runner.workspace }}\\_nexus_local_worker_state" in text
    assert "NEXUS_WORKER_MAX_SECONDS: '720'" in text
    assert "NEXUS_WORKER_MAX_TASKS_PER_LEASE: '1'" in text
    assert "NEXUS_WORKER_EXIT_ON_IDLE: '1'" in text
    assert "NEXUS_WORKER_IDLE_SLEEP: '15'" in text
    assert "${{ runner.workspace }}\\_nexus_local_worker_state\\autonomous-queue.json" in text
    assert "${{ runner.workspace }}\\_nexus_local_worker_state\\worker-heartbeat.json" in text
    assert ".nexus/autonomous-queue.json\n            build/autonomy/worker-heartbeat.json" not in text


def test_worker_yields_after_one_task_when_quota_is_one(monkeypatch):
    worker = _load_worker()
    calls = []
    heartbeats = []

    monkeypatch.setenv("NEXUS_WORKER_MAX_SECONDS", "720")
    monkeypatch.setenv("NEXUS_WORKER_MAX_TASKS_PER_LEASE", "1")
    monkeypatch.setenv("NEXUS_WORKER_EXIT_ON_IDLE", "1")
    monkeypatch.setattr(worker.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(worker, "run_once", lambda: calls.append("task") or True)
    monkeypatch.setattr(worker, "write_heartbeat", lambda **payload: heartbeats.append(payload))

    worker.main()

    assert calls == ["task"]
    assert heartbeats[-1]["state"] == "cycle_complete"
    assert heartbeats[-1]["exit_reason"] == "task_quota"
    assert heartbeats[-1]["tasks_run"] == 1
    assert heartbeats[-1]["lease_seconds"] == 720
    assert heartbeats[-1]["max_tasks_per_lease"] == 1


def test_worker_releases_runner_immediately_when_idle(monkeypatch):
    worker = _load_worker()
    calls = []
    heartbeats = []

    monkeypatch.setenv("NEXUS_WORKER_MAX_SECONDS", "720")
    monkeypatch.setenv("NEXUS_WORKER_MAX_TASKS_PER_LEASE", "1")
    monkeypatch.setenv("NEXUS_WORKER_EXIT_ON_IDLE", "1")
    monkeypatch.setattr(worker.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(worker.time, "sleep", lambda _: (_ for _ in ()).throw(AssertionError("idle worker must not sleep")))
    monkeypatch.setattr(worker, "run_once", lambda: calls.append("idle") or False)
    monkeypatch.setattr(worker, "write_heartbeat", lambda **payload: heartbeats.append(payload))

    worker.main()

    assert calls == ["idle"]
    assert heartbeats[-1]["state"] == "cycle_complete"
    assert heartbeats[-1]["exit_reason"] == "idle"
    assert heartbeats[-1]["tasks_run"] == 0
