from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from nexus_strategy_discovery_rotation import (
    StrategyDiscoveryRotationError,
    build_plan,
    commit_dispatch,
    empty_state,
    load_state,
    _digest,
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
            "rotation_eligible": True,
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

    def test_legacy_validation_is_never_autonomous_fallback(self):
        controller = _controller()
        controller["search_stages"] = [
            {
                "stage": "legacy-v7",
                "workflow": ".github/workflows/legacy-v7.yml",
                "experiment_id": "legacy-v7",
                "experiment_sha256": "a" * 64,
                "status": "READY_FOR_RESEARCH_DISPATCH",
                "rotation_eligible": False,
            },
            {
                "stage": "modern-frontier",
                "workflow": ".github/workflows/modern-frontier.yml",
                "experiment_id": "modern-frontier",
                "experiment_sha256": "b" * 64,
                "status": "READY_FOR_RESEARCH_DISPATCH",
                "rotation_eligible": True,
            },
        ]
        plan = build_plan(controller, empty_state())
        self.assertEqual(plan["stage"], "modern-frontier")

        controller["search_stages"][1]["status"] = "BLOCKED"
        with self.assertRaisesRegex(StrategyDiscoveryRotationError, "legacy validation"):
            build_plan(controller, empty_state())

    def test_changed_frontier_fingerprint_is_new_research_not_legacy_replay(self):
        controller = _controller()
        controller["search_stages"] = [controller["search_stages"][0]]
        controller["search_stages"][0]["frontier_sha256"] = "f" * 64
        old_manifest = controller["search_stages"][0]["experiment_sha256"]
        feedback_core = {
            "schema_version": "nexus.strategy-discovery-feedback.v1",
            "exhausted_experiment_sha256": [],
            "outcomes": [{
                "experiment_sha256": old_manifest,
                "outcome": "completed_no_qualification",
                "workflow_conclusion": "success",
            }],
            "research_only": True,
            "paper_only": True,
            "qualification_authority": False,
            "automatic_strategy_promotion": False,
            "live_trading_authority": False,
        }
        feedback = {**feedback_core, "state_digest": _digest(feedback_core)}

        plan = build_plan(controller, empty_state(), feedback)
        self.assertEqual(plan["experiment_sha256"], "f" * 64)
        self.assertEqual(plan["manifest_sha256"], old_manifest)

        feedback_core["outcomes"].append({
            "experiment_sha256": "f" * 64,
            "outcome": "completed_no_qualification",
            "workflow_conclusion": "success",
        })
        feedback = {**feedback_core, "state_digest": _digest(feedback_core)}
        with self.assertRaisesRegex(StrategyDiscoveryRotationError, "no untested reviewed"):
            build_plan(controller, empty_state(), feedback)

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

    def test_cli_blocked_frontier_receipt_never_authorizes_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            controller = _controller()
            state = empty_state()
            feedback_core = {
                "schema_version": "nexus.strategy-discovery-feedback.v1",
                "exhausted_experiment_sha256": [],
                "outcomes": [
                    {
                        "experiment_sha256": row["experiment_sha256"],
                        "outcome": "no_candidate",
                        "workflow_conclusion": "success",
                    }
                    for row in controller["search_stages"]
                ],
                "research_only": True,
                "paper_only": True,
                "qualification_authority": False,
                "automatic_strategy_promotion": False,
                "live_trading_authority": False,
            }
            feedback = {**feedback_core, "state_digest": _digest(feedback_core)}
            for name, doc in (
                ("controller.json", controller),
                ("state.json", state),
                ("feedback.json", feedback),
            ):
                (root / name).write_text(json.dumps(doc), encoding="utf-8")
            args = [
                sys.executable, str(Path(__file__).resolve().parents[1] /
                                    "nexus_strategy_discovery_rotation.py"),
                "plan", "--controller-status", str(root / "controller.json"),
                "--state", str(root / "state.json"),
                "--feedback-state", str(root / "feedback.json"),
                "--output", str(root / "plan.json"),
            ]
            denied = subprocess.run(args, capture_output=True, text=True, timeout=20)
            self.assertNotEqual(denied.returncode, 0)
            self.assertFalse((root / "plan.json").exists())
            allowed = subprocess.run(
                [*args, "--blocked-receipt-on-exhaustion"],
                capture_output=True, text=True, timeout=20,
            )
            self.assertEqual(allowed.returncode, 0, allowed.stderr)
            receipt = json.loads((root / "plan.json").read_text())
            self.assertEqual(receipt["status"], "NEEDS_NEW_REVIEWED_MECHANISM")
            self.assertFalse(receipt["dispatch_allowed"])
            self.assertFalse(receipt["live_trading_authority"])
            self.assertNotIn("workflow", receipt)
            with self.assertRaises(StrategyDiscoveryRotationError):
                commit_dispatch(state, receipt, source_sha="a" * 40, run_id="1")
            feedback["state_digest"] = "f" * 64
            (root / "feedback.json").write_text(json.dumps(feedback))
            tampered = subprocess.run(
                [*args, "--blocked-receipt-on-exhaustion"],
                capture_output=True, text=True, timeout=20,
            )
            self.assertNotEqual(tampered.returncode, 0)

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
