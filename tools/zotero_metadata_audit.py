#!/usr/bin/env python3
"""Read-only, offline metadata quality audit for Zotero JSON exports.

The tool only reads the supplied export file. It never calls the Zotero API,
uses credentials, or mutates library items, collections, or sync state.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "2.0"
DOI_PREFIX = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)
SPACE = re.compile(r"\s+")
YEAR = re.compile(r"(?:19|20)\d{2}")
ARTICLE_TYPES = {"journalarticle", "conferencepaper", "preprint"}


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    return SPACE.sub(" ", text)


def normalize_doi(value: Any) -> str:
    return DOI_PREFIX.sub("", normalize_text(value)).strip()


def extract_year(item: dict[str, Any]) -> str:
    date = normalize_text(item.get("date"))
    match = YEAR.search(date)
    return match.group(0) if match else ""


def load_items(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict) and isinstance(payload.get("items"), list):
        items = payload["items"]
    else:
        raise ValueError("expected a Zotero JSON list or an object with an 'items' list")

    if not all(isinstance(item, dict) for item in items):
        raise ValueError("every Zotero item must be a JSON object")
    return items


def creator_findings(item: dict[str, Any]) -> list[str]:
    creators = item.get("creators")
    if not isinstance(creators, list) or not creators:
        return ["missing_creators"]

    findings: set[str] = set()
    for creator in creators:
        if not isinstance(creator, dict):
            findings.add("invalid_creator_object")
            continue
        name = normalize_text(creator.get("name"))
        first = normalize_text(creator.get("firstName"))
        last = normalize_text(creator.get("lastName"))
        if not name and not last:
            findings.add("missing_creator_name")
        if last and not first and not name:
            findings.add("missing_creator_first_name")
    return sorted(findings)


def audit(items: list[dict[str, Any]]) -> dict[str, Any]:
    item_findings: list[dict[str, Any]] = []
    doi_groups: dict[str, list[int]] = defaultdict(list)
    title_year_groups: dict[tuple[str, str], list[int]] = defaultdict(list)

    for index, item in enumerate(items):
        title = normalize_text(item.get("title"))
        doi = normalize_doi(item.get("DOI") or item.get("doi"))
        year = extract_year(item)
        item_type = normalize_text(item.get("itemType"))

        missing = [name for name, value in (("title", title), ("year", year)) if not value]
        if item_type in ARTICLE_TYPES and not doi:
            missing.append("DOI")
        creators = creator_findings(item)
        if missing or creators:
            item_findings.append(
                {
                    "creator_findings": creators,
                    "index": index,
                    "missing_fields": missing,
                    "title": str(item.get("title", "")),
                }
            )

        if doi:
            doi_groups[doi].append(index)
        if title and year:
            title_year_groups[(title, year)].append(index)

    duplicate_doi = [
        {"doi": doi, "indexes": indexes}
        for doi, indexes in sorted(doi_groups.items())
        if len(indexes) > 1
    ]
    duplicate_title_year = [
        {"indexes": indexes, "title": title, "year": year}
        for (title, year), indexes in sorted(title_year_groups.items())
        if len(indexes) > 1
    ]

    finding_count = (
        sum(len(entry["missing_fields"]) + len(entry["creator_findings"]) for entry in item_findings)
        + len(duplicate_doi)
        + len(duplicate_title_year)
    )
    return {
        "duplicates": {
            "doi": duplicate_doi,
            "title_year": duplicate_title_year,
        },
        "finding_count": finding_count,
        "item_count": len(items),
        "items": item_findings,
        "mode": "read-only-offline",
        "schema_version": SCHEMA_VERSION,
    }


def write_json(report: dict[str, Any]) -> None:
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path, help="Path to a Zotero JSON export")
    parser.add_argument("--json", action="store_true", help="Emit the stable JSON report")
    args = parser.parse_args(argv)

    try:
        report = audit(load_items(args.export))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"zotero metadata audit failed: {exc}", file=sys.stderr)
        return 2

    if args.json:
        write_json(report)
    else:
        print(f"Items: {report['item_count']}")
        print(f"Findings: {report['finding_count']}")
        print(f"Items with metadata findings: {len(report['items'])}")
        print(f"Duplicate DOI candidates: {len(report['duplicates']['doi'])}")
        print(f"Duplicate title/year candidates: {len(report['duplicates']['title_year'])}")
        print("Mode: read-only-offline")

    return 1 if report["finding_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
