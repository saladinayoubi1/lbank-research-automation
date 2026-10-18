"""Finished-study ingestion: no new markets, no positive/qualified relabeling."""
from copy import deepcopy
import base64
import os
import json
from pathlib import Path
import subprocess
import sys

import pytest

import agent_manager as am
import agent_manager_runner as runner
import agent_transport as transport
import nexus_source_system_economic_review as review
from scripts import agent_task_executor as executor
from scripts.nexus_research_qa_source_pin import select_source

MANIFEST = review.DIRECTORY + "/failure_test_structural_v1.json"
SOURCE = "a" * 40  # Test execution identity, not a hosted run.


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    original = review.ROOT
    manifest, _, _ = review.load_evidence(MANIFEST)
    request = json.loads((original / manifest["economic_request_path"]).read_text())
    prefix = "research/source_system_economic_results/" + manifest["economic_task_id"]
    paths = (*review.CODE, MANIFEST, manifest["economic_request_path"],
             request["system_specification_path"], "scripts/nexus_source_system_economic_execution.py",
             prefix + ".json", prefix + ".qa.json")
    root = tmp_path / "source"
    for relative in paths:
        out = root / relative
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes((original / relative).read_bytes())
    monkeypatch.setattr(review, "ROOT", root)
    monkeypatch.setattr(am, "EVENT_PATH", tmp_path / "events.jsonl")
    monkeypatch.setenv("GITHUB_SHA", SOURCE)
    return root


def config():
    base = json.loads((Path(__file__).resolve().parents[1] / "config/nexus-agent-manager.json").read_text())
    result = review.materialize_reviews(base)
    result["tasks"] = [t for t in result["tasks"] if review.is_review(t)]
    am.validate_config(result)
    return result


def envelope(task):
    value = transport.envelope_for(task)
    encoded = base64.urlsafe_b64encode(json.dumps(value).encode()).decode()
    assert len(encoded) < 64_000
    return executor.decode_payload(encoded)


def execute_and_ingest(cfg):
    task = cfg["tasks"][0]
    payload = envelope(task)
    outcome, receipt = executor.deterministic_execution(payload, "github-cloud")
    assert outcome == "success", receipt
    task["dispatch_id"] = transport.dispatch_id_for(task)
    task["dispatch_transport"] = "github-cloud"
    result = {k: payload[k] for k in ("schema_version", "task_id", "lease_id", "correlation_id",
                                     "dispatch_id", "worker_id", "transport")}
    result.update(outcome=outcome, evidence=receipt)
    transport.ingest_result(cfg, task, result)
    return receipt, result


def test_real_manager_transport_worker_and_separate_qa_import_preserved_negative_result(isolated, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("evidence ingestion attempted market/network/pytest execution")
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(transport.urllib.request, "urlopen", forbidden)
    cfg = config()
    am.cycle(cfg)
    task = cfg["tasks"][0]
    assert task["status"] == "LEASED" and task["assigned_worker"] == "research-agent"
    producer, _ = execute_and_ingest(cfg)
    assert task["status"] == "VERIFYING" and task["assigned_worker"] == "qa-verifier-agent"
    pinned = select_source(envelope(task), repository="saladinayoubi1/lbank-research-automation",
                           main_sha=SOURCE, ref_name="main", default_branch="main", actor="github-actions[bot]",
                           owner="saladinayoubi1", input_lease=task["lease_id"], input_transport="github-cloud")
    assert pinned["execution_source_sha"] == SOURCE and not pinned["requested_ancestor_pin"]
    qa, _ = execute_and_ingest(cfg)
    assert task["status"] == "DONE"
    assert task["producer"] == "research-agent" and task["verifier"] == "qa-verifier-agent"
    assert qa["producer_lease_id"] == producer["lease_id"] != qa["lease_id"]
    assert qa["producer_receipt_digest"] == producer["receipt_digest"]
    assert qa["independent_evidence_import_qa_complete"] is True
    summary = am.summarize(cfg)["source_system_economic_reviews"]
    assert summary["completed"] == 1
    assert summary["latest"]["disposition"] == "HISTORICAL_NEGATIVE_DO_NOT_RETUNE"
    assert summary["latest"]["original_numerical_qa_reused"] is True
    assert summary["latest"]["partitions"][0]["trades"] == 9
    assert summary["latest"]["partitions"][2]["net_pnl_usdt"] == -2.20141854
    assert summary["latest"]["partitions"][5]["net_pnl_usdt"] == -1.02001403
    for key, expected in review.BOUNDARIES.items():
        assert qa[key] is expected and summary["latest"][key] is expected
    merged = runner.merge_definition(config(), cfg)
    am.cycle(merged)
    assert len(merged["tasks"]) == 1 and merged["tasks"][0]["status"] == "DONE"
    assert am.summarize(merged)["source_system_economic_reviews"]["completed"] == 1


@pytest.mark.parametrize("target", ["producer", "qa", "request", "system", "worker"])
def test_missing_or_changed_native_evidence_blocks_only_its_import(isolated, target):
    m = json.loads((isolated / MANIFEST).read_text())
    req = json.loads((isolated / m["economic_request_path"]).read_text())
    prefix = "research/source_system_economic_results/" + m["economic_task_id"]
    paths = {"producer": prefix + ".json", "qa": prefix + ".qa.json",
             "request": m["economic_request_path"], "system": req["system_specification_path"],
             "worker": "scripts/nexus_source_system_economic_execution.py"}
    with (isolated / paths[target]).open("ab") as f:
        f.write(b" ")
    cfg = review.materialize_reviews({"tasks": [{"id": "UNRELATED", "status": "READY"}]})
    assert cfg["tasks"][0]["status"] == "READY"
    assert cfg["tasks"][1]["status"] == "BLOCKED"
    assert cfg["tasks"][1]["failure_class"] == "invalid_economic_review_evidence"


@pytest.mark.parametrize("field", ["live_enabled", "economic_edge_established", "summary", "producer_lease_id"])
def test_self_redigested_qa_cannot_change_authority_numbers_or_producer(isolated, field):
    cfg = config(); am.cycle(cfg)
    producer, _ = execute_and_ingest(cfg)
    task = cfg["tasks"][0]
    outcome, qa = executor.deterministic_execution(envelope(task), "github-cloud")
    assert outcome == "success"
    if field == "summary":
        qa["summary"]["partitions"][0]["net_pnl_usdt"] = 999.
        qa["summary_digest"] = review.digest(qa["summary"])
    elif field == "producer_lease_id":
        qa[field] = qa["lease_id"]
    else:
        qa[field] = True
    qa["receipt_digest"] = review.digest({k: v for k, v in qa.items() if k != "receipt_digest"})
    with pytest.raises(ValueError):
        am.record_result(cfg, task["id"], "qa-verifier-agent", "success", qa)
    assert task["status"] == "VERIFYING" and task["result_evidence"] == producer


def test_wrong_worker_and_unknown_payload_field_are_rejected_before_execution(isolated):
    cfg = config(); am.cycle(cfg)
    task = cfg["tasks"][0]
    good = envelope(task)
    for change in ({"worker_id": "developer-agent"}, {"authority": 3}, {"transport": "windows"},
                   {"command": "arbitrary"}):
        bad = dict(good, **change)
        encoded = base64.urlsafe_b64encode(json.dumps(bad).encode()).decode()
        with pytest.raises(ValueError):
            executor.decode_payload(encoded)
    task["assigned_worker"] = "developer-agent"
    with pytest.raises(ValueError):
        transport.envelope_for(task)


def test_failed_import_stops_without_generic_rca_or_market_retry(isolated):
    cfg = config(); am.cycle(cfg)
    task = cfg["tasks"][0]
    am.record_result(cfg, task["id"], "research-agent", "failure", {"failure_class": "changed_evidence"})
    assert task["status"] == "BLOCKED" and task["assigned_worker"] is None
    am.cycle(cfg)
    assert task["status"] == "BLOCKED" and task["attempt"] == 1


def test_definition_change_does_not_reuse_a_done_review_for_other_inputs(isolated):
    cfg = config(); am.cycle(cfg); execute_and_ingest(cfg); execute_and_ingest(cfg)
    template = config()
    template["tasks"][0]["source_system_economic_review_task"]["manifest_sha256"] = "b" * 64
    merged = runner.merge_definition(template, cfg)
    assert merged["tasks"][0]["status"] == "READY"
    assert "verification_evidence" not in merged["tasks"][0]


def test_no_minimum_trade_count_or_qualification_from_positive_history():
    assert review.disposition([{"trades": 0, "net_pnl_usdt": 0.}]) == "NO_EXECUTION_EVIDENCE"
    assert review.disposition([{"trades": 1, "net_pnl_usdt": 1.}]).endswith("FUTURE_EVIDENCE_REQUIRED")
    assert review.disposition([{"trades": 1, "net_pnl_usdt": -1.}]).startswith("HISTORICAL_NEGATIVE")


def test_coordinator_materializes_review_without_site_packages():
    root = Path(__file__).resolve().parents[1]
    script = "import agent_manager_runner; import nexus_source_system_economic_review as r; c=r.materialize_reviews({'tasks':[]}); assert len(c['tasks'])==1 and c['tasks'][0]['status']=='READY'"
    result = subprocess.run([sys.executable, "-S", "-c", script], cwd=root, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_actual_worker_cli_emits_typed_economic_import_receipt(tmp_path):
    root = Path(__file__).resolve().parents[1]
    cfg = config()
    saved = am.EVENT_PATH
    try:
        am.EVENT_PATH = tmp_path / "events.jsonl"
        am.cycle(cfg)
    finally:
        am.EVENT_PATH = saved
    payload = envelope(cfg["tasks"][0])
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    out = tmp_path / "worker-result.json"
    env = dict(os.environ, GITHUB_SHA=SOURCE)
    result = subprocess.run([sys.executable, str(root / "scripts/agent_task_executor.py"),
                             "--payload-b64", encoded, "--transport", "github-cloud", "--output", str(out)],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    receipt = json.loads(out.read_text())["evidence"]
    assert receipt["schema"] == review.RECEIPT_SCHEMA
    assert receipt["summary"]["disposition"] == "HISTORICAL_NEGATIVE_DO_NOT_RETUNE"
    assert receipt["market_replay_performed"] is False
