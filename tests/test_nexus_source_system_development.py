"""Real compiler/task lifecycle; source SHA values below are test identities.

No physical market replay, external source attestation or strategy approval.
"""
from copy import deepcopy
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

import agent_manager as am
import agent_manager_runner as runner
import agent_transport as transport
import nexus_source_system_development as dev
from scripts import agent_task_executor as executor
from scripts.nexus_research_qa_source_pin import select_source

REQUEST = dev.REQUEST_DIR + "/prior_day_sweep_peer_resilience_v1.json"
TEST_SOURCE = "1" * 40


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    original, _ = dev.load_request(dev.ROOT, REQUEST)
    inputs = (*dev.IMPLEMENTATION_FILES, REQUEST, original["candidate_path"],
              *(n["path"] for n in original["source_notes"]),
              "research/strategy_finder_executable_intake_allowlist_v1.json")
    for name in inputs:
        out = tmp_path / "source" / name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes((dev.ROOT / name).read_bytes())
    monkeypatch.setattr(am, "EVENT_PATH", tmp_path / "events.jsonl")
    monkeypatch.setenv("GITHUB_SHA", TEST_SOURCE)
    return tmp_path / "source"


def config_for(root=dev.ROOT):
    cfg = json.loads((dev.ROOT / "config/nexus-agent-manager.json").read_text())
    cfg = dev.materialize_development_tasks(cfg, root)
    cfg["tasks"] = [t for t in cfg["tasks"] if dev.is_development(t)]
    am.validate_config(cfg)
    return cfg


def checked_envelope(task):
    envelope = transport.envelope_for(task)
    encoded = base64.urlsafe_b64encode(json.dumps(envelope).encode()).decode()
    assert len(encoded) < 64_000
    return executor.decode_payload(encoded)


def produce(config):
    am.cycle(config)
    task = config["tasks"][0]
    assert task["status"] == "LEASED" and task["assigned_worker"] == "developer-agent"
    payload = checked_envelope(task)
    outcome, receipt = executor.deterministic_execution(payload, "github-cloud")
    assert outcome == "success", receipt
    am.record_result(config, task["id"], "developer-agent", outcome, receipt)
    assert task["status"] == "VERIFYING" and task["assigned_worker"] == "qa-verifier-agent"
    return task, receipt


def test_actual_manager_worker_qa_cycle_emits_existing_executor_inputs_without_market_io(isolated, monkeypatch):
    from scripts import nexus_strategy_finder_executable_intake as intake
    def forbidden(*args, **kwargs):
        raise AssertionError("compiler attempted a market replay")
    monkeypatch.setattr(intake, "verify_pinned_market_files", forbidden)
    monkeypatch.setattr(intake, "evaluate_approved", forbidden)
    cfg = config_for()
    task, original = produce(cfg)
    payload = checked_envelope(task)
    pin = select_source(payload, repository="saladinayoubi1/lbank-research-automation", main_sha=TEST_SOURCE,
                        ref_name="main", default_branch="main", actor="github-actions[bot]",
                        owner="saladinayoubi1", input_lease=task["lease_id"], input_transport="github-cloud")
    assert pin["execution_source_sha"] == TEST_SOURCE and not pin["requested_ancestor_pin"]
    outcome, qa = executor.deterministic_execution(payload, "github-cloud")
    assert outcome == "success", qa
    am.record_result(cfg, task["id"], "qa-verifier-agent", outcome, qa)
    assert task["status"] == "DONE"
    assert task["producer"] == "developer-agent" and task["verifier"] == "qa-verifier-agent"
    assert qa["bundle_digest"] == original["bundle_digest"]
    assert qa["producer_lease_id"] != qa["lease_id"]
    assert qa["independent_implementation_qa_complete"] is True
    assert qa["research_execution_approved"] is False and qa["market_replay_performed"] is False
    assert qa["external_source_interpretation_attested"] is False and qa["economic_edge_established"] is False
    for path, content in qa["bundle"]["files"].items():
        assert content.encode() == (dev.ROOT / path).read_bytes()
    assert (isolated / intake.DEFAULT_ALLOWLIST).read_bytes() == (dev.ROOT / intake.DEFAULT_ALLOWLIST).read_bytes()


def test_real_cli_result_artifact_contains_complete_system_bytes(isolated, tmp_path):
    cfg = config_for(); am.cycle(cfg)
    payload = checked_envelope(cfg["tasks"][0])
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    output = tmp_path / "result.json"
    result = subprocess.run([sys.executable, str(dev.ROOT / "scripts/agent_task_executor.py"),
                             "--payload-b64", encoded, "--transport", "github-cloud", "--output", str(output)],
                            cwd=tmp_path, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    artifact = json.loads(output.read_text())
    assert artifact["outcome"] == "success"
    assert len(artifact["evidence"]["bundle"]["files"]) == 2


def test_materializer_and_existing_coordinator_import_without_site_packages():
    script = "import json, pathlib, agent_manager_runner as r; from nexus_source_system_development import materialize_development_tasks; c=json.loads(pathlib.Path('config/nexus-agent-manager.json').read_text()); assert len(materialize_development_tasks(c)['tasks']) == len(c['tasks'])+1"
    result = subprocess.run([sys.executable, "-S", "-c", script], cwd=dev.ROOT,
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_unchanged_implementation_is_idempotent_across_coordinator_refresh(isolated):
    cfg = config_for()
    task, _ = produce(cfg)
    # Definitions do not absorb runtime receipts; merge_definition preserves them.
    template = config_for()
    merged = runner.merge_definition(template, cfg)
    assert merged["tasks"][0]["status"] == "VERIFYING"
    assert merged["tasks"][0]["lease_id"] == task["lease_id"]
    definition = config_for()
    assert dev.materialize_development_tasks(definition) == definition


@pytest.mark.parametrize("field,value", [("phase", 4), ("gate", 3), ("worker_id", "cloud-worker"),
                                        ("authority", 3), ("transport", "windows")])
def test_dispatch_cannot_substitute_role_phase_or_authority(isolated, field, value):
    cfg = config_for(); am.cycle(cfg)
    payload = checked_envelope(cfg["tasks"][0]); payload[field] = value
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    with pytest.raises(ValueError):
        executor.decode_payload(encoded)


@pytest.mark.parametrize("field", ["context", "entry", "exit", "sizing", "no_trade"])
def test_missing_complete_component_never_materializes_a_futile_task(isolated, field):
    request, _ = dev.load_request(isolated, REQUEST)
    del request["rule_bindings"][field]; write(isolated / REQUEST, request)
    materialized = dev.materialize_development_tasks({"tasks": [{"id": "unrelated", "status": "READY"}]}, isolated)
    assert materialized["tasks"][0]["status"] == "READY"
    blocked = materialized["tasks"][1]
    assert blocked["status"] == "BLOCKED" and "five explicit" in blocked["blocked_reason"]
    assert not dev.is_development(blocked)


def test_changed_source_and_candidate_are_rejected_before_dispatch(isolated):
    request, _ = dev.load_request(isolated, REQUEST)
    (isolated / request["candidate_path"]).write_text("{}")
    result = dev.materialize_development_tasks({"tasks": []}, isolated)
    assert result["tasks"][0]["status"] == "BLOCKED"
    assert "candidate SHA" in result["tasks"][0]["blocked_reason"]


def test_unsupported_execution_is_not_replaced_with_implicit_defaults(isolated):
    request, _ = dev.load_request(isolated, REQUEST)
    request["execution_contract"]["stop_range_multiple"] = 3
    write(isolated / REQUEST, request)
    binding = dev.task_binding(isolated, REQUEST)
    with pytest.raises(ValueError, match="requires actual code implementation"):
        dev.compile_system(binding, isolated)


def test_resealed_alternate_executor_cannot_impersonate_imported_code(isolated):
    (isolated / dev.IMPLEMENTATION_FILES[0]).write_text("# alternate unexecuted code\n")
    binding = dev.task_binding(isolated, REQUEST)
    with pytest.raises(ValueError, match="actual imported code"):
        dev.compile_system(binding, isolated)


def test_candidate_artifact_preserves_exact_reviewed_bytes_including_crlf(isolated):
    request, _ = dev.load_request(isolated, REQUEST)
    path = isolated / request["candidate_path"]
    raw = path.read_bytes().replace(b"\n", b"\r\n")
    path.write_bytes(raw)
    request["candidate_sha256"] = hashlib.sha256(raw).hexdigest()
    write(isolated / REQUEST, request)
    bundle = dev.compile_system(dev.task_binding(isolated, REQUEST), isolated)
    assert bundle["files"][request["candidate_path"]].encode("utf-8") == raw
    assert bundle["file_sha256"][request["candidate_path"]] == request["candidate_sha256"]


def test_producer_success_requires_an_actual_artifact_not_a_test_count(isolated):
    cfg = config_for(); am.cycle(cfg)
    with pytest.raises(ValueError, match="receipt"):
        am.record_result(cfg, cfg["tasks"][0]["id"], "developer-agent", "success", {"tests_passed": 100})
    assert cfg["tasks"][0]["status"] == "LEASED"


def test_qa_rejects_rehashed_tampered_producer_artifact(isolated):
    cfg = config_for(); task, original = produce(cfg)
    payload = checked_envelope(task)
    tampered = payload["source_system_development_producer"]
    path = tampered["bundle"]["system_specification_path"]
    tampered["bundle"]["files"][path] += " "
    tampered["bundle"]["file_sha256"][path] = hashlib.sha256(tampered["bundle"]["files"][path].encode()).hexdigest()
    tampered["bundle_digest"] = dev.digest(tampered["bundle"])
    tampered["receipt_digest"] = dev.digest({k: v for k, v in tampered.items() if k != "receipt_digest"})
    outcome, result = executor.deterministic_execution(payload, "github-cloud")
    assert outcome == "failure" and "exact producer" in result["reason"]
    assert task["status"] == "VERIFYING"


def test_qa_receipt_cannot_complete_another_lease_even_when_rehashed(isolated):
    cfg = config_for(); task, _ = produce(cfg)
    outcome, qa = executor.deterministic_execution(checked_envelope(task), "github-cloud")
    assert outcome == "success"
    qa["lease_id"] = "unrelated-qa-lease"
    qa["receipt_digest"] = dev.digest({k: v for k, v in qa.items() if k != "receipt_digest"})
    with pytest.raises(ValueError, match="receipt"):
        am.record_result(cfg, task["id"], "qa-verifier-agent", "success", qa)
    assert task["status"] == "VERIFYING"


def test_failed_implementation_stops_instead_of_reentering_generic_rca_loop(isolated):
    cfg = config_for(); am.cycle(cfg)
    task = cfg["tasks"][0]
    am.record_result(cfg, task["id"], "developer-agent", "failure", {"failure_class": "source_system_development_failed"})
    am.cycle(cfg)
    assert task["status"] == "BLOCKED" and task["assigned_worker"] is None
    merged = runner.merge_definition(config_for(), cfg)
    assert merged["tasks"][0]["status"] == "BLOCKED"


def test_new_frozen_request_changes_identity_without_silently_reusing_done_state(isolated):
    cfg = config_for(isolated)
    cfg["tasks"][0]["status"] = "DONE"
    request, _ = dev.load_request(isolated, REQUEST)
    request["rule_bindings"]["entry"]["summary"] += " Explicit unchanged conjunction."
    write(isolated / REQUEST, request)
    template = config_for(isolated)
    assert template["tasks"][0]["id"] != cfg["tasks"][0]["id"]
    merged = runner.merge_definition(template, cfg)
    assert merged["tasks"][0]["status"] == "READY" and merged["tasks"][1]["status"] == "QUARANTINED"


def test_duplicate_json_and_traversal_are_rejected(isolated):
    with pytest.raises(ValueError, match="input path"):
        dev.task_binding(isolated, REQUEST.replace("prior_day", "../prior_day"))
    path = isolated / REQUEST
    path.write_text('{"schema":"first","schema":"second"}')
    with pytest.raises(ValueError, match="invalid implementation JSON"):
        dev.task_binding(isolated, REQUEST)
