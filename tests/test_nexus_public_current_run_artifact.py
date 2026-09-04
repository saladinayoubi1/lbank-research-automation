from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import nexus_multipair_recent_archive_runtime_snapshot as recent
from scripts import nexus_public_current_run_artifact as transport


SOURCE_SHA = "a" * 40
ARCHIVE_SHA = "b" * 64
TOKEN = "read-only-token"


def test_headers_add_bearer_only_when_token_is_supplied() -> None:
    public_headers = transport._headers()
    assert "Authorization" not in public_headers
    assert public_headers["Accept"] == "application/vnd.github+json"

    authenticated = transport._headers(TOKEN)
    assert authenticated["Authorization"] == f"Bearer {TOKEN}"
    assert authenticated["Accept"] == "application/vnd.github+json"


def test_public_repository_gate_rejects_private_or_wrong_repository(monkeypatch) -> None:
    monkeypatch.setattr(
        transport,
        "_json_get",
        lambda url, token="": {"full_name": "owner/repo", "private": True},
    )
    with pytest.raises(RuntimeError, match="exact public repository"):
        transport._require_public_repository("owner/repo", TOKEN)
    monkeypatch.setattr(
        transport,
        "_json_get",
        lambda url, token="": {"full_name": "other/repo", "private": False},
    )
    with pytest.raises(RuntimeError, match="exact public repository"):
        transport._require_public_repository("owner/repo", TOKEN)


def test_exact_artifact_cardinality_and_run_identity(monkeypatch) -> None:
    responses = iter(
        [
            {"full_name": "owner/repo", "private": False},
            {"id": 7, "head_sha": SOURCE_SHA, "head_branch": "main", "event": "push"},
            {
                "artifacts": [
                    {
                        "id": 9,
                        "name": "proof",
                        "expired": False,
                        "size_in_bytes": 12,
                        "workflow_run": {"head_sha": SOURCE_SHA},
                    }
                ]
            },
        ]
    )
    seen_tokens: list[str] = []

    def fake_json_get(url: str, token: str = "") -> dict:
        seen_tokens.append(token)
        return next(responses)

    monkeypatch.setattr(transport, "_json_get", fake_json_get)
    result = transport._artifact("owner/repo", "7", "proof", SOURCE_SHA, TOKEN)
    assert result["id"] == 9
    assert seen_tokens == [TOKEN, TOKEN, TOKEN]


def test_download_outer_passes_token_to_github_redirect_boundary(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_download(url, headers, output, *, expected_size):
        captured.update(
            url=url,
            headers=headers,
            output=output,
            expected_size=expected_size,
        )

    monkeypatch.setattr(transport.wheelhouse, "_download_with_redirect_boundary", fake_download)
    artifact = {"id": 11, "size_in_bytes": 123}
    destination = tmp_path / "artifact.zip"
    transport._download_outer("owner/repo", artifact, destination, TOKEN)
    assert captured["url"] == "https://api.github.com/repos/owner/repo/actions/artifacts/11/zip"
    assert captured["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert captured["expected_size"] == 123


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


def test_recent_restore_uses_bounded_physical_transport_window(monkeypatch, tmp_path: Path) -> None:
    acquired_at_ms = 1_000_000
    data_as_of_ms = 500_000
    snapshot_digest = "d" * 64
    work = tmp_path / "work"
    inner = tmp_path / recent.INNER_ARCHIVE_NAME
    sidecar = tmp_path / "nexus-multipair-recent-runtime-snapshot.sha256"
    inner.write_bytes(b"inner")
    sidecar.write_text(ARCHIVE_SHA + "\n", encoding="ascii")
    captured: dict[str, int] = {}

    monkeypatch.setattr(
        transport,
        "_artifact",
        lambda repository, run_id, artifact_name, source_sha, token: {
            "id": 17,
            "size_in_bytes": 5,
        },
    )
    monkeypatch.setattr(transport, "_download_outer", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        transport,
        "_extract_exact_outer",
        lambda outer, root, expected_names: {
            recent.INNER_ARCHIVE_NAME: inner,
            "nexus-multipair-recent-runtime-snapshot.sha256": sidecar,
        },
    )
    monkeypatch.setattr(transport.historical_artifact, "_sha256_file", lambda path: ARCHIVE_SHA)

    def fake_extract(inner_path: Path, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        (destination / transport.historical_artifact.MANIFEST_NAME).write_text(
            json.dumps(
                {
                    "snapshot_digest": snapshot_digest,
                    "acquired_at_ms": acquired_at_ms,
                    "data_as_of_ms": data_as_of_ms,
                    "live_freshness_claimed": False,
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(transport.historical_artifact, "_extract_inner", fake_extract)

    def fake_verify(root, value, *, source_sha, now_ms, max_transport_age_ms):
        captured["max_transport_age_ms"] = max_transport_age_ms
        return {"decision": "pass", "checks": {"transport_age": True}}

    monkeypatch.setattr(recent, "verify_recent_archive_runtime_snapshot", fake_verify)
    result = transport.restore_recent(
        repository="owner/repo",
        run_id="12",
        artifact_name="recent",
        source_sha=SOURCE_SHA,
        expected_sha256=ARCHIVE_SHA,
        expected_snapshot_digest=snapshot_digest,
        expected_acquired_at_ms=acquired_at_ms,
        expected_data_as_of_ms=data_as_of_ms,
        now_ms=acquired_at_ms + 21 * 60 * 1000,
        destination=tmp_path / "destination",
        work_root=work,
        token=TOKEN,
    )
    assert result["snapshot_digest"] == snapshot_digest
    assert captured["max_transport_age_ms"] == 45 * 60 * 1000
    assert transport.PHYSICAL_RECENT_TRANSPORT_AGE_MS < recent.MAX_SOURCE_LAG_MS


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
