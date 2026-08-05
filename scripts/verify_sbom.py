#!/usr/bin/env python3
"""Fail-closed verifier for a bounded CycloneDX JSON SBOM profile."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
ALLOWED_SPEC_VERSIONS = {"1.4", "1.5", "1.6"}
ALLOWED_COMPONENT_TYPES = {
    "application", "container", "device", "file", "firmware", "framework",
    "library", "machine-learning-model", "operating-system", "platform",
}


class SbomError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SbomError(message)


def _canonical_digest(document: dict[str, Any]) -> str:
    payload = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_sbom(document: Any) -> dict[str, Any]:
    _require(isinstance(document, dict), "SBOM root must be an object")
    _require(document.get("bomFormat") == "CycloneDX", "bomFormat must be CycloneDX")
    _require(document.get("specVersion") in ALLOWED_SPEC_VERSIONS, "unsupported specVersion")
    _require(document.get("version") == 1, "version must be 1")

    components = document.get("components")
    _require(isinstance(components, list), "components must be an array")
    refs: set[str] = set()
    purls: set[str] = set()

    for index, component in enumerate(components):
        prefix = f"components[{index}]"
        _require(isinstance(component, dict), f"{prefix} must be an object")
        ref = component.get("bom-ref")
        _require(isinstance(ref, str) and ref.strip(), f"{prefix}.bom-ref is required")
        _require(ref not in refs, f"duplicate bom-ref: {ref}")
        refs.add(ref)
        _require(component.get("type") in ALLOWED_COMPONENT_TYPES, f"{prefix}.type is invalid")
        _require(isinstance(component.get("name"), str) and component["name"].strip(), f"{prefix}.name is required")
        _require(isinstance(component.get("version"), str) and component["version"].strip(), f"{prefix}.version is required")

        purl = component.get("purl")
        _require(isinstance(purl, str) and purl.startswith("pkg:"), f"{prefix}.purl is required")
        _require(purl not in purls, f"duplicate purl: {purl}")
        purls.add(purl)

        hashes = component.get("hashes")
        _require(isinstance(hashes, list) and hashes, f"{prefix}.hashes must be non-empty")
        sha256_values = [h.get("content") for h in hashes if isinstance(h, dict) and h.get("alg") == "SHA-256"]
        _require(len(sha256_values) == 1, f"{prefix} must contain exactly one SHA-256 hash")
        _require(isinstance(sha256_values[0], str) and SHA256_RE.fullmatch(sha256_values[0]) is not None,
                 f"{prefix} SHA-256 must be 64 hexadecimal characters")

    dependencies = document.get("dependencies", [])
    _require(isinstance(dependencies, list), "dependencies must be an array")
    dependency_entries: set[str] = set()
    for index, dependency in enumerate(dependencies):
        prefix = f"dependencies[{index}]"
        _require(isinstance(dependency, dict), f"{prefix} must be an object")
        ref = dependency.get("ref")
        _require(ref in refs, f"{prefix}.ref references unknown component: {ref}")
        _require(ref not in dependency_entries, f"duplicate dependency entry: {ref}")
        dependency_entries.add(ref)
        depends_on = dependency.get("dependsOn", [])
        _require(isinstance(depends_on, list), f"{prefix}.dependsOn must be an array")
        _require(len(depends_on) == len(set(depends_on)), f"{prefix}.dependsOn contains duplicates")
        for target in depends_on:
            _require(target in refs, f"{prefix}.dependsOn references unknown component: {target}")
            _require(target != ref, f"{prefix} contains a self-dependency")

    return {
        "valid": True,
        "componentCount": len(components),
        "dependencyEntryCount": len(dependencies),
        "canonicalSha256": _canonical_digest(document),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sbom", type=Path)
    args = parser.parse_args()
    try:
        raw = args.sbom.read_text(encoding="utf-8")
        document = json.loads(raw)
        result = verify_sbom(document)
    except (OSError, json.JSONDecodeError, SbomError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
