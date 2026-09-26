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



@dataclass(frozen=True)
class ProfileEntry:
    """Simulated source/destination hashes for one persisted original owner file."""
    relative_path: str
    bytes: int
    source_sha256: str
    copied_sha256: str


@dataclass(frozen=True)
class FullProfileEvidence:
    """Untrusted reference receipt; never physical activation proof on its own."""
    owner_source_sha: str
    journal_sha256: str
    source_file_count: int
    copied_file_count: int
    files: tuple[ProfileEntry, ...]
    private_acl_verified: bool
    complete_persistent_inventory_verified: bool
    old_owner_absent_during_capture: bool
    reparse_points_refused: bool

    def valid_for(self, gate: Gate, snapshot: Snapshot) -> bool:
        required = {
            "Network/Cookies", "Local State", "Preferences",
            "product-data/product_runtime/paper-events.jsonl",
        }
        paths = [entry.relative_path for entry in self.files]
        found = set(paths)
        return (
            self.owner_source_sha == gate.owner_sha
            and self.journal_sha256 == snapshot.journal_sha256
            and self.private_acl_verified is True
            and self.complete_persistent_inventory_verified is True
            and self.old_owner_absent_during_capture is True
            and self.reparse_points_refused is True
            and self.source_file_count == self.copied_file_count == len(self.files)
            and len(found) == len(self.files)
            and len({p.casefold() for p in paths}) == len(paths)
            and required <= found
            and any(p.startswith("Local Storage/") for p in paths)
            and any(p.startswith("Session Storage/") for p in paths)
            and all(
                p and not p.startswith("/") and chr(92) not in p and ":" not in p and
                all(part not in ("", ".", "..") for part in p.split("/"))
                for p in paths
            )
            and all(
                entry.bytes >= 0
                and re.fullmatch(r"[0-9a-fA-F]{64}", entry.source_sha256) is not None
                and entry.source_sha256 == entry.copied_sha256
                for entry in self.files
            )
        )


class Port(Protocol):
    """Pure test seam; no concrete production implementation is included."""

    def capture_owner(self) -> Snapshot: ...
    def verify_immutable_backup(self, snapshot: Snapshot) -> bool: ...
    def quiesce_exact_owner(self, snapshot: Snapshot) -> None: ...
    def prove_old_absent_without_respawn(self, snapshot: Snapshot) -> bool: ...
    def capture_full_profile_after_quiescence(self, snapshot: Snapshot) -> FullProfileEvidence: ...
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

        # An earlier product-data backup is not a consistent persisted Electron
        # profile. Copy and hash the complete profile only AFTER exact owner
        # quiescence; locked Cookies or incomplete coverage must roll back.
        step = "capture_full_profile_after_quiescence"
        evidence = port.capture_full_profile_after_quiescence(snapshot)
        if not evidence.valid_for(gate, snapshot):
            raise RuntimeError("FULL_PERSISTENT_PROFILE_UNVERIFIED")
        events.append(step)

        # Prevent an owner respawn while the full-profile snapshot was copied.
        step = "prove_owner_still_absent_after_full_profile"
        if not port.prove_old_absent_without_respawn(snapshot):
            raise RuntimeError("OWNER_RESPAWNED_DURING_FULL_PROFILE")
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
