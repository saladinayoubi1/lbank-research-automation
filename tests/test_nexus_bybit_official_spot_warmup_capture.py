from pathlib import Path

import pytest

from scripts.nexus_bybit_official_spot_warmup_capture import (
    CaptureError, checked_day, fetch_file, jobs,
)


class Response:
    def __init__(self, url, status=200, body=b"a" * 101, length=None):
        self.url, self.status_code, self.body = url, status, body
        self.headers = {"Content-Length": str(len(body) if length is None else length)}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_content(self, chunk_size):
        yield self.body


class Session:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


URL = "https://public.bybit.com/spot/BTCUSDT/BTCUSDT_2026-10-18.csv.gz"


def test_exact_contiguous_paired_historical_scope_excludes_every_future_day():
    scheduled = list(jobs())
    assert len(scheduled) == len(set(scheduled)) == 158
    assert scheduled[:2] == [("BTCUSDT", "2026-08-01"), ("ETHUSDT", "2026-08-01")]
    assert scheduled[-2:] == [("BTCUSDT", "2026-10-18"), ("ETHUSDT", "2026-10-18")]
    assert all(day < "2026-10-19" for _, day in scheduled)


@pytest.mark.parametrize("symbol,day", [
    ("BTCUSDT", "2026-10-19"), ("BTCUSDT", "2027-01-16"),
    ("ETHUSDT", "2026-07-31"), ("XRPUSDT", "2026-10-18"),
    ("BTCUSDT", "20261018"), ("BTCUSDT", "2026-02-30"),
])
def test_scoped_source_rejects_unreviewed_dates_and_assets(symbol, day):
    with pytest.raises(CaptureError):
        checked_day(symbol, day)


@pytest.mark.parametrize("status,url", [(403, URL), (302, URL), (200, "https://other.test/file.gz")])
def test_denial_or_redirect_never_becomes_captured_source(tmp_path, status, url):
    session = Session(Response(url, status=status))
    target = tmp_path / "BTCUSDT_2026-10-18.csv.gz"
    with pytest.raises(CaptureError):
        fetch_file(session, "BTCUSDT", "2026-10-18", target)
    assert len(session.calls) == 1
    assert not target.exists()
    assert session.calls[0][1]["allow_redirects"] is False


def test_http_short_body_keeps_partial_and_never_claims_complete(tmp_path):
    session = Session(Response(URL, body=b"x" * 101, length=999))
    target = tmp_path / "BTCUSDT_2026-10-18.csv.gz"
    with pytest.raises(CaptureError, match="incomplete"):
        fetch_file(session, "BTCUSDT", "2026-10-18", target)
    assert not target.exists()
    assert target.with_suffix(".gz.part").exists()
    with pytest.raises(CaptureError, match="overwrite"):
        fetch_file(session, "BTCUSDT", "2026-10-18", target)
    assert len(session.calls) == 1


def test_success_records_actual_exact_source_and_never_overwrites(tmp_path):
    session = Session(Response(URL))
    target = tmp_path / "BTCUSDT_2026-10-18.csv.gz"
    receipt = fetch_file(session, "BTCUSDT", "2026-10-18", target)
    assert target.read_bytes() == b"a" * 101
    assert receipt["received_bytes"] == receipt["content_length"] == 101
    assert receipt["requested_url"] == receipt["final_url"] == URL
    with pytest.raises(CaptureError):
        fetch_file(session, "BTCUSDT", "2026-10-18", target)
    assert len(session.calls) == 1


def test_future_request_rejected_before_network(tmp_path):
    session = Session(Response(URL))
    with pytest.raises(CaptureError):
        fetch_file(session, "BTCUSDT", "2026-10-19", tmp_path / "future.gz")
    assert session.calls == []
