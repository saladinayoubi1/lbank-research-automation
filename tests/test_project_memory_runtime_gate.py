import json
from pathlib import Path

import project_memory_runtime_gate as gate


VALID_SHA = "a" * 40
OTHER_SHA = "b" * 40


def _write_memory(root: Path, observed_sha: str) -> None:
    memory = root / "docs" / "project_memory"
    memory.mkdir(parents=True)
    (memory / "PROJECT_MEMORY.md").write_text(
        "# NEXUS Project Memory\n\n## Immutable mission and safety boundary\nResearch only.\n\n## Durable-memory contract\nRepository evidence wins.\n",
        encoding="utf-8",
    )
    (memory / "DECISIONS.md").write_text(
        "# Decisions\n\nThis is an append-oriented log; later decisions supersede rather than erase history.\n",
        encoding="utf-8",
    )
    (memory / "RECOVERY_PLAYBOOK.md").write_text(
        "# Recovery\n\nverify current `main`, open PRs/issues and CI/workflow evidence before stronger action. Backup presence alone is not recovery proof.\n",
        encoding="utf-8",
    )
    state = {
        "schema_version": 2,
        "project": "NEXUS / lbank-research-automation",
        "memory_policy": {
            "repository_is_durable_source": True,
            "chat_is_source_of_truth": False,
            "secrets_allowed": False,
            "core_goals_agent_editable": False,
        },
        "data_policy": {"research_only": True, "real_trading": False, "fabricated_market_data": False},
        "continuity": {
            "required_reads": [
                "docs/project_memory/PROJECT_MEMORY.md",
                "docs/project_memory/STATE.json",
                "docs/project_memory/DECISIONS.md",
                "docs/project_memory/RECOVERY_PLAYBOOK.md",
            ],
            "drive_backup": {"secondary_only": True, "may_authorize_production_recovery": False},
        },
        "current_evidence": {"observed_main_sha": observed_sha, "observed_at_utc": "2026-08-14T00:00:00Z"},
    }
    (memory / "STATE.json").write_text(json.dumps(state), encoding="utf-8")


def test_stale_memory_is_explicitly_non_authoritative(tmp_path):
    _write_memory(tmp_path, VALID_SHA)
    result = gate.assess(tmp_path, OTHER_SHA)
    assert result["authoritative"] is False
    assert result["reason"] == "stale_or_conflicting_project_memory"


def test_matching_memory_can_be_authoritative(tmp_path):
    _write_memory(tmp_path, VALID_SHA)
    result = gate.assess(tmp_path, VALID_SHA)
    assert result["authoritative"] is True
    assert result["reason"] == "validated"
