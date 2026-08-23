from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETUP_NODE = "actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020"

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
    assert SETUP_NODE in local_runner
    assert SETUP_NODE in runtime_worker
    assert "shell: powershell" not in runtime_worker


def test_autonomous_windows_paths_disable_paid_smoke_during_stabilization() -> None:
    for name in ("nexus-local-runner.yml", "nexus_local_autonomy.yml", "nexus-continuous-phase3.yml"):
        workflow = text(ROOT / ".github" / "workflows" / name)
        assert "NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED: '0'" in workflow, name


def test_candidate_validation_state_survives_workflow_reruns() -> None:
    runtime_worker = text(ROOT / ".github" / "workflows" / "nexus-runtime-worker.yml")
    assert "NEXUS_STATE_DIR=%RUNNER_WORKSPACE%\\_nexus_phase3_candidate_state" in runtime_worker
    assert "NEXUS_STATE_DIR=%RUNNER_TEMP%" not in runtime_worker
    assert "candidate-state-%GITHUB_RUN_ID%" not in runtime_worker


def test_candidate_validation_exercises_real_durable_queue_and_state() -> None:
    runtime_worker = text(ROOT / ".github" / "workflows" / "nexus-runtime-worker.yml")
    assert "Exercise durable candidate state" in runtime_worker
    assert "candidate_queue_preexisting=" in runtime_worker
    assert "candidate_state_preexisting=" in runtime_worker
    assert "python nexus_autonomous_orchestrator.py" in runtime_worker
    assert "candidate_durable_state_verified=true" in runtime_worker
