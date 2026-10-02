from pathlib import Path


WORKFLOW = Path(".github/workflows/nexus_a7_range_failure_reversal.yml")


def test_a7_workflow_is_trusted_research_only_and_physical():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request:" in text
    assert "workflow_dispatch:" in text
    assert "schedule:" not in text
    assert "permissions:\n  contents: read" in text
    assert "github.event.pull_request.head.repo.full_name == github.repository" in text
    assert "github.actor == github.repository_owner" in text
    assert "runs-on: nexus-bybit-network" in text
    assert "persist-credentials: false" in text
    assert "nexus_multipair_recent_archive_runtime_snapshot.py acquire" in text
    assert "nexus_a7_range_failure_reversal_research.py" in text
    assert "a7_recent_source_bound_evidence=PASS" in text
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in text
    assert "secrets." not in text
    assert "live" not in text.lower() or "live_trading_authority" in text
