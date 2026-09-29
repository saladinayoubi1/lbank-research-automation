"""Transport contract tests: distinguish private owner checkpoint from missing state."""
from copy import deepcopy

import pytest

from scripts.nexus_paper_boundary_transport import TransportError, choose

RUN = "36587920304"
SOURCE = "599958ff41158b5c4a370884c9eaab81f2620b7a"
DIGEST = "a" * 64

def owner_jobs():
    names = (
        "Restore owner-controlled Paper checkpoint in primary mode",
        "Independently enforce Paper authority and mission truth",
        "Package Paper state for hosted artifact persistence",
        "Commit owner-controlled Paper checkpoint when enabled",
    )
    steps = [{"name": s, "conclusion": "success"} for s in names]
    steps.append({"name": "Restore newest persistent Paper state",
                  "conclusion": "skipped"})
    return {"total_count": 2, "jobs": [
        {"name": "paper-loop", "run_id": int(RUN), "conclusion": "success",
         "steps": steps},
        {"name": "persist-state", "run_id": int(RUN), "conclusion": "skipped"},
    ]}

def no_artifacts():
    return {"total_count": 0, "artifacts": []}


def public_artifact():
    row = {"name": "nexus-persistent-paper-trading-state",
           "id": 11000000000, "expired": False, "digest": "sha256:" + DIGEST,
           "workflow_run": {"id": int(RUN), "head_branch": "main",
                            "head_sha": SOURCE}}
    return {"total_count": 1, "artifacts": [row]}


def test_owner_primary_without_public_artifact_is_explicitly_not_dispatched():
    result = choose(no_artifacts(), owner_jobs(), RUN, SOURCE)
    assert result["mode"] == "owner_checkpoint_primary_no_public_artifact"
    assert result["discovery_dispatch"] is False
    assert result["artifact_id"] == ""


def test_exact_public_artifact_is_digest_and_source_bound():
    result = choose(public_artifact(), owner_jobs(), RUN, SOURCE)
    assert result["mode"] == "public_artifact"
    assert result["artifact_sha256"] == DIGEST
    assert result["artifact_id"] == "11000000000"
    assert choose(public_artifact(), owner_jobs(), RUN, SOURCE,
                  requested_id="11000000000", requested_digest=DIGEST) == result

@pytest.mark.parametrize("mutation", [
    lambda jobs: jobs["jobs"][0].update(conclusion="failure"),
    lambda jobs: jobs["jobs"][1].update(conclusion="success"),
    lambda jobs: jobs["jobs"][0]["steps"][0].update(conclusion="skipped"),
    lambda jobs: jobs["jobs"][0]["steps"][-1].update(conclusion="success"),
    lambda jobs: jobs["jobs"][0].update(run_id=123456789),
])
def test_private_fallback_fails_closed_without_complete_owner_proof(mutation):
    jobs = owner_jobs()
    mutation(jobs)
    with pytest.raises(TransportError):
        choose(no_artifacts(), jobs, RUN, SOURCE)


def test_public_artifact_rejects_stale_source_bad_digest_and_expiry():
    for change in ("source", "expired", "digest"):
        artifacts = public_artifact()
        row = artifacts["artifacts"][0]
        if change == "source":
            row["workflow_run"]["head_sha"] = "0" * 40
        elif change == "expired":
            row["expired"] = True
        else:
            row["digest"] = "sha256:not-a-valid-digest"
        with pytest.raises(TransportError):
            choose(artifacts, owner_jobs(), RUN, SOURCE)


def test_explicit_recovery_cannot_be_satisfied_by_private_mode():
    with pytest.raises(TransportError):
        choose(no_artifacts(), owner_jobs(), RUN, SOURCE,
               requested_id="11000000000", requested_digest=DIGEST)

def test_explicit_recovery_digest_mismatch_is_rejected():
    with pytest.raises(TransportError):
        choose(public_artifact(), owner_jobs(), RUN, SOURCE,
               requested_id="11000000000", requested_digest="0" * 64)


def test_missing_artifact_without_verified_owner_checkpoint_is_error():
    with pytest.raises(TransportError):
        choose(no_artifacts(), {"total_count": 0, "jobs": []}, RUN, SOURCE)


def test_artifact_enumeration_must_be_complete_and_unambiguous():
    value = public_artifact()
    value["total_count"] = 101
    with pytest.raises(TransportError):
        choose(value, owner_jobs(), RUN, SOURCE)
    value = public_artifact()
    value["artifacts"] *= 2
    with pytest.raises(TransportError):
        choose(value, owner_jobs(), RUN, SOURCE)

def test_workflow_transparently_skips_private_hosted_boundary():
    workflow = (
        __import__("pathlib").Path(".github/workflows/nexus_paper_boundary_discovery_feedback.yml")
        .read_text(encoding="utf-8")
    )
    assert "Resolve exact Paper transport without reading private checkpoint on GitHub" in workflow
    assert "scripts/nexus_paper_boundary_transport.py" in workflow
    assert "tests/test_nexus_paper_boundary_transport.py" in workflow
    assert "if: steps.transport.outputs.mode == 'public_artifact'" in workflow
    assert "should_dispatch: ${{ steps.health.outputs.should_dispatch || 'false' }}" in workflow
    assert "NOT DISPATCHED" in workflow
    assert "runs-on: nexus-bybit-network" in workflow
