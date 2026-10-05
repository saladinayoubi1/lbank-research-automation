from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from nexus_strategy_qa_handoff_transport import (
    ARTIFACT_PREFIX,
    StrategyQaTransportError,
    latest_verified_handoff,
    parse_artifact,
    store_verified_handoff,
)
from nexus_strategy_review_qa_handoff import verify_handoff


def _digest(value):
    import hashlib
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _handoff(source_sha: str = "b" * 40):
    task_core = {
        "schema_version": "nexus.strategy-review-qa-task.v1",
        "id": "STRATEGY-QA-" + "a" * 64,
        "task_kind": "strategy_review_independent_qa",
        "system_map_node": "QA-41",
        "status": "READY_FOR_QA_DISPATCH",
        "source_sha": source_sha,
        "proposal_digest": "a" * 64,
        "proposal_result_digest": "c" * 64,
        "requalification_digest": "d" * 64,
        "requalification_verification_digest": "e" * 64,
        "family": "momentum",
        "timeframe": "hour4",
        "variant_id": "v1",
        "strategy_config": {"lookback": 16},
        "strategy_config_digest": "",
        "runtime_evidence": [{
            "symbol": "BTCUSDT",
            "dataset_binding_sha256": "f" * 64,
            "pipeline_digest": "1" * 64,
            "qualification_digest": "2" * 64,
            "last_open_time_ms": 1_800_000_000_000,
        }],
        "producer_role": "strategy-runtime-requalification",
        "required_verifier": "qa-verifier-agent",
        "research_only": True,
        "paper_only": True,
        "candidate_creation_authority": False,
        "qualification_authority": False,
        "promotion_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    task_core["strategy_config_digest"] = _digest(task_core["strategy_config"])
    task = {**task_core, "task_digest": _digest(task_core)}
    core = {
        "schema_version": "nexus.strategy-review-qa-handoff.v1",
        "source_sha": source_sha,
        "requalification_digest": "d" * 64,
        "requalification_verification_digest": "e" * 64,
        "status": "READY_FOR_QA",
        "task_count": 1,
        "tasks": [task],
        "required_verifier": "qa-verifier-agent",
        "research_only": True,
        "paper_only": True,
        "candidate_creation_authority": False,
        "qualification_authority": False,
        "promotion_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    return {**core, "handoff_digest": _digest(core)}


def _artifact(*, source_sha: str = "b" * 40, no_work: bool = False, tamper: bool = False):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if no_work:
            zf.writestr(
                "runtime-requalification-no-work.json",
                json.dumps({"status": "NO_WORK"}),
            )
        else:
            handoff = _handoff(source_sha)
            verification = verify_handoff(handoff)
            assert verification["decision"] == "pass"
            if tamper:
                handoff["tasks"][0]["strategy_config"]["lookback"] = 99
            zf.writestr("qa-handoff.json", json.dumps(handoff))
            zf.writestr("qa-handoff-verification.json", json.dumps(verification))
    return buffer.getvalue()


def test_parse_verified_handoff_and_exact_no_work():
    parsed = parse_artifact(_artifact())
    assert parsed is not None
    handoff, verification = parsed
    assert verification == verify_handoff(handoff)
    assert parse_artifact(_artifact(no_work=True)) is None


def test_tampered_handoff_artifact_fails_closed():
    with pytest.raises(StrategyQaTransportError, match="verification rejected"):
        parse_artifact(_artifact(tamper=True))


def test_latest_handoff_admits_only_exact_current_main(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "saladinayoubi1/lbank-research-automation")
    current = "b" * 40

    def api(method, url, payload=None):
        assert method == "GET"
        if "/runs?branch=main" in url:
            return {
                "workflow_runs": [{
                    "id": 42,
                    "conclusion": "success",
                    "head_branch": "main",
                    "event": "workflow_run",
                }]
            }
        if "/runs/42/artifacts" in url:
            return {
                "artifacts": [{
                    "id": 99,
                    "name": ARTIFACT_PREFIX + "42",
                    "expired": False,
                    "size_in_bytes": len(_artifact()),
                }]
            }
        raise AssertionError(url)

    result = latest_verified_handoff(
        current_sha=current,
        api=api,
        downloader=lambda artifact_id: _artifact(source_sha=current),
    )
    assert result is not None
    assert result[0]["source_sha"] == current
    assert result[2] == 42

    stale = latest_verified_handoff(
        current_sha=current,
        api=api,
        downloader=lambda artifact_id: _artifact(source_sha="a" * 40),
    )
    assert stale is None


def test_verified_handoff_store_is_immutable(tmp_path: Path):
    handoff = _handoff()
    proof = verify_handoff(handoff)
    target = store_verified_handoff(tmp_path / "qa-store", handoff, proof)
    assert target.name == handoff["handoff_digest"]
    assert store_verified_handoff(tmp_path / "qa-store", handoff, proof) == target

    changed = json.loads(json.dumps(handoff))
    changed["tasks"][0]["strategy_config"]["lookback"] = 99
    with pytest.raises(StrategyQaTransportError):
        store_verified_handoff(tmp_path / "qa-store", changed, proof)


def test_fast_coordinator_syncs_handoff_before_agent_manager_advance():
    text = Path(".github/workflows/fast-agent-coordinator.yml").read_text(encoding="utf-8")
    sync = "python nexus_strategy_qa_handoff_transport.py"
    advance = "python agent_manager_runner.py --config config/nexus-agent-manager.json"
    assert sync in text
    assert "--store data/agent_coordination/strategy_qa_handoffs" in text
    assert text.index(sync) < text.index(advance)
    assert "actions: write" in text
