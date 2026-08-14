from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

WINDOWS_WORKFLOWS = [
    ROOT / ".github" / "workflows" / "nexus-local-runner.yml",
    ROOT / ".github" / "workflows" / "nexus_local_autonomy.yml",
    ROOT / ".github" / "workflows" / "nexus-continuous-phase3.yml",
    ROOT / ".github" / "workflows" / "nexus-runtime-worker.yml",
]


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_windows_phase3_paths_do_not_use_setup_python_action() -> None:
    for workflow in WINDOWS_WORKFLOWS:
        assert "actions/setup-python@v5" not in text(workflow), workflow.name


def test_python_windows_paths_share_portable_bootstrap() -> None:
    for name in ("nexus-local-runner.yml", "nexus_local_autonomy.yml", "nexus-continuous-phase3.yml"):
        workflow = ROOT / ".github" / "workflows" / name
        assert "scripts\\bootstrap_portable_python.cmd" in text(workflow), name


def test_node_is_provisioned_before_local_worker_and_runtime_worker() -> None:
    local_runner = text(ROOT / ".github" / "workflows" / "nexus-local-runner.yml")
    runtime_worker = text(ROOT / ".github" / "workflows" / "nexus-runtime-worker.yml")
    assert "actions/setup-node@v4" in local_runner
    assert "actions/setup-node@v4" in runtime_worker
    assert "shell: powershell" not in runtime_worker


def test_autonomous_windows_paths_disable_paid_smoke_during_stabilization() -> None:
    for name in ("nexus-local-runner.yml", "nexus_local_autonomy.yml", "nexus-continuous-phase3.yml"):
        workflow = text(ROOT / ".github" / "workflows" / name)
        assert "NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED: '0'" in workflow, name
