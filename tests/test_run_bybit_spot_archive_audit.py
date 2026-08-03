from __future__ import annotations

from pathlib import Path

import pytest

import run_bybit_spot_archive_audit as runner


class Response:
    def __init__(self, status_code: int, content: bytes = b""):
        self.status_code = status_code
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        return self.responses.pop(0)


def test_retryable_403_then_success(monkeypatch, tmp_path):
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: None)
    session = Session([Response(403), Response(200, b"archive")])
    result = runner.robust_download_archive(
        "BTCUSDT",
        "2026-08-01",
        tmp_path,
        max_attempts=3,
        session=session,
    )
    assert session.calls == 2
    assert result["download_attempts"] == 2
    assert result["loaded_from_cache"] is False
    assert Path(result["path"]).read_bytes() == b"archive"


def test_existing_cache_avoids_network(tmp_path):
    path = tmp_path / "BTCUSDT_2026-08-01.csv.gz"
    path.write_bytes(b"cached")
    session = Session([])
    result = runner.robust_download_archive(
        "BTCUSDT",
        "2026-08-01",
        tmp_path,
        session=session,
    )
    assert session.calls == 0
    assert result["loaded_from_cache"] is True
    assert result["download_attempts"] == 0


def test_max_attempts_must_be_positive(tmp_path):
    with pytest.raises(ValueError, match="at least 1"):
        runner.robust_download_archive(
            "BTCUSDT",
            "2026-08-01",
            tmp_path,
            max_attempts=0,
        )
