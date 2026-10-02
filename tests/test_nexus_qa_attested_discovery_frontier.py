"""Attacker-oriented tests for sixth QA-authorized historical research frontier."""
from __future__ import annotations
import io
import json
from pathlib import Path
import zipfile

import pytest

import nexus_composite_strategy_research as research
from scripts import nexus_qa_attested_discovery_frontier as selector
from nexus_research_missions import FIFTH


SOURCE = "a" * 40
PRODUCER = "c4b0dea7-6460-48c4-b76e-eb0b67625921"
VERIFIER = "e1016bf9-0fa5-42d6-8627-e9d9131f7fbd"
COORDINATOR_WORKFLOW_ID = 329147254


def zipped(member, obj):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, json.dumps(obj))
    return stream.getvalue()


def mock_proofs(monkeypatch, *, bad_ledger=False, bad_qa=False, no_verified_fifth=False):
    ledger = research.empty_ledger()
    core = {k: v for k, v in ledger.items() if k != "ledger_digest"}
    for config in research.CONFIGS:
        if config["mechanism"] == "relative_momentum_reacceleration" or config["risk_variant"] != 0:
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
        "mechanism": "peer_shock_noncontagion_rebound",
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
        "id": FIFTH, "status": "PENDING" if no_verified_fifth else "DONE",
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
    future = [
        {"id": "P7-RESEARCH-COMPOSITE-006", "status": "PENDING"},
        {"id": "P7-RESEARCH-COMPOSITE-007", "status": "PENDING"},
        {"id": "P7-RESEARCH-COMPOSITE-008", "status": "PENDING"},
    ]
    archive_map = {
        901: zipped("agent_manager_runtime.json", {"tasks": [task, *future]}),
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
        if endpoint.endswith("actions/workflows?per_page=100&page=1"):
            return {"workflows": [{
                "id": COORDINATOR_WORKFLOW_ID,
                "name": "Fast Agent Coordinator",
                "path": selector.COORDINATOR_WORKFLOW_PATH,
                "state": "active",
            }]}
        if endpoint.endswith(f"actions/workflows/{COORDINATOR_WORKFLOW_ID}/runs?branch=main&per_page=12"):
            return {"workflow_runs": [{"id": 1234567, "head_sha": SOURCE,
                     "head_branch": "main", "path": selector.COORDINATOR_WORKFLOW_PATH,
                     "event": "workflow_dispatch", "status": "completed",
                     "conclusion": "success", "created_at": "2026-09-29T00:00:00Z",
                     "repository": {"full_name": selector.REPO},
                     "head_repository": {"full_name": selector.REPO}}]}
        if endpoint.endswith("actions/runs?branch=main&per_page=100&page=1"):
            return {"workflow_runs": []}
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


def test_exact_completed_distinct_qa_proof_selects_fifth_frontier(monkeypatch):
    expected = mock_proofs(monkeypatch)
    result = selector.verified_frontier(selector.REPO)
    assert result["predecessor"] == FIFTH
    assert result["ledger"]["ledger_digest"] == expected["ledger_digest"]
    assert research.select_next(result["ledger"])["mechanism"] == "relative_momentum_reacceleration"
    assert result["producer_artifact_id"] == 902
    assert result["qa_artifact_id"] == 904
    assert result["research_only"] is True and result["auto_demo_promotion"] is False


@pytest.mark.parametrize("variant", ["bad_ledger", "bad_qa", "no_verified_fifth"])
def test_mutated_or_unsigned_proof_cannot_seed_sixth(monkeypatch, variant):
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
    coordinator = Path(".github/workflows/fast-agent-coordinator.yml").read_text()
    discovery = Path(".github/workflows/nexus_multitimeframe_strategy_discovery.yml").read_text()
    coordinator_trigger = coordinator.split("permissions:", 1)[0]
    assert "push:" in coordinator_trigger
    assert "branches: [main]" in coordinator_trigger
    assert "paths:" not in coordinator_trigger
    # The Research workflow still identifies the authority-changing paths that
    # start Discovery, while Coordinator now covers every main SHA rather than
    # duplicating a second, drift-prone path allowlist.
    for required in (
        "scripts/nexus_qa_attested_discovery_frontier.py",
        "nexus_research_missions.py",
        "tests/test_nexus_qa_attested_discovery_frontier.py",
    ):
        assert required in discovery


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
        if endpoint.endswith(f"actions/workflows/{COORDINATOR_WORKFLOW_ID}/runs?branch=main&per_page=12"):
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
        if endpoint.endswith(f"actions/workflows/{COORDINATOR_WORKFLOW_ID}/runs?branch=main&per_page=12"):
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
        selector.REPO, required_task_id=FIFTH,
    )
    assert artifact_id == 901
    assert manager["tasks"][0]["id"] == FIFTH
    assert all(
        task["status"] == "PENDING"
        for task in manager["tasks"][1:]
    )


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
        if endpoint.endswith(f"actions/workflows/{COORDINATOR_WORKFLOW_ID}/runs?branch=main&per_page=12"):
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
        selector.REPO, required_task_id=FIFTH,
    )
    assert artifact_id == 901
    assert manager["tasks"][0]["id"] == FIFTH


def test_bounded_repository_run_fallback_recovers_exact_active_coordinator(monkeypatch):
    mock_proofs(monkeypatch)
    original = selector.api
    monkeypatch.setenv("GITHUB_SHA", "f" * 40)

    def fallback_api(endpoint, *, binary=False):
        if endpoint.endswith(
            f"actions/workflows/{COORDINATOR_WORKFLOW_ID}/runs?branch=main&per_page=12"
        ):
            return {"workflow_runs": []}
        if endpoint.endswith("actions/runs?branch=main&per_page=100&page=1"):
            return {"workflow_runs": [{
                "id": 1234567, "workflow_id": COORDINATOR_WORKFLOW_ID,
                "head_sha": SOURCE, "head_branch": "main",
                "path": selector.COORDINATOR_WORKFLOW_PATH,
                "event": "schedule", "status": "completed", "conclusion": "success",
                "created_at": "2026-09-29T00:00:00Z",
                "repository": {"full_name": selector.REPO},
                "head_repository": {"full_name": selector.REPO},
            }]}
        return original(endpoint, binary=binary)

    monkeypatch.setattr(selector, "api", fallback_api)
    artifact_id, manager = selector.latest_coordinator(
        selector.REPO, required_task_id=FIFTH,
    )
    assert artifact_id == 901
    assert manager["tasks"][0]["id"] == FIFTH


def test_repository_fallback_rejects_same_path_from_wrong_workflow_id(monkeypatch):
    mock_proofs(monkeypatch)
    original = selector.api

    def wrong_identity(endpoint, *, binary=False):
        if endpoint.endswith(
            f"actions/workflows/{COORDINATOR_WORKFLOW_ID}/runs?branch=main&per_page=12"
        ):
            return {"workflow_runs": []}
        if endpoint.endswith("actions/runs?branch=main&per_page=100&page=1"):
            return {"workflow_runs": [{
                "id": 1234567, "workflow_id": COORDINATOR_WORKFLOW_ID + 1,
                "head_sha": SOURCE, "head_branch": "main",
                "path": selector.COORDINATOR_WORKFLOW_PATH,
                "event": "schedule", "status": "completed", "conclusion": "success",
                "created_at": "2026-09-29T00:00:00Z",
                "repository": {"full_name": selector.REPO},
                "head_repository": {"full_name": selector.REPO},
            }]}
        return original(endpoint, binary=binary)

    monkeypatch.setattr(selector, "api", wrong_identity)
    with pytest.raises(selector.QaFrontierError, match="no verified"):
        selector.latest_coordinator(selector.REPO, required_task_id=FIFTH)


def _historical_proofs(monkeypatch, *, tamper_pin=False, untrusted_actor=False,
                       divergent_source=False):
    expected = mock_proofs(monkeypatch)
    original = selector.api
    source_event = "b" * 40
    run_id = 7654321
    receipt = selector.archive_json(
        original(f"repos/{selector.REPO}/actions/artifacts/902/zip", binary=True),
        "result/agent-receipt.json",
    )
    manager = selector.archive_json(
        original(f"repos/{selector.REPO}/actions/artifacts/901/zip", binary=True),
        "agent_manager_runtime.json",
    )
    task = manager["tasks"][0]
    task["research_qa_incident_recovery"] = {
        "reason": "verified_failed_source_epoch_new_independent_qa_only",
        "original_producer_source_sha": SOURCE,
        "original_producer_receipt_digest": receipt["receipt_digest"],
        "original_producer_lease_id": PRODUCER,
        "new_qa_lease_id": VERIFIER,
        "independent_qa_complete": False,
        "automatic_demo_promotion": False,
        "live_enabled": False,
    }
    manager_archive = zipped("agent_manager_runtime.json", manager)
    pin_core = {
        "schema": "nexus.original-source-research-qa-ancestry.v1",
        "repository": selector.REPO, "run_id": str(run_id),
        "trusted_main_event_sha": source_event,
        "verified_main_ancestor_sha": "f" * 40 if tamper_pin else SOURCE,
        "original_source_checkout_verified": True,
        "independent_research_qa_only": True,
        "auto_demo_promotion": False,
        "live_enabled": False,
    }
    pin = {**pin_core, "attestation_sha256": research.digest(pin_core)}
    pin_archive = zipped("pinned-qa-attestation.json", pin)

    def historical_api(endpoint, *, binary=False):
        if binary and endpoint.endswith("actions/artifacts/901/zip"):
            return manager_archive
        if binary and endpoint.endswith("actions/artifacts/905/zip"):
            return pin_archive
        if "actions/artifacts?name=nexus-agent-qa-source-pin-" + VERIFIER in endpoint:
            return {"artifacts": [{
                "name": "nexus-agent-qa-source-pin-" + VERIFIER, "expired": False,
                "id": 905, "workflow_run": {
                    "id": run_id, "head_branch": "main", "head_sha": source_event,
                },
            }]}
        if "actions/artifacts?name=nexus-agent-research-qa-" + VERIFIER in endpoint:
            return {"artifacts": [{
                "name": "nexus-agent-research-qa-" + VERIFIER, "expired": False,
                "id": 904, "workflow_run": {
                    "id": run_id, "head_branch": "main", "head_sha": source_event,
                },
            }]}
        if endpoint.endswith(f"actions/runs/{run_id}"):
            return {
                "id": run_id, "name": "NEXUS Runtime Worker",
                "path": ".github/workflows/nexus-runtime-worker.yml",
                "head_sha": source_event, "head_branch": "main",
                "status": "completed", "conclusion": "success",
                "event": "workflow_dispatch",
                "actor": {"login": "attacker" if untrusted_actor else "github-actions[bot]"},
                "repository": {"full_name": selector.REPO},
                "head_repository": {"full_name": selector.REPO},
            }
        if "compare/" + SOURCE + "..." + source_event in endpoint:
            return {
                "status": "diverged" if divergent_source else "ahead",
                "ahead_by": 1, "behind_by": 0,
                "base_commit": {"sha": SOURCE},
                "merge_base_commit": {"sha": SOURCE},
            }
        return original(endpoint, binary=binary)

    monkeypatch.setattr(selector, "api", historical_api)
    return expected


def test_sixth_frontier_accepts_only_signed_fifth_original_source_qa(monkeypatch):
    expected = _historical_proofs(monkeypatch)
    proof = selector.verified_frontier(selector.REPO)
    assert proof["predecessor"] == FIFTH
    assert proof["ledger"]["ledger_digest"] == expected["ledger_digest"]
    assert proof["qa_artifact_id"] == 904
    assert research.select_next(proof["ledger"])["mechanism"] == (
        "relative_momentum_reacceleration"
    )


@pytest.mark.parametrize("invalid", [
    "tamper_pin", "untrusted_actor", "divergent_source",
])
def test_sixth_frontier_rejects_forgeries_even_with_valid_numeric_qa(monkeypatch, invalid):
    _historical_proofs(monkeypatch, **{invalid: True})
    with pytest.raises(selector.QaFrontierError):
        selector.verified_frontier(selector.REPO)

def test_coordinator_proof_runs_for_every_main_push_to_prevent_source_transition_race():
    text = Path(".github/workflows/fast-agent-coordinator.yml").read_text(encoding="utf-8")
    trigger = text.split("permissions:", 1)[0]
    assert "push:" in trigger
    assert "branches: [main]" in trigger
    # Discovery may be triggered by many Research paths. Coordinator proof must
    # therefore not be path-filtered, otherwise the exact source can exist
    # without any same-SHA durable runtime proof.
    assert "paths:" not in trigger

