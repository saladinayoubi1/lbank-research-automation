"""Physical early-arrival integrity: never trade freshness for slow offline setup."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import nexus_multipair_recent_archive_runtime_snapshot as recent
from scripts import nexus_public_current_run_artifact as transport
from scripts import nexus_recent_arrival as arrival

SHA = "a" * 40
ZIP_SHA = hashlib.sha256(b"original archive").hexdigest()
REPO = "owner/repo"
RUN = "42"
ACQUIRED = 2_000_000_000
SOURCE_AS_OF = ACQUIRED - 2 * 60 * 60 * 1000
ARRIVED = ACQUIRED + 12 * 60 * 1000
LATER = ACQUIRED + 62 * 60 * 1000


def producer_manifest():
    raw = {
        "schema_version": "nexus.multipair-runtime-requalification-recent-archive-snapshot.v1",
        "source_sha": SHA,
        "acquired_at_ms": ACQUIRED,
        "as_of_ms": ACQUIRED,
        "data_as_of_ms": SOURCE_AS_OF,
        "research_only": True,
        "live_freshness_claimed": False,
        "automatic_strategy_promotion": False,
        "paper_execution_started": False,
        "live_trading_authority": False,
    }
    return {**raw, "snapshot_digest": hashlib.sha256(arrival._canonical(raw)).hexdigest()}


def _stage(monkeypatch, tmp_path, *, received_ms=ARRIVED):
    manifest = producer_manifest()
    inner = tmp_path / "input.zip"
    sidecar = tmp_path / "digest.sha256"
    inner.write_bytes(b"original archive")
    sidecar.write_text(ZIP_SHA + "\n")
    monkeypatch.setattr(arrival, "_manifest_from_inner", lambda _: manifest)
    monkeypatch.setattr(transport, "_artifact", lambda *a, **k: {"id": 71, "size_in_bytes": 15})
    monkeypatch.setattr(transport, "_download_outer", lambda *a, **k: None)
    monkeypatch.setattr(
        transport, "_extract_exact_outer",
        lambda *a, **k: {arrival.INNER: inner, arrival.SIDECAR: sidecar},
    )
    # On the isolated physical disk, the staged inner zip and digest sidecar
    # are later verified again. The mock simply simulates extraction.
    monkeypatch.setattr(arrival.time, "time", lambda: received_ms / 1000)
    monkeypatch.setattr(arrival, "_hash_file", lambda p: (
        ZIP_SHA if p.read_bytes() == b"original archive" else "0" * 64
    ))
    stage = tmp_path / "stage"
    receipt = arrival.stage(
        repository=REPO, run_id=RUN, artifact_name="signed-recent",
        source_sha=SHA, expected_sha256=ZIP_SHA,
        expected_snapshot_digest=manifest["snapshot_digest"],
        expected_acquired_at_ms=ACQUIRED, expected_data_as_of_ms=SOURCE_AS_OF,
        destination=stage, token="redacted-read-only-token",
    )
    # The fixture simulates the exact byte-preserving immutable physical
    # stage. Production uses the bounded regular-file extractor, not mocks.
    stored = stage / "outer"
    stored.mkdir(exist_ok=True)
    (stored / arrival.INNER).write_bytes(b"original archive")
    (stored / arrival.SIDECAR).write_text(ZIP_SHA + "\n")
    return stage, receipt, manifest


def test_arrival_before_offline_setup_retains_strict_45min_deadline(monkeypatch, tmp_path):
    stage, receipt, manifest = _stage(monkeypatch, tmp_path)
    assert receipt["received_at_ms"] - receipt["acquired_at_ms"] == 12 * 60 * 1000
    recovered, inner = arrival.verify_stage(
        stage, repository=REPO, run_id=RUN, source_sha=SHA,
        expected_sha256=ZIP_SHA,
        expected_snapshot_digest=manifest["snapshot_digest"],
        expected_acquired_at_ms=ACQUIRED,
        expected_data_as_of_ms=SOURCE_AS_OF,
        now_ms=LATER,
    )
    assert recovered == receipt and inner.read_bytes() == b"original archive"
    # The numerical worker still sees the actual later source clock.
    for received, expected in ((None, False), (ARRIVED, True),
                               (ACQUIRED + 46 * 60 * 1000, False)):
        core = {k: v for k, v in manifest.items() if k != "snapshot_digest"}
        result = recent.verify_recent_archive_runtime_snapshot(
            tmp_path, {**core, "snapshot_digest": recent._digest(core)},
            source_sha=SHA, now_ms=LATER, max_transport_age_ms=45 * 60 * 1000,
            transport_received_at_ms=received,
        )
        assert result["checks"]["transport_age"] is expected


def test_later_actual_source_recency_must_still_fail_closed(monkeypatch, tmp_path):
    stage, _, manifest = _stage(monkeypatch, tmp_path)
    with pytest.raises(RuntimeError, match="source recency"):
        arrival.verify_stage(
            stage, repository=REPO, run_id=RUN, source_sha=SHA,
            expected_sha256=ZIP_SHA, expected_snapshot_digest=manifest["snapshot_digest"],
            expected_acquired_at_ms=ACQUIRED, expected_data_as_of_ms=SOURCE_AS_OF,
            now_ms=SOURCE_AS_OF + arrival.MAX_SOURCE_LAG_MS + 1,
        )
    core = {k: v for k, v in manifest.items() if k != "snapshot_digest"}
    verdict = recent.verify_recent_archive_runtime_snapshot(
        tmp_path, {**core, "snapshot_digest": recent._digest(core)},
        source_sha=SHA, now_ms=SOURCE_AS_OF + recent.MAX_SOURCE_LAG_MS + 1,
        max_transport_age_ms=arrival.MAX_ARRIVAL_AGE_MS,
        transport_received_at_ms=ARRIVED,
    )
    assert verdict["checks"]["source_recency"] is False


def test_reject_forged_receipt_changed_archive_and_wrong_source(monkeypatch, tmp_path):
    stage, receipt, manifest = _stage(monkeypatch, tmp_path)
    params = dict(
        repository=REPO, run_id=RUN, source_sha=SHA,
        expected_sha256=ZIP_SHA, expected_snapshot_digest=manifest["snapshot_digest"],
        expected_acquired_at_ms=ACQUIRED, expected_data_as_of_ms=SOURCE_AS_OF,
        now_ms=LATER,
    )
    with pytest.raises(RuntimeError):
        arrival.verify_stage(stage, **{**params, "run_id": "99"})
    with pytest.raises(RuntimeError):
        arrival.verify_stage(stage, **{**params, "source_sha": "b" * 40})
    path = stage / "outer" / arrival.INNER
    path.write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="bytes changed"):
        arrival.verify_stage(stage, **params)
    path.write_bytes(b"original archive")
    receipt_file = stage / "arrival-receipt.json"
    data = json.loads(receipt_file.read_text())
    data["received_at_ms"] += 40 * 60 * 1000
    receipt_file.write_text(json.dumps(data))
    with pytest.raises(RuntimeError, match="receipt source/identity"):
        arrival.verify_stage(stage, **params)


@pytest.mark.parametrize(
    "received,now",
    [(ACQUIRED + 46 * 60 * 1000, ACQUIRED + 46 * 60 * 1000),
     (ACQUIRED - 1, ACQUIRED + 1),
     (ARRIVED, ARRIVED - 1),
     (ARRIVED, SOURCE_AS_OF + arrival.MAX_SOURCE_LAG_MS + 1)],
)
def test_arrival_and_source_time_boundaries_are_not_extendable(received, now):
    with pytest.raises(RuntimeError):
        arrival._check_times(received, ACQUIRED, SOURCE_AS_OF, now)
