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
    previous_sha256: str | None
    created_at: str
    recovered: bool = False
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


def _strict_json(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(
            raw,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"invalid constant {value}")),
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise StateCorruption("stored state JSON is malformed") from exc
    if not isinstance(payload, dict):
        raise StateCorruption("stored state root must be an object")
    return payload


class SQLiteStateStore:
    """Durable, generation-fenced Phase 5 state store for a persistent volume.

    Writes use BEGIN IMMEDIATE plus compare-and-swap generation checks. Every
    snapshot is immutable and hash-chained to the previous generation. Recovery
    from a corrupted newest snapshot is explicit through recover_previous_valid;
    corruption is never treated as an empty state.
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
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    previous_sha256 TEXT,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (mission_id, generation)
                )
                """
            )
            result = conn.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise StateCorruption("SQLite integrity check failed")

    @staticmethod
    def _row_to_record(row: sqlite3.Row, previous_row: sqlite3.Row | None = None) -> StateRecord:
        if row["schema_version"] != STATE_SCHEMA:
            raise StateCorruption("unsupported stored state schema")
        raw = row["payload_json"].encode("utf-8")
        if len(raw) > MAX_STATE_BYTES:
            raise StateCorruption("stored state exceeds bounded size")
        actual = _digest(raw)
        if actual != row["payload_sha256"]:
            raise StateCorruption("stored state digest mismatch")
        payload = _strict_json(row["payload_json"])
        # Canonical serialization must reproduce the exact stored bytes. This
        # rejects semantically equivalent but substituted/non-canonical state.
        if _canonical_bytes(payload) != raw:
            raise StateCorruption("stored state is not canonical")
        expected_previous = None if previous_row is None else previous_row["payload_sha256"]
        if row["previous_sha256"] != expected_previous:
            raise StateCorruption("stored state hash chain mismatch")
        return StateRecord(
            mission_id=row["mission_id"],
            generation=int(row["generation"]),
            payload=payload,
            payload_sha256=row["payload_sha256"],
            previous_sha256=row["previous_sha256"],
            created_at=row["created_at"],
        )

    def _rows(self, conn: sqlite3.Connection, mission_id: str) -> list[sqlite3.Row]:
        return list(
            conn.execute(
                "SELECT mission_id, generation, schema_version, payload_json, payload_sha256, "
                "previous_sha256, created_at FROM snapshots WHERE mission_id=? ORDER BY generation ASC",
                (mission_id,),
            )
        )

    def load_current(self, mission_id: str) -> StateRecord | None:
        with self._connect() as conn:
            rows = self._rows(conn, mission_id)
            if not rows:
                return None
            row = rows[-1]
            previous = rows[-2] if len(rows) > 1 else None
            return self._row_to_record(row, previous)

    def recover_previous_valid(self, mission_id: str) -> StateRecord | None:
        """Return the newest valid snapshot without pretending corruption vanished."""
        with self._connect() as conn:
            rows = self._rows(conn, mission_id)
            if not rows:
                return None
            quarantined: list[int] = []
            for index in range(len(rows) - 1, -1, -1):
                row = rows[index]
                previous = rows[index - 1] if index > 0 else None
                try:
                    record = self._row_to_record(row, previous)
                except StateCorruption:
                    quarantined.append(int(row["generation"]))
                    continue
                return StateRecord(
                    **{**record.__dict__, "recovered": bool(quarantined), "quarantined_generations": tuple(quarantined)}
                )
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

            if current is not None:
                previous = rows[-2] if len(rows) > 1 else None
                # Never append to a corrupted chain.
                self._row_to_record(current, previous)
                previous_sha256 = current["payload_sha256"]
                generation = current_generation + 1
            else:
                previous_sha256 = None
                generation = 0

            created_at = _utcnow()
            conn.execute(
                "INSERT INTO snapshots(mission_id, generation, schema_version, payload_json, payload_sha256, "
                "previous_sha256, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    mission_id,
                    generation,
                    STATE_SCHEMA,
                    payload_json,
                    payload_sha256,
                    previous_sha256,
                    created_at,
                ),
            )
            conn.commit()
            return StateRecord(
                mission_id=mission_id,
                generation=generation,
                payload=payload,
                payload_sha256=payload_sha256,
                previous_sha256=previous_sha256,
                created_at=created_at,
            )
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
