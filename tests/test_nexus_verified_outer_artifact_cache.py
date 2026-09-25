"""Contract tests for the exact-SHA owner artifact cache transport."""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "download_github_actions_artifact_http11.ps1"
SOURCE = "a" * 40
ARTIFACT_ID = 4242001
RUN_ID = 98765
INNER_NAME = "NEXUS_Personal_Pro_Unpacked_5.1.0_x64.zip"


def _fixture_bytes() -> tuple[bytes, str]:
    inner_buffer = io.BytesIO()
    with zipfile.ZipFile(inner_buffer, "w", compression=zipfile.ZIP_DEFLATED) as inner:
        inner.writestr("README.txt", "Fake offline artifact; no production executable.")
    inner_bytes = inner_buffer.getvalue()
    inner_sha = hashlib.sha256(inner_bytes).hexdigest()
    outer_buffer = io.BytesIO()
    with zipfile.ZipFile(outer_buffer, "w", compression=zipfile.ZIP_DEFLATED) as outer:
        outer.writestr(INNER_NAME, inner_bytes)
        outer.writestr("SHA256SUMS.txt", f"{inner_sha}  {INNER_NAME}\n")
    return outer_buffer.getvalue(), inner_sha


def _metadata_server(metadata: dict):
    encoded = json.dumps(metadata).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != f"/repos/test-owner/test-repo/actions/artifacts/{ARTIFACT_ID}":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *_args):
            pass

    return HTTPServer(("127.0.0.1", 0), Handler)


def _run_powershell(tmp_path: Path, *, corrupt_cache: bool = False):
    outer, inner_sha = _fixture_bytes()
    expected_sha = hashlib.sha256(outer).hexdigest()
    cached = bytearray(outer)
    if corrupt_cache:
        cached[-5] ^= 1
    local = tmp_path / "appdata"
    cache = local / "NEXUS" / "verified-outer-artifacts"
    cache.mkdir(parents=True)
    archive = cache / f"nexus-artifact-{ARTIFACT_ID}.zip"
    archive.write_bytes(cached)

    temp = tmp_path / "runner-temp"
    temp.mkdir()
    destination = temp / "nexus-personal-pro-package-12345"
    metadata = {
        "id": ARTIFACT_ID,
        "name": "nexus-windows-persistent-unpacked",
        "expired": False,
        "size_in_bytes": len(outer),
        "digest": f"sha256:{expected_sha}",
        "workflow_run": {"id": RUN_ID, "head_sha": SOURCE},
    }
    server = _metadata_server(metadata)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        env = os.environ.copy()
        env.update({
            "RUNNER_TEMP": str(temp),
            "GITHUB_API_URL": f"http://127.0.0.1:{server.server_port}",
            "GITHUB_TOKEN": "offline-fixture-token",
            "GITHUB_OUTPUT": str(tmp_path / "output.txt"),
        })
        # Windows PowerShell uses LOCALAPPDATA while discovering built-in
        # Utility/Archive modules. Load them before isolating only the artifact
        # cache location; replacing LOCALAPPDATA at process startup masks
        # built-in Get-FileHash on some hosted Windows runners.
        quoted_local = str(local).replace("'", "''")
        quoted_script = str(SCRIPT).replace("'", "''")
        quoted_destination = str(destination).replace("'", "''")
        command = (
            "Import-Module Microsoft.PowerShell.Utility -ErrorAction Stop; "
            "Import-Module Microsoft.PowerShell.Archive -ErrorAction Stop; "
            f"$env:LOCALAPPDATA='{quoted_local}'; "
            f"& '{quoted_script}' "
            "-Repository 'test-owner/test-repo' "
            f"-ArtifactRunId {RUN_ID} "
            f"-ArtifactId {ARTIFACT_ID} "
            "-ArtifactName 'nexus-windows-persistent-unpacked' "
            f"-ExpectedSourceSha '{SOURCE}' "
            f"-ExpectedArchiveSha256 '{expected_sha}' "
            f"-ExpectedArchiveBytes {len(outer)} "
            f"-DestinationDirectory '{quoted_destination}' "
            "-MaxAttempts 1"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-Command", command],
            env=env, capture_output=True, text=True, timeout=45,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
    return result, destination, archive, expected_sha, inner_sha


def test_metadata_gate_precedes_cache_and_cache_copy_has_second_digest_check():
    source = SCRIPT.read_text(encoding="utf-8")
    assert source.index("Artifact metadata digest mismatch.") < source.index("$cachedArchive =")
    assert source.index("Preloaded artifact cache SHA-256 mismatch.") < source.index(
        "Copy-Item -LiteralPath $cachedArchive"
    )
    assert source.index("Copied owner artifact cache failed exact byte-level verification.") < (
        source.index("NEXUS_VERIFIED_OWNER_ARTIFACT_CACHE=PASS")
    )
    assert "'--ipv4'" in source


@pytest.mark.skipif(sys.platform != "win32", reason="Needs Windows PowerShell and Expand-Archive")
def test_owner_exact_sha_cache_bypasses_cdn_and_verifies_nested_manifest(tmp_path):
    result, destination, cache, expected_sha, inner_sha = _run_powershell(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NEXUS_VERIFIED_OWNER_ARTIFACT_CACHE=PASS" in result.stdout
    assert "transport=verified_owner_cache" in result.stdout
    assert (destination / INNER_NAME).exists()
    assert hashlib.sha256((destination / INNER_NAME).read_bytes()).hexdigest() == inner_sha
    assert cache.exists() and hashlib.sha256(cache.read_bytes()).hexdigest() == expected_sha
    assert f"inner_sha256={inner_sha}" in (tmp_path / "output.txt").read_text()


@pytest.mark.skipif(sys.platform != "win32", reason="Needs Windows PowerShell")
def test_corrupted_owner_cache_fails_closed_without_artifact_destination(tmp_path):
    result, destination, cache, expected_sha, _ = _run_powershell(
        tmp_path, corrupt_cache=True
    )
    assert result.returncode != 0
    assert "Preloaded artifact cache SHA-256 mismatch." in result.stdout + result.stderr
    assert not destination.exists()
    assert hashlib.sha256(cache.read_bytes()).hexdigest() != expected_sha
