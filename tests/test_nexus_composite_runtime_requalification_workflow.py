from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "nexus_composite_runtime_requalification.yml"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_is_manual_exact_run_only_and_read_only() -> None:
    text = _text()
    assert "workflow_dispatch:" in text
    assert "coordinator_run_id:" in text
    assert "workflow_run:" not in text
    assert "schedule:" not in text
    assert "contents: read" in text
    assert "actions: read" in text
    assert "actions: write" not in text


def test_runtime_executes_only_on_physical_bybit_lane() -> None:
    text = _text()
    assert "runtime-requalification:" in text
    assert "runs-on: nexus-bybit-network" in text
    assert "composite_val40_execution_plane=self-hosted:nexus-bybit-network" in text
    assert "runs-on: nexus-research" not in text
    assert "nexus-local" not in text


def test_trigger_and_artifact_identity_are_exact() -> None:
    text = _text()
    assert 'run.get("name") != "Fast Agent Coordinator"' in text
    assert 'run.get("conclusion") != "success"' in text
    assert 'run.get("head_branch") != "main"' in text
    assert 'expected = "fast-agent-status-" + sys.argv[2]' in text
    assert "len(matches) != 1" in text
    assert "size_in_bytes" in text
    assert "<= 8_000_000" in text


def test_only_one_verified_forward_candidate_can_run() -> None:
    text = _text()
    assert "from nexus_composite_validation_candidate import verify_candidate" in text
    assert 'computed.get("decision") != "pass"' in text
    assert 'candidate.get("decision") == "FORWARD_TO_VAL40"' in text
    assert 'candidate.get("eligible_for_fresh_runtime_requalification") is True' in text
    assert "len(eligible) != 1" in text
    assert "exactly one eligible candidate" in text


def test_runtime_never_receives_qualification_paper_or_live_authority() -> None:
    text = _text()
    assert "nexus_composite_runtime_requalification.py" in text
    assert 'result.get("candidate_state_created") is not False' in text
    assert 'result.get("qualification_authority") is not False' in text
    assert 'result.get("registry_mutation_authority") is not False' in text
    assert 'result.get("paper_execution_authority") is not False' in text
    assert 'result.get("automatic_strategy_promotion") is not False' in text
    assert 'result.get("live_trading_authority") is not False' in text
    assert 'result.get("private_credentials_used") is not False' in text


def test_contract_job_covers_candidate_transport_and_requalification() -> None:
    text = _text()
    assert "tests/test_nexus_composite_runtime_requalification.py" in text
    assert "tests/test_nexus_composite_runtime_requalification_workflow.py" in text
    assert "tests/test_nexus_composite_validation_candidate.py" in text
    assert "tests/test_nexus_composite_validation_candidate_transport.py" in text
    assert "bounded-job-log-v2" in text


def test_physical_runtime_job_is_javascript_action_free() -> None:
    text = _text()
    physical = text.split("  runtime-requalification:", 1)[1].split("  contract-test:", 1)[0]
    assert "runs-on: nexus-bybit-network" in physical
    assert "uses:" not in physical
    assert "physical_source_transport=github-api-exact-sha" in physical
    assert "No pre-provisioned CPython 3.12" in physical
    assert "actions/checkout" not in physical
    assert "actions/setup-python" not in physical
    assert "actions/upload-artifact" not in physical


def test_physical_evidence_uses_bounded_digest_bound_job_log_transport() -> None:
    text = _text()
    physical = text.split("  runtime-requalification:", 1)[1].split("  contract-test:", 1)[0]
    hosted = text.split("  contract-test:", 1)[1]
    assert "  publish-evidence:" not in text
    assert "transport_version=bounded-job-log-v2" in physical
    assert "NEXUS_COMPOSITE_VAL40_EVIDENCE_TRANSPORT=%s" in physical
    assert "NEXUS_COMPOSITE_VAL40_EVIDENCE_SHA256=" in physical
    assert "NEXUS_COMPOSITE_VAL40_EVIDENCE_SIZE=" in physical
    assert "NEXUS_COMPOSITE_VAL40_EVIDENCE_CHUNK_COUNT=" in physical
    assert "NEXUS_COMPOSITE_VAL40_EVIDENCE_CHUNK_%03d=" in physical
    assert 'test "$evidence_size" -le 500000' in physical
    assert 'test "${#evidence_b64}" -le 700000' in physical
    assert "zipfile.ZIP_DEFLATED" in physical
    assert "$WORK_ROOT/evidence.zip" in physical
    assert "needs: runtime-requalification" in hosted
    assert "runs-on: ubuntu-latest" in hosted
    assert "actions/jobs/$(cat build/publisher/job-id.txt)/logs" in hosted
    assert "physical evidence size or digest mismatch" in hosted
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in hosted
    assert "name: nexus-composite-runtime-requalification-${{ github.run_id }}" in hosted
    assert "if-no-files-found: error" in hosted
