from __future__ import annotations

from copy import deepcopy

import pytest

import phase5_attempts as attempts
import phase5_mission_contract as mc
import phase5_verification as verification

SOURCE_SHA = "a" * 64
CHECK_SHA = "c" * 64
ARTIFACT_SHA = "d" * 64


def mission(mode="independent_trust_domain"):
    return {
        "schema_version": mc.MISSION_SCHEMA,
        "mission_id": "verify-test",
        "mission_revision": 2,
        "phase": 5,
        "policy": {"version": "p2", "max_parallel_tasks": 2},
        "workers": [
            {
                "id": "producer",
                "trust_domain": "github-cloud",
                "capabilities": ["implementation"],
                "resources": ["github-cloud"],
                "authority_max": 3,
                "enabled": True,
                "verifier": False,
            },
            {
                "id": "qa-same-domain",
                "trust_domain": "github-cloud",
                "capabilities": ["integration_tests"],
                "resources": ["github-cloud"],
                "authority_max": 3,
                "enabled": True,
                "verifier": True,
            },
            {
                "id": "windows-verifier",
                "trust_domain": "windows-local",
                "capabilities": ["integration_tests"],
                "resources": ["windows-local"],
                "authority_max": 3,
                "enabled": True,
                "verifier": True,
            },
        ],
        "tasks": [
            {
                "id": "T1",
                "title": "verify",
                "phase": 5,
                "gate": 4,
                "status": "RUNNING",
                "priority": 1,
                "dependencies": [],
                "required_capabilities": ["implementation"],
                "preferred_resources": ["github-cloud"],
                "authority": 1,
                "acceptance": ["typed evidence"],
                "verification": {"mode": mode, "required_capabilities": ["integration_tests"]},
            }
        ],
    }


def prepared(mode="independent_trust_domain"):
    config = mc.to_agent_manager_config(mission(mode))
    task = config["tasks"][0]
    attempt = attempts.begin_attempt(
        task,
        worker_id="producer",
        lease_id="lease-1",
        source_sha=SOURCE_SHA,
        state_generation=3,
    )
    result = attempts.build_result(attempt, outcome="success", evidence={"tests": "green"})
    assert attempts.accept_result(task, result) is True
    return config, task, result


def checks(passed=True):
    return [{"name": "independent-test", "passed": passed, "evidence_sha256": CHECK_SHA}]


def artifacts():
    return [{"kind": "test-report", "name": "report.json", "sha256": ARTIFACT_SHA}]


def test_cross_domain_policy_rejects_same_domain_alias():
    config, task, _ = prepared()
    assert verification.eligible_verifiers(config, task, "producer") == ["windows-verifier"]

    with pytest.raises(verification.VerificationError, match="does not satisfy"):
        verification.build_verification_manifest(
            config,
            task,
            attempts.build_result(
                task["attempt_history"][0], outcome="success", evidence={"tests": "green"}
            ),
            verifier_id="qa-same-domain",
            checks=checks(),
            artifacts=artifacts(),
        )


def test_independent_worker_policy_allows_different_worker_in_same_domain():
    config, task, result = prepared("independent_worker")
    assert verification.eligible_verifiers(config, task, "producer") == ["qa-same-domain", "windows-verifier"]
    manifest = verification.build_verification_manifest(
        config, task, result, verifier_id="qa-same-domain", checks=checks(), artifacts=artifacts()
    )
    assert manifest["verification_mode"] == "independent_worker"


def test_pass_manifest_binds_current_attempt_and_marks_done():
    config, task, result = prepared()
    manifest = verification.build_verification_manifest(
        config, task, result, verifier_id="windows-verifier", checks=checks(), artifacts=artifacts()
    )
    assert manifest["decision"] == "pass"
    assert manifest["attempt_id"] == task["active_attempt_id"]
    assert manifest["fence_generation"] == task["fence_generation"]
    assert manifest["source_sha"] == SOURCE_SHA
    assert manifest["spec_digest"] == task["spec_digest"]
    assert manifest["producer"]["trust_domain"] == "github-cloud"
    assert manifest["verifier"]["trust_domain"] == "windows-local"

    assert verification.accept_verification(config, task, result, manifest) is True
    assert task["status"] == "DONE"
    assert task["verification_evidence"]["manifest_digest"]
    assert verification.accept_verification(config, task, result, deepcopy(manifest)) is False


def test_failed_independent_check_never_marks_done():
    config, task, result = prepared()
    manifest = verification.build_verification_manifest(
        config, task, result, verifier_id="windows-verifier", checks=checks(False), artifacts=artifacts()
    )
    assert manifest["decision"] == "fail"
    verification.accept_verification(config, task, result, manifest)
    assert task["status"] == "BLOCKED"
    assert task["blocked_reason"] == "independent_verification_failed"


def test_source_spec_artifact_and_check_substitution_fail_closed():
    config, task, result = prepared()
    manifest = verification.build_verification_manifest(
        config, task, result, verifier_id="windows-verifier", checks=checks(), artifacts=artifacts()
    )

    for field, replacement in (("source_sha", "e" * 64), ("spec_digest", "f" * 64)):
        candidate = deepcopy(manifest)
        candidate[field] = replacement
        with pytest.raises(verification.VerificationError):
            verification.accept_verification(config, deepcopy(task), result, candidate)

    candidate = deepcopy(manifest)
    candidate["artifacts"][0]["sha256"] = "e" * 64
    with pytest.raises(verification.VerificationError):
        verification.accept_verification(config, deepcopy(task), result, candidate)

    candidate = deepcopy(manifest)
    candidate["checks"][0]["passed"] = False
    with pytest.raises(verification.VerificationError):
        verification.accept_verification(config, deepcopy(task), result, candidate)


def test_registry_trust_domain_change_invalidates_manifest():
    config, task, result = prepared()
    manifest = verification.build_verification_manifest(
        config, task, result, verifier_id="windows-verifier", checks=checks(), artifacts=artifacts()
    )
    changed = deepcopy(config)
    for worker in changed["workers"]:
        if worker["id"] == "windows-verifier":
            worker["trust_domain"] = "github-cloud"

    with pytest.raises(verification.VerificationError):
        verification.accept_verification(changed, deepcopy(task), result, manifest)


def test_conflicting_second_verification_is_rejected():
    config, task, result = prepared()
    first = verification.build_verification_manifest(
        config, task, result, verifier_id="windows-verifier", checks=checks(), artifacts=artifacts()
    )
    verification.accept_verification(config, task, result, first)

    second = deepcopy(first)
    second["checks"] = [{"name": "second", "passed": True, "evidence_sha256": "e" * 64}]
    second["checks_digest"] = verification._digest(second["checks"])
    with pytest.raises(verification.VerificationConflict):
        verification.accept_verification(config, task, result, second)


def test_owner_required_task_has_no_autonomous_verifier():
    cfg = mission("independent_worker")
    cfg["tasks"][0]["authority"] = 4
    cfg["tasks"][0]["verification"] = {"mode": "owner_required", "required_capabilities": []}
    config = mc.to_agent_manager_config(cfg)
    task = config["tasks"][0]
    assert verification.eligible_verifiers(config, task, "producer") == []
    with pytest.raises(attempts.AttemptError, match="L4"):
        attempts.begin_attempt(task, worker_id="producer", lease_id="l", source_sha=SOURCE_SHA, state_generation=0)


def test_verification_policy_is_bound_into_gate1_spec_digest():
    a = mission("independent_worker")
    b = mission("independent_trust_domain")
    first = mc.validate_and_materialize(a)["tasks"][0]["spec_digest"]
    second = mc.validate_and_materialize(b)["tasks"][0]["spec_digest"]
    assert first != second
