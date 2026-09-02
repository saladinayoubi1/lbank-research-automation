from __future__ import annotations

import base64
import json
import subprocess
import sys


def _bounded_payload(
    *,
    task_id: str = "P4-DATA-001",
    phase: int = 4,
    transport: str = "github-cloud",
) -> str:
    payload = {
        "schema_version": 2,
        "task_id": task_id,
        "lease_id": "lease-output-parent",
        "correlation_id": "correlation-output-parent",
        "dispatch_id": "dispatch-output-parent",
        "worker_id": "developer-agent",
        "transport": transport,
        "phase": phase,
        "gate": 1,
        "title": "verify nested result output",
        "required_capabilities": [],
        "acceptance": ["result.json is durable"],
        "authority": 1,
        "attempt": 1,
    }
    return base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def _execute(tmp_path, *, task_id: str, phase: int = 4, transport: str = "github-cloud"):
    output = tmp_path / task_id / "result.json"
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/agent_task_executor.py",
            "--payload-b64",
            _bounded_payload(task_id=task_id, phase=phase, transport=transport),
            "--transport",
            transport,
            "--output",
            str(output),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    result = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else None
    return proc, result


def test_executor_creates_nested_result_parent(tmp_path):
    output = tmp_path / "nested" / "agent-result" / "result.json"
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/agent_task_executor.py",
            "--payload-b64",
            _bounded_payload(),
            "--transport",
            "github-cloud",
            "--output",
            str(output),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert output.is_file()
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["task_id"] == "P4-DATA-001"
    assert result["transport"] == "github-cloud"
    assert result["outcome"] == "success"


def test_phase4_event_workload_runs_only_canonical_event_store_suite(tmp_path):
    proc, result = _execute(tmp_path, task_id="P4-EVENT-001")

    assert proc.returncode == 0, proc.stderr
    assert result["outcome"] == "success"
    assert result["evidence"]["executor"] == "bounded-pytest"
    assert result["evidence"]["suite"] == ["tests/test_nexus_event_store.py"]
    assert result["evidence"]["purpose"] == "source-bound-event-store-canonical-chain-replay-and-corruption-proof"


def test_phase4_event_workload_rejects_phase_substitution(tmp_path):
    proc, result = _execute(tmp_path, task_id="P4-EVENT-001", phase=7)

    assert proc.returncode == 2
    assert result["outcome"] == "failure"
    assert result["evidence"]["failure_class"] == "workload_phase_mismatch"
    assert result["evidence"]["expected_phase"] == 4


def test_phase4_event_workload_rejects_transport_substitution(tmp_path):
    proc, result = _execute(tmp_path, task_id="P4-EVENT-001", transport="windows")

    assert proc.returncode == 2
    assert result["outcome"] == "failure"
    assert result["evidence"]["failure_class"] == "workload_transport_mismatch"
    assert result["evidence"]["allowed_transports"] == ["github-cloud"]


def test_phase4_ui_workload_runs_only_canonical_shell_contract(tmp_path):
    proc, result = _execute(tmp_path, task_id="P4-UI-001")

    assert proc.returncode == 0, proc.stderr
    assert result["outcome"] == "success"
    assert result["evidence"]["executor"] == "bounded-pytest"
    assert result["evidence"]["suite"] == ["tests/test_web_ui.py"]
    assert result["evidence"]["purpose"] == "source-bound-responsive-read-only-shell-and-degraded-state-proof"


def test_phase4_ui_workload_rejects_phase_substitution(tmp_path):
    proc, result = _execute(tmp_path, task_id="P4-UI-001", phase=7)

    assert proc.returncode == 2
    assert result["outcome"] == "failure"
    assert result["evidence"]["failure_class"] == "workload_phase_mismatch"
    assert result["evidence"]["expected_phase"] == 4


def test_phase4_ui_workload_rejects_transport_substitution(tmp_path):
    proc, result = _execute(tmp_path, task_id="P4-UI-001", transport="windows")

    assert proc.returncode == 2
    assert result["outcome"] == "failure"
    assert result["evidence"]["failure_class"] == "workload_transport_mismatch"
    assert result["evidence"]["allowed_transports"] == ["github-cloud"]
