"""Fail-closed, read-only adapters for dashboard integration summaries."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

ZOTERO_REPORT = "zotero_metadata_report_v2.json"
RESEARCH_REPORT = "research_evidence_summary.json"
SUPPORTED_ZOTERO_SCHEMA = "2.0"
SUPPORTED_RESEARCH_SCHEMAS = {"1.0.0", "1.1.0"}


class IntegrationUnavailableError(RuntimeError):
    """Raised when an integration report cannot be safely summarized."""


def _load_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise IntegrationUnavailableError(f"missing integration report: {path.name}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IntegrationUnavailableError(f"invalid integration report: {path.name}") from exc
    if not isinstance(payload, dict):
        raise IntegrationUnavailableError(f"invalid integration root: {path.name}")
    return payload


def load_zotero_summary(root: Path) -> dict[str, Any]:
    payload = _load_object(root / ZOTERO_REPORT)
    if payload.get("schema_version") != SUPPORTED_ZOTERO_SCHEMA:
        raise IntegrationUnavailableError("unsupported Zotero report schema")
    if payload.get("mode") != "read-only-offline":
        raise IntegrationUnavailableError("unsafe Zotero report mode")
    required = ("item_count", "finding_count", "items", "duplicates")
    if any(key not in payload for key in required):
        raise IntegrationUnavailableError("incomplete Zotero report")
    if not isinstance(payload["items"], list) or not isinstance(payload["duplicates"], dict):
        raise IntegrationUnavailableError("invalid Zotero report structure")
    return {
        "schema_version": payload["schema_version"],
        "mode": payload["mode"],
        "item_count": int(payload["item_count"]),
        "finding_count": int(payload["finding_count"]),
        "duplicate_doi_groups": len(payload["duplicates"].get("doi", [])),
        "duplicate_title_year_groups": len(payload["duplicates"].get("title_year", [])),
        "status": "attention" if int(payload["finding_count"]) else "clean",
    }


def load_research_summary(root: Path, *, today: date | None = None) -> dict[str, Any]:
    payload = _load_object(root / RESEARCH_REPORT)
    schema = payload.get("schema_version")
    if schema not in SUPPORTED_RESEARCH_SCHEMAS:
        raise IntegrationUnavailableError("unsupported Research report schema")
    if payload.get("status") != "research-only" or payload.get("paper_trading_only") is not True:
        raise IntegrationUnavailableError("unsafe Research report boundary")
    claims = payload.get("claims")
    evidence = payload.get("evidence")
    if not isinstance(claims, list) or not isinstance(evidence, list):
        raise IntegrationUnavailableError("invalid Research report structure")
    domains = sorted({str(item.get("domain")) for item in evidence if isinstance(item, dict) and item.get("domain")})
    due_raw = payload.get("next_review_due")
    stale = False
    if due_raw:
        try:
            stale = date.fromisoformat(str(due_raw)) < (today or date.today())
        except ValueError as exc:
            raise IntegrationUnavailableError("invalid Research review date") from exc
    return {
        "schema_version": schema,
        "status": payload["status"],
        "paper_trading_only": True,
        "claim_count": len(claims),
        "evidence_count": len(evidence),
        "domain_count": len(domains),
        "domains": domains,
        "next_review_due": due_raw,
        "stale": stale,
    }
