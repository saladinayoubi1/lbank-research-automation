"""No cross-source Research QA without an exact main-ancestor checkout."""
from __future__ import annotations

from pathlib import Path
import pytest
import yaml

from nexus_research_missions import FIFTH
from scripts.nexus_research_qa_source_pin import (
    REPO, ResearchQaPinError, select_source,
)

OLD = "a" * 40
CURRENT = "b" * 40
RECEIPT = "c" * 64


def qa_payload():
    return {
        "task_id": FIFTH,
        "worker_id": "qa-verifier-agent",
        "phase": 7,
        "transport": "github-cloud",
        "lease_id": "qa-original-replay-lease",
        "research_producer_source_sha": OLD,
        "research_producer_receipt_digest": RECEIPT,
        "research_producer_lease_id": "producer-original-lease",
    }


def authorized():
    return dict(
        repository=REPO, main_sha=CURRENT, ref_name="main",
        default_branch="main", actor="authorized-owner",
        owner="authorized-owner", input_lease="qa-original-replay-lease",
        input_transport="github-cloud",
    )


def test_only_original_research_qa_requests_ancestor_pin():
    decision = select_source(qa_payload(), **authorized())
    assert decision["requested_ancestor_pin"] is True
    assert decision["execution_source_sha"] == OLD
    assert decision["source_role"] == "independent-research-qa"
    assert decision["live_authority"] is False
    assert decision["auto_demo_promotion"] is False


def test_same_source_qa_does_not_change_checkout():
    p = qa_payload()
    p["research_producer_source_sha"] = CURRENT
    result = select_source(p, **authorized())
    assert result["execution_source_sha"] == CURRENT
    assert result["requested_ancestor_pin"] is False


def test_generic_cloud_worker_never_pins_old_code():
    p = qa_payload()
    p.update(task_id="P4-MGR-001", phase=4, worker_id="developer-agent")
    result = select_source(p, **authorized())
    assert result["execution_source_sha"] == CURRENT
    assert result["requested_ancestor_pin"] is False


@pytest.mark.parametrize("field,value", [
    ("research_producer_source_sha", "z" * 40),
    ("research_producer_receipt_digest", "c" * 63),
    ("research_producer_lease_id", ""),
    ("phase", 4),
])
def test_unbound_or_malformed_producer_never_selects_code(field, value):
    p = qa_payload()
    p[field] = value
    with pytest.raises(ResearchQaPinError):
        select_source(p, **authorized())


@pytest.mark.parametrize("field,value", [
    ("repository", "attacker/untrusted-repo"),
    ("ref_name", "attacker-branch"),
    ("default_branch", "not-main"),
    ("main_sha", "not-a-source-sha"),
    ("actor", "untrusted-contributor"),
    ("input_lease", "unrelated-qa-lease"),
    ("input_transport", "windows"),
])
def test_untrusted_execution_context_cannot_select_historical_code(field, value):
    ctx = authorized()
    ctx[field] = value
    with pytest.raises(ResearchQaPinError):
        select_source(qa_payload(), **ctx)


def test_workflow_pins_only_verified_main_ancestry_and_restores_original_cache():
    text = Path(".github/workflows/nexus-runtime-worker.yml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    assert data["permissions"] == {"contents": "read"}
    steps = data["jobs"]["preflight"]["steps"]
    names = {s.get("name"): s for s in steps if isinstance(s, dict)}
    pin = names["Validate and pin original main ancestor for Research QA only"]
    script = pin["run"]
    assert "python -m scripts.nexus_research_qa_source_pin" in script
    assert 'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"' in script
    assert "git fetch --no-tags --deepen=80 origin main" in script
    assert 'git cat-file -e "$source_sha^{commit}"' in script
    assert 'git merge-base --is-ancestor "$source_sha" "$GITHUB_SHA"' in script
    assert 'git checkout --detach "$source_sha"' in script
    assert script.index("git merge-base --is-ancestor") < script.index("git checkout --detach")
    assert 'test "$(git rev-parse HEAD)" = "$source_sha"' in script
    assert "auto_demo_promotion" in script and "live_enabled" in script
    assert "gh api" not in script and "git fetch origin \"$source_sha\"" not in script
    inspect = names["Inspect authorized real Research Agent lease before expensive cache restores"]
    prepare = names["Prepare verified cached archive and exact frontier for Research or independent QA"]
    execute = names["Execute bounded cloud task"]
    for step in (inspect, prepare, execute):
        assert step["env"]["NEXUS_TASK_PAYLOAD_B64"] == "${{ github.event.inputs.payload_b64 }}"
        assert step["env"]["NEXUS_EXECUTION_SOURCE_SHA"] == "${{ steps.pin-research-qa.outputs.execution_source_sha }}"
        assert 'GITHUB_SHA="$NEXUS_EXECUTION_SOURCE_SHA" python ' in step["run"]
    cache = names["Restore immutable approved Bybit Research input transport"]
    assert "steps.pin-research-qa.outputs.execution_source_sha" in cache["with"]["key"]
    qa = names["Publish independent numerical QA proof"]
    assert qa["with"]["path"] == "build/agent-research/qa-evidence.json"
    attestation = names["Publish independently bounded original-source QA ancestry attestation"]
    assert attestation["with"]["path"] == "build/pinned-qa-attestation.json"
