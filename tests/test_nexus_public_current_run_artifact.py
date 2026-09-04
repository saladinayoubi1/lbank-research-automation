from __future__ import annotations

import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from scripts import nexus_public_current_run_artifact as transport


SOURCE_SHA = "a" * 40
ARCHIVE_SHA = "b" * 64


def test_public_headers_do_not_send_authorization() -> None:
    headers = transport._headers()
    assert "Authorization" not in headers
    assert headers["Accept"] == "application/vnd.github+json"


def test_public_repository_gate_rejects_private_or_wrong_repository(monkeypatch) -> None:
    monkeypatch.setattr(transport, "_json_get", lambda url: {"full_name": "owner/repo", "private": True})
    with pytest.raises(RuntimeError, match="exact public repository"):
        transport._require_public_repository("owner/repo")
    monkeypatch.setattr(transport, "_json_get", lambda url: {"full_name": "other/repo", "private": False})
    with pytest.raises(RuntimeError, match="exact public repository"):
        transport._require_public_repository("owner/repo")


def test_exact_artifact_cardinality_and_run_identity(monkeypatch) -> None:
    responses = iter([
        {"full_name": "owner/repo", "private": False},
        {"id": 7, "head_sha": SOURCE_SHA, "head_branch": "main", "event": "push"},
        {"artifacts": [{"id": 9, "name": "proof", "expired": False, "size_in_bytes": 12, "workflow_run": {"head_sha": SOURCE_SHA}}]},
    ])
    monkeypatch.setattr(transport, "_json_get", lambda url: next(responses))
    result = transport._artifact("owner/repo", "7", "proof", SOURCE_SHA)
    assert result["id"] == 9


def test_outer_surface_rejects_extra_member(tmp_path: Path) -> None:
    outer = tmp_path / "outer.zip"
    with zipfile.ZipFile(outer, "w") as archive:
        archive.writestr("expected.zip", b"x")
        archive.writestr("extra.txt", b"y")
    with pytest.raises(RuntimeError, match="outer surface mismatch"):
        transport._extract_exact_outer(outer, tmp_path / "out", {"expected.zip"})


def test_digest_sidecar_must_match_exact_expected(tmp_path: Path) -> None:
    sidecar = tmp_path / "digest.sha256"
    sidecar.write_text(ARCHIVE_SHA + "\n", encoding="ascii")
    transport._read_digest(sidecar, ARCHIVE_SHA)
    sidecar.write_text("c" * 64 + "\n", encoding="ascii")
    with pytest.raises(RuntimeError, match="sidecar mismatch"):
        transport._read_digest(sidecar, ARCHIVE_SHA)


def test_sha_parser_is_fail_closed() -> None:
    assert transport._sha(SOURCE_SHA.upper(), transport._SHA40, "source SHA") == SOURCE_SHA
    with pytest.raises(RuntimeError, match="invalid source SHA"):
        transport._sha("not-a-sha", transport._SHA40, "source SHA")


def test_direct_script_help_bootstraps_repository_import_path() -> None:
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "nexus_public_current_run_artifact.py"
    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()
