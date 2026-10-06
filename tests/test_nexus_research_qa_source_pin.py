"""No cross-source Research QA without an exact main-ancestor checkout."""
from __future__ import annotations

from pathlib import Path
import pytest
import yaml

from nexus_research_missions import FIFTH
from nexus_strategy_independent_qa import digest
from nexus_strategy_review_qa_handoff import qa_task_id
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


def strategy_qa_payload():
    core = {
        "schema_version":"nexus.strategy-review-qa-task.v1",
        "id":qa_task_id("d"*64, OLD, "f"*64),
        "task_kind":"strategy_review_independent_qa","system_map_node":"QA-41",
        "status":"READY_FOR_QA_DISPATCH","source_sha":OLD,
        "proposal_digest":"d"*64,"proposal_result_digest":"e"*64,
        "requalification_digest":"f"*64,"requalification_verification_digest":"1"*64,
        "family":"momentum","timeframe":"hour4","variant_id":"v1",
        "strategy_config":{"lookback":16},"strategy_config_digest":"",
        "runtime_evidence":[
            {
                "symbol":"BTCUSDT","dataset_binding_sha256":"2"*64,
                "pipeline_digest":"3"*64,"qualification_digest":"4"*64,
                "last_open_time_ms":1800000000000,
            },
            {
                "symbol":"ETHUSDT","dataset_binding_sha256":"5"*64,
                "pipeline_digest":"6"*64,"qualification_digest":"7"*64,
                "last_open_time_ms":1800000000000,
            },
        ],
        "producer_role":"strategy-runtime-requalification","required_verifier":"qa-verifier-agent",
        "research_only":True,"paper_only":True,"candidate_creation_authority":False,
        "qualification_authority":False,"promotion_authority":False,
        "paper_execution_authority":False,"automatic_strategy_promotion":False,
        "live_trading_authority":False,
    }
    core["strategy_config_digest"] = digest(core["strategy_config"])
    task = {**core, "task_digest": digest(core)}
    return {
        "task_id":task["id"],"worker_id":"qa-verifier-agent","phase":7,
        "transport":"github-cloud","lease_id":"qa-original-replay-lease",
        "strategy_qa_task":task,
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
    assert cache["with"]["key"] == "${{ steps.inspect-research.outputs.research_cache_key }}"
    assert "research_cache_key=" in inspect["run"] or "nexus_agent_research_prepare --mode inspect" in inspect["run"]
    qa = names["Publish independent numerical QA proof"]
    assert qa["with"]["path"] == "build/agent-research/qa-evidence.json"
    attestation = names["Publish independently bounded original-source QA ancestry attestation"]
    assert attestation["with"]["path"] == "build/pinned-qa-attestation.json"

def test_strategy_qa_requests_exact_source_ancestor_pin():
    decision = select_source(strategy_qa_payload(), **authorized())
    assert decision["execution_source_sha"] == OLD
    assert decision["requested_ancestor_pin"] is True
    assert decision["source_role"] == "independent-strategy-qa"
    assert decision["live_authority"] is False
    assert decision["auto_demo_promotion"] is False


def test_strategy_qa_tampered_task_never_selects_code():
    payload = strategy_qa_payload()
    payload["strategy_qa_task"]["strategy_config"]["lookback"] = 99
    with pytest.raises(ResearchQaPinError, match="task binding"):
        select_source(payload, **authorized())


def _composite_qa_payload():
    return {
        "task_id": "COMPOSITE-QA-" + "d" * 64,
        "worker_id": "qa-verifier-agent",
        "phase": 7,
        "transport": "github-cloud",
        "lease_id": "qa-original-replay-lease",
        "composite_qa_task": {
            "id": "COMPOSITE-QA-" + "d" * 64,
            "task_kind": "composite_runtime_independent_qa",
            "system_map_node": "QA-41",
            "required_verifier": "qa-verifier-agent",
            "source_sha": OLD,
        },
    }


def test_composite_runtime_qa_requests_exact_physical_source_ancestor(monkeypatch):
    monkeypatch.setattr(
        "nexus_composite_runtime_independent_qa.validate_task",
        lambda value, source: dict(value),
    )
    decision = select_source(_composite_qa_payload(), **authorized())
    assert decision["execution_source_sha"] == OLD
    assert decision["requested_ancestor_pin"] is True
    assert decision["source_role"] == "independent-composite-runtime-qa"
    assert decision["live_authority"] is False
    assert decision["auto_demo_promotion"] is False


def test_composite_runtime_qa_tampered_identity_never_selects_code(monkeypatch):
    monkeypatch.setattr(
        "nexus_composite_runtime_independent_qa.validate_task",
        lambda value, source: dict(value),
    )
    payload = _composite_qa_payload()
    payload["composite_qa_task"]["id"] = "COMPOSITE-QA-" + "e" * 64
    with pytest.raises(ResearchQaPinError, match="source identity"):
        select_source(payload, **authorized())
