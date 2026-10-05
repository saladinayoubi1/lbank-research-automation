from __future__ import annotations

import base64
import json
import subprocess
import sys


def _bounded_payload(
    *,
    task_id: str = "P4-DATA-001",
    phase: int = 4,
    transport: str = "github-cloud",
) -> str:
    payload = {
        "schema_version": 2,
        "task_id": task_id,
        "lease_id": "lease-output-parent",
        "correlation_id": "correlation-output-parent",
        "dispatch_id": "dispatch-output-parent",
        "worker_id": "developer-agent",
        "transport": transport,
        "phase": phase,
        "gate": 1,
        "title": "verify nested result output",
        "required_capabilities": [],
        "acceptance": ["result.json is durable"],
        "authority": 1,
        "attempt": 1,
    }
    return base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def _execute(tmp_path, *, task_id: str, phase: int = 4, transport: str = "github-cloud"):
    output = tmp_path / task_id / "result.json"
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/agent_task_executor.py",
            "--payload-b64",
            _bounded_payload(task_id=task_id, phase=phase, transport=transport),
            "--transport",
            transport,
            "--output",
            str(output),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    result = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else None
    return proc, result


def test_executor_creates_nested_result_parent(tmp_path):
    output = tmp_path / "nested" / "agent-result" / "result.json"
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/agent_task_executor.py",
            "--payload-b64",
            _bounded_payload(),
            "--transport",
            "github-cloud",
            "--output",
            str(output),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert output.is_file()
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["task_id"] == "P4-DATA-001"
    assert result["transport"] == "github-cloud"
    assert result["outcome"] == "success"


def test_phase4_event_workload_runs_only_canonical_event_store_suite(tmp_path):
    proc, result = _execute(tmp_path, task_id="P4-EVENT-001")

    assert proc.returncode == 0, proc.stderr
    assert result["outcome"] == "success"
    assert result["evidence"]["executor"] == "bounded-pytest"
    assert result["evidence"]["suite"] == ["tests/test_nexus_event_store.py"]
    assert result["evidence"]["purpose"] == "source-bound-event-store-canonical-chain-replay-and-corruption-proof"


def test_phase4_event_workload_rejects_phase_substitution(tmp_path):
    proc, result = _execute(tmp_path, task_id="P4-EVENT-001", phase=7)

    assert proc.returncode == 2
    assert result["outcome"] == "failure"
    assert result["evidence"]["failure_class"] == "workload_phase_mismatch"
    assert result["evidence"]["expected_phase"] == 4


def test_phase4_event_workload_rejects_transport_substitution(tmp_path):
    proc, result = _execute(tmp_path, task_id="P4-EVENT-001", transport="windows")

    assert proc.returncode == 2
    assert result["outcome"] == "failure"
    assert result["evidence"]["failure_class"] == "workload_transport_mismatch"
    assert result["evidence"]["allowed_transports"] == ["github-cloud"]


def test_phase4_ui_workload_runs_only_canonical_shell_contract(tmp_path):
    proc, result = _execute(tmp_path, task_id="P4-UI-001")

    assert proc.returncode == 0, proc.stderr
    assert result["outcome"] == "success"
    assert result["evidence"]["executor"] == "bounded-pytest"
    assert result["evidence"]["suite"] == ["tests/test_web_ui.py"]
    assert result["evidence"]["purpose"] == "source-bound-responsive-read-only-shell-and-degraded-state-proof"


def test_phase4_ui_workload_rejects_phase_substitution(tmp_path):
    proc, result = _execute(tmp_path, task_id="P4-UI-001", phase=7)

    assert proc.returncode == 2
    assert result["outcome"] == "failure"
    assert result["evidence"]["failure_class"] == "workload_phase_mismatch"
    assert result["evidence"]["expected_phase"] == 4


def test_phase4_ui_workload_rejects_transport_substitution(tmp_path):
    proc, result = _execute(tmp_path, task_id="P4-UI-001", transport="windows")

    assert proc.returncode == 2
    assert result["outcome"] == "failure"
    assert result["evidence"]["failure_class"] == "workload_transport_mismatch"
    assert result["evidence"]["allowed_transports"] == ["github-cloud"]


def _strategy_qa_payload() -> str:
    from nexus_strategy_independent_qa import digest
    from nexus_strategy_review_qa_handoff import qa_task_id

    core = {
        "schema_version":"nexus.strategy-review-qa-task.v1",
        "id":qa_task_id("a"*64, "b"*40, "d"*64),
        "task_kind":"strategy_review_independent_qa","system_map_node":"QA-41",
        "status":"READY_FOR_QA_DISPATCH","source_sha":"b"*40,
        "proposal_digest":"a"*64,"proposal_result_digest":"c"*64,
        "requalification_digest":"d"*64,"requalification_verification_digest":"e"*64,
        "family":"momentum","timeframe":"hour4","variant_id":"v1",
        "strategy_config":{"lookback":16},"strategy_config_digest":"",
        "runtime_evidence":[
            {
                "symbol":"BTCUSDT","dataset_binding_sha256":"f"*64,
                "pipeline_digest":"1"*64,"qualification_digest":"2"*64,
                "last_open_time_ms":1800000000000,
            },
            {
                "symbol":"ETHUSDT","dataset_binding_sha256":"3"*64,
                "pipeline_digest":"4"*64,"qualification_digest":"5"*64,
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
    payload = {
        "schema_version":2,"task_id":task["id"],"lease_id":"strategy-qa-lease",
        "correlation_id":"strategy-qa-correlation","dispatch_id":"strategy-qa-dispatch",
        "worker_id":"qa-verifier-agent","transport":"github-cloud","phase":7,"gate":17,
        "title":"independent Strategy QA","required_capabilities":["data_validation"],
        "acceptance":["exact replay"],"authority":2,"attempt":1,
        "strategy_qa_task":task,
    }
    return base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def test_strategy_qa_executor_is_bounded_specialized_worker_not_generic_fallback(tmp_path):
    output = tmp_path / "strategy-qa" / "result.json"
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/agent_task_executor.py",
            "--payload-b64",
            _strategy_qa_payload(),
            "--transport",
            "github-cloud",
            "--output",
            str(output),
        ],
        text=True,
        capture_output=True,
        check=False,
        env={**__import__("os").environ, "GITHUB_SHA": "0" * 40},
    )
    result = json.loads(output.read_text(encoding="utf-8"))
    assert proc.returncode == 2
    assert result["outcome"] == "failure"
    assert result["evidence"]["executor"] == "nexus-strategy-independent-qa"
    assert result["evidence"]["failure_class"] == "strategy_independent_qa_failed"
    assert result["evidence"]["paper_execution_authority"] is False
    assert result["evidence"]["live_trading_authority"] is False
