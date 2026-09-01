from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import nexus_persistent_paper_bounded_cycle as bounded


class PersistentPaperBoundedCycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manifest_path = self.root / "manifest.json"
        self.policy_path = self.root / "policy.json"
        self.source_sha = "a" * 40

    def tearDown(self):
        self.temp.cleanup()

    def _run(self, *, blocked: int):
        manifest = {
            "symbols": ["BTCUSDT", "ETHUSDT"],
            "timeframes": ["minute15", "hour1", "hour4"],
            "families": ["momentum", "trend_breakout", "mean_reversion"],
        }
        pre_state = {"cells": {}}
        pre_snapshot = {
            "blocked_cell_count": blocked,
            "verified_cell_count": 6 - blocked,
        }
        final_snapshot = {"status": "WAITING_FOR_FRESH_CELLS" if blocked else "PAPER_LOOP_ACTIVE"}
        sleeper = Mock()

        with (
            patch.object(bounded, "load_manifest", return_value=manifest),
            patch.object(bounded, "load_state", return_value={}),
            patch.object(bounded, "run_matrix_cycle", return_value=(pre_state, pre_snapshot)) as matrix,
            patch.object(bounded, "verify_snapshot", return_value={"decision": "pass"}),
            patch.object(bounded, "_matrix_atomic_json") as atomic,
            patch.object(bounded, "run_persistent_cycle", return_value=final_snapshot) as persistent,
            patch.object(bounded, "verify_loop_snapshot", return_value={"decision": "pass"}),
        ):
            result = bounded.run_bounded_cycle(
                repo_root=self.root,
                state_root=self.root / "state",
                source_sha=self.source_sha,
                run_id="42",
                now_ms=1_800_000_000_000,
                manifest_path=self.manifest_path,
                selector_policy_path=self.policy_path,
                sleep=sleeper,
            )

        self.assertIs(result, final_snapshot)
        self.assertEqual(matrix.call_count, 1)
        self.assertEqual(persistent.call_count, 1)
        self.assertEqual(atomic.call_count, 2)
        return sleeper, matrix, persistent

    def test_blocked_cells_get_exactly_one_cooldown_before_final_pass(self):
        sleeper, _, _ = self._run(blocked=1)
        sleeper.assert_called_once_with(bounded.BLOCKED_CELL_COOLDOWN_SECONDS)
        self.assertEqual(bounded.BLOCKED_CELL_COOLDOWN_SECONDS, 30.0)

    def test_all_verified_cells_do_not_add_second_pass_cooldown(self):
        sleeper, _, _ = self._run(blocked=0)
        sleeper.assert_not_called()

    def test_prepass_verification_failure_stops_before_persistent_cycle(self):
        with (
            patch.object(bounded, "load_manifest", return_value={}),
            patch.object(bounded, "load_state", return_value={}),
            patch.object(
                bounded,
                "run_matrix_cycle",
                return_value=({}, {"blocked_cell_count": 1, "verified_cell_count": 5}),
            ),
            patch.object(bounded, "verify_snapshot", return_value={"decision": "reject"}),
            patch.object(bounded, "run_persistent_cycle") as persistent,
        ):
            with self.assertRaisesRegex(
                bounded.PersistentPaperTradingLoopError,
                "bounded matrix pre-pass failed verification",
            ):
                bounded.run_bounded_cycle(
                    repo_root=self.root,
                    state_root=self.root / "state",
                    source_sha=self.source_sha,
                    run_id="42",
                    now_ms=1_800_000_000_000,
                    manifest_path=self.manifest_path,
                    selector_policy_path=self.policy_path,
                    sleep=Mock(),
                )
            persistent.assert_not_called()


if __name__ == "__main__":
    unittest.main()
