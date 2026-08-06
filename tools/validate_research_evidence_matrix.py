#!/usr/bin/env python3
"""Validate NEXUS research evidence matrices offline and fail closed."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DOMAINS = {
    "market_structure", "risk", "backtesting",
    "execution_costs", "nonstationarity", "model_validation",
}
SOURCE_TYPES = {"authoritative", "academic", "limitation"}
CONFIDENCE = {"low", "medium", "high"}
VERIFICATION_STATUS = {
    "official-page-verified", "official-document-verified",
    "official-framework-verified", "doi-metadata-verified",
    "doi-and-institutional-metadata-verified", "bibliographic-metadata-verified",
}
REQUIRED_TOP_LEVEL = {
    "schema_version", "matrix_id", "status", "paper_trading_only",
    "review_date", "next_review_due", "scope", "safety_boundary",
    "obsolescence_triggers", "evidence",
}
REQUIRED_RECORD_FIELDS = {
    "id", "domain", "claim", "source_type", "title",
    "publisher_or_authors", "year", "url_or_doi", "applicability",
    "limitations", "confidence", "verification_status", "review_date",
    "obsolescence_triggers",
}


def nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def valid_https_url(value: Any) -> bool:
    if not nonempty_text(value):
        return False
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc) and " " not in value


def parse_iso_date(value: Any) -> date | None:
    if not nonempty_text(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def validate_document(document: Any, *, today: date | None = None) -> list[str]:
    today = today or date.today()
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["root must be a JSON object"]
    missing_top = sorted(REQUIRED_TOP_LEVEL - document.keys())
    if missing_top:
        return [f"missing top-level fields: {', '.join(missing_top)}"]
    if document["status"] != "research-only":
        errors.append("status must be 'research-only'")
    if document["paper_trading_only"] is not True:
        errors.append("paper_trading_only must be true")
    review_date = parse_iso_date(document["review_date"])
    due_date = parse_iso_date(document["next_review_due"])
    if review_date is None or due_date is None:
        errors.append("top-level review_date and next_review_due must be ISO dates")
    elif today > due_date:
        errors.append("top-level review fields are stale")
    triggers = document["obsolescence_triggers"]
    if not isinstance(triggers, list) or not triggers or not all(nonempty_text(x) for x in triggers):
        errors.append("top-level obsolescence_triggers must be a non-empty text list")

    records = document["evidence"]
    if not isinstance(records, list) or not records:
        return errors + ["evidence must be a non-empty list"]

    claims = document.get("claims", [])
    claim_ids: set[str] = set()
    claim_sources: dict[str, set[str]] = {}
    if claims:
        if not isinstance(claims, list):
            errors.append("claims must be a list")
        else:
            for index, claim in enumerate(claims):
                prefix = f"claims[{index}]"
                if not isinstance(claim, dict):
                    errors.append(f"{prefix} must be an object")
                    continue
                cid = claim.get("claim_id")
                refs = claim.get("source_ids")
                if not nonempty_text(cid) or cid in claim_ids:
                    errors.append(f"{prefix}.claim_id must be unique non-empty text")
                else:
                    claim_ids.add(cid)
                if not nonempty_text(claim.get("text")):
                    errors.append(f"{prefix}.text must be non-empty")
                if not isinstance(refs, list) or not refs or not all(nonempty_text(x) for x in refs):
                    errors.append(f"{prefix}.source_ids must be a non-empty text list")
                elif nonempty_text(cid):
                    claim_sources[cid] = set(refs)

    seen_ids: set[str] = set()
    coverage: dict[str, set[str]] = {}
    evidence_claim_links: dict[str, set[str]] = {}
    for index, record in enumerate(records):
        prefix = f"evidence[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{prefix} must be an object")
            continue
        missing = sorted(REQUIRED_RECORD_FIELDS - record.keys())
        if missing:
            errors.append(f"{prefix} missing fields: {', '.join(missing)}")
            continue
        rid = record["id"]
        if not nonempty_text(rid):
            errors.append(f"{prefix}.id must be non-empty text")
        elif rid in seen_ids:
            errors.append(f"duplicate evidence id: {rid}")
        else:
            seen_ids.add(rid)
        domain = record["domain"]
        source_type = record["source_type"]
        if domain not in DOMAINS:
            errors.append(f"{prefix}.domain unsupported")
        if source_type not in SOURCE_TYPES:
            errors.append(f"{prefix}.source_type unsupported")
        if domain in DOMAINS and source_type in SOURCE_TYPES:
            coverage.setdefault(domain, set()).add(source_type)
        for field in ("claim", "title", "publisher_or_authors", "applicability", "limitations"):
            if not nonempty_text(record[field]):
                errors.append(f"{prefix}.{field} must be non-empty text")
        if not valid_https_url(record["url_or_doi"]):
            errors.append(f"{prefix}.url_or_doi must be a valid HTTPS URL")
        if record["confidence"] not in CONFIDENCE:
            errors.append(f"{prefix}.confidence unsupported")
        if record["verification_status"] not in VERIFICATION_STATUS:
            errors.append(f"{prefix}.verification_status unsupported")
        record_review = parse_iso_date(record["review_date"])
        if record_review is None or (today - record_review).days > 365:
            errors.append(f"{prefix}.review_date is invalid or stale")
        if "source_verification_date" in record:
            verified = parse_iso_date(record["source_verification_date"])
            if verified is None or verified > today or (today - verified).days > 365:
                errors.append(f"{prefix}.source_verification_date is invalid or stale")
        elif claims:
            errors.append(f"{prefix}.source_verification_date is required")
        record_triggers = record["obsolescence_triggers"]
        if not isinstance(record_triggers, list) or not record_triggers or not all(nonempty_text(x) for x in record_triggers):
            errors.append(f"{prefix}.obsolescence_triggers must be a non-empty text list")
        links = record.get("claim_ids", [])
        if claims:
            if not isinstance(links, list) or not links:
                errors.append(f"{prefix}.claim_ids must be a non-empty list")
            else:
                evidence_claim_links[rid] = set(links)
                for cid in links:
                    if cid not in claim_ids:
                        errors.append(f"{prefix} references unknown claim_id {cid}")

    for domain in sorted(set(document.get("scope", [])) & DOMAINS):
        for required_type in SOURCE_TYPES:
            if required_type not in coverage.get(domain, set()):
                errors.append(f"{domain} lacks required source_type '{required_type}'")
    for cid, source_ids in claim_sources.items():
        for source_id in source_ids:
            if source_id not in seen_ids:
                errors.append(f"claim {cid} references unknown source_id {source_id}")
            elif cid not in evidence_claim_links.get(source_id, set()):
                errors.append(f"claim/source traceability mismatch: {cid} -> {source_id}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", default="research/evidence/market_structure_risk_backtesting_matrix.json", type=Path)
    args = parser.parse_args()
    try:
        document = json.loads(args.path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"INVALID: cannot read valid JSON: {exc}", file=sys.stderr)
        return 1
    errors = validate_document(document)
    if errors:
        for error in errors:
            print(f"INVALID: {error}", file=sys.stderr)
        return 1
    print(f"VALID: {args.path} contains {len(document['evidence'])} evidence records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
