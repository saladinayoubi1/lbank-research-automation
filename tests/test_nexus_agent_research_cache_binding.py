from __future__ import annotations

import pytest

import nexus_agent_research_prepare as prepare
from nexus_research_missions import ANCESTRY, EIGHTH, FIRST


SOURCE = "a" * 40
LEDGER = "d" * 64


def successor_payload() -> dict[str, str]:
    values = {
        "research_predecessor_source_sha": "b" * 40,
        "research_predecessor_receipt_digest": "c" * 64,
        "research_predecessor_qa_digest": "e" * 64,
        "research_predecessor_ledger_digest": LEDGER,
        "research_predecessor_mechanism": "lagged_peer_volatility_release",
    }
    assert set(values) == set(ANCESTRY)
    return {"task_id": EIGHTH, **values}


def test_first_research_mission_keeps_bootstrap_source_key():
    assert prepare.research_cache_key({"task_id": FIRST}, SOURCE) == (
        "nexus-composite-inputs-v1-" + SOURCE
    )


def test_successor_cache_key_binds_source_and_qa_attested_ledger():
    assert prepare.research_cache_key(successor_payload(), SOURCE) == (
        "nexus-composite-inputs-v2-" + SOURCE + "-" + LEDGER
    )


def test_successor_cache_key_rejects_missing_or_malformed_frontier():
    payload = successor_payload()
    payload["research_predecessor_ledger_digest"] = "0" * 63
    with pytest.raises(ValueError, match="predecessor attestation"):
        prepare.research_cache_key(payload, SOURCE)


def test_cache_key_rejects_malformed_source():
    with pytest.raises(prepare.ResearchPreparationError, match="source SHA"):
        prepare.research_cache_key({"task_id": FIRST}, "not-a-sha")


def test_architect_rca_inspect_is_not_granted_research_cache_access(monkeypatch):
    monkeypatch.setenv("NEXUS_TASK_PAYLOAD_B64", "opaque")
    monkeypatch.setenv("GITHUB_REPOSITORY", prepare.REPO)
    monkeypatch.setenv("GITHUB_SHA", SOURCE)
    monkeypatch.setattr(
        prepare,
        "decode_payload",
        lambda _: {
            "task_id": EIGHTH,
            "phase": 7,
            "transport": "github-cloud",
            "worker_id": "architect-agent",
        },
    )

    assert prepare._classify("inspect") == (None, "none")
    with pytest.raises(
        prepare.ResearchPreparationError,
        match="untrusted real Research Agent task context",
    ):
        prepare._classify("auto")
