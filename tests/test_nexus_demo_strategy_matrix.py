from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from nexus_demo_strategy_matrix import (
    DemoStrategyMatrixError,
    load_manifest,
    load_state,
    run_matrix_cycle,
    verify_snapshot,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "config" / "nexus-demo-strategy-matrix-v1.json"
SOURCE_SHA = "a" * 40
NOW_MS = 1_800_000_000_000


def _runner(**kwargs):
    symbol = kwargs["symbol"]
    timeframe = kwargs["timeframe"]
    tasks = []
    for family in kwargs["families"]:
        tasks.append({
            "family": family,
            "task_id": f"{symbol}:{timeframe}:{family}",
            "status": "qualification_killed",
            "evidence_digest": (family[0] * 64),
        })
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "paper_only": True,
        "live_trading_authority": False,
        "tasks": tasks,
        "ledger_digest": (symbol[0].lower() * 64),
    }


def _verifier(_ledger):
    return {"decision": "pass", "verification_digest": "b" * 64}


def _analyzer(_root, _ledger):
    return {
        "paper_only": True,
        "live_trading_authority": False,
        "status_counts": {},
        "projection_digest": "c" * 64,
    }


class DemoStrategyMatrixTests(unittest.TestCase):
    def setUp(self):
        self.manifest = load_manifest(MANIFEST_PATH)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state = load_state(self.root / "matrix-state.json", self.manifest)

    def tearDown(self):
        self.temp.cleanup()

    def test_full_2x3x3_matrix_is_verified_and_isolated(self):
        calls = []

        def runner(**kwargs):
            calls.append((kwargs["symbol"], kwargs["timeframe"], Path(kwargs["state_root"])))
            return _runner(**kwargs)

        state, snapshot = run_matrix_cycle(
            manifest=self.manifest,
            state=self.state,
            state_root=self.root,
            source_sha=SOURCE_SHA,
            run_id="42",
            now_ms=NOW_MS,
            runner=runner,
            verifier=_verifier,
            analyzer=_analyzer,
        )
        self.assertEqual(snapshot["status"], "VERIFIED")
        self.assertEqual(snapshot["expected_cell_count"], 6)
        self.assertEqual(snapshot["verified_cell_count"], 6)
        self.assertEqual(snapshot["expected_lane_count"], 18)
        self.assertEqual(snapshot["reported_lane_count"], 18)
        self.assertEqual(len(calls), 6)
        self.assertEqual(len({str(row[2]) for row in calls}), 6)
        self.assertEqual(len(state["cells"]), 6)
        self.assertEqual(verify_snapshot(snapshot)["decision"], "pass")
        self.assertTrue(snapshot["paper_only"])
        self.assertFalse(snapshot["live_trading_authority"])

    def test_same_closed_bar_is_not_reprocessed(self):
        state, _ = run_matrix_cycle(
            manifest=self.manifest, state=self.state, state_root=self.root,
            source_sha=SOURCE_SHA, run_id="42", now_ms=NOW_MS,
            runner=_runner, verifier=_verifier, analyzer=_analyzer,
        )
        calls = []
        _, snapshot = run_matrix_cycle(
            manifest=self.manifest, state=state, state_root=self.root,
            source_sha=SOURCE_SHA, run_id="43", now_ms=NOW_MS,
            runner=lambda **kwargs: calls.append(kwargs),
            verifier=_verifier, analyzer=_analyzer,
        )
        self.assertEqual(calls, [])
        self.assertTrue(all(row["status"] == "SKIPPED_NO_NEW_BAR" for row in snapshot["cycle"]))
        self.assertEqual(snapshot["status"], "VERIFIED")
        self.assertEqual(snapshot["reported_lane_count"], 18)

    def test_one_failed_cell_is_fail_closed_without_stopping_other_cells(self):
        def runner(**kwargs):
            if kwargs["symbol"] == "ETHUSDT" and kwargs["timeframe"] == "hour1":
                raise OSError("public market data unavailable")
            return _runner(**kwargs)

        state, snapshot = run_matrix_cycle(
            manifest=self.manifest, state=self.state, state_root=self.root,
            source_sha=SOURCE_SHA, run_id="42", now_ms=NOW_MS,
            runner=runner, verifier=_verifier, analyzer=_analyzer,
        )
        self.assertEqual(snapshot["status"], "DEGRADED")
        self.assertEqual(snapshot["verified_cell_count"], 5)
        self.assertEqual(snapshot["blocked_cell_count"], 1)
        blocked = state["cells"]["ETHUSDT:hour1"]
        self.assertEqual(blocked["status"], "BLOCKED")
        self.assertEqual(blocked["last_completed_open_ms"], -1)
        self.assertNotIn("public market data unavailable", json.dumps(blocked))

    def test_analysis_authority_violation_blocks_cell(self):
        def bad_analysis(_root, _ledger):
            return {
                "paper_only": True,
                "live_trading_authority": True,
                "projection_digest": "d" * 64,
            }

        _, snapshot = run_matrix_cycle(
            manifest=self.manifest, state=self.state, state_root=self.root,
            source_sha=SOURCE_SHA, run_id="42", now_ms=NOW_MS,
            runner=_runner, verifier=_verifier, analyzer=bad_analysis,
        )
        self.assertEqual(snapshot["status"], "DEGRADED")
        self.assertEqual(snapshot["blocked_cell_count"], 6)

    def test_state_and_snapshot_tampering_are_rejected(self):
        state, snapshot = run_matrix_cycle(
            manifest=self.manifest, state=self.state, state_root=self.root,
            source_sha=SOURCE_SHA, run_id="42", now_ms=NOW_MS,
            runner=_runner, verifier=_verifier, analyzer=_analyzer,
        )
        state["live_trading_authority"] = True
        path = self.root / "matrix-state.json"
        path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaises(DemoStrategyMatrixError):
            load_state(path, self.manifest)
        snapshot["expected_lane_count"] = 19
        self.assertEqual(verify_snapshot(snapshot)["decision"], "reject")


if __name__ == "__main__":
    unittest.main()
