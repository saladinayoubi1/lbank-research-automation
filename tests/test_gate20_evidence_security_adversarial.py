from __future__ import annotations

import copy
import hashlib
import json

import pytest

from gate20_ai_room_evidence import augment_gate20_evidence
from gate20_evidence_security import verify_gate20_evidence_strict
from phase4_e2e import Phase4E2EError, run_phase4_gate20, verify_gate20_evidence


SOURCE_SHA = "1" * 40


def _reseal(evidence):
    candidate = copy.deepcopy(evidence)
    candidate.pop("evidence_digest", None)
    payload = json.dumps(
        candidate,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    candidate["evidence_digest"] = hashlib.sha256(payload).hexdigest()
    return candidate


def _evidence(tmp_path):
    base = run_phase4_gate20(SOURCE_SHA, tmp_path / "source")
    return augment_gate20_evidence(base, tmp_path / "source" / "ai-room")


def test_recomputed_top_level_digest_cannot_forge_pipeline_state(tmp_path):
    evidence = _evidence(tmp_path)
    tampered = copy.deepcopy(evidence)
    tampered["pipeline"]["state_digest"] = "f" * 64
    tampered["dashboard"]["state_digest"] = "f" * 64
    tampered = _reseal(tampered)

    verify_gate20_evidence(tampered, expected_source_sha=SOURCE_SHA)

    with pytest.raises(Phase4E2EError, match="independent exact-SHA rerun"):
        verify_gate20_evidence_strict(
            tampered,
            expected_source_sha=SOURCE_SHA,
            verification_workspace=tmp_path / "independent",
        )


def test_recomputed_digest_cannot_forge_risk_decision_claim(tmp_path):
    evidence = _evidence(tmp_path)
    tampered = copy.deepcopy(evidence)
    tampered["pipeline"]["risk_allowed"] = False
    tampered["pipeline"]["risk_reason_code"] = "attacker_override"
    tampered = _reseal(tampered)

    verify_gate20_evidence(tampered, expected_source_sha=SOURCE_SHA)
    with pytest.raises(Phase4E2EError, match="Risk claim"):
        verify_gate20_evidence_strict(
            tampered,
            expected_source_sha=SOURCE_SHA,
            verification_workspace=tmp_path / "independent",
        )


def test_recomputed_digest_cannot_forge_bounded_ai_authority(tmp_path):
    evidence = _evidence(tmp_path)
    tampered = copy.deepcopy(evidence)
    tampered["ai_control"]["workflow_authority"] = 4
    tampered = _reseal(tampered)

    verify_gate20_evidence(tampered, expected_source_sha=SOURCE_SHA)
    with pytest.raises(Phase4E2EError, match="bounded AI workflow"):
        verify_gate20_evidence_strict(
            tampered,
            expected_source_sha=SOURCE_SHA,
            verification_workspace=tmp_path / "independent",
        )


def test_recomputed_digest_cannot_forge_interactive_ai_room_execution(tmp_path):
    evidence = _evidence(tmp_path)
    tampered = copy.deepcopy(evidence)
    tampered["ai_room"]["orchestration"]["executed"] = False
    tampered = _reseal(tampered)

    verify_gate20_evidence(tampered, expected_source_sha=SOURCE_SHA)
    with pytest.raises(Phase4E2EError, match="AI Room orchestration"):
        verify_gate20_evidence_strict(
            tampered,
            expected_source_sha=SOURCE_SHA,
            verification_workspace=tmp_path / "independent",
        )


def test_valid_exact_sha_evidence_passes_independent_security_rerun(tmp_path):
    evidence = _evidence(tmp_path)
    verified = verify_gate20_evidence_strict(
        evidence,
        expected_source_sha=SOURCE_SHA,
        verification_workspace=tmp_path / "independent",
    )
    assert verified["source_sha"] == SOURCE_SHA
    assert verified["pipeline"]["risk_allowed"] is True
    assert verified["security"]["live_authority_available"] is False
    assert verified["ai_room"]["orchestration"]["executed"] is True
    assert verified["ai_room"]["orchestration"]["state_mutation"] is False
