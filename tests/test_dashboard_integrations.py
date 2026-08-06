import json
from datetime import date
from http import HTTPStatus
from pathlib import Path

import pytest

from dashboard_integrations import IntegrationUnavailableError, load_research_summary, load_zotero_summary
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
        "claims": [{"claim_id": "C1"}],
        "evidence": [{"id": "E1", "domain": "model_validation"}],
    }


def test_zotero_summary_success(tmp_path: Path):
    write_json(tmp_path / "zotero_metadata_report_v2.json", zotero_payload())
    summary = load_zotero_summary(tmp_path)
    assert summary["item_count"] == 3
    assert summary["status"] == "attention"


def test_zotero_schema_mismatch_fails_closed(tmp_path: Path):
    payload = zotero_payload()
    payload["schema_version"] = "9.0"
    write_json(tmp_path / "zotero_metadata_report_v2.json", payload)
    with pytest.raises(IntegrationUnavailableError):
        load_zotero_summary(tmp_path)


def test_research_summary_success_and_staleness(tmp_path: Path):
    write_json(tmp_path / "research_evidence_summary.json", research_payload())
    summary = load_research_summary(tmp_path, today=date(2026, 8, 6))
    assert summary["claim_count"] == 1
    assert summary["stale"] is False


def test_research_unsafe_boundary_fails_closed(tmp_path: Path):
    payload = research_payload()
    payload["paper_trading_only"] = False
    write_json(tmp_path / "research_evidence_summary.json", payload)
    with pytest.raises(IntegrationUnavailableError):
        load_research_summary(tmp_path)


def test_integration_endpoints(tmp_path: Path):
    data_root = tmp_path / "market"
    integration_root = tmp_path / "integrations"
    write_json(integration_root / "zotero_metadata_report_v2.json", zotero_payload())
    write_json(integration_root / "research_evidence_summary.json", research_payload())
    zotero = dispatch_get("/api/integrations/zotero", data_root)
    research = dispatch_get("/api/integrations/research", data_root)
    assert zotero.status == HTTPStatus.OK
    assert research.status == HTTPStatus.OK


def test_missing_integration_report_is_controlled(tmp_path: Path):
    response = dispatch_get("/api/integrations/zotero", tmp_path / "market")
    assert response.status == HTTPStatus.SERVICE_UNAVAILABLE
    assert response.payload["error"] == "report_unavailable"
