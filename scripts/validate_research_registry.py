#!/usr/bin/env python3
"""Fail-closed validation for the versioned NEXUS research registry."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "research" / "evidence_registry.json"
SCHEMA = "nexus.research-evidence-registry.v1"
AUTHORITY = ["bybit-primary", "binance-secondary-corroboration", "lbank-tertiary-legacy-research-only"]
ENTRY_KEYS = {"id", "path", "sha256", "format", "domains"}
FORMATS = {"evidence-matrix-json", "evidence-matrix-markdown", "bibtex"}
SAFE_ID = re.compile(r"^[A-Z0-9][A-Z0-9-]{5,79}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _json(path: Path, limit: int = 1_000_000) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError(f"unsafe file: {path}")
    raw = path.read_bytes()
    if not raw or len(raw) > limit:
        raise ValueError(f"empty or oversized file: {path}")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _safe_repo_file(raw: Any) -> Path:
    if not isinstance(raw, str) or not raw or len(raw) > 200 or "\\" in raw:
        raise ValueError("invalid registry path")
    relative = PurePosixPath(raw)
    if relative.is_absolute() or ".." in relative.parts or raw != relative.as_posix():
        raise ValueError("non-canonical registry path")
    path = ROOT.joinpath(*relative.parts)
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError(f"unsafe registry target: {raw}")
    return path


def _canonical_text_bytes(path: Path) -> bytes:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"registry target is not UTF-8 text: {path}") from exc
    text = text.replace("\r\n", "\n")
    if "\r" in text:
        raise ValueError(f"registry target contains non-canonical line endings: {path}")
    return text.encode("utf-8")


def _validate_matrix(path: Path) -> None:
    matrix = _json(path)
    if matrix.get("status") != "research-only" or matrix.get("paper_trading_only") is not True:
        raise ValueError(f"unsafe evidence boundary: {path}")
    due = matrix.get("next_review_due")
    try:
        parsed_due = date.fromisoformat(due)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid review date: {path}") from exc
    if parsed_due < date.today():
        raise ValueError(f"review overdue: {path}")
    evidence = matrix.get("evidence")
    if not isinstance(evidence, list) or not evidence or len(evidence) > 10_000:
        raise ValueError(f"invalid evidence list: {path}")
    ids: set[str] = set()
    for row in evidence:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or row["id"] in ids:
            raise ValueError(f"invalid or duplicate evidence id: {path}")
        ids.add(row["id"])
        for key in ("domain", "claim", "source_type", "title", "publisher_or_authors", "url_or_doi", "applicability", "limitations", "confidence", "verification_status"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError(f"missing evidence field {key}: {path}")
    claims = matrix.get("claims", [])
    if claims:
        claim_ids: set[str] = set()
        for claim in claims:
            if not isinstance(claim, dict) or not isinstance(claim.get("claim_id"), str) or claim["claim_id"] in claim_ids:
                raise ValueError(f"invalid or duplicate claim id: {path}")
            refs = claim.get("source_ids")
            if not isinstance(refs, list) or not refs or len(refs) != len(set(refs)) or not set(refs) <= ids:
                raise ValueError(f"invalid claim binding: {path}")
            claim_ids.add(claim["claim_id"])


def validate(path: Path = DEFAULT_REGISTRY) -> None:
    registry = _json(path)
    if set(registry) != {"schema", "status", "paper_trading_only", "market_authority", "protocol", "max_review_age_days", "entries"}:
        raise ValueError("registry schema mismatch")
    if registry["schema"] != SCHEMA or registry["status"] != "research-only" or registry["paper_trading_only"] is not True:
        raise ValueError("unsafe registry boundary")
    if registry["market_authority"] != AUTHORITY:
        raise ValueError("market authority mismatch")
    if isinstance(registry["max_review_age_days"], bool) or registry["max_review_age_days"] != 365:
        raise ValueError("review policy mismatch")
    protocol = _safe_repo_file(registry["protocol"])
    if protocol.stat().st_size > 100_000:
        raise ValueError("protocol is oversized")
    entries = registry["entries"]
    if not isinstance(entries, list) or not entries or len(entries) > 1_000:
        raise ValueError("invalid registry entries")
    ids: set[str] = set()
    paths: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != ENTRY_KEYS:
            raise ValueError("registry entry schema mismatch")
        if not isinstance(entry["id"], str) or not SAFE_ID.fullmatch(entry["id"]) or entry["id"] in ids:
            raise ValueError("invalid or duplicate registry id")
        if entry["path"] in paths:
            raise ValueError("duplicate registry path")
        if entry["format"] not in FORMATS:
            raise ValueError("unsupported registry format")
        if not isinstance(entry["domains"], list) or not entry["domains"] or len(entry["domains"]) != len(set(entry["domains"])):
            raise ValueError("invalid registry domains")
        target = _safe_repo_file(entry["path"])
        digest = hashlib.sha256(_canonical_text_bytes(target)).hexdigest()
        if not isinstance(entry["sha256"], str) or not SHA256.fullmatch(entry["sha256"]) or digest != entry["sha256"]:
            raise ValueError(f"registry digest mismatch: {entry['path']}")
        if entry["format"] == "evidence-matrix-json":
            _validate_matrix(target)
        ids.add(entry["id"])
        paths.add(entry["path"])


def main() -> int:
    try:
        validate(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_REGISTRY)
    except (OSError, ValueError) as exc:
        print(f"RESEARCH_REGISTRY_GATE=FAIL reason={exc}", file=sys.stderr)
        return 1
    print("RESEARCH_REGISTRY_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
