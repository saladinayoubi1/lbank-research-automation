#!/usr/bin/env python3
"""Fail-closed verification for a prepared release bundle.

This verifier is intentionally offline and uses only Python's standard library.
It proves internal consistency of a release bundle; it does not create or trust
signing identities, production approvals, credentials, or billing resources.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REQUIRED = ("artifact-manifest.json", "sbom.cdx.json", "provenance.json")


def fail(message: str) -> None:
    raise ValueError(message)


def load_json(path: Path) -> Any:
    try:
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


def verify(bundle: Path, require_signature: bool = True) -> list[str]:
    if not bundle.is_dir():
        fail("release bundle directory does not exist")
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
        if not target.is_file():
            fail(f"manifest artifact missing: {name}")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            fail(f"invalid SHA-256 for: {name}")
        if sha256(target) != digest:
            fail(f"digest mismatch: {name}")
        if not isinstance(size, int) or size < 0 or target.stat().st_size != size:
            fail(f"size mismatch: {name}")

    sbom = load_json(bundle / "sbom.cdx.json")
    if not isinstance(sbom, dict) or sbom.get("bomFormat") != "CycloneDX":
        fail("SBOM must be CycloneDX JSON")
    if not isinstance(sbom.get("specVersion"), str):
        fail("SBOM specVersion is required")
    if not isinstance(sbom.get("components"), list):
        fail("SBOM components must be a list")

    provenance = load_json(bundle / "provenance.json")
    if not isinstance(provenance, dict):
        fail("provenance must be an object")
    if not provenance.get("source_commit") or not provenance.get("builder"):
        fail("provenance requires source_commit and builder")
    subjects = provenance.get("subjects")
    if not isinstance(subjects, list) or not subjects:
        fail("provenance requires non-empty subjects")
    subject_map = {s.get("path"): s.get("sha256") for s in subjects if isinstance(s, dict)}
    for item in entries:
        if subject_map.get(item["path"]) != item["sha256"]:
            fail(f"provenance subject mismatch: {item['path']}")

    if require_signature:
        signature = bundle / "artifact-manifest.sig"
        certificate = bundle / "artifact-manifest.pem"
        if not signature.is_file() or not certificate.is_file():
            fail("signature and signer certificate are required for production release")
        fail("signature identity policy is not configured; production verification is blocked")

    return ["manifest", "sbom", "provenance", "artifact-digests"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--allow-unsigned", action="store_true", help="CI validation only; never production approval")
    args = parser.parse_args()
    try:
        checks = verify(args.bundle, require_signature=not args.allow_unsigned)
    except ValueError as exc:
        print(f"RELEASE_GATE=BLOCKED reason={exc}", file=sys.stderr)
        return 1
    print("RELEASE_GATE=PASS checks=" + ",".join(checks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
