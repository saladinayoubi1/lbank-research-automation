"""Fault injection matrix for the issue #1848 simulation-only safety protocol."""
from __future__ import annotations

from decimal import Decimal
import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "scripts" / "nexus_owner_activation_protocol_model.py"
spec = importlib.util.spec_from_file_location("nexus_owner_activation_protocol_model_testonly", MODEL_PATH)
assert spec and spec.loader
model = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = model
spec.loader.exec_module(model)

OLD = "4" * 40
NEW = "9" * 40
JOURNAL = "a" * 64


def gate(**override):
    values = dict(
        main_sha=NEW,
        stage_sha=NEW,
        artifact_id=10890913225,
        owner_sha=OLD,
        journal_sha256=JOURNAL,
        main_current_verified=True,
        official_stage_proof_verified=True,
        independent_backup_manifest_pins_verified=True,
        owner_authorization_verified=True,
    )
    values.update(override)
    return model.Gate(**values)


class MemoryOnlyPort:
    """All mutation is confined to this Python instance; no host process/files."""
    def __init__(self, fault=""):
        self.fault = fault
        self.calls = []
        self.owner_running = True
        self.stage_running = False
        self.journal = JOURNAL
        self.shortcuts = [OLD] * 4
        self.sync = ["1" * 64, "2" * 64]
        self.runner_preserved = True
        self.remote_preserved = True
        self.attests = 0

    def _call(self, name):
        self.calls.append(name)

    def capture_owner(self):
        self._call("capture_owner")
        result = model.Snapshot(OLD, JOURNAL, (11, 22, 33, 44), 1, tuple(self.shortcuts), tuple(self.sync))
        if self.fault == "snapshot_wrong_journal":
            return model.Snapshot(OLD, "f" * 64, result.exact_owner_pids, 1, tuple(self.shortcuts), tuple(self.sync))
        if self.fault == "duplicate_pid":
            return model.Snapshot(OLD, JOURNAL, (11, 11, 33, 44), 1, tuple(self.shortcuts), tuple(self.sync))
        return result

    def verify_immutable_backup(self, snapshot):
        self._call("verify_immutable_backup")
        return self.fault != "backup_fail"

    def quiesce_exact_owner(self, snapshot):
        self._call("quiesce_exact_owner")
        self.owner_running = False
        if self.fault == "partial_stop":
            raise RuntimeError("injected partial process stop")

    def prove_old_absent_without_respawn(self, snapshot):
        self._call("prove_old_absent_without_respawn")
        if self.fault == "respawn":
            self.owner_running = True
        return not self.owner_running

    def launch_exact_stage(self, trusted_gate):
        self._call("launch_exact_stage")
        self.stage_running = True
        if self.fault == "partial_launch":
            raise RuntimeError("launch created child and then failed")

    def attest_exact_stage(self):
        self._call("attest_exact_stage")
        self.attests += 1
        if self.fault == "journal_mutated" and self.attests == 1:
            self.journal = "b" * 64
        return model.CandidateAttestation(
            source_sha=OLD if self.fault == "bad_source" else NEW,
            artifact_id=10890913225,
            journal_sha256=self.journal,
            paper_only=True,
            live_trading_authority=(self.fault == "live_enabled" or
                (self.fault == "postcommit_bad" and self.attests > 1)),
            orders_allowed=False,
            cash=Decimal("501") if self.fault == "cash_mismatch" else Decimal("500"),
            equity=Decimal("500"),
            open_positions=0,
        )

    def commit_shortcuts_and_sync(self):
        self._call("commit_shortcuts_and_sync")
        self.shortcuts[0] = NEW
        if self.fault == "partial_shortcut":
            raise RuntimeError("one shortcut committed")
        self.shortcuts[:] = [NEW] * 4
        self.sync[0] = "3" * 64
        if self.fault == "partial_sync":
            raise PermissionError("second sync file locked")
        self.sync[:] = ["3" * 64, "4" * 64]

    def verify_committed_state(self):
        self._call("verify_committed_state")
        return (self.fault not in {"commit_verify_failure", "cleanup_failure",
                                   "restore_files_failure", "restart_failure"} and self.stage_running
                and self.shortcuts == [NEW] * 4
                and self.sync == ["3" * 64, "4" * 64])

    def stop_exact_candidate_only(self):
        self._call("stop_exact_candidate_only")
        if self.fault == "cleanup_failure":
            raise RuntimeError("staged candidate cannot stop")
        self.stage_running = False

    def restore_original_shortcuts_and_sync(self, snapshot):
        self._call("restore_original_shortcuts_and_sync")
        self.shortcuts[:] = list(snapshot.shortcut_targets)
        self.sync[:] = list(snapshot.global_sync_sha256)
        if self.fault == "restore_files_failure":
            self.shortcuts[0] = NEW
            raise PermissionError("one backed-up shortcut cannot be restored")

    def restore_exact_owner_only(self, snapshot):
        self._call("restore_exact_owner_only")
        if self.fault == "restart_failure":
            raise RuntimeError("original owner cannot restart")
        self.owner_running = True

    def verify_full_restoration(self, snapshot):
        self._call("verify_full_restoration")
        return (self.owner_running and not self.stage_running
                and self.shortcuts == list(snapshot.shortcut_targets)
                and self.sync == list(snapshot.global_sync_sha256)
                and self.journal == snapshot.journal_sha256
                and self.runner_preserved and self.remote_preserved)


def test_successful_simulated_order_has_no_activation_authority():
    port = MemoryOnlyPort()
    result = model.simulate_activation(port, gate())
    assert result.decision == "SIMULATED_COMMIT_PATH_PASS"
    assert result.simulation_only is True and result.activation_authorized is False
    assert port.calls.index("prove_old_absent_without_respawn") < port.calls.index("launch_exact_stage")
    assert port.calls.index("attest_exact_stage") < port.calls.index("commit_shortcuts_and_sync")
    assert port.runner_preserved and port.remote_preserved


@pytest.mark.parametrize("fault", [
    "partial_stop", "respawn", "partial_launch", "bad_source",
    "live_enabled", "cash_mismatch", "partial_shortcut",
    "partial_sync", "commit_verify_failure", "postcommit_bad",
])
def test_failure_matrix_restores_exact_owner_and_never_claims_real_activation(fault):
    port = MemoryOnlyPort(fault)
    result = model.simulate_activation(port, gate())
    assert result.decision == "SIMULATED_ROLLBACK_VERIFIED"
    assert result.simulation_only and not result.activation_authorized
    assert port.shortcuts == [OLD] * 4
    assert port.sync == ["1" * 64, "2" * 64]
    assert port.owner_running and not port.stage_running
    assert port.runner_preserved and port.remote_preserved
    if fault in {"partial_stop", "respawn"}:
        assert "launch_exact_stage" not in port.calls
    if fault in {"bad_source", "live_enabled", "cash_mismatch"}:
        assert "commit_shortcuts_and_sync" not in port.calls
    if fault in {"partial_stop", "respawn", "partial_launch", "bad_source", "live_enabled", "cash_mismatch"}:
        assert "restore_original_shortcuts_and_sync" not in port.calls
        assert "owner_files_untouched_before_commit" in result.operations


@pytest.mark.parametrize("unsafe", [
    {"main_current_verified": False},
    {"official_stage_proof_verified": False},
    {"independent_backup_manifest_pins_verified": False},
    {"owner_authorization_verified": False},
    {"main_sha": OLD},
    {"main_sha": "z" * 40, "stage_sha": "z" * 40},
    {"journal_sha256": "z" * 64},
])
def test_untrusted_preflight_never_captures_or_stops_owner(unsafe):
    port = MemoryOnlyPort()
    result = model.simulate_activation(port, gate(**unsafe))
    assert result.decision == "REFUSED_UNTRUSTED_GATE"
    assert port.calls == []
    assert port.owner_running and not port.stage_running


@pytest.mark.parametrize("fault,expected", [
    ("snapshot_wrong_journal", "REFUSED_OWNER_STATE_MISMATCH"),
    ("duplicate_pid", "REFUSED_OWNER_STATE_MISMATCH"),
    ("backup_fail", "REFUSED_BACKUP_UNVERIFIED"),
])
def test_snapshot_and_backup_failure_are_action_free(fault, expected):
    port = MemoryOnlyPort(fault)
    result = model.simulate_activation(port, gate())
    assert result.decision == expected
    assert "quiesce_exact_owner" not in port.calls
    assert port.owner_running and port.shortcuts == [OLD] * 4


@pytest.mark.parametrize("fault,expected_error", [
    ("cleanup_failure", "CANDIDATE_CLEANUP_FAILED"),
    ("restore_files_failure", "ORIGINAL_FILE_RESTORATION_FAILED"),
    ("restart_failure", "EXACT_OWNER_RESTART_FAILED"),
    ("journal_mutated", "RESTORATION_EVIDENCE_INCOMPLETE"),
])
def test_unverified_rollback_fails_closed_and_attempts_other_restorations(fault, expected_error):
    port = MemoryOnlyPort(fault)
    result = model.simulate_activation(port, gate())
    assert result.decision == "SIMULATED_ROLLBACK_UNVERIFIED_FAIL_CLOSED"
    assert expected_error in result.restoration_errors
    if fault == "journal_mutated":
        assert "restore_original_shortcuts_and_sync" not in port.calls
        assert "owner_files_untouched_before_commit" in result.operations
    else:
        assert "restore_original_shortcuts_and_sync" in port.calls
    assert "restore_exact_owner_only" in port.calls
    assert "verify_full_restoration" in port.calls
    assert not result.activation_authorized


def test_reference_model_is_not_wired_to_actual_installer():
    installer = (ROOT / "scripts" / "install_and_smoke_nexus_personal_pro.ps1").read_text(encoding="utf-8")
    model_source = MODEL_PATH.read_text(encoding="utf-8")
    assert MODEL_PATH.name not in installer
    assert "SimulationReceipt" in model_source
    assert "activation_authorized: bool = False" in model_source
    assert "UNSAFE_LEGACY_OWNER_ACTIVATION_DISABLED" in installer
