from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import nexus_event_store as store


SOURCE = "896573210b6fd5a87a62562927898445f97f43ed"
NOW = datetime(2026, 9, 1, 4, 30, tzinfo=timezone.utc)


def read_raw(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def write_raw(path: Path, events: list[dict]) -> None:
    path.write_text("\n".join(store.canonical_json(event) for event in events) + "\n", encoding="utf-8")


def seed(path: Path) -> None:
    store.append_state(path, source_sha=SOURCE, state={"counter": 1, "nested": {"ok": True}}, recorded_at=NOW)
    store.append_state(path, source_sha=SOURCE, state={"counter": 2, "nested": {"ok": True}}, recorded_at=NOW)


def test_canonical_digest_is_independent_of_mapping_key_order():
    first = store.build_event(
        sequence=1,
        event_type="state_replace",
        source_sha=SOURCE,
        payload={"state": {"b": 2, "a": 1}},
        previous_event_digest=None,
        recorded_at=NOW,
    )
    second = store.build_event(
        sequence=1,
        event_type="state_replace",
        source_sha=SOURCE,
        payload={"state": {"a": 1, "b": 2}},
        previous_event_digest=None,
        recorded_at=NOW,
    )
    assert first["event_digest"] == second["event_digest"]


def test_append_builds_contiguous_source_bound_hash_chain(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    seed(path)
    events = store.load_events(path, expected_source_sha=SOURCE)

    assert [event["sequence"] for event in events] == [1, 2]
    assert events[0]["previous_event_digest"] is None
    assert events[1]["previous_event_digest"] == events[0]["event_digest"]
    assert all(event["source_sha"] == SOURCE for event in events)


def test_replay_reproduces_latest_and_prior_valid_state(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    seed(path)

    assert store.replay_state(path, expected_source_sha=SOURCE) == {
        "counter": 2,
        "nested": {"ok": True},
    }
    assert store.replay_state(path, expected_source_sha=SOURCE, upto_sequence=1) == {
        "counter": 1,
        "nested": {"ok": True},
    }


def test_missing_store_fails_closed(tmp_path: Path):
    with pytest.raises(store.EventStoreError, match="missing"):
        store.replay_state(tmp_path / "missing.jsonl", expected_source_sha=SOURCE)


def test_malformed_json_fails_closed(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    path.write_text("{not-json}\n", encoding="utf-8")

    with pytest.raises(store.EventStoreError, match="malformed"):
        store.replay_state(path, expected_source_sha=SOURCE)


def test_payload_tampering_fails_digest_validation(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    seed(path)
    events = read_raw(path)
    events[1]["payload"]["state"]["counter"] = 999
    write_raw(path, events)

    with pytest.raises(store.EventStoreError, match="digest does not match"):
        store.replay_state(path, expected_source_sha=SOURCE)


def test_chain_link_tampering_fails_closed_even_with_recomputed_event_digest(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    seed(path)
    events = read_raw(path)
    events[1]["previous_event_digest"] = "0" * 64
    events[1]["event_digest"] = store.compute_event_digest(events[1])
    write_raw(path, events)

    with pytest.raises(store.EventStoreError, match="chain link"):
        store.replay_state(path, expected_source_sha=SOURCE)


def test_sequence_gap_fails_closed_even_with_recomputed_digest(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    seed(path)
    events = read_raw(path)
    events[1]["sequence"] = 3
    events[1]["event_digest"] = store.compute_event_digest(events[1])
    write_raw(path, events)

    with pytest.raises(store.EventStoreError, match="sequence"):
        store.replay_state(path, expected_source_sha=SOURCE)


def test_mixed_source_chain_fails_closed_even_with_valid_digest(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    seed(path)
    events = read_raw(path)
    events[1]["source_sha"] = "different-source"
    events[1]["event_digest"] = store.compute_event_digest(events[1])
    write_raw(path, events)

    with pytest.raises(store.EventStoreError, match="mixed source_sha"):
        store.load_events(path)


def test_expected_source_mismatch_fails_closed(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    seed(path)

    with pytest.raises(store.EventStoreError, match="expected source"):
        store.replay_state(path, expected_source_sha="wrong-sha")


def test_append_refuses_to_extend_corrupt_existing_store(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    seed(path)
    events = read_raw(path)
    events[0]["payload"]["state"]["counter"] = 777
    write_raw(path, events)
    before = path.read_bytes()

    with pytest.raises(store.EventStoreError, match="digest does not match"):
        store.append_state(path, source_sha=SOURCE, state={"counter": 3}, recorded_at=NOW)

    assert path.read_bytes() == before


def test_full_chain_is_validated_before_prior_state_replay(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    seed(path)
    events = read_raw(path)
    events[1]["payload"]["state"]["counter"] = 999
    write_raw(path, events)

    with pytest.raises(store.EventStoreError, match="digest does not match"):
        store.replay_state(path, expected_source_sha=SOURCE, upto_sequence=1)


def test_atomic_replace_failure_preserves_previous_valid_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "events.jsonl"
    seed(path)
    before = path.read_bytes()

    def fail_replace(source: Path | str, destination: Path | str) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(store.os, "replace", fail_replace)

    with pytest.raises(store.EventStoreError, match="atomic write failed"):
        store.append_state(path, source_sha=SOURCE, state={"counter": 3}, recorded_at=NOW)

    assert path.read_bytes() == before
    assert not (tmp_path / ".events.jsonl.tmp").exists()


def test_unsupported_event_type_and_invalid_source_fail_closed():
    with pytest.raises(store.EventStoreError, match="unsupported event_type"):
        store.build_event(
            sequence=1,
            event_type="implicit_mutation",
            source_sha=SOURCE,
            payload={"state": {}},
            previous_event_digest=None,
            recorded_at=NOW,
        )

    with pytest.raises(store.EventStoreError, match="source_sha"):
        store.build_event(
            sequence=1,
            event_type="state_replace",
            source_sha="",
            payload={"state": {}},
            previous_event_digest=None,
            recorded_at=NOW,
        )


def test_blank_record_and_noncanonical_schema_fail_closed(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    event = store.build_event(
        sequence=1,
        event_type="state_replace",
        source_sha=SOURCE,
        payload={"state": {"ok": True}},
        previous_event_digest=None,
        recorded_at=NOW,
    )
    path.write_text(store.canonical_json(event) + "\n\n", encoding="utf-8")
    with pytest.raises(store.EventStoreError, match="blank event record"):
        store.load_events(path, expected_source_sha=SOURCE)

    event["unexpected"] = True
    path.write_text(store.canonical_json(event) + "\n", encoding="utf-8")
    with pytest.raises(store.EventStoreError, match="canonical schema"):
        store.load_events(path, expected_source_sha=SOURCE)
