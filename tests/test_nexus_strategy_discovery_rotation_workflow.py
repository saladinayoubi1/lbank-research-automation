from pathlib import Path


WORKFLOW = Path(".github/workflows/nexus_strategy_discovery_rotation.yml")


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_rotation_keeps_daily_fallback_and_adds_paper_loop_health_event():
    text = _text()
    assert 'cron: "37 2 * * *"' in text
    assert "workflow_run:" in text
    assert 'workflows: ["NEXUS persistent Paper trading loop"]' in text
    assert "types: [completed]" in text


def test_health_event_consumes_exact_triggering_run_artifact_before_dispatch():
    text = _text()
    assert "github.event.workflow_run.id" in text
    assert "actions/runs/$TRIGGER_RUN_ID/artifacts" in text
    assert "nexus-persistent-paper-trading-state" in text
    assert "nexus_strategy_discovery_health_trigger.py" in text
    assert "should_dispatch" in text


def test_rotation_preserves_bounded_dispatch_authority():
    text = _text()
    permissions = text.split("permissions:", 1)[1].split("concurrency:", 1)[0]
    assert "contents: read" in permissions
    assert "actions: write" in permissions
    assert "contents: write" not in permissions
    assert "id-token: write" not in permissions
    assert "packages: write" not in permissions
    assert 'gh workflow run "$workflow" --ref main' in text
    assert "nexus_strategy_discovery_rotation.py commit" in text


def test_health_dispatch_is_gated_but_daily_rotation_remains_independent():
    text = _text()
    assert "HEALTH_TRIGGER" in text
    assert "steps.health-gate.outputs.should_dispatch == 'true'" in text
    assert "github.event_name != 'workflow_run'" in text
