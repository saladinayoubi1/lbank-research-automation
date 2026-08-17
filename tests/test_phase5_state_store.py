from __future__ import annotations

import sqlite3

import pytest

import phase5_state_store as state


def test_first_write_and_monotonic_compare_and_swap(tmp_path):
    store = state.SQLiteStateStore(tmp_path / "state.db")
    first = store.compare_and_swap("mission", None, {"status": "one"})
    second = store.compare_and_swap("mission", 0, {"status": "two"})

    assert first.generation == 0
    assert first.previous_sha256 is None
    assert second.generation == 1
    assert second.previous_sha256 == first.payload_sha256
    assert store.load_current("mission").payload == {"status": "two"}


def test_stale_writer_is_fenced_by_generation(tmp_path):
    store = state.SQLiteStateStore(tmp_path / "state.db")
    store.compare_and_swap("mission", None, {"value": 1})
    store.compare_and_swap("mission", 0, {"value": 2})

    with pytest.raises(state.StateConflict, match="generation conflict"):
        store.compare_and_swap("mission", 0, {"value": "stale"})

    assert store.load_current("mission").payload == {"value": 2}


def test_nonfinite_or_oversized_state_fails_closed(tmp_path):
    store = state.SQLiteStateStore(tmp_path / "state.db")
    with pytest.raises(state.StateStoreError, match="canonical JSON"):
        store.compare_and_swap("mission", None, {"bad": float("nan")})

    with pytest.raises(state.StateStoreError, match="bounded size"):
        store.compare_and_swap("mission", None, {"blob": "x" * state.MAX_STATE_BYTES})


def test_corrupt_latest_state_is_not_treated_as_empty(tmp_path):
    path = tmp_path / "state.db"
    store = state.SQLiteStateStore(path)
    first = store.compare_and_swap("mission", None, {"value": 1})
    store.compare_and_swap("mission", 0, {"value": 2})

    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE snapshots SET payload_json=? WHERE mission_id=? AND generation=?",
            ('{"value":"tampered"}', "mission", 1),
        )
        conn.commit()

    with pytest.raises(state.StateCorruption, match="digest mismatch"):
        store.load_current("mission")

    recovered = store.recover_previous_valid("mission")
    assert recovered.generation == 0
    assert recovered.payload == {"value": 1}
    assert recovered.payload_sha256 == first.payload_sha256
    assert recovered.recovered is True
    assert recovered.quarantined_generations == (1,)


def test_store_refuses_to_append_to_corrupt_current_chain(tmp_path):
    path = tmp_path / "state.db"
    store = state.SQLiteStateStore(path)
    store.compare_and_swap("mission", None, {"value": 1})

    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE snapshots SET payload_sha256=? WHERE mission_id=? AND generation=?",
            ("0" * 64, "mission", 0),
        )
        conn.commit()

    with pytest.raises(state.StateCorruption):
        store.compare_and_swap("mission", 0, {"value": 2})

    with sqlite3.connect(path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM snapshots WHERE mission_id=?", ("mission",)).fetchone()[0]
    assert count == 1


def test_hash_chain_substitution_is_detected(tmp_path):
    path = tmp_path / "state.db"
    store = state.SQLiteStateStore(path)
    store.compare_and_swap("mission", None, {"value": 1})
    store.compare_and_swap("mission", 0, {"value": 2})

    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE snapshots SET previous_sha256=? WHERE mission_id=? AND generation=?",
            ("f" * 64, "mission", 1),
        )
        conn.commit()

    with pytest.raises(state.StateCorruption, match="hash chain"):
        store.load_current("mission")


def test_missions_have_independent_generation_streams(tmp_path):
    store = state.SQLiteStateStore(tmp_path / "state.db")
    a = store.compare_and_swap("A", None, {"value": 1})
    b = store.compare_and_swap("B", None, {"value": 2})
    assert a.generation == 0
    assert b.generation == 0
    assert store.load_current("A").payload == {"value": 1}
    assert store.load_current("B").payload == {"value": 2}
