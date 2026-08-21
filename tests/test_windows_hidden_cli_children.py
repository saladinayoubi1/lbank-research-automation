from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR = ROOT / "fast_agent_orchestrator.py"


def test_windows_cli_children_use_create_no_window() -> None:
    text = ORCHESTRATOR.read_text(encoding="utf-8")
    assert 'getattr(subprocess, "CREATE_NO_WINDOW", 0)' in text
    assert 'if os.name == "nt" else 0' in text
    assert "creationflags=creationflags" in text

    # Bind the two GitHub CLI paths semantically instead of depending on whether
    # the list literal is formatted on one line or across several lines.
    assert '"gh", "run", "list"' in text.replace("\n", " ")
    assert '"gh", "run", "rerun"' in text.replace("\n", " ")
