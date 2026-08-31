#!/usr/bin/env python3
"""Create an unsigned CI evidence bundle for built artifacts.

This tool produces artifact-manifest.json, CycloneDX SBOM metadata, and provenance
bound to an exact source commit, builder, and optional explicit build parameters.
It deliberately does not sign or approve a production release. The resulting
bundle must still pass release_gate.py with --allow-unsigned before it is uploaded
as CI evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expand_globs(patterns: list[str]) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        matches = sorted(Path.cwd().glob(pattern))
        if not matches:
            raise ValueError(f"artifact glob matched no files: {pattern}")
        for match in matches:
            if match.is_symlink() or not match.is_file():
                raise ValueError(f"artifact must be a regular non-symlink file: {match}")
            resolved = match.resolve()
            if resolved not in seen:
                seen.add(resolved)
                files.append(match)
    if not files:
        raise ValueError("at least one artifact is required")
    return files


def normalize_build_parameters(build_parameters: dict[str, str] | None) -> dict[str, str]:
    if build_parameters is None:
        return {}
    if not isinstance(build_parameters, dict):
        raise ValueError("build parameters must be a mapping")
    normalized: dict[str, str] = {}
    for key, value in build_parameters.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("build parameter key must be a non-empty string")
        if key != key.strip():
            raise ValueError(f"build parameter key must not have surrounding whitespace: {key!r}")
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"build parameter value must be a non-empty string: {key}")
        if value != value.strip():
            raise ValueError(f"build parameter value must not have surrounding whitespace: {key}")
        normalized[key] = value
    return dict(sorted(normalized.items()))


def parse_build_parameter_args(values: list[str] | None) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw in values or []:
        if "=" not in raw:
            raise ValueError("build parameter must use key=value syntax")
        key, value = raw.split("=", 1)
        if key in parsed:
            raise ValueError(f"duplicate build parameter: {key}")
        parsed[key] = value
    return normalize_build_parameters(parsed)


def build_bundle(
    bundle_dir: Path,
    artifact_globs: list[str],
    source_commit: str,
    builder: str,
    build_parameters: dict[str, str] | None = None,
) -> None:
    if len(source_commit) != 40 or any(c not in "0123456789abcdef" for c in source_commit):
        raise ValueError("source commit must be a lowercase 40-character Git SHA")
    if not builder.strip():
        raise ValueError("builder is required")
    parameters = normalize_build_parameters(build_parameters)
    if bundle_dir.exists():
        if bundle_dir.is_symlink():
            raise ValueError("bundle directory must not be a symlink")
        shutil.rmtree(bundle_dir)
    payload_dir = bundle_dir / "payload"
    payload_dir.mkdir(parents=True)

    artifacts = expand_globs(artifact_globs)
    entries: list[dict[str, object]] = []
    components: list[dict[str, str]] = []
    dependencies: list[dict[str, object]] = []
    subjects: list[dict[str, str]] = []
    used_names: set[str] = set()

    for artifact in artifacts:
        name = artifact.name
        if name in used_names:
            raise ValueError(f"duplicate artifact basename: {name}")
        used_names.add(name)
        target = payload_dir / name
        shutil.copyfile(artifact, target)
        digest = sha256(target)
        relative = target.relative_to(bundle_dir).as_posix()
        entries.append({"path": relative, "sha256": digest, "size": target.stat().st_size})
        bom_ref = f"pkg:generic/{quote(name, safe='')}@{source_commit[:12]}"
        components.append({
            "type": "application",
            "name": name,
            "version": source_commit[:12],
            "bom-ref": bom_ref,
            "purl": bom_ref,
        })
        dependencies.append({"ref": bom_ref, "dependsOn": []})
        subjects.append({"path": relative, "sha256": digest})

    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    manifest = {
        "schema": "nexus-artifact-manifest/v1",
        "purpose": "ci-build-evidence",
        "production_approval": False,
        "artifacts": entries,
    }
    (bundle_dir / "artifact-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    serial = f"urn:uuid:{uuid4()}"
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": serial,
        "version": 1,
        "metadata": {
            "timestamp": timestamp,
            "properties": [
                {"name": "nexus:graph-completeness", "value": "unknown"},
                {"name": "nexus:evidence-purpose", "value": "ci-build-evidence"},
            ],
        },
        "components": components,
        "dependencies": dependencies,
    }
    sbom_path = bundle_dir / "sbom.cdx.json"
    sbom_path.write_text(json.dumps(sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    provenance = {
        "schema": "nexus-provenance/v1",
        "purpose": "ci-build-evidence",
        "production_approval": False,
        "source_commit": source_commit,
        "builder": builder,
        "build_parameters": parameters,
        "issued_at": timestamp,
        "sbom_serial_number": serial,
        "sbom_sha256": sha256(sbom_path),
        "subjects": subjects,
    }
    (bundle_dir / "provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-dir", required=True, type=Path)
    parser.add_argument("--artifact-glob", action="append", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--builder", required=True)
    parser.add_argument(
        "--build-parameter",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="repeatable exact build parameter recorded in provenance",
    )
    args = parser.parse_args()
    try:
        build_bundle(
            args.bundle_dir,
            args.artifact_glob,
            args.source_commit,
            args.builder,
            parse_build_parameter_args(args.build_parameter),
        )
    except ValueError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
