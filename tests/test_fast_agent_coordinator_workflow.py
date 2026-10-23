from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "fast-agent-coordinator.yml"


def test_existing_coordinator_wakes_immediately_after_runtime_worker_completion():
    text = WORKFLOW.read_text(encoding="utf-8")
    trigger = re.search(
        r'(?ms)^  workflow_run:\n(?P<body>.*?)(?=^  [a-z_]+:|^jobs:)',
        text,
    )
    assert trigger is not None
    body = trigger.group("body")
    assert re.search(r'(?m)^    workflows:\n      - "NEXUS Runtime Worker"$', body)
    assert re.search(r"(?m)^    types: \[completed\]$", body)
    # Do not wake on coordinator's own completion or unrelated workflows.
    assert re.findall(r'(?m)^      - "([^"]+)"$', body) == ["NEXUS Runtime Worker"]


def test_event_trigger_is_limited_to_same_repository_main_runs():
    text = WORKFLOW.read_text(encoding="utf-8")
    job = re.search(r"(?ms)^  inspect-and-recover:\n(?P<body>.*?)(?=^  [a-z0-9_-]+:\n|^$)", text)
    assert job is not None
    body = job.group("body")
    assert "github.event_name != 'workflow_run'" in body
    assert "github.event.workflow_run.name == 'NEXUS Runtime Worker'" in body
    assert "github.event.workflow_run.head_branch == 'main'" in body
    assert "github.event.workflow_run.head_repository.full_name == github.repository" in body


def test_immediate_wakeup_reuses_existing_serialized_manager_and_result_transport():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "group: fast-agent-coordinator" in text
    assert "cancel-in-progress: false" in text
    commands = [
        "python agent_transport.py --mode poll",
        "python agent_manager_runner.py --config config/nexus-agent-manager.json",
        "python agent_transport.py --mode dispatch",
    ]
    offsets = [text.index(command) for command in commands]
    assert offsets == sorted(offsets)
    # Existing periodic watchdog remains a fallback; no new worker/queue is added.
    assert "cron: '*/5 * * * *'" in text
    assert "nexus-research-autopilot" not in text.lower()
