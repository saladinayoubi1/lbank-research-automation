from __future__ import annotations

import json
from pathlib import Path

from scripts import phase7_build_return_manifest as builder
from scripts import phase7_return_package as package

SOURCE = "a" * 40
SESSION = "p7-20260818T200000Z-deadbeef"


def test_manifest_builder_hashes_exact_payload_and_invokes_validation(monkeypatch, tmp_path: Path):
    root = tmp_path / "return"
    for index, relative in enumerate(sorted(package.PAYLOAD_FILES), start=1):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((f"payload-{index}-{relative}\n").encode("utf-8"))

    observed = {}

    def validate(path: Path, *, expected_source_sha: str | None = None):
        observed["root"] = Path(path)
        observed["source"] = expected_source_sha
        return {"ok": True}

    monkeypatch.setattr(package, "validate_package", validate)
    manifest = builder.build_manifest(
        root,
        session_id=SESSION,
        source_sha=SOURCE,
        proof_run_id=123,
        prepared_artifact_name=f"nexus-phase7-proof-{SOURCE}",
        created_at="2026-08-18T20:06:00Z",
    )

    saved = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert saved == manifest
    assert set(manifest["files"]) == package.PAYLOAD_FILES
    for relative, digest in manifest["files"].items():
        assert digest == package._sha256(root / relative)
    assert len(manifest["package_sha256"]) == 64
    assert observed == {"root": root.resolve(), "source": SOURCE}
