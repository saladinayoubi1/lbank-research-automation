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


def _reconciliation_fixture(root):
    from nexus_strategy_discovery_feedback import empty_state as empty_feedback, _digest as feedback_digest

    controller = _controller()
    state = empty_state()
    for index in range(3):
        state = commit_dispatch(
            state, build_plan(controller, state), source_sha="a" * 40,
            run_id=str(index + 1),
        )
    feedback_core = {k: v for k, v in empty_feedback().items() if k != "state_digest"}
    feedback_core["processed_run_ids"] = ["1", "2"]
    feedback_core["outcomes"] = [
        {"run_id": str(index + 1), "stage": f"stage-{index}",
         "experiment_sha256": controller["search_stages"][index]["experiment_sha256"],
         "outcome": "no_candidate", "workflow_conclusion": "success"}
        for index in range(2)
    ]
    prior_feedback = {**feedback_core, "state_digest": feedback_digest(feedback_core)}
    pending = {"research_run_id": "3", "stage": "stage-2", "source_sha": "a" * 40,
               "experiment_sha256": controller["search_stages"][2]["experiment_sha256"]}
    # Run IDs and source SHA are synthetic fixtures, never production receipts.
    for name, value in (
        ("controller.json", controller), ("rotation-state.json", state),
        ("feedback-state.json", prior_feedback), ("last-research-run.json", pending),
        ("run.json", {"databaseId": 3, "status": "completed", "conclusion": "success",
                      "headSha": "a" * 40}),
    ):
        (root / name).write_text(json.dumps(value), encoding="utf-8")
    artifacts = root / "artifacts"
    artifacts.mkdir()
    (artifacts / "outcome.json").write_text(
        json.dumps({"decision": "continue_research_no_promotion"}), encoding="utf-8",
    )
    repo = Path(__file__).resolve().parents[1]
    workflow = (repo / ".github/workflows/nexus_strategy_discovery_rotation.yml").read_text()
    reconcile_step = workflow.split("Reconcile previously dispatched Research outcome", 1)[1].split(
        "Verify discovery surface and select one stage", 1
    )[0]
    reconcile = [sys.executable, str(repo / "nexus_strategy_discovery_feedback.py"),
                 "--state", str(root / "feedback-state.json"),
                 "--run-json", str(root / "run.json"), "--artifact-root", str(artifacts),
                 "--stage", pending["stage"], "--experiment-sha256", pending["experiment_sha256"],
                 "--expected-source-sha", pending["source_sha"],
                 "--output", str(root / "feedback-state.json")]
    # Exercise the actual workflow caller's opt-in, including the old unguarded path.
    if "--require-feedback-state" in reconcile_step:
        reconcile.append("--require-feedback-state")
    plan = [sys.executable, str(repo / "nexus_strategy_discovery_rotation.py"), "plan",
            "--controller-status", str(root / "controller.json"),
            "--state", str(root / "rotation-state.json"),
            "--feedback-state", str(root / "feedback-state.json"),
            "--require-feedback-state", "--blocked-receipt-on-exhaustion",
            "--output", str(root / "plan.json")]
    return reconcile, plan


class StrategyDiscoveryRotationTests(unittest.TestCase):
    def test_pending_receipt_cannot_rebuild_lost_feedback_before_guarded_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reconcile, plan = _reconciliation_fixture(root)
            (root / "feedback-state.json").unlink()
            original_state = (root / "rotation-state.json").read_bytes()
            original_receipt = (root / "last-research-run.json").read_bytes()
            result = subprocess.run(reconcile, capture_output=True, text=True, timeout=20)
            self.assertNotEqual(result.returncode, 0, "reconciliation must not bootstrap lost history")
            self.assertIn("verified prior feedback required", result.stderr)
            self.assertFalse((root / "feedback-state.json").exists())
            self.assertEqual((root / "rotation-state.json").read_bytes(), original_state)
            self.assertEqual((root / "last-research-run.json").read_bytes(), original_receipt)
            result = subprocess.run(plan, capture_output=True, text=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((root / "plan.json").exists())

    def test_pending_receipt_preserves_prior_terminal_feedback_and_blocks_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reconcile, plan = _reconciliation_fixture(root)
            original_state = (root / "rotation-state.json").read_bytes()
            result = subprocess.run(reconcile, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            feedback = json.loads((root / "feedback-state.json").read_text())
            self.assertEqual(feedback["processed_run_ids"], ["1", "2", "3"])
            self.assertEqual(len(feedback["outcomes"]), 3)
            result = subprocess.run(plan, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads((root / "plan.json").read_text())
            self.assertEqual(receipt["status"], "NEEDS_NEW_REVIEWED_MECHANISM")
            self.assertFalse(receipt["dispatch_allowed"])
            self.assertNotIn("workflow", receipt)
            self.assertEqual((root / "rotation-state.json").read_bytes(), original_state)

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

    def test_autonomous_plan_must_not_redispatch_when_feedback_disappears(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "controller.json").write_text(
                json.dumps(_controller()), encoding="utf-8"
            )
            (root / "state.json").write_text(
                json.dumps(empty_state()), encoding="utf-8"
            )
            command = [
                sys.executable,
                str(Path(__file__).resolve().parents[1] /
                    "nexus_strategy_discovery_rotation.py"),
                "plan",
                "--controller-status", str(root / "controller.json"),
                "--state", str(root / "state.json"),
                "--feedback-state", str(root / "lost-feedback.json"),
                "--require-feedback-state",
                "--blocked-receipt-on-exhaustion",
                "--output", str(root / "plan.json"),
            ]
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=20
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("verified prior feedback required", result.stderr)
            self.assertFalse((root / "plan.json").exists())
            (root / "lost-feedback.json").write_text(
                json.dumps({"state_digest": "f" * 64}), encoding="utf-8"
            )
            tampered = subprocess.run(
                command, capture_output=True, text=True, timeout=20
            )
            self.assertNotEqual(tampered.returncode, 0)
            self.assertFalse((root / "plan.json").exists())

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
