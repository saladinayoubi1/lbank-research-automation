"""Attacker-oriented tests for fifth QA-authorized historical research frontier."""
from __future__ import annotations
import io
import json
from pathlib import Path
import zipfile

import pytest

import nexus_composite_strategy_research as research
from scripts import nexus_qa_attested_discovery_frontier as selector
from nexus_research_missions import FOURTH


SOURCE = "a" * 40
PRODUCER = "c4b0dea7-6460-48c4-b76e-eb0b67625921"
VERIFIER = "e1016bf9-0fa5-42d6-8627-e9d9131f7fbd"


def zipped(member, obj):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, json.dumps(obj))
    return stream.getvalue()


def mock_proofs(monkeypatch, *, bad_ledger=False, bad_qa=False, no_verified_fourth=False):
    ledger = research.empty_ledger()
    core = {k: v for k, v in ledger.items() if k != "ledger_digest"}
    for config in research.CONFIGS:
        if config["mechanism"] == "peer_shock_noncontagion_rebound" or config["risk_variant"] != 0:
            continue
        core["config_fingerprints_evaluated"].append(research.digest({
            "config": config, "dataset": research.ARCHIVE_SHA256, "contract": research.SCHEMA,
        }))
        core["mechanisms_evaluated"].append(config["mechanism"])
    core["mechanisms_evaluated"] = sorted(set(core["mechanisms_evaluated"]))
    ledger = {**core, "ledger_digest": research.digest(core)}
    receipt_core = {
        "lease_id": PRODUCER, "source_sha": SOURCE,
        "archive_sha256": research.ARCHIVE_SHA256,
        "ledger_digest": ledger["ledger_digest"],
        "prior_ledger_digest": "1" * 64,
        "mechanism": "lagged_peer_impulse_confirmation",
    }
    receipt = {**receipt_core, "receipt_digest": research.digest(receipt_core)}
    qa_core = {
        "lease_id": PRODUCER, "source_sha": SOURCE,
        "producer_receipt_digest": receipt["receipt_digest"],
        "independent_replay_matches": True,
        "auto_demo_promotion": False, "live_enabled": False,
    }
    proof = {**qa_core, "qa_digest": research.digest(qa_core)}
    task = {
        "id": FOURTH, "status": "PENDING" if no_verified_fourth else "DONE",
        "producer": "research-agent", "verifier": "qa-verifier-agent",
        "research_producer_lease_id": PRODUCER, "lease_id": VERIFIER,
        "result_evidence": {
            "executor": "nexus-real-composite-backtest", "source_sha": SOURCE,
            "receipt_digest": receipt["receipt_digest"],
            "ledger_digest": ledger["ledger_digest"],
            "prior_ledger_digest": receipt["prior_ledger_digest"],
            "config_fingerprint": "2" * 64, "mechanism": receipt["mechanism"],
            "independent_qa_complete": False, "auto_demo_promotion": False,
            "live_enabled": False,
        },
        "verification_evidence": {
            "executor": "nexus-independent-composite-numeric-qa",
            "source_sha": SOURCE, "producer_lease_id": PRODUCER,
            "producer_receipt_digest": receipt["receipt_digest"],
            "qa_digest": proof["qa_digest"], "independent_qa_complete": True,
            "auto_demo_promotion": False, "live_enabled": False,
        },
    }
    archive_map = {
        901: zipped("agent_manager_runtime.json", {"tasks": [task]}),
        902: zipped("result/agent-receipt.json", receipt),
        903: zipped("result/novelty-ledger.json", ledger),
        904: zipped("qa-evidence.json", proof),
    }
    if bad_ledger:
        tampered = dict(ledger)
        tampered["mechanisms_evaluated"] = []
        archive_map[903] = zipped("result/novelty-ledger.json", tampered)
    if bad_qa:
        altered = dict(proof)
        altered["independent_replay_matches"] = False
        archive_map[904] = zipped("qa-evidence.json", altered)

    def fake_api(endpoint, *, binary=False):
        if binary:
            return archive_map[int(endpoint.rsplit("/", 2)[-2])]
        if endpoint.endswith("workflows/fast-agent-coordinator.yml/runs?branch=main&per_page=12"):
            return {"workflow_runs": [{"id": 1234567, "head_sha": SOURCE,
                     "head_branch": "main", "path": ".github/workflows/fast-agent-coordinator.yml",
                     "event": "workflow_dispatch", "status": "completed",
                     "conclusion": "success", "created_at": "2026-09-29T00:00:00Z",
                     "repository": {"full_name": selector.REPO},
                     "head_repository": {"full_name": selector.REPO}}]}
        if endpoint.endswith("actions/runs/1234567/artifacts?per_page=30"):
            return {"artifacts": [{"id": 901, "name": "fast-agent-status-1234567",
                     "size_in_bytes": len(archive_map[901]),
                     "created_at": "2026-09-29T00:00:00Z", "expired": False,
                     "workflow_run": {"id": 1234567, "head_sha": SOURCE,
                                      "head_branch": "main"}}]}
        if "artifacts?name=" in endpoint:
            name = endpoint.split("name=")[1].split("&")[0]
            id_ = 904 if name.endswith("-qa-" + VERIFIER) else 902
            return {"artifacts": [{"name": name, "expired": False, "id": id_,
                                   "workflow_run": {"head_sha": SOURCE}}]}
        raise AssertionError("unexpected GitHub proof lookup " + endpoint)
    monkeypatch.setattr(selector, "api", fake_api)
    original = selector.exact_artifact_json

    def fetch_member(repo, name, sha, member):
        if member == "result/novelty-ledger.json":
            assert name == "nexus-agent-research-" + PRODUCER
            assert sha == SOURCE
            return 903, selector.archive_json(archive_map[903], member)
        return original(repo, name, sha, member)
    monkeypatch.setattr(selector, "exact_artifact_json", fetch_member)
    return ledger


def test_exact_completed_distinct_qa_proof_selects_fourth_frontier(monkeypatch):
    expected = mock_proofs(monkeypatch)
    result = selector.verified_frontier(selector.REPO)
    assert result["predecessor"] == FOURTH
    assert result["ledger"]["ledger_digest"] == expected["ledger_digest"]
    assert research.select_next(result["ledger"])["mechanism"] == "peer_shock_noncontagion_rebound"
    assert result["producer_artifact_id"] == 902
    assert result["qa_artifact_id"] == 904
    assert result["research_only"] is True and result["auto_demo_promotion"] is False


@pytest.mark.parametrize("variant", ["bad_ledger", "bad_qa", "no_verified_fourth"])
def test_mutated_or_unsigned_proof_cannot_seed_fifth(monkeypatch, variant):
    mock_proofs(monkeypatch, **{variant: True})
    with pytest.raises(selector.QaFrontierError):
        selector.verified_frontier(selector.REPO)


def test_bounded_proof_archive_rejects_duplicate_member_and_invalid_json():
    obj = zipped("proof.json", {"id": "good"})
    assert selector.archive_json(obj, "proof.json") == {"id": "good"}
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("proof.json", "{}")
        archive.writestr("proof.json", "{}")
    with pytest.raises(selector.QaFrontierError):
        selector.archive_json(stream.getvalue(), "proof.json")
    with pytest.raises(selector.QaFrontierError):
        selector.archive_json(b"bad", "proof.json")


def test_mandatory_fifth_discovery_cache_uses_exact_QA_not_standalone_artifact():
    workflow = Path(".github/workflows/nexus_multitimeframe_strategy_discovery.yml").read_text()
    segment = workflow.split("- name: Bind canonical archive and novelty frontier as one Research lease input", 1)[1].split("- name: Publish immutable approved Research input transport", 1)[0]
    assert "scripts/nexus_qa_attested_discovery_frontier.py" in segment
    assert "cp build/previous-composite/novelty-ledger.json" not in segment
    assert "cp build/composite/novelty-ledger.json" not in segment
    assert "no claimed prior" not in segment


def test_recent_coordinator_proof_rejects_unbound_same_run_artifact(monkeypatch):
    mock_proofs(monkeypatch)
    original = selector.api

    def mismatched(endpoint, *, binary=False):
        result = original(endpoint, binary=binary)
        if endpoint.endswith("actions/runs/1234567/artifacts?per_page=30"):
            result["artifacts"][0]["workflow_run"]["head_sha"] = "f" * 40
        return result

    monkeypatch.setattr(selector, "api", mismatched)
    with pytest.raises(selector.QaFrontierError, match="bind"):
        selector.latest_coordinator(selector.REPO)


def test_recent_coordinator_proof_does_not_accept_failed_run(monkeypatch):
    mock_proofs(monkeypatch)
    original = selector.api

    def failed(endpoint, *, binary=False):
        result = original(endpoint, binary=binary)
        if endpoint.endswith("workflows/fast-agent-coordinator.yml/runs?branch=main&per_page=12"):
            result["workflow_runs"][0]["conclusion"] = "failure"
        return result

    monkeypatch.setattr(selector, "api", failed)
    with pytest.raises(selector.QaFrontierError, match="no verified"):
        selector.latest_coordinator(selector.REPO)
