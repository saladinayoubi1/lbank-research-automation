from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR = ROOT / "fast_agent_orchestrator.py"


def test_windows_cli_children_use_create_no_window() -> None:
    text = ORCHESTRATOR.read_text(encoding="utf-8")
    assert 'getattr(subprocess, "CREATE_NO_WINDOW", 0)' in text
    assert 'if os.name == "nt" else 0' in text
    assert "creationflags=creationflags" in text
    assert '["gh", "run", "list"' in text
    assert '["gh", "run", "rerun"' in text
