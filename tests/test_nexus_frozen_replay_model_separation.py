import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from scripts import nexus_bybit_replay_chunks as chunks


def archive_bytes(*, model_location=None, malformed=False):
    buf = io.BytesIO()
    sources = [{"symbol": "BTCUSDT"}, {"symbol": "ETHUSDT"}]
    report = {"summary": {"current_dataset_integrity_ok": True}}
    if model_location == "source":
        sources[0]["candle_model"] = {"schema": "nexus.bybit-source-row-stable-candles.v2"}
    if model_location == "report":
        report["candle_model"] = {"schema": "nexus.bybit-source-row-stable-candles.v2"}
    with zipfile.ZipFile(buf, "w") as bundle:
        if model_location == "root":
            bundle.writestr("_candle_model.json", "{}")
        if model_location == "nested":
            bundle.writestr("chunk/_candle_model.json", "{}")
        bundle.writestr("_source_manifest.json", json.dumps({} if malformed else sources))
        bundle.writestr("_backfill_report.json", json.dumps(report))
    return buf.getvalue()


def install_download(monkeypatch, raw):
    class Download:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, bound):
            assert bound == 8_000_001
            return raw

    def open_request(request, timeout):
        assert request.full_url == "https://api.github.com/repos/example/repo/actions/artifacts/123/zip"
        assert timeout == 30
        return Download()
    monkeypatch.setattr(chunks.urllib.request, "urlopen", open_request)
    return {"id": 123, "digest": "sha256:" + hashlib.sha256(raw).hexdigest()}


@pytest.mark.parametrize("model_location", ["root", "nested", "source", "report"])
def test_versioned_model_is_excluded_even_under_a_legacy_artifact_name(monkeypatch, model_location):
    raw = archive_bytes(model_location=model_location)
    artifact = install_download(monkeypatch, raw)
    artifact["name"] = "bybit-chunk-01-attempt-1"
    assert chunks.frozen_legacy_artifact(artifact, "example/repo", "test-token") is False


def test_unversioned_legacy_source_is_eligible_without_relaxing_final_semantic_pin(monkeypatch):
    artifact = install_download(monkeypatch, archive_bytes())
    assert chunks.frozen_legacy_artifact(artifact, "example/repo", "test-token") is True


def test_changed_provider_archive_bytes_cannot_be_considered_for_frozen_replay(monkeypatch):
    artifact = install_download(monkeypatch, archive_bytes())
    artifact["digest"] = "sha256:" + "0" * 64
    with pytest.raises(RuntimeError, match="digest mismatch"):
        chunks.frozen_legacy_artifact(artifact, "example/repo", "test-token")


def test_missing_monthly_provenance_fails_closed(monkeypatch):
    artifact = install_download(monkeypatch, archive_bytes(malformed=True))
    with pytest.raises(RuntimeError, match="provenance is unavailable"):
        chunks.frozen_legacy_artifact(artifact, "example/repo", "test-token")


def test_listing_rejects_newest_v2_and_keeps_older_legacy_candidate(monkeypatch):
    artifacts = [
        {"id": 11, "name": "bybit-chunk-01-attempt-2", "expired": False, "created_at": "2026-10-09"},
        {"id": 10, "name": "bybit-chunk-01-attempt-1", "expired": False, "created_at": "2026-10-07"},
    ]
    monkeypatch.setattr(chunks, "_request_json", lambda *_args: {"artifacts": artifacts})
    inspected = []
    def inspect(artifact, *_args):
        inspected.append(artifact["id"])
        return artifact["id"] == 10
    monkeypatch.setattr(chunks, "frozen_legacy_artifact", inspect)
    plan = chunks.build_plan(chunks.fetch_artifact_pages("example/repo", "test-token", max_source_runs=0, frozen_legacy=True))
    assert plan["reusable_artifacts"]["01"]["artifact_id"] == 10
    assert plan["excluded_versioned_artifacts"][0]["artifact_id"] == 11
    assert inspected == [11, 10]


def test_42_v2_names_do_not_prematurely_complete_immutable_legacy_coverage(monkeypatch):
    modern = [{"id": i + 1, "name": f"bybit-chunk-{c.id}-attempt-2", "expired": False, "created_at": "2026-10-09"}
              for i, c in enumerate(chunks.CANONICAL_CHUNKS)]
    filler = [{"id": 500 + i, "name": "unrelated", "expired": False} for i in range(58)]
    legacy = [{"id": i + 101, "name": f"bybit-chunk-{c.id}-attempt-1", "expired": False, "created_at": "2026-10-07"}
              for i, c in enumerate(chunks.CANONICAL_CHUNKS)]
    calls = []
    def listing(url, _token):
        calls.append(url)
        return {"artifacts": modern + filler if url.endswith("&page=1") else legacy}
    monkeypatch.setattr(chunks, "_request_json", listing)
    monkeypatch.setattr(chunks, "frozen_legacy_artifact", lambda artifact, *_args: artifact["id"] >= 101)
    plan = chunks.build_plan(chunks.fetch_artifact_pages("example/repo", "test-token", max_source_runs=0, frozen_legacy=True))
    assert len(calls) == 2
    assert plan["missing_chunk_count"] == 0
    assert len(plan["excluded_versioned_artifacts"]) == 42
    assert all(value["artifact_id"] >= 101 for value in plan["reusable_artifacts"].values())


def test_immutable_history_uses_the_successful_frozen_producer_for_both_rebuild_paths():
    text = Path(".github/workflows/bybit_full_history_backfill.yml").read_text()
    assert "--frozen-legacy" in text
    assert text.count("ref: 6f209195bd7bedd81ec51e6575546137a79ccbec") == 2
    assert "python frozen-replay-builder/scripts/rehydrate_nexus_bybit_chunk.py" in text
    assert "python frozen-replay-builder/bybit_spot_backfill.py" in text
    assert "assert build_manifest(root)" in text
    assert "expected_semantic_sha256=ARCHIVE_SHA256" in text
