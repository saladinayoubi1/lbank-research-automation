"""Reference coordinator for Issue #1848 fault injection.

No production adapter, owner process control, filesystem I/O or authorization is
provided here. Test fixtures may implement the Port protocol, but a successful
simulation is NEVER evidence that the real owner can be activated.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re
from typing import Protocol


@dataclass(frozen=True)
class Gate:
    main_sha: str
    stage_sha: str
    artifact_id: int
    owner_sha: str
    journal_sha256: str
    main_current_verified: bool
    official_stage_proof_verified: bool
    independent_backup_manifest_pins_verified: bool
    owner_authorization_verified: bool

    def trusted(self) -> bool:
        return (
            self.main_sha == self.stage_sha
            and re.fullmatch(r"[0-9a-fA-F]{40}", self.main_sha) is not None
            and self.owner_sha != self.stage_sha
            and re.fullmatch(r"[0-9a-fA-F]{40}", self.owner_sha) is not None
            and re.fullmatch(r"[0-9a-fA-F]{64}", self.journal_sha256) is not None
            and self.artifact_id > 0
            and self.main_current_verified is True
            and self.official_stage_proof_verified is True
            and self.independent_backup_manifest_pins_verified is True
            and self.owner_authorization_verified is True
        )


@dataclass(frozen=True)
class Snapshot:
    source_sha: str
    journal_sha256: str
    exact_owner_pids: tuple[int, ...]
    owner_session_id: int
    shortcut_targets: tuple[str, ...]  # resolved source SHA of each .lnk executable
    global_sync_sha256: tuple[str, ...]


@dataclass(frozen=True)
class CandidateAttestation:
    source_sha: str
    artifact_id: int
    journal_sha256: str
    paper_only: bool
    live_trading_authority: bool
    orders_allowed: bool
    cash: Decimal
    equity: Decimal
    open_positions: int

    def safe_for(self, gate: Gate, snapshot: Snapshot) -> bool:
        return (
            self.source_sha == gate.stage_sha
            and self.artifact_id == gate.artifact_id
            and self.journal_sha256 == snapshot.journal_sha256
            and self.paper_only is True
            and self.live_trading_authority is False
            and self.orders_allowed is False
            and self.cash == Decimal("500")
            and self.equity == Decimal("500")
            and self.open_positions == 0
        )


class Port(Protocol):
    """Pure test seam; no concrete production implementation is included."""

    def capture_owner(self) -> Snapshot: ...
    def verify_immutable_backup(self, snapshot: Snapshot) -> bool: ...
    def quiesce_exact_owner(self, snapshot: Snapshot) -> None: ...
    def prove_old_absent_without_respawn(self, snapshot: Snapshot) -> bool: ...
    def launch_exact_stage(self, gate: Gate) -> None: ...
    def attest_exact_stage(self) -> CandidateAttestation: ...
    def commit_shortcuts_and_sync(self) -> None: ...
    def verify_committed_state(self) -> bool: ...
    def stop_exact_candidate_only(self) -> None: ...
    def restore_original_shortcuts_and_sync(self, snapshot: Snapshot) -> None: ...
    def restore_exact_owner_only(self, snapshot: Snapshot) -> None: ...
    def verify_full_restoration(self, snapshot: Snapshot) -> bool: ...


@dataclass(frozen=True)
class SimulationReceipt:
    decision: str
    at_step: str
    operations: tuple[str, ...]
    restoration_errors: tuple[str, ...] = ()
    simulation_only: bool = True
    activation_authorized: bool = False


def simulate_activation(port: Port, gate: Gate) -> SimulationReceipt:
    """Exercise ordered safety boundaries; never grant real activation authority."""
    events: list[str] = []
    if not gate.trusted():
        return SimulationReceipt("REFUSED_UNTRUSTED_GATE", "external_trust", tuple(events))

    step = "capture_owner"
    try:
        snapshot = port.capture_owner()
        events.append(step)
    except Exception:
        return SimulationReceipt("REFUSED_SNAPSHOT_FAILED", step, tuple(events))

    if (
        snapshot.source_sha != gate.owner_sha
        or snapshot.journal_sha256 != gate.journal_sha256
        or len(snapshot.exact_owner_pids) < 1
        or any(pid <= 0 for pid in snapshot.exact_owner_pids)
        or len(set(snapshot.exact_owner_pids)) != len(snapshot.exact_owner_pids)
        or snapshot.owner_session_id <= 0
        or len(snapshot.shortcut_targets) != 4
        or len(snapshot.global_sync_sha256) != 2
        or any(target != gate.owner_sha for target in snapshot.shortcut_targets)
        or any(re.fullmatch(r"[0-9a-fA-F]{64}", h) is None
               for h in snapshot.global_sync_sha256)
    ):
        return SimulationReceipt("REFUSED_OWNER_STATE_MISMATCH", step, tuple(events))

    step = "verify_immutable_backup"
    try:
        if not port.verify_immutable_backup(snapshot):
            return SimulationReceipt("REFUSED_BACKUP_UNVERIFIED", step, tuple(events))
        events.append(step)
    except Exception:
        return SimulationReceipt("REFUSED_BACKUP_UNVERIFIED", step, tuple(events))

    quiesce_attempted = False
    candidate_attempted = False
    file_commit_attempted = False
    try:
        step = "quiesce_exact_owner"
        quiesce_attempted = True  # Even a throwing stop may have partially stopped the GUI.
        port.quiesce_exact_owner(snapshot)
        events.append(step)

        step = "prove_old_absent_without_respawn"
        if not port.prove_old_absent_without_respawn(snapshot):
            raise RuntimeError("EXACT_OWNER_RESPAWN_OR_NOT_QUIESCENT")
        events.append(step)

        step = "launch_exact_stage"
        candidate_attempted = True  # Launch can create children and still throw.
        port.launch_exact_stage(gate)
        events.append(step)

        step = "attest_exact_stage_before_mutation"
        if not port.attest_exact_stage().safe_for(gate, snapshot):
            raise RuntimeError("CANDIDATE_ATTESTATION_FAILED")
        events.append(step)

        step = "commit_shortcuts_and_sync"
        file_commit_attempted = True  # Partial writes still require full rollback.
        port.commit_shortcuts_and_sync()
        events.append(step)

        step = "verify_committed_state"
        if not port.verify_committed_state():
            raise RuntimeError("COMMIT_NOT_VERIFIED")
        events.append(step)

        step = "reattest_after_commit"
        if not port.attest_exact_stage().safe_for(gate, snapshot):
            raise RuntimeError("POST_COMMIT_AUTHORITY_OR_JOURNAL_MISMATCH")
        events.append(step)
        return SimulationReceipt("SIMULATED_COMMIT_PATH_PASS", step, tuple(events))
    except Exception:
        failed_at = step

    # Independently attempt EVERY restoration step even if the previous one fails.
    errors: list[str] = []
    if candidate_attempted:
        try:
            port.stop_exact_candidate_only()
            events.append("stop_exact_candidate_only")
        except Exception:
            errors.append("CANDIDATE_CLEANUP_FAILED")
    if file_commit_attempted:
        try:
            port.restore_original_shortcuts_and_sync(snapshot)
            events.append("restore_original_shortcuts_and_sync")
        except Exception:
            errors.append("ORIGINAL_FILE_RESTORATION_FAILED")
    else:
        # No shortcut/sync rewrite is permitted before verified quiescence and stage health.
        events.append("owner_files_untouched_before_commit")
    if quiesce_attempted:
        try:
            port.restore_exact_owner_only(snapshot)
            events.append("restore_exact_owner_only")
        except Exception:
            errors.append("EXACT_OWNER_RESTART_FAILED")
    try:
        if not port.verify_full_restoration(snapshot):
            errors.append("RESTORATION_EVIDENCE_INCOMPLETE")
        else:
            events.append("verify_full_restoration")
    except Exception:
        errors.append("RESTORATION_EVIDENCE_EXCEPTION")
    decision = "SIMULATED_ROLLBACK_VERIFIED" if not errors else "SIMULATED_ROLLBACK_UNVERIFIED_FAIL_CLOSED"
    return SimulationReceipt(decision, failed_at, tuple(events), tuple(errors))
