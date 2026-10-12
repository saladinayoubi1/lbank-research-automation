import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

import nexus_composite_runtime_qa_transport as transport

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "a" * 40
CURRENT = "b" * 40


@pytest.mark.parametrize("entry", ["controller", "phase3"])
def test_standalone_entrypoints_find_real_feedback_without_pythonpath(tmp_path, entry):
    project = tmp_path / "project"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    for relative in [
        "scripts/nexus_strategy_discovery_controller.py",
        "scripts/nexus_phase3_task.py",
        "nexus_strategy_discovery_feedback.py",
        "product_research_reports.py",
    ]:
        target = project / relative
        shutil.copy2(ROOT / relative, target)
    outside = tmp_path / "outside"
    outside.mkdir()
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    if entry == "controller":
        command = [sys.executable, "-E", str(scripts / "nexus_strategy_discovery_controller.py"), "--root", str(project)]
    else:
        command = [sys.executable, "-E", str(scripts / "nexus_phase3_task.py"), "strategy"]
    result = subprocess.run(command, cwd=outside, env=env, capture_output=True, text=True, timeout=20)
    # The small isolated project has no reviewed catalog/engines and must remain unqualified.
    assert result.returncode == 2, result.stderr
    assert "ModuleNotFoundError" not in result.stderr
    payload = json.loads(result.stdout)
    assert payload["controller_verified"] is False
    assert payload["qualified_candidates"] == []
    assert payload["qualification_claimed"] is False
    assert payload["live_trading_authority"] is False


def ancestry_response():
    return {"status": "ahead", "ahead_by": 1, "behind_by": 0,
            "merge_base_commit": {"sha": SOURCE}, "commits": []}


def test_ancestry_uses_metadata_page_even_when_singleton_has_no_commit_rows(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "saladinayoubi1/lbank-research-automation")
    def api(method, url, payload):
        assert method == "GET" and payload is None
        parsed = urlsplit(url)
        assert parsed.path.endswith(f"/compare/{SOURCE}...{CURRENT}")
        assert parse_qs(parsed.query) == {"per_page": ["1"], "page": ["2"]}
        return ancestry_response()
    assert transport._trusted_main_ancestor(SOURCE, CURRENT, api=api) is True


@pytest.mark.parametrize("changed", [
    {"status": "diverged"}, {"status": "behind"}, {"behind_by": 1},
    {"ahead_by": True}, {"ahead_by": 0}, {"merge_base_commit": {"sha": "c" * 40}},
])
def test_metadata_pagination_does_not_relax_exact_ancestor_checks(monkeypatch, changed):
    monkeypatch.setenv("GITHUB_REPOSITORY", "saladinayoubi1/lbank-research-automation")
    response = {**ancestry_response(), **changed}
    assert transport._trusted_main_ancestor(SOURCE, CURRENT, api=lambda *_args: response) is False


def test_phase3_push_depends_on_the_controller_and_real_feedback_without_starting_local_worker():
    text = (ROOT / ".github/workflows/nexus-continuous-phase3.yml").read_text()
    assert "'scripts/nexus_strategy_discovery_controller.py'" in text
    assert "'nexus_strategy_discovery_feedback.py'" in text
    assert "github.event_name == 'workflow_dispatch' &&" in text
    assert "github.actor == github.repository_owner" in text
    assert "permissions:\n  contents: read" in text
