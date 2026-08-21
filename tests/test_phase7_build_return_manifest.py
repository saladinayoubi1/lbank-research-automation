from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from scripts import phase7_build_return_manifest as builder
from scripts import phase7_return_package as package

SOURCE = "a" * 40
SESSION = "p7-20260818T200000Z-deadbeef"


def _write_payload(root: Path) -> None:
    for index, relative in enumerate(sorted(package.PAYLOAD_FILES), start=1):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative == "returned/offline-network-proof.json":
            path.write_bytes(b'\xef\xbb\xbf{\r\n  "schema_version": "example",\r\n  "value": 1\r\n}\r\n')
        else:
            path.write_bytes((f"payload-{index}-{relative}\n").encode("utf-8"))


def test_manifest_builder_hashes_exact_payload_and_invokes_validation(monkeypatch, tmp_path: Path):
    root = tmp_path / "return"
    _write_payload(root)

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


def test_manifest_builder_normalizes_windows_bom_and_crlf_before_hashing(monkeypatch, tmp_path: Path):
    root = tmp_path / "return"
    _write_payload(root)
    monkeypatch.setattr(package, "validate_package", lambda *args, **kwargs: {"ok": True})

    manifest = builder.build_manifest(
        root,
        session_id=SESSION,
        source_sha=SOURCE,
        proof_run_id=123,
        prepared_artifact_name=f"nexus-phase7-proof-{SOURCE}",
        created_at="2026-08-18T20:06:00Z",
    )

    proof = root / "returned/offline-network-proof.json"
    raw = proof.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in raw
    assert raw.endswith(b"\n")
    assert json.loads(raw.decode("utf-8")) == {"schema_version": "example", "value": 1}
    assert manifest["files"]["returned/offline-network-proof.json"] == hashlib.sha256(raw).hexdigest()


def test_windows_return_branch_preflight_seeds_only_missing_delete_target(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "NEXUS Test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "nexus-test@example.invalid"], check=True)
    (repo / "README.md").write_text("phase7\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "seed"], check=True, capture_output=True, text=True)
    source = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert builder._ensure_windows_return_branch_delete_target(
        session_id=SESSION,
        source_sha=source,
        repo_root=repo,
        platform_name="nt",
    ) is True
    branch = f"phase7/return-{SESSION}"
    observed = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", branch],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert observed == source

    assert builder._ensure_windows_return_branch_delete_target(
        session_id=SESSION,
        source_sha=source,
        repo_root=repo,
        platform_name="nt",
    ) is False
