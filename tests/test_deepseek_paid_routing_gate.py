from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_smoke_rejects_when_paid_routing_not_authorized() -> None:
    env = os.environ.copy()
    env.pop("NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED", None)
    env.pop("DEEPSEEK_API_KEY", None)
    env["PYTHONPATH"] = str(ROOT)

    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "deepseek_smoke.py")],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
    )

    assert proc.returncode != 0
    assert "paid routing is not explicitly authorized" in proc.stderr


def test_phase3_worker_requires_explicit_paid_routing_gate() -> None:
    worker = (ROOT / "scripts" / "nexus_phase3_worker.js").read_text(encoding="utf-8")
    assert "process.env.NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED === '1'" in worker
    assert "paidRoutingAllowed && process.env.DEEPSEEK_API_KEY" in worker


def test_local_worker_requires_explicit_paid_routing_gate() -> None:
    worker = (ROOT / "scripts" / "nexus_local_worker.py").read_text(encoding="utf-8")
    assert "NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED') != '1'" in worker
    assert "NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED_not_1" in worker


def test_resource_activation_allows_only_one_paid_deepseek_path() -> None:
    workflow = (ROOT / ".github" / "workflows" / "nexus_phase3_resource_activation.yml").read_text(encoding="utf-8")
    assert 'if [ "$NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED" != "1" ]; then' in workflow
    assert "python scripts/deepseek_smoke.py" in workflow
    assert "Emit cloud resource status without a second paid call" in workflow
    assert workflow.count("NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED: '0'") >= 2

    status_step = workflow.split("- name: Emit cloud resource status without a second paid call", 1)[1]
    status_step = status_step.split("\n\n  laptop-runner:", 1)[0]
    assert "NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED: '0'" in status_step
    assert "${{ vars.NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED }}" not in status_step
