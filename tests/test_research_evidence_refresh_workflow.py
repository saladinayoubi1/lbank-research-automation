from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "research-evidence-refresh.yml"


def test_refresh_workflow_is_scheduled_manual_and_read_only():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "schedule:" in text and "cron:" in text
    assert "permissions:\n  contents: read" in text
    assert "contents: write" not in text and "id-token: write" not in text


def test_refresh_workflow_runs_all_research_gates():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "scripts/validate_research_registry.py" in text
    assert "scripts/validate_bibtex.py references/references.bib" in text
    assert "tests.test_research_registry tests.test_validate_bibtex" in text
