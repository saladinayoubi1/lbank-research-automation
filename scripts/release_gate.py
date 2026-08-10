#!/usr/bin/env python3
"""Fail-closed verification for a prepared release bundle.

This verifier is intentionally offline and uses only Python's standard library.
It proves bounded internal consistency only. It does not prove publisher identity,
vulnerability absence, dependency reachability, or production approval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

REQUIRED = ("artifact-manifest.json", "sbom.cdx.json", "provenance.json")
MAX_JSON_BYTES = 5 * 1024 * 1024
MAX_EVIDENCE_AGE = timedelta(hours=24)
MAX_FUTURE_SKEW = timedelta(minutes=5)
SUPPORTED_CYCLONEDX = {"1.4", "1.5", "1.6"}
COMPLETENESS_STATES = {"complete", "incomplete", "unknown"}


def fail(message: str) -> None:
    raise ValueError(message)


def load_json(path: Path) -> Any:
    try:
        if path.is_symlink():
            fail(f"JSON file must not be a symlink: {path.name}")
        if path.stat().st_size > MAX_JSON_BYTES:
            fail(f"JSON file exceeds {MAX_JSON_BYTES} bytes: {path.name}")
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"missing required file: {path.name}")
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {path.name}: {exc.msg}")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        fail(f"{field} is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        fail(f"{field} must be RFC3339")
    if parsed.tzinfo is None:
        fail(f"{field} must include timezone")
    return parsed.astimezone(timezone.utc)


def verify_freshness(timestamp: datetime, now: datetime, field: str) -> None:
    if timestamp > now + MAX_FUTURE_SKEW:
        fail(f"{field} is too far in the future")
    if now - timestamp > MAX_EVIDENCE_AGE:
        fail(f"{field} is stale")


def verify_sbom(sbom: Any, now: datetime) -> tuple[str, str, datetime]:
    if not isinstance(sbom, dict) or sbom.get("bomFormat") != "CycloneDX":
        fail("SBOM must be CycloneDX JSON")
    if sbom.get("specVersion") not in SUPPORTED_CYCLONEDX:
        fail("unsupported CycloneDX specVersion")

    serial = sbom.get("serialNumber")
    if not isinstance(serial, str) or not serial.startswith("urn:uuid:"):
        fail("SBOM serialNumber must be a UUID URN")
    try:
        UUID(serial.removeprefix("urn:uuid:"))
    except ValueError:
        fail("SBOM serialNumber must be a UUID URN")

    metadata = sbom.get("metadata")
    if not isinstance(metadata, dict):
        fail("SBOM metadata is required")
    timestamp = parse_time(metadata.get("timestamp"), "SBOM metadata.timestamp")
    verify_freshness(timestamp, now, "SBOM metadata.timestamp")

    components = sbom.get("components")
    if not isinstance(components, list) or not components:
        fail("SBOM components must be a non-empty list")

    properties = metadata.get("properties")
    completeness = "unknown"
    if isinstance(properties, list):
        for prop in properties:
            if isinstance(prop, dict) and prop.get("name") == "nexus:graph-completeness":
                completeness = prop.get("value")
                break
    if completeness not in COMPLETENESS_STATES:
        fail("invalid SBOM graph-completeness state")

    refs: set[str] = set()
    for component in components:
        if not isinstance(component, dict):
            fail("SBOM component must be an object")
        ref = component.get("bom-ref")
        if not isinstance(ref, str) or not ref.strip():
            fail("every SBOM component requires a non-empty bom-ref")
        if ref in refs:
            fail(f"duplicate SBOM bom-ref: {ref}")
        refs.add(ref)
        purl = component.get("purl")
        if purl is not None and (not isinstance(purl, str) or not purl.startswith("pkg:") or any(ch.isspace() for ch in purl)):
            fail(f"malformed component purl: {ref}")

    dependencies = sbom.get("dependencies")
    if not isinstance(dependencies, list):
        fail("SBOM dependencies must be a list")
    dependency_refs: set[str] = set()
    edges: dict[str, set[str]] = {}
    for entry in dependencies:
        if not isinstance(entry, dict) or not isinstance(entry.get("ref"), str):
            fail("SBOM dependency entry requires ref")
        ref = entry["ref"]
        if ref not in refs:
            fail(f"unknown dependency ref: {ref}")
        if ref in dependency_refs:
            fail(f"duplicate dependency entry: {ref}")
        dependency_refs.add(ref)
        depends_on = entry.get("dependsOn", [])
        if not isinstance(depends_on, list) or any(not isinstance(x, str) for x in depends_on):
            fail(f"dependsOn must be a string list: {ref}")
        unknown = set(depends_on) - refs
        if unknown:
            fail(f"unknown dependency target: {sorted(unknown)[0]}")
        if ref in depends_on:
            fail(f"self dependency is forbidden: {ref}")
        edges[ref] = set(depends_on)

    if completeness == "complete" and dependency_refs != refs:
        fail("complete SBOM must include one dependency entry per component")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            fail(f"dependency cycle detected: {node}")
        if node in visited:
            return
        visiting.add(node)
        for child in edges.get(node, set()):
            visit(child)
        visiting.remove(node)
        visited.add(node)

    for ref in refs:
        visit(ref)

    return completeness, serial, timestamp


def verify(
    bundle: Path,
    require_signature: bool = True,
    *,
    now: datetime | None = None,
    expected_source_commit: str | None = None,
    expected_builder: str | None = None,
) -> list[str]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if bundle.is_symlink() or not bundle.is_dir():
        fail("release bundle directory does not exist or is a symlink")
    for name in REQUIRED:
        if not (bundle / name).is_file():
            fail(f"missing required file: {name}")

    manifest = load_json(bundle / "artifact-manifest.json")
    entries = manifest.get("artifacts") if isinstance(manifest, dict) else None
    if not isinstance(entries, list) or not entries:
        fail("artifact manifest must contain a non-empty artifacts list")

    seen: set[str] = set()
    for item in entries:
        if not isinstance(item, dict):
            fail("artifact manifest entry must be an object")
        name = item.get("path")
        digest = item.get("sha256")
        size = item.get("size")
        if not isinstance(name, str) or not name or Path(name).is_absolute() or ".." in Path(name).parts:
            fail("artifact path must be a safe relative path")
        if name in seen:
            fail(f"duplicate artifact path: {name}")
        seen.add(name)
        target = bundle / name
        if target.is_symlink():
            fail(f"manifest artifact must not be a symlink: {name}")
        if not target.is_file():
            fail(f"manifest artifact missing: {name}")
        if not valid_sha256(digest):
            fail(f"invalid SHA-256 for: {name}")
        if sha256(target) != digest:
            fail(f"digest mismatch: {name}")
        if not isinstance(size, int) or size < 0 or target.stat().st_size != size:
            fail(f"size mismatch: {name}")

    sbom_path = bundle / "sbom.cdx.json"
    completeness, sbom_serial, sbom_timestamp = verify_sbom(load_json(sbom_path), now)

    provenance = load_json(bundle / "provenance.json")
    if not isinstance(provenance, dict):
        fail("provenance must be an object")
    source_commit = provenance.get("source_commit")
    builder = provenance.get("builder")
    if not isinstance(source_commit, str) or len(source_commit) != 40 or any(c not in "0123456789abcdef" for c in source_commit):
        fail("provenance source_commit must be a lowercase 40-character Git SHA")
    if not isinstance(builder, str) or not builder.strip():
        fail("provenance builder is required")
    if expected_source_commit is not None and source_commit != expected_source_commit:
        fail("provenance source_commit mismatch")
    if expected_builder is not None and builder != expected_builder:
        fail("provenance builder mismatch")

    issued_at = parse_time(provenance.get("issued_at"), "provenance issued_at")
    verify_freshness(issued_at, now, "provenance issued_at")
    if abs((issued_at - sbom_timestamp).total_seconds()) > MAX_FUTURE_SKEW.total_seconds():
        fail("SBOM and provenance timestamps are not coherently bound")
    if provenance.get("sbom_serial_number") != sbom_serial:
        fail("provenance SBOM serial mismatch")
    if provenance.get("sbom_sha256") != sha256(sbom_path):
        fail("provenance SBOM digest mismatch")

    subjects = provenance.get("subjects")
    if not isinstance(subjects, list) or not subjects:
        fail("provenance requires non-empty subjects")
    subject_map: dict[str, str] = {}
    for subject in subjects:
        if not isinstance(subject, dict):
            fail("provenance subject must be an object")
        path = subject.get("path")
        digest = subject.get("sha256")
        if not isinstance(path, str) or not path or Path(path).is_absolute() or ".." in Path(path).parts:
            fail("provenance subject path must be a safe relative path")
        if path in subject_map:
            fail(f"duplicate provenance subject: {path}")
        if not valid_sha256(digest):
            fail(f"invalid provenance subject SHA-256: {path}")
        subject_map[path] = digest
    if set(subject_map) != seen:
        fail("provenance subjects must exactly match manifest artifacts")
    for item in entries:
        if subject_map[item["path"]] != item["sha256"]:
            fail(f"provenance subject mismatch: {item['path']}")

    if require_signature:
        signature = bundle / "artifact-manifest.sig"
        certificate = bundle / "artifact-manifest.pem"
        if not signature.is_file() or not certificate.is_file():
            fail("signature and signer certificate are required for production release")
        fail("signature identity policy is not configured; production verification is blocked")

    return ["manifest", f"sbom-{completeness}", "provenance-fresh", "artifact-digests"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--allow-unsigned", action="store_true", help="CI validation only; never production approval")
    parser.add_argument("--expected-source-commit")
    parser.add_argument("--expected-builder")
    args = parser.parse_args()
    try:
        checks = verify(
            args.bundle,
            require_signature=not args.allow_unsigned,
            expected_source_commit=args.expected_source_commit,
            expected_builder=args.expected_builder,
        )
    except ValueError as exc:
        print(f"RELEASE_GATE=BLOCKED reason={exc}", file=sys.stderr)
        return 1
    print("RELEASE_GATE=PASS checks=" + ",".join(checks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
