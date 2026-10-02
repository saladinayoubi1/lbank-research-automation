from __future__ import annotations

from pathlib import Path

import agent_manager_runner as gate
import agent_transport
import nexus_agent_research_prepare as prepare

SOURCE = "a" * 40
LEDGER = "c" * 64
REPO = "saladinayoubi1/lbank-research-automation"


def _successor_config(*, requested_key: str | None = None):
    first = {"id": gate.FIRST, "status": "DONE"}
    successor_id = next(iter(gate.PREDECESSOR))
    successor = {
        "id": successor_id,
        "status": "BLOCKED",
        "blocked_reason": gate.RESEARCH_WAIT,
        "research_predecessor_ledger_digest": LEDGER,
    }
    if requested_key is not None:
        successor["research_cache_requested_key"] = requested_key
    return {"tasks": [first, successor]}


def _ctx(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    monkeypatch.setenv("GITHUB_SHA", SOURCE)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GH_TOKEN", "test-mocked-do-not-call-network")


def test_successor_cache_identity_includes_exact_qa_ledger_digest():
    config = _successor_config()
    expected = gate.RESEARCH_FRONTIER_CACHE_PREFIX + SOURCE + "-" + LEDGER
    assert gate._research_cache_key(config, SOURCE) == expected


def test_bootstrap_cache_identity_remains_source_only():
    config = {"tasks": [{"id": gate.FIRST, "status": "BLOCKED"}]}
    assert gate._research_cache_key(config, SOURCE) == gate.RESEARCH_CACHE_PREFIX + SOURCE


def test_successor_readiness_rejects_stale_source_only_cache(monkeypatch):
    _ctx(monkeypatch)
    config = _successor_config()
    exact = gate.RESEARCH_FRONTIER_CACHE_PREFIX + SOURCE + "-" + LEDGER

    monkeypatch.setattr(agent_transport, "_api", lambda *a, **kw: {
        "actions_caches": [{
            "key": gate.RESEARCH_CACHE_PREFIX + SOURCE,
            "ref": "refs/heads/main",
            "size_in_bytes": 1234,
        }]
    })
    assert gate.research_cache_status(config) == (
        False, "source_exact_transport_cache_absent"
    )

    monkeypatch.setattr(agent_transport, "_api", lambda *a, **kw: {
        "actions_caches": [{
            "key": exact,
            "ref": "refs/heads/main",
            "size_in_bytes": 1234,
        }]
    })
    assert gate.research_cache_status(config) == (
        True, "source_exact_transport_cache_present"
    )


def test_old_successful_same_source_run_does_not_block_new_frontier_dispatch(monkeypatch):
    _ctx(monkeypatch)
    config = _successor_config()
    calls = []

    def api(method, url, payload=None):
        calls.append((method, url, payload))
        if method == "GET":
            return {
                "workflow_runs": [{
                    "head_sha": SOURCE,
                    "head_branch": "main",
                    "event": "workflow_dispatch",
                    "status": "completed",
                    "conclusion": "success",
                }]
            }
        assert method == "POST"
        assert payload == {"ref": "main"}
        return None

    monkeypatch.setattr(agent_transport, "_api", api)
    monkeypatch.setattr(gate.am, "emit", lambda *a, **kw: None)

    assert gate.request_missing_research_cache(
        config, "source_exact_transport_cache_absent"
    ) == "source_exact_cache_build_dispatched"
    assert [row[0] for row in calls] == ["GET", "POST"]
    successor = config["tasks"][1]
    assert successor["research_cache_requested_key"] == (
        gate.RESEARCH_FRONTIER_CACHE_PREFIX + SOURCE + "-" + LEDGER
    )


def test_exact_frontier_dispatch_is_not_duplicated(monkeypatch):
    _ctx(monkeypatch)
    key = gate.RESEARCH_FRONTIER_CACHE_PREFIX + SOURCE + "-" + LEDGER
    config = _successor_config(requested_key=key)
    config["tasks"][1]["research_cache_requested_sha"] = SOURCE
    calls = []

    def api(method, url, payload=None):
        calls.append(method)
        return {
            "workflow_runs": [{
                "head_sha": SOURCE,
                "head_branch": "main",
                "event": "workflow_dispatch",
                "status": "completed",
                "conclusion": "success",
            }]
        }

    monkeypatch.setattr(agent_transport, "_api", api)
    assert gate.request_missing_research_cache(
        config, "source_exact_transport_cache_absent"
    ) == "successful_workflow_cache_pending_or_missing"
    assert calls == ["GET"]


def test_prepare_successor_identity_matches_manager_key():
    successor_id = next(iter(prepare.PREDECESSOR))
    payload = {
        "task_id": successor_id,
        "research_predecessor_source_sha": SOURCE,
        "research_predecessor_receipt_digest": "1" * 64,
        "research_predecessor_qa_digest": "2" * 64,
        "research_predecessor_ledger_digest": LEDGER,
        "research_predecessor_mechanism": "bar_proxy_vwap_reclaim",
    }
    key, digest = prepare._research_input_cache_identity(payload, SOURCE)
    assert digest == LEDGER
    assert key == prepare.INPUT_CACHE_V2_PREFIX + SOURCE + "-" + LEDGER


def test_workflows_use_frontier_bound_cache_key_contract():
    worker = Path(".github/workflows/nexus-runtime-worker.yml").read_text(encoding="utf-8")
    discovery = Path(".github/workflows/nexus_multitimeframe_strategy_discovery.yml").read_text(
        encoding="utf-8"
    )

    assert "steps.inspect-research.outputs.research_input_cache_key" in worker
    assert "steps.agent-frontier.outputs.cache_key" in discovery
    assert "nexus-composite-inputs-v2-" in discovery
    assert "build/research-frontier/previous-ledger.json" in discovery
