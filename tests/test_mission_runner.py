from __future__ import annotations

import json
from pathlib import Path

import pytest

from mission_runner import MissionRunnerError, load_queue, orchestrate, run_mission_orchestration


def queue() -> dict:
    return {
        "version": 2,
        "selectionPolicy": {"maxParallelMissions": 3},
        "missions": [
            {"id": "M-1", "title": "Done", "status": "completed", "priority": "automation", "lane": "general", "dependencies": [], "reversible": True},
            {"id": "M-2", "title": "Product", "status": "active", "priority": "product_research", "lane": "product", "dependencies": ["M-1"], "reversible": True},
            {"id": "M-3", "title": "Blocker", "status": "queued", "priority": "phase_blocker", "lane": "blocker", "dependencies": ["M-1"], "reversible": True},
            {"id": "M-4", "title": "Backlog", "status": "queued", "priority": "backlog", "lane": "backlog", "dependencies": ["M-3"], "reversible": True},
        ],
    }


def test_orchestration_is_deterministic_read_only_and_product_first():
    payload = queue()
    before = json.loads(json.dumps(payload))
    first = orchestrate(payload)
    second = orchestrate(payload)
    assert first == second
    assert payload == before
    assert first["executed"] is True
    assert first["state_mutation"] is False
    assert first["paper_only"] is True
    assert first["selected_mission_id"] == "M-2"
    assert first["parallel_mission_ids"] == ["M-2", "M-3"]
    assert len(first["queue_digest"]) == 64


def test_file_runner_reads_bounded_queue_without_writing(tmp_path: Path):
    path = tmp_path / "queue.json"
    content = json.dumps(queue(), sort_keys=True)
    path.write_text(content, encoding="utf-8")
    result = run_mission_orchestration(path)
    assert result["selected_mission_id"] == "M-2"
    assert path.read_text(encoding="utf-8") == content


def test_non_reversible_or_unknown_dependency_fails_closed(tmp_path: Path):
    bad = queue()
    bad["missions"][1]["reversible"] = False
    with pytest.raises(MissionRunnerError, match="reversible"):
        orchestrate(bad)
    bad = queue()
    bad["missions"][1]["dependencies"] = ["M-404"]
    with pytest.raises(MissionRunnerError, match="unknown mission"):
        orchestrate(bad)


def test_queue_size_and_parallel_bounds_fail_closed(tmp_path: Path):
    path = tmp_path / "queue.json"
    path.write_text("x" * 300_000, encoding="utf-8")
    with pytest.raises(MissionRunnerError, match="size"):
        load_queue(path)
    bad = queue()
    bad["selectionPolicy"]["maxParallelMissions"] = 99
    with pytest.raises(MissionRunnerError, match="maxParallelMissions"):
        orchestrate(bad)
