from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_SCHEMA = "nexus.phase5-state.v1"
MAX_STATE_BYTES = 2_000_000


class StateStoreError(RuntimeError):
    pass


class StateConflict(StateStoreError):
    pass


class StateCorruption(StateStoreError):
    pass


@dataclass(frozen=True)
class StateRecord:
    mission_id: str
    generation: int
    payload: dict[str, Any]
    payload_sha256: str
    parent_generation: int | None
    parent_sha256: str | None
    transition_kind: str
    created_at: str
    quarantined_generations: tuple[int, ...] = ()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    if not isinstance(payload, dict):
        raise StateStoreError("state payload root must be an object")
    try:
        raw = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise StateStoreError("state payload is not canonical JSON") from exc
    if len(raw) > MAX_STATE_BYTES:
        raise StateStoreError("state payload exceeds bounded size")
    return raw


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _strict_json(raw: str, *, label: str) -> Any:
    try:
        return json.loads(
            raw,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"invalid constant {value}")),
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise StateCorruption(f"stored {label} JSON is malformed") from exc


class SQLiteStateStore:
    """Durable Phase 5 state snapshots with CAS fencing and explicit recovery.

    The SQLite file is intended for a persistent volume, not an Actions cache.
    Normal writes use BEGIN IMMEDIATE and exact generation CAS. Snapshots are
    immutable. A corrupted tip cannot be overwritten or treated as empty; an
    explicit recovery appends a new higher generation that points to the newest
    previous-valid generation and records which intervening generations were
    quarantined.
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS snapshots (
                    mission_id TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    schema_version TEXT NOT NULL,
                    transition_kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    parent_generation INTEGER,
                    parent_sha256 TEXT,
                    quarantine_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (mission_id, generation)
                )
                """
            )
            result = conn.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise StateCorruption("SQLite integrity check failed")

    @staticmethod
    def _rows(conn: sqlite3.Connection, mission_id: str) -> list[sqlite3.Row]:
        return list(
            conn.execute(
                "SELECT mission_id, generation, schema_version, transition_kind, payload_json, "
                "payload_sha256, parent_generation, parent_sha256, quarantine_json, created_at "
                "FROM snapshots WHERE mission_id=? ORDER BY generation ASC",
                (mission_id,),
            )
        )

    @staticmethod
    def _row_map(rows: list[sqlite3.Row]) -> dict[int, sqlite3.Row]:
        return {int(row["generation"]): row for row in rows}

    @classmethod
    def _validate_row(
        cls,
        row: sqlite3.Row,
        by_generation: dict[int, sqlite3.Row],
        *,
        visiting: set[int] | None = None,
    ) -> StateRecord:
        generation = int(row["generation"])
        visiting = set() if visiting is None else visiting
        if generation in visiting:
            raise StateCorruption("stored state parent cycle detected")
        visiting.add(generation)
        try:
            if row["schema_version"] != STATE_SCHEMA:
                raise StateCorruption("unsupported stored state schema")
            if row["transition_kind"] not in {"normal", "recovery"}:
                raise StateCorruption("unsupported stored state transition kind")

            raw = row["payload_json"].encode("utf-8")
            if len(raw) > MAX_STATE_BYTES:
                raise StateCorruption("stored state exceeds bounded size")
            if _digest(raw) != row["payload_sha256"]:
                raise StateCorruption("stored state digest mismatch")
            payload = _strict_json(row["payload_json"], label="state")
            if not isinstance(payload, dict):
                raise StateCorruption("stored state root must be an object")
            try:
                if _canonical_bytes(payload) != raw:
                    raise StateCorruption("stored state is not canonical")
            except StateStoreError as exc:
                raise StateCorruption(str(exc)) from exc

            quarantined = _strict_json(row["quarantine_json"], label="quarantine")
            if (
                not isinstance(quarantined, list)
                or any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in quarantined)
                or quarantined != sorted(set(quarantined))
            ):
                raise StateCorruption("stored quarantine generations are invalid")

            parent_generation = row["parent_generation"]
            parent_sha256 = row["parent_sha256"]
            if generation == 0:
                if parent_generation is not None or parent_sha256 is not None:
                    raise StateCorruption("initial state must not have a parent")
                if row["transition_kind"] != "normal" or quarantined:
                    raise StateCorruption("initial state must be a normal non-recovery snapshot")
            else:
                if isinstance(parent_generation, bool) or not isinstance(parent_generation, int):
                    raise StateCorruption("stored state parent generation is invalid")
                if parent_generation < 0 or parent_generation >= generation:
                    raise StateCorruption("stored state parent generation is out of order")
                parent = by_generation.get(parent_generation)
                if parent is None:
                    raise StateCorruption("stored state parent generation is missing")
                parent_record = cls._validate_row(parent, by_generation, visiting=visiting)
                if parent_sha256 != parent_record.payload_sha256:
                    raise StateCorruption("stored state parent digest mismatch")
                if row["transition_kind"] == "normal":
                    if parent_generation != generation - 1 or quarantined:
                        raise StateCorruption("normal state transition must extend the immediate valid parent")
                else:
                    if not quarantined:
                        raise StateCorruption("recovery transition must identify quarantined generations")
                    if any(item <= parent_generation or item >= generation for item in quarantined):
                        raise StateCorruption("recovery quarantine range is invalid")

            return StateRecord(
                mission_id=row["mission_id"],
                generation=generation,
                payload=payload,
                payload_sha256=row["payload_sha256"],
                parent_generation=parent_generation,
                parent_sha256=parent_sha256,
                transition_kind=row["transition_kind"],
                created_at=row["created_at"],
                quarantined_generations=tuple(quarantined),
            )
        finally:
            visiting.remove(generation)

    def load_current(self, mission_id: str) -> StateRecord | None:
        with self._connect() as conn:
            rows = self._rows(conn, mission_id)
            if not rows:
                return None
            return self._validate_row(rows[-1], self._row_map(rows))

    def inspect_previous_valid(self, mission_id: str) -> StateRecord | None:
        """Find a previous-valid state without mutating or hiding corrupt history."""
        with self._connect() as conn:
            rows = self._rows(conn, mission_id)
            if not rows:
                return None
            by_generation = self._row_map(rows)
            for row in reversed(rows):
                try:
                    return self._validate_row(row, by_generation)
                except StateCorruption:
                    continue
            raise StateCorruption("no previous-valid state snapshot exists")

    def compare_and_swap(
        self,
        mission_id: str,
        expected_generation: int | None,
        payload: dict[str, Any],
    ) -> StateRecord:
        if not isinstance(mission_id, str) or not mission_id or len(mission_id) > 160:
            raise StateStoreError("mission_id must be a non-empty bounded string")
        raw = _canonical_bytes(payload)
        payload_json = raw.decode("utf-8")
        payload_sha256 = _digest(raw)

        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            rows = self._rows(conn, mission_id)
            current = rows[-1] if rows else None
            current_generation = None if current is None else int(current["generation"])
            if current_generation != expected_generation:
                raise StateConflict(
                    f"state generation conflict: expected {expected_generation}, current {current_generation}"
                )

            if current is None:
                generation = 0
                parent_generation = None
                parent_sha256 = None
            else:
                current_record = self._validate_row(current, self._row_map(rows))
                if current_record.payload_sha256 == payload_sha256:
                    conn.rollback()
                    return current_record
                generation = current_generation + 1
                parent_generation = current_generation
                parent_sha256 = current_record.payload_sha256

            created_at = _utcnow()
            conn.execute(
                "INSERT INTO snapshots(mission_id, generation, schema_version, transition_kind, payload_json, "
                "payload_sha256, parent_generation, parent_sha256, quarantine_json, created_at) "
                "VALUES (?, ?, ?, 'normal', ?, ?, ?, ?, '[]', ?)",
                (
                    mission_id,
                    generation,
                    STATE_SCHEMA,
                    payload_json,
                    payload_sha256,
                    parent_generation,
                    parent_sha256,
                    created_at,
                ),
            )
            conn.commit()
            return StateRecord(
                mission_id=mission_id,
                generation=generation,
                payload=payload,
                payload_sha256=payload_sha256,
                parent_generation=parent_generation,
                parent_sha256=parent_sha256,
                transition_kind="normal",
                created_at=created_at,
            )
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def recover_to_previous_valid(self, mission_id: str, expected_tip_generation: int) -> StateRecord:
        """Append an auditable recovery snapshot after a corrupted current tip.

        The corrupted rows remain immutable. Recovery is allowed only when the
        exact expected tip still exists and is invalid. The new generation is
        monotonic but points to the newest recursively valid older generation.
        """
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            rows = self._rows(conn, mission_id)
            if not rows:
                raise StateCorruption("cannot recover a mission with no snapshots")
            tip_generation = int(rows[-1]["generation"])
            if tip_generation != expected_tip_generation:
                raise StateConflict(
                    f"recovery generation conflict: expected {expected_tip_generation}, current {tip_generation}"
                )
            by_generation = self._row_map(rows)
            try:
                self._validate_row(rows[-1], by_generation)
            except StateCorruption:
                pass
            else:
                raise StateStoreError("current state is valid; recovery is not permitted")

            previous_valid: StateRecord | None = None
            for row in reversed(rows[:-1]):
                try:
                    previous_valid = self._validate_row(row, by_generation)
                    break
                except StateCorruption:
                    continue
            if previous_valid is None:
                raise StateCorruption("no previous-valid state snapshot exists")

            generation = tip_generation + 1
            quarantined = tuple(range(previous_valid.generation + 1, generation))
            quarantine_json = json.dumps(list(quarantined), separators=(",", ":"))
            payload_json = _canonical_bytes(previous_valid.payload).decode("utf-8")
            created_at = _utcnow()
            conn.execute(
                "INSERT INTO snapshots(mission_id, generation, schema_version, transition_kind, payload_json, "
                "payload_sha256, parent_generation, parent_sha256, quarantine_json, created_at) "
                "VALUES (?, ?, ?, 'recovery', ?, ?, ?, ?, ?, ?)",
                (
                    mission_id,
                    generation,
                    STATE_SCHEMA,
                    payload_json,
                    previous_valid.payload_sha256,
                    previous_valid.generation,
                    previous_valid.payload_sha256,
                    quarantine_json,
                    created_at,
                ),
            )
            conn.commit()
            return StateRecord(
                mission_id=mission_id,
                generation=generation,
                payload=previous_valid.payload,
                payload_sha256=previous_valid.payload_sha256,
                parent_generation=previous_valid.generation,
                parent_sha256=previous_valid.payload_sha256,
                transition_kind="recovery",
                created_at=created_at,
                quarantined_generations=quarantined,
            )
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
