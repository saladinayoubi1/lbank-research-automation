from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from nexus_strategy_discovery_rotation import (
    StrategyDiscoveryRotationError,
    build_plan,
    commit_dispatch,
    empty_state,
    load_state,
)


def _controller():
    return {
        "schema": "nexus.strategy-discovery-controller.v1",
        "controller_verified": True,
        "paper_only": True,
        "live_trading_authority": False,
        "qualification_claimed": False,
        "search_stages": [{
            "stage": f"stage-{index}",
            "workflow": f".github/workflows/stage-{index}.yml",
            "experiment_id": f"experiment-{index}",
            "experiment_sha256": str(index) * 64,
            "status": "READY_FOR_RESEARCH_DISPATCH",
        } for index in range(3)],
    }


class StrategyDiscoveryRotationTests(unittest.TestCase):
    def test_rotation_advances_one_reviewed_stage_per_commit(self):
        state = empty_state()
        seen = []
        for run in range(4):
            plan = build_plan(_controller(), state)
            seen.append(plan["stage"])
            state = commit_dispatch(state, plan, source_sha="a" * 40, run_id=str(run + 1))
        self.assertEqual(seen, ["stage-0", "stage-1", "stage-2", "stage-0"])
        self.assertEqual(state["dispatch_count"], 4)
        self.assertFalse(state["automatic_strategy_promotion"])

    def test_unverified_controller_fails_closed(self):
        controller = _controller()
        controller["controller_verified"] = False
        with self.assertRaises(StrategyDiscoveryRotationError):
            build_plan(controller, empty_state())

    def test_plan_tamper_and_live_authority_are_rejected(self):
        state = empty_state()
        plan = build_plan(_controller(), state)
        plan["workflow"] = ".github/workflows/evil.yml"
        with self.assertRaises(StrategyDiscoveryRotationError):
            commit_dispatch(state, plan, source_sha="a" * 40, run_id="1")
        controller = _controller()
        controller["live_trading_authority"] = True
        with self.assertRaises(StrategyDiscoveryRotationError):
            build_plan(controller, state)

    def test_state_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            state = empty_state()
            state["qualification_authority"] = True
            path.write_text(json.dumps(state), encoding="utf-8")
            with self.assertRaises(StrategyDiscoveryRotationError):
                load_state(path)


if __name__ == "__main__":
    unittest.main()
