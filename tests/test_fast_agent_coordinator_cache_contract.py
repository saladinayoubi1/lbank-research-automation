from pathlib import Path


WORKFLOW = Path(".github/workflows/fast-agent-coordinator.yml")


def test_rerun_attempts_use_distinct_durable_cache_keys() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    key = "nexus-agent-manager-${{ github.run_id }}-${{ github.run_attempt }}"
    assert text.count(key) == 2
    assert "restore-keys: |\n            nexus-agent-manager-" in text


def test_legacy_run_id_only_cache_key_is_not_used() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    legacy = "key: nexus-agent-manager-${{ github.run_id }}\n"
    assert legacy not in text


def test_fast_coordinator_syncs_composite_runtime_qa_before_manager_cycle() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    sync = "python nexus_composite_runtime_qa_transport.py"
    manager = "python agent_manager_runner.py"
    assert sync in text
    assert "--store data/agent_coordination/composite_runtime_qa_tasks" in text
    assert text.index(sync) < text.index(manager)
