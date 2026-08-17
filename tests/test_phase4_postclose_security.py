from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

import agent_transport as at
import deepseek_provider as dp
from scripts import agent_task_executor as executor


class _BytesResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeOpener:
    def __init__(self, payload: bytes):
        self.payload = payload

    def open(self, req, timeout=30):  # noqa: ANN001
        return _BytesResponse(self.payload)


def _zip_result(payload: bytes) -> bytes:
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("result.json", payload)
    return target.getvalue()


def test_deepseek_provider_rejects_oversized_response_before_json_parse(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(dp, "_reserve", lambda *args, **kwargs: ("reserved", 0.01))

    class _ProviderResponse(_BytesResponse):
        def read(self, size=-1):
            assert size == dp.MAX_PROVIDER_RESPONSE_BYTES + 1
            return b"x" * size

    monkeypatch.setattr(dp.request, "urlopen", lambda *args, **kwargs: _ProviderResponse())
    with pytest.raises(dp.AmbiguousCharge, match="exceeded bounded size"):
        dp.chat([{"role": "user", "content": "Reply with exactly: NEXUS_DEEPSEEK_OK"}])


def test_deepseek_provider_rejects_non_object_response_and_retains_ambiguity(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(dp, "_reserve", lambda *args, **kwargs: ("reserved", 0.01))
    monkeypatch.setattr(dp.request, "urlopen", lambda *args, **kwargs: _BytesResponse(b"[]"))
    with pytest.raises(dp.AmbiguousCharge, match="root is malformed"):
        dp.chat([{"role": "user", "content": "Reply with exactly: NEXUS_DEEPSEEK_OK"}])


def test_artifact_redirect_strips_authorization_and_rejects_http_downgrade():
    handler = at._StripAuthorizationRedirectHandler()
    req = at.urllib.request.Request(
        "https://api.github.com/repos/o/r/actions/artifacts/1/zip",
        headers={"Authorization": "Bearer secret", "Proxy-Authorization": "Bearer proxy-secret"},
    )
    redirected = handler.redirect_request(
        req,
        None,
        302,
        "Found",
        {},
        "https://example.invalid/signed-artifact",
    )
    assert redirected is not None
    assert redirected.get_header("Authorization") is None
    assert redirected.get_header("Proxy-Authorization") is None
    with pytest.raises(RuntimeError, match="remain HTTPS"):
        handler.redirect_request(req, None, 302, "Found", {}, "http://example.invalid/artifact")


def test_agent_artifact_rejects_oversized_result_member(monkeypatch):
    oversized = b"x" * (at.MAX_RESULT_JSON_BYTES + 1)
    archive = _zip_result(oversized)
    assert len(archive) < at.MAX_ARTIFACT_ARCHIVE_BYTES
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(at.urllib.request, "build_opener", lambda *args, **kwargs: _FakeOpener(archive))
    with pytest.raises(RuntimeError, match="uncompressed size|result.json exceeds"):
        at._artifact_json(1)


def test_find_result_rejects_oversized_artifact_metadata(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setattr(
        at,
        "_api",
        lambda *args, **kwargs: {
            "artifacts": [
                {
                    "id": 1,
                    "name": "nexus-agent-result-lease-1",
                    "expired": False,
                    "created_at": "2026-08-17T00:00:00Z",
                    "size_in_bytes": at.MAX_ARTIFACT_ARCHIVE_BYTES + 1,
                }
            ]
        },
    )
    with pytest.raises(RuntimeError, match="metadata size"):
        at.find_result("lease-1")


def test_dispatch_payload_decoder_rejects_non_base64_shell_material():
    with pytest.raises(ValueError, match="encoding is invalid"):
        executor.decode_payload("abc'; echo injected; #")


def test_runtime_workflow_never_interpolates_dispatch_payload_into_shell():
    workflow = Path(".github/workflows/nexus-runtime-worker.yml").read_text(encoding="utf-8")
    assert "--payload-b64 '${{ github.event.inputs.payload_b64 }}'" not in workflow
    assert '--payload-b64 "${{ github.event.inputs.payload_b64 }}"' not in workflow
    assert "NEXUS_TASK_PAYLOAD_B64: ${{ github.event.inputs.payload_b64 }}" in workflow
    assert "github.actor == github.repository_owner" in workflow
    assert "github.ref_name == github.event.repository.default_branch" in workflow
    assert workflow.count("persist-credentials: false") >= 4


def test_bounded_reader_refuses_one_byte_over_limit():
    with pytest.raises(RuntimeError, match="exceeds bounded size"):
        at._bounded_read(io.BytesIO(b"12345"), 4, "test stream")
    assert at._bounded_read(io.BytesIO(b"1234"), 4, "test stream") == b"1234"
