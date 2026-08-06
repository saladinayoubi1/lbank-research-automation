#!/usr/bin/env python3
"""Read-only audit for Zotero JSON exports.

The tool never calls the Zotero API and never mutates the input file. It reports
missing core metadata and conservative duplicate candidates to stdout.
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

DOI_PREFIX = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)
SPACE = re.compile(r"\s+")
YEAR = re.compile(r"(?:19|20)\d{2}")


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


def audit(items: list[dict[str, Any]]) -> dict[str, Any]:
    missing: list[dict[str, Any]] = []
    doi_groups: dict[str, list[int]] = defaultdict(list)
    title_year_groups: dict[tuple[str, str], list[int]] = defaultdict(list)

    for index, item in enumerate(items):
        title = normalize_text(item.get("title"))
        doi = normalize_doi(item.get("DOI") or item.get("doi"))
        year = extract_year(item)
        item_type = normalize_text(item.get("itemType"))

        absent = [name for name, value in (("title", title), ("year", year)) if not value]
        if item_type in {"journalarticle", "conferencepaper", "preprint"} and not doi:
            absent.append("DOI")
        if absent:
            missing.append({"index": index, "missing": absent, "title": item.get("title", "")})

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
        {"title": title, "year": year, "indexes": indexes}
        for (title, year), indexes in sorted(title_year_groups.items())
        if len(indexes) > 1
    ]

    return {
        "item_count": len(items),
        "missing_metadata": missing,
        "duplicate_doi_candidates": duplicate_doi,
        "duplicate_title_year_candidates": duplicate_title_year,
        "read_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path, help="Path to a Zotero JSON export")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args()

    try:
        report = audit(load_items(args.export))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"zotero metadata audit failed: {exc}", file=sys.stderr)
        return 2

    if args.json:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
        print()
    else:
        print(f"Items: {report['item_count']}")
        print(f"Missing metadata: {len(report['missing_metadata'])}")
        print(f"Duplicate DOI candidates: {len(report['duplicate_doi_candidates'])}")
        print(
            "Duplicate title/year candidates: "
            f"{len(report['duplicate_title_year_candidates'])}"
        )
        print("Mode: read-only")

    has_findings = any(
        report[key]
        for key in (
            "missing_metadata",
            "duplicate_doi_candidates",
            "duplicate_title_year_candidates",
        )
    )
    return 1 if has_findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
