"""Attacker-oriented tests for seventh QA-authorized historical research frontier."""
from __future__ import annotations
import io
import json
from pathlib import Path
import zipfile

import pytest

import nexus_composite_strategy_research as research
from scripts import nexus_qa_attested_discovery_frontier as selector
from nexus_research_missions import FIFTH, SIXTH


SOURCE = "a" * 40
PRODUCER = "c4b0dea7-6460-48c4-b76e-eb0b67625921"
VERIFIER = "e1016bf9-0fa5-42d6-8627-e9d9131f7fbd"


def zipped(member, obj):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, json.dumps(obj))
    return stream.getvalue()


def mock_proofs(monkeypatch, *, bad_ledger=False, bad_qa=False, no_verified_sixth=False):
    ledger = research.empty_ledger()
    core = {k: v for k, v in ledger.items() if k != "ledger_digest"}
    for config in research.CONFIGS:
        if config["mechanism"] == "lagged_peer_volatility_spillover_breakout" or config["risk_variant"] != 0:
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
        "mechanism": "relative_momentum_reacceleration",
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
        "id": SIXTH, "status": "PENDING" if no_verified_sixth else "DONE",
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


def test_exact_completed_distinct_qa_proof_selects_sixth_frontier(monkeypatch):
    expected = mock_proofs(monkeypatch)
    result = selector.verified_frontier(selector.REPO)
    assert result["predecessor"] == SIXTH
    assert result["ledger"]["ledger_digest"] == expected["ledger_digest"]
    assert research.select_next(result["ledger"])["mechanism"] == "lagged_peer_volatility_spillover_breakout"
    assert result["producer_artifact_id"] == 902
    assert result["qa_artifact_id"] == 904
    assert result["research_only"] is True and result["auto_demo_promotion"] is False


@pytest.mark.parametrize("variant", ["bad_ledger", "bad_qa", "no_verified_sixth"])
def test_mutated_or_unsigned_proof_cannot_seed_seventh(monkeypatch, variant):
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


def test_coordinator_rebuilds_on_research_frontier_authority_changes():
    workflow = Path(".github/workflows/fast-agent-coordinator.yml").read_text()
    for required in (
        "scripts/nexus_qa_attested_discovery_frontier.py",
        "nexus_research_missions.py",
        "tests/test_nexus_qa_attested_discovery_frontier.py",
    ):
        assert required in workflow


def test_mandatory_seventh_discovery_cache_uses_exact_QA_not_standalone_artifact():
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


def test_frontier_prefers_exact_current_source_over_newer_stale_coordinator(monkeypatch):
    mock_proofs(monkeypatch)
    original = selector.api
    monkeypatch.setenv("GITHUB_SHA", SOURCE)

    def raced(endpoint, *, binary=False):
        result = original(endpoint, binary=binary)
        if endpoint.endswith("workflows/fast-agent-coordinator.yml/runs?branch=main&per_page=12"):
            result["workflow_runs"].append({
                "id": 9999999, "head_sha": "b" * 40, "head_branch": "main",
                "path": ".github/workflows/fast-agent-coordinator.yml",
                "event": "schedule", "status": "completed", "conclusion": "success",
                "created_at": "2026-09-29T00:05:00Z",
                "repository": {"full_name": selector.REPO},
                "head_repository": {"full_name": selector.REPO},
            })
        if endpoint.endswith("actions/runs/9999999/artifacts?per_page=30"):
            raise AssertionError("stale-source Coordinator must not outrank exact current source")
        return result

    monkeypatch.setattr(selector, "api", raced)
    artifact_id, manager = selector.latest_coordinator(
        selector.REPO, required_task_id=SIXTH,
    )
    assert artifact_id == 901
    assert [t["id"] for t in manager["tasks"]] == [SIXTH]


def test_frontier_skips_schema_lag_snapshot_missing_required_predecessor(monkeypatch):
    mock_proofs(monkeypatch)
    original = selector.api
    monkeypatch.setenv("GITHUB_SHA", SOURCE)
    empty_manager = zipped("agent_manager_runtime.json", {"tasks": []})

    def raced(endpoint, *, binary=False):
        if binary and endpoint.endswith("actions/artifacts/906/zip"):
            return empty_manager
        if endpoint.endswith("actions/runs/2222222/artifacts?per_page=30"):
            return {"artifacts": [{
                "id": 906, "name": "fast-agent-status-2222222",
                "size_in_bytes": len(empty_manager), "expired": False,
                "workflow_run": {"id": 2222222, "head_sha": SOURCE,
                                 "head_branch": "main"},
            }]}
        result = original(endpoint, binary=binary)
        if endpoint.endswith("workflows/fast-agent-coordinator.yml/runs?branch=main&per_page=12"):
            result["workflow_runs"].append({
                "id": 2222222, "head_sha": SOURCE, "head_branch": "main",
                "path": ".github/workflows/fast-agent-coordinator.yml",
                "event": "push", "status": "completed", "conclusion": "success",
                "created_at": "2026-09-29T00:05:00Z",
                "repository": {"full_name": selector.REPO},
                "head_repository": {"full_name": selector.REPO},
            })
        return result

    monkeypatch.setattr(selector, "api", raced)
    artifact_id, manager = selector.latest_coordinator(
        selector.REPO, required_task_id=SIXTH,
    )
    assert artifact_id == 901
    assert manager["tasks"][0]["id"] == SIXTH



def _historical_fifth_qa_inputs(monkeypatch, *, tamper_pin=False,
                                untrusted_actor=False, divergent_source=False):
    source = "d" * 40
    producer = "5f0f4c58-7f2f-42a1-b7d9-3cc47a9ef111"
    verifier = "5f0f4c58-7f2f-42a1-b7d9-3cc47a9ef222"
    receipt_digest = "1" * 64
    source_event = "e" * 40
    run_id = 7654321
    task = {
        "id": FIFTH,
        "research_qa_incident_recovery": {
            "reason": "verified_failed_source_epoch_new_independent_qa_only",
            "original_producer_source_sha": source,
            "original_producer_receipt_digest": receipt_digest,
            "original_producer_lease_id": producer,
            "new_qa_lease_id": verifier,
            "independent_qa_complete": False,
            "automatic_demo_promotion": False,
            "live_enabled": False,
        },
    }
    pin_core = {
        "schema": "nexus.original-source-research-qa-ancestry.v1",
        "repository": selector.REPO,
        "run_id": str(run_id),
        "trusted_main_event_sha": source_event,
        "verified_main_ancestor_sha": "f" * 40 if tamper_pin else source,
        "original_source_checkout_verified": True,
        "independent_research_qa_only": True,
        "auto_demo_promotion": False,
        "live_enabled": False,
    }
    pin = {**pin_core, "attestation_sha256": research.digest(pin_core)}
    proof = {
        "schema": "nexus.independent-research-qa.v1",
        "source_sha": source,
        "producer_receipt_digest": receipt_digest,
        "independent_replay_matches": True,
        "auto_demo_promotion": False,
        "live_enabled": False,
    }
    pin_archive = zipped("pinned-qa-attestation.json", pin)
    proof_archive = zipped("qa-evidence.json", proof)

    def historical_api(endpoint, *, binary=False):
        if binary and endpoint.endswith("actions/artifacts/905/zip"):
            return pin_archive
        if binary and endpoint.endswith("actions/artifacts/904/zip"):
            return proof_archive
        if "actions/artifacts?name=nexus-agent-research-qa-" + verifier in endpoint:
            return {"artifacts": [{
                "name": "nexus-agent-research-qa-" + verifier,
                "expired": False, "id": 904,
                "workflow_run": {
                    "id": run_id, "head_branch": "main", "head_sha": source_event,
                },
            }]}
        if "actions/artifacts?name=nexus-agent-qa-source-pin-" + verifier in endpoint:
            return {"artifacts": [{
                "name": "nexus-agent-qa-source-pin-" + verifier,
                "expired": False, "id": 905,
                "workflow_run": {
                    "id": run_id, "head_branch": "main", "head_sha": source_event,
                },
            }]}
        if endpoint.endswith(f"actions/runs/{run_id}"):
            return {
                "id": run_id,
                "name": "NEXUS Runtime Worker",
                "path": ".github/workflows/nexus-runtime-worker.yml",
                "head_sha": source_event,
                "head_branch": "main",
                "status": "completed",
                "conclusion": "success",
                "event": "workflow_dispatch",
                "actor": {"login": "attacker" if untrusted_actor else "github-actions[bot]"},
                "repository": {"full_name": selector.REPO},
                "head_repository": {"full_name": selector.REPO},
            }
        if "compare/" + source + "..." + source_event in endpoint:
            return {
                "status": "diverged" if divergent_source else "ahead",
                "ahead_by": 1,
                "behind_by": 0,
                "base_commit": {"sha": source},
                "merge_base_commit": {"sha": source},
            }
        raise AssertionError("unexpected historical QA lookup " + endpoint)

    monkeypatch.setattr(selector, "api", historical_api)
    return task, source, producer, receipt_digest, verifier, proof


def test_legacy_fifth_original_source_qa_recovery_stays_strict(monkeypatch):
    task, source, producer, receipt_digest, verifier, expected = (
        _historical_fifth_qa_inputs(monkeypatch)
    )
    artifact_id, proof = selector._independently_pinned_historical_qa(
        selector.REPO, task, source, producer, receipt_digest, verifier
    )
    assert artifact_id == 904
    assert proof == expected


@pytest.mark.parametrize("invalid", [
    "tamper_pin", "untrusted_actor", "divergent_source",
])
def test_legacy_fifth_qa_recovery_rejects_forged_ancestry(monkeypatch, invalid):
    kwargs = {invalid: True}
    task, source, producer, receipt_digest, verifier, _ = (
        _historical_fifth_qa_inputs(monkeypatch, **kwargs)
    )
    with pytest.raises(selector.QaFrontierError):
        selector._independently_pinned_historical_qa(
            selector.REPO, task, source, producer, receipt_digest, verifier
        )
