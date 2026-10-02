from pathlib import Path


WORKFLOW = Path(".github/workflows/nexus_a9_positioning_research.yml")


def _research_job(text: str) -> str:
    start_marker = "  research-backtest:\n"
    assert text.count(start_marker) == 1
    start = text.index(start_marker)
    return text[start:]


def test_a9_job_uses_exact_source_and_fail_closed_cleanup():
    text = WORKFLOW.read_text(encoding="utf-8")
    job = _research_job(text)

    assert "github.event.pull_request.head.sha || github.sha" in job
    assert "runs-on: [self-hosted, Windows, X64, nexus-research, nexus-worker-2]" in job
    assert "scripts/nexus_windows_tree_cleanup.py" in job
    assert "build\\a9-spot-state build\\a9-spot-cache" in job
    assert "build\\a9-positioning --attempts 20 --delay-seconds 1" in job
    cleanup = job[job.index("- name: Remove raw Research state"):job.index("- name: Clean isolated Python")]
    assert "nexus_windows_tree_cleanup.py" in cleanup
    assert "exit /b 0" not in cleanup
    assert "secrets." not in job
