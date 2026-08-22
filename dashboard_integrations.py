"""Fail-closed, read-only adapters for dashboard integration summaries."""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from integration_report_provenance import MAX_REPORT_BYTES, ProvenanceError, validate_envelope

ZOTERO_REPORT = "zotero_metadata_report_v2.json"
RESEARCH_REPORT = "research_evidence_summary.json"
SUPPORTED_ZOTERO_SCHEMA = "2.0"
SUPPORTED_RESEARCH_SCHEMAS = {"1.0.0", "1.1.0"}


class IntegrationUnavailableError(RuntimeError):
    """Raised when an integration report cannot be safely summarized."""


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise IntegrationUnavailableError("duplicate JSON key")
        result[key] = value
    return result


def _load_object(path: Path, *, kind: str, now: datetime | None = None) -> dict[str, Any]:
    try:
        before = path.lstat()
        if path.is_symlink() or not path.is_file() or before.st_nlink != 1 or before.st_size < 2 or before.st_size > MAX_REPORT_BYTES:
            raise IntegrationUnavailableError(f"unsafe integration report: {path.name}")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as handle:
            raw = handle.read(MAX_REPORT_BYTES + 1)
            after = os.fstat(handle.fileno())
        if len(raw) > MAX_REPORT_BYTES or (before.st_dev, before.st_ino, before.st_size) != (after.st_dev, after.st_ino, after.st_size):
            raise IntegrationUnavailableError(f"replaced integration report: {path.name}")
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicates)
    except FileNotFoundError as exc:
        raise IntegrationUnavailableError(f"missing integration report: {path.name}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise IntegrationUnavailableError(f"invalid integration report: {path.name}") from exc
    if not isinstance(payload, dict):
        raise IntegrationUnavailableError(f"invalid integration root: {path.name}")
    try:
        return validate_envelope(payload, kind=kind, now=now)
    except ProvenanceError as exc:
        raise IntegrationUnavailableError(str(exc)) from exc


def _count(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100_000:
        raise IntegrationUnavailableError(f"invalid {name}")
    return value


def _text(value: Any, name: str, *, limit: int = 120) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise IntegrationUnavailableError(f"invalid {name}")
    return value


def load_zotero_summary(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    payload = _load_object(root / ZOTERO_REPORT, kind="zotero", now=now)
    if set(payload) != {"schema_version", "mode", "item_count", "finding_count", "items", "duplicates"}:
        raise IntegrationUnavailableError("unknown Zotero report fields")
    if payload.get("schema_version") != SUPPORTED_ZOTERO_SCHEMA:
        raise IntegrationUnavailableError("unsupported Zotero report schema")
    if payload.get("mode") != "read-only-offline":
        raise IntegrationUnavailableError("unsafe Zotero report mode")
    required = ("item_count", "finding_count", "items", "duplicates")
    if any(key not in payload for key in required):
        raise IntegrationUnavailableError("incomplete Zotero report")
    if not isinstance(payload["items"], list) or len(payload["items"]) > 100_000 or not isinstance(payload["duplicates"], dict) or set(payload["duplicates"]) != {"doi", "title_year"}:
        raise IntegrationUnavailableError("invalid Zotero report structure")
    if any(not isinstance(payload["duplicates"][key], list) or len(payload["duplicates"][key]) > 100_000 for key in ("doi", "title_year")):
        raise IntegrationUnavailableError("invalid Zotero duplicate groups")
    item_count = _count(payload["item_count"], "Zotero item count")
    finding_count = _count(payload["finding_count"], "Zotero finding count")
    if len(payload["items"]) > item_count or finding_count < len(payload["items"]):
        raise IntegrationUnavailableError("inconsistent Zotero counts")
    return {
        "schema_version": payload["schema_version"],
        "mode": payload["mode"],
        "item_count": item_count,
        "finding_count": finding_count,
        "duplicate_doi_groups": len(payload["duplicates"].get("doi", [])),
        "duplicate_title_year_groups": len(payload["duplicates"].get("title_year", [])),
        "status": "attention" if finding_count else "clean",
    }


def load_research_summary(root: Path, *, today: date | None = None, now: datetime | None = None) -> dict[str, Any]:
    payload = _load_object(root / RESEARCH_REPORT, kind="research", now=now)
    if set(payload) != {"schema_version", "status", "paper_trading_only", "next_review_due", "claims", "evidence"}:
        raise IntegrationUnavailableError("unknown Research report fields")
    schema = payload.get("schema_version")
    if schema not in SUPPORTED_RESEARCH_SCHEMAS:
        raise IntegrationUnavailableError("unsupported Research report schema")
    if payload.get("status") != "research-only" or payload.get("paper_trading_only") is not True:
        raise IntegrationUnavailableError("unsafe Research report boundary")
    claims = payload.get("claims")
    evidence = payload.get("evidence")
    if not isinstance(claims, list) or not isinstance(evidence, list) or len(claims) > 10_000 or len(evidence) > 10_000:
        raise IntegrationUnavailableError("invalid Research report structure")
    evidence_ids: set[str] = set()
    domains: set[str] = set()
    for item in evidence:
        if not isinstance(item, dict) or set(item) != {"id", "domain"}:
            raise IntegrationUnavailableError("invalid Research evidence")
        evidence_id = _text(item["id"], "evidence id")
        domain = _text(item["domain"], "evidence domain")
        if evidence_id in evidence_ids:
            raise IntegrationUnavailableError("duplicate Research evidence id")
        evidence_ids.add(evidence_id)
        domains.add(domain)
    claim_ids: set[str] = set()
    for item in claims:
        if not isinstance(item, dict) or set(item) != {"id", "evidence_ids"} or not isinstance(item["evidence_ids"], list) or not item["evidence_ids"] or len(item["evidence_ids"]) > 100:
            raise IntegrationUnavailableError("invalid Research claim")
        claim_id = _text(item["id"], "claim id")
        refs = [_text(ref, "claim evidence reference") for ref in item["evidence_ids"]]
        if claim_id in claim_ids or len(refs) != len(set(refs)) or not set(refs) <= evidence_ids:
            raise IntegrationUnavailableError("invalid Research claim binding")
        claim_ids.add(claim_id)
    due_raw = payload.get("next_review_due")
    stale = False
    if not isinstance(due_raw, str):
        raise IntegrationUnavailableError("missing Research review date")
    try:
        due = date.fromisoformat(due_raw)
    except ValueError as exc:
        raise IntegrationUnavailableError("invalid Research review date") from exc
    current = today or date.today()
    if (due - current).days > 366:
        raise IntegrationUnavailableError("untrusted future Research review date")
    stale = due < current
    return {
        "schema_version": schema,
        "status": payload["status"],
        "paper_trading_only": True,
        "claim_count": len(claims),
        "evidence_count": len(evidence),
        "domain_count": len(domains),
        "domains": sorted(domains),
        "next_review_due": due_raw,
        "stale": stale,
    }
