from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import pytest

from scripts import nexus_local_autonomy_receipt as mod

SHA = "a" * 40
RUN = "36641410417"


def _fixture(root: Path, *, now: float = 1200.0):
    workspace = root / "runner-workspace"
    state = workspace / "nexus-phase3-state"
    state.mkdir(parents=True)
    hb = {"pid": 12, "time": now - 8, "queue_path": "owner-only-path",
          "state": "cycle_complete", "exit_reason": "lease_expired",
          "tasks_run": 2, "lease_seconds": 240, "max_tasks_per_lease": 0}
    queue = [{"id": "owner-private-1", "task": "private-name", "status": "completed"},
             {"id": "owner-private-2", "status": "blocked"},
             {"id": "owner-private-3", "status": "pending"},
             {"id": "owner-private-4", "status": "superseded"}]
    (state / "worker-heartbeat.json").write_text(json.dumps(hb), encoding="utf-8")
    (state / "autonomous-queue.json").write_text(json.dumps(queue), encoding="utf-8")
    return workspace, state


def _check(ws: Path, state: Path, now: float = 1200.0):
    return mod.build_receipt(state, ws, SHA, RUN,
                             runner_name="NEXUS-LOCAL-RUNNER", now=now)


def test_owner_only_receipt_has_exact_runner_and_no_task_ids(tmp_path):
    workspace, state = _fixture(tmp_path)
    before_hb = (state / "worker-heartbeat.json").read_bytes()
    before_queue = (state / "autonomous-queue.json").read_bytes()
    receipt = _check(workspace, state)
    assert receipt["decision"] == "OWNER_LOCAL_CYCLE_VERIFIED_ONLY"
    assert receipt["source_sha"] == SHA and receipt["workflow_run_id"] == RUN
    assert receipt["queue_status_counts"] == {
        "pending": 1, "running": 0, "completed": 1, "failed": 0, "blocked": 1,
        "superseded": 1,
    }
    assert receipt["paper_only"] is True
    assert receipt["live_trading_authority"] is False
    assert receipt["qualification_authority"] is False
    assert "owner-private" not in json.dumps(receipt)
    assert "owner-only-path" not in json.dumps(receipt)
    assert hashlib.sha256(before_queue).hexdigest() == receipt["queue_sha256"]
    assert hashlib.sha256(before_hb).hexdigest() == receipt["heartbeat_sha256"]
    mod._store_local(state, receipt)
    persisted = json.loads((state / "autonomy-receipt.json").read_text())
    assert persisted == receipt
    assert (state / "autonomous-queue.json").read_bytes() == before_queue
    assert (state / "worker-heartbeat.json").read_bytes() == before_hb
    payload = {k: v for k, v in persisted.items() if k != "receipt_sha256"}
    expected = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"),
                   allow_nan=False).encode()
    ).hexdigest()
    assert expected == persisted["receipt_sha256"]


@pytest.mark.parametrize("bad_id,bad_sha,bad_runner", [
    ("0", SHA, "NEXUS-LOCAL-RUNNER"),
    ("abc", SHA, "NEXUS-LOCAL-RUNNER"),
    (RUN, "invalid", "NEXUS-LOCAL-RUNNER"),
    (RUN, SHA, "NEXUS-WINDOWS-DR"),
])
def test_exact_job_and_runner_policy_is_strict(tmp_path, bad_id, bad_sha, bad_runner):
    workspace, state = _fixture(tmp_path)
    with pytest.raises(mod.PrivateReceiptError):
        mod.build_receipt(state, workspace, bad_sha, bad_id,
                          runner_name=bad_runner, now=1200.0)


def test_heartbeat_must_be_local_and_recent(tmp_path):
    workspace, state = _fixture(tmp_path)
    with pytest.raises(mod.PrivateReceiptError, match="incomplete or stale"):
        _check(workspace, state, now=2000)
    p = state / "worker-heartbeat.json"
    hb = json.loads(p.read_text())
    hb["state"] = "running"
    hb["time"] = 1200
    p.write_text(json.dumps(hb))
    with pytest.raises(mod.PrivateReceiptError, match="incomplete or stale"):
        _check(workspace, state)


def test_private_state_path_does_not_accept_sibling_directory(tmp_path):
    workspace, state = _fixture(tmp_path)
    sibling = workspace / "other"
    sibling.mkdir()
    with pytest.raises(mod.PrivateReceiptError, match="root boundary"):
        mod.build_receipt(sibling, workspace, SHA, RUN,
                          runner_name="NEXUS-LOCAL-RUNNER", now=1200.0)


def test_repository_superseded_queue_state_is_terminal_and_safe(tmp_path):
    workspace, state = _fixture(tmp_path)
    p = state / "autonomous-queue.json"
    p.write_text(json.dumps([
        {"id": "legacy-1", "status": "superseded", "superseded_by": "checkpoint"},
        {"id": "legacy-2", "status": "superseded", "superseded_by": "checkpoint"},
    ]), encoding="utf-8")
    receipt = _check(workspace, state)
    assert receipt["queue_status_counts"]["superseded"] == 2
    assert receipt["queue_status_counts"]["pending"] == 0
    assert receipt["qualification_authority"] is False


def test_private_queue_malformed_status_fails_closed(tmp_path):
    workspace, state = _fixture(tmp_path)
    p = state / "autonomous-queue.json"
    p.write_text('[{"status":"auto_live"}]')
    with pytest.raises(mod.PrivateReceiptError, match="state invalid"):
        _check(workspace, state)


def test_symlinked_private_file_is_rejected(tmp_path):
    workspace, state = _fixture(tmp_path)
    path = state / "autonomous-queue.json"
    target = tmp_path / "outside.json"
    target.write_bytes(path.read_bytes())
    path.unlink()
    try:
        path.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation requires unavailable platform privilege")
    with pytest.raises(mod.PrivateReceiptError, match="unsafe"):
        _check(workspace, state)


def test_main_logs_allowlisted_counts_not_private_queue_or_digests(
    tmp_path, monkeypatch, capsys,
):
    now = time.time()
    workspace, state = _fixture(tmp_path, now=now)
    monkeypatch.setenv("RUNNER_WORKSPACE", str(workspace))
    monkeypatch.setenv("NEXUS_STATE_DIR", str(state))
    monkeypatch.setenv("GITHUB_SHA", SHA)
    monkeypatch.setenv("GITHUB_RUN_ID", RUN)
    monkeypatch.setenv("RUNNER_NAME", "NEXUS-LOCAL-RUNNER")
    mod.main()
    text = capsys.readouterr().out
    report = json.loads(text)
    assert report["queue_status_counts"]["completed"] == 1
    assert "owner-private" not in text
    assert "owner-only-path" not in text
    assert "queue_sha256" not in text
    assert "heartbeat_sha256" not in text
    assert report["no_private_state_export"] is True
    local = json.loads((state / "autonomy-receipt.json").read_text())
    assert "queue_sha256" in local and "heartbeat_sha256" in local


def test_workflow_cannot_upload_or_print_owner_private_queue():
    root = Path(__file__).resolve().parents[1]
    text = (root / ".github" / "workflows" / "nexus_local_autonomy.yml").read_text()
    local = text.split("  local-worker:", 1)[1]
    assert "nexus_local_autonomy_receipt.py" in local
    assert "Verify and retain owner-private autonomy evidence" in local
    assert "if: always()" in local
    assert "actions/upload-artifact@" not in local
    assert "durable-state" not in local
    assert 'type "%NEXUS_STATE_DIR%\\autonomous-queue.json"' not in local
    assert 'copy /Y "%NEXUS_STATE_DIR%\\autonomous-queue.json"' not in local
    assert "NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED: '0'" in local
