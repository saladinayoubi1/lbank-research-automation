from __future__ import annotations

import base64
import json
import subprocess
import sys


def _bounded_payload() -> str:
    payload = {
        "schema_version": 2,
        "task_id": "P4-DATA-001",
        "lease_id": "lease-output-parent",
        "correlation_id": "correlation-output-parent",
        "dispatch_id": "dispatch-output-parent",
        "worker_id": "developer-agent",
        "transport": "github-cloud",
        "phase": 4,
        "gate": 1,
        "title": "verify nested result output",
        "required_capabilities": [],
        "acceptance": ["result.json is durable"],
        "authority": 1,
        "attempt": 1,
    }
    return base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


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
