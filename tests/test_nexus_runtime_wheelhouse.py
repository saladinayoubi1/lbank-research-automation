from __future__ import annotations

import hashlib
import io
import json
import shutil
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import pytest

import scripts.nexus_runtime_wheelhouse as wheelhouse
from scripts.nexus_runtime_wheelhouse import (
    MAX_ARTIFACT_BYTES,
    _download_with_redirect_boundary,
    _validate_content_range,
    deterministic_pack,
    safe_extract_flat_archive,
)


class _Response:
    def __init__(
        self,
        status: int,
        *,
        headers: dict[str, str] | None = None,
        chunks: list[bytes] | None = None,
        failure: BaseException | None = None,
    ) -> None:
        self.status = status
        self.headers = headers or {}
        self._chunks = list(chunks or [])
        self._failure = failure

    def read(self, _size: int) -> bytes:
        if self._chunks:
            return self._chunks.pop(0)
        if self._failure is not None:
            failure = self._failure
            self._failure = None
            raise failure
        return b""

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class _RedirectingOpener:
    def __init__(self) -> None:
        self.calls = 0

    def open(self, request, timeout: int):
        assert timeout == 60
        self.calls += 1
        raise urllib.error.HTTPError(
            request.full_url,
            302,
            "Found",
            {"Location": f"https://blob.example.invalid/artifact/{self.calls}"},
            None,
        )


def test_deterministic_pack_is_stable_and_flat(tmp_path: Path) -> None:
    root = tmp_path / "wheelhouse"
    root.mkdir()
    (root / "requirements.lock").write_text("demo==1.0\n", encoding="utf-8")
    (root / "demo-1.0-py3-none-any.whl").write_bytes(b"wheel-bytes")
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"

    first_digest = deterministic_pack(root, first)
    second_digest = deterministic_pack(root, second)

    assert first.read_bytes() == second.read_bytes()
    assert first_digest == second_digest == hashlib.sha256(first.read_bytes()).hexdigest()
    with zipfile.ZipFile(first) as archive:
        assert archive.namelist() == ["demo-1.0-py3-none-any.whl", "requirements.lock"]


def test_safe_extract_rejects_path_traversal(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../escape.whl", b"bad")

    with pytest.raises(RuntimeError, match="unsafe archive path"):
        safe_extract_flat_archive(archive_path, tmp_path / "out")


def test_safe_extract_rejects_unexpected_wheelhouse_member(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe-member.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("payload.txt", b"bad")

    with pytest.raises(RuntimeError, match="unexpected wheelhouse member"):
        safe_extract_flat_archive(archive_path, tmp_path / "out")


def test_restore_accepts_one_digest_pinned_inner_archive_with_nonlegacy_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_lock = tmp_path / "requirements.lock"
    repository_lock.write_text("demo==1.0\n", encoding="utf-8")
    wheelhouse_root = tmp_path / "wheelhouse-source"
    wheelhouse_root.mkdir()
    (wheelhouse_root / "requirements.lock").write_bytes(repository_lock.read_bytes())
    (wheelhouse_root / "demo-1.0-py3-none-any.whl").write_bytes(b"wheel-bytes")
    inner = tmp_path / "nexus-multipair-continuity-wheelhouse.zip"
    expected_sha256 = deterministic_pack(wheelhouse_root, inner)
    outer = tmp_path / "github-artifact-wrapper.zip"
    with zipfile.ZipFile(outer, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(inner.name, inner.read_bytes())

    payload = {
        "artifacts": [
            {
                "id": 17,
                "name": "nexus-multipair-continuity-wheelhouse-deadbeef",
                "expired": False,
                "size_in_bytes": outer.stat().st_size,
            }
        ]
    }

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: io.BytesIO(json.dumps(payload).encode("utf-8")),
    )
    download_target = tmp_path / "download.zip.part"
    monkeypatch.setattr(
        wheelhouse,
        "_cross_attempt_resume_path",
        lambda **_kwargs: download_target,
    )

    def fake_download(_url, _headers, output: Path, **_kwargs) -> None:
        shutil.copyfile(outer, output)

    monkeypatch.setattr(wheelhouse, "_download_with_redirect_boundary", fake_download)

    destination = tmp_path / "restored"
    result = wheelhouse.restore_current_run_artifact(
        repository="example/repo",
        run_id="123456",
        token="token",
        artifact_name="nexus-multipair-continuity-wheelhouse-deadbeef",
        expected_sha256=expected_sha256,
        repository_lock=repository_lock,
        destination=destination,
        work_root=tmp_path / "work",
    )

    assert result["archive_sha256"] == expected_sha256
    assert result["wheel_count"] == 1
    assert (destination / "requirements.lock").read_bytes() == repository_lock.read_bytes()
    assert (destination / "demo-1.0-py3-none-any.whl").read_bytes() == b"wheel-bytes"


def test_restore_still_rejects_multiple_inner_archives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_lock = tmp_path / "requirements.lock"
    repository_lock.write_text("demo==1.0\n", encoding="utf-8")
    outer = tmp_path / "github-artifact-wrapper.zip"
    with zipfile.ZipFile(outer, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("one.zip", b"PK\x05\x06" + b"\x00" * 18)
        archive.writestr("two.zip", b"PK\x05\x06" + b"\x00" * 18)
    payload = {
        "artifacts": [
            {
                "id": 18,
                "name": "multi",
                "expired": False,
                "size_in_bytes": outer.stat().st_size,
            }
        ]
    }
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: io.BytesIO(json.dumps(payload).encode("utf-8")),
    )
    download_target = tmp_path / "download.zip.part"
    monkeypatch.setattr(
        wheelhouse,
        "_cross_attempt_resume_path",
        lambda **_kwargs: download_target,
    )
    monkeypatch.setattr(
        wheelhouse,
        "_download_with_redirect_boundary",
        lambda _url, _headers, output, **_kwargs: shutil.copyfile(outer, output),
    )

    with pytest.raises(RuntimeError, match="exactly one inner archive"):
        wheelhouse.restore_current_run_artifact(
            repository="example/repo",
            run_id="123456",
            token="token",
            artifact_name="multi",
            expected_sha256="0" * 64,
            repository_lock=repository_lock,
            destination=tmp_path / "restored",
            work_root=tmp_path / "work",
        )


def test_resumable_storage_retry_uses_fresh_signed_url_and_never_forwards_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opener = _RedirectingOpener()
    storage_requests = []
    storage_responses = [
        _Response(200, chunks=[b"abc"], failure=TimeoutError("simulated stall")),
        _Response(
            206,
            headers={"Content-Range": "bytes 3-5/6"},
            chunks=[b"def"],
        ),
    ]

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_args, **_kwargs: opener)

    def fake_urlopen(request, timeout: int):
        assert timeout == 1
        storage_requests.append(request)
        return storage_responses.pop(0)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    sleeps: list[float] = []
    monkeypatch.setattr(wheelhouse.time, "sleep", sleeps.append)

    output = tmp_path / "artifact.zip"
    _download_with_redirect_boundary(
        "https://api.github.com/repos/example/repo/actions/artifacts/1/zip",
        {"Authorization": "Bearer secret", "User-Agent": "test"},
        output,
        expected_size=6,
        timeout=1,
        retry_delays=(0.25,),
    )

    assert output.read_bytes() == b"abcdef"
    assert opener.calls == 2
    assert sleeps == [0.25]
    assert len(storage_requests) == 2
    assert storage_requests[0].get_header("Authorization") is None
    assert storage_requests[1].get_header("Authorization") is None
    assert storage_requests[0].get_header("Range") is None
    assert storage_requests[1].get_header("Range") == "bytes=3-"


def test_cross_attempt_resume_keeps_existing_partial_without_forwarding_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opener = _RedirectingOpener()
    storage_requests = []
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_args, **_kwargs: opener)

    def fake_urlopen(request, timeout: int):
        assert timeout == 1
        storage_requests.append(request)
        return _Response(
            206,
            headers={"Content-Range": "bytes 3-5/6"},
            chunks=[b"def"],
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    output = tmp_path / "artifact.zip"
    output.write_bytes(b"abc")

    _download_with_redirect_boundary(
        "https://api.github.com/repos/example/repo/actions/artifacts/1/zip",
        {"Authorization": "Bearer secret", "User-Agent": "test"},
        output,
        expected_size=6,
        timeout=1,
        retry_delays=(),
        preserve_existing=True,
    )

    assert output.read_bytes() == b"abcdef"
    assert opener.calls == 1
    assert len(storage_requests) == 1
    assert storage_requests[0].get_header("Authorization") is None
    assert storage_requests[0].get_header("Range") == "bytes=3-"


def test_content_range_is_fail_closed_for_wrong_resume_offset() -> None:
    with pytest.raises(RuntimeError, match="start mismatch"):
        _validate_content_range("bytes 2-5/6", expected_start=3, expected_total=6)
    with pytest.raises(RuntimeError, match="total mismatch"):
        _validate_content_range("bytes 3-5/7", expected_start=3, expected_total=6)


@pytest.mark.parametrize("expected_size", [0, MAX_ARTIFACT_BYTES + 1])
def test_artifact_size_is_bounded_before_network_access(
    tmp_path: Path, expected_size: int
) -> None:
    with pytest.raises(RuntimeError, match="size is outside bounds"):
        _download_with_redirect_boundary(
            "https://api.github.com/repos/example/repo/actions/artifacts/1/zip",
            {"Authorization": "Bearer secret"},
            tmp_path / "artifact.zip",
            expected_size=expected_size,
        )
