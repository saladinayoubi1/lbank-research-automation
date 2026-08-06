#!/usr/bin/env python3
"""Validate the NEXUS market-structure/risk/backtesting evidence matrix.

The validator is offline, read-only, dependency-free, and fail-closed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DOMAINS = {"market_structure", "risk", "backtesting"}
SOURCE_TYPES = {"authoritative", "academic", "limitation"}
CONFIDENCE = {"low", "medium", "high"}
REQUIRED_TOP_LEVEL = {
    "schema_version",
    "matrix_id",
    "status",
    "paper_trading_only",
    "review_date",
    "next_review_due",
    "scope",
    "safety_boundary",
    "obsolescence_triggers",
    "evidence",
}
REQUIRED_RECORD_FIELDS = {
    "id",
    "domain",
    "claim",
    "source_type",
    "title",
    "publisher_or_authors",
    "year",
    "url_or_doi",
    "applicability",
    "limitations",
    "confidence",
    "verification_status",
    "review_date",
    "obsolescence_triggers",
}


def nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def valid_https_url(value: Any) -> bool:
    if not nonempty_text(value):
        return False
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def validate_document(document: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["root must be a JSON object"]

    missing_top = sorted(REQUIRED_TOP_LEVEL - document.keys())
    if missing_top:
        errors.append(f"missing top-level fields: {', '.join(missing_top)}")
        return errors

    if document["status"] != "research-only":
        errors.append("status must be 'research-only'")
    if document["paper_trading_only"] is not True:
        errors.append("paper_trading_only must be true")
    if not isinstance(document["obsolescence_triggers"], list) or not document["obsolescence_triggers"]:
        errors.append("top-level obsolescence_triggers must be a non-empty list")

    records = document["evidence"]
    if not isinstance(records, list) or not records:
        errors.append("evidence must be a non-empty list")
        return errors

    seen_ids: set[str] = set()
    coverage = {domain: set() for domain in DOMAINS}

    for index, record in enumerate(records):
        prefix = f"evidence[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{prefix} must be an object")
            continue

        missing = sorted(REQUIRED_RECORD_FIELDS - record.keys())
        if missing:
            errors.append(f"{prefix} missing fields: {', '.join(missing)}")
            continue

        record_id = record["id"]
        if not nonempty_text(record_id):
            errors.append(f"{prefix}.id must be non-empty text")
        elif record_id in seen_ids:
            errors.append(f"duplicate evidence id: {record_id}")
        else:
            seen_ids.add(record_id)

        domain = record["domain"]
        source_type = record["source_type"]
        if domain not in DOMAINS:
            errors.append(f"{prefix}.domain must be one of {sorted(DOMAINS)}")
        if source_type not in SOURCE_TYPES:
            errors.append(f"{prefix}.source_type must be one of {sorted(SOURCE_TYPES)}")
        if domain in DOMAINS and source_type in SOURCE_TYPES:
            coverage[domain].add(source_type)

        for field in (
            "claim",
            "title",
            "publisher_or_authors",
            "applicability",
            "limitations",
            "verification_status",
            "review_date",
        ):
            if not nonempty_text(record[field]):
                errors.append(f"{prefix}.{field} must be non-empty text")

        if not isinstance(record["year"], int) or not 1900 <= record["year"] <= 2100:
            errors.append(f"{prefix}.year must be an integer from 1900 through 2100")
        if not valid_https_url(record["url_or_doi"]):
            errors.append(f"{prefix}.url_or_doi must be an HTTPS URL or DOI URL")
        if record["confidence"] not in CONFIDENCE:
            errors.append(f"{prefix}.confidence must be one of {sorted(CONFIDENCE)}")
        if not isinstance(record["obsolescence_triggers"], list) or not record["obsolescence_triggers"]:
            errors.append(f"{prefix}.obsolescence_triggers must be a non-empty list")

    for domain, source_types in sorted(coverage.items()):
        for required_type in ("authoritative", "academic", "limitation"):
            if required_type not in source_types:
                errors.append(f"{domain} lacks required source_type '{required_type}'")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "path",
        nargs="?",
        default="research/evidence/market_structure_risk_backtesting_matrix.json",
        type=Path,
    )
    args = parser.parse_args()

    try:
        raw = args.path.read_text(encoding="utf-8")
        document = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"INVALID: cannot read valid JSON: {exc}", file=sys.stderr)
        return 1

    errors = validate_document(document)
    if errors:
        for error in errors:
            print(f"INVALID: {error}", file=sys.stderr)
        return 1

    print(
        f"VALID: {args.path} contains {len(document['evidence'])} evidence records "
        f"across {len(DOMAINS)} required domains."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
