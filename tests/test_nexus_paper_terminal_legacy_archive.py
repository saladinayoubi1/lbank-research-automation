"""Fail closed on historical terminal source/run/artifact changes, without execution."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

import bybit_prospective_paper_forward_v1 as forward
import nexus_paper_terminal_legacy_archive as archive


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "experiments/bybit_prospective_paper_forward_v1.json"
SOURCE = "a" * 40
CURRENT_SOURCE = "b" * 40


@pytest.fixture
def specimen(tmp_path: Path, monkeypatch):
    cfg, _ = forward.load_contract(MANIFEST)
    engine = ROOT / "bybit_prospective_paper_forward_v1.py"
    original_sha = forward._file_sha(engine)  # noqa: SLF001
    old_run_id = 10
    state = forward.new_state(
        cfg, engine_sha256=original_sha, source_sha=SOURCE, run_id=old_run_id
    )
    state["status"] = "QUARANTINED"
    state["decision"] = "paper_forward_failed_no_promotion"
    state["state_digest"] = forward._digest({k: v for k, v in state.items() if k != "state_digest"})  # noqa: SLF001
    state_path = tmp_path / "historical.json"
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    run = {
        "id": old_run_id, "head_sha": SOURCE, "head_branch": "main",
        "name": "Bybit prospective Paper forward v1",
        "event": "schedule", "status": "completed", "conclusion": "success",
        "html_url": f"https://github.com/saladinayoubi1/lbank-research-automation/actions/runs/{old_run_id}",
    }
    run_file = tmp_path / "original-run.json"
    run_file.write_text(json.dumps(run), encoding="utf-8")
    monkeypatch.setattr(archive, "OLD_SOURCE_SHA", SOURCE)
    monkeypatch.setattr(archive, "OLD_ENGINE_SHA256", original_sha)
    monkeypatch.setattr(archive, "OLD_STATE_DIGEST", state["state_digest"])
    monkeypatch.setattr(archive, "OLD_STATE_RAW_SHA256", hashlib.sha256(state_path.read_bytes()).hexdigest())
    monkeypatch.setattr(archive, "OLD_RUN_ID", old_run_id)
    monkeypatch.setattr(archive, "OLD_BAR_COUNT", 0)
    return {
        "manifest_path": MANIFEST, "state_path": state_path,
        "old_engine_path": engine, "old_run_path": run_file,
        "current_source_sha": CURRENT_SOURCE, "current_run_id": old_run_id + 1,
        "output": tmp_path / "terminal-receipt.json",
    }


def test_exact_legacy_archive_does_not_mutate_original_state_or_claim_runtime_migration(specimen):
    original = specimen["state_path"].read_bytes()
    result = archive.archive(**specimen)
    assert specimen["state_path"].read_bytes() == original
    assert result["historical_state_unchanged"] is True
    assert result["historical_runtime_requalified_for_current_engine"] is False
    assert result["new_bars_processed"] == 0
    assert result["new_paper_admission"] is False
    assert result["automatic_paper_promotion"] is False
    assert result["live_trading_enabled"] is False
    assert result["original_status"] == "QUARANTINED"
    assert archive.verify_receipt(
        **{k: v for k, v in specimen.items() if k != "output"},
        receipt_path=specimen["output"],
    ) == result
    with pytest.raises(archive.HistoricalTerminalArchiveError, match="overwrite"):
        archive.archive(**specimen)


def test_changed_historical_state_even_if_resigned_rejected(specimen, monkeypatch):
    value = json.loads(specimen["state_path"].read_text())
    value["completed_bar_count"] = 1
    value["state_digest"] = forward._digest({k: v for k, v in value.items() if k != "state_digest"})  # noqa: SLF001
    specimen["state_path"].write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    with pytest.raises(archive.HistoricalTerminalArchiveError, match="untrusted"):
        archive.archive(**specimen)
    # Even if an adversary tries re-pinning just the raw bytes, the historical
    # state digest and the original approved completed-bar count still fail.
    monkeypatch.setattr(archive, "OLD_STATE_RAW_SHA256", hashlib.sha256(specimen["state_path"].read_bytes()).hexdigest())
    with pytest.raises(archive.HistoricalTerminalArchiveError):
        archive.archive(**specimen)


@pytest.mark.parametrize("corruption", [
    {"head_sha": "z" * 40},
    {"head_branch": "feature"},
    {"conclusion": "failure"},
    {"event": "pull_request"},
    {"id": 999},
    {"name": "unrelated"},
])
def test_wrong_original_workflow_run_fails_closed(specimen, corruption):
    path = specimen["old_run_path"]
    record = json.loads(path.read_text())
    record.update(corruption)
    path.write_text(json.dumps(record))
    with pytest.raises(archive.HistoricalTerminalArchiveError, match="run identity"):
        archive.archive(**specimen)


def test_unrelated_engine_or_invented_prior_sha_never_archived(specimen, tmp_path):
    wrong = tmp_path / "wrong.py"
    wrong.write_bytes(specimen["old_engine_path"].read_bytes() + b"\n# drift\n")
    with pytest.raises(archive.HistoricalTerminalArchiveError, match="untrusted"):
        archive.archive(**{**specimen, "old_engine_path": wrong})
    with pytest.raises(archive.HistoricalTerminalArchiveError, match="source SHA"):
        archive.archive(**{**specimen, "current_source_sha": "z" * 40})
    with pytest.raises(archive.HistoricalTerminalArchiveError, match="subsequent"):
        archive.archive(**{**specimen, "current_run_id": 10})


def test_receipt_tamper_and_replay_under_another_run_fail_closed(specimen):
    archive.archive(**specimen)
    kwargs = {k: v for k, v in specimen.items() if k != "output"}
    forged = deepcopy(json.loads(specimen["output"].read_text()))
    forged["new_bars_processed"] = 1
    forged["receipt_digest"] = forward._digest({k: v for k, v in forged.items() if k != "receipt_digest"})  # noqa: SLF001
    specimen["output"].write_text(json.dumps(forged))
    with pytest.raises(archive.HistoricalTerminalArchiveError, match="receipt"):
        archive.verify_receipt(receipt_path=specimen["output"], **kwargs)
    with pytest.raises(archive.HistoricalTerminalArchiveError):
        archive.verify_receipt(receipt_path=specimen["output"], **{**kwargs, "current_run_id": 12})


def test_archiver_workflow_keeps_historical_state_not_rebound_or_promoted():
    producer = (ROOT / ".github/workflows/bybit_prospective_paper_forward_v1.yml").read_text()
    reporter = (ROOT / ".github/workflows/nexus_bybit_paper_gate_report.yml").read_text()
    assert "nexus_paper_terminal_legacy_archive.py archive" in producer
    assert "nexus_paper_terminal_legacy_archive.py verify" in producer
    assert "legacy-archive" in producer
    assert 'steps.terminal.outputs.legacy_archive != \'true\'' in producer
    assert "terminal_archive_receipt.json" in producer
    assert "nexus_paper_terminal_legacy_archive.py verify" in reporter
    assert "terminal_archive_receipt.json" in reporter
    assert "nexus_paper_runtime_attestation.py verify" in reporter
