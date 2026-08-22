import json
import os
from datetime import date, datetime, timezone
from http import HTTPStatus
from pathlib import Path

import pytest

from dashboard_integrations import IntegrationUnavailableError, load_research_summary, load_zotero_summary
from integration_report_provenance import build_envelope, trusted_source_commit
from web_dashboard import dispatch_get


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def zotero_payload() -> dict:
    return {
        "schema_version": "2.0",
        "mode": "read-only-offline",
        "item_count": 3,
        "finding_count": 1,
        "items": [{"index": 0}],
        "duplicates": {"doi": [], "title_year": []},
    }


def research_payload() -> dict:
    return {
        "schema_version": "1.1.0",
        "status": "research-only",
        "paper_trading_only": True,
        "next_review_due": "2027-02-06",
        "claims": [{"id": "C1", "evidence_ids": ["E1"]}],
        "evidence": [{"id": "E1", "domain": "model_validation"}],
    }


NOW = datetime.now(timezone.utc)
SOURCE_COMMIT = trusted_source_commit()


def envelope(kind: str, payload: dict) -> dict:
    return build_envelope(
        kind=kind, report=payload,
        source_commit=SOURCE_COMMIT, workflow_run="github-123",
        generated_at=NOW.isoformat().replace("+00:00", "Z"),
    )


def test_zotero_summary_success(tmp_path: Path):
    write_json(tmp_path / "zotero_metadata_report_v2.json", envelope("zotero", zotero_payload()))
    summary = load_zotero_summary(tmp_path, now=NOW)
    assert summary["item_count"] == 3
    assert summary["status"] == "attention"


def test_zotero_schema_mismatch_fails_closed(tmp_path: Path):
    payload = zotero_payload()
    payload["schema_version"] = "9.0"
    write_json(tmp_path / "zotero_metadata_report_v2.json", envelope("zotero", payload))
    with pytest.raises(IntegrationUnavailableError):
        load_zotero_summary(tmp_path, now=NOW)


def test_research_summary_success_and_staleness(tmp_path: Path):
    write_json(tmp_path / "research_evidence_summary.json", envelope("research", research_payload()))
    summary = load_research_summary(tmp_path, today=date(2026, 8, 6), now=NOW)
    assert summary["claim_count"] == 1
    assert summary["stale"] is False


def test_research_unsafe_boundary_fails_closed(tmp_path: Path):
    payload = research_payload()
    payload["paper_trading_only"] = False
    write_json(tmp_path / "research_evidence_summary.json", envelope("research", payload))
    with pytest.raises(IntegrationUnavailableError):
        load_research_summary(tmp_path, now=NOW)


def test_integration_endpoints(tmp_path: Path):
    data_root = tmp_path / "market"
    integration_root = tmp_path / "integrations"
    write_json(integration_root / "zotero_metadata_report_v2.json", envelope("zotero", zotero_payload()))
    write_json(integration_root / "research_evidence_summary.json", envelope("research", research_payload()))
    zotero = dispatch_get("/api/integrations/zotero", data_root)
    research = dispatch_get("/api/integrations/research", data_root)
    assert zotero.status == HTTPStatus.OK
    assert research.status == HTTPStatus.OK


def test_missing_integration_report_is_controlled(tmp_path: Path):
    response = dispatch_get("/api/integrations/zotero", tmp_path / "market")
    assert response.status == HTTPStatus.SERVICE_UNAVAILABLE
    assert response.payload["error"] == "report_unavailable"


@pytest.mark.parametrize("bad", [True, -1, 100_001, "3"])
def test_zotero_invalid_counts_fail_closed(tmp_path: Path, bad: object):
    payload = zotero_payload()
    payload["item_count"] = bad
    write_json(tmp_path / "zotero_metadata_report_v2.json", envelope("zotero", payload))
    with pytest.raises(IntegrationUnavailableError):
        load_zotero_summary(tmp_path, now=NOW)


def test_unbound_or_digest_modified_report_fails_closed(tmp_path: Path):
    write_json(tmp_path / "zotero_metadata_report_v2.json", zotero_payload())
    with pytest.raises(IntegrationUnavailableError):
        load_zotero_summary(tmp_path, now=NOW)
    bound = envelope("zotero", zotero_payload())
    bound["report"]["item_count"] = 4
    write_json(tmp_path / "zotero_metadata_report_v2.json", bound)
    with pytest.raises(IntegrationUnavailableError):
        load_zotero_summary(tmp_path, now=NOW)


def test_duplicate_json_keys_and_symlink_fail_closed(tmp_path: Path):
    target = tmp_path / "target.json"
    target.write_text('{"schema":"x","schema":"y"}', encoding="utf-8")
    report = tmp_path / "zotero_metadata_report_v2.json"
    report.symlink_to(target)
    with pytest.raises(IntegrationUnavailableError):
        load_zotero_summary(tmp_path, now=NOW)


def test_duplicate_keys_hardlink_and_oversized_report_fail_closed(tmp_path: Path):
    report = tmp_path / "zotero_metadata_report_v2.json"
    report.write_text('{"schema":"x","schema":"y"}', encoding="utf-8")
    with pytest.raises(IntegrationUnavailableError):
        load_zotero_summary(tmp_path, now=NOW)
    report.unlink()
    target = tmp_path / "hardlink-target.json"
    write_json(target, envelope("zotero", zotero_payload()))
    os.link(target, report)
    with pytest.raises(IntegrationUnavailableError):
        load_zotero_summary(tmp_path, now=NOW)
    report.unlink()
    report.write_bytes(b"{" + b"x" * 262_144 + b"}")
    with pytest.raises(IntegrationUnavailableError):
        load_zotero_summary(tmp_path, now=NOW)


def test_producer_source_and_freshness_mismatches_fail_closed(tmp_path: Path):
    cases = []
    producer = envelope("zotero", zotero_payload())
    producer["producer"] = "attacker"
    cases.append(producer)
    source = envelope("zotero", zotero_payload())
    source["source_commit"] = "b" * 40
    cases.append(source)
    for timestamp in ("2020-01-01T00:00:00Z", "2099-01-01T00:00:00Z"):
        value = envelope("zotero", zotero_payload())
        value["generated_at"] = timestamp
        cases.append(value)
    for value in cases:
        write_json(tmp_path / "zotero_metadata_report_v2.json", value)
        with pytest.raises(IntegrationUnavailableError):
            load_zotero_summary(tmp_path, now=NOW)


def test_research_dangling_binding_and_missing_review_fail_closed(tmp_path: Path):
    for mutation in ("dangling", "missing-date"):
        payload = research_payload()
        if mutation == "dangling":
            payload["claims"][0]["evidence_ids"] = ["missing"]
        else:
            payload["next_review_due"] = None
        write_json(tmp_path / "research_evidence_summary.json", envelope("research", payload))
        with pytest.raises(IntegrationUnavailableError):
            load_research_summary(tmp_path, today=date(2026, 8, 6), now=NOW)


def test_summaries_emit_only_privacy_allowlisted_fields(tmp_path: Path):
    write_json(tmp_path / "zotero_metadata_report_v2.json", envelope("zotero", zotero_payload()))
    write_json(tmp_path / "research_evidence_summary.json", envelope("research", research_payload()))
    combined = {**load_zotero_summary(tmp_path, now=NOW), **load_research_summary(tmp_path, today=date(2026, 8, 6), now=NOW)}
    for forbidden in ("title", "creator", "doi", "note", "tag", "path", "prompt", "raw_evidence", "items", "claims", "evidence"):
        assert forbidden not in combined
