from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

import nexus_composite_validation_candidate_transport as transport


def _ledger(digest_value: str):
    core = {
        "schema": "nexus.automatic-composite-novelty-ledger.v1",
        "archive_sha256": "a" * 64,
        "mechanisms_evaluated": [],
        "config_fingerprints_evaluated": [],
        "frontier_screened_mechanisms": [],
        "frontier_screening_version": "nexus.frontier-train-screen.v5",
        "research_only": True,
        "auto_demo_promotion": False,
        "live_enabled": False,
    }
    # Caller replaces the expected digest with the canonical one.
    return core


def _zip():
    prior_core = _ledger("")
    prior_digest = transport.digest(prior_core)
    prior = {**prior_core, "ledger_digest": prior_digest}
    ledger_core = _ledger("")
    ledger_core["mechanisms_evaluated"] = ["factory_example"]
    ledger_digest = transport.digest(ledger_core)
    ledger = {**ledger_core, "ledger_digest": ledger_digest}
    report = {"schema": "report", "value": 1}
    report_raw = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
    ledger_raw = (json.dumps(ledger, indent=2, sort_keys=True) + "\n").encode()
    prior_raw = (json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()
    receipt = {
        "schema": "nexus.agent-composite-execution.v1",
        "lease_id": "lease-1",
        "source_sha": "b" * 40,
        "archive_sha256": "a" * 64,
        "prior_ledger_digest": prior_digest,
        "ledger_digest": ledger_digest,
        "report_digest": "c" * 64,
        "report_file_sha256": hashlib.sha256(report_raw).hexdigest(),
        "ledger_file_sha256": hashlib.sha256(ledger_raw).hexdigest(),
        "prior_ledger_file_sha256": hashlib.sha256(prior_raw).hexdigest(),
        "mechanism": "factory_example",
        "config_fingerprint": "d" * 64,
        "validation": [],
        "research_only": True,
        "auto_demo_promotion": False,
        "live_enabled": False,
        "independent_qa_complete": False,
        "receipt_digest": "e" * 64,
    }
    receipt_raw = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("result/agent-receipt.json", receipt_raw)
        zf.writestr("result/research-report.json", report_raw)
        zf.writestr("result/novelty-ledger.json", ledger_raw)
        zf.writestr("result/previous-ledger.json", prior_raw)
    return out.getvalue(), receipt, report


def _task(task_id: str, lease: str):
    return {
        "id": task_id,
        "status": "DONE",
        "producer": "research-agent",
        "verifier": "qa-verifier-agent",
        "research_producer_lease_id": lease,
        "result_evidence": {
            "independent_qa_complete": False,
            "qualification_authority": False,
            "auto_demo_promotion": False,
            "live_enabled": False,
        },
        "verification_evidence": {
            "independent_qa_complete": True,
            "qualification_authority": False,
            "auto_demo_promotion": False,
            "live_enabled": False,
        },
    }


def test_parse_producer_artifact_binds_actual_files():
    blob, receipt, report = _zip()
    got_receipt, got_report = transport.parse_producer_artifact(blob)
    assert got_receipt == receipt
    assert got_report == report

    tampered = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(blob)) as original, zipfile.ZipFile(tampered, "w") as zf:
        for info in original.infolist():
            data = original.read(info.filename)
            if info.filename.endswith("research-report.json"):
                data += b" "
            zf.writestr(info.filename, data)
    with pytest.raises(transport.CompositeVal40TransportError, match="report file hash"):
        transport.parse_producer_artifact(tampered.getvalue())


def test_sync_stores_forward_and_rejection_without_authority(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "saladinayoubi1/lbank-research-automation")
    blob, _receipt, _report = _zip()
    runtime = {
        "tasks": [
            _task("P7-RESEARCH-COMPOSITE-015", "lease-a"),
            _task("P7-RESEARCH-COMPOSITE-016", "lease-b"),
        ]
    }
    ids = {"lease-a": 11, "lease-b": 12}

    def api(method, url, payload):
        assert method == "GET"
        lease = "lease-a" if "lease-a" in url else "lease-b"
        return {
            "artifacts": [{
                "id": ids[lease], "name": "nexus-agent-research-" + lease,
                "expired": False, "size_in_bytes": len(blob),
            }]
        }

    def builder(task, receipt, report):
        eligible = task["id"].endswith("015")
        core = {
            "research_task_id": task["id"],
            "producer_lease_id": task["research_producer_lease_id"],
            "decision": "FORWARD_TO_VAL40" if eligible else "REJECTED_RESEARCH_VALIDATION",
            "eligible_for_fresh_runtime_requalification": eligible,
            "paper_only": True,
            "qualification_authority": False,
            "registry_mutation_authority": False,
            "paper_execution_authority": False,
            "live_trading_authority": False,
        }
        return {**core, "candidate_digest": transport.digest(core)}

    def verifier(candidate):
        core = {
            "decision": "pass",
            "candidate_digest": candidate["candidate_digest"],
        }
        return {**core, "verification_digest": transport.digest(core)}

    monkeypatch.setattr(transport, "verify_candidate", verifier)
    result = transport.sync_verified_candidates(
        runtime, tmp_path, api=api, downloader=lambda _id: blob,
        builder=builder, verifier=verifier,
    )
    assert result["processed"] == 2
    assert result["stored"] == 2
    assert result["eligible"] == 1
    assert result["qualification_authority"] is False
    assert result["paper_execution_authority"] is False
    assert result["live_trading_authority"] is False
    stored = list(tmp_path.glob("*/candidate.json"))
    assert len(stored) == 2


def test_missing_artifact_never_creates_candidate(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "saladinayoubi1/lbank-research-automation")
    runtime = {"tasks": [_task("P7-RESEARCH-COMPOSITE-017", "missing-lease")]}
    result = transport.sync_verified_candidates(
        runtime, tmp_path,
        api=lambda *args: {"artifacts": []},
        downloader=lambda _id: b"",
    )
    assert result["processed"] == 1
    assert result["stored"] == 0
    assert result["eligible"] == 0
    assert not list(tmp_path.rglob("candidate.json"))


def test_composite_val40_transport_import_is_control_plane_lightweight():
    import subprocess
    import sys

    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "sys.modules['pandas']=None; "
                "import nexus_composite_validation_candidate_transport; "
                "print('lightweight_composite_val40_transport=PASS')"
            ),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "lightweight_composite_val40_transport=PASS" in proc.stdout
