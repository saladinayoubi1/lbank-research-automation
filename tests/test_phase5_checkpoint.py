import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT_PATH = ROOT / ".nexus" / "phase5-checkpoint.json"
QUEUE_PATH = ROOT / ".nexus" / "autonomous-queue.json"
MANIFEST_PATH = ROOT / "docs" / "evidence" / "phase5" / "gate9" / "manifest.json"
CLOUD_PATH = ROOT / "docs" / "evidence" / "phase5" / "gate9" / "cloud.json"
WINDOWS_PATH = ROOT / "docs" / "evidence" / "phase5" / "gate9" / "windows.json"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_phase5_checkpoint_is_closed_and_paper_only():
    checkpoint = load_json(CHECKPOINT_PATH)

    assert checkpoint["phase"] == 5
    assert checkpoint["status"] == "complete"
    assert checkpoint["formal_gates"] == "0-9"
    assert checkpoint["formal_gates_complete"] is True
    assert checkpoint["paper_only"] is True
    assert checkpoint["live_trading_authority"] is False
    assert checkpoint["next_phase_requires_new_contract"] is True


def test_gate9_durable_evidence_matches_manifest():
    checkpoint = load_json(CHECKPOINT_PATH)
    manifest = load_json(MANIFEST_PATH)
    cloud = load_json(CLOUD_PATH)
    windows = load_json(WINDOWS_PATH)

    assert checkpoint["gate9_evidence_manifest"] == "docs/evidence/phase5/gate9/manifest.json"
    assert manifest["status"] == "complete"
    assert manifest["paper_only"] is True
    assert cloud["runtime_platform"] == "Linux"
    assert windows["runtime_platform"] == "Windows"

    for evidence in (cloud, windows):
        assert evidence["source_sha"] == manifest["source_sha"]
        assert evidence["gate9"]["source_sha"] == manifest["source_sha"]
        assert evidence["gate9"]["evidence_digest"] == manifest["gate9_evidence_digest"]
        assert evidence["gate9"]["paper_only"] is True
        assert evidence["gate9"]["gate6"]["profitability_claim"] is False
        assert evidence["gate9"]["gate6"]["status"] == "killed"
        assert "ROBUSTNESS_KILL" in evidence["gate9"]["gate6"]["kill_reasons"]


def test_legacy_phase3_queue_cannot_reappear_as_pending_work():
    checkpoint = load_json(CHECKPOINT_PATH)
    queue = load_json(QUEUE_PATH)

    assert checkpoint["legacy_queue_state"] == "superseded"
    assert queue
    assert all(item["id"].startswith("phase3-") for item in queue)
    assert all(item["status"] == "superseded" for item in queue)
    assert all(item["superseded_by"] == ".nexus/phase5-checkpoint.json" for item in queue)
