from pathlib import Path


WORKFLOW = Path(".github/workflows/nexus_multipair_archive_snapshot.yml")


def _a7_job(text: str) -> str:
    start_marker = "  a7-research-backtest:\n"
    end_marker = "  contract-test:\n"
    assert text.count(start_marker) == 1
    start = text.index(start_marker)
    end = text.index(end_marker, start + len(start_marker))
    return text[start:end]


def test_a7_job_is_trusted_research_only_and_physical():
    text = WORKFLOW.read_text(encoding="utf-8")
    job = _a7_job(text)

    assert "pull_request:" in text
    assert "permissions:\n  actions: read\n  contents: read" in text
    assert "a7-research-backtest:" in job
    assert "github.event.pull_request.head.repo.full_name == github.repository" in job
    assert "github.actor == github.repository_owner" in job
    assert "runs-on: [self-hosted, Windows, X64, nexus-research, nexus-worker-2]" in job
    assert "ref: ${{ github.event.pull_request.head.sha }}" in job
    assert "persist-credentials: false" in job
    assert "shell: powershell" not in job
    assert "actions/setup-python" not in job
    assert "nexus_a7_daily_recent_source.py" in job
    assert "--source-proof-root build/a7-recent-proof" in job
    assert "a7_recent_source_bound_evidence=PASS" in job
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in job
    assert "secrets." not in job
