from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "nexus-local-runner.yml"
BOOTSTRAP = ROOT / "scripts" / "bootstrap_portable_python.cmd"


def test_zero_touch_install_does_not_depend_on_machine_execution_policy() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    install = text.split("- name: Install zero-touch NEXUS autostart", 1)[1].split(
        "- name: Upload zero-touch install evidence", 1
    )[0]
    assert "shell: powershell" not in install
    assert "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass" in install
    assert "-File scripts\\install_nexus_autostart_from_runner.ps1" in install
    assert '-SourceSha "%GITHUB_SHA%"' in install


def test_portable_runner_python_uses_project_lockfile() -> None:
    text = BOOTSTRAP.read_text(encoding="utf-8")
    assert text.count("-r requirements-dev.lock") == 2
    assert "-r requirements.txt" not in text
