#!/usr/bin/env python3
"""Validate and optionally upload CSL JSON items to Zotero Web API."""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REQUIRED = ("title", "type")
ALLOWED_TYPES = {"article-journal", "book", "chapter", "paper-conference", "report", "thesis", "webpage"}


def load_items(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError("input must be a non-empty JSON array")
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"item[{i}] must be an object")
        for field in REQUIRED:
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ValueError(f"item[{i}].{field} is required")
        if item["type"] not in ALLOWED_TYPES:
            raise ValueError(f"item[{i}].type is unsupported: {item['type']}")
        identity = str(item.get("DOI") or item.get("URL") or item["title"]).strip().lower()
        if identity in seen:
            raise ValueError(f"duplicate item identity: {identity}")
        seen.add(identity)
        items.append(item)
    return items


def to_zotero(item: dict[str, Any], collection_key: str | None) -> dict[str, Any]:
    type_map = {
        "article-journal": "journalArticle", "book": "book", "chapter": "bookSection",
        "paper-conference": "conferencePaper", "report": "report", "thesis": "thesis", "webpage": "webpage",
    }
    creators = []
    for author in item.get("author", []):
        if isinstance(author, dict):
            creators.append({"creatorType": "author", "firstName": author.get("given", ""), "lastName": author.get("family", "")})
    payload: dict[str, Any] = {
        "itemType": type_map[item["type"]], "title": item["title"], "creators": creators,
        "date": str(item.get("issued", {}).get("date-parts", [[""]])[0][0]),
        "DOI": item.get("DOI", ""), "url": item.get("URL", ""),
        "abstractNote": item.get("abstract", ""), "tags": [{"tag": t} for t in item.get("keyword", "").split(",") if t.strip()],
    }
    if collection_key:
        payload["collections"] = [collection_key]
    return payload


def upload(items: list[dict[str, Any]], *, library_id: str, api_key: str, collection_key: str | None) -> None:
    url = f"https://api.zotero.org/users/{library_id}/items"
    body = json.dumps([to_zotero(i, collection_key) for i in items]).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json", "Zotero-API-Key": api_key, "Zotero-API-Version": "3"
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            if response.status not in (200, 201):
                raise RuntimeError(f"unexpected Zotero status: {response.status}")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Zotero API rejected request: HTTP {exc.code}") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--apply", action="store_true", help="perform remote write; default is dry-run")
    parser.add_argument("--collection-key")
    args = parser.parse_args()
    try:
        items = load_items(args.input)
        if args.apply:
            api_key = os.environ.get("ZOTERO_API_KEY")
            library_id = os.environ.get("ZOTERO_LIBRARY_ID")
            if not api_key or not library_id:
                raise ValueError("ZOTERO_API_KEY and ZOTERO_LIBRARY_ID are required for --apply")
            upload(items, library_id=library_id, api_key=api_key, collection_key=args.collection_key)
        print(json.dumps({"valid": True, "count": len(items), "applied": bool(args.apply)}, sort_keys=True))
        return 0
    except (OSError, json.JSONDecodeError, ValueError, RuntimeError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
