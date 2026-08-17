from __future__ import annotations

import sqlite3

import pytest

import phase5_state_store as state


def _tamper_payload(path, mission_id: str, generation: int, raw: str) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE snapshots SET payload_json=? WHERE mission_id=? AND generation=?",
            (raw, mission_id, generation),
        )
        conn.commit()


def test_first_write_and_monotonic_compare_and_swap(tmp_path):
    store = state.SQLiteStateStore(tmp_path / "state.db")
    first = store.compare_and_swap("mission", None, {"status": "one"})
    second = store.compare_and_swap("mission", 0, {"status": "two"})

    assert first.generation == 0
    assert first.parent_generation is None
    assert second.generation == 1
    assert second.parent_generation == 0
    assert second.parent_sha256 == first.payload_sha256
    assert store.load_current("mission").payload == {"status": "two"}


def test_identical_payload_is_a_noop_snapshot(tmp_path):
    store = state.SQLiteStateStore(tmp_path / "state.db")
    first = store.compare_and_swap("mission", None, {"status": "same"})
    again = store.compare_and_swap("mission", 0, {"status": "same"})
    assert again == first

    with sqlite3.connect(tmp_path / "state.db") as conn:
        count = conn.execute("SELECT COUNT(*) FROM snapshots WHERE mission_id='mission'").fetchone()[0]
    assert count == 1


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


def test_corrupt_tip_is_not_treated_as_empty_or_overwritten(tmp_path):
    path = tmp_path / "state.db"
    store = state.SQLiteStateStore(path)
    first = store.compare_and_swap("mission", None, {"value": 1})
    store.compare_and_swap("mission", 0, {"value": 2})
    _tamper_payload(path, "mission", 1, '{"value":"tampered"}')

    with pytest.raises(state.StateCorruption, match="digest mismatch"):
        store.load_current("mission")
    with pytest.raises(state.StateCorruption):
        store.compare_and_swap("mission", 1, {"value": 3})

    inspected = store.inspect_previous_valid("mission")
    assert inspected.generation == 0
    assert inspected.payload_sha256 == first.payload_sha256

    with sqlite3.connect(path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM snapshots WHERE mission_id='mission'").fetchone()[0]
    assert count == 2


def test_explicit_recovery_appends_new_generation_and_preserves_corrupt_history(tmp_path):
    path = tmp_path / "state.db"
    store = state.SQLiteStateStore(path)
    first = store.compare_and_swap("mission", None, {"value": 1})
    store.compare_and_swap("mission", 0, {"value": 2})
    _tamper_payload(path, "mission", 1, '{"value":"tampered"}')

    recovered = store.recover_to_previous_valid("mission", expected_tip_generation=1)
    assert recovered.generation == 2
    assert recovered.transition_kind == "recovery"
    assert recovered.parent_generation == 0
    assert recovered.parent_sha256 == first.payload_sha256
    assert recovered.payload == {"value": 1}
    assert recovered.quarantined_generations == (1,)

    current = store.load_current("mission")
    assert current.generation == 2
    assert current.transition_kind == "recovery"
    assert current.quarantined_generations == (1,)

    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "SELECT generation, transition_kind, payload_json FROM snapshots WHERE mission_id='mission' ORDER BY generation"
        ).fetchall()
    assert [row[0] for row in rows] == [0, 1, 2]
    assert rows[1][2] == '{"value":"tampered"}'
    assert rows[2][1] == "recovery"


def test_recovery_is_race_protected_and_cannot_run_on_valid_tip(tmp_path):
    store = state.SQLiteStateStore(tmp_path / "state.db")
    store.compare_and_swap("mission", None, {"value": 1})

    with pytest.raises(state.StateStoreError, match="current state is valid"):
        store.recover_to_previous_valid("mission", expected_tip_generation=0)

    store.compare_and_swap("mission", 0, {"value": 2})
    with pytest.raises(state.StateConflict, match="recovery generation conflict"):
        store.recover_to_previous_valid("mission", expected_tip_generation=0)


def test_recovery_skips_a_chain_depending_on_a_corrupt_parent(tmp_path):
    path = tmp_path / "state.db"
    store = state.SQLiteStateStore(path)
    first = store.compare_and_swap("mission", None, {"value": 0})
    store.compare_and_swap("mission", 0, {"value": 1})
    store.compare_and_swap("mission", 1, {"value": 2})
    _tamper_payload(path, "mission", 1, '{"value":"bad-parent"}')

    with pytest.raises(state.StateCorruption):
        store.load_current("mission")
    recovered = store.recover_to_previous_valid("mission", expected_tip_generation=2)
    assert recovered.generation == 3
    assert recovered.parent_generation == 0
    assert recovered.parent_sha256 == first.payload_sha256
    assert recovered.quarantined_generations == (1, 2)


def test_parent_digest_substitution_is_detected(tmp_path):
    path = tmp_path / "state.db"
    store = state.SQLiteStateStore(path)
    store.compare_and_swap("mission", None, {"value": 1})
    store.compare_and_swap("mission", 0, {"value": 2})

    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE snapshots SET parent_sha256=? WHERE mission_id=? AND generation=?",
            ("f" * 64, "mission", 1),
        )
        conn.commit()

    with pytest.raises(state.StateCorruption, match="parent digest"):
        store.load_current("mission")


def test_missions_have_independent_generation_streams(tmp_path):
    store = state.SQLiteStateStore(tmp_path / "state.db")
    a = store.compare_and_swap("A", None, {"value": 1})
    b = store.compare_and_swap("B", None, {"value": 2})
    assert a.generation == 0
    assert b.generation == 0
    assert store.load_current("A").payload == {"value": 1}
    assert store.load_current("B").payload == {"value": 2}
