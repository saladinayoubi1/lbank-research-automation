from pathlib import Path


WORKFLOW = Path(".github/workflows/nexus_multipair_archive_snapshot.yml")


def test_a7_job_is_trusted_research_only_and_physical():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request:" in text
    assert "permissions:\n  actions: read\n  contents: read" in text
    assert "a7-research-backtest:" in text
    assert "github.event.pull_request.head.repo.full_name == github.repository" in text
    assert "github.actor == github.repository_owner" in text
    assert "runs-on: [self-hosted, Windows, X64, nexus-research, nexus-worker-2]" in text
    assert "persist-credentials: false" in text
    assert "shell: powershell" not in text
    assert "actions/setup-python" not in text
    assert "nexus_a7_daily_recent_source.py" in text
    assert "--source-proof-root build/a7-recent-proof" in text
    assert "a7_recent_source_bound_evidence=PASS" in text
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in text
    assert "secrets." not in text
